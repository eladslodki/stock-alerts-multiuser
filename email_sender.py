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

    def send_session_break_email(
        self,
        to_email: str,
        symbol: str,
        session_type: str,
        session_date: str,
        direction: str,
        session_high: float,
        session_low: float,
        first_break_ts: str,
        first_break_level: float,
        confirm_break_ts: str,
        confirm_break_level: float,
    ) -> bool:
        """Legacy wrapper – delegates to send_session_sweep_email."""
        return self.send_session_sweep_email(
            to_email=to_email,
            symbol=symbol,
            session_type=session_type,
            session_date=session_date,
            direction=direction,
            session_high=session_high,
            session_low=session_low,
            sweep_start_ts=first_break_ts,
            first_sweep_level=first_break_level,
            sweep_end_ts=first_break_ts,          # not available in old callers
            confirm_break_ts=confirm_break_ts,
            confirm_break_level=confirm_break_level,
        )

    def send_session_sweep_email(
        self,
        to_email: str,
        symbol: str,
        session_type: str,
        session_date: str,
        direction: str,
        session_high: float,
        session_low: float,
        sweep_start_ts: str,
        first_sweep_level: float,
        sweep_end_ts: str,
        confirm_break_ts: str,
        confirm_break_level: float,
    ) -> bool:
        """Send a Session Liquidity Sweep alert email."""
        if not self.enabled:
            logger.error(
                "EMAIL NOT SENT (disabled) – would send session sweep alert to %s "
                "symbol=%s session=%s/%s direction=%s",
                to_email, symbol, session_type, session_date, direction,
            )
            return False

        dir_emoji  = "⬆️" if direction == "UP" else "⬇️"
        dir_color  = "#00FFA3" if direction == "UP" else "#FF6B6B"
        dir_label  = "Bullish (UP)" if direction == "UP" else "Bearish (DOWN)"
        session_label = session_type.capitalize()
        subject = f"🚨 Sweep Confirmed: {symbol} {dir_emoji} {direction} ({session_label})"

        try:
            sh_str  = f"{float(session_high):.5f}"
            sl_str  = f"{float(session_low):.5f}"
            sl_lvl  = f"{float(first_sweep_level):.5f}"
            cb_str  = f"{float(confirm_break_level):.5f}"
        except (TypeError, ValueError):
            sh_str  = str(session_high)
            sl_str  = str(session_low)
            sl_lvl  = str(first_sweep_level)
            cb_str  = str(confirm_break_level)

        html_content = f"""
<html>
<head>
  <style>
    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
    .container {{ max-width: 620px; margin: 0 auto; padding: 20px; }}
    .header {{
        background: linear-gradient(135deg, #1a1f2e 0%, #2d3561 100%);
        color: white; padding: 30px; text-align: center;
        border-radius: 10px 10px 0 0;
    }}
    .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
    .alert-box {{
        background: white; padding: 20px;
        border-left: 4px solid {dir_color};
        margin: 20px 0; border-radius: 5px;
    }}
    .level {{ font-size: 20px; font-weight: bold; color: {dir_color}; }}
    .row {{ display: flex; justify-content: space-between; margin: 6px 0; }}
    .label {{ color: #888; font-size: 13px; }}
    .value {{ font-weight: 600; }}
    .section-title {{ font-size: 12px; text-transform: uppercase; color: #aaa;
                      letter-spacing: 0.05em; margin: 14px 0 4px; }}
    .footer {{ font-size: 12px; color: #999; margin-top: 20px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1 style="margin:0;font-size:22px;">{dir_emoji} Session Liquidity Sweep Confirmed</h1>
      <p style="margin:6px 0 0;opacity:.8;font-size:14px;">
        {symbol} &bull; {session_label} Session &bull; {session_date}
      </p>
    </div>
    <div class="content">
      <div class="alert-box">
        <h2 style="margin-top:0;color:{dir_color};">{dir_label} Sweep on {symbol}</h2>

        <p class="section-title">Session Range</p>
        <div class="row">
          <span class="label">Session</span>
          <span class="value">{session_label} ({session_date})</span>
        </div>
        <div class="row">
          <span class="label">Session High</span>
          <span class="value">{sh_str}</span>
        </div>
        <div class="row">
          <span class="label">Session Low</span>
          <span class="value">{sl_str}</span>
        </div>

        <hr style="border:none;border-top:1px solid #eee;margin:16px 0;">

        <p class="section-title">Sweep Phase</p>
        <div class="row">
          <span class="label">Sweep Start (UTC)</span>
          <span class="value">{sweep_start_ts}</span>
        </div>
        <div class="row">
          <span class="label">Sweep Extreme Level</span>
          <span class="level">{sl_lvl}</span>
        </div>
        <div class="row">
          <span class="label">Re-entry (Sweep End, UTC)</span>
          <span class="value">{sweep_end_ts}</span>
        </div>

        <hr style="border:none;border-top:1px solid #eee;margin:16px 0;">

        <p class="section-title">Confirmation Break</p>
        <div class="row">
          <span class="label">Confirm Level</span>
          <span class="level">{cb_str}</span>
        </div>
        <div class="row">
          <span class="label">Confirm Time (UTC)</span>
          <span class="value">{confirm_break_ts}</span>
        </div>
      </div>

      <p style="font-size:13px;color:#555;">
        Price swept the session {("high" if direction == "UP" else "low")},
        reached a swing extreme of <strong>{sl_lvl}</strong>,
        re-entered the session range, then confirmed the break above/below
        that extreme level.  All times are UTC. Candle timeframe: 5M.
      </p>
      <p class="footer">Sent by PulseAlerts &bull; Session Liquidity Sweep Alert</p>
    </div>
  </div>
</body>
</html>
"""
        try:
            import sib_api_v3_sdk
            from sib_api_v3_sdk.rest import ApiException

            send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": to_email}],
                sender={"email": "eladslodki@gmail.com", "name": "PulseAlerts"},
                subject=subject,
                html_content=html_content,
            )
            response = self.api_instance.send_transac_email(send_smtp_email)
            logger.info(
                "SESSION SWEEP EMAIL SENT to=%s symbol=%s session=%s/%s direction=%s msg_id=%s",
                to_email, symbol, session_type, session_date, direction,
                response.message_id,
            )
            return True

        except Exception as e:
            logger.error(
                "SESSION SWEEP EMAIL FAILED to=%s symbol=%s err=%s",
                to_email, symbol, e,
            )
            return False


email_sender = EmailSender()
