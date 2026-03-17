import json
import os
import time
from datetime import datetime
from typing import Dict, Optional
import threading
import requests
from dotenv import load_dotenv
import base64
from config import Config

load_dotenv()

class InventoryData:
    """ Manages RIM config settings """
    def __init__(self):
        # defining the json file location
        rim_dir = os.path.dirname(os.path.abspath(__file__))
        self.filepath = os.path.join(rim_dir, 'data.json')

        self.lock = threading.Lock()
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        # Check if file exists and is valid
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    content = f.read().strip()
                    if content:
                        json.loads(content)  # Validate it's valid JSON
                        return
            except (json.JSONDecodeError, IOError):
                pass  # File is corrupted, will recreate below
        
        # Create or recreate the file
        initial_data = {
            "config": {
                "last_sync_run": None,
                "last_check_run": None,
                "sync_interval_minutes": 5,
                "sales_interval_minutes": 180,
                "auto_sync_enabled": False,
                "inventory_method": "automated"
            },
            "skus": {}
        }
        with open(self.filepath, 'w') as f:
            json.dump(initial_data, f, indent=2)
    
    def _read_data(self) -> dict:
        with self.lock:
            max_retries = 10
            for attempt in range(max_retries):
                try:
                    with open(self.filepath, 'r') as f:
                        data = json.load(f)
                    return data
                except (IOError, json.JSONDecodeError) as e:
                    if attempt < max_retries - 1:
                        time.sleep(0.1)
                    else:
                        raise
    
    def _write_data(self, data:dict):
        with self.lock:
            max_retries = 10
            for attempt in range(max_retries):
                try:
                    # Write to temp file first, then rename (atomic operation)
                    temp_file = self.filepath + '.tmp'
                    with open(temp_file, 'w') as f:
                        json.dump(data, f, indent=2)
                    
                    # Atomic rename
                    if os.path.exists(self.filepath):
                        os.replace(temp_file, self.filepath)
                    else:
                        os.rename(temp_file, self.filepath)
                    break
                except IOError as e:
                    if attempt < max_retries - 1:
                        time.sleep(0.1)
                    else:
                        raise
    
    def get_all_skus(self) -> Dict:
        data = self._read_data()
        return data.get('skus', {})
    
    def get_sku(self, sku:str) -> Optional[Dict]:
        skus = self.get_all_skus()
        return skus.get(sku)
    
    def add_sku(self, sku:str, product_name:str, available_qty:int, modified_by:str='system', notes:str='', 
                sn_flag:bool=False, part_num:str=None) -> Dict:
        data = self._read_data()
        
        sku_data = {
            'product_name': product_name,
            'available_qty': available_qty,
            'initial_qty': available_qty,
            'last_modified': datetime.now().isoformat(),
            'modified_by': modified_by,
            'notes': notes,
            'sn_flag':sn_flag,
            'part_num':part_num,
            'orders_processed': 0
        }
        
        data['skus'][sku] = sku_data
        self._write_data(data)
        
        return sku_data
    
    def update_sku(self, sku:str, updates:Dict, modified_by:str='system') -> Optional[Dict]:
        data = self._read_data()
        
        if sku not in data['skus']:
            return None
        
        # Update fields
        for key, value in updates.items():
            if key in ['product_name', 'available_qty', 'notes']:
                data['skus'][sku][key] = value
        
        data['skus'][sku]['initial_qty'] = updates['available_qty']
        data['skus'][sku]['orders_processed'] = 0
        data['skus'][sku]['last_modified'] = datetime.now().isoformat()
        data['skus'][sku]['modified_by'] = modified_by

        self._write_data(data)
        return data['skus'][sku]
    
    def delete_sku(self, sku:str) -> bool:
        data = self._read_data()
        
        if sku not in data['skus']:
            return False
        
        deleted_data = data['skus'].pop(sku)

        self._write_data(data)
        return True
    
    def decrement_sku(self, sku:str, qty:int, orders_count:int=1) -> Optional[Dict]:
        data = self._read_data()
        
        if sku not in data['skus']:
            return None
        
        #print(f'SKU: {sku}, qty: {qty}, orders_count: {orders_count}')
        data['skus'][sku]['available_qty'] -= qty
        data['skus'][sku]['orders_processed'] += orders_count
        data['skus'][sku]['last_modified'] = datetime.now().isoformat()
        data['skus'][sku]['modified_by'] = 'sync'
        
        self._write_data(data)
        return data['skus'][sku]
    
    def get_config(self) -> Dict:
        data = self._read_data()
        return data.get('config', {})
    
    def update_config(self, updates: Dict):
        data = self._read_data()
        data['config'].update(updates)
        self._write_data(data)
    
    # these are all former methods of this class, but have moved or need to move to the logging class below.
    """
    def get_audit_log(self, limit: int = 50) -> list:
        data = self._read_data()
        return data.get('audit_log', [])[-limit:]

    def get_log_stats(self) -> dict:
        data = self._read_data()
        logs = data.get('audit_log', [])
        return {
            'total_logs': data['audit_log_stats'].get('total_logs', 0),
            'last_log': data['audit_log_stats'].get('last_log'),
            'current_logs': len(logs),
        }
    
    def get_log_by_id(self, log_id: int) -> Optional[dict]:
        data = self._read_data()
        logs = data.get('audit_log', [])

        for log in logs:
            if log.get('id') == log_id:
                return log
        return None
    
    def clear_all_logs(self) -> int:
        data = self._read_data()
        log_count = len(data.get('audit_log', []))

        data['audit_log'] = []
        data['audit_log_stats'] = {
            'total_logs': 0,
            'last_log': None
        }

        self._write_data(data)
        return log_count
    """

