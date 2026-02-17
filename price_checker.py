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
        Calculate Simple Moving Average using direct Yahoo Finance API
        Does NOT use yfinance library - uses raw API calls
        
        Args:
            ticker: Stock symbol
            period: MA period (20, 50, 150)
        
        Returns:
            float: MA value or None if error
        """
        try:
            # Calculate timestamp range (we need period + buffer days)
            import time
            from datetime import datetime, timedelta
            
            # Get data for last (period * 2) days to ensure we have enough
            days_to_fetch = period * 3
            end_time = int(time.time())
            start_time = int((datetime.now() - timedelta(days=days_to_fetch)).timestamp())
            
            # Yahoo Finance Chart API - Direct call
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            params = {
                'period1': start_time,
                'period2': end_time,
                'interval': '1d',
                'includePrePost': 'false'
            }
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            logger.info(f"Fetching {days_to_fetch} days of data for {ticker} to calculate MA{period}")
            
            response = requests.get(url, params=params, headers=headers, timeout=15)
            
            if response.status_code == 404:
                logger.error(f"Ticker {ticker} not found (404)")
                return None
            
            if response.status_code == 429:
                logger.warning(f"Rate limited for {ticker}")
                return None
            
            response.raise_for_status()
            data = response.json()
            
            # Parse the response
            chart = data.get('chart', {})
            result = chart.get('result', [])
            
            if not result or len(result) == 0:
                logger.error(f"No chart data for {ticker}")
                return None
            
            result_data = result[0]
            
            # Get close prices
            indicators = result_data.get('indicators', {})
            quote = indicators.get('quote', [{}])[0]
            close_prices = quote.get('close', [])
            
            # Filter out None values
            valid_prices = [p for p in close_prices if p is not None]

            logger.info(f"📊 Got {len(valid_prices)} valid prices for {ticker} MA{period} calculation")
            
            if len(valid_prices) < period:
                logger.warning(f"⚠️ Not enough data for MA{period} on {ticker} (got {len(valid_prices)} days, need {period})")
                # Try fallback method
                logger.info(f"🔄 Trying fallback MA calculation for {ticker} MA{period}")
                return PriceChecker._fallback_ma_calculation(ticker, period)
            
            # Calculate MA from last N valid prices
            recent_prices = valid_prices[-period:]
            ma_value = sum(recent_prices) / len(recent_prices)
            
            logger.info(f"✅ Calculated MA{period} for {ticker}: ${ma_value:.2f} (from {len(valid_prices)} days)")
            return float(ma_value)
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching data for {ticker}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error for {ticker}: {e}")
            return None
        except (KeyError, IndexError, ValueError, TypeError) as e:
            logger.error(f"Parse error calculating MA{period} for {ticker}: {e}")
            logger.error(f"Response data: {data if 'data' in locals() else 'N/A'}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error calculating MA{period} for {ticker}: {e}")
            return None
    
    @staticmethod
    def _fallback_ma_calculation(ticker, period):
        """
        Fallback: Calculate MA using direct Yahoo Finance API call
        This works even when yfinance library has issues
        """
        try:
            # Calculate how many days of data we need
            days_needed = period + 100  # Extra buffer for weekends/holidays

            
            # Yahoo Finance Chart API
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            # Yahoo Finance range param maxes out at certain values
            # Use '1y' for periods up to 150, '2y' for longer
            range_str = '2y' if period >= 100 else '1y'
            params = {
                'interval': '1d',
                'range': range_str
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
