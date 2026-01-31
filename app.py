from flask import Flask, request, jsonify, render_template_string, redirect, url_for
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import logging
import os
from database import db
from models import User, Alert
from price_checker import price_checker
from alert_processor import alert_processor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-this')

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page'

@login_manager.user_loader
def load_user(user_id):
    return User.get_by_id(int(user_id))

# ============================================================================
# ROUTES - ADD ALL OF THESE
# ============================================================================

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login_page'))

@app.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200

@app.route('/login')
def login_page():
    return """<!DOCTYPE html><html><body><h1>Login - UI Goes Here</h1></body></html>"""

@app.route('/register')  
def register_page():
    return """<!DOCTYPE html><html><body><h1>Register - UI Goes Here</h1></body></html>"""

@app.route('/dashboard')
@login_required
def dashboard():
    return """<!DOCTYPE html><html><body><h1>Dashboard - UI Goes Here</h1></body></html>"""

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'success': False, 'error': 'Email and password required'}), 400
    
    existing = User.get_by_email(email)
    if existing:
        return jsonify({'success': False, 'error': 'Email already registered'}), 400
    
    try:
        User.create(email, password)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': 'Registration failed'}), 500

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    user = User.verify_password(email, password)
    
    if not user:
        return jsonify({'success': False, 'error': 'Invalid email or password'}), 401
    
    login_user(user)
    return jsonify({'success': True, 'email': email})

@app.route('/api/logout')
@login_required
def api_logout():
    logout_user()
    return jsonify({'success': True})

@app.route('/api/alerts', methods=['GET'])
@login_required
def get_alerts():
    alerts = Alert.get_user_alerts(current_user.id)
    return jsonify({'success': True, 'alerts': alerts})

@app.route('/api/alerts', methods=['POST'])
@login_required
def create_alert():
    data = request.json
    ticker = data.get('ticker', '').upper()
    target_price = float(data.get('target_price'))
    
    if not ticker or target_price <= 0:
        return jsonify({'success': False, 'error': 'Invalid input'}), 400
    
    current_price = price_checker.get_price(ticker)
    if current_price is None:
        return jsonify({'success': False, 'error': 'Invalid ticker'}), 400
    
    direction = 'up' if target_price > current_price else 'down'
    alert_id = Alert.create(current_user.id, ticker, target_price, current_price, direction)
    
    return jsonify({
        'success': True,
        'alert': {
            'id': alert_id,
            'ticker': ticker,
            'target_price': target_price,
            'current_price': current_price,
            'direction': direction
        }
    })

@app.route('/api/alerts/<int:alert_id>', methods=['DELETE'])
@login_required
def delete_alert(alert_id):
    Alert.delete(alert_id, current_user.id)
    return jsonify({'success': True})

# Initialize database schema in background
def init_db_and_scheduler():
    try:
        db.init_schema()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
    
    # Start alert processor
    alert_processor.start()

# Run after first request, not at startup
@app.before_request
def before_first_request():
    if not hasattr(app, '_initialized'):
        app._initialized = True
        from threading import Thread
        Thread(target=init_db_and_scheduler, daemon=True).start()

# Gunicorn will run the app, this is only for local testing
if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
