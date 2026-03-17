"""
script dosctring:

"""

import os
from dotenv import load_dotenv
load_dotenv()

from common.Clients.Google.GoogleSession import *
from common.Clients.Fishbowl.FishbowlSession import FishbowlSession
from common.Clients.Fishbowl.Queries import *
from common.Clients.Email.EmailApi import *
from common.Utils.Logging import SessionLog
from common.Utils.Utils import load_query
from datetime import datetime, timedelta
import pandas, os

# ----------------------------- Globals ------------------------------- #
WIP_TRACKER_ID = None
SS = None
REPO_ROOT = None
CSV_FOLDER = None
TODAY = None
LOG = None

last_week_ship = None                                   # FB query result save variable. 
six_month_ship = None                                   # FB query result save variable. 
bo = None                                               # FB query result save variable. 

# Custom exceptions:
class ColumnPositionChanged(Exception):
    """ Used for denoting a column position change in the WIP tracker. """
    pass

#-------------------------- Archive WIP Data -------------------------------#

# Note: Ensure all fields are allowed to edit in the SS. 
def _archive_wip_data() -> None:
    """
    Moves various columns in the WIP tracker to archive data.
    """
    # verifying column positions have not changed. 
    try:
        LOG.log("archive_wip_data", "Verifying column positions... ")
        master_sku_list_headers = SS.read_range("MASTER SKU LIST", "F1:I1")
        results_headers = SS.read_range("RESULTS", "D2:H2")
        LOG.log("archive_wip_data", "Success. Read column headers. ")
        if len(master_sku_list_headers[0]) != 4 or len(results_headers[0]) != 5:
            raise ColumnPositionChanged("Columns were moved in the WIP Tracker, and some columns " \
                                        "in the range are blank. No data will be updated. Ending call stack. ")

        # Master SKU List Sheet. 
        qty_from_backorder = master_sku_list_headers[0][0]
        paste_last_backorder = master_sku_list_headers[0][3]
        # Results Sheet. 
        last_bo_qty = results_headers[0][0]
        bo_qty = results_headers[0][1]
        last_week_ship_qty = results_headers[0][3]
        week_ship_qty = results_headers[0][4]
        
        combined = [qty_from_backorder, paste_last_backorder, last_bo_qty, 
                    bo_qty, last_week_ship_qty, week_ship_qty]
        check_vals = ["PASTE LAST BACKORDER", "QTY FROM BACKORDER", "LAST BACK ORDER QTY", 
                      "BACK ORDER QTY", "LAST WEEK SHIP QTY", "WEEK SHIP QTY"]
        
        for index, val in enumerate(combined):
            if str(val) != str(check_vals[index]):
                raise ColumnPositionChanged("The column " + str(check_vals[index]) + 
                                            " was moved. No data will be updated. Ending call stack. ")
        LOG.log("archive_wip_data", "All column headers are unchanged. Validation passed. ")
    except Exception as e:
        LOG.log("archive_wip_data", str(e), True)
        return      # return early so the following events don't trigger

    # Collecting data to archive. 
    try:
        LOG.log("archive_wip_data", "Reading column data... ")
        master_sku_list_data = SS.read_range("MASTER SKU LIST", "I6:I")
        results_data = SS.read_range("RESULTS", "D4:H")
        last_bo_qty_data = []
        last_week_ship_data = []

        EXPECTED_COLS = 5
        for row in results_data:
            # Padding the end of the row to be the expected number of columns if needed. 
            if len(row) < EXPECTED_COLS:
                padding = EXPECTED_COLS - len(row)
                for i in range(padding):
                    row.append('')

            last_bo_qty_data.append([row[1]])
            last_week_ship_data.append([row[4]])
        LOG.log("archive_wip_data", "Success. Column data saved. ")
    except Exception as e:
        LOG.log("archive_wip_data", "Unable to read WIP data. Nothing has been or will be updated. Ending call stack. ", True)
        LOG.log("archive_wip_data", e, True)
        return      # return early so the following events don't trigger
    
    # Paste BO (master sku list). 
    try:
        LOG.log("archive_wip_data", "Pasting to last BO column in MASTER SKU LIST. ")
        SS.update_range("MASTER SKU LIST", "F6:F", master_sku_list_data)
        LOG.log("archive_wip_data", "Success. MASTER SKU LIST sheet data archived. ")
    except Exception as e:
        LOG.log("archive_wip_data", e, True)
        LOG.log("archive_wip_data", "Failed to archive BO data in MASTER SKU LIST. No data was modified. Ending call stack. ", True)
        return      # return early so the following event doesn't trigger

    # Paste Last Week Ship (Results sheet)
    try:
        LOG.log("archive_wip_data", "Pasting to last BO qty column in RESULTS. ")
        SS.update_range("RESULTS", "D4:D", last_bo_qty_data)
        LOG.log("archive_wip_data", "Pasting to last week ship column in RESULTS. ")
        SS.update_range("RESULTS", "G4:G", last_week_ship_data)
        LOG.log("archive_wip_data", "Success. RESULTS sheet data archived. ")
    except Exception as e:
        LOG.log("archive_wip_data", e, True)
        LOG.log("archive_wip_data", "Failed to update RESULTS sheet data. MASTER SKU LIST sheet BO archive " \
                                        "was already completed successfully. Ending call stack. ", True)
        return

