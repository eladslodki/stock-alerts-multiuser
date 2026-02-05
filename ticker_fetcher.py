import requests
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

class TickerFetcher:
    """Fetch available tickers - optimized version"""
    
    @staticmethod
    @lru_cache(maxsize=1)
    def get_all_tickers():
        """
        Fast ticker list - returns pre-defined list
        Returns: List of dicts with {symbol, name, type}
        """
        logger.info("🔍 Loading ticker list...")
        
        # Pre-defined list for instant loading (no API calls needed)
        tickers = [
            # Tech Giants
            {'symbol': 'AAPL', 'name': 'Apple Inc.', 'type': 'Stock'},
            {'symbol': 'MSFT', 'name': 'Microsoft Corporation', 'type': 'Stock'},
            {'symbol': 'GOOGL', 'name': 'Alphabet Inc.', 'type': 'Stock'},
            {'symbol': 'AMZN', 'name': 'Amazon.com Inc.', 'type': 'Stock'},
            {'symbol': 'NVDA', 'name': 'NVIDIA Corporation', 'type': 'Stock'},
            {'symbol': 'META', 'name': 'Meta Platforms Inc.', 'type': 'Stock'},
            {'symbol': 'TSLA', 'name': 'Tesla Inc.', 'type': 'Stock'},
            
            # Finance
            {'symbol': 'JPM', 'name': 'JPMorgan Chase & Co.', 'type': 'Stock'},
            {'symbol': 'V', 'name': 'Visa Inc.', 'type': 'Stock'},
            {'symbol': 'MA', 'name': 'Mastercard Inc.', 'type': 'Stock'},
            {'symbol': 'BAC', 'name': 'Bank of America Corp.', 'type': 'Stock'},
            {'symbol': 'WFC', 'name': 'Wells Fargo & Co.', 'type': 'Stock'},
            
            # Consumer
            {'symbol': 'WMT', 'name': 'Walmart Inc.', 'type': 'Stock'},
            {'symbol': 'HD', 'name': 'The Home Depot Inc.', 'type': 'Stock'},
            {'symbol': 'PG', 'name': 'Procter & Gamble Co.', 'type': 'Stock'},
            {'symbol': 'KO', 'name': 'The Coca-Cola Company', 'type': 'Stock'},
            {'symbol': 'PEP', 'name': 'PepsiCo Inc.', 'type': 'Stock'},
            {'symbol': 'NKE', 'name': 'Nike Inc.', 'type': 'Stock'},
            
            # Healthcare
            {'symbol': 'JNJ', 'name': 'Johnson & Johnson', 'type': 'Stock'},
            {'symbol': 'UNH', 'name': 'UnitedHealth Group Inc.', 'type': 'Stock'},
            {'symbol': 'PFE', 'name': 'Pfizer Inc.', 'type': 'Stock'},
            {'symbol': 'ABBV', 'name': 'AbbVie Inc.', 'type': 'Stock'},
            {'symbol': 'TMO', 'name': 'Thermo Fisher Scientific Inc.', 'type': 'Stock'},
            
            # Energy
            {'symbol': 'XOM', 'name': 'Exxon Mobil Corporation', 'type': 'Stock'},
            {'symbol': 'CVX', 'name': 'Chevron Corporation', 'type': 'Stock'},
            {'symbol': 'COP', 'name': 'ConocoPhillips', 'type': 'Stock'},
            
            # Tech/Semi
            {'symbol': 'AMD', 'name': 'Advanced Micro Devices Inc.', 'type': 'Stock'},
            {'symbol': 'INTC', 'name': 'Intel Corporation', 'type': 'Stock'},
            {'symbol': 'QCOM', 'name': 'QUALCOMM Inc.', 'type': 'Stock'},
            {'symbol': 'AVGO', 'name': 'Broadcom Inc.', 'type': 'Stock'},
            {'symbol': 'ORCL', 'name': 'Oracle Corporation', 'type': 'Stock'},
            {'symbol': 'CRM', 'name': 'Salesforce Inc.', 'type': 'Stock'},
            {'symbol': 'ADBE', 'name': 'Adobe Inc.', 'type': 'Stock'},
            {'symbol': 'NFLX', 'name': 'Netflix Inc.', 'type': 'Stock'},
            
            # Growth/Meme
            {'symbol': 'GME', 'name': 'GameStop Corp.', 'type': 'Stock'},
            {'symbol': 'AMC', 'name': 'AMC Entertainment Holdings Inc.', 'type': 'Stock'},
            {'symbol': 'PLTR', 'name': 'Palantir Technologies Inc.', 'type': 'Stock'},
            {'symbol': 'SNOW', 'name': 'Snowflake Inc.', 'type': 'Stock'},
            
            # Crypto (Top 20)
            {'symbol': 'BTC-USD', 'name': 'Bitcoin USD', 'type': 'Crypto'},
            {'symbol': 'ETH-USD', 'name': 'Ethereum USD', 'type': 'Crypto'},
            {'symbol': 'BNB-USD', 'name': 'Binance Coin USD', 'type': 'Crypto'},
            {'symbol': 'XRP-USD', 'name': 'Ripple USD', 'type': 'Crypto'},
            {'symbol': 'ADA-USD', 'name': 'Cardano USD', 'type': 'Crypto'},
            {'symbol': 'DOGE-USD', 'name': 'Dogecoin USD', 'type': 'Crypto'},
            {'symbol': 'SOL-USD', 'name': 'Solana USD', 'type': 'Crypto'},
            {'symbol': 'MATIC-USD', 'name': 'Polygon USD', 'type': 'Crypto'},
            {'symbol': 'DOT-USD', 'name': 'Polkadot USD', 'type': 'Crypto'},
            {'symbol': 'AVAX-USD', 'name': 'Avalanche USD', 'type': 'Crypto'},
            {'symbol': 'LINK-USD', 'name': 'Chainlink USD', 'type': 'Crypto'},
            {'symbol': 'UNI7083-USD', 'name': 'Uniswap USD', 'type': 'Crypto'},
            {'symbol': 'LTC-USD', 'name': 'Litecoin USD', 'type': 'Crypto'},
            {'symbol': 'ATOM-USD', 'name': 'Cosmos USD', 'type': 'Crypto'},
            {'symbol': 'ETC-USD', 'name': 'Ethereum Classic USD', 'type': 'Crypto'},
            {'symbol': 'XLM-USD', 'name': 'Stellar USD', 'type': 'Crypto'},
            {'symbol': 'SHIB-USD', 'name': 'Shiba Inu USD', 'type': 'Crypto'},
        ]
        
        logger.info(f"✅ Loaded {len(tickers)} tickers instantly")
        return sorted(tickers, key=lambda x: x['symbol'])

ticker_fetcher = TickerFetcher()
