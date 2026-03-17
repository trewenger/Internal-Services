import pandas
import os
from pathlib import Path
from .data import Logger

# Initialize error logger
error_logger = Logger()

def output_csv(headers:list,  data:list[list], name:str="default.csv") -> str:
    ''' a helper function that takes input data and outputs a csv to outputs/csv_file_name.csv '''
    try:
        # base case
        if not headers or not data or not data[0]:
            raise ValueError("Missing headers or data input.")
        
        # ensure .csv extension
        if not name.lower().endswith('.csv'):
            name += '.csv'
        
        # define output location
        root = Path(__file__).resolve().parent
        output_dir = root / 'output'
        # create the folder if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # csv name init
        output_file = output_dir / name
        if output_file.exists():
            os.remove(output_file)


        framed = pandas.DataFrame(data=data, columns=headers)
        framed.to_csv(output_file, index=False)  # index=False omits the row numbers
        return f'Successfully exported {name} to {output_dir}.'
    except Exception as e:
        error_logger.log_error(
            error_type='csv_export_error',
            message=f"Failed to export CSV file: {str(e)}",
            source='RetailInventoryManager/modules.py:output_csv',
            details={'filename': name, 'error': str(e)}
        )
        return f'Failed to export the csv file: {e}'
    
    
def create_matrix(headers, data) -> list:
    '''
    helper function that creates a 2D array from a list of headers and a dict/obj
    '''
    # base case.
    if not headers or not data:
        return None
    
    try:
        result = []
        result.append(headers)
        for row in data:
            cur_row = []
            for header in headers:
                cur_row.append(row[header])
            result.append(cur_row)

            # adding 100 SN as their own rows per the upload requirements
            if row["SnFlag"] == True:
                for i in range(int(row["Qty"])):
                    sn_row = []
                    sn_row.append(f'FAKE_SN_{row["PartNumber"]}-{i + 1}')

                    # padding empty column values
                    for _ in range(len(headers) - 1):
                        sn_row.append('')
                    
                    result.append(sn_row)
        return result
    except Exception as e:
        print(f"Unable to create the matrix: {e}")
        error_logger.log_error(
            error_type='matrix_creation_error',
            message=f"Failed to create matrix: {str(e)}",
            source='RetailInventoryManager/modules.py:create_matrix',
            details={'headers': headers, 'data_count': len(data) if data else 0, 'error': str(e)}
        )
        return None