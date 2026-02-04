import requests
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

class TickerFetcher:
    """Fetch available tickers - expanded list"""
    
    @staticmethod
    @lru_cache(maxsize=1)
    def get_all_tickers():
        """
        Comprehensive list of stocks and cryptos
        Returns: List of dicts with {symbol, name, type}
        """
        # Expanded stock list (300+ tickers)
        stock_symbols = [
            # Mega caps
            'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK.B', 'BRK.A',
            'UNH', 'XOM', 'JNJ', 'JPM', 'V', 'PG', 'MA', 'HD', 'CVX', 'LLY', 'ABBV', 'MRK',
            'AVGO', 'PEP', 'COST', 'ADBE', 'WMT', 'TMO', 'CSCO', 'ACN', 'MCD', 'NFLX', 'ABT',
            'CRM', 'CMCSA', 'DHR', 'VZ', 'NKE', 'AMD', 'INTC', 'TXN', 'PM', 'NEE', 'UNP', 'RTX',
            'COP', 'WFC', 'SPGI', 'ORCL', 'LOW', 'QCOM', 'HON', 'IBM', 'ELV', 'INTU', 'GE', 'BA',
            
            # Tech
            'SBUX', 'GS', 'CAT', 'DE', 'AXP', 'BKNG', 'NOW', 'BLK', 'GILD', 'MDLZ', 'ADI', 'REGN',
            'ISRG', 'CVS', 'TJX', 'VRTX', 'SYK', 'ADP', 'PANW', 'ZTS', 'PLD', 'SO', 'SCHW', 'CI',
            'MO', 'CB', 'DUK', 'ITW', 'EQIX', 'BSX', 'BDX', 'APH', 'TGT', 'SNOW', 'CRWD', 'NET',
            'DDOG', 'ZS', 'OKTA', 'TEAM', 'U', 'PATH', 'DKNG', 'COIN', 'RBLX', 'HOOD', 'SOFI',
            
            # Growth/Tech
            'SQ', 'SHOP', 'UBER', 'LYFT', 'ABNB', 'DASH', 'ZM', 'DOCU', 'TWLO', 'MDB', 'SPLK',
            'WDAY', 'VEEV', 'FTNT', 'MRVL', 'ANET', 'LRCX', 'KLAC', 'SNPS', 'CDNS', 'NXPI',
            'MCHP', 'SWKS', 'ON', 'MPWR', 'ENPH', 'SEDG', 'FSLR', 'RUN', 'PLUG', 'BLNK',
            
            # EV & Auto
            'F', 'GM', 'RIVN', 'LCID', 'NIO', 'XPEV', 'LI', 'PLUG', 'CHPT', 'EVGO',
            
            # Finance
            'BAC', 'C', 'USB', 'PNC', 'TFC', 'COF', 'BK', 'STT', 'SCHW', 'MS', 'AXP', 'V', 'MA',
            'PYPL', 'SQ', 'FIS', 'FISV', 'ADP', 'PAYX', 'BR', 'MMC', 'AON', 'WTW', 'AJG',
            
            # Healthcare
            'PFE', 'MRNA', 'BNTX', 'JNJ', 'UNH', 'CVS', 'CI', 'HUM', 'ANTM', 'TMO', 'DHR', 'ABT',
            'ISRG', 'SYK', 'BDX', 'BAX', 'EW', 'ZBH', 'HOLX', 'ALGN', 'DXCM', 'PODD', 'TDOC',
            
            # Retail & Consumer
            'AMZN', 'WMT', 'TGT', 'COST', 'HD', 'LOW', 'NKE', 'LULU', 'SBUX', 'MCD', 'YUM',
            'CMG', 'DPZ', 'QSR', 'DRI', 'TXRH', 'CAKE', 'BLMN', 'DENN', 'JACK',
            
            # Energy
            'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'PXD', 'OXY', 'MPC', 'VLO', 'PSX', 'HES', 'DVN',
            
            # Industrial
            'BA', 'CAT', 'DE', 'GE', 'HON', 'UNP', 'UPS', 'FDX', 'LMT', 'RTX', 'NOC', 'GD',
            
            # Crypto-related stocks
            'COIN', 'MSTR', 'RIOT', 'MARA', 'CLSK', 'HUT', 'BITF', 'BTBT', 'CAN', 'SOS',
            
            # Meme/Popular
            'GME', 'AMC', 'BB', 'NOK', 'PLTR', 'WISH', 'CLOV', 'SPCE', 'TLRY', 'SNDL'
        ]
        
        # Top 50 cryptocurrencies
        crypto_symbols = [
            'BTC-USD', 'ETH-USD', 'USDT-USD', 'BNB-USD', 'XRP-USD', 'USDC-USD', 'SOL-USD',
            'ADA-USD', 'DOGE-USD', 'TRX-USD', 'TON11419-USD', 'LINK-USD', 'MATIC-USD',
            'DOT-USD', 'WBTC-USD', 'DAI-USD', 'LTC-USD', 'SHIB-USD', 'AVAX-USD', 'BCH-USD',
            'UNI7083-USD', 'ATOM-USD', 'XLM-USD', 'ETC-USD', 'OKB-USD', 'XMR-USD', 'FIL-USD',
            'HBAR-USD', 'APT21794-USD', 'ARB11841-USD', 'VET-USD', 'NEAR-USD', 'AAVE-USD',
            'GRT6719-USD', 'ALGO-USD', 'EOS-USD', 'FLOW-USD', 'ICP-USD', 'SAND-USD', 'MANA-USD',
            'THETA-USD', 'AXS-USD', 'XTZ-USD', 'EGLD-USD', 'ZEC-USD', 'CAKE-USD', 'FTM-USD',
            'KLAY-USD', 'CHZ-USD', 'ENJ-USD'
        ]
        
        all_symbols = list(set(stock_symbols + crypto_symbols))
        tickers = []
        
        # Try to fetch names, fallback to symbol
        for symbol in all_symbols:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                response = requests.get(url, params={'interval': '1d', 'range': '1d'}, timeout=3)
                
                if response.status_code == 200:
                    data = response.json()
                    result = data.get('chart', {}).get('result', [{}])[0]
                    meta = result.get('meta', {})
                    name = meta.get('longName') or meta.get('shortName') or symbol
                else:
                    name = symbol
                    
                ticker_type = 'Crypto' if '-USD' in symbol else 'Stock'
                
                tickers.append({
                    'symbol': symbol,
                    'name': name,
                    'type': ticker_type
                })
            except:
                tickers.append({
                    'symbol': symbol,
                    'name': symbol,
                    'type': 'Crypto' if '-USD' in symbol else 'Stock'
                })
        
        logger.info(f"Loaded {len(tickers)} tickers")
        return sorted(tickers, key=lambda x: x['symbol'])

ticker_fetcher = TickerFetcher()
