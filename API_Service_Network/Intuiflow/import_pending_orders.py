from config import Config
from common.Clients.Fishbowl.FishbowlSession import FishbowlSession
from common.Clients.Intuiflow.IntuiflowApi import (
    get_pending_orders, get_bom_info, get_routing_info, committ_pending_orders,
)
from common.Utils.Logging import SessionLog
from common.Utils.Utils import load_query
from datetime import datetime

# ── Private helpers ───────────────────────────────────────────────────────────

def _is_valid(val):
    return val and str(val) not in ("", "null", "undefined", "None", "NA")

def _build_timestamp() -> str:
    """Builds an ISO-like timestamp string to append to date fields sent to Fishbowl
    (e.g. 'T14:30:22.123-0700'). Computed once per run."""
    now = datetime.now().astimezone()
    ms  = now.microsecond // 1000
    return now.strftime("T%H:%M:%S.") + f"{ms:03d}" + now.strftime("%z")

def _build_mo_payload(order: dict, timestamp: str, is_test_db: bool) -> dict:
    """Builds the Fishbowl Create MO POST payload from an enriched WO dict."""
    cf_link_id    = Config.FISHBOWL_TEST_CF_MO_LINK_CODE_ID if is_test_db else Config.FISHBOWL_PROD_CF_MO_LINK_CODE_ID
    cf_routing_id = Config.FISHBOWL_TEST_CF_MO_ROUTING_NAME_ID if is_test_db else Config.FISHBOWL_PROD_CF_MO_ROUTING_NAME_ID
    cf_date_id    = Config.FISHBOWL_TEST_CF_MO_DATE_SCHEDULED_ID if is_test_db else Config.FISHBOWL_PROD_CF_MO_DATE_SCHEDULED_ID

    return {
        "status":        "Issued",
        "note":          "Intuiflow API Imported Order",
        "dateScheduled": str(order["PromiseDate"]) + timestamp,
        "configurations": [{
            "bom":                  {"id": int(order["BomId"])},
            "quantity":             float(order["Qty"]),
            "dateScheduled":        str(order["PromiseDate"]) + timestamp,
            "dateScheduledToStart": str(order["StartDate"]) + timestamp,
            "note":                 "Intuiflow Order",
            "priority":             "3-Normal",
        }],
        "customFields": [
            {
                "id": cf_link_id,    
                "value": str(order["OrderId"])
            },
            {
                "id": cf_routing_id, 
                "value": str(order.get("RoutingName", "")).replace('"', '\\"')
            },
            {
                "id": cf_date_id,    
                "value": str(order["DateScheduled"]) + " 00:00:00"   # date field format
            },
        ],
    }

def _build_outsourced_po_payload(order: dict, timestamp: str, today_ts: str, is_test_db: bool) -> dict:
    """Builds the Fishbowl Create Outsourced PO POST payload from an enriched PO dict."""
    cf_link_id = Config.FISHBOWL_TEST_CF_PO_LINK_CODE_ID if is_test_db else Config.FISHBOWL_PROD_CF_PO_LINK_CODE_ID

    return {
        "status": "Issued",
        "vendor": {
            "id": int(order["VendorId"])
            },
        "issuedByUser": {
            "username": "Intuiflow", 
            "dateLastModified": today_ts
            },
        "dateScheduled": str(order["DateScheduled"]) + timestamp,
        "note": "Intuiflow API Imported Order",
        "poItems": [
            {
            "part": {
                "id": int(order["ChildPartId"]), 
                "description": str(order["PartDescription"]).replace('"', '\\"')
                },
            "outsourcedPart": {
                "id": int(order["PartId"])
                },
            "type": {
                "id": 30
                },
            "quantity": float(order["Qty"]),
            "totalCost": 0,
            "dateScheduled": str(order["DateScheduled"]) + timestamp,
            "note": "Intuiflow API Imported Order",
            "customFields": [
                    {
                        "id": cf_link_id, 
                        "value": str(order["OrderId"])
                    }
                ],
            }
        ],
    }

