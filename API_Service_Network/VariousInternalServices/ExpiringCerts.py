"""
script dosctring:

This script allows for a report to be emailed and sent. This report provides a summary
of Avalara customer accounts with expiring certs within the set amount of time. It also
includes a csv attachment with exact details of the expiring certs. 

THIS SCRIPT IS CURRENTLY NOT FUNCTIONING
"""

# need to load the environment variables first.
import os
from dotenv import load_dotenv
load_dotenv()

from common.Utils.Logging import SessionLog
from common.Clients.Email.EmailApi import *
from common.Clients.Avalara.Avatax import Avalara
from common.Utils.Logging import SessionLog
from datetime import datetime, date
import calendar
from pprint import pprint

# ----------------------------- Globals ------------------------------- #
# NOTE: Avalara environment variables need to be configured before this script will work. See the config file in the project root.

# Connection configs:
AVA_ENVIRONMENT = 'sandbox'                 # required, 'sandbox' or 'production'
API_NAME = 'Expired_Cert_Check'             # required
API_VERSION = 'ver 0.1'                     # required
API_MACHINE_NAME = 'Internal Services'      # optional

# filter: the number of days or less from now that a cert will expire.
START_DATE = None
END_DATE = None

LOG = None
# ---------------------------- Functions ------------------------------ #

def get_certs() -> object:
    ''' 
    retrieves certificates and customer info for certs expiring within X days (global var).
    Returns a LIST of formatted certs.
    '''

    LOG.log('get_certs', 'Calling the Avalara API...')
    session = Avalara(AVA_ENVIRONMENT, API_NAME, API_VERSION, API_MACHINE_NAME)
    response = session.get_certs(True, str(START_DATE), str(END_DATE))
    if response['status'] > 204:
        raise Exception("The API call failed to get the certificates")

    LOG.log('get_certs', 'Successfully retrieved data. Reformatting...')
    try:
        certs = response['data']['value']
        formatted_certs = []
        for cert in certs:
            temp = {}
            for customer in cert['customers']:
                temp = {
                    'customer': customer['name'],
                    'cert_type': cert['exemptionReason']['name'],
                    'expiration_date': cert['expirationDate'],
                    'cert_region': cert['exposureZoneName'],
                }

            formatted_certs.append(temp)

        LOG.log('get_certs', 'Successfully parsed the query response.')
        return formatted_certs
    except Exception as e:
        LOG.log('get_certs', f'ERROR: Failed to parse and reformat the Avalara query: {e}')
        return None



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

def expiring_certs():
    """
    """

    # discovering the first and last days/dates of the next month.
    today = date.today()
    start_date = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
    last_day_num = calendar.monthrange(start_date.year, start_date.month)[1]
    end_date = date(start_date.year, start_date.month, last_day_num)

    # set globals on function run.
    global LOG, START_DATE, END_DATE
    LOG = SessionLog()
    START_DATE = start_date
    END_DATE = end_date

    # returns the list of certs and customers meeting the filter criteria.
    certs = get_certs()
    # lines are duplicated for each customer sharing a cert, so the count of the list = customers with expiring certs. 
    num_customer = len(certs)



    # return the log at the end. 
    return LOG

expiring_certs()