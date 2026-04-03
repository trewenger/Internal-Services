from config import Config
from common.Clients.Fishbowl.FishbowlSession import FishbowlSession
from common.Clients.Intuiflow.IntuiflowApi import get_closed_rope_items
from common.Utils.Logging import SessionLog
from common.Utils.Utils import load_query
from datetime import datetime, timedelta
from pprint import pprint

# ── Private helpers ───────────────────────────────────────────────────────────
def _is_valid(val):
    return val and str(val) not in ("", "null", "undefined", "None", "NA")

def _check_inventory(order:dict) -> tuple:
    """
    Returns (is_ok, messages). Checks ALL parts for INSUFFICIENT INVENTORY from the query.
    Also checks RG parts to ensure total available quantity across locations is sufficient.
    FG parts need no quantity check — inventory is being cycled in, not out.
    """
    messages = []
    for part_num, cfg in order["PartConfigs"].items():
        failure_msg = (
            f"Please ensure there are at "
            f"least {cfg['PartQty']} units of part {part_num} in its default location or location group."
        )
        # FG parts are skipped entirely — inventory is being cycled in for FG, not consumed.
        if cfg["ItemType"] == "FG":
            continue
        # check for the INSUFFICIENT INVENTORY flag from the SQL query (applies to RG parts)
        if any(loc["QtyOnHand"] == "INSUFFICIENT INVENTORY" for loc in cfg["InventoryLocations"]):
            messages.append(failure_msg)
        elif cfg["ItemType"] == "RG":
            total = sum(loc["QtyOnHand"] for loc in cfg["InventoryLocations"])
            if total < cfg["PartQty"]:
                messages.append(
                    f"Part {part_num}: available qty ({total}) < required ({cfg['PartQty']}). {failure_msg}"
                )
    return (len(messages) == 0, messages)

def _aggregate_cycles(order:dict) -> list | None:
    """
    Computes the inventory cycle adjustments for each part in the order.
    FG parts: cycle UP by QtyCompleted * PartBomQty.
    RG parts: cycle DOWN across locations (largest first) until PartQty is consumed.
    Returns list of cycle dicts, or None if an unknown ItemType is encountered.
    """
    cycles = []
    qty_completed = float(order["QtyCompleted"])

    for part_num, cfg in order["PartConfigs"].items():
        if cfg["ItemType"] == "FG":
            qty_to_add = round(qty_completed * cfg["PartBomQty"], 5)
            loc = cfg["InventoryLocations"][0]
            cycles.append({
                "PartId":              cfg["PartId"],
                "InventoryLocationId": loc["InventoryLocationId"],
                "NewQtyOnHand":        round(loc["QtyOnHand"] + qty_to_add, 5),
                "OriginalQtyOnHand":   loc["QtyOnHand"],
                "ItemType":            "FG",
                "MoNum":               order["MoNum"],
            })
        elif cfg["ItemType"] == "RG":
            amount_cycled = 0.0
            part_qty = cfg["PartQty"]
            # Postman uses: while (amountCycled < QtyOrdered * PartBomQty).
            # PartQty == QtyOrdered * PartBomQty per the SQL query, so these are equivalent.
            # The for-loop with an early break is used here instead of a while-loop for clarity.
            for loc in cfg["InventoryLocations"]:
                needed = round(part_qty - amount_cycled, 5)
                if needed <= 0:
                    break
                if loc["QtyOnHand"] <= needed:
                    # uses all the inventory in the location
                    amount_cycled += loc["QtyOnHand"]
                    new_qty = 0.0
                else:
                    amount_cycled += needed
                    new_qty = round(loc["QtyOnHand"] - needed, 5)

                cycles.append({
                    "PartId":              cfg["PartId"],
                    "InventoryLocationId": loc["InventoryLocationId"],
                    "NewQtyOnHand":        new_qty,
                    "OriginalQtyOnHand":   loc["QtyOnHand"],
                    "ItemType":            "RG",
                    "MoNum":               order["MoNum"],
                })
        else:
            return None     # unknown item type — caller should skip this order

    return cycles

