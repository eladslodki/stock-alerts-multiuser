from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import pytz
import logging
from database import db
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
            alert_type = alert.get('alert_type', 'price')
            ma_period = alert.get('ma_period')
            
            asset_type = '₿ CRYPTO' if self.is_crypto(ticker) else '📈 STOCK'
            alert_label = f"MA{ma_period}" if alert_type == 'ma' else f"${target_price:.2f}"
            
            logger.info(
                f"🎯 {asset_type} Alert #{alert['id']} - {ticker} | "
                f"Current: ${current_price:.2f} | "
                f"Target: {alert_label} | "
                f"Direction: {direction.upper()} | "
                f"User: {alert['user_email']}"
            )
            
            # Check if triggered - DIFFERENT LOGIC FOR MA vs PRICE ALERTS
            triggered = False
            
            if alert_type == 'ma':
                # MA ALERT: Check for CROSS, not just above/below
                ma_value = alert.get('ma_value')
                last_price = alert.get('last_price', current_price)
                crossed = alert.get('crossed', False)
                
                if ma_value is None:
                    logger.warning(f"⚠️ MA value is None for alert {alert['id']}, skipping")
                    continue
                
                # CROSS DETECTION: Only trigger on actual cross
                if direction == 'up':
                    # Trigger only if: was below/at MA before, now above MA, hasn't crossed yet
                    if last_price <= ma_value and current_price > ma_value and not crossed:
                        triggered = True
                        logger.info(f"🎯 CROSS DETECTED: {ticker} crossed ABOVE MA{ma_period} (was ${last_price:.2f}, now ${current_price:.2f}, MA=${ma_value:.2f})")
                    else:
                        logger.info(f"⏳ No cross detected - Price: ${current_price:.2f}, MA: ${ma_value:.2f}, Last: ${last_price:.2f}, Crossed: {crossed}")
                else:
                    # Trigger only if: was above/at MA before, now below MA, hasn't crossed yet
                    if last_price >= ma_value and current_price < ma_value and not crossed:
                        triggered = True
                        logger.info(f"🎯 CROSS DETECTED: {ticker} crossed BELOW MA{ma_period} (was ${last_price:.2f}, now ${current_price:.2f}, MA=${ma_value:.2f})")
                    else:
                        logger.info(f"⏳ No cross detected - Price: ${current_price:.2f}, MA: ${ma_value:.2f}, Last: ${last_price:.2f}, Crossed: {crossed}")
                
                # Update last_price for next check (even if not triggered)
                if not triggered:
                    try:
                        db.execute("""
                            UPDATE alerts 
                            SET last_price = %s 
                            WHERE id = %s
                        """, (current_price, alert['id']))
                        logger.debug(f"✅ Updated last_price to ${current_price:.2f} for alert #{alert['id']}")
                    except Exception as e:
                        logger.error(f"❌ Failed to update last_price for alert {alert['id']}: {e}")
            
            else:
                # PRICE ALERT: Original logic (check if above/below target)
                if direction == 'up' and current_price >= target_price:
                    triggered = True
                    logger.info(f"✅ CONDITION MET: ${current_price:.2f} >= {alert_label} (UP)")
                elif direction == 'down' and current_price <= target_price:
                    triggered = True
                    logger.info(f"✅ CONDITION MET: ${current_price:.2f} <= {alert_label} (DOWN)")
                else:
                    diff = abs(current_price - target_price)
                    pct = (diff / target_price) * 100
                    logger.info(f"⏳ Not triggered - ${diff:.2f} away ({pct:.1f}%)")
            
            # Trigger handling
            if triggered:
                from services.ai_explanations import explanation_generator
                from models import AlertTrigger
                
                alert_description = f"MA{alert['ma_period']}" if alert_type == 'ma' else f"${target_price:.2f}"
                
                logger.info(
                    f"🔔 ALERT TRIGGERED! {ticker} for user {alert['user_email']} | "
                    f"Target: {alert_description} | Triggered at: ${current_price:.2f}"
                )
                
                try:
                    # Generate AI explanation
                    alert_data = {
                        'ticker': ticker,
                        'alert_type': alert_type,
                        'price_at_trigger': current_price,
                        'target_price': target_price,
                        'direction': direction,
                        'ma_period': alert.get('ma_period'),
                        'ma_value': alert.get('ma_value')
                    }
                    
                    explanation = explanation_generator.generate(alert_data)
                    logger.info(f"🤖 AI Explanation: {explanation}")
                    
                    # Record trigger history
                    AlertTrigger.create(
                        user_id=alert['user_id'],
                        ticker=ticker,
                        alert_type=alert_type,
                        alert_params={'target_price': target_price, 'direction': direction},
                        price_at_trigger=current_price,
                        explanation=explanation,
                        metrics={'alert_id': alert['id']}
                    )
                    
                    # Send email with explanation
                    email_sent = email_sender.send_alert_email(
                        to_email=alert['user_email'],
                        ticker=ticker,
                        target_price=target_price,
                        triggered_price=current_price,
                        direction=direction,
                        explanation=explanation
                    )
                    
                    if email_sent:
                        logger.info(f"📧 Email sent successfully to {alert['user_email']}")
                    else:
                        logger.error(f"📧 Email failed to send to {alert['user_email']}")
                    
                    Alert.delete_by_id(alert['id'])
                    logger.info(f"🗑️ Alert #{alert['id']} deleted after trigger")
                    
                    # Mark MA alert as crossed to prevent re-triggering
                    if alert_type == 'ma':
                        try:
                            db.execute("""
                                UPDATE alerts 
                                SET crossed = TRUE 
                                WHERE id = %s
                            """, (alert['id'],))
                            logger.info(f"✓ Marked MA alert #{alert['id']} as crossed")
                        except Exception as e:
                            logger.error(f"❌ Failed to mark alert as crossed: {e}")
                    
                except Exception as e:
                    logger.error(f"❌ Error processing triggered alert {alert['id']}: {e}")
        
        logger.info("✅ Alert processing complete")
    
    def update_ma_alerts(self):
        """
        Daily job to update target_price for all MA alerts to current MA value
        This keeps MA alerts aligned with the moving average
        """
        logger.info("=" * 60)
        logger.info("🔄 UPDATING MA ALERTS")
        logger.info("=" * 60)
        
        try:
            # Get all active MA alerts
            all_alerts = Alert.get_all_active()
            ma_alerts = [a for a in all_alerts if a.get('alert_type') == 'ma']
            
            logger.info(f"Found {len(ma_alerts)} MA alerts to update")
            
            for alert in ma_alerts:
                ticker = alert['ticker']
                ma_period = alert['ma_period']
                
                try:
                    # Calculate new MA value
                    ma_value = price_checker.get_moving_average(ticker, ma_period)
                    
                    if ma_value is not None:
                        # Update the alert's target price to new MA value AND reset cross detection
                        db.execute(
                            "UPDATE alerts SET target_price = %s, current_price = %s, crossed = %s, last_price = %s WHERE id = %s",
                            (ma_value, alert['current_price'], False, alert['current_price'], alert['id'])
                        )
                        
                        logger.info(f"✅ Updated alert #{alert['id']} - {ticker} MA{ma_period} = ${ma_value:.2f}")
                    else:
                        logger.warning(f"⚠️ Could not calculate MA{ma_period} for {ticker}")
                        
                except Exception as e:
                    logger.error(f"❌ Error updating MA alert #{alert['id']}: {e}")
            
            logger.info("✅ MA alert update complete")
            
        except Exception as e:
            logger.error(f"❌ Error in MA alert updater: {e}")
    
    def schedule_anomaly_detection(self):
        """Schedule hourly anomaly detection"""
        from services.anomaly_detector import anomaly_detector
        
        def detect_and_store():
            logger.info("🚨 Running anomaly detection...")
            try:
                users = db.execute("SELECT id FROM users", fetchall=True)
                for user in users:
                    anomalies = anomaly_detector.detect_for_user(user['id'])
                    if anomalies:
                        anomaly_detector.store_anomalies(anomalies)
            except Exception as e:
                logger.error(f"❌ Anomaly detection failed: {e}")
        
        self.scheduler.add_job(detect_and_store, 'interval', hours=1, id='anomaly_detection')
        logger.info("✅ Anomaly detection scheduled (hourly)")
    
    def start(self):
        """Start the background scheduler"""
        # Check alerts every minute
        self.scheduler.add_job(
            self.process_alerts,
            'interval',
            minutes=1,
            id='process_alerts'
        )
        
        # Update MA alerts daily at 4 AM ET
        self.scheduler.add_job(
            self.update_ma_alerts,
            'cron',
            hour=4,
            minute=0,
            timezone='America/New_York',
            id='update_ma_alerts'
        )
        
        self.schedule_anomaly_detection()
        
        self.scheduler.start()
        logger.info("✅ Alert processor started - checking every 60 seconds")
        logger.info("✅ MA alert updater scheduled - daily at 4 AM ET")
    
    def shutdown(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("🛑 Alert processor stopped")

alert_processor = AlertProcessor()
