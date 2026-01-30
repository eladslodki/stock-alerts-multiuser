import yfinance as yf
import logging

logger = logging.getLogger(__name__)

class PriceChecker:
    @staticmethod
    def get_price(ticker):
        """Fetch current stock price"""
        try:
            stock = yf.Ticker(ticker)
            data = stock.info
            
            price = (
                data.get('currentPrice') or 
                data.get('regularMarketPrice') or 
                data.get('previousClose')
            )
            
            if price:
                return float(price)
            
            # Fallback to history
            hist = stock.history(period='1d', interval='1m')
            if not hist.empty:
                return float(hist['Close'].iloc[-1])
            
            logger.warning(f"No price data for {ticker}")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching {ticker}: {e}")
            return None

price_checker = PriceChecker()