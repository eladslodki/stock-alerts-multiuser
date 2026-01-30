from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from database import db
import logging

logger = logging.getLogger(__name__)

class User(UserMixin):
    def __init__(self, id, email):
        self.id = id
        self.email = email
    
    @staticmethod
    def create(email, password):
        """Create new user"""
        password_hash = generate_password_hash(password)
        
        result = db.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
            (email, password_hash),
            fetchone=True
        )
        
        logger.info(f"User created: {email}")
        return result['id']
    
    @staticmethod
    def get_by_email(email):
        """Get user by email"""
        result = db.execute(
            "SELECT id, email, password_hash FROM users WHERE email = %s",
            (email,),
            fetchone=True
        )
        return result
    
    @staticmethod
    def get_by_id(user_id):
        """Get user by ID"""
        result = db.execute(
            "SELECT id, email FROM users WHERE id = %s",
            (user_id,),
            fetchone=True
        )
        
        if result:
            return User(result['id'], result['email'])
        return None
    
    @staticmethod
    def verify_password(email, password):
        """Verify user password"""
        user_data = User.get_by_email(email)
        
        if not user_data:
            return None
        
        if check_password_hash(user_data['password_hash'], password):
            return User(user_data['id'], user_data['email'])
        
        return None

class Alert:
    @staticmethod
    def create(user_id, ticker, target_price, current_price, direction):
        """Create alert for user"""
        result = db.execute("""
            INSERT INTO alerts (user_id, ticker, target_price, current_price, direction)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, ticker, target_price, current_price, direction), fetchone=True)
        
        logger.info(f"Alert created for user {user_id}: {ticker} @ ${target_price}")
        return result['id']
    
    @staticmethod
    def get_user_alerts(user_id):
        """Get all alerts for specific user"""
        return db.execute("""
            SELECT id, ticker, target_price, current_price, direction,
                   active, created_at, triggered_at, triggered_price
            FROM alerts
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (user_id,), fetchall=True)
    
    @staticmethod
    def get_all_active():
        """Get all active alerts across all users (for background processing)"""
        return db.execute("""
            SELECT a.id, a.user_id, a.ticker, a.target_price, a.direction,
                   a.current_price, u.email as user_email
            FROM alerts a
            JOIN users u ON a.user_id = u.id
            WHERE a.active = TRUE
        """, fetchall=True)
    
    @staticmethod
    def update_price(alert_id, current_price):
        """Update current price for alert"""
        db.execute(
            "UPDATE alerts SET current_price = %s WHERE id = %s",
            (current_price, alert_id)
        )
    
    @staticmethod
    def delete(alert_id, user_id):
        """Delete alert (with user verification)"""
        db.execute(
            "DELETE FROM alerts WHERE id = %s AND user_id = %s",
            (alert_id, user_id)
        )
        logger.info(f"Alert {alert_id} deleted by user {user_id}")
    
    @staticmethod
    def delete_by_id(alert_id):
        """Delete alert by ID (for system use after trigger)"""
        db.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
        logger.info(f"Alert {alert_id} deleted after trigger")