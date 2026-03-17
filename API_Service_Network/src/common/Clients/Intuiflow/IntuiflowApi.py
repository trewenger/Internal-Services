"""
Docstring for Common.clients.Intuiflow.IntuiflowSession
Purpose: 
-   This session class is used specifically for interaction with the Intuiflow Web Application API.
-   The class provides import, validate, and upload interaction methods. 
-   This Intuiflow API is still a work in progress, and will likely not function correctly at this time.
-   .env must be loaded in the script importing this client BEFORE importing this client.
"""

import os
import requests
import json
# ------------------------------------------------------------ #
#                         Configs:
# ------------------------------------------------------------ #

INTUIFLOW_PROD_ADDRESS = os.getenv("INTUIFLOW_PROD_ADDRESS")
INTUIFLOW_PROD_TOKEN = os.getenv("INTUIFLOW_PROD_TOKEN")
INTUIFLOW_TEST_ADDRESS = os.getenv("INTUIFLOW_TEST_ADDRESS")
INTUIFLOW_TEST_TOKEN = os.getenv("INTUIFLOW_TEST_TOKEN")

# ------------------------------------------------------------ #
#                       POST Requests:
# ------------------------------------------------------------ #

def create_import(import_mode:str, is_test_environment:bool = False) -> object: 
    """   """
    if import_mode != "Replace" and import_mode != "Update":
        raise Exception("The import mode must be either 'Replace' or 'Update'. ")

    base_url = INTUIFLOW_TEST_ADDRESS if is_test_environment else INTUIFLOW_PROD_ADDRESS
    token = INTUIFLOW_TEST_TOKEN if is_test_environment else INTUIFLOW_PROD_TOKEN
    url = f"{base_url}/api/v2/import"

    headers = {
        "Content-Type": "application/json",
        "api_key": token
    }

    payload = json.dumps({
        "Mode": import_mode,
        "Type": "Host",
        "Option": "None",
        "IgnoreSourceERP": "false"
    })

    response = requests.post(url=url, headers=headers, data=payload)
    return {"status":response.status_code, "reason":response.reason, "data":response.json()}

def delete_import(import_id:int, is_test_environment:bool = False) -> object: 
    """   """
    base_url = INTUIFLOW_TEST_ADDRESS if is_test_environment else INTUIFLOW_PROD_ADDRESS
    token = INTUIFLOW_TEST_TOKEN if is_test_environment else INTUIFLOW_PROD_TOKEN
    url = f"{base_url}/api/v2/import/{import_id}"

    headers = {
        "api_key": token
    }

    payload = {}

    response = requests.delete(url=url, headers=headers, data=payload)
    return {"status":response.status_code, "reason":response.reason}

def create_import_item(import_id:int, data:list, is_test_environment:bool = False) -> object:
    """   """
    base_url = INTUIFLOW_TEST_ADDRESS if is_test_environment else INTUIFLOW_PROD_ADDRESS
    token = INTUIFLOW_TEST_TOKEN if is_test_environment else INTUIFLOW_PROD_TOKEN
    url = f"{base_url}/api/v2/import/{import_id}/item?type=BillOfMaterial"

    headers = {
        "Content-Type": "application/json",
        "api_key": token
    }

    # this is the file data from Fishbowl.
    payload = json.dumps(data)

    response = requests.post(url=url, headers=headers, data=payload)
    return {"status":response.status_code, "reason":response.reason, "data":response.json()}

def validate_import(import_id:int, is_test_environment:bool = False) -> object:
    """   """
    base_url = INTUIFLOW_TEST_ADDRESS if is_test_environment else INTUIFLOW_PROD_ADDRESS
    token = INTUIFLOW_TEST_TOKEN if is_test_environment else INTUIFLOW_PROD_TOKEN
    url = f"{base_url}/api/v2/import/{import_id}/validate"

    headers = {
        "api_key": token
    }

    payload = {}

    response = requests.post(url=url, headers=headers, data=payload)
    return {"status":response.status_code, "reason":response.reason, "data":response.json()}

def run_import(import_id:int, is_test_environment:bool = False) -> object:
    """   """
    base_url = INTUIFLOW_TEST_ADDRESS if is_test_environment else INTUIFLOW_PROD_ADDRESS
    token = INTUIFLOW_TEST_TOKEN if is_test_environment else INTUIFLOW_PROD_TOKEN
    url = f"{base_url}/api/v2/import/{import_id}/run"

    headers = {
        "api_key": token
    }

    payload = {}

    response = requests.post(url=url, headers=headers, data=payload)
    return {"status":response.status_code, "reason":response.reason, "data":response.json()}

def committ_pending_orders(order_ids:list, is_test_environment:bool = False) -> object:
    """   """
    base_url = INTUIFLOW_TEST_ADDRESS if is_test_environment else INTUIFLOW_PROD_ADDRESS
    token = INTUIFLOW_TEST_TOKEN if is_test_environment else INTUIFLOW_PROD_TOKEN
    url = f"{base_url}/api/v2/planner/orders/pending"

    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
        "api_key": token
    }

    payload = json.dumps([
        # list of order ids
    ])

    response = requests.post(url=url, headers=headers, data=payload)
    return {"status":response.status_code, "reason":response.reason, "data":response.json()}

