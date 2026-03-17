"""
script dosctring:

This script discovers the quantity of parts at vendor via Fishbowl queries,
then pastes the results into a Google Sheet. Parts are at vendor if they are outsourced, 
and have been shipped but not yet received in Fishbowl. 

This script is designed to be ran with the WipUpdate Script. Part of this
requires the script to check Fishbowl part custom fields for the WIP name, 
which relates it to names in the WIP Tracker (see WipUpdate.py). Missing custom
field entries, or entries that do not match any existing part name in the Google sheet 
will cause an error email to be sent. 
"""

import os
from dotenv import load_dotenv
load_dotenv()

from common.Clients.Google.GoogleSession import *
from common.Clients.Fishbowl.FishbowlSession import *
from common.Clients.Email.EmailApi import *
from common.Clients.Fishbowl.Queries import *
from common.Utils.Logging import SessionLog
from common.Utils.Utils import load_query
from datetime import datetime

# ----------------------------- Globals ------------------------------- #
VENDOR_TRACKER_SHEET_ID = None
SS = None
TODAY = None
LOG = None
WIP_NAMES_FLAG = 0
# ---------------------------- Functions ------------------------------ #

# Get Fishbowl Data 
def _get_fb_data(query) -> object:
    """
    Logs into fishbowl and queries the data, returns the response or None if failure.
    """
    try:
        session = FishbowlSession(attempt_wait_secs=30)
        LOG.log("get_fb_data", "Successfully logged in. ")
        qty_at_vendor = session.query(query)
        LOG.log("get_fb_data", "Successfully saved query. ")
        session.logout()
        LOG.log("get_fb_data", "Successfully logged out. ")
        return qty_at_vendor
    except Exception as e:
        LOG.log("get_fb_data", e, True)
        LOG.log("get_fb_data", "Failed to retrieve Fishbowl query data. Nothing was updated or changed. " \
        "Ending the call stack. ", True)
        
# Check fishbowl data for missing/invalid WIP Tracker name
def _check_name_exists(qty_at_vendor) -> None:
    """
    Checks Fishbowl part CFs if it is missing the WIP name. Sets the global 
    WIP Name flag if missing names are found. 
    """
    try:
        missing_wip_name = []
        LOG.log("check_name_exists", "Checking for missing WIP names in the part custom fields...")
        for val in qty_at_vendor:
            if not val["WipName"] or val["WipName"] == "":
                missing_wip_name.append([val["PartNumber"], val["Description"]])
        
        if len(missing_wip_name) > 0:
            LOG.log("check_name_exists", ("There are missing names found. "))
            global WIP_NAMES_FLAG
            WIP_NAMES_FLAG = 1

            missing_names = "The following parts have missing WIP Names: <ul>" 
            for part in missing_wip_name:
                list_item = "<b>" + str(part[0]) + "</b>: " + str(part[1])
                missing_names += "<li>" + str(list_item) + "</li>"
            missing_names += "</ul>"
            LOG.log("check_name_exists", str(missing_names))
        else:
            LOG.log("check_name_exists", "There are no parts with missing WIP names. ")

    except Exception as e:
        LOG.log("check_name_exists", e, True)
        LOG.log("check_name_exists", "Failed to check for missing WIP names. Nothing was updated or changed. " \
        "Ending the API call stack. ")

def _check_name_is_valid(qty_at_vendor, name_range, sheet_name):
    """
    Checks that the custom field wip names in the FB data exists as a real name in the WIP.
    Sets the global WIP Names flag if invalid names are found. Returns None.
    """
    try:
        dne = []

        # Reformatting google range read to a list of values instead of 2D list.
        LOG.log("check_name_is_valid", "Starting check to see if FB WIP names are present in the WIP Tracker. ")
        wip_names_read = SS.read_range(sheet_name, name_range)
        wip_names = []
        for arr in wip_names_read:
            if arr[0] and arr:
                wip_names.append(arr[0])
        LOG.log("check_name_is_valid", "Successfully read WIP Tracker names. ")

        # Checking google sheet wip names against FB data wip names. 
        for val in qty_at_vendor:
            fb_wip_name = val["WipName"]
            if fb_wip_name not in wip_names:
                dne.append([val["PartNumber"], val["Description"]])

        # Logging results and drafting error message for email.
        if len(dne) > 0:
            LOG.log("check_name_is_valid", ("There are names with no match found. "))
            global WIP_NAMES_FLAG
            WIP_NAMES_FLAG = 1

            unmatched_names = "The following parts have unmatched WIP Names: <ul>" 
            for part in dne:
                list_item = "<b>" + str(part[0]) + "</b>: " + str(part[1])
                unmatched_names += "<li>" + str(list_item) + "</li>"
            unmatched_names += "</ul>"
            LOG.log("check_name_is_valid", str(unmatched_names))
        else:
            LOG.log("check_name_is_valid", "There are no parts with unmatched WIP names. ")
    except Exception as e:
        LOG.log("check_name_is_valid", e, True)
        LOG.log("check_name_is_valid", "Failed to check for unmatched WIP names. Nothing was updated or changed. " \
        "Ending the API call stack. ")

