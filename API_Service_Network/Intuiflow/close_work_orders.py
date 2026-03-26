from config import Config
from common.Clients.Fishbowl.FishbowlSession import FishbowlSession
from common.Clients.Intuiflow.IntuiflowApi import get_closed_rope_items
from common.Utils.Logging import SessionLog
from common.Utils.Utils import load_query
from datetime import datetime, timedelta

# ── Private helpers ───────────────────────────────────────────────────────────

def _validate_order_fields(order: dict) -> bool:
    """Returns False if any required field is null, empty, or 'null'."""
    for key, val in order.items():
        if val is None or str(val).strip() in ("", "null", "undefined", "None"):
            return False
    return True

def _check_inventory(order: dict) -> tuple:
    """
    Returns (is_ok, messages). Checks ALL parts for INSUFFICIENT INVENTORY from the query.
    Also checks RG parts to ensure total available quantity across locations is sufficient.
    FG parts need no quantity check — inventory is being cycled in, not out.
    """
    messages = []
    for part_num, cfg in order["PartConfigs"].items():
        failure_msg = (
            f"Ensure at least {cfg['PartQty']} units of part {part_num} "
            f"are in its default location or location group."
        )
        # Postman checks only InventoryLocations[0] for "INSUFFICIENT INVENTORY". Checking all
        # locations here is more thorough in case the SQL returns the flag on a non-first row.
        if any(loc["QtyOnHand"] == "INSUFFICIENT INVENTORY" for loc in cfg["InventoryLocations"]):
            messages.append(f"Part {part_num}: query returned INSUFFICIENT INVENTORY. {failure_msg}")
        elif cfg["ItemType"] == "RG":
            # FG parts are skipped here — we're cycling inventory in for FG, not consuming it.
            total = sum(loc["QtyOnHand"] for loc in cfg["InventoryLocations"])
            if total < cfg["PartQty"]:
                messages.append(
                    f"Part {part_num}: available qty ({total}) < required ({cfg['PartQty']}). {failure_msg}"
                )
    return (len(messages) == 0, messages)

def _aggregate_cycles(order: dict) -> list | None:
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

