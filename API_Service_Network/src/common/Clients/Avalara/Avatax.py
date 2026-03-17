from avalara import AvataxClient
import json, os
from datetime import datetime, timedelta, date
from pprint import pprint

# ========================================================================================== #
# Auth configs: (sandbox configs required if using a sandbox connection)
COMPANY_ID = os.getenv('AVA_COMPANY_ID')
COMPANY_ID_SANDBOX = os.getenv('AVA_SB_COMPANY_ID')
USERNAME = os.getenv('AVA_USERNAME')
PASSWORD = os.getenv('AVA_PW')
PASSWORD_SANDBOX = os.getenv('AVA_SB_PW')

"""
# Connection configs: Used to construct the client header, which is returned in the response object.
API_NAME =            # required
API_VERSION =         # required
API_MACHINE_NAME =    # optional
AVA_ENVIRONMENT =     # required, 'sandbox' or 'production'
"""
# ========================================================================================== #

def response_decorator(func):
    def wrapper(*args, **kwargs):
        response = func(*args, **kwargs)
        formatted = {'status': response.status_code, 'data':response.json()}
        return formatted
    return wrapper

class Avalara:
    '''
    Creates a new Avalara connection session. 
    Environment must be 'sandbox' or 'production'. 
    '''

    def __init__(self, environment:str, api_name:str, api_version:str, machine_name:str):
        if environment.lower() != 'production' and environment.lower() != 'sandbox':
            raise Exception ('Invalid environment type. Must be: sandbox or production')

        self._environment = environment.lower()
        self._username = USERNAME
        self._password = PASSWORD if environment == 'production' else PASSWORD_SANDBOX
        self._company_id = COMPANY_ID if environment == 'production' else COMPANY_ID_SANDBOX
        self._api_name = api_name
        self._api_version = api_version
        self._api_machine_name = machine_name
        self._client = self._create_client()

        # check the client connection was successful and is authenticated.
        ping_result = self.ping()
        if not ping_result['data']['authenticated']:
            raise Exception('Failed to authenticate the Avalara connection. Check authentication parameters. ')
        
    def _create_client(self):
        ''' Internal method: creates the initial client connection object. '''
        # creating the client object/connection
        client = AvataxClient(
            app_name=self._api_name,
            app_version=self._api_version,
            machine_name=self._api_machine_name,
            environment=self._environment
            )
        
        # adding login credentials (auth)
        client = client.add_credentials(
            username=self._username,
            password=self._password,
        )
        return client
    
    @response_decorator
    def ping(self) -> object:
        ''' pings the avalara API connection/server. '''
        return self._client.ping()
    
    @response_decorator
    def get_customers(self) -> object:
        ''' gets a list of all customers. '''
        return self._client.query_customers(self._company_id, 'certificates')

    @response_decorator
    def get_certs(self, valid:bool=True, exp_start:str=None, exp_end:str=None) -> object:
        ''' 
        gets a list of all certificates.
        :param status: cert status, True (default) for valid and False for invalid
        :param exp_start: certs expiring after or on this date
        :param exp_end: certs expiring before or on this date
        '''
        params = {
            '$include': 'customers',
            '$filter': f'valid eq {valid}'
        }
        if exp_start and exp_end:
            # filter_date = date.today() + timedelta(days=days_until_exp)
            params['$filter'] += f" AND expirationDate >= '{exp_start}' AND expirationDate <= '{exp_end}'"

        result = self._client.query_certificates(self._company_id, params)
        return result