# Paste FB data into Sheet
def _paste_data(qty_at_vendor, column_order, sheet_name, paste_range, date_cell) -> None:
    """
    Updates the values in the sheet with the new FB data. 
    """
    try:
        LOG.log("paste_data", "Updating sheet data... ")
        column_order = qty_at_vendor.keys() if not column_order else column_order
        rows = [[row.get(k, "") for k in column_order] for row in qty_at_vendor]
        
        # Updating cell's data.
        SS.clear_range(sheet_name, paste_range)
        LOG.log("paste_data", "Successfully cleared import range. ")
        SS.update_range(sheet_name, paste_range, rows)
        LOG.log("paste_data", "Successfully imported updated vendor data from Fishbowl. ")

        # Updating 'last updated' date. 
        SS.clear_range(sheet_name, date_cell)
        LOG.log("paste_data", "Successfully cleared 'last updated' date cell. ")
        SS.update_range(sheet_name, date_cell, [[str(TODAY)]])
        LOG.log("paste_data", "Successfully updated 'last updated' date cell to todays date. ")

    except Exception as e:
        LOG.log("paste_data", e, True)
        LOG.log("paste_data", "Failed to update the vendor tracker import sheet. Some or no data could have " \
        "been modified. Check the call stack info above to see where failure occured. ", True)

# Email Confirmation
def _summary_email(email_rec_list) -> None:
    """
    Sends an error email HTML formatted for any logged errors and run results.
    Returns None.
    """
    email_body = "Please see the below run results for the Vendor Tracker API: <br><br>"

    # Determine log message and email subject. 
    global WIP_NAMES_FLAG
    if LOG.error_flag() == 1:
        LOG.log("System", "Errors encountered during run. Sending error summary email. ", True)
        email_subject = "Error Summary Report: Vendor Tracker API"
    elif WIP_NAMES_FLAG == 1:
        LOG.log("System", "Update completed with no errors, but there are missing or unmatched WIP names. Sending run summary email. ")
        email_subject = "Success Summary Report (Missing/Unmatched WIP Names): Vendor Tracker API"
        email_body = """
        There are missing and/or unmatched WIP Names in the vendor tracker API. Otherwise, the API ran successfully with no errors. <br>
        See below run results: 
        """
    else:
        LOG.log("System", "Update completed with no errors. Sending run summary email. ")
        email_subject = "Success Summary Report: Vendor Tracker API" 
        
    logs = LOG.get_log()
    email_body += "<ol>"
    for key in logs:
        email_body += ("<li><b>" + str(key) + "</b></li><ul>")
        for msg in logs[key]:
            if msg is not None and msg != "":
                email_body += ("<li>" + str(msg) + "</li>")
        email_body += "</ul>"
    email_body += "</ol>"

    response = send_email(email_subject, email_body, email_rec_list)
    print(f'Email send attempt: {response.status_code, response.reason}')

#---------------------------- Main -------------------------------------#

def vendor_tracker(email_rec:list[str], column_order:list[str], sheet_name:str='import', query_name:str="VendorTracker", 
                   paste_range:str="A3:D", last_updated_cell:str="E3:E3", wip_name_range:str="Q2:Q"):
    """
    This function performs the update of the vendor tracker Google Sheet. This script requires a env
    file with several defined params including an SMTP2GO_API_KEY, VENDOR_TRACKER_SHEET_ID, and all fishbowl info.
    In addition a sql query must be defined and stored in the Queries folder. 
    
    :param email_rec: REQUIRED. A list of recipients for the run summary email to be sent to.
    :type email_rec: list[str]
    :param column_order: OPT. he order of column headers for the pasted data. Must align with the headers returned by the query. Ex: ['PartNumber', 'Description', 'Qty', 'WipName']
    :type column_order: list[str]
    :param sheet_name: OPT. The name of the Google Sheet to read and update, 'Import' by default.
    :type sheet_name: str
    :param query_name: OPT. The name of the Fishbowl query to determine qty of parts at vendor.
    :type query_name: str
    :param paste_range: OPT. The WRITE range on the defined sheet where the query results will be pasted, 'A3:D' by default.
    :type paste_range: str
    :param last_updated_cell: OPT. The WRITE range (1 cell) on the defined sheet where date last updated field is stored, 'E3:E3' by default.
    :type last_updated_cell: str
    :param wip_name_range: OPT. The READ range on the defined sheet where current WIP part names are stored, 'Q2:Q' by default.
    :type wip_name_range: str
    :returns: Session Log Object
    """

    # set globals on function run.
    global LOG, VENDOR_TRACKER_SHEET_ID, SS, TODAY, WIP_NAMES_FLAG
    VENDOR_TRACKER_SHEET_ID = os.getenv('VENDOR_TRACKER_SHEET_ID')
    SS = GoogleSession(VENDOR_TRACKER_SHEET_ID)
    TODAY = (datetime.now()).strftime("%m/%d/%Y")
    LOG = SessionLog()
    WIP_NAMES_FLAG = 0

    # load the query
    query = load_query(query_name)

    # run the query against Fishbowl
    qty_at_vendor = _get_fb_data(query)
    qty_at_vendor = qty_at_vendor.get('data')

    # Validate WIP Names Fishbowl CF values exist
    if LOG.error_flag() == 0:
        _check_name_exists(qty_at_vendor)

    # Validate the entered Fishbowl CF values 
    if LOG.error_flag() == 0:
        _check_name_is_valid(qty_at_vendor, wip_name_range, sheet_name)

    # Update the Google Sheet data
    if LOG.error_flag() == 0:
        _paste_data(qty_at_vendor, column_order, sheet_name, paste_range, last_updated_cell)
        
    # Always send a run summary email
    _summary_email(email_rec)

    return LOG
