from config import Config
from common.Clients.Fishbowl.FishbowlSession import FishbowlSession
from common.Clients.Intuiflow.IntuiflowApi import (
    get_open_wo, get_open_rope_items, get_bom_names,
    get_closed_wo, get_closed_rope_items,
)
from common.Utils.Logging import SessionLog
from common.Utils.Utils import load_query
from datetime import datetime, timedelta

# ── Private helpers ───────────────────────────────────────────────────────────
def _is_valid(val):
    return val and str(val) not in ("", "null", "undefined", "None", "NA")

def _validate_order(order: dict) -> dict:
    """Replaces null/empty/zero-qty values with "NA". Modifies the order in place. """
    for key in order:
        val = order[key]
        if key == "Qty" and val in (0, "0"):
            order[key] = "NA"
        elif not _is_valid(val):
            order[key] = "NA"
    return order

def _build_timestamp() -> str:
    """Builds an ISO-like timestamp string to append to date fields sent to Fishbowl
    (e.g. "T14:30:22.123-0700"). Computed once per run."""
    now = datetime.now().astimezone()
    ms  = now.microsecond // 1000
    return now.strftime("T%H:%M:%S.") + f"{ms:03d}" + now.strftime("%z")

def _build_update_payload(order: dict, timestamp: str, is_test_db: bool) -> dict:
    """Builds the Fishbowl Update MO POST request payload from a merged order dict."""
    cf_routing_id = (Config.FISHBOWL_TEST_CF_MO_ROUTING_NAME_ID if is_test_db else Config.FISHBOWL_PROD_CF_MO_ROUTING_NAME_ID)
    cf_date_id    = (Config.FISHBOWL_TEST_CF_MO_DATE_SCHEDULED_ID if is_test_db else Config.FISHBOWL_PROD_CF_MO_DATE_SCHEDULED_ID)
    routing_name  = str(order.get("RoutingName", "")).replace('"', '\\"')
    qty_val       = order.get("Qty")
    qty           = float(qty_val) if qty_val not in (None, "NA") else 0.0

    return {
        "id":            int(order["MoId"]),
        "number":        str(order["MoNumber"]),
        "note":          "Intuiflow API Import",
        "status":        "Entered",
        "dateScheduled": str(order["PromiseDate"]) + timestamp,
        "configurations": [{
            "bom":                  {"id": int(order["BomId"])},
            "quantity":             qty,
            "dateScheduled":        str(order["PromiseDate"])  + timestamp,
            "dateScheduledToStart": str(order["StartDate"])    + timestamp,
            "note":                 str(order.get("Notes", ""))
        }],
        "customFields": [
            {"id": cf_routing_id, "value": routing_name},
            {"id": cf_date_id,    "value": str(order["DateScheduled"]) + " 00:00:00"}
        ]
    }

# ── Public entry point ────────────────────────────────────────────────────────

