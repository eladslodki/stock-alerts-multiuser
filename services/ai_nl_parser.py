"""
AI-powered natural language alert parser using Anthropic Claude
"""

import logging
import json
import re
from typing import Dict, Optional
import os

logger = logging.getLogger(__name__)


class AINLAlertParser:
    """LLM-powered alert parser for flexible natural language understanding"""
    
    def __init__(self):
       
        # TEMPORARY HARDCODE FOR TESTING
        self.api_key = "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"
        self.provider = "anthropic"
        # Debug logging
        logger.info(f"🔑 AI_PROVIDER: {self.provider}")
        logger.info(f"🔑 API_KEY present: {bool(self.api_key)}")
        if self.api_key:
            logger.info(f"🔑 API_KEY length: {len(self.api_key)}")
            logger.info(f"🔑 API_KEY starts with: {self.api_key[:15]}...")
    
        if not self.api_key and self.provider != 'mock':
            logger.warning("⚠️ AI_API_KEY not set for NL parser")
    
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
            logger.info(f"🔍 Parsing: {text}")
            
            prompt = self._build_prompt(text)
            response = self._call_anthropic(prompt)
            
            logger.info(f"🤖 LLM Response: {response[:200] if response else 'None'}...")
            
            if not response:
                logger.error("❌ No response from AI")
                return self._fallback_error("AI service unavailable")
            
            # Parse JSON response
            parsed = self._parse_llm_response(response)
            
            logger.info(f"📊 Parsed result: {parsed}")
            
            if not parsed:
                logger.error("❌ Failed to parse LLM response")
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
                'ticker': validation['ticker'],
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
        
        prompt = f"""You are a stock alert parser. Extract structured information from user requests.

User request: "{user_text}"

Your task: Extract the ticker symbol, alert intent, and parameters.

EXAMPLES:
"AAPL above 200" → ticker: AAPL, intent: PRICE_TARGET, price: 200, direction: up
"Tell me when bitcoin drops below 40000" → ticker: BTC-USD, intent: PRICE_TARGET, price: 40000, direction: down
"NVDA crosses MA50" → ticker: NVDA, intent: MA_CONDITION, ma_period: 50
"Alert when TSLA is near 250" → ticker: TSLA, intent: PRICE_NEAR, price: 250
"SPY shows big moves" → ticker: SPY, intent: BIG_MOVE
"ETH pumps 5%" → ticker: ETH-USD, intent: PERCENT_CHANGE, percent: 5, direction: up

INTENT TYPES:
- PRICE_TARGET: specific price level with direction (above/below)
- PRICE_NEAR: near a price level
- PERCENT_CHANGE: percentage move (pump/dump/rise/fall)
- MA_CONDITION: moving average cross (MA20, MA50, MA150)
- BIG_MOVE: any significant move
- VOLATILITY: high volatility or unusual activity

TICKER RULES:
- Stocks: use symbol as-is (AAPL, NVDA, TSLA, SPY, etc.)
- Crypto: add -USD (BTC-USD, ETH-USD)
- If unclear, use most likely ticker
- Common names: "bitcoin"→BTC-USD, "ethereum"→ETH-USD, "apple"→AAPL

CRITICAL:
- Be generous with confidence (0.7+ if you can extract ticker and intent)
- Extract ticker even from short phrases like "AAPL above 200"
- Default direction: "up" for above/breaks/crosses, "down" for below/drops
- If multiple tickers mentioned, use first one only
- NO trading advice, only parse the request

Return ONLY this JSON (no markdown, no explanation):
{{
  "ticker": "SYMBOL",
  "intent": "PRICE_TARGET",
  "parameters": {{
    "price": 200,
    "percent": null,
    "direction": "up",
    "ma_period": null,
    "threshold": null
  }},
  "confidence": 0.9,
  "interpretation": "Alert when AAPL goes above $200"
}}

JSON:"""
        
        return prompt
    
    def _call_anthropic(self, prompt: str) -> Optional[str]:
        """Call Anthropic API directly for parsing"""
        if self.provider == 'mock':
            mock_json = {
                "ticker": "AAPL",
                "intent": "PRICE_TARGET",
                "parameters": {
                    "price": 200,
                    "percent": None,
                    "direction": "up",
                    "ma_period": None,
                    "threshold": None
                },
                "confidence": 0.9,
                "interpretation": "Alert when AAPL goes above $200"
            }
            return json.dumps(mock_json)
    
        try:
            import anthropic
        
            # Create client without extra kwargs
            client = anthropic.Anthropic(
                api_key=self.api_key
            )
        
            # Make API call
            message = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=400,
                temperature=0.3,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
        
            response_text = message.content[0].text.strip()
            logger.info("✅ Anthropic API call successful")
            return response_text
    
        except anthropic.APIConnectionError as e:
            logger.error(f"❌ Anthropic connection error: {e}")
            return None
    
        except anthropic.RateLimitError as e:
            logger.error(f"❌ Anthropic rate limit: {e}")
            return None
    
        except anthropic.APIStatusError as e:
            logger.error(f"❌ Anthropic API status error: {e.status_code} - {e.response}")
            return None
    
        except Exception as e:
            logger.error(f"❌ Anthropic API error: {e}")
            logger.error(f"❌ Error type: {type(e).__name__}")
            return None
        
    def _parse_llm_response(self, response: str) -> Optional[Dict]:
        """Parse LLM JSON response with robust error handling"""
        try:
            clean = response.strip()
            
            if '```' in clean:
                parts = clean.split('```')
                if len(parts) >= 3:
                    clean = parts[1]
                    if clean.startswith('json'):
                        clean = clean[4:]
            
            if not clean.startswith('{'):
                json_match = re.search(r'\{.*\}', clean, re.DOTALL)
                if json_match:
                    clean = json_match.group(0)
            
            clean = clean.strip()
            
            logger.info(f"🧹 Cleaned JSON: {clean[:100]}...")
            
            parsed = json.loads(clean)
            
            if not isinstance(parsed, dict):
                logger.error(f"❌ Parsed result is not a dict: {type(parsed)}")
                return None
            
            if not parsed.get('ticker'):
                logger.error("❌ No ticker in parsed result")
                return None
            
            confidence = parsed.get('confidence', 0)
            if confidence < 0.3:
                logger.warning(f"⚠️ Low confidence: {confidence}")
                return None
            
            logger.info(f"✅ Successfully parsed: ticker={parsed['ticker']}, confidence={confidence}")
            return parsed
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON decode error: {e}")
            logger.error(f"❌ Response was: {response[:200]}...")
            return None
        
        except Exception as e:
            logger.error(f"❌ Parse error: {e}")
            return None
    
    def _validate_ticker(self, ticker: str) -> Dict:
        """Validate ticker exists using price checker"""
        if not ticker:
            return {'valid': False, 'suggestion': 'Please specify a ticker symbol.'}
        
        try:
            from price_checker import price_checker
            
            ticker = ticker.upper().strip()
            
            price = price_checker.get_price(ticker)
            
            if price is None:
                variations = [
                    ticker,
                    f"{ticker}-USD",
                    ticker.replace('-USD', ''),
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
        
        if intent == 'PRICE_TARGET' and params.get('price'):
            return {
                'supported': True,
                'alert_type': 'price',
                'parameters': {
                    'target_price': params['price'],
                    'direction': params.get('direction', 'both')
                }
            }
        
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


ai_nl_parser = AINLAlertParser()
