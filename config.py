import os
from dotenv import load_dotenv

load_dotenv()

"""
Use a env file in the project root for these secrets. 
not all secrets are listed here and this will be improved/added upon in future updates. 
"""

class Config:
    # Flask settings
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-this-to-random-secret-key')

    # Session cookie security — requires HTTPS in production (served via IIS)
    SESSION_COOKIE_SECURE = True     # Browser only sends cookie over HTTPS (localhost exempt)
    SESSION_COOKIE_HTTPONLY = True   # JavaScript cannot read the session cookie
    SESSION_COOKIE_SAMESITE = 'Lax'  # Cookie not sent on cross-site requests

    # Public base URL — used to build links in invite and password reset emails.
    # Set in .env for production (e.g. https://RWAS01). Falls back to request host if not set.
    APP_BASE_URL = os.getenv('APP_BASE_URL', '').rstrip('/')

    # Admin email for triggered error email logging
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'user@example.com')
    SENDER_EMAIL = os.getenv('SENDER_EMAIL', 'sender@example.com')
    SMTP2GO_API_KEY = os.getenv('SMTP2GO_API_KEY', 'change-this-to-smtp2go-api-key')

    # Fishbowl API settings
    FISHBOWL_SERVER_ADDRESS = os.getenv('FISHBOWL_SERVER_ADDRESS', 'localhost')
    FISHBOWL_PROD_PORT = os.getenv('FISHBOWL_PROD_PORT')
    FISHBOWL_TEST_PORT = os.getenv('FISHBOWL_TEST_PORT')
    FISHBOWL_APP_NAME = os.getenv('FISHBOWL_APP_NAME')
    FISHBOWL_APP_DESCRIPTION = os.getenv('FISHBOWL_APP_DESCRIPTION')
    FISHBOWL_APP_ID = os.getenv('FISHBOWL_APP_ID')
    FISHBOWL_USERNAME = os.getenv('FISHBOWL_USERNAME', 'admin')
    FISHBOWL_PASSWORD = os.getenv('FISHBOWL_PASSWORD', 'password')
    FISHBOWL_COMPANY_NAME = os.getenv('FISHBOWL_COMPANY_NAME', 'company_name_here')
    USE_TEST_DB = os.getenv('USE_TEST_DB', "True") == "True"

    # Avalara settings
    AVA_USERNAME = os.getenv('AVA_USERNAME', 'your-avalara-admin-login-username')
    AVA_PW = os.getenv('AVA_PW', 'your-avalara-admin-login-pw')
    AVA_SB_PW = os.getenv('AVA_SB_PW', 'your-avalara-sandbox-admin-login-pw')
    AVA_COMPANY_ID = os.getenv('AVA_COMPANY_ID', 'your-avalara-company-id')
    AVA_SB_COMPANY_ID = os.getenv('AVA_SB_COMPANY_ID', 'your-avalara-sandbox-company-id')
    
    # Google Services
    GOOGLE_SERVICE_SCOPES = os.getenv('GOOGLE_SERVICE_SCOPES', 'service-scopes-here')
    GOOGLE_CREDENTIALS_PATH = os.getenv('GOOGLE_CREDENTIALS_PATH', 'json-cred-file-path')
    
    # Various Google Sheet IDs and URLs
    VENDOR_TRACKER_SHEET_ID = os.getenv('VENDOR_TRACKER_SHEET_ID', 'sheet-id-here')
    WIP_TRACKER_SHEET_ID = os.getenv('WIP_TRACKER_SHEET_ID', 'sheet-id-here')
    ON_TIME_PERFORMANCE_SHEET_ID = os.getenv('ON_TIME_PERFORMANCE_SHEET_ID', 'sheet-id-here')
    ON_TIME_PERFORMANCE_SHEET_URL = os.getenv('ON_TIME_PERFORMANCE_SHEET_URL', 'full-sheet-url-here')

    # Digital Routing Card Manager
    INTUIFLOW_WORKORDER_BASE_URL = os.getenv('INTUIFLOW_WORKORDER_BASE_URL', '')
    INTUIFLOW_LOCATION           = os.getenv('INTUIFLOW_LOCATION', '')
    CARD_HOST_BASE_URL           = os.getenv('CARD_HOST_BASE_URL', 'https://RWAS01')

    # Intuiflow settings
    INTUIFLOW_PROD_ADDRESS = os.getenv('INTUIFLOW_PROD_ADDRESS', 'intuiflow-prod-url')
    INTUIFLOW_PROD_TOKEN = os.getenv('INTUIFLOW_PROD_TOKEN', 'intuiflow-prod-token')
    INTUIFLOW_TEST_ADDRESS = os.getenv('INTUIFLOW_TEST_ADDRESS', 'intuiflow-test-url')
    INTUIFLOW_TEST_TOKEN = os.getenv('INTUIFLOW_TEST_TOKEN', 'intuiflow-test-token')
    INTUIFLOW_USE_TEST = os.getenv('USE_TEST_DB', "True") == "True"
    INTUIFLOW_ROPE_ITEMS_LOCATION = os.getenv('INTUIFLOW_ROPE_ITEMS_LOCATION', 'Radian Weapons')
        # Fishbowl custom field IDs (test and prod are separate DBs with different IDs)
    FISHBOWL_TEST_CF_MO_ROUTING_NAME_ID   = int(os.getenv('FISHBOWL_TEST_CF_MO_ROUTING_NAME_ID',   0))
    FISHBOWL_TEST_CF_MO_DATE_SCHEDULED_ID = int(os.getenv('FISHBOWL_TEST_CF_MO_DATE_SCHEDULED_ID',  0))
    FISHBOWL_TEST_CF_MO_LINK_CODE_ID      = int(os.getenv('FISHBOWL_TEST_CF_MO_LINK_CODE_ID',   0))
    FISHBOWL_TEST_CF_PO_LINK_CODE_ID      = int(os.getenv('FISHBOWL_TEST_CF_PO_LINK_CODE_ID',   0))

    FISHBOWL_PROD_CF_MO_ROUTING_NAME_ID   = int(os.getenv('FISHBOWL_PROD_CF_MO_ROUTING_NAME_ID',   0))
    FISHBOWL_PROD_CF_MO_DATE_SCHEDULED_ID = int(os.getenv('FISHBOWL_PROD_CF_MO_DATE_SCHEDULED_ID',  0))
    FISHBOWL_PROD_CF_MO_LINK_CODE_ID      = int(os.getenv('FISHBOWL_PROD_CF_MO_LINK_CODE_ID',   0))
    FISHBOWL_PROD_CF_PO_LINK_CODE_ID      = int(os.getenv('FISHBOWL_PROD_CF_PO_LINK_CODE_ID',   0))
