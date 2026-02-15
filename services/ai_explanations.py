"""
AI-powered alert trigger explanations
Swappable LLM provider architecture
"""

import os
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class AIClient:
    """Abstract AI client - swap providers via env var"""
    
    def __init__(self):
        self.provider = os.getenv('AI_PROVIDER', 'mock')
        self.api_key = os.getenv('AI_API_KEY')
        
        if self.provider != 'mock' and not self.api_key:
            logger.warning("⚠️ AI_API_KEY not set, using mock mode")
            self.provider = 'mock'
    
    def generate_explanation(self, prompt: str, max_tokens: int = 150) -> Optional[str]:
        """Generate explanation using configured LLM provider"""
        if self.provider == 'anthropic':
            return self._anthropic_call(prompt, max_tokens)
        elif self.provider == 'openai':
            return self._openai_call(prompt, max_tokens)
        else:
            return self._mock_call(prompt)
    
    def _anthropic_call(self, prompt: str, max_tokens: int) -> Optional[str]:
        """Call Anthropic Claude API"""
        try:
            import anthropic
            
            client = anthropic.Anthropic(api_key=self.api_key)
            message = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
                timeout=10.0
            )
            return message.content[0].text.strip()
        except Exception as e:
            logger.error(f"❌ Anthropic API error: {e}")
            return None
    
    def _openai_call(self, prompt: str, max_tokens: int) -> Optional[str]:
        """Call OpenAI API"""
        try:
            import openai
            
            client = openai.OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                timeout=10.0
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"❌ OpenAI API error: {e}")
            return None
    
    def _mock_call(self, prompt: str) -> str:
        """Mock response for development"""
        return "Market conditions triggered this alert based on price movement."


class AlertExplanationGenerator:
    """Generate AI explanations for triggered alerts"""
    
    def __init__(self):
        self.ai_client = AIClient()
    
    def build_prompt(self, alert_data: Dict) -> str:
        """Build LLM prompt from alert data"""
        ticker = alert_data['ticker']
        alert_type = alert_data['alert_type']
        current_price = alert_data['price_at_trigger']
        
        if alert_type == 'ma':
            ma_period = alert_data.get('ma_period', 20)
            ma_value = alert_data.get('ma_value', 0)
            direction = alert_data.get('direction', 'up')
            
            context = f"""Ticker: {ticker}
Alert: MA{ma_period}
Current Price: ${current_price:.2f}
MA Value: ${ma_value:.2f}
Crossed: {'above' if direction == 'up' else 'below'}"""
        else:
            target_price = alert_data.get('target_price', 0)
            direction = alert_data.get('direction', 'up')
            
            context = f"""Ticker: {ticker}
Alert: Price Target
Target: ${target_price:.2f}
Triggered: ${current_price:.2f}
Direction: {'above' if direction == 'up' else 'below'}"""
        
        prompt = f"""Explain why this stock alert triggered in 1-2 sentences.

{context}

Rules:
- Be factual, no advice
- Don't say "you should"
- Focus on what happened
- Under 50 words

Explanation:"""
        
        return prompt
    
    def generate(self, alert_data: Dict, retry: bool = True) -> str:
        """Generate explanation with fallback"""
        try:
            prompt = self.build_prompt(alert_data)
            explanation = self.ai_client.generate_explanation(prompt)
            
            if explanation:
                logger.info(f"✅ Generated AI explanation for {alert_data['ticker']}")
                return explanation
            
            if retry:
                logger.warning("⚠️ Retrying...")
                return self.generate(alert_data, retry=False)
        
        except Exception as e:
            logger.error(f"❌ Explanation generation failed: {e}")
        
        return self._fallback_template(alert_data)
    
    def _fallback_template(self, alert_data: Dict) -> str:
        """Template-based fallback if AI fails"""
        ticker = alert_data['ticker']
        alert_type = alert_data['alert_type']
        price = alert_data['price_at_trigger']
        
        if alert_type == 'ma':
            ma_period = alert_data.get('ma_period', 20)
            return f"{ticker} crossed its {ma_period}-day moving average at ${price:.2f}."
        else:
            target = alert_data.get('target_price', 0)
            direction = 'above' if alert_data.get('direction') == 'up' else 'below'
            return f"{ticker} reached ${price:.2f}, crossing {direction} your target of ${target:.2f}."


# Global instance
explanation_generator = AlertExplanationGenerator()
