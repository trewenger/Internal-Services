"""
script dosctring:

This script should run daily for all orders completed the day before. 
Queries fishbowl for the order info, then pastes it into the database sheet of the 
On-Time Performance SS, and sends a summary report email. 
"""

from config import Config
from common.Clients.Fishbowl.FishbowlSession import FishbowlSession
from common.Clients.Google.GoogleSession import *
from common.Clients.Email.EmailApi import *
from common.Utils.Logging import SessionLog
from common.Utils.Utils import load_query
from datetime import datetime

# ----------------------------- Globals ------------------------------- #
__all__ = ["on_time_performance"]
TODAY = None
SHEET_ID = None
SHEET_URL = None
LOG = None
SS = None
#---------------------------- Functions ------------------------------#

def _get_fb_data(query) -> dict:
    """ Internal function: 
    Queries the Fishbowl DB for the selected query and returns it, or 
    an error if applicable.
    """
    try:
        fb_session = FishbowlSession(is_test_db=Config.USE_TEST_DB)
        LOG.log("get_fb_data", "Successfully logged in. ")
        result = fb_session.query(query)
        LOG.log("get_fb_data", "Successfully saved query. ")
        fb_session.logout()
        LOG.log("get_fb_data", "Successfully logged out. ")
        return result
    
    except Exception as e:
        LOG.log("get_fb_data", e, True)
        LOG.log("get_fb_data", "Failed to retrieve Fishbowl query data. Nothing was updated or changed. " \
        "Ending the call stack. ", True)
        return e

def _find_paste_area(data_length: int, last_row:int) -> int:
    """ Internal function: Uses the passed data length to ensure enough room in the spreadsheet, and returns the 
    start row number. """
    try:
        LOG.log("find_paste_area", "Looking for start row... ")
        db_col = SS.read_range("Database", "A:A")
        row_offset = 0
        is_valid = False
        while not is_valid:
            row_offset += 1
            start_row = SS.read_range("Database", f"A{len(db_col)+row_offset}:R{len(db_col)+row_offset}")
            is_valid = all(cell == [] or cell is None for cell in start_row)
            if row_offset > 5:
                raise Exception("Unable to find the start row. Preventing infinite loop. ")
            
        LOG.log("find_paste_area", "Found the start row successfully. ")
        if (len(db_col)+row_offset+data_length) <= last_row:
            LOG.log("find_paste_data", f"There are enough rows for the update. There are {last_row-(len(db_col)+row_offset)} rows remaining. ")
            return len(db_col)+row_offset
        else:
            raise Exception(f"Not enough rows in the database. Add at least {(len(db_col)+row_offset+data_length)-last_row} more rows need to be added. ")
        
    except Exception as e:
        LOG.log("find_paste_area", e, True)
        LOG.log("find_paste_area", "No data was updated. Ending the call stack. ", True)
        return e

def _paste_data(data:list, start_row:int, headers:list) -> None:
    """ Internal function: 
    Pastes the passed data into the google sheet. Returns None.
    """
    try:
        num_entries = len(data)
        LOG.log("paste_data", "Started reformating JSON to 2D array. ")
        column_order = headers
        """
        column_order = ['OrderType', 'SO', 'SoDateCreated', 'Family', 'SKU', 'Description', 'QuantityOrdered', 
                        'QuantityFulfilled', 'DateFulfilled', 'DateScheduled', 'LeadTime', 'DateScheduledFlag']
        """
        rows = [[row.get(k, "") for k in column_order] for row in data]
        LOG.log("paste_data", "Successfully reformated JSON to a 2D array. ")
        SS.update_range("Database", f"A{start_row}", rows)
        LOG.log("paste_data", f"Successfully pasted {num_entries} entries to the Database sheet. ")

    except Exception as e:
        LOG.log("paste_data", e, True)
        LOG.log("paste_data", "Something when wrong when trying to paste the data. It may or may not have updated. ", True)
        # Not allowing the next code chunk to run if exception occurs. 
        return

    try:
        # Update the date last updated fields. 
        # (sheet name, range, values)
        SS.update_range("Retail", "B18", [[TODAY]])
        SS.update_range("OEM", "B18", [[TODAY]])
        SS.update_range("TIER", "B18", [[TODAY]])
        return
    except Exception as e:
        LOG.log("paste_data", e, True)
        LOG.log("paste_data", "Unable to update the 'date last updated' field. Everything else updated successfully.")
        return

