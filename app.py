from flask import Flask, request, jsonify, render_template_string, redirect, url_for
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import logging
import os
from database import db
from models import User, Alert
from price_checker import price_checker
from alert_processor import alert_processor
from ticker_fetcher import ticker_fetcher
from bitcoin_scanner import bitcoin_scanner
import time

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
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: #fff;
            padding: 20px;
        }

        .container { max-width: 1400px; margin: 0 auto; }

        .nav {
            display: flex;
            gap: 20px;
            margin-bottom: 30px;
            padding: 15px;
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
        }

        .nav a {
            color: #64ffda;
            text-decoration: none;
            font-weight: 500;
            transition: color 0.3s;
        }

        .nav a:hover { color: #fff; }

        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 30px;
            border-radius: 15px;
            margin-bottom: 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        }

        .header h1 {
            font-size: 32px;
            margin-bottom: 5px;
        }

        .header p {
            opacity: 0.9;
            font-size: 14px;
        }

        .logout-btn {
            padding: 10px 20px;
            background: rgba(255,255,255,0.2);
            border: 1px solid rgba(255,255,255,0.3);
            color: white;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: all 0.3s;
        }

        .logout-btn:hover {
            background: rgba(255,255,255,0.3);
            transform: translateY(-2px);
        }

        .grid {
            display: grid;
            grid-template-columns: 1fr 2fr;
            gap: 25px;
            margin-bottom: 30px;
        }

        @media (max-width: 968px) {
            .grid { grid-template-columns: 1fr; }
        }

        .card {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.2);
        }

        .card h2 {
            font-size: 20px;
            margin-bottom: 20px;
            color: #64ffda;
        }

        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            color: #64ffda;
            font-size: 14px;
        }

        input, select {
            width: 100%;
            padding: 12px 15px;
            background: rgba(255,255,255,0.1);
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 8px;
            color: #fff;
            font-size: 15px;
            transition: all 0.3s;
        }
            
        input:focus, select:focus {
                outline: none;
                border-color: #64ffda;
                background: rgba(255,255,255,0.15);
        }
            
        input::placeholder {
                color: rgba(255,255,255,0.4);
        }
            
        .autocomplete-container {
                position: relative;
                margin-bottom: 15px;
        }

       .autocomplete-dropdown {
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            max-height: 300px;
            overflow-y: auto;
            background: rgba(30,30,46,0.98);
            border: 1px solid rgba(100,255,218,0.3);
            border-radius: 8px;
            margin-top: 5px;
            z-index: 1000;
            display: none;
            box-shadow: 0 10px 40px rgba(0,0,0,0.4);
        }
            
        .autocomplete-item {
            padding: 12px 15px;
            cursor: pointer;
            transition: background 0.2s;
            border-bottom: 1px solid rgba(255,255,255,0.05);
         }
            
        .autocomplete-item:hover {
            background: rgba(100,255,218,0.1);
         }
            
        .ticker-symbol {
            font-weight: 600;
            color: #64ffda;
         }
            
         .ticker-name {
            font-size: 13px;
            color: #888;
            margin-left: 10px;
         }
            
        .ticker-type {
            float: right;
            font-size: 11px;
            padding: 2px 8px;
            background: rgba(100,255,218,0.2);
            border-radius: 4px;
            color: #64ffda;
        }
            
        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            font-size: 15px;
            transition: transform 0.2s;
            margin-top: 10px;
        }
            
        button:hover {
            transform: translateY(-2px);
        }
            
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
            
        .message {
            padding: 12px;
            border-radius: 8px;
            margin-top:15px;
            font-size: 14px;
        }
        .success {
            background: rgba(76,175,80,0.2);
            border: 1px solid rgba(76,175,80,0.4);
            color: #4caf50;
        }
        
        .error {
            background: rgba(244,67,54,0.2);
            border: 1px solid rgba(244,67,54,0.4);
            color: #f44336;
        }
        
        .alert-item {
            background: rgba(255,255,255,0.03);
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 15px;
            border-left: 4px solid #64ffda;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: all 0.3s;
        }
        
        .alert-item:hover {
            background: rgba(255,255,255,0.06);
            transform: translateX(5px);
        }
        
        .alert-info {
            flex: 1;
        }
        
        .alert-ticker {
            font-size: 24px;
            font-weight: 700;
            color: #64ffda;
            margin-bottom: 8px;
        }
        
        .alert-direction {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 5px;
            font-size: 12px;
            font-weight: 600;
            margin-left: 10px;
        }
        
        .direction-up {
            background: rgba(76,175,80,0.2);
            color: #4caf50;
        }
        
        .direction-down {
            background: rgba(244,67,54,0.2);
            color: #f44336;
        }
        
        .alert-prices {
            font-size: 14px;
            color: #aaa;
            margin-top: 5px;
        }
        
        .current-price {
            color: #fff;
            font-weight: 600;
        }
        
        .target-price {
            color: #ffc107;
            font-weight: 600;
        }
        
        .alert-status {
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            margin-right: 15px;
        }
        
        .status-active {
            background: rgba(33,150,243,0.2);
            color: #2196f3;
        }
        
        .status-triggered {
            background: rgba(255,193,7,0.2);
            color: #ffc107;
        }
        
        .delete-btn {
            padding: 10px 20px;
            background: rgba(244,67,54,0.2);
            border: 1px solid rgba(244,67,54,0.3);
            color: #f44336;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.3s;
            width: auto;
            margin: 0;
        }
        
        .delete-btn:hover {
            background: rgba(244,67,54,0.3);
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #64ffda;
            font-size: 16px;
        }
        
        .empty {
            text-align: center;
            padding: 40px;
            color: #666;
        }
        
        .spinner {
            border: 3px solid rgba(100,255,218,0.1);
            border-top: 3px solid #64ffda;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="nav">
            <a href="/dashboard">📊 Stock Alerts</a>
            <a href="/bitcoin-scanner">₿ Bitcoin Scanner</a>
        </div>
        
        <div class="header">
            <div>
                <h1>📊 Stock Price Alerts</h1>
                <p id="userEmail">Loading...</p>
            </div>
            <button class="logout-btn" onclick="logout()">Logout</button>
        </div>
        
        <div class="grid">
            <div class="card">
                <h2>Create New Alert</h2>
                
                <div class="autocomplete-container">
                    <label>Stock / Crypto Ticker</label>
                    <input 
                        type="text" 
                        id="tickerInput" 
                        placeholder="Search ticker (e.g., AAPL, BTC-USD)" 
                        autocomplete="off"
                    />
                    <div id="autocompleteDropdown" class="autocomplete-dropdown"></div>
                </div>
                
                <label>Target Price ($)</label>
                <input type="number" id="targetPrice" placeholder="Enter target price" step="0.01" />
                
                <button onclick="createAlert()" id="createBtn">
                    Create Alert
                </button>
                
                <div id="message"></div>
            </div>
            
            <div class="card">
                <h2>Your Active Alerts</h2>
                <div id="alertsList">
                    <div class="loading">
                        <div class="spinner"></div>
                        Loading alerts...
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let allTickers = [];
        let selectedTicker = null;
        
        // Load tickers on page load
        async function loadTickers() {
            try {
              console.log('Loading tickers...');
              const res = await fetch('/api/tickers');
              const data = await res.json();
        
        if (data.success) {
            allTickers = data.tickers;
            console.log(`✅ Loaded ${allTickers.length} tickers`);
        } else {
            console.error('❌ Failed to load tickers:', data);
        }
    } catch (error) {
        console.error('❌ Error loading tickers:', error);
        // Fallback: add some basic tickers so autocomplete still works
        allTickers = [
            {symbol: 'AAPL', name: 'Apple Inc.', type: 'Stock'},
            {symbol: 'TSLA', name: 'Tesla Inc.', type: 'Stock'},
            {symbol: 'MSFT', name: 'Microsoft Corporation', type: 'Stock'},
            {symbol: 'BTC-USD', name: 'Bitcoin USD', type: 'Crypto'}
        ];
        console.log('Using fallback ticker list');
    }
}

        
        // Autocomplete functionality
        const tickerInput = document.getElementById('tickerInput');
        const dropdown = document.getElementById('autocompleteDropdown');
        
        tickerInput.addEventListener('input', function() {
    const query = this.value.toUpperCase().trim();
    
    console.log(`Searching for: "${query}"`);
    
    if (query.length < 1) {
        dropdown.style.display = 'none';
        selectedTicker = null;
        return;
    }
    
    if (allTickers.length === 0) {
        console.error('No tickers loaded yet!');
        dropdown.innerHTML = '<div class="autocomplete-item">Loading tickers...</div>';
        dropdown.style.display = 'block';
        return;
    }
    
    const matches = allTickers.filter(t => 
        t.symbol.toUpperCase().includes(query) || 
        t.name.toUpperCase().includes(query)
    ).slice(0, 10);
    
    console.log(`Found ${matches.length} matches`);
    
    if (matches.length === 0) {
        dropdown.style.display = 'none';
        return;
    }
    
    dropdown.innerHTML = matches.map(ticker => `
        <div class="autocomplete-item" onclick="selectTicker('${ticker.symbol}', '${ticker.name}')">
            <span class="ticker-symbol">${ticker.symbol}</span>
            <span class="ticker-name">${ticker.name}</span>
            <span class="ticker-type">${ticker.type}</span>
        </div>
    `).join('');
    
    dropdown.style.display = 'block';
    console.log('Dropdown shown');
});

        
        function selectTicker(symbol, name) {
            selectedTicker = symbol;
            tickerInput.value = symbol;
            dropdown.style.display = 'none';
        }
        
        // Close dropdown when clicking outside
        document.addEventListener('click', function(e) {
            if (!tickerInput.contains(e.target) && !dropdown.contains(e.target)) {
                dropdown.style.display = 'none';
            }
        });
        
        async function createAlert() {
            const ticker = selectedTicker || tickerInput.value.toUpperCase().trim();
            const target = parseFloat(document.getElementById('targetPrice').value);
            const msgEl = document.getElementById('message');
            const btn = document.getElementById('createBtn');
            
            if (!ticker || !target) {
                msgEl.innerHTML = '<div class="message error">Please select a ticker and enter a target price</div>';
                return;
            }
            
            btn.disabled = true;
            btn.textContent = 'Creating...';
            
            try {
                const res = await fetch('/api/alerts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ticker, target_price: target })
                });
                
                const data = await res.json();
                
                if (data.success) {
                    msgEl.innerHTML = '<div class="message success">✓ Alert created successfully!</div>';
                    tickerInput.value = '';
                    document.getElementById('targetPrice').value = '';
                    selectedTicker = null;
                    loadAlerts();
                } else {
                    msgEl.innerHTML = `<div class="message error">✗ ${data.error}</div>`;
                }
            } catch (error) {
                msgEl.innerHTML = '<div class="message error">✗ Failed to create alert</div>';
            } finally {
                btn.disabled = false;
                btn.textContent = 'Create Alert';
            }
        }
        
        async function loadAlerts() {
    const alertsEl = document.getElementById('alertsList');
    
    try {
        const res = await fetch('/api/alerts');
        const data = await res.json();
        
        console.log('📊 Alerts loaded:', data);
        
        if (!data.success) {
            alertsEl.innerHTML = '<div class="error">Failed to load alerts</div>';
            return;
        }
        
        const active = data.alerts.filter(a => a.active);
        
        if (active.length === 0) {
            alertsEl.innerHTML = '<div class="empty">No active alerts. Create one to get started!</div>';
            return;
        }
        
        alertsEl.innerHTML = active.map(alert => {
            const direction = alert.direction === 'up' ? 'UP ↑' : 'DOWN ↓';
            const directionClass = alert.direction === 'up' ? 'direction-up' : 'direction-down';
            
            // Calculate progress toward target
            const current = alert.current_price || 0;
            const target = alert.target_price;
            const progress = alert.direction === 'up' 
                ? (current / target * 100).toFixed(1)
                : (target / current * 100).toFixed(1);
            
            // Log to console for debugging
            console.log(`${alert.ticker}: $${current.toFixed(2)} → $${target.toFixed(2)} (${progress}%)`);
            
            return `
                <div class="alert-item">
                    <div class="alert-info">
                        <div class="alert-ticker">
                            ${alert.ticker}
                            <span class="alert-direction ${directionClass}">${direction}</span>
                        </div>
                        <div class="alert-prices">
                            Current: <span class="current-price">$${current.toFixed(2)}</span>
                            →
                            Target: <span class="target-price">$${target.toFixed(2)}</span>
                            <span style="color: #888; margin-left: 10px;">(${progress}%)</span>
                        </div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <span class="alert-status status-active">ACTIVE</span>
                        <button class="delete-btn" onclick="deleteAlert(${alert.id})">Delete</button>
                    </div>
                </div>
            `;
        }).join('');
        
    } catch (error) {
        console.error('❌ Error loading alerts:', error);
        alertsEl.innerHTML = '<div class="error">Failed to load alerts</div>';
    }
}

        async function deleteAlert(id) {
            if (!confirm('Delete this alert?')) return;
            
            try {
                await fetch(`/api/alerts/${id}`, { method: 'DELETE' });
                loadAlerts();
            } catch (error) {
                console.error('Error deleting alert:', error);
            }
        }
        
        async function logout() {
            await fetch('/api/logout');
            window.location.href = '/login';
        }
        
        // Initialize
        console.log('starting initialize')
        loadAlerts();
        loadTickers();
        setInterval(loadAlerts, 30000); // Refresh every 30 seconds
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
    """Get current user's alerts"""
    try:
        alerts_raw = Alert.get_user_alerts(current_user.id)
        
        # Convert to plain dicts with explicit price conversion
        alerts = []
        for alert in alerts_raw:
            alerts.append({
                'id': alert['id'],
                'ticker': alert['ticker'],
                'target_price': float(alert['target_price']),
                'current_price': float(alert['current_price']) if alert['current_price'] else None,
                'direction': alert['direction'],
                'active': alert['active'],
                'created_at': alert['created_at'].isoformat() if hasattr(alert['created_at'], 'isoformat') else str(alert['created_at']),
                'triggered_at': alert['triggered_at'].isoformat() if alert.get('triggered_at') and hasattr(alert['triggered_at'], 'isoformat') else alert.get('triggered_at'),
                'triggered_price': float(alert['triggered_price']) if alert.get('triggered_price') else None
            })
        
        logger.info(f"📤 Returning {len(alerts)} alerts for user {current_user.id}")
        
        # Log each alert's current state
        for alert in alerts:
            logger.debug(f"Alert: {alert['ticker']} - Current: ${alert['current_price'] or 0:.2f}, Target: ${alert['target_price']:.2f}")
        
        return jsonify({'success': True, 'alerts': alerts})
    
    except Exception as e:
        logger.error(f"❌ Error getting alerts for user {current_user.id}: {e}")
        return jsonify({'success': False, 'error': str(e), 'alerts': []}), 500

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