def _build_purchase_po_payload(order: dict, timestamp: str, today_ts: str, is_test_db: bool) -> dict:
    """Builds the Fishbowl Create Purchase PO POST payload from an enriched PO dict."""
    cf_link_id = Config.FISHBOWL_TEST_CF_PO_LINK_CODE_ID if is_test_db else Config.FISHBOWL_PROD_CF_PO_LINK_CODE_ID

    return {
        "status":        "Issued",
        "vendor":        {
            "id": int(order["VendorId"])
            },
        "issuedByUser":  {
            "username": "Intuiflow", 
            "dateLastModified": today_ts
            },
        "dateScheduled": str(order["DateScheduled"]) + timestamp,
        "note":          "Intuiflow API Imported Order",
        "poItems": [
            {
            "part": {
                "id": int(order["PartId"]), 
                "description": str(order["PartDescription"]).replace('"', '\\"')
                },
            "type": {
                "id": 10
                },
            "quantity":      float(order["Qty"]),
            "totalCost":     0,
            "dateScheduled": str(order["DateScheduled"]) + timestamp,
            "note":          "Intuiflow API Imported Order",
            "customFields":  [
                    {
                    "id": cf_link_id, 
                    "value": str(order["OrderId"])
                    }
                ],
            }
        ],
    }

# ── Public entry point ────────────────────────────────────────────────────────

