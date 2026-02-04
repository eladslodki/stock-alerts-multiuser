import requests
from datetime import datetime
import logging
import time

logger = logging.getLogger(__name__)

class BitcoinScanner:
    """
    Scan Bitcoin blockchain for large transactions
    Uses Blockstream API (free, better historical data)
    """
    
    BASE_URL = "https://blockstream.info/api"
    
    @staticmethod
    def scan_large_transactions(min_btc_amount, time_range_hours):
        """
        Scan for Bitcoin transactions above threshold
        
        Args:
            min_btc_amount: Minimum BTC amount (float)
            time_range_hours: Hours to look back
        
        Returns:
            List of transactions matching criteria
        """
        try:
            transactions = []
            min_satoshis = int(min_btc_amount * 100000000)
            cutoff_timestamp = int(time.time()) - (time_range_hours * 3600)
            
            # Get recent blocks
            url = f"{BitcoinScanner.BASE_URL}/blocks/tip/height"
            response = requests.get(url, timeout=10)
            latest_height = int(response.text)
            
            logger.info(f"Scanning from block {latest_height}, looking back {time_range_hours} hours")
            
            # Bitcoin blocks are ~10 minutes apart, so calculate how many blocks to check
            blocks_to_check = min(int(time_range_hours * 6), 50)  # Max 50 blocks to avoid timeout
            
            for block_offset in range(blocks_to_check):
                block_height = latest_height - block_offset
                
                try:
                    # Get block hash
                    block_hash_url = f"{BitcoinScanner.BASE_URL}/block-height/{block_height}"
                    block_hash = requests.get(block_hash_url, timeout=10).text.strip()
                    
                    # Get block data
                    block_url = f"{BitcoinScanner.BASE_URL}/block/{block_hash}"
                    block_data = requests.get(block_url, timeout=10).json()
                    block_timestamp = block_data.get('timestamp', 0)
                    
                    # Stop if block is older than time range
                    if block_timestamp < cutoff_timestamp:
                        logger.info(f"Reached blocks older than {time_range_hours} hours, stopping")
                        break
                    
                    # Get transactions in this block (first 25 txs only to avoid timeout)
                    tx_ids = block_data.get('tx_count', 0)
                    if tx_ids > 0:
                        txs_url = f"{BitcoinScanner.BASE_URL}/block/{block_hash}/txs/0"
                        txs_data = requests.get(txs_url, timeout=15).json()
                        
                        for tx in txs_data[:25]:  # Limit to 25 per block
                            try:
                                # Calculate total output
                                total_out = sum(out.get('value', 0) for out in tx.get('vout', []))
                                
                                if total_out >= min_satoshis:
                                    # Get addresses
                                    inputs = []
                                    for vin in tx.get('vin', [])[:3]:
                                        addr = vin.get('prevout', {}).get('scriptpubkey_address', 'Unknown')
                                        inputs.append(addr)
                                    
                                    outputs = []
                                    for vout in tx.get('vout', [])[:3]:
                                        addr = vout.get('scriptpubkey_address', 'Unknown')
                                        outputs.append(addr)
                                    
                                    transactions.append({
                                        'hash': tx.get('txid'),
                                        'time': datetime.fromtimestamp(block_timestamp).isoformat(),
                                        'amount_btc': total_out / 100000000,
                                        'amount_usd': (total_out / 100000000) * get_btc_price(),
                                        'from_addresses': inputs,
                                        'to_addresses': outputs,
                                        'num_inputs': len(tx.get('vin', [])),
                                        'num_outputs': len(tx.get('vout', [])),
                                        'label': None
                                    })
                            except Exception as e:
                                logger.error(f"Error parsing tx: {e}")
                                continue
                
                except Exception as e:
                    logger.error(f"Error fetching block {block_height}: {e}")
                    continue
                
                # Rate limit: don't spam the API
                time.sleep(0.5)
            
            logger.info(f"Found {len(transactions)} transactions above {min_btc_amount} BTC in last {time_range_hours} hours")
            return transactions
            
        except Exception as e:
            logger.error(f"Bitcoin scan error: {e}")
            return []

def get_btc_price():
    """Get current BTC/USD price"""
    try:
        url = "https://blockstream.info/api/blocks/tip/height"
        # Use CoinGecko for price
        price_url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        response = requests.get(price_url, timeout=10)
        data = response.json()
        return data['bitcoin']['usd']
    except:
        return 50000  # Fallback estimate

bitcoin_scanner = BitcoinScanner()
