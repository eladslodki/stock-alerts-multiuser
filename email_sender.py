import os
import logging

logger = logging.getLogger(__name__)

class EmailSender:
    def __init__(self):
        self.api_key = os.getenv('BREVO_API_KEY')
        
        if not self.api_key:
            logger.error("=" * 60)
            logger.error("❌ CRITICAL: BREVO_API_KEY environment variable NOT SET")
            logger.error("Emails will NOT be sent!")
            logger.error("Set BREVO_API_KEY in Railway environment variables")
            logger.error("=" * 60)
            self.enabled = False
            return
        
        # Mask API key for security (show first 10 chars only)
        masked_key = self.api_key[:10] + "..." if len(self.api_key) > 10 else "***"
        logger.info(f"🔑 Brevo API key found: {masked_key}")
        
        try:
            import sib_api_v3_sdk
            from sib_api_v3_sdk.rest import ApiException
            
            configuration = sib_api_v3_sdk.Configuration()
            configuration.api_key['api-key'] = self.api_key
            self.api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
                sib_api_v3_sdk.ApiClient(configuration)
            )
            self.enabled = True
            logger.info("✅ Email sender initialized successfully")
            
        except ImportError:
            logger.error("=" * 60)
            logger.error("❌ CRITICAL: sib-api-v3-sdk library not installed")
            logger.error("Run: pip install sib-api-v3-sdk")
            logger.error("=" * 60)
            self.enabled = False
        except Exception as e:
            logger.error(f"❌ Email sender initialization failed: {e}")
            self.enabled = False
    
    def send_alert_email(self, to_email, ticker, target_price, triggered_price, direction, explanation=None):
        """Send stock alert notification email"""
        if not self.enabled:
            logger.error("=" * 60)
            logger.error(f"❌ EMAIL NOT SENT - Service disabled")
            logger.error(f"Would send to: {to_email}")
            logger.error(f"Alert: {ticker} @ ${triggered_price:.2f}")
            logger.error("Check BREVO_API_KEY configuration")
            logger.error("=" * 60)
            return False
        
        logger.info("=" * 60)
        logger.info(f"📧 Attempting to send email")
        logger.info(f"To: {to_email}")
        logger.info(f"Ticker: {ticker}")
        logger.info(f"Target: ${target_price:.2f}")
        logger.info(f"Triggered: ${triggered_price:.2f}")
        logger.info("=" * 60)
        
        try:
            import sib_api_v3_sdk
            from sib_api_v3_sdk.rest import ApiException
            
            subject = f"🎯 Stock Alert: {ticker} Triggered"
            
            html_content = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                               color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                    .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                    .alert-box {{ background: white; padding: 20px; border-left: 4px solid #667eea; 
                                  margin: 20px 0; border-radius: 5px; }}
                    .price {{ font-size: 24px; font-weight: bold; color: #667eea; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🎯 Stock Alert Triggered!</h1>
                    </div>
                    <div class="content">
                        <div class="alert-box">
                            <h2>Your {ticker} alert has been triggered</h2>
                            <p><strong>Stock Symbol:</strong> {ticker}</p>
                            <p><strong>Target Price:</strong> <span class="price">${target_price:.2f}</span></p>
                            <p><strong>Triggered At:</strong> <span class="price">${triggered_price:.2f}</span></p>
                            <p><strong>Direction:</strong> {direction.upper()}</p>
                            {f'<div style="background: #e3f2fd; padding: 15px; margin-top: 15px; border-left: 4px solid #2196F3; border-radius: 5px;"><strong>🤖 AI Insight:</strong> {explanation}</div>' if explanation else ''}
                        </div>
                        <p>Your alert has been automatically deleted.</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": to_email}],
                sender={"email": "eladslodki@gmail.com", "name": "Stock Alerts"},
                subject=subject,
                html_content=html_content
            )
            
            logger.info("🔄 Calling Brevo API...")
            response = self.api_instance.send_transac_email(send_smtp_email)
            
            logger.info("=" * 60)
            logger.info("✅ EMAIL SENT SUCCESSFULLY!")
            logger.info(f"Message ID: {response.message_id}")
            logger.info(f"Recipient: {to_email}")
            logger.info("Check spam folder if not in inbox")
            logger.info("=" * 60)
            return True
            
        except ApiException as e:
            logger.error("=" * 60)
            logger.error(f"❌ BREVO API ERROR")
            logger.error(f"Status code: {e.status}")
            logger.error(f"Reason: {e.reason}")
            logger.error(f"Body: {e.body}")
            logger.error(f"Recipient: {to_email}")
            logger.error("Possible issues:")
            logger.error("1. Invalid API key")
            logger.error("2. API key permissions")
            logger.error("3. Sender email not verified")
            logger.error("4. Daily limit exceeded")
            logger.error("=" * 60)
            return False
        except Exception as e:
            logger.error("=" * 60)
            logger.error(f"❌ UNEXPECTED EMAIL ERROR")
            logger.error(f"Error: {e}")
            logger.error(f"Type: {type(e).__name__}")
            logger.error("=" * 60)
            return False

email_sender = EmailSender()
