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
            {'symbol': 'AAPL', 'name': 'Apple Inc.', 'type': 'Stock'},
            {'symbol': 'ABBV', 'name': 'AbbVie Inc.', 'type': 'Stock'},
            {'symbol': 'ADA-USD', 'name': 'Cardano USD', 'type': 'Crypto'},
            {'symbol': 'ADBE', 'name': 'Adobe Inc.', 'type': 'Stock'},
            {'symbol': 'AMC', 'name': 'AMC Entertainment Holdings Inc.', 'type': 'Stock'},
            {'symbol': 'AMD', 'name': 'Advanced Micro Devices Inc.', 'type': 'Stock'},
            {'symbol': 'AMZN', 'name': 'Amazon.com Inc.', 'type': 'Stock'},
            {'symbol': 'ATOM-USD', 'name': 'Cosmos USD', 'type': 'Crypto'},
            {'symbol': 'AVAX-USD', 'name': 'Avalanche USD', 'type': 'Crypto'},
            {'symbol': 'AVGO', 'name': 'Broadcom Inc.', 'type': 'Stock'},
            {'symbol': 'BAC', 'name': 'Bank of America Corp.', 'type': 'Stock'},
            {'symbol': 'BNB-USD', 'name': 'Binance Coin USD', 'type': 'Crypto'},
            {'symbol': 'BTC-USD', 'name': 'Bitcoin USD', 'type': 'Crypto'},
            {'symbol': 'COP', 'name': 'ConocoPhillips', 'type': 'Stock'},
            {'symbol': 'CRM', 'name': 'Salesforce Inc.', 'type': 'Stock'},
            {'symbol': 'CVX', 'name': 'Chevron Corporation', 'type': 'Stock'},
            {'symbol': 'DOGE-USD', 'name': 'Dogecoin USD', 'type': 'Crypto'},
            {'symbol': 'DOT-USD', 'name': 'Polkadot USD', 'type': 'Crypto'},
            {'symbol': 'ETC-USD', 'name': 'Ethereum Classic USD', 'type': 'Crypto'},
            {'symbol': 'ETH-USD', 'name': 'Ethereum USD', 'type': 'Crypto'},
            {'symbol': 'GME', 'name': 'GameStop Corp.', 'type': 'Stock'},
            {'symbol': 'GOOGL', 'name': 'Alphabet Inc.', 'type': 'Stock'},
            {'symbol': 'HD', 'name': 'The Home Depot Inc.', 'type': 'Stock'},
            {'symbol': 'INTC', 'name': 'Intel Corporation', 'type': 'Stock'},
            {'symbol': 'JNJ', 'name': 'Johnson & Johnson', 'type': 'Stock'},
            {'symbol': 'JPM', 'name': 'JPMorgan Chase & Co.', 'type': 'Stock'},
            {'symbol': 'KO', 'name': 'The Coca-Cola Company', 'type': 'Stock'},
            {'symbol': 'LINK-USD', 'name': 'Chainlink USD', 'type': 'Crypto'},
            {'symbol': 'LTC-USD', 'name': 'Litecoin USD', 'type': 'Crypto'},
            {'symbol': 'MA', 'name': 'Mastercard Inc.', 'type': 'Stock'},
            {'symbol': 'MATIC-USD', 'name': 'Polygon USD', 'type': 'Crypto'},
            {'symbol': 'META', 'name': 'Meta Platforms Inc.', 'type': 'Stock'},
            {'symbol': 'MSFT', 'name': 'Microsoft Corporation', 'type': 'Stock'},
            {'symbol': 'NFLX', 'name': 'Netflix Inc.', 'type': 'Stock'},
            {'symbol': 'NKE', 'name': 'Nike Inc.', 'type': 'Stock'},
            {'symbol': 'NVDA', 'name': 'NVIDIA Corporation', 'type': 'Stock'},
            {'symbol': 'ORCL', 'name': 'Oracle Corporation', 'type': 'Stock'},
            {'symbol': 'PEP', 'name': 'PepsiCo Inc.', 'type': 'Stock'},
            {'symbol': 'PFE', 'name': 'Pfizer Inc.', 'type': 'Stock'},
            {'symbol': 'PG', 'name': 'Procter & Gamble Co.', 'type': 'Stock'},
            {'symbol': 'PLTR', 'name': 'Palantir Technologies Inc.', 'type': 'Stock'},
            {'symbol': 'QCOM', 'name': 'QUALCOMM Inc.', 'type': 'Stock'},
            {'symbol': 'SHIB-USD', 'name': 'Shiba Inu USD', 'type': 'Crypto'},
            {'symbol': 'SNOW', 'name': 'Snowflake Inc.', 'type': 'Stock'},
            {'symbol': 'SOL-USD', 'name': 'Solana USD', 'type': 'Crypto'},
            {'symbol': 'TMO', 'name': 'Thermo Fisher Scientific Inc.', 'type': 'Stock'},
            {'symbol': 'TSLA', 'name': 'Tesla Inc.', 'type': 'Stock'},
            {'symbol': 'UNH', 'name': 'UnitedHealth Group Inc.', 'type': 'Stock'},
            {'symbol': 'UNI7083-USD', 'name': 'Uniswap USD', 'type': 'Crypto'},
            {'symbol': 'V', 'name': 'Visa Inc.', 'type': 'Stock'},
            {'symbol': 'WFC', 'name': 'Wells Fargo & Co.', 'type': 'Stock'},
            {'symbol': 'WMT', 'name': 'Walmart Inc.', 'type': 'Stock'},
            {'symbol': 'XLM-USD', 'name': 'Stellar USD', 'type': 'Crypto'},
            {'symbol': 'XOM', 'name': 'Exxon Mobil Corporation', 'type': 'Stock'},
            {'symbol': 'XRP-USD', 'name': 'Ripple USD', 'type': 'Crypto'},
        ]
        
        logger.info(f"✅ Loaded {len(tickers)} tickers instantly")
        # Case-insensitive A→Z sort — single source of truth for backend order.
        # Matches the JS frontend's localeCompare(…, {sensitivity:'base'}).
        return sorted(tickers, key=lambda x: x['symbol'].upper())

ticker_fetcher = TickerFetcher()
