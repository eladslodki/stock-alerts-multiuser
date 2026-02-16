"""
AI-powered natural language alert parser using Anthropic Claude
"""

import logging
from typing import Dict, Optional
from services.ai_explanations import AIClient

logger = logging.getLogger(__name__)


class AINLAlertParser:
    """LLM-powered alert parser for flexible natural language understanding"""
    
    def __init__(self):
        self.ai_client = AIClient()
    
    def parse(self, text: str) -> Dict:
        """
        Parse natural language alert request using LLM
        
        Returns:
        {
            'success': bool,
            'ticker': str,
            'alert_type': str,
            'parameters': dict,
            'confidence': float,
            'interpretation': str,
            'error': str (if failed)
        }
        """
        try:
            prompt = self._build_prompt(text)
            response = self.ai_client.generate_explanation(prompt, max_tokens=300)
            
            if not response:
                return self._fallback_error("AI service unavailable")
            
            # Parse JSON response
            parsed = self._parse_llm_response(response)
            
            if not parsed:
                return self._fallback_error("Could not understand request")
            
            # Validate ticker exists
            validation = self._validate_ticker(parsed.get('ticker'))
            if not validation['valid']:
                return {
                    'success': False,
                    'error': f"Ticker '{parsed.get('ticker')}' not found. {validation['suggestion']}"
                }
            
            # Map to supported alert types
            mapped = self._map_to_alert_type(parsed)
            
            if not mapped['supported']:
                return {
                    'success': False,
                    'error': mapped['message']
                }
            
            return {
                'success': True,
                'ticker': validation['ticker'],  # Use validated ticker
                'alert_type': mapped['alert_type'],
                'parameters': mapped['parameters'],
                'confidence': parsed.get('confidence', 0.8),
                'interpretation': parsed.get('interpretation', '')
            }
        
        except Exception as e:
            logger.error(f"AI parsing error: {e}")
            return self._fallback_error("Parsing failed")
    
    def _build_prompt(self, user_text: str) -> str:
        """Build LLM prompt for alert parsing"""
        
        prompt = f"""You are a stock alert parser. Extract structured alert information from user requests.

User request: "{user_text}"

Analyze the request and extract:
1. TICKER - Stock/crypto symbol (e.g., AAPL, BTC-USD, NVDA, SPY)
2. INTENT - What type of alert:
   - PRICE_TARGET: Specific price level (above/below)
   - PRICE_NEAR: Near a price level
   - PERCENT_CHANGE: Large % move up/down
   - MA_CONDITION: Moving average cross
   - VOLATILITY: High volatility/unusual activity
   - BIG_MOVE: Any significant price change
3. PARAMETERS - Specific values (price, %, direction)
4. CONFIDENCE - How confident are you (0.0-1.0)

CRITICAL RULES:
- Extract only factual information, NO trading advice
- If no clear ticker, set ticker to null
- If multiple tickers, choose the primary one
- If request is too vague, set confidence < 0.5
- Direction: "up", "down", or "both"

Return ONLY valid JSON (no markdown, no explanation):
{{
  "ticker": "SYMBOL or null",
  "intent": "PRICE_TARGET|PRICE_NEAR|PERCENT_CHANGE|MA_CONDITION|VOLATILITY|BIG_MOVE",
  "parameters": {{
    "price": number or null,
    "percent": number or null,
    "direction": "up|down|both",
    "ma_period": number or null,
    "threshold": string or null
  }},
  "confidence": 0.0-1.0,
  "interpretation": "Brief explanation of what user wants"
}}

JSON:"""
        
        return prompt
    
    def _parse_llm_response(self, response: str) -> Optional[Dict]:
        """Parse LLM JSON response"""
        import json
        
        try:
            # Clean response (remove markdown if present)
            clean = response.strip()
            if clean.startswith('```'):
                clean = clean.split('```')[1]
                if clean.startswith('json'):
                    clean = clean[4:]
            clean = clean.strip()
            
            parsed = json.loads(clean)
            
            # Validate required fields
            if not parsed.get('ticker') or parsed['confidence'] < 0.5:
                return None
            
            return parsed
        
        except Exception as e:
            logger.error(f"JSON parse error: {e}")
            return None
    
    def _validate_ticker(self, ticker: str) -> Dict:
        """Validate ticker exists using price checker"""
        if not ticker:
            return {'valid': False, 'suggestion': 'Please specify a ticker symbol.'}
        
        try:
            from price_checker import price_checker
            
            # Normalize ticker
            ticker = ticker.upper().strip()
            
            # Try to get price (validates ticker exists)
            price = price_checker.get_price(ticker)
            
            if price is None:
                # Try common variations
                variations = [
                    ticker,
                    f"{ticker}-USD",  # Crypto
                    ticker.replace('-USD', ''),  # Strip -USD
                ]
                
                for variant in variations:
                    price = price_checker.get_price(variant)
                    if price:
                        return {'valid': True, 'ticker': variant}
                
                return {
                    'valid': False,
                    'suggestion': f'Try using full symbol like {ticker}-USD for crypto or check spelling.'
                }
            
            return {'valid': True, 'ticker': ticker}
        
        except Exception as e:
            logger.error(f"Ticker validation error: {e}")
            return {'valid': False, 'suggestion': 'Could not validate ticker.'}
    
    def _map_to_alert_type(self, parsed: Dict) -> Dict:
        """Map LLM intent to supported alert types"""
        intent = parsed.get('intent')
        params = parsed.get('parameters', {})
        
        # PRICE_TARGET
        if intent == 'PRICE_TARGET' and params.get('price'):
            return {
                'supported': True,
                'alert_type': 'price',
                'parameters': {
                    'target_price': params['price'],
                    'direction': params.get('direction', 'both')
                }
            }
        
        # PRICE_NEAR
        if intent == 'PRICE_NEAR' and params.get('price'):
            return {
                'supported': True,
                'alert_type': 'price',
                'parameters': {
                    'target_price': params['price'],
                    'direction': 'both',
                    'tolerance_pct': 0.01
                }
            }
        
        # PERCENT_CHANGE
        if intent == 'PERCENT_CHANGE':
            threshold = params.get('percent', 5.0)
            return {
                'supported': True,
                'alert_type': 'percent_change',
                'parameters': {
                    'threshold_pct': threshold,
                    'direction': params.get('direction', 'both'),
                    'timeframe_hours': 24
                }
            }
        
        # MA_CONDITION
        if intent == 'MA_CONDITION':
            ma_period = params.get('ma_period', 50)
            return {
                'supported': True,
                'alert_type': 'ma',
                'parameters': {
                    'ma_period': ma_period,
                    'direction': params.get('direction', 'up')
                }
            }
        
        # VOLATILITY or BIG_MOVE - map to percent_change
        if intent in ['VOLATILITY', 'BIG_MOVE']:
            return {
                'supported': True,
                'alert_type': 'percent_change',
                'parameters': {
                    'threshold_pct': 5.0,
                    'direction': 'both',
                    'timeframe_hours': 24
                }
            }
        
        # Unsupported or ambiguous
        return {
            'supported': False,
            'message': f'Cannot create alert for "{intent}". Try: "Alert when {parsed.get("ticker")} goes above [price]"'
        }
    
    def _fallback_error(self, message: str) -> Dict:
        """Return error response"""
        return {
            'success': False,
            'error': f'{message}. Try: "Alert me if AAPL goes above 200"'
        }


# Global instance
ai_nl_parser = AINLAlertParser()
