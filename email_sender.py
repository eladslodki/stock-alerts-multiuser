import os
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
import logging

logger = logging.getLogger(__name__)

class EmailSender:
    def __init__(self):
        api_key = os.getenv('BREVO_API_KEY')
        if not api_key:
            logger.warning("BREVO_API_KEY not set - emails will not be sent")
            self.enabled = False
            return
        
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = api_key
        self.api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
            sib_api_v3_sdk.ApiClient(configuration)
        )
        self.enabled = True
    
    def send_alert_email(self, to_email, ticker, target_price, triggered_price, direction):
        """Send stock alert notification email"""
        if not self.enabled:
            logger.warning(f"Email service not enabled - skipping email to {to_email}")
            return False
        
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
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
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
                    </div>
                    <p>Your alert has been automatically deleted as requested.</p>
                    <p>You can create new alerts anytime by logging into your account.</p>
                </div>
                <div class="footer">
                    <p>This is an automated email from Stock Alerts</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": to_email}],
            sender={"email": "noreply@stockalerts.app", "name": "Stock Alerts"},
            subject=subject,
            html_content=html_content
        )
        
        try:
            response = self.api_instance.send_transac_email(send_smtp_email)
            logger.info(f"✅ Email sent to {to_email} for {ticker} alert")
            return True
        except ApiException as e:
            logger.error(f"❌ Email send failed to {to_email}: {e}")
            return False

email_sender = EmailSender()