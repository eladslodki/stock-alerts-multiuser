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

    @staticmethod
    def get_moving_average(ticker, period):
        """
        Calculate Simple Moving Average using yfinance
        Fetches historical data and computes the average
        
        Args:
            ticker: Stock symbol
            period: MA period (20, 50, 150)
        
        Returns:
            float: MA value or None if error
        """
        try:
            import yfinance as yf
            
            # Fetch enough historical data
            # Use different period formats based on MA length
            if period <= 50:
                fetch_period = "3mo"  # 3 months for MA20, MA50
            else:
                fetch_period = "1y"   # 1 year for MA150
            
            stock = yf.Ticker(ticker)
            hist = stock.history(period=fetch_period)
            
            if hist.empty:
                logger.warning(f"No historical data for {ticker}")
                return None
            
            if len(hist) < period:
                logger.warning(f"Not enough data to calculate MA{period} for {ticker} (got {len(hist)} days, need {period})")
                return None
            
            # Calculate SMA from Close prices (last N days)
            close_prices = hist['Close'].tail(period)
            ma_value = close_prices.mean()
            
            logger.info(f"Calculated MA{period} for {ticker}: ${ma_value:.2f} (from {len(hist)} days of data)")
            return float(ma_value)
            
        except Exception as e:
            logger.error(f"Error calculating MA{period} for {ticker}: {e}")
            # Fallback: Try with basic requests if yfinance fails
            try:
                return PriceChecker._fallback_ma_calculation(ticker, period)
            except:
                return None
    
    @staticmethod
    def _fallback_ma_calculation(ticker, period):
        """
        Fallback: Calculate MA using direct Yahoo Finance API call
        This works even when yfinance library has issues
        """
        try:
            # Calculate how many days of data we need
            days_needed = period + 30  # Extra buffer
            
            # Yahoo Finance Chart API
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            params = {
                'interval': '1d',
                'range': f'{days_needed}d'
            }
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Extract close prices
            result = data['chart']['result'][0]
            close_prices = result['indicators']['quote'][0]['close']
            
            # Remove None values and take last N periods
            valid_prices = [p for p in close_prices if p is not None]
            
            if len(valid_prices) < period:
                logger.warning(f"Fallback: Not enough data for MA{period} on {ticker}")
                return None
            
            # Calculate average of last N prices
            recent_prices = valid_prices[-period:]
            ma_value = sum(recent_prices) / len(recent_prices)
            
            logger.info(f"Fallback MA{period} for {ticker}: ${ma_value:.2f}")
            return float(ma_value)
            
        except Exception as e:
            logger.error(f"Fallback MA calculation failed for {ticker}: {e}")
            return None
        
price_checker = PriceChecker()
