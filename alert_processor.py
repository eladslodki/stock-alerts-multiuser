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
        
    def is_market_hours(self):
        """Check if US market is open"""
        et_tz = pytz.timezone('America/New_York')
        now = datetime.now(et_tz)
        
        # Weekend check
        if now.weekday() > 4:  # Saturday=5, Sunday=6
            return False
        
        # Market hours: 9:30 AM - 4:00 PM ET
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        
        return market_open <= now < market_close
    
    def process_alerts(self):
        """
        Main processing function - runs every 60 seconds
        This runs on the SERVER, not on user devices
        """
        if not self.is_market_hours():
            logger.debug("⏰ Market closed - skipping alert check")
            return
        
        # Get all active alerts from ALL users
        active_alerts = Alert.get_all_active()
        
        if not active_alerts:
            logger.debug("📭 No active alerts to process")
            return
        
        logger.info(f"🔍 Processing {len(active_alerts)} active alerts")
        
        # Group by ticker to minimize API calls
        tickers = list(set(alert['ticker'] for alert in active_alerts))
        prices = {}
        
        # Fetch all prices FIRST
        logger.info(f"📊 Fetching prices for {len(tickers)} unique tickers: {', '.join(tickers)}")
        for ticker in tickers:
            price = price_checker.get_price(ticker)
            prices[ticker] = price
            if price:
                logger.info(f"💰 {ticker}: ${price:.2f}")
            else:
                logger.warning(f"⚠️ Could not fetch price for {ticker}")
        
        # Process each alert
        for alert in active_alerts:
            ticker = alert['ticker']
            current_price = prices.get(ticker)
            
            if current_price is None:
                logger.warning(f"⚠️ Skipping {ticker} alert (user: {alert['user_email']}) - no price data")
                continue
            
            # Update current price in database
            try:
                Alert.update_price(alert['id'], current_price)
            except Exception as e:
                logger.error(f"❌ Failed to update price for alert {alert['id']}: {e}")
            
            # Log the comparison
            target_price = float(alert['target_price'])
            direction = alert['direction']
            
            logger.info(
                f"🎯 Alert #{alert['id']} - {ticker} | "
                f"Current: ${current_price:.2f} | "
                f"Target: ${target_price:.2f} | "
                f"Direction: {direction.upper()} | "
                f"User: {alert['user_email']}"
            )
            
            # Check if alert should trigger
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
                logger.debug(f"⏳ Not triggered yet - {diff:.2f} away ({pct:.1f}%)")
            
            if triggered:
                logger.info(
                    f"🔔 ALERT TRIGGERED! {ticker} for user {alert['user_email']} | "
                    f"Target: ${target_price:.2f} | Triggered at: ${current_price:.2f}"
                )
                
                try:
                    # Send email notification
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
                    
                    # Delete alert as per requirement (auto-delete after trigger)
                    Alert.delete_by_id(alert['id'])
                    logger.info(f"🗑️ Alert #{alert['id']} deleted after trigger")
                    
                except Exception as e:
                    logger.error(f"❌ Error processing triggered alert {alert['id']}: {e}")
    
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
