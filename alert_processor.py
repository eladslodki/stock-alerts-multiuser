from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import pytz
import logging
from models import Alert
from price_checker import price_checker
from email_sender import email_sender

logger = logging.getLogger(__name__)

class AlertProcessor:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
    
    def is_crypto(self, ticker):
        """Check if ticker is a cryptocurrency"""
        return '-USD' in ticker or ticker in ['BTC', 'ETH', 'DOGE', 'SHIB']
    
    def is_market_hours(self):
        """Check if US stock market is open"""
        et_tz = pytz.timezone('America/New_York')
        now = datetime.now(et_tz)
        
        if now.weekday() > 4:
            return False
        
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        
        return market_open <= now < market_close
    
    def process_alerts(self):
        """
        Main processing function - runs every 60 seconds
        Processes crypto 24/7, stocks only during market hours
        """
        logger.info("=" * 60)
        logger.info("🚀 ALERT PROCESSOR RUNNING")
        logger.info("=" * 60)
        
        et_tz = pytz.timezone('America/New_York')
        now = datetime.now(et_tz)
        current_time_str = now.strftime('%Y-%m-%d %H:%M:%S %Z')
        market_open = self.is_market_hours()
        
        logger.info(f"⏰ Current time: {current_time_str}")
        logger.info(f"📊 Stock market: {'OPEN' if market_open else 'CLOSED'}")
        logger.info(f"₿ Crypto market: ALWAYS OPEN (24/7)")
        
        try:
            active_alerts = Alert.get_all_active()
            logger.info(f"📊 Found {len(active_alerts) if active_alerts else 0} active alerts in database")
        except Exception as e:
            logger.error(f"❌ Error fetching alerts: {e}")
            return
        
        if not active_alerts:
            logger.info("📭 No active alerts to process")
            return
        
        stock_alerts = []
        crypto_alerts = []
        
        for alert in active_alerts:
            if self.is_crypto(alert['ticker']):
                crypto_alerts.append(alert)
            else:
                stock_alerts.append(alert)
        
        logger.info(f"📈 Stock alerts: {len(stock_alerts)}")
        logger.info(f"₿ Crypto alerts: {len(crypto_alerts)}")
        
        alerts_to_process = []
        
        if market_open:
            alerts_to_process = active_alerts
            logger.info("✅ Processing ALL alerts (stocks + crypto)")
        else:
            alerts_to_process = crypto_alerts
            if stock_alerts:
                logger.info(f"⏸️ Skipping {len(stock_alerts)} stock alerts (market closed)")
            if crypto_alerts:
                logger.info(f"✅ Processing {len(crypto_alerts)} crypto alerts (24/7 trading)")
        
        if not alerts_to_process:
            logger.info("⏸️ No alerts to process right now")
            return
        
        logger.info(f"🔍 Processing {len(alerts_to_process)} alerts")
        
        tickers = list(set(alert['ticker'] for alert in alerts_to_process))
        prices = {}
        
        logger.info(f"📊 Fetching prices for {len(tickers)} unique tickers: {', '.join(tickers)}")
        for ticker in tickers:
            try:
                price = price_checker.get_price(ticker)
                prices[ticker] = price
                if price:
                    symbol = '₿' if self.is_crypto(ticker) else '📈'
                    logger.info(f"{symbol} {ticker}: ${price:.2f}")
                else:
                    logger.warning(f"⚠️ Could not fetch price for {ticker}")
            except Exception as e:
                logger.error(f"❌ Error fetching price for {ticker}: {e}")
                prices[ticker] = None
        
        for alert in alerts_to_process:
            ticker = alert['ticker']
            current_price = prices.get(ticker)
            
            if current_price is None:
                logger.warning(f"⚠️ Skipping {ticker} alert (user: {alert['user_email']}) - no price data")
                continue
            
            try:
                Alert.update_price(alert['id'], current_price)
                logger.debug(f"✅ Updated price in DB for alert #{alert['id']}")
            except Exception as e:
                logger.error(f"❌ Failed to update price for alert {alert['id']}: {e}")
            
            target_price = float(alert['target_price'])
            direction = alert['direction']
            
            asset_type = '₿ CRYPTO' if self.is_crypto(ticker) else '📈 STOCK'
            
            logger.info(
                f"🎯 {asset_type} Alert #{alert['id']} - {ticker} | "
                f"Current: ${current_price:.2f} | "
                f"Target: ${target_price:.2f} | "
                f"Direction: {direction.upper()} | "
                f"User: {alert['user_email']}"
            )
            
            triggered = False
            if direction == 'up' and current_price >= target_price:
                triggered = True
                logger.info(f"✅ CONDITION MET: ${current_price:.2f} >= ${target_price:.2f} (UP)")
            elif direction == 'down' and current_price <= target_price:
                triggered = True
                logger.info(f"✅ CONDITION MET: ${current_price:.2f} <= ${target_price:.2f} (DOWN)")
            else:
                diff = abs(current_price - target_price)
                pct = (diff / target_price) * 100
                logger.info(f"⏳ Not triggered - ${diff:.2f} away ({pct:.1f}%)")
            
            if triggered:
                logger.info(
                    f"🔔 ALERT TRIGGERED! {ticker} for user {alert['user_email']} | "
                    f"Target: ${target_price:.2f} | Triggered at: ${current_price:.2f}"
                )
                
                try:
                    email_sent = email_sender.send_alert_email(
                        to_email=alert['user_email'],
                        ticker=ticker,
                        target_price=target_price,
                        triggered_price=current_price,
                        direction=direction
                    )
                    
                    if email_sent:
                        logger.info(f"📧 Email sent successfully to {alert['user_email']}")
                    else:
                        logger.error(f"📧 Email failed to send to {alert['user_email']}")
                    
                    Alert.delete_by_id(alert['id'])
                    logger.info(f"🗑️ Alert #{alert['id']} deleted after trigger")
                    
                except Exception as e:
                    logger.error(f"❌ Error processing triggered alert {alert['id']}: {e}")
        
        logger.info("✅ Alert processing complete")
    
    def start(self):
        """Start the background scheduler"""
        self.scheduler.add_job(
            self.process_alerts,
            'interval',
            minutes=1,
            id='process_alerts'
        )
        self.scheduler.start()
        logger.info("✅ Alert processor started - checking every 60 seconds")
    
    def shutdown(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("🛑 Alert processor stopped")

alert_processor = AlertProcessor()
