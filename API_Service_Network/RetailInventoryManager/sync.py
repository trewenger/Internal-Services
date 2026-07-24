from datetime import datetime, timedelta
from typing import Dict, List
from config import Config
from .data import InventoryData, Logger
from common.Clients.Fishbowl.FishbowlSession import FishbowlSession, CallFailure
from common.Utils.Utils import load_query, csv_export
import logging
import time
from pathlib import Path
from .modules import output_csv, create_matrix
import threading
from datetime import date
from pprint import pprint
import json

SALES_CHECK_LOCK = threading.Lock()
SYNC_LOCK        = threading.Lock()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FishbowlSync:
    def __init__(self):
        self.data = InventoryData()
        self.error_logger = Logger()
        self.config = Config()
        self.is_test_db = Config.USE_TEST_DB

        # Load the query for the Fishbowl calls
        self._qoh_query = load_query('qoh.sql')
        self._cycle_out_query = load_query('cycle_out.sql')

    def get_sku_info(self, sku:str) -> dict:
        ''' determines if a SKU exists and if its serialized or not. Used when adding SKUs in manual mode. '''
        try:
            # Create Fishbowl session
            session = FishbowlSession(is_test_db=self.is_test_db, auto_login=True, login_attempts=2, attempt_wait_secs=20)

            if not session.is_logged_in():
                raise CallFailure("Failed to login to Fishbowl")
            
            query = f'''
                SELECT 
                    Product.num as Sku, 
                    Part.num as PartNumber,
                    Part.serializedFlag AS SnFlag
                FROM 
                    Product
                    JOIN Part ON Product.partId = Part.id
                WHERE 
                    Part.activeFlag = 1
                    AND Product.activeFlag = 1
                    AND Product.num = '{sku}'
                LIMIT 1
                ;
            '''

            logger.info(f"Running product check query: {query[:100]}...")
            # request the query
            result = session.query(query)
            
            # Logout
            session.logout()

            if result and result.get('data'):
                sn_flag = result['data'][0]['SnFlag']
                part_num = result['data'][0]['PartNumber']

                logger.info(f"Found and validated the SKU.")
                return {
                    'success': True,
                    'validated_sku': True,
                    'is_serialized': sn_flag,
                    'part_num': part_num,
                    'message': f'Found and validated the SKU.'
                }
            
            else:
                logger.info("No product found")
                return {
                    'success': True,
                    'validated_sku': False,
                    'is_serialized': None,
                    'part_num': None,
                    'message': f'Did not find {sku} as an active part and product in Fishbowl. Ensure the SKU is an exact match for an active part/product.'
                }
            
        except CallFailure as e:
            logger.error(f"Fishbowl API call failed: {e}")
            self.error_logger.log_error(
                error_type='fishbowl_api_error',
                message=f"Fishbowl API call failed: {str(e)}",
                source='sync.py:get_sku_info',
                details={'sku_number': sku, 'reason': e}
            )
            return {
                'success': False,
                'validated_sku': False,
                'is_serialized': None,
                'part_num': None,
                'message': f'Fishbowl API call failed: {str(e)}'
            }
        except Exception as e:
            logger.error(f"Error querying Fishbowl: {e}")
            self.error_logger.log_error(
                error_type='fishbowl_query_error',
                message=f"Error querying Fishbowl for orders: {str(e)}",
                source='sync.py:get_sku_info',
                details={'sku_number': sku, 'reason': e}
            )
            return {
                'success': False,
                'validated_sku': False,
                'is_serialized': None,
                'part_num': None,
                'message': f'Fishbowl API call failed: {str(e)}'
            }
        finally:
            session.logout()

    def get_orders_since(self, since_datetime: datetime) -> List[Dict]:
        '''
        Query Fishbowl for orders created since the given datetime.
        '''
        try:
            # Create Fishbowl session
            session = FishbowlSession(is_test_db=self.is_test_db, auto_login=True, login_attempts=2, attempt_wait_secs=20)
            
            # Format datetime for SQL
            since_str = since_datetime.strftime('%Y-%m-%d %H:%M:%S')

            if not session.is_logged_in():
                raise CallFailure("Failed to login to Fishbowl")
            
            query = f'''
                    SELECT 
                        product.num as sku,
                        SUM(soitem.qtyordered) as qty_sold,
                        COUNT(DISTINCT so.id) as order_count
                    FROM so 
                        JOIN soitem ON so.id = soitem.soid
                        JOIN product on soitem.productid = product.id
                        JOIN Part ON Product.partId = Part.id
                    WHERE 
                        so.dateissued >= '{since_str}'
                        AND so.statusid NOT IN (60, 70, 80, 85, 90, 95)
                        AND soitem.statusid NOT IN (50, 60, 70, 75, 95)
                        AND so.createdbyuserid IN (95, 25)
                    GROUP BY product.num
                    ;
                    '''
            
            logger.info(f"Executing query: {query[:100]}...")
            
            result = session.query(query)
            
            # Logout
            session.logout()
            
            if result and result.get('data'):
                logger.info(f"Found {len(result['data'])} SKUs with orders")
                return result['data']
            else:
                logger.info("No orders found")
                return []
            
        except CallFailure as e:
            logger.error(f"Fishbowl API call failed: {e}")
            self.error_logger.log_error(
                error_type='fishbowl_api_error',
                message=f"Fishbowl API call failed: {str(e)}",
                source='sync.py:get_orders_since',
                details={'since_datetime': since_str}
            )
            return []
        except Exception as e:
            logger.error(f"Error querying Fishbowl: {e}")
            self.error_logger.log_error(
                error_type='fishbowl_query_error',
                message=f"Error querying Fishbowl for orders: {str(e)}",
                source='sync.py:get_orders_since',
                details={'since_datetime': since_str}
            )
            return []
        finally:
            session.logout()

    def get_cycle_data(self, override:dict={}, ignored:list=[]) -> list[dict]:
        ''' Calls and combines the two Fishbowl inventory queries: qoh and out_data '''
        try:
            # Login
            session = FishbowlSession(is_test_db=self.is_test_db, auto_login=True, login_attempts=2, attempt_wait_secs=20)

            if not session.is_logged_in():
                raise CallFailure("Failed to login to Fishbowl")

            # run the queries
            logger.info(f"Executing cycle out query...")
            cycle_out_data = session.query(self._cycle_out_query)
            logger.info(f"Executing QOH query...")
            qoh_data = session.query(self._qoh_query)
            session.logout()

            # ensure there is data in the response
            if cycle_out_data and qoh_data and cycle_out_data.get('data') and qoh_data.get('data'):
                logger.info(f"Gathered {len(qoh_data['data'])} retail inventory records.")
                cycle_in_inv = qoh_data.get('data')
                cycle_out_inv = cycle_out_data.get('data')
            else:
                logger.info("No inventory found")
                raise Exception("There are no inventory records present in the Fishbowl query. Sync failed.")


            #               union both queries for the final result:
            # Existing part numbers
            cycle_in_products = {item['PartNumber'] for item in cycle_in_inv if item['PartNumber']}
            to_remove = set()
            processed = set()

            # add the ignore SKUs to processed (so they are skipped) and to_remove
            for sku in ignored:
                to_remove.add(sku)
                processed.add(sku)

            # Remove the record if its a manual override part and it exists in the import data (cycle_in)
            # handling part and product numbers in case they are different. 
            for record in cycle_in_inv:
                part_num = record.get('PartNumber')
                product_num = record.get('ProductNum')
                if part_num in override or product_num in override:
                    to_remove.add(part_num)
                    processed.add(part_num)
                    to_remove.add(product_num)
                    processed.add(product_num)

            # processing query results with auto-calc on-hand inventory second, skips manually modified parts
            # For each part that has a record of inventory in the retail inventory location...
            for item in cycle_out_inv:
                part_num = item.get('PartNumber')
                # skip it if its already been processed or is manually overridden.
                if not part_num or part_num in processed:
                    continue

                processed.add(part_num)

                # if its a serialized part, has valid inventory records, and exists in the retail location already, remove it from import (static QOH)
                # Ensures static records are not overwritten by the import, saving time to create/remove SNs by the API.
                # Serialized inventory without records in the retail location will still be imported, then will be ignored on future imports. 
                if part_num in cycle_in_products and item.get('SnFlag') == 1:
                    to_remove.add(part_num)
                # otherwise if its non-serialized and it does not have a valid inventory record, add it to cycle_in with qty = 0
                # ensures existing inventory records in retail location are set to 0 if they no longer have valid inventory elsewhere
                elif part_num not in cycle_in_products and item.get('SnFlag') == 0:
                    cycle_in_inv.append(item)
                    cycle_in_products.add(part_num)
                # Do nothing if the part number is serialized and has no valid inventory records (preserves static values)
                # Do nothing if the part number is not serialized and has valid inventory records (update existing retail inventory location records)

            # Remove flagged serialized items and manual override items and ignored items
            # handling part and product number seperately in case they are different.
            cycle_in_inv = [i for i in cycle_in_inv 
                            if i['PartNumber'] not in to_remove 
                            and i.get('ProductNum') not in to_remove]

            # add the manual override items back to the import with the correct values
            for part_num in override:
                cycle_in_inv.append(override[part_num])

            # Final deduplication by PartNumber (removes one lingering duplicate)
            unique_inv = {item['PartNumber']: item for item in cycle_in_inv if item.get('PartNumber')}
            cycle_in_inv = list(unique_inv.values())

            return cycle_in_inv

        except Exception as e:
            print(f'Failed to create cycle data: {e}')
            self.error_logger.log_error(
                error_type='cycle_data_error',
                message=f"Failed to create cycle data: {str(e)}",
                source='sync.py:get_cycle_data',
                details={'error': str(e)}
            )
            return []
        finally:
            session.logout()

    def cycle_inventory(self, matrix:list) -> list[dict]:
        ''' Cycles inventory out of the retail inventory location in Fishbowl. '''
        try:
            # Create Fishbowl session
            session = FishbowlSession(is_test_db=self.is_test_db, auto_login=True, login_attempts=2, attempt_wait_secs=20)
            
            if not session.is_logged_in():
                raise CallFailure("Failed to login to Fishbowl")
            
            logger.info(f"Executing inventory cycling...")

            result = session.cycle_inventory(matrix)

            return result
            
        except CallFailure as e:
            logger.error(f"Fishbowl cycle out API call failed: {e}")
            self.error_logger.log_error(
                error_type='fishbowl_api_error',
                message=f"Fishbowl cycle out API call failed: {str(e)}",
                source='sync.py:cycle_inventory',
                details={'error': str(e)}
            )
            return []
        except Exception as e:
            logger.error(f"Error cycling retail inventory in Fishbowl: {e}")
            self.error_logger.log_error(
                error_type='cycle_inventory_error',
                message=f"Error cycling retail inventory in Fishbowl: {str(e)}",
                source='sync.py:cycle_inventory',
                details={'error': str(e)}
            )
            return []
        finally:
            session.logout()

    def determine_sync(self) -> Dict:
        '''
        Main logic to determine the sync. Called by the sync now button and the scheduler jobs.
        '''
        if not SYNC_LOCK.acquire(blocking=False):
            logger.info("Sync skipped: already running")
            return {'success': False, 'error': 'Sync is already running'}
        try:
            # Check inventory method
            config = self.data.get_config()
            inventory_method = config.get('inventory_method', 'manual')

            if inventory_method == 'manual':
                # Use existing manual logic
                logger.info("Running sync in MANUAL mode")
                return self._run_manual_sync()
            else:
                # Use automated logic (you'll implement this)
                logger.info("Running sync in AUTOMATED mode")
                return self._run_automated_sync()

        except Exception as e:
            logger.error(f"Sync error: {e}")
            self.error_logger.log_error(
                error_type='sync_error',
                message=f"Sync error in determine_sync: {str(e)}",
                source='sync.py:determine_sync',
                details={'error': str(e)}
            )
            return {
                'success': False,
                'error': str(e)
            }
        finally:
            SYNC_LOCK.release()

    def run_sales_check(self) -> Dict:
        '''
        Sales check logic: query Fishbowl for recent orders and decrement inventory.
        '''
        with SALES_CHECK_LOCK:
            try:
                print("\n SALES CHECK TRIGGERED \n")
                start_time = time.time()

                # Get last sync time
                config = self.data.get_config()
                last_check = config.get('last_check_run')
                
                if last_check:
                    since_datetime = datetime.fromisoformat(last_check)
                else:
                    # First run - go back 1 hour
                    since_datetime = datetime.now() - timedelta(hours=1)
                
                logger.info(f"Querying orders since {since_datetime}")
                
                # Get orders from Fishbowl
                orders = self.get_orders_since(since_datetime)
                
                if not orders:
                    logger.info("No new orders to process.")
                    self.data.update_config({'last_check_run': datetime.now().isoformat()})

                    # Format the last check datetime in a human-readable way
                    formatted_check_time = since_datetime.strftime('%B %d at %I:%M:%S %p')

                    return {
                        'success': True,
                        'orders_processed': 0,
                        'skus_updated': 0,
                        'message': f'No new orders since {formatted_check_time}'
                    }
                
                # Process each SKU
                skus_updated = 0
                total_orders = 0
                
                for order in orders:
                    sku = order['sku']
                    qty_sold = int(order['qty_sold'])
                    order_count = int(order['order_count'])
                    total_orders += order_count
                    
                    # Check if this SKU is in our tracking system
                    sku_data = self.data.get_sku(sku)
                    if not sku_data:
                        logger.info(f"SKU {sku} not tracked, skipping")
                        continue
                    
                    # Check if this SKU was manually modified since last sync
                    last_modified = datetime.fromisoformat(sku_data['last_modified'])
                    if last_modified > since_datetime:
                        logger.info(f"SKU {sku} manually modified, skipping auto-decrement")
                        continue
                    
                    # Decrement inventory
                    self.data.decrement_sku(sku, qty_sold, order_count)
                    skus_updated += 1
                    
                    logger.info(f"Updated {sku}: -{qty_sold} qty from {order_count} orders")
                
                # Update last sync time
                self.data.update_config({'last_check_run': datetime.now().isoformat()})
                end_time = time.time()
                run_duration = round(end_time - start_time, 2)
                #run_duration = run_duration if run_duration > 0
                

                if skus_updated > 0:
                    note = (f"Check complete: {total_orders} new products/orders checked and {skus_updated} SKUs updated in {run_duration} seconds!")
                else:
                    note = (f"Check complete: {total_orders} new products/orders checked in {run_duration} seconds, but none of them are tracked below.")
                    logger.info(note)

                return {
                    'success': True,
                    'orders_processed': total_orders,
                    'skus_updated': skus_updated,
                    'message': note
                }

            except Exception as e:
                logger.error(f"Sync error: {e}")
                self.error_logger.log_error(
                    error_type='sales_check_error',
                    message=f"Sales check error: {str(e)}",
                    source='sync.py:run_sales_check',
                    details={'error': str(e)}
                )
                return {
                    'success': False,
                    'error': str(e)
                }

    def _run_automated_sync(self):
        ''' Runs the sync in automated system mode. '''
        try:
            print("\n AUTOMATIC SYNC TRIGGERED \n")
            start_time = time.time()

            # querying fishbowl and creating the sync data to cycle in. 
            ignored_skus = self.data.get_ignored_skus() or []
            data = self.get_cycle_data(ignored=ignored_skus)

            # create the import matrix
            import_headers = ['PartNumber', 'Location', 'Qty', 'Note',
                                        'Tracking-Lot Number', 'Tracking-Revision Level', 
                                        'Tracking-Expiration Date']
            matrix = create_matrix(import_headers, data)

            # adjusting inventory
            cycle_in_result = self.cycle_inventory(matrix=matrix)

            if cycle_in_result:
                # Update last sync time
                self.data.update_config({'last_sync_run': datetime.now().isoformat()})
                
                # logging run stats
                records_updated = len(data)
                sn_created = len(matrix) - records_updated - 1
                end_time = time.time()
                run_duration = round(end_time - start_time)     # seconds
                logger.info(f"Auto-Sync complete: Updated {records_updated} inventory records and \
                            created {sn_created} serial numbers.")
                
                return {
                    'success': True,
                    'inventory_updated': records_updated,
                    'sn_created': sn_created,
                    'message': f'Updated {records_updated} inventory records and {sn_created} \
                        serial numbers in {run_duration} seconds!'
                }
            else:
                raise Exception("Gathered inventory data but failed to cycle update in FB.")

        except Exception as e:
            logger.error(f"Sync error: {e}")
            self.error_logger.log_error(
                error_type='automated_sync_error',
                message=f"Automated sync error: {str(e)}",
                source='sync.py:_run_automated_sync',
                details={'error': str(e)}
            )
            return {
                'success': False,
                'error': str(e)
            }

    def _run_manual_sync(self) -> Dict:
        """  """
        try:
            print("\n MANUAL SYNC TRIGGERED \n")
            start_time = time.time()

            # Wait for the sales check to finish running before running it here, if it is running. 
            sales_check = self.run_sales_check()

            if not sales_check.get('success'):
                raise CallFailure("Sales check failed during manual sync")
            
            self.data.update_config({'last_check_run': datetime.now().isoformat()})

            # get company name from config
            company = self.config.FISHBOWL_COMPANY_NAME
            override_skus = self.data.get_all_skus()
            override = {}
            today_str = date.today().strftime("%Y-%m-%d")
            for sku in override_skus:
                avail_qty = override_skus[sku]['available_qty']
                temp = {
                    'PartNumber': override_skus[sku]['part_num'],
                    'SnFlag': override_skus[sku]['sn_flag'],
                    'Location':f'{company} / Main-Retail Website Inventory',
                    'Qty': avail_qty if avail_qty >= 0 else 0,
                    'Note': f'Retail Website Inventory API Manual Override: {today_str}',
                    'Tracking-Lot Number': '',
                    'Tracking-Revision Level': '',
                    'Tracking-Expiration Date': ''
                }
                override[sku] = temp

            ignored_skus = self.data.get_ignored_skus() or []
            cycle_data = self.get_cycle_data(override=override, ignored=ignored_skus)
            import_headers = ['PartNumber', 'Location', 'Qty', 'Note',
                            'Tracking-Lot Number', 'Tracking-Revision Level', 
                            'Tracking-Expiration Date']
            matrix = create_matrix(import_headers, cycle_data)

            # adjusting inventory
            cycle_in_result = self.cycle_inventory(matrix=matrix)
            if cycle_in_result:
                # Update last sync time
                self.data.update_config({'last_sync_run': datetime.now().isoformat()})
                
                # logging run stats
                records_updated = len(cycle_data)
                sn_created = len(matrix) - records_updated - 1
                end_time = time.time()
                run_duration = round(end_time - start_time)     # seconds
                logger.info(f"Manual-Sync complete: Ran a sales check then updated {records_updated} inventory records and \
                            created {sn_created} serial numbers.")
                
                return {
                    'success': True,
                    'inventory_updated': records_updated,
                    'sn_created': sn_created,
                    'message': f'Ran a Sales Check then updated {records_updated} inventory records and {sn_created} \
                        serial numbers in {run_duration} seconds!'
                }
            else:
                raise Exception("Gathered inventory data but failed to cycle update in FB.")
            
        except CallFailure as e:
            logger.error(f"Fishbowl Sales Check API call failed: {e}")
            self.error_logger.log_error(
                error_type='fishbowl_api_error',
                message=f"Fishbowl Sales Check API call failed: {str(e)}",
                source='sync.py:_run_manual_sync',
                details={'error': str(e)}
            )
            return []
        except Exception as e:
            logger.error(f"Fishbowl Manual Sync API call failed: {e}")
            self.error_logger.log_error(
                error_type='manual_sync_error',
                message=f"Fishbowl Manual Sync API call failed: {str(e)}",
                source='sync.py:_run_manual_sync',
                details={'error': str(e)}
            )
            return []
