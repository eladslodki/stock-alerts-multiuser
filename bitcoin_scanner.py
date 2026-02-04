import requests
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class BitcoinScanner:
    """
    Scan Bitcoin blockchain for large transactions
    Uses Blockchain.info API (free, no API key needed)
    """
    
    BASE_URL = "https://blockchain.info"
    
    @staticmethod
    def get_recent_blocks(hours=24):
        """Get recent Bitcoin blocks"""
        try:
            url = f"{BitcoinScanner.BASE_URL}/blocks/{int(time.time() * 1000)}?format=json"
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching blocks: {e}")
            return []
    
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
            # Use Blockchain.info unconfirmed transactions endpoint
            # Note: Full historical scan requires paid API or running own node
            # This demo uses latest unconfirmed + recent confirmed txs
            
            url = f"{BitcoinScanner.BASE_URL}/unconfirmed-transactions?format=json"
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            transactions = []
            min_satoshis = int(min_btc_amount * 100000000)  # Convert BTC to satoshis
            cutoff_time = datetime.now() - timedelta(hours=time_range_hours)
            
            for tx in data.get('txs', [])[:100]:  # Limit to latest 100
                try:
                    # Get transaction details
                    tx_time = datetime.fromtimestamp(tx.get('time', 0))
                    
                    if tx_time < cutoff_time:
                        continue
                    
                    # Calculate total output value
                    total_out = sum(out.get('value', 0) for out in tx.get('out', []))
                    
                    if total_out >= min_satoshis:
                        # Get addresses
                        inputs = [inp.get('prev_out', {}).get('addr', 'Unknown') 
                                 for inp in tx.get('inputs', [])]
                        outputs = [out.get('addr', 'Unknown') 
                                  for out in tx.get('out', [])]
                        
                        transactions.append({
                            'hash': tx.get('hash'),
                            'time': tx_time.isoformat(),
                            'amount_btc': total_out / 100000000,
                            'amount_usd': (total_out / 100000000) * get_btc_price(),
                            'from_addresses': inputs[:3],  # Limit display
                            'to_addresses': outputs[:3],
                            'num_inputs': len(inputs),
                            'num_outputs': len(outputs),
                            'label': None  # Blockchain.info doesn't provide labels
                        })
                except Exception as e:
                    logger.error(f"Error parsing tx: {e}")
                    continue
            
            logger.info(f"Found {len(transactions)} transactions above {min_btc_amount} BTC")
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
