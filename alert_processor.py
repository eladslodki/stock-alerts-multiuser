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
            logger.debug("Market closed - skipping alert check")
            return
        
        # Get all active alerts from ALL users
        active_alerts = Alert.get_all_active()
        
        if not active_alerts:
            logger.debug("No active alerts to process")
            return
        
        logger.info(f"Processing {len(active_alerts)} active alerts")
        
        # Group by ticker to minimize API calls
        tickers = list(set(alert['ticker'] for alert in active_alerts))
        prices = {}
        
        # Fetch all prices
        for ticker in tickers:
            prices[ticker] = price_checker.get_price(ticker)
        
        # Process each alert
        for alert in active_alerts:
            ticker = alert['ticker']
            current_price = prices.get(ticker)
            
            if current_price is None:
                logger.warning(f"Could not fetch price for {ticker}")
                continue
            
            # Update current price in database
            Alert.update_price(alert['id'], current_price)
            
            logger.info(
                f"{ticker}: ${current_price:.2f} "
                f"(target: ${alert['target_price']:.2f}, "
                f"direction: {alert['direction']}, "
                f"user: {alert['user_email']})"
            )
            
            # Check if alert should trigger
            triggered = False
            if alert['direction'] == 'up' and current_price >= alert['target_price']:
                triggered = True
            elif alert['direction'] == 'down' and current_price <= alert['target_price']:
                triggered = True
            
            if triggered:
                logger.info(
                    f"🎯 ALERT TRIGGERED: {ticker} reached ${current_price:.2f} "
                    f"(target: ${alert['target_price']:.2f}) for user {alert['user_email']}"
                )
                
                # Send email to THIS USER ONLY
                email_sender.send_alert_email(
                    to_email=alert['user_email'],
                    ticker=ticker,
                    target_price=alert['target_price'],
                    triggered_price=current_price,
                    direction=alert['direction']
                )
                
                # Delete alert as per requirement
                Alert.delete_by_id(alert['id'])
                logger.info(f"Alert {alert['id']} deleted after notification sent")
    
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
        logger.info("Alert processor stopped")

alert_processor = AlertProcessor()