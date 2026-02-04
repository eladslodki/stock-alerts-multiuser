import requests
from datetime import datetime, timedelta
import logging
import time

logger = logging.getLogger(__name__)

class BitcoinScanner:
    """
    Scan Bitcoin blockchain for large transactions
    Uses Blockchain.info API (free, no API key needed)
    """
    
    BASE_URL = "https://blockchain.info"
    
    @staticmethod
    def scan_large_transactions(min_btc_amount, time_range_hours):
        """
        Scan for Bitcoin transactions above threshold
        
        Args:
            min_btc_amount: Minimum BTC amount (float)
            time_range_hours: Hours to look back (24, 168, 720, 4320)
        
        Returns:
            List of transactions matching criteria
        """
        try:
            url = f"{BitcoinScanner.BASE_URL}/unconfirmed-transactions?format=json"
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            transactions = []
            min_satoshis = int(min_btc_amount * 100000000)
            cutoff_timestamp = int(time.time()) - (time_range_hours * 3600)
            
            for tx in data.get('txs', [])[:100]:
                try:
                    tx_timestamp = tx.get('time', 0)
                    
                    if tx_timestamp < cutoff_timestamp:
                        continue
                    
                    total_out = sum(out.get('value', 0) for out in tx.get('out', []))
                    
                    if total_out >= min_satoshis:
                        inputs = [inp.get('prev_out', {}).get('addr', 'Unknown') 
                                 for inp in tx.get('inputs', [])]
                        outputs = [out.get('addr', 'Unknown') 
                                  for out in tx.get('out', [])]
                        
                        transactions.append({
                            'hash': tx.get('hash'),
                            'time': datetime.fromtimestamp(tx_timestamp).isoformat(),
                            'amount_btc': total_out / 100000000,
                            'amount_usd': (total_out / 100000000) * get_btc_price(),
                            'from_addresses': inputs[:3],
                            'to_addresses': outputs[:3],
                            'num_inputs': len(inputs),
                            'num_outputs': len(outputs),
                            'label': None
                        })
                except Exception as e:
                    logger.error(f"Error parsing tx: {e}")
                    continue
            
            logger.info(f"Found {len(transactions)} transactions above {min_btc_amount} BTC in last {time_range_hours} hours")
            return transactions
            
        except Exception as e:
            logger.error(f"Bitcoin scan error: {e}")
            return []

def get_btc_price():
    """Get current BTC/USD price"""
    try:
        url = "https://blockchain.info/ticker"
        response = requests.get(url, timeout=10)
        data = response.json()
        return data['USD']['last']
    except:
        return 0

bitcoin_scanner = BitcoinScanner()
