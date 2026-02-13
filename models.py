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
    def create(user_id, ticker, target_price, current_price, direction, alert_type='price', ma_period=None):
            """Create alert for user"""
            result = db.execute("""
            INSERT INTO alerts (user_id, ticker, target_price, current_price, direction, alert_type, ma_period)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, ticker, target_price, current_price, direction, alert_type, ma_period), fetchone=True)
        
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
    def update_ma_value(alert_id, ma_value):
        """Update the cached MA value for an alert"""
        db.execute(
            "UPDATE alerts SET ma_value = %s WHERE id = %s",
            (ma_value, alert_id)
        )
    
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

# ============================================================================
# Portfolio Models
# ============================================================================

class Portfolio:
    @staticmethod
    def get_user_portfolio(user_id):
        """Get user's portfolio cash value"""
        result = db.execute(
            "SELECT cash FROM portfolios WHERE user_id = %s",
            (user_id,),
            fetchone=True
        )
        return result['cash'] if result else 0.0
    
    @staticmethod
    def set_user_portfolio(user_id, cash):
        """Set or update user's portfolio cash"""
        existing = db.execute(
            "SELECT id FROM portfolios WHERE user_id = %s",
            (user_id,),
            fetchone=True
        )
        
        if existing:
            db.execute(
                "UPDATE portfolios SET cash = %s, updated_at = NOW() WHERE user_id = %s",
                (cash, user_id)
            )
        else:
            db.execute(
                "INSERT INTO portfolios (user_id, cash) VALUES (%s, %s)",
                (user_id, cash)
            )
        
        logger.info(f"Portfolio updated for user {user_id}: ${cash}")

class Trade:
    @staticmethod
    def get_user_trades(user_id):
        """Get all trades for a user"""
        return db.execute("""
            SELECT id, ticker, buy_price, quantity, position_size, risk_amount,
                   timeframe, trade_date, stop_loss, take_profit, is_closed,
                   close_price, close_date, notes, created_at
            FROM trades
            WHERE user_id = %s
            ORDER BY is_closed ASC, trade_date DESC, created_at DESC
        """, (user_id,), fetchall=True)
    
    @staticmethod
    def get_open_trades(user_id):
        """Get only open trades for a user"""
        return db.execute("""
            SELECT id, ticker, buy_price, quantity, position_size, risk_amount,
                   timeframe, trade_date, stop_loss, take_profit, notes, created_at
            FROM trades
            WHERE user_id = %s AND is_closed = FALSE
            ORDER BY trade_date DESC, created_at DESC
        """, (user_id,), fetchall=True)
    
    @staticmethod
    def get_closed_trades(user_id):
        """Get only closed trades for a user"""
        return db.execute("""
            SELECT id, ticker, buy_price, quantity, position_size, risk_amount,
                   timeframe, trade_date, stop_loss, take_profit, close_price,
                   close_date, notes, created_at
            FROM trades
            WHERE user_id = %s AND is_closed = TRUE
            ORDER BY close_date DESC, created_at DESC
        """, (user_id,), fetchall=True)
    
    @staticmethod
    def create_trade(user_id, ticker, buy_price, quantity, position_size, risk_amount, 
                     timeframe, trade_date, stop_loss=None, take_profit=None, notes=None):
        """Create a new trade"""
        result = db.execute("""
            INSERT INTO trades (user_id, ticker, buy_price, quantity, position_size, 
                                risk_amount, timeframe, trade_date, stop_loss, take_profit, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, ticker, buy_price, quantity, position_size, risk_amount, 
              timeframe, trade_date, stop_loss, take_profit, notes),
        fetchone=True)
        
        logger.info(f"Trade created for user {user_id}: {ticker}")
        return result['id']
    
    @staticmethod
    def update_trade(trade_id, user_id, ticker, buy_price, quantity, position_size, 
                     risk_amount, timeframe, trade_date, stop_loss=None, take_profit=None, notes=None):
        """Update an existing trade (with user verification)"""
        db.execute("""
            UPDATE trades
            SET ticker = %s, buy_price = %s, quantity = %s, position_size = %s,
                risk_amount = %s, timeframe = %s, trade_date = %s, 
                stop_loss = %s, take_profit = %s, notes = %s, updated_at = NOW()
            WHERE id = %s AND user_id = %s
        """, (ticker, buy_price, quantity, position_size, risk_amount, timeframe, 
              trade_date, stop_loss, take_profit, notes, trade_id, user_id))
        
        logger.info(f"Trade {trade_id} updated by user {user_id}")
    
    @staticmethod
    def close_trade(trade_id, user_id, close_price, close_date):
        """Close a trade and record the exit"""
        db.execute("""
            UPDATE trades
            SET is_closed = TRUE, close_price = %s, close_date = %s, updated_at = NOW()
            WHERE id = %s AND user_id = %s
        """, (close_price, close_date, trade_id, user_id))
        
        logger.info(f"Trade {trade_id} closed by user {user_id} at ${close_price}")
    
    @staticmethod
    def reopen_trade(trade_id, user_id):
        """Reopen a closed trade"""
        db.execute("""
            UPDATE trades
            SET is_closed = FALSE, close_price = NULL, close_date = NULL, updated_at = NOW()
            WHERE id = %s AND user_id = %s
        """, (trade_id, user_id))
        
        logger.info(f"Trade {trade_id} reopened by user {user_id}")
    
    @staticmethod
    def delete_trade(trade_id, user_id):
        """Delete a trade (with user verification)"""
        db.execute(
            "DELETE FROM trades WHERE id = %s AND user_id = %s",
            (trade_id, user_id)
        )
        logger.info(f"Trade {trade_id} deleted by user {user_id}")
    
    @staticmethod
    def get_trade_statistics(user_id):
        """Calculate trading statistics from closed trades"""
        closed_trades = Trade.get_closed_trades(user_id)
        
        if not closed_trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'avg_rr': 0,
                'expectancy': 0,
                'total_realized_pnl': 0
            }
        
        wins = []
        losses = []
        total_pnl = 0
        
        for trade in closed_trades:
            buy_price = float(trade['buy_price'])
            close_price = float(trade['close_price'])
            quantity = float(trade['quantity'])
            
            pnl = (close_price - buy_price) * quantity
            total_pnl += pnl
            
            if pnl > 0:
                wins.append(pnl)
            elif pnl < 0:
                losses.append(abs(pnl))
        
        total_trades = len(closed_trades)
        winning_trades = len(wins)
        losing_trades = len(losses)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        avg_rr = avg_win / avg_loss if avg_loss > 0 else 0
        
        # Expectancy = (Win Rate * Avg Win) - (Loss Rate * Avg Loss)
        loss_rate = (losing_trades / total_trades) if total_trades > 0 else 0
        expectancy = (win_rate / 100 * avg_win) - (loss_rate * avg_loss)
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': round(win_rate, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'avg_rr': round(avg_rr, 2),
            'expectancy': round(expectancy, 2),
            'total_realized_pnl': round(total_pnl, 2)
        }