class UpdateWorkOrders:
    ''' Handles the operations required to sync current Intuiflow order 
    configurations (source of truth) with the open orders in Fishbowl. '''

    def __init__(self):
        seven_days_ago = datetime.now() - timedelta(days=7)
        self._date_7_ago = f"{seven_days_ago.month}-{seven_days_ago.day}-{seven_days_ago.year}"
        self.log = SessionLog()
        # Intuiflow configs
        self._location = Config.INTUIFLOW_ROPE_ITEMS_LOCATION
        self._is_intuiflow_test_db = Config.INTUIFLOW_USE_TEST
        # Fishbowl configs
        self._is_fb_test_db = Config.USE_TEST_DB
        self._query_wo_boms = load_query("OpenWOBoMs")
        self._query_wo_configs = load_query("OpenWOConfigs")
        # shared data
        self._open_wos = []
        self._closed_wos = []
        self._all_wos = []
        self._orders_to_unissue = []
        self._orders_to_update = []

    def _get_intuiflow_open_wos(self) -> None:
        ''' Retrieves open work orders from Intuiflow, normalizes them, hydrates them
        with current BoM and start date info, then saves them to the class instance. '''
        try:
            # API call to Intuiflow
            resp = get_open_wo(self._is_intuiflow_test_db)    # API calls raise Exception on failure.
            orders = resp["data"]

            self.log.log("_get_intuiflow_open_wos", "Successfully queried open work orders in Intuiflow.")

            # validate and normalize the fields
            processed_open_orders = []
            for order in (orders or []):
                parsed = {
                    "OrderNum":      order.get("OrderNumber"),
                    "RoutingName":   order.get("RoutingName"),
                    "Qty":           order.get("OrderQuantity"),
                    "Notes":         order.get("ProductionNotes"),
                    "BOMName":       None,
                    "BomId":         None,
                    "Status":        "Open",
                    "PromiseDate":   order["PromiseDate"][:10]    if order.get("PromiseDate")    else None,
                    "DateScheduled": order["EndRequestDate"][:10] if order.get("EndRequestDate") else None,
                }

                # replace invalid fields with 'NA' then capture the normalized order configs
                validated = _validate_order(parsed)
                processed_open_orders.append(validated)

            self._open_wos = processed_open_orders
            if not processed_open_orders:
                self.log.log("_get_intuiflow_open_wos", "Warning: No valid open orders detected. Will check for closed orders.")
            else:
                self.log.log("_get_intuiflow_open_wos", f"Successfully parsed {len(processed_open_orders)} work orders.")
                # hydrate the open work orders with start dates and BoM info
                self._get_intuiflow_open_rope_items()
                self._get_intuiflow_open_order_boms()
        except Exception as e:
            self.log.log("_get_intuiflow_open_wos", f"Ending the API call stack due to error: {e}", True)
            raise
    
    def _get_intuiflow_open_rope_items(self) -> None:
        ''' Uses operations/rope-items tied to the order to determine order start date, modifying 
        self._open_wos directly '''
        try:
            # API call to Intuiflow
            resp = get_open_rope_items(self._location, self._is_intuiflow_test_db)    # API calls raise Exception on failure.
            rope_items = resp["data"] or []
            if not rope_items:
                self.log.log("_get_intuiflow_open_rope_items", "Warning: no data returned in the open rope items call.", True)
            else:
                self.log.log("_get_intuiflow_open_rope_items", "Successfully queried open rope-items in Intuiflow.")

            # Pre-group rope items by order number for O(n+m) lookup
            rope_by_order = {}
            for op in rope_items:
                order_num = op.get("OrderNumber")
                if order_num:
                    rope_by_order.setdefault(order_num, []).append(op)

            # add scheduled start date to each of the orders based on their first operation/rope-item
            updated_start_dates = 0
            for order in self._open_wos:
                matched_ops = rope_by_order.get(order["OrderNum"], [])

                # find the first operations out of the matched operations
                first_op = None
                for op in matched_ops:
                    if not first_op:
                        first_op = op
                    elif op.get("OperationSequenceNumber") < first_op.get("OperationSequenceNumber"):
                        first_op = op

                # no rope items for this order — start date cannot be determined
                if not first_op:
                    self.log.log("_get_intuiflow_open_rope_items", 
                                 f"Warning: No rope items for order {order['OrderNum']}. Start date will not be updated.", True)
                    order["StartDate"] = "NA"
                    continue

                # determine the field to use for the order start date
                promise_date = order.get("PromiseDate", None)
                sso = first_op.get("ScheduledStartOperation") if _is_valid(first_op.get("ScheduledStartOperation")) else None
                srb = first_op.get("ScheduledReceiptAtBuffer") if _is_valid(first_op.get("ScheduledReceiptAtBuffer")) else None

                # order start date set to first operations scheduled start its valid and if its earlier than the order's promise_date
                # start date cannot be earlier than the order's promise date in Fishbowl
                if sso and promise_date and sso[:10] <= promise_date:
                    updated_start_dates += 1
                    order["StartDate"] = sso[:10]
                # same methedology as above except using a fallback field from the rope item
                elif srb and promise_date and srb[:10] <= promise_date:
                    updated_start_dates += 1
                    order["StartDate"] = srb[:10]
                else:
                    self.log.log("_get_intuiflow_open_rope_items", 
                                 f"Warning: this order will not have its start date updated: {order['OrderNum']}", True)
                    order["StartDate"] = "NA"

            self.log.log("_get_intuiflow_open_rope_items", 
                         f"Successfully processed start dates on {updated_start_dates} of {len(self._open_wos)} open work orders.")
        except Exception as e:
            self.log.log("_get_intuiflow_open_rope_items", f"Ending the API call stack due to error: {e}", True)
            raise

    def _get_intuiflow_open_order_boms(self) -> None:
        ''' Queries BoMs tied to open orders in Intuiflow to modify open_wos in place by setting 
        the BOMName '''
        try:
            # API call to Intuiflow
            resp = get_bom_names(self._is_intuiflow_test_db)    # API calls raise Exception on failure.
            bom_data = resp["data"] or []
            if not bom_data:
                self.log.log("_get_intuiflow_open_order_boms", "Warning: no data returned in the open order BoMs call.", True)
            else:
                self.log.log("_get_intuiflow_open_order_boms", "Successfully queried open order BoM names in Intuiflow.")

            # Pre-group BoMs by order number for O(n) lookup, then match to open orders
            matched_boms = 0
            bom_by_order = {b.get("OrderNumber"): b for b in bom_data if b.get("OrderNumber")}
            for order in self._open_wos:
                match = bom_by_order.get(order["OrderNum"])
                if match:
                    order["BOMName"] = match.get("BOMName")
                    matched_boms += 1
                else:
                    self.log.log("_get_intuiflow_open_order_boms", 
                                 f"Warning: No BoM found for order {order['OrderNum']}. BoM won't be updated.", True)

            self.log.log("_get_intuiflow_open_order_boms", 
                         f"Successfully processed BoM names for {matched_boms} of {len(self._open_wos)} open work orders.")
        except Exception as e:
            self.log.log("_get_intuiflow_open_order_boms", f"Ending the API call stack due to error: {e}", True)
            raise

    def _get_intuiflow_closed_wos(self) -> None:
        ''' Retrieves closed work orders from Intuiflow, normalizes them, hydrates them
        with current start date info, then saves them to the class instance. '''
        try:
            # API call to Intuiflow
            resp = get_closed_wo(self._date_7_ago, self._is_intuiflow_test_db)    # API calls raise Exception on failure.
            orders = resp["data"]

            self.log.log("_get_intuiflow_closed_wos", "Successfully queried closed orders in Intuiflow.")

            # validate and normalize the fields
            processed_closed_orders = []
            for order in (orders or []):
                parsed = {
                    "OrderNum":      order.get("OrderNumber"),
                    "RoutingName":   order.get("RoutingName"),
                    "Qty":           order.get("OrderQuantity"),
                    "Notes":         order.get("ProductionNotes"),
                    "BOMName":       None,
                    "BomId":         None,
                    "Status":        "Closed",
                    "PromiseDate":   order["PromiseDate"][:10]    if order.get("PromiseDate")    else None,
                    "DateScheduled": order["EndRequestDate"][:10] if order.get("EndRequestDate") else None,
                }

                # replace invalid fields with 'NA' then capture the normalized order configs
                validated = _validate_order(parsed)
                processed_closed_orders.append(validated)

            self._closed_wos = processed_closed_orders
            if not processed_closed_orders:
                # no need to check for rope items if no orders exist
                self.log.log("_get_intuiflow_closed_wos", f"Warning: No valid closed orders detected since {self._date_7_ago}.", True)
            else:
                self.log.log("_get_intuiflow_closed_wos", f"Successfully retrieved {len(processed_closed_orders)} work orders.")
                # Hydrate closed orders with start dates (intentionally not modifying BoMs on closed orders)
                self._get_intuiflow_closed_rope_items()
        except Exception as e:
            self.log.log("_get_intuiflow_closed_wos", f"Ending the API call stack due to error: {e}", True)
            raise

    def _get_intuiflow_closed_rope_items(self) -> None:
        ''' Uses operations/rope-items tied to the order to determine order start date, modifying 
        self._closed_wos directly '''
        try:
            # API call to Intuiflow
            resp = get_closed_rope_items(self._date_7_ago, self._location, self._is_intuiflow_test_db)    # API calls raise Exception on failure.
            rope_items = resp["data"] or []
            if not rope_items:
                self.log.log("_get_intuiflow_closed_rope_items", "Warning: no data returned in the closed rope items call.", True)
            else:
                self.log.log("_get_intuiflow_closed_rope_items", "Successfully queried closed order rope-items in Intuiflow.")

            # Pre-group rope items by order number for O(n+m) lookup
            rope_by_order = {}
            for op in rope_items:
                order_num = op.get("OrderNumber")
                if order_num:
                    rope_by_order.setdefault(order_num, []).append(op)

            # add scheduled start date to each of the orders based on their first operation/rope-item
            updated_start_dates = 0
            for order in self._closed_wos:
                matched_ops = rope_by_order.get(order["OrderNum"], [])

                # find the first operations out of the matched operations
                first_op = None
                for op in matched_ops:
                    if not first_op:
                        first_op = op
                    elif op.get("OperationSequenceNumber") < first_op.get("OperationSequenceNumber"):
                        first_op = op

                # no rope items for this order — start date cannot be determined
                if not first_op:
                    order["StartDate"] = "NA"
                    continue

                # determine the field to use for the order start date
                promise_date = order.get("PromiseDate", None)
                sso = first_op.get("ScheduledStartOperation") if _is_valid(first_op.get("ScheduledStartOperation")) else None
                srb = first_op.get("ScheduledReceiptAtBuffer") if _is_valid(first_op.get("ScheduledReceiptAtBuffer")) else None

                # order start date set to first operations scheduled start its valid and if its earlier than the order's promise_date
                # start date cannot be earlier than the order's promise date in Fishbowl
                if sso and promise_date and sso[:10] <= promise_date:
                    order["StartDate"] = sso[:10]
                    updated_start_dates += 1
                # same methedology as above except using a fallback field from the rope item
                elif srb and promise_date and srb[:10] <= promise_date:
                    order["StartDate"] = srb[:10]
                    updated_start_dates += 1
                else:
                    self.log.log("_get_intuiflow_closed_rope_items", 
                                 f"Warning: this order will not have its start date updated: {order['OrderNum']}", True)
                    order["StartDate"] = "NA"

            self.log.log("_get_intuiflow_closed_rope_items", 
                         f"Successfully processed start dates on {updated_start_dates} of {len(self._closed_wos)} closed work orders.")
        except Exception as e:
            self.log.log("_get_intuiflow_closed_rope_items", f"Ending the API call stack due to error: {e}", True)
            raise

    def _get_fishbowl_bom_info(self) -> None:
        ''' Looks up BoM IDs in Fishbowl based on BoM Name from the Intuiflow orders,
        then adds the BoM ID to the order object in place. '''
        try:
            fb = None       # initializing for the finally block in case fatal login error.
            # Fishbowl login and login validation
            fb = FishbowlSession(self._is_fb_test_db)
            if not fb.is_logged_in():
                raise Exception(f"Failed to login to Fishbowl after {fb._login_attemps} attempts.")
            
            self.log.log("_get_fishbowl_bom_info", "Successfully logged into Fishbowl.")

            # resolve BomId for each order by BOMName & add the BoM ID to each order in self._all_wos
            bom_rows = fb.query(self._query_wo_boms)["data"] or []      # Raises exception on api call failure
            if not bom_rows:
                raise Exception("The FB BoM query response has no records.")
            
            self.log.log("_get_fishbowl_bom_info", "Successfully queried BoM IDs in Fishbowl.")

            bom_by_name = {r.get("BOMName"): r for r in bom_rows if r.get("BOMName")}
            bom_match_count = 0
            for order in self._all_wos:
                bom_name = order.get("BOMName")
                if bom_name and bom_name != "NA":
                    match = bom_by_name.get(bom_name)
                    if match:
                        order["BomId"] = match.get("BomId")
                        bom_match_count += 1
                    else:
                        self.log.log("_get_fishbowl_bom_info", 
                                     f"Warning: No BomId found for BoM name: '{bom_name}' (order {order['OrderNum']}). This field won't be updated.", True)
                        
            self.log.log("_get_fishbowl_bom_info", f"Successfully processed BoM IDs for {bom_match_count} of {len(self._open_wos)} work orders.")
        except Exception as e:
            self.log.log("_get_fishbowl_bom_info", 
                         f"Fatal error trying to retrieve required Fishbowl BoM information for the update: {e}", True)
            raise
        finally:
            if fb:
                fb.logout()

    def _get_fishbowl_wo_configs(self) -> None:
        ''' Updates and hydrates Intuiflow order config data with current Fishbowl data before 
        importing the updated order to Fishbowl. Populates self._orders_to_update and 
        self._orders_to_unissue'''
        try:
            fb = None       # initializing for the finally block in case fatal login error.
            fb = FishbowlSession(self._is_fb_test_db)
            if not fb.is_logged_in():
                raise Exception(f"Failed to login to Fishbowl after {fb._login_attemps} attempts.")
            
            self.log.log("_get_fishbowl_wo_configs", "Successfully logged into Fishbowl.")

            configs = fb.query(self._query_wo_configs)["data"] or []      # Raises exception on api call failure
            if not configs:
                raise Exception("The FB WO configs query response has no records.")
            
            self.log.log("_get_fishbowl_wo_configs", "Successfully queried work order configs in Fishbowl.")

            # resolve current MO configs; diff vs Intuiflow data - (uses existing BoM ID if _get_fishbowl_bom_info fails)
            orders_to_unissue = self._orders_to_unissue
            orders_to_update  = self._orders_to_update
            configs_by_order_num = {r.get("OrderNum"): r for r in configs if r.get("OrderNum")}
            no_update_count = 0
            update_count = 0
            already_closed_count = 0
            for order in self._all_wos:
                # match the FB MO to the current order to compare configs
                matched_config = configs_by_order_num.get(order["OrderNum"])

                # no matching order edge case
                if matched_config is None:
                    if order["Status"] == "Open":
                        no_update_count += 1
                        self.log.log("_get_fishbowl_wo_configs", 
                                     f"Warning: No Fishbowl MO match for open order {order['OrderNum']}. Match expected.", True)
                    else:
                        already_closed_count += 1
                    continue

                # Overwrite invalid Intuiflow order data with valid Fishbowl order data.
                compare_skip = frozenset({"Status", "OrderNum"})
                needs_update_flag = False
                for key in order:
                    if key in compare_skip:
                        continue
                    if not _is_valid(order[key]) and _is_valid(matched_config.get(key)):
                        order[key] = matched_config.get(key)
                    if order[key] != matched_config.get(key):
                        needs_update_flag = True

                # hydrate order data with MoID, MoNumber, MoStatus from Fishbowl.
                order["MoId"]     = matched_config.get("MoId")
                order["MoNumber"] = matched_config.get("MoNumber")
                order["MoStatus"] = matched_config.get("MoStatus")

                # No differences — no need to update
                if not needs_update_flag:
                    no_update_count += 1
                    continue
                # these values are required for updates, skip if missing or invalid
                if not order.get("MoId") or not order.get("MoNumber"):
                    no_update_count += 1
                    self.log.log("_get_fishbowl_wo_configs", 
                                 f"Warning: Missing MoId/MoNumber for order {order['OrderNum']}. Skipping update.", True)
                    continue
                if not _is_valid(order.get("BomId")):
                    no_update_count += 1
                    self.log.log("_get_fishbowl_wo_configs", 
                                 f"Warning: Missing BomId for order {order['OrderNum']}. Skipping update.", True)
                    continue

                # add the order to the processing lists
                if order.get("MoStatus") == "Issued":
                    update_count += 1
                    orders_to_unissue.append(order)
                elif order.get("MoStatus") == "Entered":
                    update_count += 1
                    orders_to_update.append(order)
                else:
                    no_update_count += 1
                    self.log.log("_get_fishbowl_wo_configs", 
                                 f"Warning: Unknown MO status for {order['OrderNum']}. Skipping update.", True)
                    
            self.log.log("_get_fishbowl_wo_configs", 
                         f"Successfully staged {update_count} for updates. \
                         {no_update_count} were invalid or had no changes. \
                         {already_closed_count} were already closed in Fishbowl.")
        except Exception as e:
            self.log.log("_get_fishbowl_wo_configs", f"Failed to retrieve Fishbowl WO/BoM info: {e}", True)
            raise
        finally:
            if fb:
                fb.logout()
    
    def _unissue_wos(self) -> None:
        ''' Unissues Fishbowl work orders one at a time. Orders must be unissued to 
        make changes to them. Requires self._orders_to_unissue be populated first. '''
        try:
            fb = None       # initializing for the finally block in case fatal login error.
            fb = FishbowlSession(self._is_fb_test_db)
            if not fb.is_logged_in():
                raise Exception(f"Failed to login to Fishbowl after {fb._login_attemps} login attempts.")
            
            self.log.log("_unissue_wos", "Successfully logged into Fishbowl.")

            unissued_orders = 0
            for order in self._orders_to_unissue:
                try:
                    fb.unissue_mo(int(order["MoId"]))       # raises an exception on call failure
                    self._orders_to_update.append(order)    # ready to be updated now that its unissued
                    unissued_orders += 1
                except Exception as e:
                    self.log.log("_unissue_wos", 
                                 f"Unable to unissue {order.get('OrderNum')}. This order will not be updated. ", True)
                    
            self.log.log("_unissue_wos", 
                         f"Successfully unissued {unissued_orders} of {len(self._orders_to_unissue)} work orders in Fishbowl.")
        except Exception as e:
            self.log.log("_unissue_wos", f"Warning: Failed to unissue MO in Fishbowl: {e}", True)
            raise
        finally:
            if fb:
                fb.logout()

    def _update_reissue_wos(self) -> None:
        ''' Final loop that updates then reissues the orders inside of Fishbowl. Requires 
        self._orders_to_update be populated first. '''
        try:
            fb = None       # initializing for the finally block in case fatal login error.
            fb = FishbowlSession(self._is_fb_test_db)
            if not fb.is_logged_in():
                raise Exception(f"Failed to login to Fishbowl after {fb._login_attemps} login attempts.")
            
            self.log.log("_update_reissue_wos", "Successfully logged into Fishbowl.")
            
            # Update → Issue loop
            timestamp = _build_timestamp()          # this should be updated at some point to be a real timestamp from Intuiflow
            orders_updated = 0
            orders_issued = 0
            for order in self._orders_to_update:
                order_id = int(order["MoId"])
                try:
                    update_payload = _build_update_payload(order, timestamp, self._is_fb_test_db)
                    fb.update_mo(order_id, update_payload)      # raises exception on API call failure
                    orders_updated += 1
                except Exception as e:
                    self.log.log("_update_reissue_wos", 
                                 f"Error: Failed to update MO {order.get('MoNumber')}, will attempt to re-issue: {e}", True)
                try:
                    fb.issue_mo(order_id)                       # raises exception on API call failure
                    orders_issued += 1
                except Exception as e:
                    self.log.log("_update_reissue_wos", 
                                 f"Error: Failed to re-issue MO {order.get('MoNumber')}: {e}", True)

            self.log.log("_update_reissue_wos", 
                         f"Successfully updated {orders_updated} and issued {orders_issued} of {len(self._orders_to_update)} total Fishbowl work orders. ")
        except Exception as e:
            self.log.log("_update_reissue_wos", f"Warning: Failed to update/issue some or all of the MOs in Fishbowl: {e}", True)
            raise
        finally:
            if fb:
                fb.logout()


    def auto_run(self) -> SessionLog:
        ''' Auto runs the entire pipeline in the intended order. '''
        try:
            # get open and closed intuiflow order info and combine into 1 list
            self._get_intuiflow_open_wos()
            self._get_intuiflow_closed_wos()
            self._all_wos = self._open_wos + self._closed_wos
            # hydrate the order info with Fishbowl data where needed
            self._get_fishbowl_bom_info()
            self._get_fishbowl_wo_configs()
            # unissue FB orders, update them, then re-issue them
            self._unissue_wos()
            self._update_reissue_wos()
        except Exception as e:
            self.log.log("auto_run", f"ERROR: Unable to complete work order update: {e}", True)
        finally:
            return self.log
        