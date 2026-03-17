"""
Docstring for Common.clients.Microsoft.GraphSession
Purpose: 
-   This common module is still in testing. 
-   The class provides basic interactivity with the Microsoft Graph API.
-   Class methods provide basic functionality such as selecting, reading, and editing documents.
-   .env must be loaded in the script importing this client BEFORE importing this client.
"""

import msal
import requests
import re
import os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
from cryptography.hazmat.backends import default_backend


class GraphSession:
    """ 
    A verified session of the customer Graph API application used to define and authenticate calls
    via a self-signed certificate.  
    """
    base_url = "https://graph.microsoft.com/v1.0"

    def __init__(self, user_principle_name:str, OneDrive_file_path:str):
        # === Azure App / Cert info ===
        self._TENANT_ID = os.getenv("GRAPH_TENANT_ID")
        self._CLIENT_ID = os.getenv("GRAPH_CLIENT_ID")
        self._PFX_PATH = os.getenv("GRAPH_PFX_PATH")
        self._PFX_PASSWORD = os.getenv("GRAPH_PFX_PASSWORD")
        self._PFX_THUMBPRINT = os.getenv("GRAPH_PFX_THUMBPRINT")
        self._AUTHORITY = f"https://login.microsoftonline.com/{self._TENANT_ID}"

        # === Graph settings ===
        self._SCOPES = ["https://graph.microsoft.com/.default"]

        # === MSAL App with cert-based auth ===
        self._app = msal.ConfidentialClientApplication(
            self._CLIENT_ID,
            authority=self._AUTHORITY,
            client_credential={
                "private_key": (
                    load_key_and_certificates(
                        data=open(self._PFX_PATH, "rb").read(),
                        password=self._PFX_PASSWORD.encode(),
                        backend=default_backend()
                    )[0].private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption()
                    ).decode()
                ),
                "thumbprint": self._PFX_THUMBPRINT
            }
        )

        self._result = self._app.acquire_token_for_client(self._SCOPES)
        if "access_token" not in self._result:
            raise Exception("Could not acquire token: %s" % self._result)
        self._access_token = self._result["access_token"]

        self._HEADERS = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "Application/json"
        }

        self._DRIVE_ID = self._set_drive_id(user_principle_name)
        self._ITEM_ID = self._set_item_id(OneDrive_file_path)


    def _set_drive_id(self, user_principal_name:str):
        """
        Docstring for _set_drive_id
        Internal method used during init or the change document method.
        :param self: Description
        :param user_principal_name: Description
        :type user_principal_name: str
        """
        url = f"{self.base_url}/users/{user_principal_name}/drive"
        response = requests.get(url, headers=self._HEADERS)
        response.raise_for_status()
        drive_info = response.json()
        print(f"Drive ID Set: {drive_info["id"]}")
        return drive_info["id"]

    def _set_item_id(self, file_path):
        """
        Internal method.
        Given a OneDrive/SharePoint drive ID and a file path, return the item's unique ID.
        Example file_path: 'Shared Documents/Folder/MyFile.xlsx'
        """
        url = f"{self.base_url}/drives/{self._DRIVE_ID}/root:/{file_path}"
        response = requests.get(url, headers=self._HEADERS)
        response.raise_for_status()
        data = response.json()
        print(f"Item ID Set: {data.get("id")}")
        print(f"Item name: {data.get("name")}")
        return data.get("id")

    def change_document(self, user_principle_name:str, OneDrive_file_path:str):
        """ Allows you to change the document in the current API session. """
        self._DRIVE_ID = self._set_drive_id(user_principle_name)
        self._ITEM_ID = self._set_item_id(OneDrive_file_path)

    def get_excel_range(self, sheet_name, cell_range):
        """
        Reads a range of cells from an Excel workbook in OneDrive.
        :param sheet_name: Name of the sheet.
        :param cell_range: Excel-style range, e.g. 'A1:C5'.
        """
        url = f"{self.base_url}/drives/{self._DRIVE_ID}/items/{self._ITEM_ID}/workbook/worksheets/{sheet_name}/range(address='{cell_range}')"
        resp = requests.get(url, headers=self._HEADERS)
        resp.raise_for_status()
        return resp.json()

    def update_excel_range(self, sheet_name, top_left_cell, values):
        """
        Update values in a given Excel range.
        :param sheet_name: Name of the sheet.
        :param cell_range: Excel-style range, e.g. 'A1:C5'.
        :param values: A 2D list (rows of columns), e.g. '[[A1, B1], [A2, B2]]'.
        """

        header_row_len = len(values[0])
        for index, i in enumerate(values):
            if len(i) != header_row_len:
                raise Exception(f"The data is not symmetric. Pad missing data in row {index + 1}")

        match = re.match(r"([A-Za-z]+)(\d+)", top_left_cell)
        if match:
            start_col, start_row = match.groups()

        end_col = chr(ord(start_col) + (len(values[0])-1))
        end_row = int(start_row) + len(values) - 1
        cell_range = f"{start_col}{start_row}:{end_col}{end_row}"
        print(f"cell range: {cell_range}")

        url = f"{self.base_url}/drives/{self._DRIVE_ID}/items/{self._ITEM_ID}/workbook/worksheets/{sheet_name}/range(address='{cell_range}')"
        body = {"values": values}
        res = requests.patch(url, headers=self._HEADERS, json=body)
        res.raise_for_status()
        return res.json()
    