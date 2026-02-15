"""
Market anomaly detection
Scans user's watchlist for unusual activity
"""

import logging
import json
from typing import List, Dict, Optional
from datetime import datetime
from database import db

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Detect market anomalies for user's watchlist"""
    
    BIG_MOVE_THRESHOLD = 5.0  # %
    
    def get_user_universe(self, user_id: int) -> List[str]:
        """Get list of tickers to monitor for this user"""
        try:
            alert_tickers = db.execute(
                "SELECT DISTINCT ticker FROM alerts WHERE user_id = %s AND active = TRUE",
                (user_id,), fetchall=True
            )
            
            trade_tickers = db.execute(
                "SELECT DISTINCT ticker FROM trades WHERE user_id = %s",
                (user_id,), fetchall=True
            )
            
            tickers = set()
            if alert_tickers:
                tickers.update([row['ticker'] for row in alert_tickers])
            if trade_tickers:
                tickers.update([row['ticker'] for row in trade_tickers])
            
            logger.info(f"📊 User {user_id} universe: {len(tickers)} tickers")
            return list(tickers)
        
        except Exception as e:
            logger.error(f"❌ Error getting user universe: {e}")
            return []
    
    def detect_for_user(self, user_id: int) -> List[Dict]:
        """Detect anomalies for a user's universe"""
        tickers = self.get_user_universe(user_id)
        if not tickers:
            return []
        
        anomalies = []
        
        for ticker in tickers:
            try:
                from price_checker import price_checker
                current_price = price_checker.get_price(ticker)
                if not current_price:
                    continue
                
                big_move = self._check_big_move(ticker, current_price)
                if big_move:
                    big_move['user_id'] = user_id
                    anomalies.append(big_move)
            
            except Exception as e:
                logger.error(f"❌ Error checking {ticker}: {e}")
        
        logger.info(f"🚨 Found {len(anomalies)} anomalies for user {user_id}")
        return anomalies
    
    def _check_big_move(self, ticker: str, current_price: float) -> Optional[Dict]:
        """Detect large price moves (>5% in 24h)"""
        try:
            import yfinance as yf
            
            stock = yf.Ticker(ticker)
            hist = stock.history(period="2d")
            
            if len(hist) < 2:
                return None
            
            prev_close = hist['Close'].iloc[-2]
            pct_change = ((current_price - prev_close) / prev_close) * 100
            
            if abs(pct_change) >= self.BIG_MOVE_THRESHOLD:
                direction = 'up' if pct_change > 0 else 'down'
                severity = 'high' if abs(pct_change) >= 10 else 'medium'
                
                return {
                    'ticker': ticker,
                    'anomaly_type': 'BIG_MOVE',
                    'metrics_json': {
                        'current_price': current_price,
                        'prev_close': prev_close,
                        'pct_change': round(pct_change, 2),
                        'direction': direction
                    },
                    'severity': severity,
                    'detected_at': datetime.now()
                }
        
        except Exception as e:
            logger.error(f"❌ Big move check failed for {ticker}: {e}")
        
        return None
    
    def store_anomalies(self, anomalies: List[Dict]):
        """Store detected anomalies in database"""
        for anomaly in anomalies:
            try:
                db.execute("""
                    INSERT INTO market_anomalies 
                    (user_id, ticker, anomaly_type, metrics_json, detected_at, severity)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    anomaly['user_id'],
                    anomaly['ticker'],
                    anomaly['anomaly_type'],
                    json.dumps(anomaly['metrics_json']),
                    anomaly.get('detected_at', datetime.now()),
                    anomaly.get('severity', 'medium')
                ))
            except Exception as e:
                logger.error(f"❌ Failed to store anomaly: {e}")


# Global instance
anomaly_detector = AnomalyDetector()
