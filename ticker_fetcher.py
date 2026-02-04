import requests
import logging
import json
from functools import lru_cache

logger = logging.getLogger(__name__)

class TickerFetcher:
    """Fetch available tickers from Yahoo Finance"""
    
    # Use screener API to get popular stocks
    SCREENER_URL = "https://query2.finance.yahoo.com/v1/finance/screener"
    
    @staticmethod
    @lru_cache(maxsize=1)
    def get_all_tickers():
        """
        Fetch list of popular stocks and cryptos.
        Cached to avoid repeated API calls.
        Returns: List of dicts with {symbol, name, type}
        """
        try:
            tickers = []
            
            # Get top stocks from S&P 500, NASDAQ, Dow Jones
            stock_lists = [
                # S&P 500 components (simplified - top 100)
                ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK.B', 'UNH', 'XOM',
                 'JNJ', 'JPM', 'V', 'PG', 'MA', 'HD', 'CVX', 'LLY', 'ABBV', 'MRK',
                 'AVGO', 'PEP', 'COST', 'ADBE', 'WMT', 'TMO', 'CSCO', 'ACN', 'MCD', 'NFLX',
                 'ABT', 'CRM', 'CMCSA', 'DHR', 'VZ', 'NKE', 'AMD', 'INTC', 'TXN', 'PM',
                 'NEE', 'UNP', 'RTX', 'COP', 'WFC', 'SPGI', 'ORCL', 'LOW', 'QCOM', 'HON',
                 'IBM', 'ELV', 'INTU', 'GE', 'BA', 'SBUX', 'GS', 'CAT', 'DE', 'AXP',
                 'BKNG', 'NOW', 'BLK', 'GILD', 'MDLZ', 'ADI', 'REGN', 'MMM', 'AMT', 'ISRG',
                 'CVS', 'TJX', 'VRTX', 'SYK', 'ADP', 'PANW', 'ZTS', 'PLD', 'SO', 'SCHW',
                 'CI', 'MO', 'CB', 'DUK', 'ITW', 'EQIX', 'BSX', 'BDX', 'APH', 'TGT'],
                
                # Popular tech stocks
                ['NVDA', 'AMD', 'PLTR', 'SNOW', 'CRWD', 'NET', 'DDOG', 'ZS', 'OKTA', 'TEAM'],
                
                # EV & Energy
                ['TSLA', 'RIVN', 'LCID', 'NIO', 'XPEV', 'LI', 'F', 'GM'],
                
                # Crypto-related stocks
                ['COIN', 'MSTR', 'RIOT', 'MARA', 'CLSK', 'HUT'],
                
                # Popular cryptos (Yahoo Finance symbols)
                ['BTC-USD', 'ETH-USD', 'BNB-USD', 'XRP-USD', 'ADA-USD', 'DOGE-USD', 
                 'SOL-USD', 'MATIC-USD', 'DOT-USD', 'AVAX-USD', 'LINK-USD', 'UNI-USD']
            ]
            
            # Flatten and dedupe
            all_symbols = list(set([s for sublist in stock_lists for s in sublist]))
            
            # Get company names for each ticker
            for symbol in all_symbols:
                try:
                    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                    response = requests.get(url, params={'interval': '1d', 'range': '1d'}, timeout=5)
                    
                    if response.status_code == 200:
                        data = response.json()
                        result = data.get('chart', {}).get('result', [{}])[0]
                        meta = result.get('meta', {})
                        
                        name = meta.get('longName') or meta.get('shortName') or symbol
                        
                        ticker_type = 'Crypto' if '-USD' in symbol else 'Stock'
                        
                        tickers.append({
                            'symbol': symbol,
                            'name': name,
                            'type': ticker_type
                        })
                except:
                    # If can't fetch name, still add symbol
                    tickers.append({
                        'symbol': symbol,
                        'name': symbol,
                        'type': 'Unknown'
                    })
            
            logger.info(f"Loaded {len(tickers)} tickers")
            return sorted(tickers, key=lambda x: x['symbol'])
            
        except Exception as e:
            logger.error(f"Error fetching tickers: {e}")
            # Return minimal list as fallback
            return [
                {'symbol': 'AAPL', 'name': 'Apple Inc.', 'type': 'Stock'},
                {'symbol': 'TSLA', 'name': 'Tesla Inc.', 'type': 'Stock'},
                {'symbol': 'MSFT', 'name': 'Microsoft Corporation', 'type': 'Stock'},
                {'symbol': 'GOOGL', 'name': 'Alphabet Inc.', 'type': 'Stock'},
                {'symbol': 'BTC-USD', 'name': 'Bitcoin USD', 'type': 'Crypto'}
            ]

ticker_fetcher = TickerFetcher()
