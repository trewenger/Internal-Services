"""
Docstring for Common.Utils.Utils
Purpose: 
-   This file contains various helper functions and utilities that are common to projects and are overall generic.
-   Utilities defined here include but are not limited to:
    - load_query(): Imports an .sql file as a string. 
    - csv_export(): Exports a data set as a csv file.
"""

import os
from pathlib import Path
import pandas

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))  # path to save the csv output
REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_FOLDER = REPO_ROOT / "CSV"

def load_query(filename: str) -> str:
    """
    Searches the entire project directory for an SQL file and returns its contents.
    Query file names must be unique or this could return an unexpected query.
    
    :param filename: The name of the SQL file (with or without .sql extension)
    :return: The SQL query string
    :raises FileNotFoundError: If the file is not found anywhere in the project
    """
    # Ensure the file ends with .sql
    if not filename.endswith(".sql"):
        filename += ".sql"

    # Get the absolute root of the project (where this script is run)
    project_root = os.path.abspath(os.getcwd())

    # Walk through all subdirectories to find the file
    for root, dirs, files in os.walk(project_root):
        if filename in files:
            file_path = os.path.join(root, filename)
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()

    # If not found, raise an error
    raise FileNotFoundError(f"Could not find '{filename}' anywhere under {project_root}")

def csv_export(data, filename, path:str=None) -> None:
    """
    Date: Any json data set.
    Removes the previous CSV file from the CSV folder, then exports the new CSV file. Returns the file path.
    """
    try:
        if not filename:
            filename = "default.csv"
            print("Filename was not supplied. This file name will be: default.csv")
        if not filename.endswith(".csv"):
            print("Appending .csv to the supplied file name. ")
            filename = f"{filename}.csv"

        # CSV Names
        if not path:
            csv_file = os.path.join(CSV_FOLDER, filename)
        else:
            csv_file = os.path.join(path, filename)

        # Removing old CSV files. 
        print(f"Deleting old CSV file(s) named {filename} ")
        if os.path.exists(csv_file):
            os.remove(csv_file)
    except Exception as e:
        print("The following exemption occured: {e} \n Failed to delete old CSV files. No new files were created. ")
        return e

    try:
        print("Exporting data as a csv. ")
        headers = data[0].keys()
        framed = pandas.DataFrame(data, columns=headers)
        framed.to_csv(csv_file, index=False)  # index=False omits the row numbers
        print(f"Success. CSV file exported as: {filename}")
        return csv_file
    except Exception as e:
        print(f"Failed to export the CSV files. The old files were deleted. Reason: \n {e}")
        return e
    