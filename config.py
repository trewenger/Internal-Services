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
    USE_TEST_DB = True

    # Avalara settings
    AVA_USERNAME=os.getenv('AVA_USERNAME', 'your-avalara-admin-login-username')
    AVA_PW=os.getenv('AVA_PW', 'your-avalara-admin-login-pw')
    AVA_SB_PW=os.getenv('AVA_SB_PW', 'your-avalara-sandbox-admin-login-pw')
    AVA_COMPANY_ID=os.getenv('AVA_COMPANY_ID', 'your-avalara-company-id')
    AVA_SB_COMPANY_ID=os.getenv('AVA_SB_COMPANY_ID', 'your-avalara-sandbox-company-id')