def _build_cycle_payload(cycle: dict, is_rollback: bool = False) -> dict:
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
                raise Exception("No closed rope items returned from Intuiflow.")

            self.log.log("_get_intuiflow_closed_orders", "Successfully queried closed rope items from Intuiflow.")

            completion_resource_names = {"completion", "Shipping"}
            seen_order_nums = set()
            scheduler_closed = []
            completed = []

            for item in items:
                wo_num = item.get("OrderNumber")
                if wo_num:
                    seen_order_nums.add(str(wo_num))

                op_seq = item.get("OperationSequenceNumber")
                resource = item.get("ResourceName")

                # only process completion operations
                if op_seq is None or (op_seq < 1000 and resource not in completion_resource_names):
                    continue

                delim = str(wo_num).find(":") if wo_num else -1
                if delim < 0:
                    self.log.log("_get_intuiflow_closed_orders",
                                 f"Warning: OrderNumber '{wo_num}' missing ':' delimiter, skipping.", True)
                    continue

                order = {
                    "MoNum":              str(wo_num)[:delim],
                    "WoNum":              str(wo_num),
                    "QtyCompleted":       item.get("QuantityCompleted"),
                    "RealCompletionFlag": item.get("ActualEndOperation_LastBatch"),
                    "PartConfigs":        {},
                }

                if not _validate_order_fields({k: v for k, v in order.items() if k != "PartConfigs"}):
                    self.log.log("_get_intuiflow_closed_orders",
                                 f"Warning: Order {order['WoNum']} is missing required fields and will be skipped.", True)
                    continue

                is_fake = (not order["RealCompletionFlag"] or float(order["QtyCompleted"]) == 0)
                if is_fake:
                    scheduler_closed.append(order)
                else:
                    completed.append(order)

            # Postman only warns when allOrders.length < uniqueOrderNums.length (i.e. some were dropped).
            # Always iterating here is more explicit — same warning, no behavior difference.
            captured_wo_nums = {o["WoNum"] for o in scheduler_closed + completed}
            for wo_num in seen_order_nums:
                if wo_num not in captured_wo_nums:
                    self.log.log("_get_intuiflow_closed_orders",
                                 f"Warning: Order {wo_num} was in Intuiflow response but will not be processed.", True)

            if not scheduler_closed and not completed:
                raise Exception("No orders qualify for processing after filtering.")

            self._scheduler_closed_orders = scheduler_closed
            self._completed_orders = completed
            self.log.log("_get_intuiflow_closed_orders",
                         f"Parsed {len(completed)} real closure(s) and {len(scheduler_closed)} fake closure(s).")
        except Exception as e:
            self.log.log("_get_intuiflow_closed_orders", f"Fatal error: {e}", True)
            raise

    def _delete_fake_closures(self) -> None:
        ''' Unissues and deletes scheduler-closed (fake) MOs from Fishbowl.
        These are orders Intuiflow closed automatically — not genuine completions. '''
        if not self._scheduler_closed_orders:
            return
        try:
            fb = None       # initializing for the finally block in case fatal login error.
            fb = FishbowlSession(self._is_fb_test_db)
            if not fb.is_logged_in():
                raise Exception(f"Failed to login to Fishbowl after {fb._login_attemps} attempts.")

            self.log.log("_delete_fake_closures", "Successfully logged into Fishbowl.")

            # Postman runs ClosedWOConfigs per-order in a loop. Running it once here
            # and matching in memory is equivalent and avoids redundant DB round-trips.
            configs = fb.query(self._query_wo_configs)["data"] or []
            if not configs:
                raise Exception("ClosedWOConfigs query returned no records.")

            configs_by_mo = {}
            for row in configs:
                mo_num = row.get("MoNumber")
                if mo_num and mo_num not in configs_by_mo:
                    configs_by_mo[mo_num] = row

            self.log.log("_delete_fake_closures", "Successfully queried Fishbowl WO configs.")

            deleted = 0
            for order in self._scheduler_closed_orders:
                mo_num = order["MoNum"]
                config = configs_by_mo.get(mo_num)
                if not config or not config.get("MoId"):
                    self.log.log("_delete_fake_closures",
                                 f"Order {mo_num} not found in Fishbowl — may already be deleted. Skipping.")
                    continue
                mo_id = int(config["MoId"])
                try:
                    fb.unissue_mo(mo_id)
                    fb.delete_mo(mo_id)
                    deleted += 1
                except Exception as e:
                    self.log.log("_delete_fake_closures",
                                 f"Failed to delete fake closure {mo_num}: {e}", True)

            self.log.log("_delete_fake_closures",
                         f"Deleted {deleted} of {len(self._scheduler_closed_orders)} fake closure MOs.")
        except Exception as e:
            self.log.log("_delete_fake_closures", f"Fatal error: {e}", True)
            raise
        finally:
            if fb:
                fb.logout()

    def _check_default_locations(self) -> None:
        ''' Queries Fishbowl for default part locations on each completed order and filters
        out any orders missing a default location or not found in Fishbowl. '''
        if not self._completed_orders:
            return
        try:
            fb = None       # initializing for the finally block in case fatal login error.
            fb = FishbowlSession(self._is_fb_test_db)
            if not fb.is_logged_in():
                raise Exception(f"Failed to login to Fishbowl after {fb._login_attemps} attempts.")

            self.log.log("_check_default_locations", "Successfully logged into Fishbowl.")

            # inject MO numbers into the SQL placeholder
            mo_nums_str = ", ".join(f"'{o['MoNum']}'" for o in self._completed_orders)
            query = self._query_default_location_check.replace("{{Location Check MO Nums}}", mo_nums_str)

            location_rows = fb.query(query)["data"] or []
            if not location_rows:
                raise Exception("DefaultLocationCheck query returned no records — no orders can be processed.")

            self.log.log("_check_default_locations", "Successfully queried default part locations in Fishbowl.")

            # group rows by MoNumber for O(n) lookup
            locations_by_mo: dict[str, list] = {}
            for row in location_rows:
                mo_num = row.get("MoNumber")
                if mo_num:
                    locations_by_mo.setdefault(mo_num, []).append(row)

            kept = []
            for order in self._completed_orders:
                mo_num = order["MoNum"]
                rows = locations_by_mo.get(mo_num)

                if not rows:
                    # not found in Fishbowl — already closed/deleted, skip silently
                    self.log.log("_check_default_locations",
                                 f"Order {mo_num} not found in Fishbowl default location query — may already be closed.")
                    continue

                no_location = False
                for row in rows:
                    if not row.get("DefaultLocation"):
                        self.log.log("_check_default_locations",
                                     f"Warning: Part {row.get('PartNum')} on order {mo_num} has no default location. "
                                     f"Order will be skipped for closure.", True)
                        no_location = True
                        break

                if not no_location:
                    kept.append(order)

            total_before = len(self._completed_orders)
            self._completed_orders = kept
            self.log.log("_check_default_locations",
                         f"{len(kept)} of {total_before} real closure orders passed the default location check.")
        except Exception as e:
            self.log.log("_check_default_locations", f"Fatal error: {e}", True)
            raise
        finally:
            if fb:
                fb.logout()

    def _process_real_closures(self) -> None:
        ''' Processes each real closure order: builds part configs, checks inventory,
        cycles inventory, and deletes the MO. Rolls back inventory and re-issues the MO
        if any cycle fails. '''
        if not self._completed_orders:
            self.log.log("_process_real_closures", "No real closure orders to process.")
            return
        try:
            fb = None       # initializing for the finally block in case fatal login error.
            fb = FishbowlSession(self._is_fb_test_db)
            if not fb.is_logged_in():
                raise Exception(f"Failed to login to Fishbowl after {fb._login_attemps} attempts.")

            self.log.log("_process_real_closures", "Successfully logged into Fishbowl.")

            # Postman runs ClosedWOConfigs per-order in a loop. Running it once here
            # and matching in memory is equivalent and avoids redundant DB round-trips.
            configs = fb.query(self._query_wo_configs)["data"] or []
            if not configs:
                raise Exception("ClosedWOConfigs query returned no records.")

            self.log.log("_process_real_closures", "Successfully queried Fishbowl WO configs.")

            # group config rows by MoNumber — multiple rows per MO (one per part per location)
            configs_by_mo: dict[str, list] = {}
            for row in configs:
                mo_num = row.get("MoNumber")
                if mo_num:
                    configs_by_mo.setdefault(mo_num, []).append(row)

            orders_deleted = 0
            for order in self._completed_orders:
                mo_num = order["MoNum"]
                matched_rows = configs_by_mo.get(mo_num)

                if not matched_rows:
                    self.log.log("_process_real_closures",
                                 f"Order {mo_num} not found in Fishbowl configs — may already be closed. Skipping.")
                    continue

                # ── Build PartConfigs ──────────────────────────────────────────
                mo_id = None
                part_configs: dict[str, dict] = {}
                skip_order = False
                for row in matched_rows:
                    # validate config row — skip entire order on bad data
                    required = ["MoId", "MoNumber", "PartNum", "PartId", "PartDefaultLocationId",
                                "OrderQty", "PartBomQty", "PartQty", "ItemType", "QtyOnHand", "InvLocationId"]
                    for field in required:
                        if row.get(field) is None or str(row.get(field, "")).strip() == "":
                            if field != "WoNumber":  # WoNumber is optional per Postman
                                self.log.log("_process_real_closures",
                                             f"Order {mo_num}, part {row.get('PartNum')}: "
                                             f"field '{field}' is missing. Skipping order.", True)
                                skip_order = True
                                break
                    if skip_order:
                        break

                    # numeric validation — PartQty and OrderQty must be valid non-negative numbers
                    for num_field in ("PartQty", "OrderQty"):
                        try:
                            if float(row[num_field]) < 0:
                                raise ValueError
                        except (ValueError, TypeError):
                            self.log.log("_process_real_closures",
                                         f"Order {mo_num}, part {row.get('PartNum')}: "
                                         f"'{num_field}' is not a valid number. Skipping order.", True)
                            skip_order = True
                            break
                    if skip_order:
                        break

                    mo_id = int(row["MoId"])
                    part_num = row["PartNum"]
                    qty_on_hand = row["QtyOnHand"]

                    inv_location = {
                        "InventoryLocationGroupId": row.get("InvLocationGroupId"),
                        "InventoryLocationId":      row["InvLocationId"],
                        "QtyOnHand":                qty_on_hand if qty_on_hand == "INSUFFICIENT INVENTORY"
                                                    else round(float(qty_on_hand), 5),
                    }

                    if part_num not in part_configs:
                        part_configs[part_num] = {
                            "PartId":               int(row["PartId"]),
                            "PartDefaultLocationId":int(row["PartDefaultLocationId"]),
                            "PartQty":              round(float(row["PartQty"]), 5),
                            "PartBomQty":           float(row["PartBomQty"]),
                            "ItemType":             row["ItemType"],
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

                if skip_order or not mo_id:
                    continue

                order["PartConfigs"] = part_configs
                order["MoId"] = mo_id
                order["QtyOrdered"] = round(float(matched_rows[0]["OrderQty"]), 5)

                # ── Check Inventory ───────────────────────────────────────────
                inv_ok, inv_messages = _check_inventory(order)
                if not inv_ok:
                    self.short_inventory[mo_num] = inv_messages
                    self.log.log("_process_real_closures",
                                 f"Order {mo_num} has insufficient inventory. Skipping. See short_inventory for details.")
                    continue

                # ── Aggregate Cycles ──────────────────────────────────────────
                cycles = _aggregate_cycles(order)
                if cycles is None:
                    self.log.log("_process_real_closures",
                                 f"Order {mo_num} has an unknown part ItemType. Skipping.", True)
                    continue

                # ── Unissue ───────────────────────────────────────────────────
                try:
                    fb.unissue_mo(mo_id)
                except Exception as e:
                    self.log.log("_process_real_closures",
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
                        self.log.log("_process_real_closures",
                                     f"Cycle failed for order {mo_num}, part {cycle['PartId']}: {e}. "
                                     f"Rolling back {len(completed_cycles)} completed cycle(s).", True)
                        cycle_failed = True
                        break

                if cycle_failed:
                    # rollback all completed cycles
                    for cycle in completed_cycles:
                        try:
                            payload = _build_cycle_payload(cycle, is_rollback=True)
                            fb.cycle_part_inventory(int(cycle["PartId"]), payload)
                        except Exception as e:
                            self.log.log("_process_real_closures",
                                         f"CRITICAL: Rollback failed for order {mo_num}, part {cycle['PartId']}: {e}. "
                                         f"Manual correction required: {cycle}", True)
                    # re-issue the MO to restore it (regardless of rollback outcome)
                    try:
                        fb.issue_mo(mo_id)
                        self.log.log("_process_real_closures",
                                     f"Warning: Order {mo_num} had inventory partially cycled then rolled back. MO re-issued.", True)
                    except Exception as e:
                        self.log.log("_process_real_closures",
                                     f"CRITICAL: Order {mo_num} rollback complete but re-issue failed. "
                                     f"Please manually re-issue MO {mo_num}. {e}", True)
                    continue     # skip delete

                # ── Delete MO ─────────────────────────────────────────────────
                try:
                    fb.delete_mo(mo_id)
                    orders_deleted += 1
                except Exception as e:
                    # inventory was already cycled — must rollback and re-issue
                    self.log.log("_process_real_closures",
                                 f"Delete failed for order {mo_num} after inventory was cycled. "
                                 f"Rolling back inventory. {e}", True)
                    for cycle in completed_cycles:
                        try:
                            payload = _build_cycle_payload(cycle, is_rollback=True)
                            fb.cycle_part_inventory(int(cycle["PartId"]), payload)
                        except Exception as re:
                            self.log.log("_process_real_closures",
                                         f"CRITICAL: Rollback failed for order {mo_num}, part {cycle['PartId']}: {re}. "
                                         f"Manual correction required: {cycle}", True)
                    try:
                        fb.issue_mo(mo_id)
                    except Exception as ie:
                        self.log.log("_process_real_closures",
                                     f"CRITICAL: Order {mo_num} inventory rolled back but re-issue failed. "
                                     f"Please manually re-issue MO {mo_num}. {ie}", True)

            self.log.log("_process_real_closures",
                         f"Successfully closed {orders_deleted} of {len(self._completed_orders)} real closure orders.")
        except Exception as e:
            self.log.log("_process_real_closures", f"Fatal error: {e}", True)
            raise
        finally:
            if fb:
                fb.logout()

    def auto_run(self) -> SessionLog:
        ''' Runs the full close work orders pipeline end-to-end and returns the session log. '''
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
            self.log.log("auto_run", str(e), True)
        finally:
            return self.log
