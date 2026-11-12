"""
Docstring for Common.clients.Microsoft.GraphSession
Purpose:
-   This common module is still in testing.
-   The class provides basic interactivity with the Microsoft Graph API for both OneDrive
    and SharePoint (sites, document libraries, and lists).
-   Class methods provide basic functionality such as selecting, reading, and editing
    documents, and reading/writing SharePoint list items.
-   Auth is app-only via a self-signed PFX certificate (MSAL confidential client).
-   .env must be loaded in the script importing this client BEFORE importing this client.
"""

import msal
import requests
import re
import os
import time
from datetime import datetime
from urllib.parse import urlparse, unquote, quote
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
from cryptography.hazmat.backends import default_backend


class GraphSession:
    """                                                                                                                                                                                                                                                            
    A verified session of the Graph API application used to define and authenticate calls
    via a self-signed certificate. Authenticates on init; OneDrive files or SharePoint sites are
    opened explicitly afterward via open_onedrive_file() / open_sharepoint_site().
    """
    base_url = "https://graph.microsoft.com/v1.0"

    def __init__(self):
        # === Azure App / Cert info ===
        self._TENANT_ID = os.getenv("GRAPH_TENANT_ID")
        self._CLIENT_ID = os.getenv("GRAPH_CLIENT_ID")
        self._PFX_PATH = os.getenv("GRAPH_PFX_PATH")
        self._PFX_PASSWORD = os.getenv("GRAPH_PFX_PASSWORD")
        self._PFX_THUMBPRINT = os.getenv("GRAPH_PFX_THUMBPRINT")
        self._APP_NAME = os.getenv("GRAPH_APP_NAME")
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
            raise Exception(f"[{self._APP_NAME}] Could not acquire token: {self._result}")
        self._access_token = self._result["access_token"]

        self._HEADERS = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json"
        }

        # Active context - set via open_onedrive_file() / open_sharepoint_site()
        self._SITE_ID = None
        self._DRIVE_ID = None
        self._ITEM_ID = None

    @staticmethod
    def _raise_for_status(response: requests.Response) -> requests.Response:
        """
        Internal method. Like response.raise_for_status(), but includes the response body in
        the raised exception - Graph error responses carry a specific error.code/message that
        raise_for_status() alone discards, which is usually the only way to tell (for example)
        a permission-scope 403 apart from a list-setting/compliance-hold 403.
        """
        if not response.ok:
            raise requests.exceptions.HTTPError(
                f"{response.status_code} {response.reason} for url: {response.url}\n{response.text}",
                response=response
            )
        return response

    # Throttling / transient-failure handling (used by _get_all_pages and the generic methods below).
    _RETRY_STATUSES = {429, 503, 504}
    _MAX_RETRIES = 5
    _REQUEST_TIMEOUT = 120

    @staticmethod
    def _retry_delay(headers: dict, attempt: int) -> float:
        """ Internal method. Seconds to wait before a retry: honors Retry-After, else exponential backoff. """
        retry_after = (headers or {}).get("Retry-After") or (headers or {}).get("retry-after")
        try:
            return min(float(retry_after), 120.0)
        except (TypeError, ValueError):
            return min(2.0 ** attempt, 60.0)

    def _send(self, method: str, url: str, headers: dict = None, **kwargs) -> requests.Response:
        """
        Internal method. Sends a request, retrying on 429/503/504 (honoring Retry-After) up to
        _MAX_RETRIES times. Does NOT raise on error status - callers decide (_raise_for_status or
        inspect the status themselves).
        """
        headers = headers or self._HEADERS
        response = None
        for attempt in range(self._MAX_RETRIES + 1):
            response = requests.request(method, url, headers=headers, timeout=self._REQUEST_TIMEOUT, **kwargs)
            if response.status_code not in self._RETRY_STATUSES or attempt == self._MAX_RETRIES:
                return response
            time.sleep(self._retry_delay(response.headers, attempt))
        return response

    def _get_all_pages(self, url: str, headers: dict = None) -> list:
        """
        Internal method. Follows @odata.nextLink pagination and returns the combined 'value' list.
        Retries throttled (429/503/504) pages per Retry-After.
        """
        results = []
        while url:
            response = self._raise_for_status(self._send("GET", url, headers=headers))
            data = response.json()
            results.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return results

    # ------------------------------------------------------------------
    # OneDrive (user drive) files
    # ------------------------------------------------------------------

    def open_onedrive_file(self, user_principal_name: str, file_path: str):
        """ Opens a file in a specific user's OneDrive, making it the active drive/item. """
        self._SITE_ID = None
        self._DRIVE_ID = self._get_user_drive_id(user_principal_name)
        self._ITEM_ID = self._get_item_id(self._DRIVE_ID, file_path)

    def _get_user_drive_id(self, user_principal_name: str) -> str:
        """ Internal method. Resolves a user's OneDrive drive ID from their principal name. """
        url = f"{self.base_url}/users/{user_principal_name}/drive"
        response = self._raise_for_status(requests.get(url, headers=self._HEADERS))
        return response.json()["id"]

    # ------------------------------------------------------------------
    # SharePoint site / document library resolution
    # ------------------------------------------------------------------

    def open_sharepoint_site(self, hostname: str, site_path: str, library_name: str = None, file_path: str = None):
        """
        Resolves a SharePoint site by hostname + server-relative site path, and sets its
        document library as the active drive.
        :param hostname: e.g. 'contoso.sharepoint.com'
        :param site_path: server-relative site path, e.g. '/sites/TeamSite'
        :param library_name: Optional document library display name. Defaults to the site's default library.
        :param file_path: Optional path within the library to open immediately (sets the active item).
        """
        self._SITE_ID = self._get_site_id(hostname, site_path)
        self._DRIVE_ID = self._get_site_drive_id(library_name)
        self._ITEM_ID = self._get_item_id(self._DRIVE_ID, file_path) if file_path else None

    def _get_site_id(self, hostname: str, site_path: str) -> str:
        """ Internal method. Resolves a SharePoint site ID from hostname + server-relative path. """
        site_path = site_path if site_path.startswith("/") else f"/{site_path}"
        url = f"{self.base_url}/sites/{hostname}:{site_path}"
        response = self._raise_for_status(requests.get(url, headers=self._HEADERS))
        return response.json()["id"]

    def _get_site_drive_id(self, library_name: str = None) -> str:
        """ Internal method. Resolves the active site's document library drive ID. """
        if not self._SITE_ID:
            raise Exception("No active SharePoint site. Call open_sharepoint_site() first.")

        if library_name:
            url = f"{self.base_url}/sites/{self._SITE_ID}/drives"
            response = self._raise_for_status(requests.get(url, headers=self._HEADERS))
            for drive in response.json().get("value", []):
                if drive.get("name") == library_name:
                    return drive["id"]
            raise Exception(f"Document library '{library_name}' not found on site.")

        url = f"{self.base_url}/sites/{self._SITE_ID}/drive"
        response = self._raise_for_status(requests.get(url, headers=self._HEADERS))
        return response.json()["id"]

    def _get_item_id(self, drive_id: str, file_path: str) -> str:
        """ Internal method. Given a drive ID and a file path, return the item's unique ID. """
        url = f"{self.base_url}/drives/{drive_id}/root:/{file_path}"
        response = self._raise_for_status(requests.get(url, headers=self._HEADERS))
        return response.json()["id"]

    def change_document(self, file_path: str):
        """ Switches the active file within the currently active drive (OneDrive or SharePoint library). """
        if not self._DRIVE_ID:
            raise Exception("No active drive. Call open_onedrive_file() or open_sharepoint_site() first.")
        self._ITEM_ID = self._get_item_id(self._DRIVE_ID, file_path)

    # ------------------------------------------------------------------
    # Drive item / file operations (OneDrive and SharePoint libraries)
    # ------------------------------------------------------------------

    def list_drive_items(self, folder_path: str = ""):
        """ Lists files/folders in the active drive at the given folder path ('' = library root). """
        if folder_path:
            url = f"{self.base_url}/drives/{self._DRIVE_ID}/root:/{folder_path}:/children"
        else:
            url = f"{self.base_url}/drives/{self._DRIVE_ID}/root/children"
        return self._get_all_pages(url)

    def download_file(self, file_path: str = None) -> bytes:
        """ Downloads and returns raw bytes for a file. Uses the active item if file_path is omitted. """
        item_id = self._get_item_id(self._DRIVE_ID, file_path) if file_path else self._ITEM_ID
        url = f"{self.base_url}/drives/{self._DRIVE_ID}/items/{item_id}/content"
        response = self._raise_for_status(requests.get(url, headers=self._HEADERS))
        return response.content

    def upload_file(self, file_path: str, content: bytes):
        """ Creates or overwrites a file at the given path in the active drive. Simple upload only (<4MB). """
        url = f"{self.base_url}/drives/{self._DRIVE_ID}/root:/{file_path}:/content"
        headers = {**self._HEADERS, "Content-Type": "application/octet-stream"}
        response = self._raise_for_status(requests.put(url, headers=headers, data=content))
        return response.json()

    def get_excel_range(self, sheet_name, cell_range):
        """
        Reads a range of cells from an Excel workbook in the active drive.
        :param sheet_name: Name of the sheet.
        :param cell_range: Excel-style range, e.g. 'A1:C5'.
        """
        url = f"{self.base_url}/drives/{self._DRIVE_ID}/items/{self._ITEM_ID}/workbook/worksheets/{sheet_name}/range(address='{cell_range}')"
        resp = self._raise_for_status(requests.get(url, headers=self._HEADERS))
        return resp.json()

    def update_excel_range(self, sheet_name, top_left_cell, values):
        """
        Update values in a given Excel range.
        :param sheet_name: Name of the sheet.
        :param top_left_cell: Top-left cell of the target range, e.g. 'A1'.
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

        url = f"{self.base_url}/drives/{self._DRIVE_ID}/items/{self._ITEM_ID}/workbook/worksheets/{sheet_name}/range(address='{cell_range}')"
        body = {"values": values}
        res = self._raise_for_status(requests.patch(url, headers=self._HEADERS, json=body))
        return res.json()

    # ------------------------------------------------------------------
    # SharePoint lists
    # ------------------------------------------------------------------

    def get_lists(self):
        """ Returns all lists (including document libraries) on the active SharePoint site. """
        if not self._SITE_ID:
            raise Exception("No active SharePoint site. Call open_sharepoint_site() first.")
        url = f"{self.base_url}/sites/{self._SITE_ID}/lists"
        return self._get_all_pages(url)

    def get_list_id(self, list_name: str) -> str:
        """ Resolves a SharePoint list's ID from its display name. """
        for lst in self.get_lists():
            if lst.get("name") == list_name or lst.get("displayName") == list_name:
                return lst["id"]
        raise Exception(f"List '{list_name}' not found on site.")

    def get_list_items(self, list_id: str, filter_query: str = None):
        """
        Returns items (with field values) from a SharePoint list.
        :param list_id: The list's Graph ID (see get_list_id()).
        :param filter_query: Optional OData $filter expression, e.g. "fields/Status eq 'Open'".
        """
        url = f"{self.base_url}/sites/{self._SITE_ID}/lists/{list_id}/items?expand=fields"
        if filter_query:
            url += f"&$filter={filter_query}"
        return self._get_all_pages(url)

    def get_list_item(self, list_id: str, item_id: str):
        """ Returns a single SharePoint list item (with field values) by ID. """
        url = f"{self.base_url}/sites/{self._SITE_ID}/lists/{list_id}/items/{item_id}?expand=fields"
        response = self._raise_for_status(requests.get(url, headers=self._HEADERS))
        return response.json()

    def create_list_item(self, list_id: str, fields: dict):
        """ Creates a new item in a SharePoint list. :param fields: column-name/value pairs. """
        url = f"{self.base_url}/sites/{self._SITE_ID}/lists/{list_id}/items"
        body = {"fields": fields}
        response = self._raise_for_status(requests.post(url, headers=self._HEADERS, json=body))
        return response.json()

    def update_list_item(self, list_id: str, item_id: str, fields: dict):
        """
        Updates field values on an existing SharePoint list item. Only fields that are
        writable per the list's own column schema are sent - so callers can pass a full
        fields dict straight from get_list_item()/get_list_items() with just the desired
        column(s) changed, and read-only/system/calculated columns (id, ContentType, Created,
        Author/Editor, AppEditorLookupId, etc.) are stripped automatically regardless of which
        specific fields a given list happens to expose as read-only.
        """
        writable_fields = {
            col["name"] for col in self.get_columns(list_id)
            if not col.get("readOnly") and not col.get("hidden")
        }
        payload = {key: value for key, value in fields.items() if key in writable_fields}
        url = f"{self.base_url}/sites/{self._SITE_ID}/lists/{list_id}/items/{item_id}/fields"
        response = self._raise_for_status(requests.patch(url, headers=self._HEADERS, json=payload))
        return response.json()

    def delete_list_item(self, list_id: str, item_id: str):
        """ Deletes a SharePoint list item. """
        url = f"{self.base_url}/sites/{self._SITE_ID}/lists/{list_id}/items/{item_id}"
        self._raise_for_status(requests.delete(url, headers=self._HEADERS))
        return True

    def get_columns(self, list_id: str):
        """ Returns all columns defined on a SharePoint list. """
        url = f"{self.base_url}/sites/{self._SITE_ID}/lists/{list_id}/columns"
        return self._get_all_pages(url)

    def _get_column(self, list_id: str, column_name: str) -> dict:
        """ Internal method. Resolves a column's definition from its internal or display name. """
        for col in self.get_columns(list_id):
            if col.get("name") == column_name or col.get("displayName") == column_name:
                return col
        raise Exception(f"Column '{column_name}' not found on list.")

    def get_column_choices(self, list_id: str, column_name: str) -> list:
        """ Returns the current allowed values for a Choice-type list column. """
        choice = self._get_column(list_id, column_name).get("choice")
        if choice is None:
            raise Exception(f"Column '{column_name}' is not a Choice column.")
        return choice.get("choices", [])

    def update_column_choices(self, list_id: str, column_name: str, choices: list):
        """
        Replaces the set of allowed values on a Choice-type list column.
        Preserves the column's existing allowTextEntry/displayAs settings.
        :param choices: Full replacement list of allowed values (SharePoint choice columns
            don't support incremental add/remove - the whole set is written each time).
        """
        column = self._get_column(list_id, column_name)
        choice = column.get("choice")
        if choice is None:
            raise Exception(f"Column '{column_name}' is not a Choice column.")

        url = f"{self.base_url}/sites/{self._SITE_ID}/lists/{list_id}/columns/{column['id']}"
        body = {"choice": {**choice, "choices": choices}}
        response = self._raise_for_status(requests.patch(url, headers=self._HEADERS, json=body))
        return response.json()

    # ------------------------------------------------------------------
    # SharePoint list item version history
    # ------------------------------------------------------------------

    # System fields that change on every version regardless of an actual column edit.
    _VERSION_DIFF_IGNORE_FIELDS = {
        "Modified", "Editor", "_UIVersionString", "Edit",
        "LinkTitleNoMenu", "LinkTitle", "ItemChildCount", "FolderChildCount"
    }

    # SharePoint Content Approval moderation status. Only present on lists with
    # "Require Content Approval" enabled (List Settings > Versioning Settings).
    # NOTE: unlike most underscore-prefixed internal names, Graph does not escape this one
    # to "OData__ModerationStatus" here - confirmed via a live pending item that it comes
    # back as "_ModerationStatus" in versions().fields.
    _MODERATION_STATUS_FIELD = "_ModerationStatus"
    _MODERATION_STATUS_APPROVED = 0

    def get_list_item_versions(self, list_id: str, item_id: str):
        """
        Returns all historical versions (full field snapshots) of a SharePoint list item,
        oldest first. Requires version history to be enabled on the list.
        """
        url = f"{self.base_url}/sites/{self._SITE_ID}/lists/{list_id}/items/{item_id}/versions?expand=fields"
        versions = self._get_all_pages(url)
        versions.sort(key=lambda v: v.get("lastModifiedDateTime", ""))
        return versions

    def diff_list_item_versions(self, list_id: str, item_id: str, ignore_fields: set = None,
                                 approved_only: bool = False):
        """
        Compares each consecutive pair of versions for a list item and reports which fields
        changed and their before/after values.
        :param ignore_fields: Field names to exclude from diffing. Defaults to _VERSION_DIFF_IGNORE_FIELDS.
        :param approved_only: Only meaningful on lists with Content Approval enabled. When True,
            an edit that lands in a Pending version is held rather than reported immediately; if a
            later version shows the same content approved, it's reported using THAT version's
            modified_at/modified_by (i.e. approval time/approver, not submission time/submitter).
            If the edit is instead rejected, or is still unresolved as of the last version fetched,
            it's dropped entirely. Lists without Content Approval are unaffected (every fields
            snapshot lacks a moderation status, so every edit is treated as already-approved).
        :return: List of {"modified_at", "modified_by", "changes": {field: {"from": ..., "to": ...}}},
            oldest change first. Versions with no field-level changes (e.g. an ignored-field-only
            edit) are omitted.
        """
        ignore_fields = ignore_fields if ignore_fields is not None else self._VERSION_DIFF_IGNORE_FIELDS
        versions = self.get_list_item_versions(list_id, item_id)

        diffs = []
        pending = None  # most recent unresolved edit, awaiting an approval/rejection version
        for previous, current in zip(versions, versions[1:]):
            prev_fields = previous.get("fields", {})
            curr_fields = current.get("fields", {})
            changed_keys = (set(prev_fields) | set(curr_fields)) - ignore_fields
            if approved_only:
                changed_keys = changed_keys - {self._MODERATION_STATUS_FIELD}
            changes = {
                key: {"from": prev_fields.get(key), "to": curr_fields.get(key)}
                for key in changed_keys
                if prev_fields.get(key) != curr_fields.get(key)
            }
            modified_by = current.get("lastModifiedBy", {}).get("user") or {}
            entry = {
                "modified_at": current.get("lastModifiedDateTime"),
                "modified_by": modified_by.get("displayName"),
                "changes": changes
            }

            if not approved_only:
                if changes:
                    diffs.append(entry)
                continue

            status = curr_fields.get(self._MODERATION_STATUS_FIELD)
            if changes:
                if status is None or status == self._MODERATION_STATUS_APPROVED:
                    diffs.append(entry)
                    pending = None
                else:
                    pending = entry  # awaiting approval - hold until resolved
            elif pending is not None and status is not None:
                if status == self._MODERATION_STATUS_APPROVED:
                    diffs.append({**pending, "modified_at": entry["modified_at"], "modified_by": entry["modified_by"]})
                pending = None  # resolved either way - approved & reported, or rejected & dropped
        return diffs

    @staticmethod
    def _parse_iso(value: str) -> datetime:
        """ Internal method. Parses a Graph ISO 8601 timestamp ('...Z') into a datetime. """
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def get_list_changes_since(self, list_id: str, since: str, ignore_fields: set = None,
                                approved_only: bool = False):
        """
        Returns version changes for every item in a list that was modified at or after `since`.
        :param list_id: The list's Graph ID.
        :param since: ISO 8601 date/time string, e.g. '2026-07-01T00:00:00Z'.
        :param ignore_fields: Field names to exclude from diffing. Defaults to _VERSION_DIFF_IGNORE_FIELDS.
        :param approved_only: Passed through to diff_list_item_versions() - when True, pending/
            rejected edits are excluded, and each reported change's timestamp is the approval
            time rather than the edit time, so `since` is effectively matched against approval
            date, not edit date.
        :return: List of {"item_id", "changes": [...]} for items with at least one change at or
            after `since`. `changes` entries match diff_list_item_versions()'s format. Note: the
            initial item lookup filters on the list's Modified column via OData $filter, which
            requires that column to be indexed on large lists.
        """
        since_dt = self._parse_iso(since)
        modified_items = self.get_list_items(list_id, filter_query=f"fields/Modified ge '{since}'")

        results = []
        for item in modified_items:
            item_id = item["id"]
            diffs = self.diff_list_item_versions(list_id, item_id, ignore_fields=ignore_fields,
                                                   approved_only=approved_only)
            diffs = [d for d in diffs if d.get("modified_at") and self._parse_iso(d["modified_at"]) >= since_dt]
            if diffs:
                results.append({"item_id": item_id, "changes": diffs})
        return results

    # ------------------------------------------------------------------
    # Generic, stateless lookups (sites, libraries, directory) + batching.
    # These do NOT touch the active _SITE_ID/_DRIVE_ID/_ITEM_ID context.
    # ------------------------------------------------------------------

    _GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
    # Path segments that mark a page/library/list URL rather than the site itself.
    _SITE_URL_STOP_SEGMENTS = ("/_layouts/", "/forms/", "/sitepages/", "/lists/", "/shared documents")

    @classmethod
    def parse_site_url(cls, site_url: str) -> tuple:
        """
        Splits a SharePoint site URL into (hostname, server_relative_path). Tolerates trailing
        slashes, query strings, and pasted page/library URLs (e.g. '.../Shared Documents/Forms/AllItems.aspx'),
        which are trimmed back to the site. Root sites return path ''.
        :param site_url: e.g. 'https://contoso.sharepoint.com/sites/CompanyHub'
        """
        parsed = urlparse((site_url or "").strip())
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"Invalid SharePoint site URL: '{site_url}'")
        path = unquote(parsed.path or "")
        lowered = path.lower() + "/"
        cut = len(path)
        for stop in cls._SITE_URL_STOP_SEGMENTS:
            idx = lowered.find(stop)
            if idx != -1:
                cut = min(cut, idx)
        path = path[:cut]
        if path.lower().endswith(".aspx"):
            path = path.rsplit("/", 1)[0]
        return parsed.netloc.lower(), path.rstrip("/")

    def get_site_by_url(self, site_url: str) -> dict:
        """
        Resolves a SharePoint site from its URL.
        :return: {"id", "site_guid", "web_guid", "web_url", "display_name", "hostname"}. The Graph
            site id has the form 'hostname,siteGuid,webGuid'.
        """
        hostname, path = self.parse_site_url(site_url)
        if path:
            url = f"{self.base_url}/sites/{hostname}:{quote(path)}"
        else:
            url = f"{self.base_url}/sites/{hostname}"
        site = self._raise_for_status(self._send("GET", url)).json()
        parts = site["id"].split(",")
        if len(parts) != 3:
            raise Exception(f"Unexpected site id format from Graph: '{site['id']}'")
        return {
            "id": site["id"],
            "hostname": parts[0],
            "site_guid": parts[1],
            "web_guid": parts[2],
            "web_url": site.get("webUrl"),
            "display_name": site.get("displayName"),
        }

    def list_site_drives(self, site_id: str) -> list:
        """ Returns every document library (drive) on a site: [{"id", "name", "web_url", "drive_type"}]. """
        url = f"{self.base_url}/sites/{site_id}/drives?$select=id,name,webUrl,driveType"
        return [
            {"id": d["id"], "name": d.get("name"), "web_url": d.get("webUrl"), "drive_type": d.get("driveType")}
            for d in self._get_all_pages(url)
        ]

    def get_drive_list_id(self, site_id: str, drive_id: str) -> str:
        """ Returns the SharePoint list ID backing a document library (drive). """
        url = f"{self.base_url}/sites/{site_id}/drives/{drive_id}/list?$select=id"
        return self._raise_for_status(self._send("GET", url)).json()["id"]

    def get_user(self, upn_or_id: str, select: list = None):
        """
        Returns a user by UPN or object ID, or None if the user does not exist (404).
        :param select: Optional list of properties to $select.
        """
        url = f"{self.base_url}/users/{quote(upn_or_id, safe='@')}"
        if select:
            url += f"?$select={','.join(select)}"
        response = self._send("GET", url)
        if response.status_code == 404:
            return None
        return self._raise_for_status(response).json()

    def list_users(self, filter_query: str = None, select: list = None) -> list:
        """
        Returns all users matching an optional OData $filter (paged).
        :param filter_query: e.g. "accountEnabled eq true and userType eq 'Member'"
        :param select: Optional list of properties to $select.
        """
        params = ["$top=999"]
        if filter_query:
            params.append(f"$filter={quote(filter_query, safe='=')}")
        if select:
            params.append(f"$select={','.join(select)}")
        return self._get_all_pages(f"{self.base_url}/users?{'&'.join(params)}")

    def get_group(self, name_or_id: str) -> dict:
        """
        Returns a group ({"id", "displayName", ...}) by object ID or exact display name.
        Raises if no group, or more than one group, matches the display name.
        """
        name_or_id = (name_or_id or "").strip()
        if self._GUID_RE.match(name_or_id):
            url = f"{self.base_url}/groups/{name_or_id}?$select=id,displayName,mail"
            response = self._send("GET", url)
            if response.status_code == 404:
                raise ValueError(f"Group not found: '{name_or_id}'")
            return self._raise_for_status(response).json()

        escaped = name_or_id.replace("'", "''")
        flt = "displayName eq '" + escaped + "'"
        url = f"{self.base_url}/groups?$filter={quote(flt, safe='=')}&$select=id,displayName,mail"
        groups = self._get_all_pages(url)
        if not groups:
            raise ValueError(f"Group not found: '{name_or_id}'")
        if len(groups) > 1:
            raise ValueError(f"More than one group is named '{name_or_id}' - use the group's object ID instead")
        return groups[0]

    def list_group_transitive_users(self, group_id: str, select: list = None) -> list:
        """
        Returns every user in a group, including members of nested groups (paged).
        Non-user members (devices, service principals, the nested groups themselves) are excluded.
        """
        params = ["$top=999", "$count=true"]
        if select:
            params.append(f"$select={','.join(select)}")
        url = f"{self.base_url}/groups/{group_id}/transitiveMembers/microsoft.graph.user?{'&'.join(params)}"
        # OData type-cast segments are an advanced query - requires ConsistencyLevel + $count.
        headers = {**self._HEADERS, "ConsistencyLevel": "eventual"}
        return self._get_all_pages(url, headers=headers)

    def batch(self, requests_: list) -> list:
        """
        Sends many Graph requests via JSON batching (POST /$batch, 20 per call). Individual
        responses that are throttled (429/503/504) are retried per their Retry-After, up to
        _MAX_RETRIES times.
        :param requests_: [{"method": "GET|POST|PATCH|DELETE", "url": "/users/{id}/drive/...",
            "body": {...} (optional), "headers": {...} (optional)}]. URLs are relative to /v1.0.
        :return: One entry per request, in the same order: {"status": int, "headers": dict, "body": dict|None}.
            Never raises for per-request errors - inspect "status" (and body["error"]["code"]).
        """
        results = [None] * len(requests_)
        pending = list(range(len(requests_)))
        attempt = 0

        while pending:
            retry, delay = [], 0.0
            for start in range(0, len(pending), 20):
                chunk = pending[start:start + 20]
                payload = {"requests": []}
                for idx in chunk:
                    req = requests_[idx]
                    entry = {"id": str(idx), "method": req["method"].upper(), "url": req["url"]}
                    if req.get("body") is not None:
                        entry["body"] = req["body"]
                        entry["headers"] = {"Content-Type": "application/json", **(req.get("headers") or {})}
                    elif req.get("headers"):
                        entry["headers"] = req["headers"]
                    payload["requests"].append(entry)

                response = self._raise_for_status(self._send("POST", f"{self.base_url}/$batch", json=payload))
                for item in response.json().get("responses", []):
                    idx = int(item["id"])
                    status = int(item.get("status", 0))
                    result = {"status": status, "headers": item.get("headers") or {}, "body": item.get("body")}
                    if status in self._RETRY_STATUSES and attempt < self._MAX_RETRIES:
                        retry.append(idx)
                        delay = max(delay, self._retry_delay(result["headers"], attempt))
                    results[idx] = result

            pending = sorted(retry)
            if pending:
                attempt += 1
                time.sleep(delay)

        return results

    @staticmethod
    def batch_error_code(result: dict) -> str:
        """ Returns the Graph error code ('nameAlreadyExists', 'itemNotFound', ...) from a batch() result, or ''. """
        body = result.get("body") if isinstance(result, dict) else None
        if isinstance(body, dict):
            return (body.get("error") or {}).get("code", "") or ""
        return ""

    @staticmethod
    def batch_error_message(result: dict) -> str:
        """ Returns a readable 'status code: message' string for a failed batch() result. """
        body = result.get("body") if isinstance(result, dict) else None
        err = (body.get("error") or {}) if isinstance(body, dict) else {}
        return f"{result.get('status')} {err.get('code', '')}: {err.get('message', '')}".strip()
