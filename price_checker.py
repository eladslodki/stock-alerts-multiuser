import requests
import logging

logger = logging.getLogger(__name__)

class PriceChecker:
    @staticmethod
    def get_price(ticker):
        """Fetch current stock price using Yahoo Finance Chart API"""
        try:
            # Use simpler Chart API instead of quoteSummary
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            params = {
                'interval': '1d',
                'range': '1d'
            }
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            
            if response.status_code == 429:
                logger.warning(f"Rate limited for {ticker}")
                return None
            
            response.raise_for_status()
            data = response.json()
            
            # Get current price from chart data
            result = data.get('chart', {}).get('result', [{}])[0]
            meta = result.get('meta', {})
            
            price = meta.get('regularMarketPrice')
            
            if price:
                logger.info(f"Fetched {ticker}: ${price:.2f}")
                return float(price)
            
            logger.warning(f"No price data for {ticker}")
            return None
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching {ticker}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching {ticker}: {e}")
            return None
        except (KeyError, IndexError, ValueError) as e:
            logger.error(f"Parse error for {ticker}: {e}")
            return None

price_checker = PriceChecker()
