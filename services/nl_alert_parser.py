"""
Natural language alert parser (rule-based)
Parses text like "TSLA above 200" into structured alerts
"""

import re
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class NLAlertParser:
    """Rule-based natural language alert parser"""
    
    TICKER_PATTERN = r'\b([A-Z]{1,5})\b'
    PRICE_PATTERN = r'(\d+(?:\.\d{1,2})?)'
    
    INTENTS = {
        'PRICE_TARGET_ABOVE': ['above', 'over', 'breaks', 'hits', 'reaches', 'crosses'],
        'PRICE_TARGET_BELOW': ['below', 'under', 'falls', 'drops'],
        'PRICE_NEAR': ['near', 'around', 'close to'],
        'PUMP': ['pump', 'surge', 'rally', 'moon', 'rocket'],
        'DUMP': ['dump', 'crash', 'tank', 'plunge'],
        'BREAKOUT': ['breakout', 'break out']
    }
    
    def parse(self, text: str) -> Dict:
        """Parse natural language text into structured alert suggestion"""
        text = text.strip()
        logger.info(f"🔍 Parsing: {text}")
        
        ticker = self._extract_ticker(text)
        if not ticker:
            return {'success': False, 'error': 'No ticker found. Include a symbol like AAPL or TSLA.'}
        
        price = self._extract_price(text)
        intent = self._detect_intent(text)
        result = self._map_to_alert(ticker, price, intent, text)
        
        logger.info(f"✅ Result: {result.get('readable_summary', 'N/A')}")
        return result
    
    def _extract_ticker(self, text: str) -> Optional[str]:
        """Extract ticker symbol"""
        matches = re.findall(self.TICKER_PATTERN, text)
        blacklist = {'AND', 'OR', 'THE', 'WHEN', 'IF', 'AT', 'TO', 'IS', 'ME', 'IT'}
        tickers = [m for m in matches if m not in blacklist]
        return tickers[0] if tickers else None
    
    def _extract_price(self, text: str) -> Optional[float]:
        """Extract numeric price"""
        matches = re.findall(self.PRICE_PATTERN, text)
        return float(matches[0]) if matches else None
    
    def _detect_intent(self, text: str) -> str:
        """Detect user intent from keywords"""
        text_lower = text.lower()
        for intent, keywords in self.INTENTS.items():
            if any(kw in text_lower for kw in keywords):
                return intent
        return 'UNKNOWN'
    
    def _map_to_alert(self, ticker: str, price: Optional[float], intent: str, original: str) -> Dict:
        """Map to alert structure"""
        
        if intent in ['PRICE_TARGET_ABOVE', 'PRICE_TARGET_BELOW'] and price:
            direction = 'up' if intent == 'PRICE_TARGET_ABOVE' else 'down'
            return {
                'success': True,
                'ticker': ticker,
                'alert_type': 'price',
                'params': {'target_price': price, 'direction': direction},
                'readable_summary': f"Alert when {ticker} goes {'above' if direction == 'up' else 'below'} ${price:.2f}"
            }
        
        if intent == 'PRICE_NEAR' and price:
            return {
                'success': True,
                'ticker': ticker,
                'alert_type': 'price',
                'params': {'target_price': price, 'direction': 'both'},
                'readable_summary': f"Alert when {ticker} is near ${price:.2f}"
            }
        
        if intent in ['PUMP', 'DUMP']:
            threshold = 3.0
            direction = 'up' if intent == 'PUMP' else 'down'
            return {
                'success': True,
                'ticker': ticker,
                'alert_type': 'percent_change',
                'params': {'threshold_pct': threshold, 'direction': direction, 'timeframe_hours': 24},
                'readable_summary': f"Alert when {ticker} {'pumps' if direction == 'up' else 'dumps'} {threshold}%+ in 24h"
            }
        
        if intent == 'BREAKOUT':
            if price:
                return {
                    'success': True,
                    'ticker': ticker,
                    'alert_type': 'price',
                    'params': {'target_price': price, 'direction': 'up'},
                    'readable_summary': f"Alert when {ticker} breaks above ${price:.2f}"
                }
            else:
                return {
                    'success': True,
                    'ticker': ticker,
                    'alert_type': 'breakout',
                    'params': {'n_days': 20},
                    'readable_summary': f"Alert when {ticker} breaks 20-day high"
                }
        
        return {'success': False, 'error': f"Couldn't understand. Try: '{ticker} above 200'"}


# Global instance
nl_parser = NLAlertParser()