#-------------------------- Get Fishbowl Data -------------------------------#

def _get_fb_data(last_week_ship_query, wip_six_month_ship_query, wip_bo_query) -> None:
    """
    Retrieves Fishbowl query data and saves it to the global variables.
    """
    try:
        LOG.log("get_fb_data", "Logging in to Fishbowl. ")
        session = FishbowlSession()

        LOG.log("get_fb_data", "Querying last week shipped report. ")
        global last_week_ship
        last_week_ship = session.query(last_week_ship_query).get('data')

        LOG.log("get_fb_data", "Querying six months shipped report. ")
        global six_month_ship
        six_month_ship = session.query(wip_six_month_ship_query).get('data')

        LOG.log("get_fb_data", "Querying BO report. ")
        global bo
        bo = session.query(wip_bo_query).get('data')

        LOG.log("get_fb_data", "Logging out. ")
        session.logout()
        LOG.log("get_fb_data", "Success. Fishbowl queries collected and session logged out. ")

    except Exception as e:
        LOG.log("get_fb_data", e, True)
        LOG.log("get_fb_data", "No data was updated, no CSVs were modified. Ending call stack. ", True)

#-------------------------- Write to CSV ------------------------------------#

def _csv_export() -> None:
    """
    Exports the current data to CSV folder. Retains the previous export. Only retains the most recent
    and the previous exports.
    """
    try:
        # CSV Names
        LOG.log("csv_export", "Setting file paths for CSV files based on current PC. ")
        old_last_week_ship = os.path.join(CSV_FOLDER, "last_week_shipped_previous.csv")
        old_bo = os.path.join(CSV_FOLDER, "bo_previous.csv")
        old_six_month_ship = os.path.join(CSV_FOLDER, "six_month_shipped_previous.csv")
        current_last_week_ship = os.path.join(CSV_FOLDER, "last_week_shipped_current.csv")
        current_bo = os.path.join(CSV_FOLDER, "bo_current.csv")
        current_six_month_ship = os.path.join(CSV_FOLDER, "six_month_shipped_current.csv")

        # Removing old CSV files. 
        LOG.log("csv_export", "Deleting CSV files in location marked 'previous'. ")
        if os.path.exists(old_last_week_ship):
            os.remove(old_last_week_ship)
        if os.path.exists(old_bo):
            os.remove(old_bo)
        if os.path.exists(old_six_month_ship):
            os.remove(old_six_month_ship)
        # Renaming previous CSV files.
        LOG.log("csv_export", "Renaming CSV files in location from 'current' to 'previous'. ")
        if os.path.exists(current_last_week_ship):
            os.rename(current_last_week_ship, old_last_week_ship)
        if os.path.exists(current_bo):
            os.rename(current_bo, old_bo)
        if os.path.exists(current_six_month_ship):
            os.rename(current_six_month_ship, old_six_month_ship)
        LOG.log("csv_export", "Success. All files deleted/renamed. ")
    except Exception as e:
        LOG.log("csv_export", "Failed to rename and remove previously existing CSV exports. ", True)
        LOG.log("csv_export", e, True)

    try:
        # Exporting new data as 'current'
        LOG.log("csv_export", "Exporting new last week ship query as CSV. ")
        framed = pandas.DataFrame(last_week_ship, columns=["ProductNumber", "ProductDescription", "Qty"])
        framed.to_csv(f'{CSV_FOLDER}/last_week_shipped_current.csv', index=False)  # index=False omits the row numbers

        LOG.log("csv_export", "Exporting new six months shipped query as CSV. ")
        framed = pandas.DataFrame(six_month_ship, columns=["ProductNumber", "ProductDescription", "Qty"])
        framed.to_csv(f'{CSV_FOLDER}/six_month_shipped_current.csv', index=False)

        LOG.log("csv_export", "Exporting new BO query as CSV. ")
        framed = pandas.DataFrame(bo, columns=["Product", "Description", "TotalOrdered", "TotalOnHand", "QtyShort", "QtyOver"])
        framed.to_csv(f'{CSV_FOLDER}/bo_current.csv', index=False)
        LOG.log("csv_export", "Success. 3/3 CSV files exported with name '..._current'. ")
    except Exception as e:
        LOG.log("csv_export", "Failed to export the most recent CSV files. CSV from two weeks ago was removed, and csv" \
        "export from last week was renamed '..._previous.csv'. ", True)
        LOG.log("csv_export", e, True)

