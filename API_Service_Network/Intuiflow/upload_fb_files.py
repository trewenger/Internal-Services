from config import Config
from common.Clients.Fishbowl.FishbowlSession import FishbowlSession
from common.Clients.Microsoft.GraphSession import GraphSession
from common.Clients.Intuiflow.IntuiflowApi import (
    create_import, create_import_item, validate_import, run_import, delete_import,
    get_closed_wo
)
from common.Utils.Logging import SessionLog
from common.Utils.Utils import load_query, csv_export
import time 
from datetime import datetime, timedelta
from pprint import pprint

# ── Public entry point ─────────────────────────────────────────────────────────

class UploadFbFiles:
    """Queries Fishbowl for demand history, part, BoM, supply order, demand order, and
    inventory data, then uploads each file to Intuiflow via its import API.

    Demand history and part files are uploaded individually (Mode=Update).
    BoM, supply order, demand order, and inventory are uploaded as a single group (Mode=Replace).
    """

    def __init__(self):
        seven_days_ago = datetime.now() - timedelta(days=7)
        self._date_7_ago = f"{seven_days_ago.month}-{seven_days_ago.day}-{seven_days_ago.year}"
        self.log = SessionLog()
        self._is_intuiflow_test = Config.INTUIFLOW_USE_TEST
        self._is_fb_test_db     = Config.USE_TEST_DB
        self._closed_wo_nums        = ["000000"]    # place holder value so the query always has something
        self._resource_lookup       = None          # used for resource lookup by ID in the get_routings function
        # SQL queries loaded once at init
        self._sql_demand_history = load_query("DemandHistory")
        self._sql_part           = load_query("Part")
        self._sql_bom            = load_query("BillOfMaterials")
        self._sql_supply_order   = load_query("SupplyOrder")
        self._sql_demand_order   = load_query("DemandOrder")
        self._sql_inventory      = load_query("Inventory")
        # queried file data: {"Data": [...], "Mode": "...", "RecordCount": N} or None if 0 records
        self._demand_history = None
        self._part           = None
        self._bom            = None
        self._supply_order   = None
        self._demand_order   = None
        self._inventory      = None
        self._resource       = None
        self._routings       = None

    def _get_resources(self):
        """ Get the resource file from SharePoint and parse into Intuiflow compatible API values """
        try:
            # Graph API session and site connection
            session = GraphSession()
            session.open_sharepoint_site("xfactormachine.sharepoint.com", "sites/Manufacturing")
            self.log.log("Get Resources", "Successfully connected to SharePoint.")

            # Retrieve the resource list from SharePoint
            resources_list_id = session.get_list_id("Resources")
            resources = session.get_list_items(resources_list_id)
            self.log.log("Get Resources", f"Successfully retrieved {len(resources)} resource records from the SharePoint list.")
            
            # Parse the SharePoint list response
            parsed_resources = []
            resource_lookup_dict = {}
            for r in resources:
                r = r.get("fields")
                parsed = {
                    "Name": r.get("Title"),
                    "Location": "Radian Weapons",
                    "Description": r.get("field_2"),
                    "Type": r.get("ResourceType"),
                    "Count": r.get("field_4"),
                    "CrewSize": r.get("field_5"),
                    "Buffer": r.get("field_6"),
                    "SetupTime": r.get("field_7"),
                    "FixedOffset": r.get("field_8"),
                    "Efficiency": r.get("field_12"),
                    "Notes": r.get("field_13") or "",
                    "RequireAtBufferReceive": r.get("field_14"),
                    "RequireToStart": r.get("field_15"),
                    "RequireToComplete": r.get("field_16"),
                    "ShowUnreleasedonSchedules": r.get("field_17"),
                    "ResourceCalendar": r.get("field_18"),
                    "IsActive": r.get("field_19")
                }

                parsed_resources.append(parsed)
                resource_lookup_dict[r.get("id")] = parsed

            # used to parse routings in _get_routings
            self._resource_lookup = resource_lookup_dict    

            # Reformat the SharePoint list response for the Intuiflow API
            self._resource = {
                "Data": parsed_resources, 
                "Mode": "Replace", 
                "RecordCount": len(parsed_resources)
            }

            self.log.log("Get Resources", f"Successfully parsed and saved SharePoint resources.")

        except Exception as e:
            self.log.log("Get Resources", f"Failed to connect to sharepoint and parse the resource list: {e}")
            raise

    def _get_routings(self):
        """ Get the routing files from SharePoint and parse into the correct API format for Intuiflow """
        try:
            # Graph API session and site connection
            session = GraphSession()
            session.open_sharepoint_site("xfactormachine.sharepoint.com", "sites/Manufacturing")
            self.log.log("Get Routings", "Successfully connected to SharePoint.")

            # Retrieve the resource list from SharePoint
            routings_list_id = session.get_list_id("Routings")
            routings = session.get_list_items(routings_list_id)
            self.log.log("Get Routings", f"Successfully retrieved {len(routings)} routing records from the SharePoint list.")

            # Retrieve the routing headers list from SharePoint
            headers_list_id = session.get_list_id("Routing Headers")
            headers = session.get_list_items(headers_list_id)
            self.log.log("Get Routings", f"Successfully retrieved {len(headers_list_id)} routing headers from the SharePoint list.")

            parsed_headers = {}
            for h in headers:
                h = h.get("fields")
                parsed_headers[h.get("id")] = h.get("Title")
            
            # Parse the SharePoint list Routings response - Routing ID: {routing info}, and link the resource name
            parsed_routings = {}
            for r in routings:
                r = r.get("fields")
                resource_lookup_id = r.get("ResourceV3LookupId")
                linked_resource = self._resource_lookup.get(resource_lookup_id)
                parsed_routings.setdefault(r.get("RoutingHeaderLookupId"), []).append({
                    "RoutingName": parsed_headers.get(r.get("RoutingHeaderLookupId")),
                    "RoutingId": r.get("RoutingHeaderLookupId"),
                    "Resource": linked_resource.get("Name"),
                    "Location": "Radian Weapons",
                    "RunRate": r.get("field_1"),
                    "SetupTime": r.get("field_3"),
                    "FixedOffset": r.get("field_4"),
                    "IsPrimaryConstraint": r.get("field_5"),
                    "OperationSequenceNumber": int(r.get("field_6")),
                    "ParallelOperationResourceCount": int(r.get("ParallelOperationResourceCount"))
                })
            
            # Parse the Sharepoint list response for Routing Assignments and build the Intuiflow payload data
            assignments_list_id = session.get_list_id("Routing Assignments")
            assignments = session.get_list_items(assignments_list_id)
            self.log.log("Get Routings", f"Successfully retrieved {len(assignments)} routing assignment records from the SharePoint list.")

            # create a lookup for parts in intuiflow so routes for parts not in Intuiflow are excluded
            part_lookup = set(x.get("PartNumber") for x in self._part.get("Data"))
            
            routing_assignments = []
            for a in assignments:
                a = a.get("fields")
                if a.get("Title") not in part_lookup:       # skip routings for parts not in Intuiflow
                    continue

                routing_id = a.get("RoutingNameV2LookupId")
                matched_routes = parsed_routings.get(routing_id)
                for route in matched_routes:
                    routing_assignments.append({
                        # matched routing fields
                        "RoutingName":              route.get("RoutingName"),
                        "Revision":                 "", 
                        "Resource":                 route.get("Resource"),
                        "OperationDescription":     route.get("Resource"),
                        "Location":                 "Radian Weapons",
                        "RunRate":                  route.get("RunRate"),
                        "SetupTime":                route.get("SetupTime"),
                        "FixedOffset":              route.get("FixedOffset"),
                        "IsPrimaryConstraint":      route.get("IsPrimaryConstraint"),
                        "OperationSequenceNumber":  route.get("OperationSequenceNumber"),
                        "ParallelOperationResourceCount": route.get("ParallelOperationResourceCount"),
                        # routing assignment fields
                        "PartNumber":                       a.get("Title"),
                        "Family":                           a.get("field_4"),
                        "IsDisabled":                       a.get("field_3"),
                        "IsDefault":                        a.get("field_6"),
                    })

            # Reformat the SharePoint list response for the Intuiflow API
            self._routings = {
                "Data": routing_assignments, 
                "Mode": "Replace", 
                "RecordCount": len(routing_assignments)
            }

            self.log.log("Get Routings", f"Successfully parsed and saved SharePoint routings.")

            csv_export(routing_assignments, f"routing_item.csv", 
                        "C:/Users/twenger/OneDrive - X Factor Machine/Tre Wenger/1. System Architecture and Projects/INTERNAL_SERVICES_V2/API_Service_Network/Intuiflow/outputs")

        except Exception as e:
            self.log.log("Get Routings", f"Failed to connect to sharepoint and parse the routings lists: {e}")
            raise

    def _get_closed_work_orders(self) -> None:
        """ Get closed orders from intuiflow to exclude them in the supply order query. """
        try:
            # API call to Intuiflow
            resp = get_closed_wo(self._date_7_ago, self._is_intuiflow_test)    # API calls raise Exception on failure.
            orders = resp["data"]

            self.log.log("Get Closed Work Orders (Intuiflow)", "Successfully queried closed orders in Intuiflow.")

            # validate and normalize the fields
            for order in (orders or []):
                if order.get("OrderNumber"):
                    self._closed_wo_nums.append(order["OrderNumber"])

            nums_sql = ", ".join(f"'{n}'" for n in self._closed_wo_nums)
            self._sql_supply_order = self._sql_supply_order.replace(
                "{closed_wo_filter}",
                f"AND WO.num NOT IN ({nums_sql})"
            )
        except Exception as e:
            self.log.log("Get Closed Work Orders (Intuiflow)", f"Ending the API call stack due to error: {e}", True)
            raise

    def _check_validation_results(self, response_items: list, expected_files: dict, context: str) -> bool:
        """Validates Intuiflow import response items against expected file record counts.

        expected_files: {intuiflow_type_str: record_count}
        Returns True if all items pass.
        Returns False if any item has an unrecognized file name.
        """
        if not response_items:
            self.log.log(context, "Validation response contained no Items.", True)
            return False

        all_passed = True
        for item in response_items:
            file_name    = item.get("FileName") or item.get("Type", "")
            record_count = item.get("RecordCount")
            processed    = item.get("ProcessedCount", 0)
            ignored      = item.get("IgnoredCount", 0)
            val_msgs     = list({m for m in (item.get("ValidationResults") or [])})
            parse_msgs   = list({m for m in (item.get("ParsingErrors")     or [])})
            count_msg    = len(item.get("ParsingErrors") or []) + len(item.get("ValidationResults") or [])

            # demand history exception, Intuiflow calls this both file names, need to accept both.
            is_demand_history = file_name in ("DemandHistory", "DemandArchive")
            adjusted_name = file_name
            if is_demand_history:
                alt_name = "DemandArchive" if file_name == "DemandHistory" else "DemandHistory"
                adjusted_name = alt_name if alt_name in expected_files else file_name
                            
            if adjusted_name not in expected_files:
                self.log.log(context, f"Validation returned unrecognized file name: '{file_name}'.", True)
                all_passed = False
                continue

            expected_count = expected_files[adjusted_name]
            if record_count is not None and int(record_count) != int(expected_count):
                self.log.log(context,
                        f"Record count mismatch for {adjusted_name}: "
                        f"expected {expected_count}, Intuiflow returned {record_count}.", True)
                all_passed = False
            elif processed == 0:
                self.log.log(context,
                        f"Validation failed for {adjusted_name}: 0 records processed "
                        f"({ignored} ignored). Messages: {val_msgs + parse_msgs}", True)
                all_passed = False
            elif ignored > 0:
                self.log.log(context,
                        f"Warning: Validated {processed} of {record_count} records for {adjusted_name} "
                        f"({ignored} records ignored). Messages: {val_msgs + parse_msgs}", True)
                all_passed = False
            else:
                self.log.log(context, 
                             f"Successfully validated {processed} of {expected_count} records for {adjusted_name}. "
                             f"All records will be imported.")
                tot_msg = val_msgs + parse_msgs
                if tot_msg:
                    self.log.log(context, 
                                 f"Warning: All records will be imported but there are {count_msg} records "
                                 f"with one the following non-critical warnings messages: {tot_msg}.")

        return all_passed

    def _query_fishbowl(self) -> None:
        """Runs all 6 SQL queries against Fishbowl in a single session and stores the results.
        A query returning 0 records is a warning, not a fatal error. Raises if every query
        returns 0 records (nothing at all to upload). """
        try:
            fb = None
            fb = FishbowlSession(self._is_fb_test_db)
            if not fb.is_logged_in():
                raise Exception(f"Failed to login to Fishbowl after {fb._login_attemps} attempts.")

            self.log.log("Query Fishbowl", "Successfully logged into Fishbowl.", auto_print=False)


            # simple helper function to avoid duplicate FB query logic
            def _run(label, sql, mode):
                rows = fb.query(sql)["data"] or []      # auto raises CallFailure on call failure
                if not rows:
                    self.log.log(f"Query Fishbowl: {label}", 
                                 f"Warning: {label} query returned 0 records and will not be imported.", True)
                    return None
                self.log.log(f"Query Fishbowl: {label}", 
                             f"{label} query returned {len(rows)} records.", auto_print=False)
                csv_export(rows, f"{label}.csv", 
                           "C:/Users/twenger/OneDrive - X Factor Machine/Tre Wenger/1. System Architecture and Projects/INTERNAL_SERVICES_V2/API_Service_Network/Intuiflow/outputs")
                return {"Data": rows, "Mode": mode, "RecordCount": len(rows)}

            # Dynamically set the valid location groups for the inventory query based on FB environment.
            nums_sql = "(1, 22, 24, 28, 37, 38)" if not self._is_fb_test_db else "(1, 64, 24, 65, 73, 74)"
            self._sql_inventory = self._sql_inventory.replace(
                "{valid_inventory_lg_filter}",
                nums_sql
            )

            self._demand_history = _run("DemandArchive",   self._sql_demand_history, "Update")
            self._part           = _run("Part",            self._sql_part,           "Replace")
            self._bom            = _run("BillOfMaterials", self._sql_bom,            "Replace")
            self._supply_order   = _run("SupplyOrder",     self._sql_supply_order,   "Replace")
            self._demand_order   = _run("DemandOrder",     self._sql_demand_order,   "Replace")
            self._inventory      = _run("Inventory",       self._sql_inventory,      "Replace")

            files_with_records = sum(1 for f in [
                self._demand_history, self._part, self._bom,
                self._supply_order, self._demand_order, self._inventory,
            ] if f is not None)

            if files_with_records == 0:
                # This edge case likely shows a deeper issue with the Fishbowl connection if its hit
                raise Exception("All 6 Fishbowl queries returned 0 records. Nothing to upload to Intuiflow.")

            self.log.log("Query Fishbowl",
                         f"Successfully queried Fishbowl, and {files_with_records} of 6 files have records.")
        except Exception as e:
            self.log.log("Query Fishbowl", f"Fatal error: {e}", True)
            raise
        finally:
            if fb:
                fb.logout()

    def _upload_standalone(self, file_name:str, file_data:dict) -> None:
        """Runs the full Intuiflow import pipeline for a single file.

        create → upload item → validate → run → delete (always in finally).
        Errors are logged but the exception is swallowed — per-file failures are non-fatal. """
        import_id = None
        upload_type = None
        try:
            # ---------------------- create import ----------------
            # auto raises CallFailure on API call failure
            upload_type = file_data["Mode"]
            resp = create_import(upload_type, is_test_environment=self._is_intuiflow_test)
            import_id = (resp.get("data") or {}).get("Id")
            if import_id is None:
                raise Exception(f"Create import returned no ID for {file_name}. Ending call stack.")

            self.log.log(f"Upload Standalone: {upload_type} - {file_name}", 
                         f"Successfully created new Intuiflow import with ID: {import_id}.")

            # ---------------------- upload item ------------------
            resp  = create_import_item(import_id, file_data["Data"], file_name,
                                       is_test_environment=self._is_intuiflow_test)
            items = (resp.get("data") or {}).get("Items") or []
            confirmed = next((i for i in items
                              if i.get("Status") == "Identified"
                              and (i.get("FileName") == file_name
                                   or i.get("Type")     == file_name)), None)

            if not confirmed:
                raise Exception(f"Upload item did not confirm 'Identified' status for {file_name}. Ending call stack.")

            self.log.log(f"Upload Standalone: {upload_type} - {file_name}", 
                         f"Successfully uploaded the {file_name} to import ID: {import_id}.")

            # ------------------------ validate -------------------
            resp  = validate_import(import_id, is_test_environment=self._is_intuiflow_test)
            items = (resp.get("data") or {}).get("Items") or []
            
            passed = self._check_validation_results(items, {file_name: file_data["RecordCount"]},
                                            f"Upload Standalone: {upload_type} - {file_name}")
            
            if not passed:
                raise Exception(f"Validation failed for {file_name}. Ending the call stack.")

            # -------------------------- run ----------------------
            run_import(import_id, is_test_environment=self._is_intuiflow_test)
            self.log.log(f"Upload Standalone: {upload_type} - {file_name}", 
                         f"Successfully imported {file_name} with {file_data['RecordCount']} records.")
            import_id = None
        except Exception as e:
            self.log.log(f"Upload Standalone: {upload_type} - {file_name}", 
                        f"Error: {e}", True)
            raise
        finally:
            # if critical failure after creating the import, attempt to delete it
            if import_id is not None:
                try:
                    delete_import(import_id, is_test_environment=self._is_intuiflow_test)
                    self.log.log(f"Upload Standalone: {upload_type} - {file_name}", 
                                 f"Successfully deleted the import with ID: {import_id}.")
                except Exception as de:
                    self.log.log(f"Upload Standalone: {upload_type} - {file_name}", 
                                 f"Failed to delete failed import with ID {import_id}: {de}", True)
                    raise

    def _upload_group(self, files: list[tuple[str, dict | None]]) -> None:
        """Uploads multiple files as a single grouped import. All files share one import ID
        and are validated together. Files with None data (0 records from Fishbowl) are skipped.

        files: list of (file_name, file_data) tuples where file_data is
               {"Data": [...], "Mode": "...", "RecordCount": N} or None if the query returned 0 records.
        Errors are logged but the exception is swallowed — group failures are non-fatal. """
        files = [(t, f) for (t, f) in files if f is not None]
        if not files:
            self.log.log("Upload Group", "No group files have records. Skipping group upload.")
            return

        import_id = None
        upload_type = None
        all_file_names = [i[0] for i in files]
        try:
            # --------------- create import (group always uses Replace) ---------------
            upload_type = "Replace"
            resp = create_import(upload_type, is_test_environment=self._is_intuiflow_test)
            import_id = (resp.get("data") or {}).get("Id")
            if import_id is None:
                raise Exception(f"Create import returned no ID for the group upload. Ending call stack.")

            self.log.log(f"Upload Group: {upload_type} - {all_file_names}", 
                         f"Group import created with ID: {import_id}.")

            # ----------- upload each file's records to the same import ID ------------
            uploaded_types = {}     # {file_name: record_count} for validation lookup
            for file_name, file_data in files:
                resp  = create_import_item(import_id, file_data["Data"], file_name,
                                           is_test_environment=self._is_intuiflow_test)
                items = (resp.get("data") or {}).get("Items") or []
                confirmed = next((i for i in items
                                  if i.get("Status") == "Identified"
                                  and (i.get("FileName") == file_name
                                       or i.get("Type")     == file_name)), None)
                if not confirmed:
                    raise Exception(
                        f"Upload item did not confirm 'Identified' status for {file_name}. Ending call stack."
                    )
                uploaded_types[file_name] = file_data["RecordCount"]
                self.log.log(f"Upload Group: {upload_type} - {all_file_names}", 
                             f"Successfully uploaded {file_name} to import ID: {import_id}.")

            # ---------------- validate all uploaded files together ----------------
            resp  = validate_import(import_id, is_test_environment=self._is_intuiflow_test)
            items = (resp.get("data") or {}).get("Items") or []
            passed = self._check_validation_results(items, uploaded_types, 
                                                    f"Upload Group: {upload_type} - {all_file_names}")
            if not passed:
                raise Exception(f"Validation failed for the group import {all_file_names}. Ending the call stack.")

            # -------------------------------- run ---------------------------------
            run_import(import_id, is_test_environment=self._is_intuiflow_test)
            self.log.log(f"Upload Group: {upload_type} - {all_file_names}", 
                         f"Successfully imported all grouped files. "
                         f"({sum(uploaded_types.values())} total records across "
                         f"{len(uploaded_types)} files: {list(uploaded_types.keys())}).")
            import_id = None
        except Exception as e:
            self.log.log(f"Upload Group: {upload_type} - {all_file_names}", 
                         f"Error: {e}", True)
            raise
        finally:
            # if critical failure after creating the import, attempt to delete it
            if import_id is not None:
                try:
                    delete_import(import_id, is_test_environment=self._is_intuiflow_test)
                    self.log.log(f"Upload Group: {upload_type} - {all_file_names}", 
                                 f"Successfully deleted the group import with ID: {import_id}.")
                except Exception as de:
                    self.log.log(f"Upload Group: {upload_type} - {all_file_names}", 
                                 f"Failed to delete failed import with ID {import_id}: {de}", True)
                    raise

    def auto_run(self) -> SessionLog:
        """Queries Fishbowl for all file data, then uploads each to Intuiflow. Returns the session log."""
        try:
            self._get_closed_work_orders()

            # query Fishbowl for all six file datasets in a single session
            self._query_fishbowl()

            # query sharepoint for the routing and resource files
            self._get_resources()
            self._get_routings()    # must be ran after _get_resources

            # upload part alone (Mode=Update)
            if self._part:
                self._upload_standalone("Part", self._part)
                print("Waiting 10 seconds to ensure file is loaded.")
                time.sleep(15)

            # upload demand history alone (Mode=Update)
            if self._demand_history:
                self._upload_standalone("DemandArchive", self._demand_history)

            # upload BoM, supply order, demand order, and inventory as a group (Mode=Replace)
            self._upload_group([
                ("BillOfMaterial", self._bom),
                ("SupplyOrder",    self._supply_order),
                ("DemandOrder",    self._demand_order),
                ("PartInventory",  self._inventory),
                ("Resource",      self._resource),
                ("RoutingItem", self._routings)
            ])
        except Exception as e:
            self.log.log("Auto Run", str(e), True)
        finally:
            return self.log