def _build_cycle_payload(cycle:dict, is_rollback:bool=False) -> dict:
    """Builds the Fishbowl cycle inventory POST payload for a single location."""
    mo_num = cycle["MoNum"]
    if is_rollback:
        qty   = cycle["OriginalQtyOnHand"]
        note  = f"Intuiflow API error occurred when closing order {mo_num}. Reverting inventory back."
    else:
        qty   = cycle["NewQtyOnHand"]
        note  = f"{cycle['ItemType']} This was cycled by Intuiflow for order {mo_num}"
    return {
        "location":      {"id": int(cycle["InventoryLocationId"])},
        "quantity":      qty,
        "note":          note,
        "trackingItems": [{"partTracking": {"id": 1}, "value": 1}],
    }

# ── Public entry point ────────────────────────────────────────────────────────

class CloseWorkOrders:
    ''' Handles the operations required to close completed Intuiflow work orders
    in Fishbowl, including cycling inventory and deleting the MO. '''

    def __init__(self):
        seven_days_ago = datetime.now() - timedelta(days=7)
        self._date_7_ago = f"{seven_days_ago.month}-{seven_days_ago.day}-{seven_days_ago.year}"
        self.log = SessionLog()
        # Intuiflow configs
        self._is_intuiflow_test_db = Config.INTUIFLOW_USE_TEST
        # Fishbowl configs
        self._is_fb_test_db = Config.USE_TEST_DB
        self._query_wo_configs             = load_query("ClosedWOConfigs")
        self._query_default_location_check = load_query("DefaultLocationCheck")
        # shared data
        self._scheduler_closed_orders = []  # fake closures — just unissue + delete
        self._completed_orders        = []  # real closures — full cycle + delete process
        # short inventory issues exposed for orchestrator — {MoNum: [messages]}
        self.short_inventory: dict[str, list] = {}

    def _get_intuiflow_closed_orders(self) -> None:
        ''' Fetches closed rope items from Intuiflow, filters to completion operations,
        and splits orders into real closures and fake/scheduler closures. '''
        try:
            resp = get_closed_rope_items(self._date_7_ago, is_test_environment=self._is_intuiflow_test_db)
            items = resp["data"] or []
            if not items:
                raise Exception("No closed work orders found in Intuiflow in the last 7 days. Nothing to process.")

            self.log.log("Get Closed Orders (Intuiflow)", "Successfully queried closed rope items from Intuiflow.")

            for item in items:
                wo_num = item.get("OrderNumber")
                resource = item.get("ResourceName")

                # only use the final operation rope item for data, skip the other earlier ops
                if resource != "Completion" and resource != "Shipping":
                    continue

                # parse the order
                delim = str(wo_num).find(":") if wo_num else -1
                order = {
                    "MoNum":              str(wo_num)[:delim] if delim > 0 else str(wo_num),
                    "WoNum":              str(wo_num),
                    "QtyCompleted":       item.get("QuantityCompleted"),
                    "RealCompletionFlag": item.get("ActualEndOperation_LastBatch"),
                }

                # ensure valid data
                invalid_flag = False
                for key, val in order.items():
                    if key == "QtyCompleted" and not order["RealCompletionFlag"]:       # 0 is a valid qty for scheduler closed orders
                        continue
                    if key == "RealCompletionFlag" and isinstance(val, bool):           # False bool values allowed
                        continue
                    if not _is_valid(val):
                        invalid_flag = True
                        self.log.log("Get Closed Orders (Intuiflow)", 
                                     f"Warning: Order {order['WoNum']} will be skipped due to an invalid value for {key}: {val}", True)
                        
                # assign the validated and parsed order to the correct list
                if not invalid_flag:
                    if not order["RealCompletionFlag"]:
                        self._scheduler_closed_orders.append(order)
                    else:
                        self._completed_orders.append(order)

            if len(self._completed_orders) + len(self._scheduler_closed_orders) == 0:
                self.log.log("Get Closed Orders (Intuiflow)",
                    f"Warning: Detected no valid closed orders from Intuiflow. Nothing to process.", True)
            else:
                self.log.log("Get Closed Orders (Intuiflow)",
                            f"Successfully parsed {len(self._completed_orders) + len(self._scheduler_closed_orders)} closed orders from Intuiflow.")
        except Exception as e:
            self.log.log("Get Closed Orders (Intuiflow)", f"Fatal error: {e}", True)
            raise

    def _delete_fake_closures(self) -> None:
        ''' Unissues and deletes scheduler-closed (fake) MOs from Fishbowl.
        These are orders closed from the scheduler — not genuine completions. '''
        if not self._scheduler_closed_orders:
            self.log.log("Delete Fake Closures", "There are no scheduler closed orders to process.")
            return
        
        try:
            fb = None       # initializing for the finally block in case fatal login error.
            fb = FishbowlSession(self._is_fb_test_db)
            if not fb.is_logged_in():
                raise Exception(f"Failed to login to Fishbowl after {fb._login_attemps} attempts.")
            
            self.log.log("Delete Fake Closures", "Successfully logged into Fishbowl.", auto_print=False)

            configs = fb.query(self._query_wo_configs)["data"] or []
            if not configs:
                # this would imply there are no open MOs in Fishbowl...
                raise Exception("ClosedWOConfigs Fishbowl query returned no records.")

            self.log.log("Delete Fake Closures", "Successfully queried Fishbowl WO configs.", auto_print=False)

            # will need to update this section if allowing multi-line item MOs
            # Create a dict of Fishbowl configs for faster lookup/linking
            configs_by_mo = {}
            for row in configs:
                mo_num = row.get("MoNumber")
                if mo_num and mo_num not in configs_by_mo:
                    configs_by_mo[mo_num] = row

            deleted = 0
            already_deleted = 0
            for order in self._scheduler_closed_orders:
                mo_num = order["MoNum"]
                matched_config = configs_by_mo.get(mo_num)
                if not matched_config:
                    # order was not found in Fishbowl — likely already deleted, or MO number changed.
                    already_deleted += 1
                    continue
                mo_id = matched_config.get("MoId")
                mo_status = matched_config.get("MoStatus")
                if not mo_id:
                    self.log.log("Delete Fake Closures",
                                 f"Warning: MoId missing for order {mo_num} in Fishbowl configs. Skipping.", True)
                    continue
                if not mo_status:
                    self.log.log("Delete Fake Closures", 
                                 f"Warning: Status for order {mo_num} is not issued or entered. It will not be closed in Fishbowl.", True)
                    continue
                    
                try:
                    if mo_status == "Issued":
                        fb.unissue_mo(mo_id)
                    fb.delete_mo(mo_id)
                    deleted += 1
                except Exception as e:
                    self.log.log("Delete Fake Closures",
                                 f"Failed to delete order {mo_num}: {e}", True)
                    
            self.log.log("Delete Fake Closures", f"{already_deleted} orders were already deleted.")
            self.log.log("Delete Fake Closures",
                         f"Successfully deleted {deleted} of {len(self._scheduler_closed_orders)} fake closure MOs.")
        except Exception as e:
            self.log.log("Delete Fake Closures", f"Fatal error: {e}", True)
            raise
        finally:
            if fb:
                fb.logout()

    def _check_default_locations(self) -> None:
        ''' Queries Fishbowl for default part locations on each completed order and filters
        out any orders missing a default location or not found in Fishbowl. '''
        if not self._completed_orders:
            self.log.log("Check Default Locations", "There are no completed orders to process default locations on.")
            return
        
        try:
            fb = None       # initializing for the finally block in case fatal login error.
            fb = FishbowlSession(self._is_fb_test_db)
            if not fb.is_logged_in():
                raise Exception(f"Failed to login to Fishbowl after {fb._login_attemps} attempts.")

            self.log.log("Check Default Locations", "Successfully logged into Fishbowl.", auto_print=False)

            # inject MO numbers into the query via the SQL placeholder
            mo_nums_str = ", ".join(f"'{o['MoNum']}'" for o in self._completed_orders)
            query = self._query_default_location_check.replace("{{Location Check MO Nums}}", mo_nums_str)

            part_def_locations = fb.query(query)["data"] or []
            if not part_def_locations:
                raise Exception("DefaultLocationCheck query returned no records — no orders can be processed.")

            self.log.log("Check Default Locations", "Successfully queried default part locations in Fishbowl.", auto_print=False)

            # group rows by MoNumber for O(n) lookup
            locations_by_mo = {}
            for row in part_def_locations:
                mo_num = row.get("MoNumber")
                if mo_num:
                    locations_by_mo.setdefault(mo_num, []).append(row)

            kept_orders = []
            already_processed = 0
            for order in self._completed_orders:
                mo_num = order["MoNum"]
                locations = locations_by_mo.get(mo_num)

                if not locations:
                    # not found in Fishbowl — already closed/deleted, skip silently
                    already_processed += 1
                    continue

                no_location = False
                for row in locations:
                    if not row.get("DefaultLocation"):
                        self.log.log("Check Default Locations",
                                     f"Warning: Part {row.get('PartNum')} on order {mo_num} has no default location. "
                                     f"Order will be skipped for closure.", True)
                        no_location = True

                if not no_location:
                    kept_orders.append(order)

            total_before = len(self._completed_orders)
            self._completed_orders = kept_orders
            self.log.log("Check Default Locations",
                         f"{already_processed} orders have already been closed. ")
            self.log.log("Check Default Locations",
                         f"{len(kept_orders)} of {total_before} completed orders have not been closed yet and have valid \
                         default locations for each part.")
        except Exception as e:
            self.log.log("Check Default Locations", f"Fatal error: {e}", True)
            raise
        finally:
            if fb:
                fb.logout()

    def _parse_part_configs(self, order:dict, matched_configs:list[dict], running_inv:dict):
        """ Modifies a single completed order and returns it hydrated with the 
        relevant part configs, MoID and total inventory count. Returns None if 
        there were invalid fields in any of the matched part configs. """
        try:
            required = ["MoId", "MoNumber", "PartNum", "PartId", "PartDefaultLocationId",
                "OrderQty", "PartBomQty", "PartQty", "ItemType", "QtyOnHand", "InvLocationId"]
            running_inv = running_inv or {}
            part_configs = {}
            mo_id = None
            for part_config in matched_configs:
                # validate each part's data in the config — returns early to skip entire order on bad data
                mo_num = part_config.get("MoNumber")
                part_num = part_config.get("PartNum")
                for field in required:
                    # Edge case check (return early)
                    if not _is_valid(part_config.get(field)):
                        self.log.log("Parse Part Configs",
                                        f"Order {mo_num} for part {part_num}: "
                                        f"field '{field}' is invalid. Skipping order.", True)
                        return
                    if field == "PartQty" and float(part_config[field]) < 0:
                        self.log.log("Parse Part Configs",
                                        f"Order {mo_num}, part {part_num}: "
                                        f"'{field}' is not a valid number. Skipping order.", True)
                        return
                    if field == "OrderQty" and float(part_config[field]) < 0:
                        self.log.log("Parse Part Configs",
                                        f"Order {mo_num}, part {part_num}: "
                                        f"'{field}' is not a valid number. Skipping order.", True)
                        return

                # Build part configs with inventory locations for each part and add them all to the order object
                # there can be multiple of the same part returned if inventory exists in multiple locations
                mo_id = int(part_config["MoId"])
                qty_on_hand = part_config["QtyOnHand"]
                part_id = int(part_config["PartId"])
                location_id = int(part_config["InvLocationId"])
                key = (part_id, location_id)
                
                if key in running_inv:
                    # inventory for this part has already been cycled by previous order in call stack.
                    old_qoh = qty_on_hand if qty_on_hand == "INSUFFICIENT INVENTORY" else round(float(qty_on_hand), 5)
                    qty_on_hand = running_inv.get(key)
                    print(f"\n{part_num} HAS ALREADY BEEN CYCLED IN LOCATION ID: {location_id}"
                        f"QOH HAS BEEN OVERWRITTEN FROM {old_qoh} TO {qty_on_hand}. "
                        f"THIS IMPLIES THAT {abs(old_qoh-qty_on_hand)} UNITS WERE CYCLED IN PREVIOUS ORDERS.\n")
                else:
                    qty_on_hand = qty_on_hand if qty_on_hand == "INSUFFICIENT INVENTORY" else round(float(qty_on_hand), 5)

                inv_location = {
                    "InventoryLocationGroupId": part_config.get("InvLocationGroupId"),
                    "InventoryLocationId":      location_id,
                    "QtyOnHand":                qty_on_hand,
                }

                if part_num not in part_configs:
                    part_configs[part_num] = {
                        "PartId":               int(part_config["PartId"]),
                        "PartDefaultLocationId":int(part_config["PartDefaultLocationId"]),
                        "PartQty":              round(float(part_config["PartQty"]), 5),
                        "PartBomQty":           float(part_config["PartBomQty"]),
                        "ItemType":             part_config["ItemType"],
                        "PartNum":              part_num,
                        "TotalInventory":       0.0 if qty_on_hand == "INSUFFICIENT INVENTORY"
                                                else round(float(qty_on_hand), 5),
                        "InventoryLocations":   [inv_location],
                    }
                else:
                    # aggregate additional inventory locations for same part
                    part_configs[part_num]["TotalInventory"] += (
                        0.0 if qty_on_hand == "INSUFFICIENT INVENTORY" else round(float(qty_on_hand), 5)
                    )
                    part_configs[part_num]["InventoryLocations"].append(inv_location)
            
            # hydrate the order
            order["PartConfigs"] = part_configs
            order["MoId"] = mo_id
            order["QtyOrdered"] = round(float(matched_configs[0]["OrderQty"]), 5)
            return order
        except Exception as e:
            self.log.log("Parse Part Configs", f"Skipping order due to error: {e}", True)
            return

    def _process_real_closures(self) -> None:
        """ Processes each completed order: builds part configs, checks inventory,
        cycles inventory, and deletes the MO. Rolls back inventory and re-issues the MO
        if any cycle fails. """
        if not self._completed_orders:
            self.log.log("Process Real Closures", "No completed orders to process.")
            return
        
        try:
            fb = None       # initializing for the finally block in case fatal login error.
            fb = FishbowlSession(self._is_fb_test_db)
            if not fb.is_logged_in():
                raise Exception(f"Failed to login to Fishbowl after {fb._login_attemps} attempts.")

            self.log.log("Process Real Closures", "Successfully logged into Fishbowl.", auto_print=False)

            configs = fb.query(self._query_wo_configs)["data"] or []
            if not configs:
                raise Exception("ClosedWOConfigs query returned no records.")

            self.log.log("Process Real Closures", "Successfully queried Fishbowl WO configs.", auto_print=False)

            # group config rows by MoNumber — multiple parts per MO (one per part per location)
            # this section will need to be updated to accomodate multi-line MOs in the future
            configs_by_mo = {}
            for config in configs:
                mo_num = config.get("MoNumber")
                if mo_num:
                    configs_by_mo.setdefault(mo_num, []).append(config)


            orders_deleted = 0
            already_deleted = 0
            running_inv = {}       # contains the previously completed cycles
            for order in self._completed_orders:
                mo_num = order["MoNum"]
                matched_configs = configs_by_mo.get(mo_num)
                if not matched_configs: 
                    already_deleted += 1
                    continue        # order was already closed (likely), or someone changed the MO number. Skip silently.

                hydrated_order = self._parse_part_configs(order, matched_configs, running_inv)
                if not hydrated_order:
                    continue        # order had invalid fields. This info is logged by self._parse_part_configs()

                # ── Check Inventory ───────────────────────────────────────────
                # skip the order if insufficient RG inventory 
                inv_ok, inv_messages = _check_inventory(hydrated_order)
                if not inv_ok:
                    self.short_inventory[mo_num] = inv_messages
                    self.log.log("Process Real Closures", 
                                f"Order {mo_num} has insufficient inventory. Skipping.")
                    continue
                
                # ── Aggregate Cycles ──────────────────────────────────────────
                # create the list of inventory cycles based on part QOH and order qtys needed
                cycles = _aggregate_cycles(hydrated_order)
                if cycles is None:
                    self.log.log("Process Real Closures",
                                 f"Order {mo_num} has an unknown part ItemType. Skipping.", True)
                    continue

                # ── Unissue ───────────────────────────────────────────────────
                try:
                    fb.unissue_mo(hydrated_order["MoId"])
                except Exception as e:
                    self.log.log("Process Real Closures",
                                 f"Failed to unissue MO {mo_num}. Skipping. {e}", True)
                    continue

                # ── Cycle Inventory (with rollback on failure) ─────────────────
                completed_cycles = []
                cycle_failed = False
                for cycle in cycles:
                    try:
                        payload = _build_cycle_payload(cycle)
                        fb.cycle_part_inventory(int(cycle["PartId"]), payload)
                        completed_cycles.append(cycle)
                    except Exception as e:
                        self.log.log("Process Real Closures",
                                     f"Cycle failed for order {mo_num}, part ID {cycle['PartId']}: {e}. "
                                     f"Rolling back {len(completed_cycles)} completed cycle(s).", True)
                        cycle_failed = True
                        break

                if cycle_failed:
                    # rollback all completed cycles
                    completed_recycles = []
                    for cycle in completed_cycles:
                        try:
                            if not fb.is_logged_in():
                                fb = FishbowlSession(self._is_fb_test_db)
                            payload = _build_cycle_payload(cycle, is_rollback=True)
                            fb.cycle_part_inventory(int(cycle["PartId"]), payload)
                            completed_recycles.append(cycle)
                        except Exception as e:
                            self.log.log("Process Real Closures",
                                         f"CRITICAL: Rollback failed for order {mo_num}, part {cycle['PartId']}: {e}. "
                                         f"Manual correction required: {cycle}", True)
                            self.log.log("Process Real Closures", 
                                         f"The following were recycled: \n{completed_recycles}")
                            self.log.log("Process Real Closures", 
                                         f"The following may need need manual recycle if not in the above list: \n"
                                         f"{completed_cycles}")
                            self.log.log("Process Real Closures", "The order will remain unissued. Ending the call stack.")
                            raise
                            
                    # re-issue the MO to restore it
                    try:
                        if not fb.is_logged_in():
                            fb = FishbowlSession(self._is_fb_test_db)
                        fb.issue_mo(hydrated_order["MoId"])
                        self.log.log("Process Real Closures",
                                     f"Warning: Order {mo_num} had inventory partially cycled then rolled back. MO re-issued.", True)
                    except Exception as e:
                        self.log.log("Process Real Closures",
                                     f"CRITICAL: Order {mo_num} rollback complete but re-issue failed. "
                                     f"Please manually re-issue MO {mo_num}. {e}", True)
                    finally:
                        continue     # skip deleting the order, has not been cycled yet. 

                # ── Delete MO ─────────────────────────────────────────────────
                try:
                    if not fb.is_logged_in():
                        fb = FishbowlSession(self._is_fb_test_db)
                    fb.delete_mo(hydrated_order["MoId"])
                    orders_deleted += 1

                    # used to track current on hand for the the other orders because their on-hand data is stale.
                    for i in cycles:
                        # the most current cycle has the most current inventory record.
                        key = (int(i["PartId"]), int(i["InventoryLocationId"]))
                        running_inv[key] = i["NewQtyOnHand"]
                except Exception as e:
                    # inventory was already cycled — must rollback and re-issue
                    completed_recycles = []
                    self.log.log("Process Real Closures",
                                 f"Delete failed for order {mo_num} after inventory was cycled. "
                                 f"Rolling back inventory. {e}", True)
                    for cycle in completed_cycles:
                        try:
                            if not fb.is_logged_in():
                                fb = FishbowlSession(self._is_fb_test_db)
                            payload = _build_cycle_payload(cycle, is_rollback=True)
                            fb.cycle_part_inventory(int(cycle["PartId"]), payload)
                            completed_recycles.append(cycle)
                        except Exception as re:
                            self.log.log("Process Real Closures",
                                         f"CRITICAL: Rollback failed for order {mo_num}, part {cycle['PartId']}: {re}. "
                                         f"Manual correction required: {cycle}", True)
                            self.log.log("Process Real Closures", 
                                         f"The following were recycled: \n{completed_recycles}")
                            self.log.log("Process Real Closures", 
                                         f"The following may need need manual recycle if not in the above list: \n"
                                         f"{completed_cycles}")
                            self.log.log("Process Real Closures", "The order will remain unissued. Ending the call stack.")
                            raise
                    try:
                        if not fb.is_logged_in():
                            fb = FishbowlSession(self._is_fb_test_db)
                        fb.issue_mo(hydrated_order["MoId"])
                    except Exception as ie:
                        self.log.log("Process Real Closures",
                                     f"CRITICAL: Order {mo_num} inventory rolled back but re-issue failed. "
                                     f"Please manually re-issue MO {mo_num}. {ie}", True)
            
            self.log.log("Process Real Closures", f"{already_deleted} orders were already cycled and deleted.")
            self.log.log("Process Real Closures",
                         f"Successfully cycled and deleted {orders_deleted} of {len(self._completed_orders)} completed orders.")
        except Exception as e:
            self.log.log("Process Real Closures", f"Fatal error: {e}", True)
            raise
        finally:
            if fb:
                fb.logout()

    def auto_run(self) -> SessionLog:
        ''' Runs the full close work orders pipeline end-to-end and returns the session log. 
        You can access short inventory messages from the class definition. '''
        try:
            # fetch and classify all closed orders from Intuiflow (real vs. fake/scheduler closures)
            self._get_intuiflow_closed_orders()
            # unissue and delete scheduler-closed (fake) MOs — no inventory changes needed
            self._delete_fake_closures()
            # filter real closures to only orders with valid default part locations in Fishbowl
            self._check_default_locations()
            # cycle inventory and delete MOs for all genuine completions
            self._process_real_closures()
        except Exception as e:
            self.log.log("Auto Run", str(e), True)
        finally:
            return self.log