@app.route('/api/tickers', methods=['GET'])
def get_tickers():
    """Get list of all available tickers"""
    tickers = ticker_fetcher.get_all_tickers()
    return jsonify({'success': True, 'tickers': tickers})

@app.route('/bitcoin-scanner')
@login_required
def bitcoin_scanner_page():
    """Bitcoin transaction scanner page"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Bitcoin Scanner - Stock Alerts</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                min-height: 100vh;
                color: #fff;
                padding: 20px;
            }
            .nav {
                display: flex;
                gap: 20px;
                margin-bottom: 30px;
                padding: 15px;
                background: rgba(255,255,255,0.05);
                border-radius: 10px;
            }
            .nav a {
                color: #64ffda;
                text-decoration: none;
                font-weight: 500;
            }
            .container { max-width: 1200px; margin: 0 auto; }
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 30px;
                border-radius: 15px;
                margin-bottom: 30px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.3);
            }
            .header h1 { font-size: 32px; margin-bottom: 10px; }
            .card {
                background: rgba(255,255,255,0.05);
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 15px;
                padding: 25px;
                margin-bottom: 25px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.2);
            }
            .form-grid {
                display: grid;
                grid-template-columns: 1fr 1fr auto;
                gap: 15px;
                margin-bottom: 20px;
            }
            label {
                display: block;
                margin-bottom: 8px;
                font-weight: 500;
                color: #64ffda;
            }
            input, select {
                width: 100%;
                padding: 12px 15px;
                background: rgba(255,255,255,0.1);
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 8px;
                color: #fff;
                font-size: 15px;
            }
            button {
                padding: 12px 30px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: 600;
                cursor: pointer;
                font-size: 15px;
                transition: transform 0.2s;
            }
            button:hover { transform: translateY(-2px); }
            button:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
            .tx-table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }
            .tx-table th {
                background: rgba(100,255,218,0.1);
                padding: 15px;
                text-align: left;
                font-weight: 600;
                color: #64ffda;
                border-bottom: 2px solid rgba(100,255,218,0.3);
            }
            .tx-table td {
                padding: 15px;
                border-bottom: 1px solid rgba(255,255,255,0.05);
            }
            .tx-table tr:hover {
                background: rgba(255,255,255,0.03);
            }
            .hash {
                font-family: monospace;
                color: #64ffda;
                font-size: 12px;
            }
            .amount {
                font-weight: 600;
                color: #f39c12;
            }
            .address {
                font-family: monospace;
                font-size: 11px;
                color: #888;
            }
            .loading {
                text-align: center;
                padding: 40px;
                color: #64ffda;
            }
            .empty {
                text-align: center;
                padding: 40px;
                color: #888;
            }
            .stats {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 20px;
            }
            .stat-card {
                background: rgba(100,255,218,0.1);
                padding: 20px;
                border-radius: 10px;
                border: 1px solid rgba(100,255,218,0.2);
            }
            .stat-value {
                font-size: 28px;
                font-weight: 700;
                color: #64ffda;
            }
            .stat-label {
                font-size: 13px;
                color: #888;
                margin-top: 5px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="nav">
                <a href="/dashboard">📊 Stock Alerts</a>
                <a href="/bitcoin-scanner">₿ Bitcoin Scanner</a>
                <a href="#" onclick="logout()">Logout</a>
            </div>

            <div class="header">
                <h1>₿ Bitcoin Transaction Scanner</h1>
                <p>Scan on-chain transactions for large BTC movements</p>
            </div>

            <div class="card">
                <h2 style="margin-bottom: 20px;">Scan Parameters</h2>
                <div class="form-grid">
                    <div>
                        <label>Minimum Amount (BTC)</label>
                        <input type="number" id="minAmount" value="10" step="0.1" min="0.1">
                    </div>
                    <div>
                        <label>Time Range</label>
                        <select id="timeRange">
                            <option value="24">Last 24 hours</option>
                            <option value="168">Last 7 days</option>
                            <option value="720">Last 30 days</option>
                            <option value="4320">Last 6 months</option>
                        </select>
                    </div>
                    <div style="display: flex; align-items: flex-end;">
                        <button onclick="scanTransactions()" id="scanBtn">Scan Blockchain</button>
                    </div>
                </div>
                <div style="background: rgba(255,193,7,0.1); padding: 15px; border-radius: 8px; border-left: 4px solid #ffc107;">
                    <strong>⚠️ Note:</strong> Uses Blockchain.info free API. Shows recent unconfirmed + latest confirmed transactions.
                    Full historical scanning requires paid API or running your own Bitcoin node.
                </div>
            </div>

            <div class="card">
                <div class="stats" id="stats" style="display: none;">
                    <div class="stat-card">
                        <div class="stat-value" id="txCount">-</div>
                        <div class="stat-label">Transactions Found</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="totalBTC">-</div>
                        <div class="stat-label">Total BTC Volume</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="totalUSD">-</div>
                        <div class="stat-label">Total USD Value</div>
                    </div>
                </div>

                <div id="results"></div>
            </div>
        </div>

        <script>
            async function scanTransactions() {
                const minAmount = parseFloat(document.getElementById('minAmount').value);
                const timeRange = parseInt(document.getElementById('timeRange').value);
                const resultsEl = document.getElementById('results');
                const scanBtn = document.getElementById('scanBtn');
                
                scanBtn.disabled = true;
                scanBtn.textContent = 'Scanning...';
                resultsEl.innerHTML = '<div class="loading">🔍 Scanning Bitcoin blockchain...</div>';
                
                try {
                    const res = await fetch('/api/bitcoin/scan', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ min_amount: minAmount, time_range: timeRange })
                    });
                    
                    const data = await res.json();
                    
                    if (data.success && data.transactions.length > 0) {
                        displayResults(data.transactions);
                    } else {
                        resultsEl.innerHTML = '<div class="empty">No transactions found matching your criteria.</div>';
                        document.getElementById('stats').style.display = 'none';
                    }
                } catch (error) {
                    resultsEl.innerHTML = '<div class="empty">Error scanning blockchain. Please try again.</div>';
                } finally {
                    scanBtn.disabled = false;
                    scanBtn.textContent = 'Scan Blockchain';
                }
            }
            
            function displayResults(transactions) {
                const statsEl = document.getElementById('stats');
                const resultsEl = document.getElementById('results');
                
                // Calculate stats
                const totalBTC = transactions.reduce((sum, tx) => sum + tx.amount_btc, 0);
                const totalUSD = transactions.reduce((sum, tx) => sum + tx.amount_usd, 0);
                
                // Update stats
                document.getElementById('txCount').textContent = transactions.length;
                document.getElementById('totalBTC').textContent = totalBTC.toFixed(2) + ' BTC';
                document.getElementById('totalUSD').textContent = '$' + totalUSD.toLocaleString();
                statsEl.style.display = 'grid';
                
                // Build table
                let html = `
                    <table class="tx-table">
                        <thead>
                            <tr>
                                <th>Transaction Hash</th>
                                <th>Time</th>
                                <th>Amount</th>
                                <th>From</th>
                                <th>To</th>
                            </tr>
                        </thead>
                        <tbody>
                `;
                
                transactions.forEach(tx => {
                    const time = new Date(tx.time).toLocaleString();
                    const fromAddr = tx.from_addresses.slice(0, 2).join('<br>');
                    const toAddr = tx.to_addresses.slice(0, 2).join('<br>');
                    
                    html += `
                        <tr>
                            <td><a href="https://blockchain.info/tx/${tx.hash}" target="_blank" class="hash">${tx.hash.substring(0, 16)}...</a></td>
                            <td>${time}</td>
                            <td class="amount">${tx.amount_btc.toFixed(4)} BTC<br><span style="font-size:12px;color:#888;">$${tx.amount_usd.toLocaleString()}</span></td>
                            <td class="address">${fromAddr}${tx.num_inputs > 2 ? '<br>+' + (tx.num_inputs - 2) + ' more' : ''}</td>
                            <td class="address">${toAddr}${tx.num_outputs > 2 ? '<br>+' + (tx.num_outputs - 2) + ' more' : ''}</td>
                        </tr>
                    `;
                });
                
                html += '</tbody></table>';
                resultsEl.innerHTML = html;
            }
            
            async function logout() {
                await fetch('/api/logout');
                window.location.href = '/login';
            }
            // Initialize
            loadTickers();
            loadAlerts();
            setInterval(loadAlerts, 30000); // Refresh every 30 seconds
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/api/bitcoin/scan', methods=['POST'])
@login_required
def scan_bitcoin():
    """Scan Bitcoin blockchain for large transactions"""
    data = request.json
    min_amount = float(data.get('min_amount', 10))
    time_range = int(data.get('time_range', 24))
    
    transactions = bitcoin_scanner.scan_large_transactions(min_amount, time_range)
    
    return jsonify({
        'success': True,
        'transactions': transactions,
        'count': len(transactions)
    })

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
