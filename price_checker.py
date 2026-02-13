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

    def get_moving_average(ticker, period):
    """
    Calculate moving average for a ticker
    
    Args:
        ticker: Stock symbol
        period: MA period (20, 50, 150)
    
    Returns:
        float: MA value or None if error
    """
    try:
        import yfinance as yf
        
        # Fetch historical data (need period + buffer days)
        stock = yf.Ticker(ticker)
        hist = stock.history(period=f"{period + 10}d")  # Extra days for safety
        
        if hist.empty or len(hist) < period:
            logger.warning(f"Not enough data to calculate MA{period} for {ticker}")
            return None
        
        # Calculate MA from Close prices
        ma_value = hist['Close'].tail(period).mean()
        
        logger.info(f"Calculated MA{period} for {ticker}: ${ma_value:.2f}")
        return float(ma_value)
        
    except Exception as e:
        logger.error(f"Error calculating MA for {ticker}: {e}")
        return None

price_checker = PriceChecker()
