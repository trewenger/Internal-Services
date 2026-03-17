"""
Docstring for Common.clients.fishbowl.FishbowlCalls
Purpose: 
-   This client contains various REST API requests for the Fishbowl Advanced application.
-   Intended to interact with the Fishbowl Advanced Server. 
-   .env must be loaded in the script importing this client BEFORE importing this client.
"""

import requests, json, os

def fb_login(is_test_db) -> object: 
    """
    This function logs into the Fishbowl application. 
    Returns an object: {'token', 'status', 'reason'} or None if it fails.
    """
    # Pulling env configs
    fb_server_address = os.getenv("FISHBOWL_SERVER_ADDRESS")
    fb_port = os.getenv("FISHBOWL_TEST_PORT") if is_test_db else os.getenv("FISHBOWL_PROD_PORT")
    fb_app_name = os.getenv("FISHBOWL_APP_NAME")
    fb_app_description = os.getenv("FISHBOWL_APP_DESCRIPTION")
    fb_app_id = os.getenv("FISHBOWL_APP_ID")
    fb_username = os.getenv("FISHBOWL_USERNAME")
    fb_pw = os.getenv("FISHBOWL_PASSWORD")
    fb_bearer = os.getenv("FISHBOWL_BEARER_TOKEN")

    print(f"""
    Logging in to Fishbowl...
    address: {fb_server_address} 
    port: {fb_port}
    username: {fb_username} 
    app name: {fb_app_name}
    app description: {fb_app_description} 
    app id: {fb_app_id}
    """)

    # POST request configs
    url = f"http://{fb_server_address}:{fb_port}/api/login"
    payload = json.dumps({
    "appName": fb_app_name,
    "appDescription": fb_app_description,
    "appId": fb_app_id,
    "username": fb_username,
    "password": fb_pw
    })
    headers = {
    'Content-Type': 'application/json',
    'Authorization': fb_bearer
    }

    try:
        response = requests.request("POST", url, headers=headers, data=payload)
        response_json = response.json()
        token = response_json.get("token")
        if token:
            try:
                print("Session Created: ", response.status_code, response.reason, response.json().get('message'))
            except:
                print("Session Created: ", response.status_code, response.reason)
        else:
            print(f"No token in the response: {response.status_code, response.reason, response.json().get("message")}")

        return {"token":token, "status":response.status_code, "reason":response.reason}
    except Exception as e:
        print(f"Login error: {e}")
        return None


def fb_logout(token:str, is_test_db:bool = False) -> object: 
    """
    Logs out of the current session of Fishbowl and invalidates the current API token. 
    Returns an object: {'status', 'reason'}
    """
    fb_server_address = os.getenv("FISHBOWL_SERVER_ADDRESS")
    fb_port = os.getenv("FISHBOWL_TEST_PORT") if is_test_db else os.getenv("FISHBOWL_PROD_PORT")
    url = f"http://{fb_server_address}:{fb_port}/api/logout"

    payload = {}
    headers = {
    'Authorization': 'Bearer ' + str(token)
    }

    response = requests.request("POST", url, headers=headers, data=payload)
    print("Logout: ", response.status_code, response.reason)
    return {"status":response.status_code, "reason":response.reason}


def fb_query(token:str, query:str, is_test_db:bool = False) -> object:
    """
    Queries the Fishbowl database using a MySQL Query passed as a long string. 
    returns an object: {'data', 'status', 'reason'}
    """
    fb_server_address = os.getenv("FISHBOWL_SERVER_ADDRESS")
    fb_port = os.getenv("FISHBOWL_TEST_PORT") if is_test_db else os.getenv("FISHBOWL_PROD_PORT")
    url = f"http://{fb_server_address}:{fb_port}/api/data-query"

    payload = str(query)
    headers = {
    'Content-Type': 'text/plain',
    'Authorization': 'Bearer ' + str(token)
    }
    
    response = requests.request("GET", url, headers=headers, data=payload)
    print("Query: ", response.status_code, response.reason)
    data = None if not response.content else json.loads(response.content)
    return {"data": data,"status":response.status_code, "reason":response.reason}


def fb_inventory_cycle_import(token:str, data:json, is_test_db:bool = False) -> object:
    """ 
    Allows JSON formatted data to be imported to Fishbowl for inventory cycling. 
    Use 2D-Arrays/Matrix for data. Returns the POST response.
    """

    fb_server_address = os.getenv("FISHBOWL_SERVER_ADDRESS")
    fb_port = os.getenv("FISHBOWL_TEST_PORT") if is_test_db else os.getenv("FISHBOWL_PROD_PORT")
    url = f"http://{fb_server_address}:{fb_port}/api/import/Cycle-Count-Data"

    headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + str(token)
    }
    
    # Py list to JSON string.
    payload = json.dumps(data)
    
    response = requests.request("POST", url, headers=headers, data=payload)
    print("Response: ", response.status_code, response.reason)
    return response


def fb_create_mo(token:str, data:json, is_test_db:bool = False) -> object:
    """ 
    TBD. Not currently functioning. Do not use. 
    """
    return
    fb_server_address = os.getenv("FISHBOWL_SERVER_ADDRESS")
    fb_port = os.getenv("FISHBOWL_TEST_PORT") if is_test_db else os.getenv("FISHBOWL_PROD_PORT")
    url = f"http://{fb_server_address}:{fb_port}/api/import/Cycle-Count-Data"

    headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + str(token)
    }

    # Py list to JSON string.
    payload = json.dumps(data)
    
    response = requests.post(url, headers=headers, data=payload)
    print("Response: ", response.status_code, response.reason)
    return {"status":response.status_code, "reason":response.reason}
