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
from portfolio_calculator import portfolio_calculator
from models import Portfolio, Trade
from portfolio_calculator import portfolio_calculator
from price_checker import price_checker
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
            <a href="/portfolio">💼 Portfolio</a>
            <a href="#" onclick="logout()">Logout</a>
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
        // Add timestamp to prevent caching
        const timestamp = new Date().getTime();
        const res = await fetch(`/api/alerts?t=${timestamp}`);
        const data = await res.json();
        
        console.log(`📊 [${new Date().toLocaleTimeString()}] Alerts loaded:`, data);
        
        if (!data.success) {
            alertsEl.innerHTML = '<div class="error">Failed to load alerts</div>';
            return;
        }
        
        const active = data.alerts.filter(a => a.active);
        
        if (active.length === 0) {
            alertsEl.innerHTML = '<div class="empty">No active alerts. Create one to get started!</div>';
            return;
        }
        
        // Generate unique key for each render to force update
        const renderKey = Math.random().toString(36).substring(7);
        
        alertsEl.innerHTML = active.map(alert => {
            const direction = alert.direction === 'up' ? 'UP ↑' : 'DOWN ↓';
            const directionClass = alert.direction === 'up' ? 'direction-up' : 'direction-down';
            
            const current = alert.current_price || 0;
            const target = alert.target_price;
            const progress = alert.direction === 'up' 
                ? (current / target * 100).toFixed(1)
                : (target / current * 100).toFixed(1);
            
            const diff = Math.abs(current - target);
            const pct = ((diff / target) * 100).toFixed(1);
            
            // Visual indicator if price just updated
            const priceClass = 'current-price';
            
            console.log(`  ${alert.ticker}: $${current.toFixed(2)} → $${target.toFixed(2)} (${pct}% away)`);
            
            return `
                <div class="alert-item" data-key="${renderKey}">
                    <div class="alert-info">
                        <div class="alert-ticker">
                            ${alert.ticker}
                            <span class="alert-direction ${directionClass}">${direction}</span>
                        </div>
                        <div class="alert-prices">
                            Current: <span class="${priceClass}" id="price-${alert.id}">$${current.toFixed(2)}</span>
                            →
                            Target: <span class="target-price">$${target.toFixed(2)}</span>
                            <span style="color: #888; margin-left: 10px; font-size: 12px;">
                                ${pct}% away
                            </span>
                        </div>
                        <div style="font-size: 11px; color: #666; margin-top: 4px;">
                            Last updated: ${new Date().toLocaleTimeString()}
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
        setInterval(loadAlerts, 10000); // Refresh every 30 seconds
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
    try:
        logger.info("📊 /api/tickers called")
        tickers = ticker_fetcher.get_all_tickers()
        logger.info(f"✅ Returning {len(tickers)} tickers")
        return jsonify({'success': True, 'tickers': tickers})
    except Exception as e:
        logger.error(f"❌ Error in /api/tickers: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

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
                <a href="/portfolio">💼 Portfolio</a>
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
                    <div class="form-group">
    <label>Time Period</label>
    <select id="timeframeSelect" style="width: 100%; padding: 12px; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); border-radius: 8px; color: #fff;">
        <option value="24h">Last 24 Hours</option>
        <option value="7d">Last Week (7 days)</option>
        <option value="30d">Last Month (30 days)</option>
        <option value="180d">Last 6 Months (180 days)</option>
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
    try:
        data = request.json
        min_amount = float(data.get('min_amount', 100))
        
        # NEW: Support different timeframes
        timeframe = data.get('timeframe', '24h')
        
        # Convert timeframe to hours
        if timeframe == '7d':
            time_range = 24 * 7  # 168 hours
        elif timeframe == '30d':
            time_range = 24 * 30  # 720 hours
        elif timeframe == '180d':
            time_range = 24 * 180  # 4320 hours
        else:  # Default '24h'
            time_range = 24
        
        logger.info(f"Scanning for transactions > {min_amount} BTC in last {time_range} hours")
        # ... rest of existing code stays the same
    
        transactions = bitcoin_scanner.scan_large_transactions(min_amount, time_range)
    
        return jsonify({
            'success': True,
            'transactions': transactions,
            'count': len(transactions)
        })
# ============================================================================
# PORTFOLIO MANAGEMENT ROUTES
# ============================================================================

from models import Portfolio, Trade

@app.route('/portfolio')
@login_required
def portfolio_page():
    """Portfolio management page"""
    html = """
    <!DOCTYPE html>
<html>
<head>
    <title>Portfolio Management - Stock Alerts</title>
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
        
        .container { max-width: 1600px; margin: 0 auto; }
        
        /* Navigation */
        .nav {
            display: flex;
            gap: 20px;
            margin-bottom: 30px;
            padding: 15px;
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
            flex-wrap: wrap;
        }
        .nav a {
            color: #64ffda;
            text-decoration: none;
            font-weight: 500;
            transition: color 0.3s;
        }
        .nav a:hover { color: #fff; }
        
        /* Header */
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 30px;
            border-radius: 15px;
            margin-bottom: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        }
        
        /* Card Styles */
        .card {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 25px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.2);
        }
        
        .card h2 {
            color: #64ffda;
            margin-bottom: 20px;
            font-size: 22px;
        }
        
        .card h3 {
            color: #64ffda;
            margin-bottom: 15px;
            font-size: 18px;
        }
        
        /* Portfolio Summary Grid */
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .summary-item {
            background: rgba(100,255,218,0.1);
            padding: 20px;
            border-radius: 10px;
            border: 1px solid rgba(100,255,218,0.2);
        }
        
        .summary-label {
            font-size: 13px;
            color: rgba(255,255,255,0.7);
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .summary-value {
            font-size: 28px;
            font-weight: 700;
            color: #64ffda;
        }
        
        .summary-value.positive { color: #4caf50; }
        .summary-value.negative { color: #f44336; }
        
        /* Statistics */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
        }
        
        .stat-item {
            background: rgba(255,255,255,0.05);
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        
        .stat-label {
            font-size: 12px;
            color: rgba(255,255,255,0.6);
            margin-bottom: 5px;
        }
        
        .stat-value {
            font-size: 20px;
            font-weight: 600;
            color: #fff;
        }
        
        /* Form Styles */
        .form-group {
            margin-bottom: 15px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            color: #64ffda;
            font-size: 14px;
        }
        
        input, select, textarea {
            width: 100%;
            padding: 12px 15px;
            background: rgba(255,255,255,0.1);
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 8px;
            color: #fff;
            font-size: 15px;
            font-family: inherit;
        }
        
        textarea {
            min-height: 80px;
            resize: vertical;
        }
        
        input:focus, select:focus, textarea:focus {
            outline: none;
            border-color: #64ffda;
            background: rgba(255,255,255,0.15);
        }
        
        input:disabled {
            background: rgba(255,255,255,0.05);
            color: rgba(255,255,255,0.5);
            cursor: not-allowed;
        }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }
        
        .calculated-value {
            background: rgba(100,255,218,0.1);
            padding: 12px 15px;
            border-radius: 8px;
            border: 1px solid rgba(100,255,218,0.2);
            color: #64ffda;
            font-weight: 600;
            font-size: 15px;
        }
        
        /* Buttons */
        button {
            padding: 12px 24px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            font-size: 15px;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(102,126,234,0.4);
        }
        
        button:active {
            transform: translateY(0);
        }
        
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }
        
        .btn-delete {
            background: linear-gradient(135deg, #f44336 0%, #e91e63 100%);
            padding: 8px 16px;
            font-size: 13px;
        }
        
        .btn-edit {
            background: linear-gradient(135deg, #ff9800 0%, #ff5722 100%);
            padding: 8px 16px;
            font-size: 13px;
            margin-right: 8px;
        }
        
        .btn-close {
            background: linear-gradient(135deg, #2196f3 0%, #1976d2 100%);
            padding: 8px 16px;
            font-size: 13px;
            margin-right: 8px;
        }
        
        .btn-secondary {
            background: rgba(255,255,255,0.1);
            margin-left: 10px;
        }
        
        /* Table Styles */
        .table-container {
            overflow-x: auto;
            margin-top: 20px;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            min-width: 1000px;
        }
        
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        
        th {
            background: rgba(100,255,218,0.1);
            color: #64ffda;
            font-weight: 600;
            position: sticky;
            top: 0;
            z-index: 10;
        }
        
        tbody tr {
            transition: background 0.2s;
        }
        
        tbody tr:hover {
            background: rgba(255,255,255,0.05);
        }
        
        .ticker-cell {
            font-weight: 700;
            color: #64ffda;
            font-size: 15px;
        }
        
        .positive {
            color: #4caf50;
            font-weight: 600;
        }
        
        .negative {
            color: #f44336;
            font-weight: 600;
        }
        
        .neutral {
            color: #ffc107;
        }
        
        /* Warning Badges */
        .warning-badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            margin: 2px;
            text-transform: uppercase;
        }
        
        .warning-badge.error {
            background: rgba(244,67,54,0.3);
            border: 1px solid #f44336;
            color: #ff5252;
        }
        
        .warning-badge.warning {
            background: rgba(255,193,7,0.3);
            border: 1px solid #ffc107;
            color: #ffd54f;
        }
        
        /* Status Badges */
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .status-badge.open {
            background: rgba(76,175,80,0.2);
            color: #4caf50;
        }
        
        .status-badge.closed {
            background: rgba(158,158,158,0.2);
            color: #9e9e9e;
        }
        
        /* Messages */
        .message {
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 15px;
            animation: slideIn 0.3s ease-out;
        }
        
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(-10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
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
        
        /* Loading */
        .loading {
            text-align: center;
            padding: 40px;
            color: #64ffda;
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
        
        /* Modal */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.8);
            backdrop-filter: blur(5px);
        }
        
        .modal.active { display: flex; align-items: center; justify-content: center; }
        
        .modal-content {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            padding: 30px;
            border-radius: 15px;
            max-width: 500px;
            width: 90%;
            border: 1px solid rgba(100,255,218,0.2);
        }
        
        .modal-header {
            margin-bottom: 20px;
        }
        
        .modal-header h3 {
            color: #64ffda;
        }
        
        /* Responsive */
        @media (max-width: 768px) {
            .summary-grid {
                grid-template-columns: 1fr;
            }
            
            .stats-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            
            .grid {
                grid-template-columns: 1fr;
            }
            
            table {
                font-size: 12px;
            }
            
            th, td {
                padding: 8px 4px;
            }
            
            .summary-value {
                font-size: 22px;
            }
        }
        
        /* Tabs */
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            border-bottom: 2px solid rgba(255,255,255,0.1);
        }
        
        .tab {
            padding: 12px 24px;
            background: transparent;
            border: none;
            color: rgba(255,255,255,0.6);
            cursor: pointer;
            border-bottom: 2px solid transparent;
            margin-bottom: -2px;
            transition: all 0.3s;
        }
        
        .tab.active {
            color: #64ffda;
            border-bottom-color: #64ffda;
        }
        
        .tab:hover {
            color: #fff;
        }
        
        .tab-content {
            display: none;
        }
        
        .tab-content.active {
            display: block;
        }
        
        .info-text {
            font-size: 12px;
            color: rgba(255,255,255,0.6);
            margin-top: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Navigation -->
        <div class="nav">
            <a href="/dashboard">📊 Stock Alerts</a>
            <a href="/bitcoin-scanner">₿ Bitcoin Scanner</a>
            <a href="/portfolio">💼 Portfolio</a>
            <a href="#" onclick="logout()">Logout</a>
        </div>

        <!-- Header -->
        <div class="header">
            <h1>💼 Professional Portfolio Management</h1>
            <p>Advanced trading & risk management with automatic calculations</p>
        </div>

        <div id="message"></div>

        <!-- Portfolio Cash -->
        <div class="card">
            <h2>Portfolio Balance</h2>
            <div class="form-group">
                <label>Total Portfolio Cash ($)</label>
                <input type="number" id="portfolioCash" placeholder="Enter total portfolio value" step="0.01" min="0">
            </div>
            <button onclick="updatePortfolioCash()">Update Balance</button>
        </div>

        <!-- Portfolio Summary -->
        <div class="card" id="summaryCard">
            <h2>📈 Portfolio Overview</h2>
            <div class="summary-grid">
                <div class="summary-item">
                    <div class="summary-label">Portfolio Value</div>
                    <div class="summary-value" id="portfolioValue">$0.00</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Total Invested</div>
                    <div class="summary-value" id="totalInvested">$0.00</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Total at Risk</div>
                    <div class="summary-value neutral" id="totalRisk">$0.00</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Unrealized P&L</div>
                    <div class="summary-value" id="unrealizedPnl">$0.00</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Realized P&L</div>
                    <div class="summary-value" id="realizedPnl">$0.00</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Total Return</div>
                    <div class="summary-value" id="portfolioReturn">0.00%</div>
                </div>
            </div>
        </div>

        <!-- Trading Statistics -->
        <div class="card" id="statsCard">
            <h2>📊 Trading Performance</h2>
            <div class="stats-grid">
                <div class="stat-item">
                    <div class="stat-label">Win Rate</div>
                    <div class="stat-value" id="winRate">0%</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Total Trades</div>
                    <div class="stat-value" id="totalTrades">0</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Wins / Losses</div>
                    <div class="stat-value" id="winsLosses">0 / 0</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Avg Win</div>
                    <div class="stat-value positive" id="avgWin">$0.00</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Avg Loss</div>
                    <div class="stat-value negative" id="avgLoss">$0.00</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Expectancy</div>
                    <div class="stat-value" id="expectancy">$0.00</div>
                </div>
            </div>
        </div>

        <!-- Add/Edit Trade Form -->
        <div class="card">
            <h2 id="formTitle">➕ Add New Trade</h2>
            <div class="grid">
                <div class="form-group">
                    <label>Ticker *</label>
                    <input type="text" id="ticker" placeholder="e.g., AAPL" maxlength="10">
                </div>
                <div class="form-group">
                    <label>Buy Price ($) *</label>
                    <input type="number" id="buyPrice" step="0.01" min="0" oninput="calculateValues()">
                </div>
                <div class="form-group">
                    <label>Quantity *</label>
                    <input type="number" id="quantity" step="0.0001" min="0" oninput="calculateValues()">
                </div>
                <div class="form-group">
                    <label>Stop Loss ($)</label>
                    <input type="number" id="stopLoss" step="0.01" min="0" placeholder="Optional" oninput="calculateValues()">
                </div>
                <div class="form-group">
                    <label>Position Size ($) - Auto Calculated</label>
                    <div class="calculated-value" id="positionSizeDisplay">$0.00</div>
                    <div class="info-text">= Buy Price × Quantity</div>
                </div>
                <div class="form-group">
                    <label>Risk Amount ($) - Auto Calculated</label>
                    <div class="calculated-value" id="riskAmountDisplay">$0.00</div>
                    <div class="info-text">= |Buy Price - Stop Loss| × Quantity</div>
                </div>
                <div class="form-group">
                    <label>Take Profit ($)</label>
                    <input type="number" id="takeProfit" step="0.01" min="0" placeholder="Optional">
                </div>
                <div class="form-group">
                    <label>Timeframe *</label>
                    <select id="timeframe">
                        <option value="Long">Long</option>
                        <option value="Swing">Swing</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Trade Date *</label>
                    <input type="date" id="tradeDate">
                </div>
            </div>
            <div class="form-group">
                <label>Notes</label>
                <textarea id="notes" placeholder="Optional trade notes..."></textarea>
            </div>
            <button id="saveTradeBtn" onclick="saveTrade()">Add Trade</button>
            <button class="btn-secondary" onclick="clearForm()" style="display:none;" id="cancelBtn">Cancel</button>
        </div>

        <!-- Trades Table -->
        <div class="card">
            <h2>📋 Trade Journal</h2>
            
            <!-- Tabs -->
            <div class="tabs">
                <button class="tab active" onclick="switchTab(event, 'all')">All Trades</button>
                <button class="tab" onclick="switchTab(event, 'open')">Open Positions</button>
                <button class="tab" onclick="switchTab(event, 'closed')">Closed Positions</button>
            </div>

            <!-- All Trades Tab -->
            <div id="allTab" class="tab-content active">
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Status</th>
                                <th>Ticker</th>
                                <th>Date</th>
                                <th>Buy Price</th>
                                <th>Qty</th>
                                <th>Position $</th>
                                <th>Risk $</th>
                                <th>Risk %</th>
                                <th>R:R</th>
                                <th>P&L $</th>
                                <th>P&L %</th>
                                <th>Warnings</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="allTradesBody">
                            <tr><td colspan="13" class="loading"><div class="spinner"></div>Loading trades...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Open Trades Tab -->
            <div id="openTab" class="tab-content">
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Ticker</th>
                                <th>Date</th>
                                <th>Buy Price</th>
                                <th>Qty</th>
                                <th>Position $</th>
                                <th>Risk $</th>
                                <th>Risk %</th>
                                <th>R:R</th>
                                <th>Unrealized P&L $</th>
                                <th>Unrealized P&L %</th>
                                <th>Warnings</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="openTradesBody">
                            <tr><td colspan="12" class="loading"><div class="spinner"></div>Loading open trades...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Closed Trades Tab -->
            <div id="closedTab" class="tab-content">
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Ticker</th>
                                <th>Open Date</th>
                                <th>Close Date</th>
                                <th>Buy Price</th>
                                <th>Close Price</th>
                                <th>Qty</th>
                                <th>Realized P&L $</th>
                                <th>Realized P&L %</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="closedTradesBody">
                            <tr><td colspan="9" class="loading"><div class="spinner"></div>Loading closed trades...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <!-- Close Trade Modal -->
    <div id="closeModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3>Close Trade</h3>
            </div>
            <div class="form-group">
                <label>Close Price ($)</label>
                <input type="number" id="closePrice" step="0.01" min="0">
            </div>
            <div class="form-group">
                <label>Close Date</label>
                <input type="date" id="closeDate">
            </div>
            <button onclick="confirmCloseTrade()">Close Trade</button>
            <button class="btn-secondary" onclick="closeModal()">Cancel</button>
        </div>
    </div>

    <script>
        let portfolioCash = 0;
        let allTrades = [];
        let editingTradeId = null;
        let closingTradeId = null;

        // Initialize
        document.addEventListener('DOMContentLoaded', function() {
            console.log('Page loaded, initializing...');
            loadPortfolio();
            loadSummary();
            loadTrades();
            
            // Set today's date as default
            const today = new Date().toISOString().split('T')[0];
            document.getElementById('tradeDate').value = today;
            document.getElementById('closeDate').value = today;
        });

        // Calculate position size and risk amount automatically
        function calculateValues() {
            const buyPrice = parseFloat(document.getElementById('buyPrice').value) || 0;
            const quantity = parseFloat(document.getElementById('quantity').value) || 0;
            const stopLoss = parseFloat(document.getElementById('stopLoss').value) || 0;
            
            // Position Size = buy_price * quantity
            const positionSize = buyPrice * quantity;
            document.getElementById('positionSizeDisplay').textContent = 
                '$' + positionSize.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            
            // Risk Amount = |buy_price - stop_loss| * quantity
            let riskAmount = 0;
            if (stopLoss > 0) {
                riskAmount = Math.abs(buyPrice - stopLoss) * quantity;
            } else {
                // Default 2% risk if no stop loss
                riskAmount = positionSize * 0.02;
            }
            document.getElementById('riskAmountDisplay').textContent = 
                '$' + riskAmount.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
        }

        // Tab switching
        function switchTab(event, tab) {
            // Update tab buttons
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            
            // Update tab content
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.getElementById(tab + 'Tab').classList.add('active');
            
            // Render appropriate table
            renderTrades();
        }

        // Load portfolio cash
        async function loadPortfolio() {
            try {
                console.log('Loading portfolio...');
                const res = await fetch('/api/portfolio');
                const data = await res.json();
                console.log('Portfolio response:', data);
                if (data.success) {
                    portfolioCash = data.cash;
                    document.getElementById('portfolioCash').value = portfolioCash;
                    document.getElementById('portfolioValue').textContent = 
                        '$' + portfolioCash.toLocaleString('en-US', {minimumFractionDigits: 2});
                }
            } catch (error) {
                console.error('Error loading portfolio:', error);
                showMessage('Error loading portfolio: ' + error.message, 'error');
            }
        }

        // Update portfolio cash
        async function updatePortfolioCash() {
            const cash = parseFloat(document.getElementById('portfolioCash').value);
            
            if (isNaN(cash) || cash < 0) {
                showMessage('Please enter a valid amount', 'error');
                return;
            }

            try {
                const res = await fetch('/api/portfolio', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cash })
                });
                
                const data = await res.json();
                if (data.success) {
                    portfolioCash = cash;
                    showMessage('Portfolio balance updated!', 'success');
                    await loadSummary();
                    await loadTrades();
                }
            } catch (error) {
                console.error('Error updating portfolio:', error);
                showMessage('Failed to update portfolio balance', 'error');
            }
        }

        // Load portfolio summary
        async function loadSummary() {
            try {
                console.log('Loading summary...');
                const res = await fetch('/api/portfolio/summary');
                const data = await res.json();
                console.log('Summary response:', data);
                
                if (data.success) {
                    const summary = data.summary;
                    const stats = data.statistics;
                    
                    // Update summary
                    document.getElementById('totalInvested').textContent = 
                        '$' + summary.total_invested.toLocaleString('en-US', {minimumFractionDigits: 2});
                    document.getElementById('totalRisk').textContent = 
                        '$' + summary.total_risk.toLocaleString('en-US', {minimumFractionDigits: 2});
                    
                    const unrealizedEl = document.getElementById('unrealizedPnl');
                    unrealizedEl.textContent = '$' + summary.unrealized_pnl.toLocaleString('en-US', {minimumFractionDigits: 2});
                    unrealizedEl.className = 'summary-value ' + (summary.unrealized_pnl >= 0 ? 'positive' : 'negative');
                    
                    const realizedEl = document.getElementById('realizedPnl');
                    realizedEl.textContent = '$' + summary.realized_pnl.toLocaleString('en-US', {minimumFractionDigits: 2});
                    realizedEl.className = 'summary-value ' + (summary.realized_pnl >= 0 ? 'positive' : 'negative');
                    
                    const returnEl = document.getElementById('portfolioReturn');
                    returnEl.textContent = summary.portfolio_return_pct.toFixed(2) + '%';
                    returnEl.className = 'summary-value ' + (summary.portfolio_return_pct >= 0 ? 'positive' : 'negative');
                    
                    // Update statistics
                    document.getElementById('winRate').textContent = stats.win_rate.toFixed(1) + '%';
                    document.getElementById('totalTrades').textContent = stats.total_trades;
                    document.getElementById('winsLosses').textContent = stats.winning_trades + ' / ' + stats.losing_trades;
                    document.getElementById('avgWin').textContent = '$' + stats.avg_win.toLocaleString('en-US', {minimumFractionDigits: 2});
                    document.getElementById('avgLoss').textContent = '$' + stats.avg_loss.toLocaleString('en-US', {minimumFractionDigits: 2});
                    
                    const expectancyEl = document.getElementById('expectancy');
                    expectancyEl.textContent = '$' + stats.expectancy.toLocaleString('en-US', {minimumFractionDigits: 2});
                    expectancyEl.className = 'stat-value ' + (stats.expectancy >= 0 ? 'positive' : 'negative');
                }
            } catch (error) {
                console.error('Error loading summary:', error);
            }
        }

        // Load trades
        async function loadTrades() {
            try {
                console.log('Loading trades...');
                const res = await fetch('/api/trades/enriched');
                const data = await res.json();
                console.log('Trades response:', data);
                
                if (data.success) {
                    allTrades = data.trades;
                    console.log('Loaded', allTrades.length, 'trades');
                    renderTrades();
                } else {
                    console.error('Failed to load trades:', data.error);
                    showMessage('Failed to load trades: ' + data.error, 'error');
                }
            } catch (error) {
                console.error('Error loading trades:', error);
                showMessage('Error loading trades: ' + error.message, 'error');
            }
        }

        // Render trades based on active tab
        function renderTrades() {
            const activeTab = document.querySelector('.tab.active');
            if (!activeTab) return;
            
            const tabText = activeTab.textContent.toLowerCase();
            
            if (tabText.includes('all')) {
                renderAllTrades();
            } else if (tabText.includes('open')) {
                renderOpenTrades();
            } else if (tabText.includes('closed')) {
                renderClosedTrades();
            }
        }

        // Render all trades
        function renderAllTrades() {
            const tbody = document.getElementById('allTradesBody');
            
            if (allTrades.length === 0) {
                tbody.innerHTML = '<tr><td colspan="13" style="text-align: center; padding: 40px; color: #888;">No trades yet. Add your first trade above!</td></tr>';
                return;
            }

            tbody.innerHTML = allTrades.map(trade => {
                const status = trade.is_closed ? 'closed' : 'open';
                const pnl = trade.is_closed ? trade.realized_pnl : trade.unrealized_pnl;
                const pnlPct = trade.is_closed ? trade.realized_pnl_pct : trade.unrealized_pnl_pct;
                
                const warnings = (trade.warnings || []).map(w => 
                    `<span class="warning-badge ${w.severity}">${w.type.replace('_', ' ')}</span>`
                ).join('');
                
                return `
                    <tr>
                        <td><span class="status-badge ${status}">${status.toUpperCase()}</span></td>
                        <td class="ticker-cell">${trade.ticker}</td>
                        <td>${trade.trade_date}</td>
                        <td>$${parseFloat(trade.buy_price).toFixed(2)}</td>
                        <td>${parseFloat(trade.quantity).toFixed(4)}</td>
                        <td>$${parseFloat(trade.position_size).toLocaleString('en-US', {minimumFractionDigits: 2})}</td>
                        <td>$${parseFloat(trade.risk_amount).toLocaleString('en-US', {minimumFractionDigits: 2})}</td>
                        <td class="${trade.risk_pct > 2 ? 'negative' : ''}">${trade.risk_pct}%</td>
                        <td class="${trade.rr_ratio !== null && trade.rr_ratio < 1.5 ? 'negative' : 'positive'}">${trade.rr_ratio !== null ? trade.rr_ratio.toFixed(2) : 'N/A'}</td>
                        <td class="${pnl !== null && pnl >= 0 ? 'positive' : 'negative'}">${pnl !== null ? '$' + pnl.toLocaleString('en-US', {minimumFractionDigits: 2}) : 'N/A'}</td>
                        <td class="${pnlPct !== null && pnlPct >= 0 ? 'positive' : 'negative'}">${pnlPct !== null ? pnlPct.toFixed(2) + '%' : 'N/A'}</td>
                        <td>${warnings || '-'}</td>
                        <td style="white-space: nowrap;">
                            ${!trade.is_closed ? `<button class="btn-close" onclick="openCloseModal(${trade.id})">Close</button>` : ''}
                            <button class="btn-edit" onclick="editTrade(${trade.id})">Edit</button>
                            <button class="btn-delete" onclick="deleteTrade(${trade.id})">Delete</button>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        // Render open trades
        function renderOpenTrades() {
            const tbody = document.getElementById('openTradesBody');
            const openTrades = allTrades.filter(t => !t.is_closed);
            
            if (openTrades.length === 0) {
                tbody.innerHTML = '<tr><td colspan="12" style="text-align: center; padding: 40px; color: #888;">No open positions</td></tr>';
                return;
            }

            tbody.innerHTML = openTrades.map(trade => {
                const warnings = (trade.warnings || []).map(w => 
                    `<span class="warning-badge ${w.severity}">${w.type.replace('_', ' ')}</span>`
                ).join('');
                
                return `
                    <tr>
                        <td class="ticker-cell">${trade.ticker}</td>
                        <td>${trade.trade_date}</td>
                        <td>$${parseFloat(trade.buy_price).toFixed(2)}</td>
                        <td>${parseFloat(trade.quantity).toFixed(4)}</td>
                        <td>$${parseFloat(trade.position_size).toLocaleString('en-US', {minimumFractionDigits: 2})}</td>
                        <td>$${parseFloat(trade.risk_amount).toLocaleString('en-US', {minimumFractionDigits: 2})}</td>
                        <td class="${trade.risk_pct > 2 ? 'negative' : ''}">${trade.risk_pct}%</td>
                        <td class="${trade.rr_ratio !== null && trade.rr_ratio < 1.5 ? 'negative' : 'positive'}">${trade.rr_ratio !== null ? trade.rr_ratio.toFixed(2) : 'N/A'}</td>
                        <td class="${trade.unrealized_pnl !== null && trade.unrealized_pnl >= 0 ? 'positive' : 'negative'}">${trade.unrealized_pnl !== null ? '$' + trade.unrealized_pnl.toLocaleString('en-US', {minimumFractionDigits: 2}) : 'N/A'}</td>
                        <td class="${trade.unrealized_pnl_pct !== null && trade.unrealized_pnl_pct >= 0 ? 'positive' : 'negative'}">${trade.unrealized_pnl_pct !== null ? trade.unrealized_pnl_pct.toFixed(2) + '%' : 'N/A'}</td>
                        <td>${warnings || '-'}</td>
                        <td style="white-space: nowrap;">
                            <button class="btn-close" onclick="openCloseModal(${trade.id})">Close</button>
                            <button class="btn-edit" onclick="editTrade(${trade.id})">Edit</button>
                            <button class="btn-delete" onclick="deleteTrade(${trade.id})">Delete</button>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        // Render closed trades
        function renderClosedTrades() {
            const tbody = document.getElementById('closedTradesBody');
            const closedTrades = allTrades.filter(t => t.is_closed);
            
            if (closedTrades.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 40px; color: #888;">No closed positions</td></tr>';
                return;
            }

            tbody.innerHTML = closedTrades.map(trade => {
                return `
                    <tr>
                        <td class="ticker-cell">${trade.ticker}</td>
                        <td>${trade.trade_date}</td>
                        <td>${trade.close_date || 'N/A'}</td>
                        <td>$${parseFloat(trade.buy_price).toFixed(2)}</td>
                        <td>$${parseFloat(trade.close_price).toFixed(2)}</td>
                        <td>${parseFloat(trade.quantity).toFixed(4)}</td>
                        <td class="${trade.realized_pnl >= 0 ? 'positive' : 'negative'}">$${trade.realized_pnl.toLocaleString('en-US', {minimumFractionDigits: 2})}</td>
                        <td class="${trade.realized_pnl_pct >= 0 ? 'positive' : 'negative'}">${trade.realized_pnl_pct.toFixed(2)}%</td>
                        <td style="white-space: nowrap;">
                            <button class="btn-edit" onclick="editTrade(${trade.id})">Edit</button>
                            <button class="btn-delete" onclick="deleteTrade(${trade.id})">Delete</button>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        // Save trade (add or update)
        async function saveTrade() {
            const ticker = document.getElementById('ticker').value.toUpperCase().trim();
            const buyPrice = parseFloat(document.getElementById('buyPrice').value);
            const quantity = parseFloat(document.getElementById('quantity').value);
            const stopLoss = document.getElementById('stopLoss').value ? parseFloat(document.getElementById('stopLoss').value) : null;
            const takeProfit = document.getElementById('takeProfit').value ? parseFloat(document.getElementById('takeProfit').value) : null;
            const timeframe = document.getElementById('timeframe').value;
            const tradeDate = document.getElementById('tradeDate').value;
            const notes = document.getElementById('notes').value.trim();

            if (!ticker || isNaN(buyPrice) || isNaN(quantity) || !tradeDate) {
                showMessage('Please fill in all required fields (Ticker, Buy Price, Quantity, Date)', 'error');
                return;
            }

            if (buyPrice <= 0 || quantity <= 0) {
                showMessage('Buy price and quantity must be positive', 'error');
                return;
            }

            const payload = {
                ticker,
                buy_price: buyPrice,
                quantity,
                timeframe,
                trade_date: tradeDate,
                stop_loss: stopLoss,
                take_profit: takeProfit,
                notes: notes || null
            };

            console.log('Saving trade:', payload);

            try {
                const saveBtn = document.getElementById('saveTradeBtn');
                saveBtn.disabled = true;
                saveBtn.textContent = editingTradeId ? 'Updating...' : 'Adding...';
                
                const url = editingTradeId ? `/api/trades/${editingTradeId}` : '/api/trades';
                const method = editingTradeId ? 'PUT' : 'POST';
                
                const res = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                const data = await res.json();
                console.log('Save response:', data);
                
                if (data.success) {
                    showMessage(editingTradeId ? 'Trade updated!' : 'Trade added!', 'success');
                    clearForm();
                    
                    // Reload all data
                    await Promise.all([
                        loadSummary(),
                        loadTrades()
                    ]);
                } else {
                    showMessage('Failed to save trade: ' + (data.error || 'Unknown error'), 'error');
                }
            } catch (error) {
                console.error('Error saving trade:', error);
                showMessage('Failed to save trade: ' + error.message, 'error');
            } finally {
                const saveBtn = document.getElementById('saveTradeBtn');
                saveBtn.disabled = false;
                saveBtn.textContent = editingTradeId ? 'Update Trade' : 'Add Trade';
            }
        }

        // Edit trade
        function editTrade(id) {
            const trade = allTrades.find(t => t.id === id);
            if (!trade) {
                console.error('Trade not found:', id);
                return;
            }

            console.log('Editing trade:', trade);

            document.getElementById('ticker').value = trade.ticker;
            document.getElementById('buyPrice').value = trade.buy_price;
            document.getElementById('quantity').value = trade.quantity;
            document.getElementById('stopLoss').value = trade.stop_loss || '';
            document.getElementById('takeProfit').value = trade.take_profit || '';
            document.getElementById('timeframe').value = trade.timeframe;
            document.getElementById('tradeDate').value = trade.trade_date;
            document.getElementById('notes').value = trade.notes || '';

            calculateValues();

            editingTradeId = id;
            document.getElementById('formTitle').textContent = '✏️ Edit Trade';
            document.getElementById('saveTradeBtn').textContent = 'Update Trade';
            document.getElementById('cancelBtn').style.display = 'inline-block';
            
            // Scroll to form
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        // Delete trade
        async function deleteTrade(id) {
            if (!confirm('Delete this trade? This cannot be undone.')) return;

            try {
                const res = await fetch(`/api/trades/${id}`, { method: 'DELETE' });
                const data = await res.json();
                
                if (data.success) {
                    showMessage('Trade deleted', 'success');
                    await Promise.all([
                        loadSummary(),
                        loadTrades()
                    ]);
                } else {
                    showMessage('Failed to delete trade: ' + data.error, 'error');
                }
            } catch (error) {
                console.error('Error deleting trade:', error);
                showMessage('Failed to delete trade: ' + error.message, 'error');
            }
        }

        // Open close modal
        function openCloseModal(id) {
            closingTradeId = id;
            document.getElementById('closeModal').classList.add('active');
            document.getElementById('closeDate').value = new Date().toISOString().split('T')[0];
        }

        // Close modal
        function closeModal() {
            closingTradeId = null;
            document.getElementById('closeModal').classList.remove('active');
            document.getElementById('closePrice').value = '';
        }

        // Confirm close trade
        async function confirmCloseTrade() {
            const closePrice = parseFloat(document.getElementById('closePrice').value);
            const closeDate = document.getElementById('closeDate').value;

            if (isNaN(closePrice) || !closeDate) {
                showMessage('Please enter close price and date', 'error');
                return;
            }

            try {
                const res = await fetch(`/api/trades/${closingTradeId}/close`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ close_price: closePrice, close_date: closeDate })
                });
                
                const data = await res.json();
                if (data.success) {
                    showMessage('Trade closed successfully!', 'success');
                    closeModal();
                    await Promise.all([
                        loadSummary(),
                        loadTrades()
                    ]);
                } else {
                    showMessage('Failed to close trade: ' + data.error, 'error');
                }
            } catch (error) {
                console.error('Error closing trade:', error);
                showMessage('Failed to close trade: ' + error.message, 'error');
            }
        }

        // Clear form
        function clearForm() {
            document.getElementById('ticker').value = '';
            document.getElementById('buyPrice').value = '';
            document.getElementById('quantity').value = '';
            document.getElementById('stopLoss').value = '';
            document.getElementById('takeProfit').value = '';
            document.getElementById('timeframe').value = 'Long';
            document.getElementById('tradeDate').value = new Date().toISOString().split('T')[0];
            document.getElementById('notes').value = '';
            
            calculateValues();
            
            editingTradeId = null;
            document.getElementById('formTitle').textContent = '➕ Add New Trade';
            document.getElementById('saveTradeBtn').textContent = 'Add Trade';
            document.getElementById('cancelBtn').style.display = 'none';
        }

        // Show message
        function showMessage(text, type) {
            const msgEl = document.getElementById('message');
            msgEl.innerHTML = `<div class="message ${type}">${text}</div>`;
            setTimeout(() => msgEl.innerHTML = '', 5000);
        }

        // Logout
        async function logout() {
            await fetch('/api/logout');
            window.location.href = '/login';
        }
    </script>
</body>
</html>
    """
    return render_template_string(html)

@app.route('/api/portfolio', methods=['GET'])
@login_required
def get_portfolio():
    """Get user's portfolio cash"""
    try:
        cash = Portfolio.get_user_portfolio(current_user.id)
        return jsonify({'success': True, 'cash': float(cash)})
    except Exception as e:
        logger.error(f"Error getting portfolio for user {current_user.id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/portfolio', methods=['POST'])
@login_required
def update_portfolio():
    """Update user's portfolio cash"""
    try:
        data = request.json
        cash = float(data.get('cash', 0))
        
        if cash < 0:
            return jsonify({'success': False, 'error': 'Cash cannot be negative'}), 400
        
        Portfolio.set_user_portfolio(current_user.id, cash)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error updating portfolio for user {current_user.id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/portfolio/summary', methods=['GET'])
@login_required
def get_portfolio_summary():
    """Get comprehensive portfolio summary with all metrics"""
    try:
        portfolio_cash = float(Portfolio.get_user_portfolio(current_user.id))
        trades_raw = Trade.get_user_trades(current_user.id)
        
        # Convert to dict list
        trades = [dict(t) for t in trades_raw]
        
        # Calculate summary
        summary = portfolio_calculator.calculate_portfolio_summary(trades, portfolio_cash)
        
        # Get trading statistics
        stats = Trade.get_trade_statistics(current_user.id)
        
        return jsonify({
            'success': True,
            'portfolio_cash': portfolio_cash,
            'summary': summary,
            'statistics': stats
        })
    except Exception as e:
        logger.error(f"Error getting portfolio summary for user {current_user.id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/trades', methods=['GET'])
@login_required
def get_trades():
    """Get user's trades"""
    try:
        trades_raw = Trade.get_user_trades(current_user.id)
        
        trades = []
        for trade in trades_raw:
            trades.append({
                'id': trade['id'],
                'ticker': trade['ticker'],
                'buy_price': float(trade['buy_price']),
                'quantity': float(trade['quantity']),
                'position_size': float(trade['position_size']),
                'risk_amount': float(trade['risk_amount']),
                'timeframe': trade['timeframe'],
                'trade_date': trade['trade_date'].isoformat() if hasattr(trade['trade_date'], 'isoformat') else str(trade['trade_date'])
            })
        
        return jsonify({'success': True, 'trades': trades})
    except Exception as e:
        logger.error(f"Error getting trades for user {current_user.id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
        
@app.route('/api/trades/enriched', methods=['GET'])
@login_required
def get_enriched_trades():
    """Get trades with all calculated fields (risk %, R:R, P&L, warnings)"""
    try:
        portfolio_cash = float(Portfolio.get_user_portfolio(current_user.id))
        trades_raw = Trade.get_user_trades(current_user.id)
        
        enriched_trades = []
        
        for trade in trades_raw:
            # Get current price for open trades
            current_price = None
            if not trade.get('is_closed'):
                try:
                    current_price = price_checker.get_price(trade['ticker'])
                except Exception as e:
                    logger.warning(f"Could not fetch price for {trade['ticker']}: {e}")
            
            # Enrich trade with all calculations
            enriched = portfolio_calculator.enrich_trade_with_calculations(
                dict(trade), portfolio_cash, current_price
            )
            
            # Convert dates to strings
            if enriched.get('trade_date'):
                enriched['trade_date'] = enriched['trade_date'].isoformat() if hasattr(enriched['trade_date'], 'isoformat') else str(enriched['trade_date'])
            if enriched.get('close_date'):
                enriched['close_date'] = enriched['close_date'].isoformat() if hasattr(enriched['close_date'], 'isoformat') else str(enriched['close_date'])
            
            # Convert Decimal to float
            for key in enriched:
                if hasattr(enriched[key], '__float__'):
                    enriched[key] = float(enriched[key])
            
            enriched_trades.append(enriched)
        
        return jsonify({'success': True, 'trades': enriched_trades})
    except Exception as e:
        logger.error(f"Error getting enriched trades for user {current_user.id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/trades', methods=['POST'])
@login_required
def create_trade():
    """
    Create a new trade with automatic calculations
    Position Size = buy_price * quantity
    Risk Amount = |buy_price - stop_loss| * quantity
    """
    try:
        data = request.json
        
        # Get required fields
        ticker = data['ticker'].upper()
        buy_price = float(data['buy_price'])
        quantity = float(data['quantity'])
        timeframe = data['timeframe']
        trade_date = data['trade_date']
        
        # Get optional fields
        stop_loss = float(data['stop_loss']) if data.get('stop_loss') else None
        take_profit = float(data['take_profit']) if data.get('take_profit') else None
        notes = (data.get('notes') or '').strip() or None
        
        # AUTOMATIC CALCULATIONS
        # Position Size = buy_price * quantity
        position_size = buy_price * quantity
        
        # Risk Amount = |buy_price - stop_loss| * quantity (if stop_loss provided)
        if stop_loss is not None:
            risk_amount = abs(buy_price - stop_loss) * quantity
        else:
            # Default risk if no stop loss (e.g., 2% of position)
            risk_amount = position_size * 0.02
        
        logger.info(f"Creating trade for user {current_user.id}: {ticker} - Position: ${position_size:.2f}, Risk: ${risk_amount:.2f}")
        
        trade_id = Trade.create_trade(
            current_user.id,
            ticker,
            buy_price,
            quantity,
            position_size,
            risk_amount,
            timeframe,
            trade_date,
            stop_loss,
            take_profit,
            notes
        )
        
        logger.info(f"Trade created successfully with ID: {trade_id}")
        return jsonify({'success': True, 'id': trade_id})
    except KeyError as e:
        logger.error(f"Missing required field: {e}")
        return jsonify({'success': False, 'error': f'Missing required field: {e}'}), 400
    except Exception as e:
        logger.error(f"Error creating trade for user {current_user.id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/trades/<int:trade_id>', methods=['PUT'])
@login_required
def update_trade_route(trade_id):
    """
    Update a trade with automatic calculations
    Position Size = buy_price * quantity
    Risk Amount = |buy_price - stop_loss| * quantity
    """
    try:
        data = request.json
        
        # Get required fields
        ticker = data['ticker'].upper()
        buy_price = float(data['buy_price'])
        quantity = float(data['quantity'])
        timeframe = data['timeframe']
        trade_date = data['trade_date']
        
        # Get optional fields
        stop_loss = float(data['stop_loss']) if data.get('stop_loss') else None
        take_profit = float(data['take_profit']) if data.get('take_profit') else None
        notes = data.get('notes', '').strip() or None
        
        # AUTOMATIC CALCULATIONS
        # Position Size = buy_price * quantity
        position_size = buy_price * quantity
        
        # Risk Amount = |buy_price - stop_loss| * quantity (if stop_loss provided)
        if stop_loss is not None:
            risk_amount = abs(buy_price - stop_loss) * quantity
        else:
            # Default risk if no stop loss
            risk_amount = position_size * 0.02
        
        Trade.update_trade(
            trade_id,
            current_user.id,
            ticker,
            buy_price,
            quantity,
            position_size,
            risk_amount,
            timeframe,
            trade_date,
            stop_loss,
            take_profit,
            notes
        )
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error updating trade {trade_id} for user {current_user.id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/trades/<int:trade_id>', methods=['DELETE'])
@login_required
def delete_trade_route(trade_id):
    """Delete a trade"""
    try:
        Trade.delete_trade(trade_id, current_user.id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error deleting trade {trade_id} for user {current_user.id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/trades/<int:trade_id>/close', methods=['POST'])
@login_required
def close_trade_route(trade_id):
    """Close a trade and record realized P&L"""
    try:
        data = request.json
        close_price = float(data['close_price'])
        close_date = data['close_date']
        
        Trade.close_trade(trade_id, current_user.id, close_price, close_date)
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error closing trade {trade_id} for user {current_user.id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/trades/<int:trade_id>/reopen', methods=['POST'])
@login_required
def reopen_trade_route(trade_id):
    """Reopen a closed trade"""
    try:
        Trade.reopen_trade(trade_id, current_user.id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error reopening trade {trade_id} for user {current_user.id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
@app.route('/api/trades/<int:trade_id>/current-price', methods=['GET'])
@login_required
def get_trade_current_price(trade_id):
    """Get current market price for a trade's ticker"""
    try:
        # Get trade to find ticker
        trades = Trade.get_user_trades(current_user.id)
        trade = next((t for t in trades if t['id'] == trade_id), None)
        
        if not trade:
            return jsonify({'success': False, 'error': 'Trade not found'}), 404
        
        current_price = price_checker.get_price(trade['ticker'])
        
        if current_price is None:
            return jsonify({'success': False, 'error': 'Could not fetch price'}), 500
        
        return jsonify({'success': True, 'price': current_price})
    except Exception as e:
        logger.error(f"Error fetching current price for trade {trade_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
        
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