class Logger:
    """Separate class for managing RIM logs in a dedicated JSON file"""

    def __init__(self):
        # defining the json file location
        rim_dir = os.path.dirname(os.path.abspath(__file__))
        self.filepath = os.path.join(rim_dir, 'log.json')

        self.lock = threading.Lock()
        self._ensure_file_exists()
        self._admin_email = Config.ADMIN_EMAIL
        self._sender_email = Config.SENDER_EMAIL

    def _ensure_file_exists(self):
        """Create the error log file if it doesn't exist"""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    content = f.read().strip()
                    if content:
                        json.loads(content)
                        return
            except (json.JSONDecodeError, IOError):
                pass

        # Create or recreate the file
        initial_data = {
            "errors": [],
            "error_stats": {
                "total_errors": 0,
                "last_error": None
            },
            "logs": [],
            "log_stats": {
                "total_logs": 0,
                "last_log": None
            }
        }
        with open(self.filepath, 'w') as f:
            json.dump(initial_data, f, indent=2)

    def _read_data(self) -> dict:
        """Read error log data with retry logic"""
        with self.lock:
            max_retries = 10
            for attempt in range(max_retries):
                try:
                    with open(self.filepath, 'r') as f:
                        data = json.load(f)
                    return data
                except (IOError, json.JSONDecodeError) as e:
                    if attempt < max_retries - 1:
                        time.sleep(0.1)
                    else:
                        raise

    def _write_data(self, data:dict):
        """Write error log data atomically"""
        with self.lock:
            max_retries = 10
            for attempt in range(max_retries):
                try:
                    temp_file = self.filepath + '.tmp'
                    with open(temp_file, 'w') as f:
                        json.dump(data, f, indent=2)

                    if os.path.exists(self.filepath):
                        os.replace(temp_file, self.filepath)
                    else:
                        os.rename(temp_file, self.filepath)
                    break
                except IOError as e:
                    if attempt < max_retries - 1:
                        time.sleep(0.1)
                    else:
                        raise

    def log_error(self, error_type:str, message:str, source:str='unknown', 
                  details:dict=None, user:str='system') -> dict:
        """
        Log an error to the log file

        Args:
            error_type: Type of error (e.g., 'sync_error', 'api_error', 'database_error')
            message: Error message
            source: Where the error occurred (e.g., 'sync.py', 'app.py')
            details: Additional error details (optional)
            user: User associated with the error (optional)

        Returns:
            The error entry that was logged
        """
        data = self._read_data()

        # helps prevent tons of emails being sent out for the exact same issue. 
        same_error_flag = 0
        errors = data.get('errors', [])
        errors = [e for e in errors if not e.get('resolved', False)]    # unsresolved errors only.
        for e in errors:
            if e['error_type'] == error_type and e['message'] == message and e['source'] == source and e['resolved'] is False:
                same_error_flag = 1
                break
            
        error_entry = {
            'id': data['error_stats']['total_errors'] + 1,
            'timestamp': datetime.now().isoformat(),
            'error_type': error_type,
            'message': message,
            'source': source,
            'user': user,
            'details': details or {},
            'resolved': False
        }

        # Add to errors list
        data['errors'].append(error_entry)

        # Update stats
        data['error_stats']['total_errors'] += 1
        data['error_stats']['last_error'] = datetime.now().isoformat()

        self._write_data(data)

        # creating the error email html body and other params (if new error)
        if same_error_flag == 0:
            email_body_error = "<ul>"
            for key in error_entry.keys():
                email_body_error += f"<li><b>{key}</b>: {error_entry[key]}</li>" 
            email_body_error += "</ul>"

            email_body = f"""The <b>Retail Inventory Manager</b> experienced a new error. Please review and resolve:
            <br><br>
            {email_body_error}
            """
            email_subject = "Error Summary Email: Retail Inventory Manager"
            self.send_email(email_subject, email_body, [self._admin_email])
        same_error_flag = 0

        return error_entry

    def log(self, action:str, sku:str, data:dict, details:dict=None, user:str='system') -> dict:
        """
        Write a log to the json log file

        Args:
            action: Type of action (e.g., 'add', 'update', 'delete')
            sku: The sku the action is being performed on
            data: Dictionary containing the deleted sku data, the updated sku data, or the new sku entry data
            details: A dict with any additional details (optional)
            user: User associated with the change (optional)

        Returns:
            The Log entry dict
        """
        log = self._read_data()

        log_entry = {
            'id': log['log_stats']['total_logs'] + 1,
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'sku': sku,
            'user': user,
            'details': details or {},
            'data': data
        }

        # Add audit log entry
        log['logs'].insert(0, log_entry)

        # Update stats
        log['log_stats']['total_logs'] += 1
        log['log_stats']['last_log'] = datetime.now().isoformat()
        
        self._write_data(log)
        
        return log_entry

    def get_errors(self, limit:int=50, unresolved_only:bool=False) -> list:
        """
        Get error logs

        Args:
            limit: Maximum number of errors to return (most recent)
            unresolved_only: If True, only return unresolved errors

        Returns:
            List of error entries
        """
        data = self._read_data()
        errors = data.get('errors', [])

        if unresolved_only:
            errors = [e for e in errors if not e.get('resolved', False)]

        # Return most recent errors first
        return list(reversed(errors[-limit:]))
    
    def get_logs(self, limit:int=50) -> list:
        """
        Get logs

        Args:
            limit: Maximum number of errors to return (most recent)

        Returns:
            List of error entries
        """
        data = self._read_data()
        logs = data.get('logs', [])

        # Return most recent logs first
        return list(logs[-limit:])

    def get_error_by_id(self, error_id:int) -> Optional[dict]:
        """Get a specific error by ID"""
        data = self._read_data()
        errors = data.get('errors', [])

        for error in errors:
            if error.get('id') == error_id:
                return error
        return None
    
    def get_log_by_id(self, log_id:int) -> Optional[dict]:
        """Get a specific log by ID"""
        data = self._read_data()
        logs = data.get('logs', [])

        for log in logs:
            if log.get('id') == log_id:
                return log
        return None

    def mark_resolved(self, error_id:int, resolved_by:str='system') -> bool:
        """
        Mark an error as resolved

        Args:
            error_id: ID of the error to mark as resolved
            resolved_by: Who resolved the error

        Returns:
            True if successful, False if error not found
        """
        data = self._read_data()
        errors = data.get('errors', [])

        for error in errors:
            if error.get('id') == error_id:
                error['resolved'] = True
                error['resolved_at'] = datetime.now().isoformat()
                error['resolved_by'] = resolved_by
                self._write_data(data)
                return True

        return False

    def clear_all_errors(self) -> int:
        """
        Clear all errors from the log file

        Returns:
            Number of errors cleared
        """
        data = self._read_data()
        error_count = len(data.get('errors', []))

        data['errors'] = []
        data['error_stats'] = {
            'total_errors': 0,
            'last_error': None
        }

        self._write_data(data)
        return error_count

    def clear_all_logs(self) -> int:
        """
        Clear all logs from the log file

        Returns:
            Number of logs cleared
        """
        data = self._read_data()
        log_count = len(data.get('logs', []))

        data['logs'] = []
        data['log_stats'] = {
            'total_logs': 0,
            'last_log': None
        }

        self._write_data(data)
        return log_count

    def get_error_stats(self) -> dict:
        """Get error statistics"""
        data = self._read_data()
        errors = data.get('errors', [])

        unresolved_count = sum(1 for e in errors if not e.get('resolved', False))

        return {
            'total_errors': data['error_stats'].get('total_errors', 0),
            'last_error': data['error_stats'].get('last_error'),
            'current_errors': len(errors),
            'unresolved_errors': unresolved_count,
            'resolved_errors': len(errors) - unresolved_count
        }
    
    def get_log_stats(self) -> dict:
        """Get log statistics"""
        data = self._read_data()
        return {
            'total_logs': data['log_stats'].get('total_logs', 0),
            'last_log': data['log_stats'].get('last_log'),
            'current_logs': len(data['logs'])
        }
    
    def send_email(self, subject:str, html_body:str, recipients:list, attachments=[], sender=None) -> object:
        """ sends a basic notification email """

        sender = self._sender_email if not sender else sender
        url = "https://api.smtp2go.com/v3/email/send"
        headers = {
            'Content-Type': 'application/json',
            'url': 'https://api.smtp2go.com/v3/',
            'X-Smtp2go-Api-Key': Config.SMTP2GO_API_KEY
        }
        payload = {
            "sender": sender,
            "to": recipients,
            "subject": subject,
            "html_body": html_body
        }
        payload = json.dumps(payload)

        # Convert file paths to base64-encoded attachments if included in method call
        if attachments and len(attachments) > 0:
            encoded_attachments = []
            for filepath in attachments:
                with open(filepath, "rb") as f:
                    file_data = f.read()
                    encoded_attachments.append({
                        "filename": os.path.basename(filepath),
                        "fileblob": base64.b64encode(file_data).decode("utf-8")
                    })

            payload["attachments"] = encoded_attachments

        response = requests.request("POST", url, headers=headers, data=payload)

        return response
