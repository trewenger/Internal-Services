"""
Docstring for Common.Utils.Logging
Purpose: 
-   This class provides basic session logging functionality for consistent use across various projects. 
-   The class starts a session, which tracks its own error logs, error flag, and provides methods to interact with the log.
"""

class SessionLog:
    """
    A session log that keeps track of errors and run state.
    """

    def __init__(self):
        self._error_flag = 0
        self._logs = {}

    def log(self, func_name:str, message:str, is_error:bool = False) -> None:
        """
        Prints and adjusts the logs attribute to track function specific run results. Set the is_error param 
        to True to change the error_flag to 1. Returns None. 
        """

        print(message)

        if is_error:
            self._error_flag = 1

        if func_name not in self._logs:
            self._logs[str(func_name)] = []
        self._logs[str(func_name)].append(str(message))

    def get_log(self) -> object:
        return self._logs
    
    def error_flag(self) -> int:
        return self._error_flag
    
    def set_error_flag(self) -> None:
        self._error_flag = 1
        return
    
    def remove_error_flag(self) -> None:
        self._error_flag = 0
        return