#---------------------- Paste FB data into WIP. ------------------------------#

def _six_months_ship_report() -> None:
    """
    Clears and replaces the data in the six month ship tab of the WIP with the new Fishbowl data.
    """
    try:
        LOG.log("six_months_ship_report", "Updating six months shipped report sheet... ")
        column_order = ['ProductNumber', 'ProductDescription', 'Qty']
        rows = [[row.get(k, "") for k in column_order] for row in six_month_ship]
        SS.clear_range("PASTE 6 MONTH SHIPPED", "F3:H")
        LOG.log("six_months_ship_report", "Previous report data cleared successfully. ")
        SS.update_range("PASTE 6 MONTH SHIPPED", "F3:H", rows)
        LOG.log("six_months_ship_report", "New report data pasted successfully. ")
    except Exception as e:
        message = "Errors when attempting to replace the six month ship report in the WIP. WIP Data has " \
        "already been archived. Ending call stack. "
        LOG.log("six_months_ship_report", message, True)
        LOG.log("six_months_ship_report", e, True)

def _bo_report() -> None:
    """
    Clears and replaces the data in the BO report tab of the WIP with the new Fishbowl data.
    """
    try:
        LOG.log("bo_report", "Updating BO report sheet... ")
        column_order = ['Product', 'Description', 'TotalOrdered']
        rows = [[row.get(k, "") for k in column_order] for row in bo]
        SS.clear_range("PASTE BACKORDER REPORT", "F3:H")
        LOG.log("bo_report", "Previous report data cleared successfully. ")
        SS.update_range("PASTE BACKORDER REPORT", "F3:H", rows)
        LOG.log("bo_report", "New report data pasted successfully. ")
    except Exception as e:
            message = "Errors when attempting to replace the BO report in the WIP. 6 month shipped report was " \
            "already completed. all data was already archived. Ending call stack. "
            LOG.log("six_months_ship_report", message, True)
            LOG.log("six_months_ship_report", e, True)

def _last_week_ship_report() -> None:
    """
    Clears and replaces the data in the last week ship tab of the WIP with the new Fishbowl data.
    """
    try:
        LOG.log("last_week_ship_report", "Updating last week ship report sheet... ")
        column_order = ['ProductNumber', 'ProductDescription', 'Qty']
        rows = [[row.get(k, "") for k in column_order] for row in last_week_ship]
        SS.clear_range("PASTE WEEK SHIPPED", "F3:H")
        LOG.log("last_week_ship_report", "Previous report data cleared successfully. ")
        SS.update_range("PASTE WEEK SHIPPED", "F3:H", rows)
        LOG.log("last_week_ship_report", "New report data pasted successfully. ")
    
    except Exception as e:
        message = "Errors when attempting to replace the BO report in the WIP. 6 month shipped and BO reports " \
        "were already completed. all data was already archived. Ending call stack. "
        LOG.log("six_months_ship_report", message, True)
        LOG.log("six_months_ship_report", e, True)

def _update_wip_date() -> None:
    """
    Updates the 'INVENTORY DATE' field in the WIP tracker RESULTS sheet. 
    """
    try:
        LOG.log("update_wip_date", "Checking date is still in the same location. ")
        date_field = SS.read_range("RESULTS", "AA1")[0][0]
        LOG.log("update_wip_date", "Successfully read cell data. ")
        is_date_wip = _is_date_format(date_field)
        is_date_today = _is_date_format(TODAY)
        if is_date_wip and is_date_today:
            LOG.log("update_wip_date", "Successfully validated date field location. ")
            SS.update_range("RESULTS", "AA1", [[TODAY]])
            LOG.log("update_wip_date", "Successfully updated the date to today. ")
        else:
            LOG.log("update_wip_date", "The date field has moved. Cell contents were not a valid date (reading cell AA1" \
            "from the RESULTS sheet). All other data was updated successfully. ", True)
    except Exception as e:
        LOG.log("update_wip_date", e, True)
        LOG.log("update_wip_date", "Call failure when attempting to update the date. All other data is updated. ", True)

