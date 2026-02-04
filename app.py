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
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login - Stock Alerts</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: Arial; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                   min-height: 100vh; display: flex; align-items: center; justify-content: center; margin: 0; }
            .container { background: white; padding: 40px; border-radius: 10px; max-width: 400px; width: 90%; }
            h1 { text-align: center; color: #333; }
            input { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ddd; border-radius: 5px; box-sizing: border-box; }
            button { width: 100%; padding: 12px; background: #667eea; color: white; border: none; 
                     border-radius: 5px; cursor: pointer; font-size: 16px; }
            button:hover { background: #5568d3; }
            .message { padding: 10px; margin: 10px 0; border-radius: 5px; }
            .error { background: #fee; color: #c33; }
            .success { background: #efe; color: #3c3; }
            .link { text-align: center; margin-top: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Stock Alerts</h1>
            <div id="message"></div>
            <input type="email" id="email" placeholder="Email" />
            <input type="password" id="password" placeholder="Password" />
            <button onclick="login()">Login</button>
            <div class="link">
                Don't have an account? <a href="/register">Register</a>
            </div>
        </div>
        <script>
            async function login() {
                const email = document.getElementById('email').value;
                const password = document.getElementById('password').value;
                const msgEl = document.getElementById('message');
                
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password })
                });
                
                const data = await res.json();
                if (data.success) {
                    window.location.href = '/dashboard';
                } else {
                    msgEl.innerHTML = '<div class="message error">' + data.error + '</div>';
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/register')  
def register_page():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Register - Stock Alerts</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: Arial; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                   min-height: 100vh; display: flex; align-items: center; justify-content: center; margin: 0; }
            .container { background: white; padding: 40px; border-radius: 10px; max-width: 400px; width: 90%; }
            h1 { text-align: center; color: #333; }
            input { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ddd; border-radius: 5px; box-sizing: border-box; }
            button { width: 100%; padding: 12px; background: #667eea; color: white; border: none; 
                     border-radius: 5px; cursor: pointer; font-size: 16px; }
            button:hover { background: #5568d3; }
            .message { padding: 10px; margin: 10px 0; border-radius: 5px; }
            .error { background: #fee; color: #c33; }
            .success { background: #efe; color: #3c3; }
            .link { text-align: center; margin-top: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Create Account</h1>
            <div id="message"></div>
            <input type="email" id="email" placeholder="Email" />
            <input type="password" id="password" placeholder="Password (min 6 chars)" />
            <button onclick="register()">Register</button>
            <div class="link">
                Already have an account? <a href="/login">Login</a>
            </div>
        </div>
        <script>
            async function register() {
                const email = document.getElementById('email').value;
                const password = document.getElementById('password').value;
                const msgEl = document.getElementById('message');
                
                if (password.length < 6) {
                    msgEl.innerHTML = '<div class="message error">Password must be at least 6 characters</div>';
                    return;
                }
                
                const res = await fetch('/api/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password })
                });
                
                const data = await res.json();
                if (data.success) {
                    msgEl.innerHTML = '<div class="message success">Registration successful! Redirecting to login...</div>';
                    setTimeout(() => window.location.href = '/login', 2000);
                } else {
                    msgEl.innerHTML = '<div class="message error">' + data.error + '</div>';
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/dashboard')
@login_required
def dashboard():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Dashboard - Stock Alerts</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: Arial; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                   min-height: 100vh; margin: 0; padding: 20px; }
            .container { max-width: 800px; margin: 0 auto; }
            .header { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; 
                      display: flex; justify-content: space-between; align-items: center; }
            .card { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
            h1, h2 { margin: 0; color: #333; }
            input { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ddd; 
                    border-radius: 5px; box-sizing: border-box; }
            button { padding: 12px 20px; background: #667eea; color: white; border: none; 
                     border-radius: 5px; cursor: pointer; }
            button:hover { background: #5568d3; }
            .logout { background: #e74c3c; }
            .logout:hover { background: #c0392b; }
            .alert-item { padding: 15px; background: #f9f9f9; margin: 10px 0; border-radius: 5px; 
                          display: flex; justify-content: space-between; align-items: center; }
            .delete-btn { background: #e74c3c; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div>
                    <h1>📊 Stock Alerts</h1>
                    <p id="userEmail"></p>
                </div>
                <button class="logout" onclick="logout()">Logout</button>
            </div>
            
            <div class="card">
                <h2>Create New Alert</h2>
                <input type="text" id="ticker" placeholder="Ticker (e.g., AAPL)" maxlength="5" />
                <input type="number" id="target" placeholder="Target Price" step="0.01" />
                <button onclick="addAlert()">Add Alert</button>
                <div id="msg"></div>
            </div>
            
            <div class="card">
                <h2>My Alerts</h2>
                <div id="alerts">Loading...</div>
            </div>
        </div>
        
        <script>
            async function loadAlerts() {
                const res = await fetch('/api/alerts');
                const data = await res.json();
                
                if (!data.success) return;
                
                const active = data.alerts.filter(a => a.active);
                const alertsEl = document.getElementById('alerts');
                
                if (active.length === 0) {
                    alertsEl.innerHTML = '<p>No active alerts. Create one above!</p>';
                    return;
                }
                
                alertsEl.innerHTML = active.map(a => `
                    <div class="alert-item">
                        <div>
                            <strong>${a.ticker}</strong> ${a.direction === 'up' ? '↑' : '↓'}<br>
                            Current: $${(a.current_price || 0).toFixed(2)} → Target: $${a.target_price.toFixed(2)}
                        </div>
                        <button class="delete-btn" onclick="deleteAlert(${a.id})">Delete</button>
                    </div>
                `).join('');
            }
            
            async function addAlert() {
                const ticker = document.getElementById('ticker').value.toUpperCase();
                const target = parseFloat(document.getElementById('target').value);
                
                const res = await fetch('/api/alerts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ticker, target_price: target })
                });
                
                const data = await res.json();
                if (data.success) {
                    document.getElementById('ticker').value = '';
                    document.getElementById('target').value = '';
                    loadAlerts();
                }
            }
            
            async function deleteAlert(id) {
                await fetch(`/api/alerts/${id}`, { method: 'DELETE' });
                loadAlerts();
            }
            
            async function logout() {
                await fetch('/api/logout');
                window.location.href = '/login';
            }
            
            loadAlerts();
            setInterval(loadAlerts, 30000);
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

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
