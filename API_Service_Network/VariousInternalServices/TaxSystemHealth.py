"""
script dosctring:

This script checks the Fishbowl database for common core tax-compliance dependancies such as:
Product Tax Codes and Customer Exempt Statuses.
"""

from common.Clients.Google.GoogleSession import *
from common.Clients.Fishbowl.FishbowlSession import FishbowlSession
from common.Clients.Fishbowl.Queries import *
from common.Clients.Email.EmailApi import *
from common.Utils.Logging import SessionLog
from common.Utils.Utils import load_query

# ----------------------------- Globals ------------------------------- #
__all__ = ["tax_system_health"]
LOG = SessionLog()
INCORRECT_PRODUCT_FLAG = 0
INCORRECT_CUSTOMER_FLAG = 0
#---------------------------- Functions ------------------------------#

def _get_product_data(query) -> dict:
    """ Logs into fishbowl and returns the product query. """
    try:
        LOG.log("get_product_data", "Logging into Fishbowl ")
        fb_session = FishbowlSession()
        LOG.log("get_product_data", "Querying product data ")
        response = fb_session.query(query)
        LOG.log("get_product_data", "Success, logging out. ")
        fb_session.logout()
        return response
    except Exception as e:
        LOG.log("main", "Unable to get fishbowl product query data. Ending the call stack.  ", True)
        LOG.log("main", e, True)
        return

def _get_customer_data(query) -> dict:
    """ Logs into fishbowl and returns the customer query. """
    try:
        LOG.log("get_customer_data", "Logging into Fishbowl ")
        fb_session = FishbowlSession()
        LOG.log("get_customer_data", "Querying customer data ")
        response = fb_session.query(query)
        LOG.log("get_customer_data", "Success, logging out. ")
        fb_session.logout()
        return response
    except Exception as e:
        LOG.log("main", "Unable to get fishbowl customer query data. Ending the call stack.  ", True)
        LOG.log("main", e, True)
        return

def _check_product_data(data:list) -> bool:
    """ Checks Fishbowl query data for invalid product setups. Returns True if errors found, false otherwise. """
    try:
        LOG.log("check_product_data", "Checking for incorrect product entries... ")
        for entry in data:
            # If there are entries, these are issues. Query will return nothing if there are no problems. 
            LOG.log("check_product_data", "Product issues found: ")
            temp_object = {
                "product": entry["num"],
                "description": entry["description"],
                "date created": entry["dateCreated"]
            }

            LOG.log("check_product_data", temp_object)
        
        if len(data) > 0:
            return True
        
        return False
    except Exception as e:
        LOG.log("check_product_data", "Unable to check the product data query. Ending the call stack. ", True)
        LOG.log("check_product_data", e, True)
        return False

def _check_customer_data(data:list) -> None:
    """ Checks Fishbowl Query data for invalid customer account setups. Returns True if errors found, false otherwise. """
    try:
        LOG.log("check_customer_data", "Checking for incorrect customer accounts... ")
        for entry in data:
            # If there are entries, these are issues. Query will return nothing if there are no problems. 
            LOG.log("check_customer_data", "Customer account issues found: ")
            temp_object = {
                "name": entry["name"],
                "number": entry["number"],
                "last modified by": entry["lastChangedUser"]
            }

            LOG.log("check_customer_data", temp_object)
        
        if len(data) > 0:
            return True
        
        return False
    except Exception as e:
        LOG.log("check_customer_data", "Unable to check the customer data query. Ending the call stack. ", True)
        LOG.log("check_customer_data", e, True)
        return False

def _draft_email_std(result_recipients) -> None:
    """ Sends either a success email or a failure email with the log from the run. Returns None."""

    email_subject = "Success Summary Report: Tax System Health API" if LOG.error_flag() == 0 else "Failure Summary Report: Tax System Health API"
    email_body = """Please see the below run results: """

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

    send_email(subject=email_subject, html_body=email_body, recipients=result_recipients)

def _draft_email_issues(result_recipients) -> None:
    """ Alternate email send function if there are issues discovered in queries. """

    email_subject = "Success Summary Report (Product or Customer Issues): Tax System Health API"
    email_body = """Please see the below run results: """
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

    send_email(subject=email_subject, html_body=email_body, recipients=result_recipients)



def tax_system_health(result_recipients:list=[], product_query_name:str="TaxHealthProductCheck", customer_query_name:str="TaxHealthProductCheck"):
    """
    Docstring for tax_system_health
    
    :param result_recipients: Description
    :type result_recipients: list
    :param product_query_name: Description
    :type product_query_name: str
    :param customer_query_name: Description
    :type customer_query_name: str
    :return: The session log object. 
    """

    # load the queries
    product_query = load_query(product_query_name)
    customer_query = load_query(customer_query_name)
    
    if not product_query or not customer_query:
        LOG.log('tax_system_health', "Failed to load 1 or more queries. Ending the call stack. ", True)

    # run the queries
    if LOG.error_flag() == 0:
        product_data = _get_product_data(product_query)

    if LOG.error_flag() == 0:
        customer_data = _get_customer_data(customer_query)

    # check the responses for issues
    if LOG.error_flag() == 0:
        _check_product_data(product_data)

    if LOG.error_flag() == 0:
        _check_customer_data(customer_data)

    # send the email summary
    if result_recipients:
        if LOG.error_flag() == 1:
            _draft_email_std(result_recipients)
        elif INCORRECT_PRODUCT_FLAG == 1 or INCORRECT_CUSTOMER_FLAG == 1:
            _draft_email_issues(result_recipients)
        
    return LOG