#------------------------- Misc Functions -----------------------------------#

def _summary_email(recipients:list[str]) -> None:
    """
    Sends an error email HTML formatted for any logged errors.
    """
    if LOG.error_flag() == 1:
        LOG.log("System", "Errors encountered during run. Sending error summary email. ", True)
        email_subject = "Error Summary Report: WIP Update API"
    else:
        LOG.log("System", "Update completed with no errors. Sending run summary email. ")
        email_subject = "Success Summary Report: WIP Update API"

    email_body = "Please see the below run results for the WIP Tracker update: <br><br>"

    logs = LOG.get_log()
    email_body += "<ol>"
    for key in logs:
        email_body += ("<li><b>" + str(key) + "</b></li><ul>")
        for msg in logs[key]:
            if msg is not None and msg != "":
                email_body += ("<li>" + str(msg) + "</li>")
        email_body += "</ul>"
    email_body += "</ol>"

    send_email(email_subject, email_body, recipients)

def _is_date_format(value, fmt="%m/%d/%Y"):
    """
    Checks if a value is a valid date. 
    """
    try:
        datetime.strptime(value, fmt)
        return True
    except (ValueError, TypeError):
        return False

#----------------------------- Main --------------------------------------#

def wip_update(email_recipients:list[str], last_week_ship_query_name:str='WipLastWeekShip', 
               six_month_ship_query_name:str='WipSixMonthShip', bo_query_name:str='WipBO'):
    """
    This script performs an update of the WIP Tracker Google Sheet. It also perists
    the current and previous week as a csv file. This script invokes complex business logic
    and is likely not reusable for other means, therefore much of this script is not generic
    or customizable. Requires Fishbowl login params, an existing google sheet with a WIP_TRACKER_ID
    env variable, SMTP2GO/EmailApi creds, and predefined sql files in this directory.
    
    :param email_recipients: REQ. A list of recipients to recieve the run summary email.
    :type email_recipients: list[str]
    :param last_week_ship_query_name: The name of the sql file to query shipped products from last week, default is WipLastWeekShip.
    :type last_week_ship_query_name: str
    :param six_month_ship_query_name: The name of the sql file to query shipped products over the last 6 months, default is WipSixMonthShip.
    :type six_month_ship_query_name: str
    :param bo_query_name: The name of the sql file to query the current back order of products (products on order), default is WipBO.
    :type bo_query_name: str
    """

    global WIP_TRACKER_ID, SS, REPO_ROOT, CSV_FOLDER, TODAY, LOG
    WIP_TRACKER_ID = os.getenv('WIP_TRACKER_ID')
    SS = GoogleSession(WIP_TRACKER_ID)
    REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
    CSV_FOLDER = os.path.join(REPO_ROOT, "Outputs")             # path to save the csv output
    TODAY = (datetime.now()).strftime("%m/%d/%Y")
    LOG = SessionLog()

    if not WIP_TRACKER_ID:
        print(f"""Missing Sheet ID: Please provide a WIP_TRACKER_ID variable in a .env file in this directory:
              {os.path.join(REPO_ROOT, "VariousInternalServices")}""")
        exit()

    # load the saved sql files
    last_week_ship_query = load_query(last_week_ship_query_name)
    six_month_ship_query = load_query(six_month_ship_query_name)
    bo_query = load_query(bo_query_name)

    # Runs each function if there are no logged errors. 
    _get_fb_data(last_week_ship_query, six_month_ship_query, bo_query)

    if LOG.error_flag() == 0:
        _archive_wip_data()
    
    if LOG.error_flag() == 0:
        _csv_export()
    
    if LOG.error_flag() == 0:
        _six_months_ship_report()

    if LOG.error_flag() == 0:
        _bo_report()

    if LOG.error_flag() == 0:
        _last_week_ship_report()

    if LOG.error_flag() == 0:
        _update_wip_date()

    if email_recipients:
        _summary_email(email_recipients)