def _draft_email(recipients:list) -> None:
    """ Internal function: Sends either a success email or a failure email with the log from the run. Returns None."""

    email_subject = "Success Summary Report: On-Time Performance API" if LOG.error_flag() == 0 else "Failure Summary Report: On-Time Performance API"
    email_body = f"""Please see the below run results for the <a href="{SHEET_URL}"> On-Time Performance Sheet</a> API: <br><br>"""

    LOG.log("System Message", f"Sending email: {email_subject}.")
        
    logs = LOG.get_log()
    
    email_body += "<ol>"
    for key in logs:
        email_body += ("<li><b>" + str(key) + "</b></li><ul>")
        for msg in logs[key]:
            if msg is not None and msg != "":
                email_body += ("<li>" + str(msg) + "</li>")
        email_body += "</ul>"
    email_body += "</ol>"

    send_email(subject=email_subject, html_body=email_body, recipients=recipients)
    return
    
#---------------------------------------------------------------------#

def on_time_performance(result_recipients:list[str], notification_mode:str="none", custom_headers:list=[], 
                        query_name:str='OnTimePerformance.sql', last_row:int = 200000) -> object:
    """
    Syncs the on time performance Google Sheet with current Fishbowl data. 
    Requires a defined SELECT query in a .sql file somewhere in the project.
    Also requires a .env file in the same directory defining ON_TIME_PERFORMANCE_SHEET_ID,
    and ON_TIME_PERFORMANCE_SHEET_URL.

    :param result_recipients: List of email recipients for notification
    :type result_recipients: list
    :param notification_mode: 'none', 'failure' for abnormal/error run notifications, and 'always' for notification on every run
    :type notification_mode: str
    :param custom_headers: Optional. To dictate paste column order. Must match column values from the SQL query.
    :type custom_headers: list
    :param query_name: Optional. The name of the query to run to get needed data. Searches for 'OnTimePerformance.sql' by default.
    :type query_name: str
    :param last_row: Optional. 200000 by default. Do not let program paste past this row, and send an email once the limit has been hit.
    :type last_row: int
    :return: The session logging output object.
    """

    global TODAY, SHEET_ID, SHEET_URL, LOG, SS
    TODAY = (datetime.now()).strftime("%m/%d/%Y")
    SHEET_ID = Config.ON_TIME_PERFORMANCE_SHEET_ID
    SHEET_URL = Config.ON_TIME_PERFORMANCE_SHEET_URL
    SS = GoogleSession(SHEET_ID)
    LOG = SessionLog()

    # Find the .sql SELECT query and load it as a string
    query = load_query(query_name)
    if not query:
        LOG.log('load_query', 'Query failed to load. Unable to query the FB DB. ', True)

    # Run the query against the Fishbowl DB and return the response
    if LOG.error_flag() == 0:
        query_resp = _get_fb_data(query)

    # Locate the cell range to paste values based on the length of the query response
    if LOG.error_flag() == 0:
        start_row = _find_paste_area(len(query_resp), last_row)

    # Paste the query response values into the indentified cell range
    if LOG.error_flag() == 0:
        # Use customer headers if passed
        default_headers = ['OrderType', 'SO', 'SoDateCreated', 'Family', 'SKU', 'Description', 'QuantityOrdered', 
                        'QuantityFulfilled', 'DateFulfilled', 'DateScheduled', 'LeadTime', 'DateScheduledFlag']
        headers = custom_headers if custom_headers else default_headers
        _paste_data(query_resp.get('data'), start_row, headers)
    
    # Send summary email: success or failure
    if result_recipients and notification_mode != 'none':
        if notification_mode == 'always':
            _draft_email(result_recipients)
        elif LOG.error_flag() == 1:
            _draft_email(result_recipients)

    return LOG