class ImportPendingOrders:
    ''' Fetches approved Intuiflow pending orders, imports them into Fishbowl as MOs
    and POs, then commits the successfully imported orders back in Intuiflow. '''

    def __init__(self):
        self.log = SessionLog()
        # Intuiflow configs
        self._is_intuiflow_test = Config.INTUIFLOW_USE_TEST
        # Fishbowl configs
        self._is_fb_test_db       = Config.USE_TEST_DB
        self._query_bom_id        = load_query("BoMID")
        self._query_part_info     = load_query("PartInfo")
        self._query_part_vendor   = load_query("PartVendor")
        # shared data
        self._work_orders:    list[dict] = []   # OrderType == 2
        self._purchase_orders: list[dict] = []  # OrderType == 1, before BoM split
        self._outsourced_pos: list[dict] = []   # POs classified as outsourced (matched BoM in Intuiflow)
        self._purchase_pos:   list[dict] = []   # POs classified as standard purchase (no BoM match)
        self._all_orders:     list[dict] = []   # original full list for commit verification
        self._committed_ids:  list       = []   # PendingOrderIds of successfully created orders

    def _get_pending_orders(self) -> None:
        ''' Fetches approved pending orders from Intuiflow and splits them into
        work orders (OrderType=2) and purchase orders (OrderType=1). Applies
        date adjustments and field normalization for Fishbowl compatibility. '''
        try:
            resp = get_pending_orders(is_test_environment=self._is_intuiflow_test)
            orders = resp["data"] or []
            if not orders:
                self.log.log("Get Pending Orders", "Intuiflow returned no pending orders. Nothing to import.")
                return

            self.log.log("Get Pending Orders", "Successfully queried pending orders from Intuiflow.")

            for order in orders:
                order_type = order.get("OrderType")

                if order_type == 2:     # work order
                    due_date     = order.get("DueDate")
                    start_date   = order.get("StartDate")
                    promise_date = order.get("PromiseDate")
                    routing_name = order.get("RoutingName") or None   # normalize empty string → None
                    bom_name     = order.get("BOMName")    or None

                    # Fishbowl requires StartDate ≤ DueDate and StartDate ≤ PromiseDate
                    if start_date and due_date and start_date > due_date:
                        due_date = start_date
                    if start_date and promise_date and start_date > promise_date:
                        promise_date = start_date

                    wo = {
                        "DateScheduled":  due_date,
                        "PromiseDate":    promise_date,
                        "PartNumber":     order.get("PartNumber"),
                        "Qty":            order.get("Quantity"),
                        "StartDate":      start_date,
                        "OrderId":        order.get("OrderNumber"),   # link code stored in Fishbowl custom field
                        "OrderType":      order_type,
                        "RoutingName":    routing_name,
                        "BomName":        bom_name,
                        "Notes":          order.get("Notes"),
                        "PendingOrderId": order.get("OrderId"),       # Intuiflow internal ID used for commit
                    }
                    self._work_orders.append(wo)
                    self._all_orders.append(wo)

                elif order_type == 1:   # purchase order
                    po = {
                        "DateScheduled":  order.get("DueDate"),
                        "PromiseDate":    order.get("PromiseDate"),
                        "PartNumber":     order.get("PartNumber"),
                        "Qty":            order.get("Quantity"),
                        "StartDate":      order.get("StartDate"),
                        "OrderId":        order.get("OrderNumber"),
                        "OrderType":      order_type,
                        "Notes":          order.get("Notes"),
                        "VendorId":       order.get("VendorIdentifier"),   # may be null — Fishbowl lookup fills it in if so
                        "PendingOrderId": order.get("OrderId"),
                    }
                    self._purchase_orders.append(po)
                    self._all_orders.append(po)

            if not self._work_orders and not self._purchase_orders:
                raise Exception("No valid pending orders (OrderType 1 or 2) found. Nothing to import.")

            self.log.log("Get Pending Orders",
                         f"Found {len(self._work_orders)} pending work orders and "
                         f"{len(self._purchase_orders)} pending purchase orders to import to Fishbowl.")
        except Exception as e:
            self.log.log("Get Pending Orders", f"Fatal error: {e}", True)
            raise

    def _enrich_orders_intuiflow(self) -> None:
        ''' Fetches BoM data (to classify POs as outsourced vs purchase) and routing
        data (to fill in missing WO routing names) from Intuiflow. Removes orders
        that cannot be processed due to missing routing. '''
        if not self._all_orders:
            self.log.log("Enrich Orders (Intuiflow)", "No orders to hydrate with Intuiflow data.")
            return
        
        try:
            # ── Classify POs: outsourced vs. standard purchase ─────────────────
            if self._purchase_orders:
                resp = get_bom_info(is_test_environment=self._is_intuiflow_test)
                bom_data = resp["data"] or []
                if not bom_data:
                    raise Exception("Intuiflow returned no BoM data for PO classification. Ending the call stack.")

                self.log.log("Enrich Orders (Intuiflow)", "Successfully queried BoM info from Intuiflow.")

                for po in self._purchase_orders:
                    matched_bom = next(
                        (b for b in bom_data if str(b.get("PartNumber")) == str(po["PartNumber"])), None
                    )
                    if matched_bom:
                        po["PoTypeID"]     = 30                              # outsourced PO
                        po["ChildPartNum"] = matched_bom.get("ChildPartNumber")
                        self._outsourced_pos.append(po)
                    else:
                        po["PoTypeID"] = 10                                  # standard purchase PO
                        self._purchase_pos.append(po)

                self.log.log("Enrich Orders (Intuiflow)",
                             f"Successfully categorized {len(self._outsourced_pos)} outsourced POs and "
                             f"{len(self._purchase_pos)} purchase POs out of {len(self._purchase_orders)} total POs.")

            # ── Fill in WO routing names ───────────────────────────────────────
            if self._work_orders:
                resp = get_routing_info(is_test_environment=self._is_intuiflow_test)
                routing_data = resp["data"] or []
                if not routing_data:
                    raise Exception("Intuiflow returned no routing data for the pending work orders. Ending the call stack.")

                self.log.log("Enrich Orders (Intuiflow)", "Successfully queried routing info from Intuiflow.")

                enriched = []
                for wo in self._work_orders:
                    if wo.get("RoutingName"):
                        # routing was already set on the order in Intuiflow — use it directly
                        enriched.append(wo)
                    else:
                        matched = next(
                            (r for r in routing_data if str(r.get("PartNumber")) == str(wo["PartNumber"])), None
                        )
                        if matched:
                            wo["RoutingName"] = matched.get("RoutingName")
                            enriched.append(wo)
                        else:
                            self.log.log("Enrich Orders (Intuiflow)",
                                         f"Warning: No routing found for part {wo['PartNumber']} "
                                         f"on WO {wo['OrderId']}. This order will not be imported.", True)
                            
                self.log.log("Enrich Orders (Intuiflow)",
                                f"Successfully assigned a valid routing to {len(enriched)} "
                                f"of {len(self._work_orders)} work orders.")
                self._work_orders = enriched
        except Exception as e:
            self.log.log("Enrich Orders (Intuiflow)", f"Fatal error: {e}", True)
            raise

    def _enrich_orders_fishbowl(self) -> None:
        ''' Queries Fishbowl for BoM IDs (WOs), part info, and vendor info (POs) in a single
        session. Removes orders that cannot be matched. '''
        if not self._work_orders and not self._outsourced_pos and not self._purchase_pos:
            self.log.log("Enrich Orders (Fishbowl)", "No orders to hydrate with Fishbowl data.")
            return

        try:
            fb = None       # initializing for the finally block in case fatal login error.
            fb = FishbowlSession(self._is_fb_test_db)
            if not fb.is_logged_in():
                raise Exception(f"Failed to login to Fishbowl after {fb._login_attemps} attempts.")

            self.log.log("Enrich Orders (Fishbowl)", "Successfully logged into Fishbowl.", auto_print=False)

            # ── Query BoM IDs for WOs ─────────────────────────────────────────
            if self._work_orders:
                bom_rows = fb.query(self._query_bom_id)["data"] or []
                if not bom_rows:
                    raise Exception("BoMID query returned no records - cannot hydrate work orders.")

                self.log.log("Enrich Orders (Fishbowl)", "Successfully queried BoM IDs from Fishbowl.", auto_print=False)

                enriched = []
                for wo in self._work_orders:
                    if wo.get("BomName"):
                        # a specific BoM was selected in Intuiflow — match by BomNumber
                        matched = next((b for b in bom_rows if str(b.get("BomNumber")) == str(wo["BomName"])), None)
                    else:
                        # no BoM selected — prefer the default BoM, fall back to any active BoM for the part.
                        # Postman has a logic inversion bug here that accidentally discards the default BoM
                        # and replaces it with a non-default. Fixed: try default first, then fall back.
                        matched = next(
                            (b for b in bom_rows if str(b.get("PartNumber")) == str(wo["PartNumber"]) and b.get("IsDefault") == "TRUE"), None
                        )
                        if not matched:
                            matched = next(
                                (b for b in bom_rows if str(b.get("PartNumber")) == str(wo["PartNumber"])), None
                            )

                    if matched and matched["BomId"] and matched["BomNumber"]:
                        wo["BomId"]   = matched["BomId"]
                        wo["BomName"] = matched["BomNumber"]
                        enriched.append(wo)
                    else:
                        self.log.log("Enrich Orders (Fishbowl)",
                                     f"Warning: No BoM found for part {wo['PartNumber']} "
                                     f"on WO {wo['OrderId']}. This order will not be imported.", True)

                self.log.log("Enrich Orders (Fishbowl)",
                                f"{len(enriched)} of {len(self._work_orders)} work orders were hydrated with Fishbowl BoM IDs.")
                self._work_orders = enriched

            # ── Query Part Info for POs ───────────────────────────────────────
            if self._outsourced_pos or self._purchase_pos:
                part_rows = fb.query(self._query_part_info)["data"] or []
                if not part_rows:
                    raise Exception("PartInfo query returned no records — cannot hydrate purchase orders.")

                self.log.log("Enrich Orders (Fishbowl)", "Successfully queried part info from Fishbowl.", auto_print=False)

                # reformat the query response for faster lookup
                parts_by_num = {str(p["PartNumber"]): p for p in part_rows}

                # outsourced PO list hydration first
                enriched_outsourced = []
                for po in self._outsourced_pos:
                    parent = parts_by_num.get(str(po.get("PartNumber")))
                    child  = parts_by_num.get(str(po.get("ChildPartNum")))
                    if parent and child and parent["PartId"] and child["PartId"] and child["PartDescription"]:
                        po["PartId"]          = str(parent["PartId"])
                        po["ChildPartId"]     = str(child["PartId"])
                        po["PartDescription"] = str(child["PartDescription"])
                        enriched_outsourced.append(po)
                    else:
                        self.log.log("Enrich Orders (Fishbowl)",
                                     f"Warning: Could not find part info for outsourced PO {po['OrderId']} "
                                     f"(part {po['PartNumber']} and/or child {po.get('ChildPartNum')}). Skipping import.", True)

                # purchased PO list hydration second
                enriched_purchase = []
                for po in self._purchase_pos:
                    part = parts_by_num.get(str(po["PartNumber"]))
                    if part and part["PartId"] and part["PartDescription"]:
                        po["PartId"]          = str(part["PartId"])
                        po["PartDescription"] = str(part["PartDescription"])
                        enriched_purchase.append(po)
                    else:
                        self.log.log("Enrich Orders (Fishbowl)",
                                     f"Warning: Could not find part info for purchase PO {po['OrderId']} "
                                     f"(part {po['PartNumber']}). Skipping import.", True)

                self._outsourced_pos = enriched_outsourced
                self._purchase_pos   = enriched_purchase

            # ── Query Part Vendor for POs ─────────────────────────────────────
            if self._outsourced_pos or self._purchase_pos:
                vendor_rows = fb.query(self._query_part_vendor)["data"] or []
                if not vendor_rows:
                    raise Exception("PartVendor query returned no records — cannot hydrate purchase orders.")

                self.log.log("Enrich Orders (Fishbowl)", "Successfully queried part vendor info from Fishbowl.", auto_print=False)

                # reformat the query response for faster lookup
                vendors_by_part = {str(v["PartNumber"]): v for v in vendor_rows}

                enriched_outsourced = []
                for po in self._outsourced_pos:
                    # outsourced POs: vendor is looked up by child part number
                    matched = vendors_by_part.get(str(po.get("ChildPartNum")))
                    if matched and matched["VendorId"]:
                        po["VendorId"] = str(matched["VendorId"])
                        enriched_outsourced.append(po)
                    else:
                        self.log.log("Enrich Orders (Fishbowl)",
                                     f"Warning: No vendor found for child part {po.get('ChildPartNum')} "
                                     f"on outsourced PO {po['OrderId']}. Skipping import.", True)

                enriched_purchase = []
                for po in self._purchase_pos:
                    if _is_valid(po.get("VendorId")):
                        # Intuiflow provided a VendorId — use it directly, no lookup needed
                        enriched_purchase.append(po)
                    else:
                        # VendorId was not provided by Intuiflow — look it up from Fishbowl
                        matched = vendors_by_part.get(str(po["PartNumber"]))
                        if matched and matched["VendorId"]:
                            po["VendorId"] = str(matched["VendorId"])
                            enriched_purchase.append(po)
                        else:
                            self.log.log("Enrich Orders (Fishbowl)",
                                         f"Warning: No vendor found for part {po['PartNumber']} "
                                         f"on purchase PO {po['OrderId']}. Skipping import.", True)
                            
                self.log.log("Enrich Orders (Fishbowl)",
                        f"{len(enriched_outsourced)} of {len(self._outsourced_pos)} outsourced POs "
                        f"and {len(enriched_purchase)} of {len(self._purchase_pos)} purchase POs "
                        "were hydrated with current Fishbowl part info.")
                self._outsourced_pos = enriched_outsourced
                self._purchase_pos   = enriched_purchase

            self.log.log("Enrich Orders (Fishbowl)",
                         f"Hydration complete: {len(self._work_orders)} WOs, "
                         f"{len(self._outsourced_pos)} outsourced POs, "
                         f"{len(self._purchase_pos)} purchase POs ready to import.")
        except Exception as e:
            self.log.log("Enrich Orders (Fishbowl)", f"Fatal error: {e}", True)
            raise
        finally:
            if fb:
                fb.logout()

    def _import_to_fishbowl(self) -> None:
        ''' Creates MOs and POs in Fishbowl for all enriched orders. Successfully
        created orders have their PendingOrderId added to the commit list. Per-order
        failures are logged but do not abort the remaining orders. '''
        if not self._work_orders and not self._outsourced_pos and not self._purchase_pos:
            self.log.log("Import To Fishbowl", "No orders to import to Fishbowl.")
            return

        try:
            fb = None       # initializing for the finally block in case fatal login error.
            fb = FishbowlSession(self._is_fb_test_db)
            if not fb.is_logged_in():
                raise Exception(f"Failed to login to Fishbowl after {fb._login_attemps} attempts.")

            self.log.log("Import To Fishbowl", "Successfully logged into Fishbowl.", auto_print=False)

            timestamp = _build_timestamp()
            today     = datetime.now()
            today_ts  = f"{today.year}-{today.month}-{today.day}" + timestamp

            # ── Create MOs ────────────────────────────────────────────────────
            mo_created = 0
            for wo in self._work_orders:
                try:
                    payload = _build_mo_payload(wo, timestamp, self._is_fb_test_db)
                    fb.create_mo(payload)       # raises CallFailure on call fail
                    self._committed_ids.append(wo["PendingOrderId"])
                    mo_created += 1
                except Exception as e:
                    self.log.log("Import To Fishbowl",
                                 f"Failed to create an MO for part {wo['PartNumber']} "
                                 f"(order {wo['OrderId']}): {e}", True)

            if self._work_orders:
                self.log.log("Import To Fishbowl",
                             f"Created {mo_created} of {len(self._work_orders)} MOs in Fishbowl.")

            # ── Create Outsourced POs ─────────────────────────────────────────
            outsourced_created = 0
            for po in self._outsourced_pos:
                try:
                    payload = _build_outsourced_po_payload(po, timestamp, today_ts, self._is_fb_test_db)
                    fb.create_po(payload)       # raises CallFailure on call fail
                    self._committed_ids.append(po["PendingOrderId"])
                    outsourced_created += 1
                except Exception as e:
                    self.log.log("Import To Fishbowl",
                                 f"Failed to create an outsourced PO for part {po['PartNumber']} "
                                 f"(order {po['OrderId']}): {e}", True)

            if self._outsourced_pos:
                self.log.log("Import To Fishbowl",
                             f"Created {outsourced_created} of {len(self._outsourced_pos)} outsourced POs in Fishbowl.")

            # ── Create Purchase POs ───────────────────────────────────────────
            purchase_created = 0
            for po in self._purchase_pos:
                try:
                    payload = _build_purchase_po_payload(po, timestamp, today_ts, self._is_fb_test_db)
                    fb.create_po(payload)       # raises CallFailure on call fail
                    self._committed_ids.append(po["PendingOrderId"])
                    purchase_created += 1
                except Exception as e:
                    self.log.log("Import To Fishbowl",
                                 f"Failed to create a purchase PO for part {po['PartNumber']} "
                                 f"(order {po['OrderId']}): {e}", True)

            if self._purchase_pos:
                self.log.log("Import To Fishbowl",
                             f"Created {purchase_created} of {len(self._purchase_pos)} purchase POs in Fishbowl.")

        except Exception as e:
            self.log.log("Import To Fishbowl", f"Fatal error: {e}", True)
            raise
        finally:
            if fb:
                fb.logout()

    def _commit_orders(self) -> None:
        ''' Posts the PendingOrderIds of all successfully created Fishbowl orders
        to Intuiflow to mark them as committed. Warns if any orders failed to import. '''
        if not self._committed_ids:
            self.log.log("Commit Orders", "No orders were imported — nothing to commit.")
            return

        try:
            # Postman verifies committed IDs against the original pending order list.
            # Postman compares PendingOrderId vs OrderId (link code) — these are different fields
            # and would never match. Fixed: compare PendingOrderId to PendingOrderId.
            if len(self._committed_ids) < len(self._all_orders):
                committed_set = {str(i) for i in self._committed_ids}
                failed_parts  = [
                    o["PartNumber"] for o in self._all_orders
                    if str(o["PendingOrderId"]) not in committed_set
                ]
                self.log.log("Commit Orders",
                             f"Warning: Only {len(self._committed_ids)} of {len(self._all_orders)} orders were "
                             f"imported and committed. The following parts failed at some point in the pipeline: "
                             f"{failed_parts}", True)

            committ_pending_orders(self._committed_ids, is_test_environment=self._is_intuiflow_test)
            self.log.log("Commit Orders",
                         f"Successfully committed {len(self._committed_ids)} orders in Intuiflow.")
        except Exception as e:
            self.log.log("Commit Orders", f"Fatal error: {e}", True)
            raise

    def auto_run(self) -> SessionLog:
        ''' Runs the full pending orders import pipeline end-to-end and returns the session log. '''
        try:
            # fetch and split approved pending orders from Intuiflow (WOs and POs)
            self._get_pending_orders()
            # classify POs and fill in WO routing names using Intuiflow BoM/routing data
            self._enrich_orders_intuiflow()
            # attach BoM IDs (WOs) and part/vendor info (POs) from Fishbowl
            self._enrich_orders_fishbowl()
            # create MOs and POs in Fishbowl, collecting IDs to commit
            self._import_to_fishbowl()
            # commit successfully imported orders in Intuiflow
            self._commit_orders()
        except Exception as e:
            self.log.log("Auto Run", str(e), True)
        finally:
            return self.log