# ------------------------------------------------------------ #
#                       GET Requests:
# ------------------------------------------------------------ #

def get_pending_orders(is_test_environment:bool = False) -> object:
    """   """
    base_url = INTUIFLOW_TEST_ADDRESS if is_test_environment else INTUIFLOW_PROD_ADDRESS
    token = INTUIFLOW_TEST_TOKEN if is_test_environment else INTUIFLOW_PROD_TOKEN
    url = f"{base_url}/api/v2/planner/orders/pending"

    headers = {
        "api_key": token
    }

    payload = {}

    response = requests.request("GET", url, headers=headers, data=payload)
    return {"status":response.status_code, "reason":response.reason, "data":response.json()}

def get_bom_info(is_test_environment:bool = False) -> object:
    """   """
    base_url = INTUIFLOW_TEST_ADDRESS if is_test_environment else INTUIFLOW_PROD_ADDRESS
    token = INTUIFLOW_TEST_TOKEN if is_test_environment else INTUIFLOW_PROD_TOKEN
    url = f"{base_url}/api/v2/data/billofmaterials"

    headers = {
        "api_key": token
    }

    payload = {}

    response = requests.request("GET", url, headers=headers, data=payload)
    return {"status":response.status_code, "reason":response.reason, "data":response.json()}

def get_routing_info(is_test_environment:bool = False) -> object:
    """   """
    base_url = INTUIFLOW_TEST_ADDRESS if is_test_environment else INTUIFLOW_PROD_ADDRESS
    token = INTUIFLOW_TEST_TOKEN if is_test_environment else INTUIFLOW_PROD_TOKEN
    url = f"{base_url}/api/v2/data/routingitems"

    headers = {
        "api_key": token
    }

    payload = {}

    response = requests.request("GET", url, headers=headers, data=payload)
    return {"status":response.status_code, "reason":response.reason, "data":response.json()}

def get_open_wo(is_test_environment:bool = False) -> object:
    """   """
    base_url = INTUIFLOW_TEST_ADDRESS if is_test_environment else INTUIFLOW_PROD_ADDRESS
    token = INTUIFLOW_TEST_TOKEN if is_test_environment else INTUIFLOW_PROD_TOKEN
    url = f"{base_url}/api/v2/scheduling/orders?includeClosed=false&withRoot=false"

    headers = {
        "api_key": token
    }

    payload = {}

    response = requests.request("GET", url, headers=headers, data=payload)
    return {"status":response.status_code, "reason":response.reason, "data":response.json()}

def get_open_rope_items(is_test_environment:bool = False) -> object:
    """   """
    base_url = INTUIFLOW_TEST_ADDRESS if is_test_environment else INTUIFLOW_PROD_ADDRESS
    token = INTUIFLOW_TEST_TOKEN if is_test_environment else INTUIFLOW_PROD_TOKEN
    url = f"{base_url}/api/v2/scheduling/orders/ropeitems?withRoot=false"

    headers = {
        "api_key": token
    }

    payload = {}

    response = requests.request("GET", url, headers=headers, data=payload)
    return {"status":response.status_code, "reason":response.reason, "data":response.json()}

def get_bom_names(is_test_environment:bool = False) -> object:
    """   """
    base_url = INTUIFLOW_TEST_ADDRESS if is_test_environment else INTUIFLOW_PROD_ADDRESS
    token = INTUIFLOW_TEST_TOKEN if is_test_environment else INTUIFLOW_PROD_TOKEN
    url = f"{base_url}/api/v2/data/supplyorders?raw=false"

    headers = {
        "api_key": token
    }

    payload = {}

    response = requests.request("GET", url, headers=headers, data=payload)
    return {"status":response.status_code, "reason":response.reason, "data":response.json()}

def get_closed_wo(closed_after:str, is_test_environment:bool = False) -> object:
    """  date must be mm-dd-yyyy, returns orders closed after the date.  """
    base_url = INTUIFLOW_TEST_ADDRESS if is_test_environment else INTUIFLOW_PROD_ADDRESS
    token = INTUIFLOW_TEST_TOKEN if is_test_environment else INTUIFLOW_PROD_TOKEN
    url = f"{base_url}/api/v2/scheduling/orders?includeClosed=true&closedAfter={closed_after}&withRoot=false"

    headers = {
        "api_key": token
    }

    payload = {}

    response = requests.request("GET", url, headers=headers, data=payload)
    return {"status":response.status_code, "reason":response.reason, "data":response.json()}

def get_closed_rope_items(closed_after:str, is_test_environment:bool = False) -> object:
    """   """
    base_url = INTUIFLOW_TEST_ADDRESS if is_test_environment else INTUIFLOW_PROD_ADDRESS
    token = INTUIFLOW_TEST_TOKEN if is_test_environment else INTUIFLOW_PROD_TOKEN
    url = f"{base_url}/api/v2/scheduling/orders/ropeitems?includeClosed=true&closedAfter={closed_after}&withRoot=false"

    headers = {
        "api_key": token
    }

    payload = {}

    response = requests.request("GET", url, headers=headers, data=payload)
    return {"status":response.status_code, "reason":response.reason, "data":response.json()}
