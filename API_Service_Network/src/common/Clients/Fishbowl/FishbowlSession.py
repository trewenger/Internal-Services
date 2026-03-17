"""
Docstring for Common.clients.fishbowl.FishbowlSession
Purpose: 
-   This client contains a session class that manages an active Fishbowl Advanced connection.
-   Intended to interact with the Fishbowl Advanced Server utilizing calls from FishbowlCalls.py
-   .env must be loaded in the script importing this client BEFORE importing this client.
"""

from common.Clients.Fishbowl.FishbowlCalls import *
import time

class CallFailure(Exception):
    """Custom exception to return on call failure"""
    pass

class FishbowlSession:
    """
    This class creates an active fishbowl login session and provides
    methods for each of the fishbowl API calls. Instantiating automatically logs in.
    - is_test_db: default=False, set to connect to the test database instance of Fishbowl Advanced.
    - auto_login: default=True, unset to stop auto-login.
    - login_attempts: default=5, used to set the number of times it will attempt to connect to the Fishbowl DB. 0 means no retries.
    - attempt_wait_secs: default=300, the number of seconds between each failed login attempt.
    """
    def __init__(self, is_test_db:bool = False, auto_login:bool = True, login_attempts:int = 5, attempt_wait_secs:int = 300):
        self._is_test_db = is_test_db
        self._login_attemps = login_attempts
        self._attempts_wait = attempt_wait_secs
        try:
            self._token = self.login() if auto_login else None
            if self._token:
                self._is_active = True
            else:
                self._is_active = False
                print("Fishbowl session is not logged in. ")
        except Exception as e:
            print(e)
            self._token = None
            self._is_active = False

        self._call_count = 0


    def login(self) -> str:
        """
        This method is used when creating a FishbowlSession class or explicitly called when auto_login=False.
        Returns the FishbowlSession token or None if failure.
        """
        logged_in = False
        retry_counter = self._login_attemps
        # try to login repeatedly if session enables this feature.
        while logged_in is False and retry_counter > 0:
            print(f"Fishbowl login attempts remaining {retry_counter}")
            result = fb_login(self._is_test_db)
            if result and result["token"]:
                print("Logged In successfully")
                logged_in = True
                return result["token"]
            else:
                retry_counter -= 1
                print(f"Login Failed. Waiting for {self._attempts_wait} seconds before next login attempt.")
                time.sleep(self._attempts_wait)
        
        return None


    def is_logged_in(self) -> bool:
        """
        This method returns the current session's is_active flag. 
        True = active, False = inactive.
        """
        return self._is_active 


    def logout(self) -> object:
        """
        This method logs out of the current Fishbowl session connection. 
        Returns {status, reason}
        """
        if self._is_active:
            result = fb_logout(self._token, self._is_test_db)
            if result["reason"] == "OK":
                self._call_count += 1
                self._is_active = False
                self._token = None
                return result
            else:
                print(result["status"], result["reason"])
                raise CallFailure
        else:
            print("Fishbowl is already logged out or inactive. ")
            return {"status":200, "reason":"OK"}


    def query(self, sql:str) -> object:
        """
        Returns the JSON response from a specified MySQL query against the 
        Fishbowl database if successful, and the reason code and reason if not. 
        Auto logout on failure.
        returns {data, status, reason}.
        """ 
        if not self.is_logged_in():
            raise Exception("Fishbowl session is logged out or inactive.")
        
        result = fb_query(self._token, sql, self._is_test_db)
        if result["reason"] == "OK":
            self._call_count += 1
            return result
        else:
            print(result["status"], result["reason"], result["data"])
            self.logout()
            raise CallFailure
        

    def cycle_inventory(self, data) -> object:
        """
        Bulk cycles inventory into fishbowl using the Cycle Count Import method. 
        Auto logout on failure. Returns the API POST request response.
        data must be a 2D-array/matrix. Returns the response and reason code if failure. 
        """
        result = fb_inventory_cycle_import(self._token, data, self._is_test_db)

        if result.reason == "OK":
            self._call_count += 1
            return result
        else:
            print(result.content)
            self.logout()
            raise CallFailure
