"""
Docstring for Common.clients.Google.GoogleSession
Purpose: 
-   This session class is used specifically for interaction with Google Sheets.
-   The class provides basic interaction methods, such as edit range, read range, and copy/paste.
-   .env must be loaded in the script importing this client BEFORE importing this client.
"""

from google.oauth2 import service_account
from googleapiclient.discovery import build
import os

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

class GoogleApiException(Exception):
    """
    Custom exception to raise by the GoogleAPI Session Class.
    """
    pass

class GoogleSession:
    """
    Google API Session Class. Used to initialize the sheet, and session instance. 
    """

    def __init__(self, sheet_id:str):
        self._SCOPES = [os.getenv("GOOGLE_SERVICE_SCOPES")]
        self._SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_CREDENTIALS_PATH")
        self._SHEET_ID = sheet_id
        self._SHEET_SERVICE = self._get_sheets_service()
        

    def _get_sheets_service(self):
        """ Authenticates and returns the Google Sheets service client on session init. """
        creds = service_account.Credentials.from_service_account_file(self._SERVICE_ACCOUNT_FILE, scopes=self._SCOPES)
        service = build('sheets', 'v4', credentials=creds)
        return service.spreadsheets()

    def clear_range(self, sheet_name, cell_range) -> None:
        """ Clears the specified cell range in a sheet. """
        self._SHEET_SERVICE.values().clear(
            spreadsheetId=self._SHEET_ID,
            range=f"{sheet_name}!{cell_range}"
        ).execute()

    def update_range(self, sheet_name, cell_range, values) -> None:
        """ Updates (overwrites) a cell range with provided values. """
        self._SHEET_SERVICE.values().update(
            spreadsheetId=self._SHEET_ID,
            range=f"{sheet_name}!{cell_range}",
            valueInputOption="USER_ENTERED",
            body={"values": values}
        ).execute()

    def append_rows(self, sheet_name, start_cell, values):
        """ Appends rows to a specified start location. """
        self._SHEET_SERVICE.values().append(
            spreadsheetId=self._SHEET_ID,
            range=f"{sheet_name}!{start_cell}",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values}
        ).execute()

    def read_range(self, sheet_name, cell_range):
        """ Reads and returns values from the specified range. """

        result = self._SHEET_SERVICE.values().get(
            spreadsheetId=self._SHEET_ID,
            range=f"{sheet_name}!{cell_range}"
        ).execute()
        return result.get('values', [])
    
    def copy_range(self, source_range, dest_range):
        """ Copies data from one range to another (basic manual copy). """
        values = self._SHEET_SERVICE.values().get(
            spreadsheetId=self._SHEET_ID,
            range=source_range
        ).execute().get('values', [])

        self._SHEET_SERVICE.values().update(
            spreadsheetId=self._SHEET_ID,
            range=dest_range,
            valueInputOption="USER_ENTERED",
            body={"values": values}
        ).execute()
        