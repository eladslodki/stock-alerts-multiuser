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
import json

# Configure logging
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'DEBUG')),
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

# ── Fundamentals Reports feature ──────────────────────────────────────────────
try:
    from fundamentals_db import init_db as _init_fundamentals_db
    from fundamentals_routes import fundamentals_bp
    app.register_blueprint(fundamentals_bp)
    _init_fundamentals_db()
    logger.info("Fundamentals Reports feature loaded.")
except Exception as _fn_err:
    logger.warning("Fundamentals Reports feature could not be loaded: %s", _fn_err)
# ─────────────────────────────────────────────────────────────────────────────

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
    <html lang="en">
    <head>
        <title>Sign In — Stock Alerts</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="/static/css/theme.css">
        <style>
            /* page-specific overrides */
            .auth-screen { background: none; }
        </style>
    </head>
    <body>
        <div class="auth-screen">
            <div class="auth-card">
                <div class="auth-logo">📈</div>
                <h1 class="auth-title">Welcome back</h1>
                <p class="auth-subtitle">Sign in to your trading dashboard</p>

                <div class="form-group">
                    <label class="form-label">Email</label>
                    <input type="email" id="email" placeholder="you@example.com" autocomplete="email" />
                </div>
                <div class="form-group">
                    <label class="form-label">Password</label>
                    <input type="password" id="password" placeholder="••••••••" autocomplete="current-password" />
                </div>

                <div id="message"></div>

                <button class="btn btn-primary" onclick="login()" style="margin-top: 12px;">
                    Sign In
                </button>

                <div class="auth-footer">
                    No account? <a href="/register">Create one</a>
                </div>
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
                    msgEl.innerHTML = '<div class="message message-error">' + (data.error || 'Login failed') + '</div>';
                }
            }
            document.addEventListener('keydown', e => { if (e.key === 'Enter') login(); });
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/register')  
def register_page():
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>Create Account — Stock Alerts</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="/static/css/theme.css">
        <style>
        </style>
    </head>
    <body>
        <div class="auth-screen">
            <div class="auth-card">
                <div class="auth-logo">📈</div>
                <h1 class="auth-title">Create account</h1>
                <p class="auth-subtitle">Start tracking your trades today</p>

                <div class="form-group">
                    <label class="form-label">Email</label>
                    <input type="email" id="email" placeholder="you@example.com" autocomplete="email" />
                </div>
                <div class="form-group">
                    <label class="form-label">Password</label>
                    <input type="password" id="password" placeholder="Min 6 characters" autocomplete="new-password" />
                </div>

                <div id="message"></div>

                <button class="btn btn-primary" onclick="register()" style="margin-top: 12px;">
                    Create Account
                </button>

                <div class="auth-footer">
                    Already have an account? <a href="/login">Sign in</a>
                </div>
            </div>
        </div>
        <script>
            async function register() {
                const email = document.getElementById('email').value;
                const password = document.getElementById('password').value;
                const msgEl = document.getElementById('message');
                if (password.length < 6) {
                    msgEl.innerHTML = '<div class="message message-error">Password must be at least 6 characters</div>';
                    return;
                }
                const res = await fetch('/api/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password })
                });
                const data = await res.json();
                if (data.success) {
                    msgEl.innerHTML = '<div class="message message-success">Account created! Redirecting to login...</div>';
                    setTimeout(() => window.location.href = '/login', 2000);
                } else {
                    msgEl.innerHTML = '<div class="message message-error">' + (data.error || 'Registration failed') + '</div>';
                }
            }
            document.addEventListener('keydown', e => { if (e.key === 'Enter') register(); });
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
<html lang="en">
<head>
    <title>Dashboard — PulseAlerts</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="/static/css/theme.css">
    <style>
        body { padding: 0; }
        .page-wrapper { padding-top: 0; }
        .dash-layout {
            display: grid;
            grid-template-columns: 380px 1fr;
            gap: 24px;
            align-items: start;
        }
        @media (max-width: 960px) { .dash-layout { grid-template-columns: 1fr; } }
        @media (max-width: 768px) {
            .dash-layout { gap: var(--sp-3); }
        }

        /* Alert price grid (JS-generated) */
        .alert-price-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
            margin-bottom: 12px;
        }
        @media (max-width: 360px) {
            .alert-price-grid { grid-template-columns: 1fr; }
        }

        /* Alert card rendered by JS */
        .alert-card {
            background: rgba(255,255,255,0.045);
            border: 1px solid rgba(255,255,255,0.07);
            border-radius: 16px;
            padding: 18px 18px 18px 22px;
            margin-bottom: 10px;
            position: relative; overflow: hidden;
            transition: border-color 0.15s, box-shadow 0.15s;
        }
        .alert-card::before {
            content: ''; position: absolute; top: 0; left: 0;
            width: 3px; height: 100%;
            background: linear-gradient(180deg, #5B7CFF 0%, #7B5CFF 100%);
        }
        .alert-card.ma-alert::before { background: linear-gradient(180deg, #00D9FF 0%, #0099FF 100%); }
        .alert-card:hover { border-color: rgba(255,255,255,0.12); box-shadow: 0 4px 20px rgba(0,0,0,0.3); }

        /* Alert type toggle */
        .alert-type-toggle { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 4px; margin-bottom: 20px; }
        .toggle-option { height: 40px; border-radius: 8px; background: transparent; border: none; color: #8B92A8; font-size: 13px; font-weight: 600; transition: all 0.15s; margin: 0; width: auto; cursor: pointer; font-family: inherit; }
        .toggle-option.active { background: #5B7CFF; color: #fff; box-shadow: 0 2px 10px rgba(91,124,255,0.3); }

        /* Status indicators (JS-generated) */
        .status-indicator { font-size: 12px; font-weight: 600; padding: 5px 10px; border-radius: 8px; display: inline-flex; align-items: center; gap: 4px; }
        .status-indicator.above { background: rgba(0,208,132,0.1); color: #00D084; border: 1px solid rgba(0,208,132,0.2); }
        .status-indicator.below { background: rgba(255,71,87,0.1); color: #FF4757; border: 1px solid rgba(255,71,87,0.2); }
        .status-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; box-shadow: 0 0 6px currentColor; flex-shrink: 0; }

        /* Badges (JS-generated) */
        .status-badge { font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 99px; letter-spacing: 0.3px; }
        .status-badge.price { background: rgba(91,124,255,0.15); color: #5B7CFF; border: 1px solid rgba(91,124,255,0.25); }
        .status-badge.ma    { background: rgba(0,217,255,0.12); color: #00D9FF; border: 1px solid rgba(0,217,255,0.2); }

        /* Delete button (JS-generated) */
        .delete-btn { padding: 8px 16px; background: rgba(255,71,87,0.1); border: 1px solid rgba(255,71,87,0.2); color: #FF4757; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; font-family: inherit; transition: background 0.15s; width: auto; margin: 0; }
        .delete-btn:hover { background: rgba(255,71,87,0.18); }

        /* NL Preview block */
        .nl-preview {
            background: rgba(91,124,255,0.07);
            border: 1px solid rgba(91,124,255,0.2);
            border-radius: 12px;
            padding: 16px;
            margin-top: 14px;
        }
        .nl-preview-label { font-size: 11px; font-weight: 700; color: var(--accent); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
    </style>
</head>
<body>
    <nav class="top-nav">
        <span class="top-nav-brand">📈 PulseAlerts</span>
        <a href="/dashboard" class="top-nav-link active">📊 Alerts</a>
        <a href="/portfolio" class="top-nav-link">💼 Portfolio</a>
        <a href="/alerts/history" class="top-nav-link">📜 History</a>
        <a href="/radar" class="top-nav-link">🚨 Radar</a>
        <a href="/bitcoin-scanner" class="top-nav-link">₿ Bitcoin</a>
        <a href="/forex-sessions" class="top-nav-link">🌐 Forex</a>
        <a href="/fundamentals" class="top-nav-link">📋 Fundamentals</a>
        <span class="top-nav-spacer"></span>
        <button class="top-nav-logout" onclick="logout()">Sign out</button>
    </nav>

    <div class="page-wrapper">
        <div class="page-header">
            <div class="page-header-left">
                <div class="page-eyebrow">Dashboard</div>
                <h1 class="page-title">Stock Alerts</h1>
                <p class="page-subtitle">Monitor price targets and moving average crossovers</p>
            </div>
        </div>

        <div class="dash-layout">
            <!-- Left column: Create Alert + NL Alert -->
            <div>
                <!-- Create Alert Card -->
                <div class="card">
                    <div class="card-header">
                        <div>
                            <div class="card-title">Create Alert</div>
                            <div class="card-subtitle">Price target or MA crossover</div>
                        </div>
                    </div>

                    <div class="alert-type-toggle">
                        <button id="priceTypeBtn" class="toggle-option active" onclick="switchAlertType('price')">Price Alert</button>
                        <button id="maTypeBtn" class="toggle-option" onclick="switchAlertType('ma')">MA Alert</button>
                    </div>

                    <div class="autocomplete-container">
                        <label class="form-label">Ticker Symbol</label>
                        <input type="text" id="tickerInput" placeholder="Search (e.g. AAPL, BTC-USD)" autocomplete="off" />
                        <div id="autocompleteDropdown" class="autocomplete-dropdown"></div>
                    </div>

                    <div id="priceAlertFields">
                        <div class="form-group">
                            <label class="form-label">Target Price</label>
                            <input type="number" id="targetPrice" placeholder="0.00" step="0.01" />
                        </div>
                        <p class="info-text">Alert triggers when price crosses the target in either direction.</p>
                    </div>

                    <div id="maAlertFields" style="display:none;">
                        <div class="form-group">
                            <label class="form-label">Moving Average Period</label>
                            <div class="ma-selector">
                                <div class="ma-option active" onclick="selectMA(20)">
                                    <div class="ma-label">MA 20</div>
                                    <div class="ma-sublabel">Short</div>
                                </div>
                                <div class="ma-option" onclick="selectMA(50)">
                                    <div class="ma-label">MA 50</div>
                                    <div class="ma-sublabel">Medium</div>
                                </div>
                                <div class="ma-option" onclick="selectMA(150)">
                                    <div class="ma-label">MA 150</div>
                                    <div class="ma-sublabel">Long</div>
                                </div>
                            </div>
                            <input type="hidden" id="maPeriod" value="20" />
                        </div>
                        <p class="info-text">Alert triggers when price crosses the moving average.</p>
                    </div>

                    <button class="btn btn-primary" onclick="createAlert()" id="createBtn" style="margin-top:16px;">
                        Create Alert
                    </button>
                    <div id="message"></div>
                </div>

                <!-- NL Alert Card -->
                <div class="card">
                    <div class="card-header">
                        <div>
                            <div class="card-title">✨ Create from Text</div>
                            <div class="card-subtitle">Describe your alert in plain English</div>
                        </div>
                    </div>
                    <div class="form-group">
                        <input type="text" id="nlAlertInput" placeholder='e.g. "Alert me when TSLA breaks 200"' />
                    </div>
                    <button class="btn btn-secondary btn-sm" onclick="parseNLAlert()" id="parseBtn">Parse Alert</button>

                    <div id="nlPreview" style="display:none;" class="nl-preview">
                        <div class="nl-preview-label">Preview</div>
                        <div id="nlSummary" style="margin-bottom:14px;font-size:14px;line-height:1.6;"></div>
                        <div style="display:flex;gap:8px;">
                            <button class="btn btn-primary btn-sm" onclick="confirmNLAlert()" id="confirmBtn" style="width:auto;flex:1;">Confirm & Create</button>
                            <button class="btn btn-secondary btn-sm" onclick="cancelNLAlert()">Cancel</button>
                        </div>
                    </div>
                    <div id="nlMessage"></div>
                </div>
            </div>

            <!-- Right column: Active Alerts -->
            <div>
                <div class="card">
                    <div class="card-header">
                        <div class="card-title">Active Alerts</div>
                        <span id="alertCount" class="badge badge-muted" style="display:none;"></span>
                    </div>
                    <div id="alertsList">
                        <div class="loading">Loading alerts...</div>
                    </div>
                </div>
            </div>
        </div>
    </div><!-- /.page-wrapper -->
    
    <script>
        let allTickers = [];
        let selectedTicker = null;

            // NEW: Toggle between price and MA alert fields
       function toggleAlertFields() {
            const priceFields = document.getElementById('priceAlertFields');
            const maFields = document.getElementById('maAlertFields');
            
            // Check which button is active
            const isPriceActive = document.getElementById('priceTypeBtn').classList.contains('active');
            
            if (isPriceActive) {
                priceFields.style.display = 'block';
                maFields.style.display = 'none';
            } else {
                priceFields.style.display = 'none';
                maFields.style.display = 'block';
            }
        }
        
        // Load tickers on page load
        async function loadTickers() {
            try {
              console.log('Loading tickers...');
              const res = await fetch('/api/tickers');
              const data = await res.json();
        
        if (data.success) {
            allTickers = data.tickers.slice().sort((a, b) =>
                a.symbol.localeCompare(b.symbol, undefined, {sensitivity: 'base'})
            );
            console.log(`✅ Loaded ${allTickers.length} tickers`);
        } else {
            console.error('❌ Failed to load tickers:', data);
        }
    } catch (error) {
        console.error('❌ Error loading tickers:', error);
        // Fallback: add some basic tickers so autocomplete still works
        allTickers = [
            {symbol: 'AAPL',    name: 'Apple Inc.',             type: 'Stock'},
            {symbol: 'BTC-USD', name: 'Bitcoin USD',            type: 'Crypto'},
            {symbol: 'MSFT',    name: 'Microsoft Corporation',  type: 'Stock'},
            {symbol: 'TSLA',    name: 'Tesla Inc.',             type: 'Stock'}
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
    
    const matches = allTickers
        .filter(t =>
            t.symbol.toUpperCase().includes(query) ||
            t.name.toUpperCase().includes(query)
        )
        .sort((a, b) => a.symbol.localeCompare(b.symbol, undefined, {sensitivity: 'base'}))
        .slice(0, 10);
    
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
        const alertType = document.getElementById('priceTypeBtn').classList.contains('active') ? 'price' : 'ma';
        const msgEl = document.getElementById('message');
        const btn = document.getElementById('createBtn');
    
        if (!ticker) {
            msgEl.innerHTML = '<div class="message error">Please select a ticker</div>';
            return;
        }
    
    // Build payload based on alert type
        let payload = { ticker, alert_type: alertType };
    
        if (alertType === 'ma') {
            const maPeriod = parseInt(document.getElementById('maPeriod').value);
    
            payload.ma_period = maPeriod;
            payload.direction = 'up';  // MA alerts always trigger when price > MA
            payload.target_price = 0;  // Will be set by backend to current MA value
        } else {
        const target = parseFloat(document.getElementById('targetPrice').value);
        
        if (!target) {
            msgEl.innerHTML = '<div class="message error">Please enter a target price</div>';
            return;
        }
        
        payload.target_price = target;
        payload.direction = 'both';  // Trigger on crossing either direction
    }
    
        btn.disabled = true;
        btn.textContent = 'Creating...';
    
        try {
            const res = await fetch('/api/alerts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
                
                const data = await res.json();
                
                if (data.success) {
                    msgEl.innerHTML = '<div class="message success">✓ Alert created successfully!</div>';
                    tickerInput.value = '';
                    document.getElementById('targetPrice').value = '';
                    switchAlertType('price');  // Reset to price view
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
        console.log('🔄 Loading alerts...');  // ADD THIS
        // Add timestamp to prevent caching
        const timestamp = new Date().getTime();
        const res = await fetch(`/api/alerts?t=${timestamp}`);
        console.log('Response status:', res.status);  // ADD THIS
        const data = await res.json();
        console.log('Alerts data:', data);  // ADD THIS
        
        console.log(`📊 [${new Date().toLocaleTimeString()}] Alerts loaded:`, data);
        
        if (!data.success) {
            alertsEl.innerHTML = '<div class="error">Failed to load alerts</div>';
            return;
        }
        
        const active = data.alerts
            .filter(a => a.active)
            .sort((a, b) => a.ticker.localeCompare(b.ticker, undefined, {sensitivity: 'base'}));
        
        if (active.length === 0) {
            alertsEl.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">🎯</div>
                    <div class="empty-state-title">No Active Alerts</div>
                    <div class="empty-state-text">Create an alert to get notified when a price target is hit.</div>
                </div>`;
            const countBadge = document.getElementById('alertCount');
            if (countBadge) countBadge.style.display = 'none';
            return;
        }

        const countBadge = document.getElementById('alertCount');
        if (countBadge) { countBadge.textContent = active.length; countBadge.style.display = 'inline-flex'; }

        alertsEl.innerHTML = active.map(alert => {
        const current = alert.current_price || 0;
        const target = alert.target_price || 0;
        const alertType = alert.alert_type || 'price';
        const maPeriod = alert.ma_period;

        const isAbove = current >= target;
        const diff = Math.abs(current - target);
        const pct = target > 0 ? ((diff / target) * 100).toFixed(1) : '0.0';

        const accentClass = alertType === 'ma' ? 'ma-alert' : '';
        const badgeLabel = alertType === 'ma' ? `MA ${maPeriod}` : 'PRICE';
        const badgeClass = alertType === 'ma' ? 'ma' : 'price';
        const targetLabel = alertType === 'ma' ? `MA${maPeriod}` : 'Target';

        return `
            <div class="alert-card ${accentClass}">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span style="font-size:18px;font-weight:800;letter-spacing:-0.3px;">${alert.ticker}</span>
                        <span class="status-badge ${badgeClass}">${badgeLabel}</span>
                    </div>
                    <div class="status-indicator ${isAbove ? 'above' : 'below'}">
                        <span class="status-dot"></span>
                        ${isAbove ? 'Above' : 'Below'}
                    </div>
                </div>
                <div class="alert-price-grid">
                    <div>
                        <div class="item-field-label">Current Price</div>
                        <div class="item-field-value" style="font-size:18px;">$${current.toFixed(2)}</div>
                    </div>
                    <div>
                        <div class="item-field-label">${targetLabel}</div>
                        <div class="item-field-value accent" style="font-size:18px;">$${target.toFixed(2)}</div>
                    </div>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:12px;color:var(--text-muted);">${pct}% from ${targetLabel.toLowerCase()}</span>
                    <button class="delete-btn" onclick="deleteAlert(${alert.id})">Delete</button>
                </div>
            </div>`;
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
        setInterval(loadAlerts, 10000); // Refresh every 10 seconds
        // Premium UI Functions
        function switchAlertType(type) {
        document.querySelectorAll('.toggle-option').forEach(btn => {
            btn.classList.remove('active');
        });
        
        if (type === 'price') {
            document.getElementById('priceTypeBtn').classList.add('active');
        } else {
            document.getElementById('maTypeBtn').classList.add('active');
        }
        
        toggleAlertFields();
    }
    
    function selectMA(period) {
        // Remove active from all
        document.querySelectorAll('.ma-option').forEach(opt => {
            opt.classList.remove('active');
        });
        
        // Add active to clicked
        event.target.closest('.ma-option').classList.add('active');
        
        // Update hidden input
        document.getElementById('maPeriod').value = period;
    }
    // Natural Language Alert Functions
let nlSuggestion = null;

async function parseNLAlert() {
    const text = document.getElementById('nlAlertInput').value.trim();
    const msgEl = document.getElementById('nlMessage');
    const parseBtn = document.getElementById('parseBtn');
    
    if (!text) {
        msgEl.innerHTML = '<div class="message error">Please enter some text</div>';
        return;
    }
    
    parseBtn.disabled = true;
    parseBtn.textContent = 'Parsing...';
    msgEl.innerHTML = '';
    
    try {
        const res = await fetch('/api/alerts/parse-text', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text })
        });
        
        const data = await res.json();
        
        if (data.success) {
    nlSuggestion = data.suggestion;
    
    // Show confidence level
    const confidence = (nlSuggestion.confidence * 100).toFixed(0);
    const confidenceColor = confidence >= 80 ? '#00FFA3' : confidence >= 50 ? '#FFB800' : '#FF6B6B';
    
    // Build enhanced preview with interpretation
    document.getElementById('nlSummary').innerHTML = `
        <div style="margin-bottom: 8px; font-size: 15px; font-weight: 600;">
            ${nlSuggestion.summary}
        </div>
        ${nlSuggestion.interpretation ? `
        <div style="font-size: 13px; color: #8B92A8; margin-bottom: 8px;">
            📝 ${nlSuggestion.interpretation}
        </div>
        ` : ''}
        <div style="margin-top: 8px; font-size: 11px; color: ${confidenceColor};">
            ✓ Confidence: ${confidence}%
        </div>
    `;
    
    document.getElementById('nlPreview').style.display = 'block';
    msgEl.innerHTML = '';
    } else {
            msgEl.innerHTML = `<div class="message error">${data.error}</div>`;
        }
    } catch (error) {
        console.error('Parse error:', error);
        msgEl.innerHTML = '<div class="message error">Failed to parse alert</div>';
    } finally {
        parseBtn.disabled = false;
        parseBtn.textContent = 'Parse Alert';
    }
}

async function confirmNLAlert() {
    if (!nlSuggestion) return;
    
    const confirmBtn = document.getElementById('confirmBtn');
    const msgEl = document.getElementById('nlMessage');
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Creating...';
    
    try {
        const res = await fetch('/api/alerts/create-from-suggestion', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(nlSuggestion)
        });
        
        const data = await res.json();
        
        if (data.success) {
            msgEl.innerHTML = '<div class="message success">✓ Alert created successfully!</div>';
            document.getElementById('nlAlertInput').value = '';
            cancelNLAlert();
            loadAlerts();  // Refresh alert list
        } else {
            msgEl.innerHTML = `<div class="message error">${data.error}</div>`;
        }
    } catch (error) {
        console.error('Create error:', error);
        msgEl.innerHTML = '<div class="message error">Failed to create alert</div>';
    } finally {
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Confirm & Create';
    }
}

function cancelNLAlert() {
    document.getElementById('nlPreview').style.display = 'none';
    document.getElementById('nlMessage').innerHTML = '';
    nlSuggestion = null;
}

    </script>
    <script src="/static/js/nav-mobile.js"></script>
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
                'triggered_price': float(alert['triggered_price']) if alert.get('triggered_price') else None,
                'alert_type': alert.get('alert_type', 'price'),
                'ma_period': alert.get('ma_period'),
                'ma_value': float(alert['ma_value']) if alert.get('ma_value') else None
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
    target_price = float(data.get('target_price', 0))
    
    # NEW: Get alert type and MA period
    alert_type = data.get('alert_type', 'price')
    ma_period = data.get('ma_period')
    direction = data.get('direction', 'up')
    
    if not ticker:
        return jsonify({'success': False, 'error': 'Ticker required'}), 400
    
    # Validate alert type
    if alert_type not in ['price', 'ma']:
        return jsonify({'success': False, 'error': 'Invalid alert type'}), 400
    
    # Validate MA period if MA alert
    if alert_type == 'ma' and ma_period not in [20, 50, 150]:
        return jsonify({'success': False, 'error': 'Invalid MA period'}), 400
    
    # Get current price
    current_price = price_checker.get_price(ticker)
    if current_price is None:
        return jsonify({'success': False, 'error': 'Invalid ticker or unable to fetch price'}), 400
    
    # For MA alerts, calculate and set target_price to current MA value
    if alert_type == 'ma':
        ma_value = price_checker.get_moving_average(ticker, ma_period)  # FIXED: Use price_checker.
        if ma_value is None:
            return jsonify({'success': False, 'error': f'Could not calculate MA{ma_period} for {ticker}'}), 400
        target_price = ma_value
        direction = 'up'  # MA alerts trigger when crossing in either direction
        logger.info(f"MA alert created: {ticker} MA{ma_period} = ${ma_value:.2f}")
    else:
        # Validate target price for price alerts
        if target_price <= 0:
            return jsonify({'success': False, 'error': 'Invalid target price'}), 400
            
    # Determine direction based on current price vs target
    if direction == 'both':
        # Alert triggers on crossing - set direction based on current position
        direction = 'up' if current_price < target_price else 'down'
        
    # Create alert
    alert_id = Alert.create(current_user.id, ticker, target_price, current_price, direction, alert_type, ma_period)
    
    return jsonify({
        'success': True,
        'alert': {
            'id': alert_id,
            'ticker': ticker,
            'target_price': target_price,
            'current_price': current_price,
            'direction': direction,
            'alert_type': alert_type,
            'ma_period': ma_period
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
    <html lang="en">
    <head>
        <title>Bitcoin Scanner — PulseAlerts</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="/static/css/theme.css">
        <style>
            body { padding: 0; }
            .hash { font-family: monospace; color: var(--accent-cyan); font-size: 12px; text-decoration: none; }
            .hash:hover { text-decoration: underline; }
            .col-btc  { font-weight: 700; color: var(--warning); }
            .col-addr { font-family: monospace; font-size: 11px; color: var(--text-muted); }
            .scan-note { background: rgba(255,184,0,0.07); border-left: 3px solid var(--warning); border-radius: var(--r-md); padding: 12px 14px; font-size: 13px; color: var(--text-secondary); margin-top: 16px; }
        </style>
    </head>
    <body>
        <nav class="top-nav">
            <span class="top-nav-brand">📈 PulseAlerts</span>
            <a href="/dashboard" class="top-nav-link">📊 Alerts</a>
            <a href="/portfolio" class="top-nav-link">💼 Portfolio</a>
            <a href="/alerts/history" class="top-nav-link">📜 History</a>
            <a href="/radar" class="top-nav-link">🚨 Radar</a>
            <a href="/bitcoin-scanner" class="top-nav-link active">₿ Bitcoin</a>
            <a href="/forex-sessions" class="top-nav-link">🌐 Forex</a>
            <a href="/fundamentals" class="top-nav-link">📋 Fundamentals</a>
            <span class="top-nav-spacer"></span>
            <button class="top-nav-logout" onclick="logout()">Sign out</button>
        </nav>
        <div class="page-wrapper medium">
            <div class="page-header">
                <div class="page-header-left">
                    <div class="page-eyebrow">Blockchain</div>
                    <h1 class="page-title">₿ Bitcoin Scanner</h1>
                    <p class="page-subtitle">Scan blockchain for large transaction activity</p>
                </div>
            </div>

            <!-- Scan controls -->
            <div class="card">
                <div class="card-header">
                    <div class="card-title">Scan Parameters</div>
                </div>
                <div class="form-row">
                    <div class="form-group" style="margin-bottom:0;">
                        <label class="form-label">Minimum Amount (BTC)</label>
                        <input type="number" id="minAmount" value="10" step="0.1" min="0.1">
                    </div>
                    <div class="form-group" style="margin-bottom:0;">
                        <label class="form-label">Time Period</label>
                        <select id="timeRange">
                            <option value="24">Last 24 Hours</option>
                            <option value="168">Last 7 Days</option>
                            <option value="720">Last 30 Days</option>
                            <option value="4320">Last 6 Months</option>
                        </select>
                    </div>
                </div>
                <button class="btn btn-primary" onclick="scanTransactions()" id="scanBtn" style="margin-top:16px;">
                    Scan Blockchain
                </button>
                <div class="scan-note">
                    ⚠️ Uses Blockchain.info free API — shows recent unconfirmed and latest confirmed transactions.
                    Full historical scanning requires a paid API or self-hosted Bitcoin node.
                </div>
            </div>

            <!-- Stats + Results -->
            <div class="card" id="resultsCard" style="display:none;">
                <div id="statsGrid" class="stat-grid stat-grid-3" style="margin-bottom:20px;display:none;">
                    <div class="stat-card">
                        <div class="stat-label">Transactions</div>
                        <div class="stat-value accent" id="txCount">—</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Total BTC Volume</div>
                        <div class="stat-value warning" id="totalBTC">—</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Total USD Value</div>
                        <div class="stat-value" id="totalUSD">—</div>
                    </div>
                </div>
                <div id="results"></div>
            </div>
        </div>

        <script>
            async function scanTransactions() {
                const minAmount = parseFloat(document.getElementById('minAmount').value);
                const timeRange = document.getElementById('timeRange').value;
                const resultsEl = document.getElementById('results');
                const scanBtn = document.getElementById('scanBtn');
                const resultsCard = document.getElementById('resultsCard');

                scanBtn.disabled = true;
                scanBtn.textContent = 'Scanning...';
                resultsCard.style.display = 'block';
                resultsEl.innerHTML = '<div class="loading">Scanning Bitcoin blockchain...</div>';
                document.getElementById('statsGrid').style.display = 'none';

                try {
                    const res = await fetch('/api/bitcoin/scan', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ min_amount: minAmount, timeframe: timeRange })
                    });
                    const data = await res.json();

                    if (!data.success) {
                        resultsEl.innerHTML = `<div class="empty">Scan failed: ${data.error || 'Unknown error'}</div>`;
                    } else if (data.transactions.length === 0) {
                        resultsEl.innerHTML = `
                            <div class="empty-state">
                                <div class="empty-state-icon">₿</div>
                                <div class="empty-state-title">No Transactions Found</div>
                                <div class="empty-state-text">Try lowering the minimum BTC amount or extending the time range.</div>
                            </div>`;
                    } else {
                        displayResults(data.transactions);
                    }
                } catch (error) {
                    resultsEl.innerHTML = '<div class="empty">Error scanning blockchain. Please try again.</div>';
                } finally {
                    scanBtn.disabled = false;
                    scanBtn.textContent = 'Scan Blockchain';
                }
            }

            function displayResults(txs) {
                const totalBTC = txs.reduce((s, t) => s + t.amount_btc, 0);
                const totalUSD = txs.reduce((s, t) => s + t.amount_usd, 0);
                document.getElementById('txCount').textContent = txs.length;
                document.getElementById('totalBTC').textContent = totalBTC.toFixed(2) + ' BTC';
                document.getElementById('totalUSD').textContent = '$' + Math.round(totalUSD).toLocaleString();
                document.getElementById('statsGrid').style.display = 'grid';

                let html = `<div class="table-wrap"><table class="data-table">
                    <thead><tr>
                        <th>Transaction</th><th>Time</th><th>Amount</th><th>Inputs</th><th>Outputs</th>
                    </tr></thead><tbody>`;

                txs.forEach(tx => {
                    const time = new Date(tx.time).toLocaleString('en-US', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' });
                    const from = tx.from_addresses.slice(0, 1).join('') || '—';
                    const to   = tx.to_addresses.slice(0, 1).join('') || '—';
                    html += `<tr>
                        <td><a href="https://blockchain.info/tx/${tx.hash}" target="_blank" class="hash">${tx.hash.substring(0,14)}…</a></td>
                        <td class="col-muted">${time}</td>
                        <td><span class="col-btc">${tx.amount_btc.toFixed(4)} BTC</span><br><span style="font-size:11px;color:var(--text-muted);">$${Math.round(tx.amount_usd).toLocaleString()}</span></td>
                        <td class="col-addr">${from.substring(0,12)}…${tx.num_inputs > 1 ? ' +' + (tx.num_inputs-1) : ''}</td>
                        <td class="col-addr">${to.substring(0,12)}…${tx.num_outputs > 1 ? ' +' + (tx.num_outputs-1) : ''}</td>
                    </tr>`;
                });
                html += '</tbody></table></div>';
                document.getElementById('results').innerHTML = html;
            }

            async function logout() {
                await fetch('/api/logout');
                window.location.href = '/login';
            }
        </script>
        <script src="/static/js/nav-mobile.js"></script>
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

        timeframe = data.get('timeframe', '24h')

        if timeframe == '7d':
            time_range = 24 * 7
        elif timeframe == '30d':
            time_range = 24 * 30
        elif timeframe == '180d':
            time_range = 24 * 180
        else:
            time_range = 24

        logger.info(
            f"Scanning for transactions > {min_amount} BTC in last {time_range} hours"
        )

        transactions = bitcoin_scanner.scan_large_transactions(
            min_amount, time_range
        )

        return jsonify({
            'success': True,
            'transactions': transactions,
            'count': len(transactions)
        })

    except Exception as e:
        logger.error(f"Error scanning Bitcoin transactions: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'transactions': []
        }), 500
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
<html lang="en">
<head>
    <title>Portfolio — Stock Alerts</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
    <link rel="stylesheet" href="/static/css/theme.css">
    <style>
        /* Portfolio page — minimal overrides on top of theme.css */
        .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--sp-4); margin-bottom: var(--sp-5); }
        .summary-item { background: var(--bg-surface); border: 1px solid var(--border-card); border-radius: var(--r-md); padding: var(--sp-4); }
        .summary-label { font-size: 11px; color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
        .summary-value { font-size: 24px; font-weight: 800; font-variant-numeric: tabular-nums; letter-spacing: -0.5px; color: var(--accent); }
        .summary-value.positive { color: var(--positive); }
        .summary-value.negative { color: var(--negative); }
        .summary-value.neutral  { color: var(--warning); }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: var(--sp-3); }
        .stat-item { background: var(--bg-surface); border: 1px solid var(--border-card); border-radius: var(--r-md); padding: var(--sp-3); text-align: center; }
        .stat-label { font-size: 11px; color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 4px; }
        .stat-value { font-size: 18px; font-weight: 700; font-variant-numeric: tabular-nums; }
        .stat-value.positive { color: var(--positive); }
        .stat-value.negative { color: var(--negative); }
        .calculated-value { height: 48px; padding: 0 14px; background: rgba(0,208,132,0.07); border: 1px solid rgba(0,208,132,0.18); border-radius: var(--r-md); color: var(--positive); font-weight: 700; font-size: 14px; display: flex; align-items: center; }
        .info-text { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--sp-4); }
        .ticker-cell { font-weight: 700; color: var(--accent); font-size: 14px; }
        .positive { color: var(--positive); font-weight: 600; }
        .negative { color: var(--negative); font-weight: 600; }
        .neutral  { color: var(--warning); }
        .warning-badge { display: inline-block; padding: 2px 7px; border-radius: 99px; font-size: 10px; font-weight: 700; margin: 2px; text-transform: uppercase; }
        .warning-badge.error   { background: rgba(255,71,87,0.15); border: 1px solid rgba(255,71,87,0.3); color: var(--negative); }
        .warning-badge.warning { background: rgba(255,184,0,0.15); border: 1px solid rgba(255,184,0,0.3); color: var(--warning); }
        .status-badge { display: inline-block; padding: 3px 10px; border-radius: 99px; font-size: 11px; font-weight: 700; }
        .status-badge.open   { background: rgba(0,208,132,0.12); color: var(--positive); border: 1px solid rgba(0,208,132,0.25); }
        .status-badge.closed { background: rgba(139,146,168,0.12); color: var(--text-muted); border: 1px solid rgba(139,146,168,0.2); }
        .message { padding: 12px 16px; border-radius: var(--r-md); margin: var(--sp-3) 0; font-size: 14px; font-weight: 500; }
        .success { background: rgba(0,208,132,0.1); border: 1px solid rgba(0,208,132,0.25); color: var(--positive); }
        .error   { background: rgba(255,71,87,0.1); border: 1px solid rgba(255,71,87,0.25); color: var(--negative); }
        .spinner { border: 3px solid rgba(91,124,255,0.1); border-top-color: var(--accent); border-radius: 50%; width: 24px; height: 24px; animation: spin 0.7s linear infinite; display: inline-block; vertical-align: middle; margin-right: 8px; }
        .table-container { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { padding: 10px 12px; text-align: left; background: rgba(91,124,255,0.06); color: var(--text-muted); font-weight: 700; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--border); white-space: nowrap; }
        td { padding: 12px; text-align: left; border-bottom: 1px solid var(--border-subtle); white-space: nowrap; }
        tbody tr:hover { background: rgba(255,255,255,0.035); }
        .btn-close, .btn-edit, .btn-delete { padding: 4px 10px; border: none; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; font-family: inherit; margin-right: 4px; transition: opacity 0.15s; }
        .btn-close:hover, .btn-edit:hover, .btn-delete:hover { opacity: 0.8; }
        .btn-close  { background: rgba(0,208,132,0.12); color: var(--positive); }
        .btn-edit   { background: rgba(91,124,255,0.12); color: var(--accent); }
        .btn-delete { background: rgba(255,71,87,0.12); color: var(--negative); }
        .tabs { display: flex; border-bottom: 1px solid var(--border); margin-bottom: var(--sp-4); }
        .tab { padding: 10px 20px; background: transparent; border: none; color: var(--text-muted); font-size: 13px; font-weight: 600; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; transition: color 0.15s, border-color 0.15s; font-family: inherit; }
        .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
        .tab:hover:not(.active) { color: var(--text-primary); }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        /* ── Mobile overrides ── */
        @media (max-width: 768px) {
            .summary-grid { grid-template-columns: 1fr 1fr; }
            .stats-grid   { grid-template-columns: repeat(2, 1fr); }
            .grid         { grid-template-columns: 1fr; }
            th, td        { padding: 8px 8px; font-size: 12px; }
            .tab          { padding: 10px 12px; font-size: 12px; }
            /* Pie chart + legend: stack vertically */
            .alloc-chart-wrap { flex-direction: column; align-items: flex-start; gap: var(--sp-4); }
            .alloc-legend-wrap { min-width: unset !important; width: 100%; }
            /* Summary value font size */
            .summary-value { font-size: 20px; }
            /* Action buttons in tables */
            .btn-close, .btn-edit, .btn-delete { padding: 5px 8px; font-size: 11px; }
            /* Form grid */
            .form-group { margin-bottom: 10px; }
        }
        @media (max-width: 480px) {
            .summary-grid { grid-template-columns: 1fr; }
            .stats-grid   { grid-template-columns: repeat(2, 1fr); }
            .summary-value { font-size: 18px; }
        }

        /* ── Chart Modal ─────────────────────────────────────────────────────── */
        .ticker-link {
            font-weight: 700;
            color: var(--accent);
            font-size: 14px;
            cursor: pointer;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            transition: color 0.15s, opacity 0.15s;
            border-bottom: 1px dashed rgba(91,124,255,0.4);
            padding-bottom: 1px;
        }
        .ticker-link:hover {
            color: #fff;
            border-bottom-color: rgba(255,255,255,0.5);
        }
        .ticker-link::after {
            content: '↗';
            font-size: 10px;
            opacity: 0.6;
        }

        /* Slide-over panel overlay */
        #chartModal {
            display: none;
            position: fixed;
            inset: 0;
            z-index: 2000;
            background: rgba(0,0,0,0.72);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
        }
        #chartModal.active { display: flex; align-items: stretch; justify-content: flex-end; }

        /* Slide-over panel */
        #chartPanel {
            width: min(92vw, 1060px);
            height: 100vh;
            background: var(--bg-elevated, #141520);
            border-left: 1px solid rgba(91,124,255,0.18);
            display: flex;
            flex-direction: column;
            transform: translateX(100%);
            transition: transform 0.32s cubic-bezier(0.22,1,0.36,1);
            overflow: hidden;
        }
        #chartModal.active #chartPanel { transform: translateX(0); }

        /* Panel header */
        #chartPanelHeader {
            display: flex;
            align-items: center;
            gap: var(--sp-4);
            padding: 18px 24px;
            border-bottom: 1px solid rgba(91,124,255,0.12);
            background: rgba(91,124,255,0.04);
            flex-shrink: 0;
        }
        .chart-header-ticker {
            font-size: 22px;
            font-weight: 900;
            color: #fff;
            letter-spacing: -0.5px;
        }
        .chart-side-badge {
            padding: 4px 12px;
            border-radius: 99px;
            font-size: 12px;
            font-weight: 800;
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }
        .chart-side-badge.long  { background: rgba(0,208,132,0.18); color: var(--positive); border: 1px solid rgba(0,208,132,0.35); }
        .chart-side-badge.short { background: rgba(255,71,87,0.18);  color: var(--negative); border: 1px solid rgba(255,71,87,0.35); }
        .chart-status-badge {
            padding: 3px 10px;
            border-radius: 99px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
        }
        .chart-status-badge.open   { background: rgba(0,208,132,0.12); color: var(--positive); border: 1px solid rgba(0,208,132,0.25); }
        .chart-status-badge.closed { background: rgba(139,146,168,0.12); color: var(--text-muted); border: 1px solid rgba(139,146,168,0.2); }
        .chart-close-btn {
            margin-left: auto;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.1);
            color: #aaa;
            width: 36px;
            height: 36px;
            border-radius: 50%;
            cursor: pointer;
            font-size: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.15s, color 0.15s;
            flex-shrink: 0;
        }
        .chart-close-btn:hover { background: rgba(255,71,87,0.18); color: var(--negative); border-color: rgba(255,71,87,0.35); }

        /* Panel body: levels strip + chart area */
        #chartPanelBody {
            display: flex;
            flex-direction: column;
            flex: 1;
            overflow: hidden;
        }

        /* Trade summary strip */
        #tradeSummaryStrip {
            display: flex;
            gap: 0;
            border-bottom: 1px solid rgba(91,124,255,0.1);
            flex-shrink: 0;
            overflow-x: auto;
        }
        .strip-item {
            padding: 14px 20px;
            border-right: 1px solid rgba(91,124,255,0.08);
            display: flex;
            flex-direction: column;
            gap: 3px;
            min-width: 90px;
        }
        .strip-label {
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            color: var(--text-muted, #8B92A8);
        }
        .strip-value {
            font-size: 14px;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            color: #fff;
        }
        .strip-value.pos { color: var(--positive, #00D084); }
        .strip-value.neg { color: var(--negative, #FF4757); }
        .strip-value.warn { color: var(--warning, #FFB800); }

        /* Chart + levels visualizer row */
        #chartAndLevels {
            display: flex;
            flex: 1;
            overflow: hidden;
        }

        /* TradingView iframe area */
        #tvChartWrap {
            flex: 1;
            position: relative;
            background: #0d0f1a;
            display: flex;
            flex-direction: column;
            min-height: 0;
        }
        #tvChartWrap iframe {
            width: 100%;
            height: 100%;
            border: none;
            display: block;
        }
        #tvChartLoading {
            position: absolute;
            inset: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: #0d0f1a;
            gap: 12px;
            z-index: 1;
        }
        #tvChartLoading .spinner { width: 32px; height: 32px; border-width: 3px; }
        #tvChartLoadingText { font-size: 13px; color: var(--text-muted, #8B92A8); }
        #tvChartError {
            display: none;
            position: absolute;
            inset: 0;
            background: #0d0f1a;
            align-items: center;
            justify-content: center;
            flex-direction: column;
            gap: 8px;
            padding: 24px;
            text-align: center;
        }
        #tvChartError .err-icon { font-size: 40px; }
        #tvChartError .err-title { font-size: 16px; font-weight: 700; color: #fff; }
        #tvChartError .err-sub { font-size: 13px; color: #8B92A8; }

        /* Price levels sidebar */
        #levelsBar {
            width: 180px;
            flex-shrink: 0;
            background: rgba(0,0,0,0.25);
            border-left: 1px solid rgba(91,124,255,0.1);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .levels-title {
            padding: 12px 14px 8px;
            font-size: 10px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-muted, #8B92A8);
            border-bottom: 1px solid rgba(91,124,255,0.1);
        }
        #levelsList {
            flex: 1;
            display: flex;
            flex-direction: column;
            justify-content: space-around;
            padding: 12px 0;
        }
        .level-row {
            padding: 10px 14px;
            display: flex;
            flex-direction: column;
            gap: 3px;
        }
        .level-label {
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .level-price {
            font-size: 15px;
            font-weight: 800;
            font-variant-numeric: tabular-nums;
            letter-spacing: -0.3px;
        }
        .level-pct {
            font-size: 10px;
            font-weight: 600;
            opacity: 0.7;
        }
        /* Colour coding */
        .level-row.entry  .level-label { color: var(--accent, #5B7CFF); }
        .level-row.entry  .level-price { color: var(--accent, #5B7CFF); }
        .level-row.tp     .level-label { color: var(--positive, #00D084); }
        .level-row.tp     .level-price { color: var(--positive, #00D084); }
        .level-row.sl     .level-label { color: var(--negative, #FF4757); }
        .level-row.sl     .level-price { color: var(--negative, #FF4757); }
        .level-row.current .level-label { color: #fff; }
        .level-row.current .level-price { color: #fff; }

        /* Visual price scale */
        #priceScale {
            margin: 0 14px 12px;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid rgba(91,124,255,0.12);
        }
        .scale-zone {
            padding: 6px 8px;
            font-size: 10px;
            font-weight: 600;
            text-align: center;
            letter-spacing: 0.3px;
        }
        .scale-zone.profit-zone { background: rgba(0,208,132,0.12); color: var(--positive); }
        .scale-zone.entry-zone  { background: rgba(91,124,255,0.14); color: var(--accent); font-weight: 800; }
        .scale-zone.risk-zone   { background: rgba(255,71,87,0.12);  color: var(--negative); }
        .scale-zone.divider     { background: rgba(255,255,255,0.03); color: #555; font-size: 9px; }

        /* Responsive: on mobile, levels bar moves below chart */
        @media (max-width: 640px) {
            #chartPanel { width: 100vw; }
            #chartAndLevels { flex-direction: column; }
            #levelsBar {
                width: 100%;
                border-left: none;
                border-top: 1px solid rgba(91,124,255,0.1);
                flex-direction: row;
                overflow-x: auto;
                height: auto;
                max-height: 130px;
            }
            .levels-title { display: none; }
            #levelsList {
                flex-direction: row;
                padding: 0;
                justify-content: flex-start;
            }
            .level-row { border-right: 1px solid rgba(91,124,255,0.08); min-width: 90px; }
            #priceScale { display: none; }
            #tradeSummaryStrip .strip-item { min-width: 80px; padding: 10px 14px; }
            #tvChartWrap { min-height: 320px; }
        }
        @media (max-width: 480px) {
            #chartPanelHeader { padding: 14px 16px; }
            .chart-header-ticker { font-size: 18px; }
        }
    </style>
</head>
<body>
    <!-- Sticky Top Nav -->
    <nav class="top-nav">
        <span class="top-nav-brand">📈 PulseAlerts</span>
        <a href="/dashboard" class="top-nav-link">📊 Alerts</a>
        <a href="/portfolio" class="top-nav-link active">💼 Portfolio</a>
        <a href="/alerts/history" class="top-nav-link">📜 History</a>
        <a href="/radar" class="top-nav-link">🚨 Radar</a>
        <a href="/bitcoin-scanner" class="top-nav-link">₿ Bitcoin</a>
        <a href="/forex-sessions" class="top-nav-link">🌐 Forex</a>
        <a href="/fundamentals" class="top-nav-link">📋 Fundamentals</a>
        <span class="top-nav-spacer"></span>
        <button class="top-nav-logout" onclick="logout()">Sign out</button>
    </nav>

    <div class="page-wrapper">
        <div class="page-header" style="margin-bottom: var(--sp-6);">
            <div class="page-eyebrow">Trading</div>
            <h1 class="page-title">Portfolio</h1>
            <p class="page-subtitle">Track positions, P&amp;L, and allocation across your portfolio</p>
        </div>

        <div id="message"></div>

        <!-- Portfolio Cash -->
        <div class="card" style="margin-bottom: var(--sp-4);">
            <div class="card-header">
                <div class="card-title">Portfolio Balance</div>
            </div>
            <div class="form-group">
                <label class="form-label">Total Portfolio Cash ($)</label>
                <input type="number" id="portfolioCash" placeholder="Enter total portfolio value" step="0.01" min="0" class="form-input">
            </div>
            <button class="btn btn-primary" onclick="updatePortfolioCash()">Update Balance</button>
        </div>

        <!-- Portfolio Summary -->
        <div class="card" id="summaryCard" style="margin-bottom: var(--sp-4);">
            <div class="card-header"><div class="card-title">Portfolio Overview</div></div>
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
        <div class="card" id="statsCard" style="margin-bottom: var(--sp-4);">
            <div class="card-header"><div class="card-title">Trading Performance</div></div>
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

        <!-- Allocation Pie Chart -->
        <div class="card" id="allocationCard" style="margin-bottom: var(--sp-4);">
            <div class="card-header"><div class="card-title">Allocation by Category</div></div>
            <div class="alloc-chart-wrap" style="display:flex;align-items:center;gap:40px;flex-wrap:wrap;">
                <div style="position:relative;width:220px;height:220px;flex-shrink:0;">
                    <canvas id="allocPieCanvas" width="220" height="220"></canvas>
                </div>
                <div id="allocLegend" class="alloc-legend-wrap" style="display:flex;flex-direction:column;gap:10px;font-size:13px;flex:1;min-width:200px;"></div>
            </div>
        </div>

        <!-- Add/Edit Trade Form -->
        <div class="card" style="margin-bottom: var(--sp-4);">
            <div class="card-header">
                <div class="card-title" id="formTitle">Add New Trade</div>
            </div>
            <div class="grid">
                <div class="form-group">
                    <label class="form-label">Ticker *</label>
                    <input type="text" id="ticker" placeholder="e.g., AAPL" maxlength="10" class="form-input">
                </div>
                <div class="form-group">
                    <label class="form-label">Buy Price ($) *</label>
                    <input type="number" id="buyPrice" step="0.01" min="0" oninput="calculateValues()" class="form-input">
                </div>
                <div class="form-group">
                    <label class="form-label">Quantity *</label>
                    <input type="number" id="quantity" step="0.0001" min="0" oninput="calculateValues()" class="form-input">
                </div>
                <div class="form-group">
                    <label class="form-label">Stop Loss ($)</label>
                    <input type="number" id="stopLoss" step="0.01" min="0" placeholder="Optional" oninput="calculateValues()" class="form-input">
                </div>
                <div class="form-group">
                    <label class="form-label">Position Size ($) — Auto</label>
                    <div class="calculated-value" id="positionSizeDisplay">$0.00</div>
                    <div class="info-text">= Buy Price × Quantity</div>
                </div>
                <div class="form-group">
                    <label class="form-label">Risk Amount ($) — Auto</label>
                    <div class="calculated-value" id="riskAmountDisplay">$0.00</div>
                    <div class="info-text">= |Buy Price − Stop Loss| × Quantity</div>
                </div>
                <div class="form-group">
                    <label class="form-label">Take Profit ($)</label>
                    <input type="number" id="takeProfit" step="0.01" min="0" placeholder="Optional" class="form-input">
                </div>
                <div class="form-group">
                    <label class="form-label">Timeframe *</label>
                    <select id="timeframe" class="form-input">
                        <option value="Long">Long</option>
                        <option value="Swing">Swing</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Trade Date *</label>
                    <input type="date" id="tradeDate" class="form-input">
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Notes</label>
                <textarea id="notes" placeholder="Optional trade notes..." class="form-input" style="height:auto;min-height:80px;padding:12px 14px;"></textarea>
            </div>
            <div style="display:flex;gap:var(--sp-3);align-items:center;">
                <button id="saveTradeBtn" class="btn btn-primary" onclick="saveTrade()">Add Trade</button>
                <button class="btn btn-ghost" onclick="clearForm()" style="display:none;" id="cancelBtn">Cancel</button>
            </div>
        </div>

        <!-- Trades Table -->
        <div class="card" style="margin-bottom: var(--sp-4);">
            <div class="card-header"><div class="card-title">Trade Journal</div></div>
            
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

    <!-- ── Chart Viewer Panel ─────────────────────────────────────────────── -->
    <div id="chartModal" onclick="handleChartModalBackdrop(event)">
        <div id="chartPanel">

            <!-- Header -->
            <div id="chartPanelHeader">
                <span class="chart-header-ticker" id="cpTicker">—</span>
                <span class="chart-side-badge long" id="cpSideBadge">LONG</span>
                <span class="chart-status-badge open" id="cpStatusBadge">OPEN</span>
                <button class="chart-close-btn" onclick="closeChartModal()" title="Close">&#x2715;</button>
            </div>

            <!-- Summary strip -->
            <div id="tradeSummaryStrip">
                <div class="strip-item">
                    <span class="strip-label">Entry</span>
                    <span class="strip-value" id="cpEntry">—</span>
                </div>
                <div class="strip-item">
                    <span class="strip-label">Stop Loss</span>
                    <span class="strip-value neg" id="cpSL">—</span>
                </div>
                <div class="strip-item">
                    <span class="strip-label">Take Profit</span>
                    <span class="strip-value pos" id="cpTP">—</span>
                </div>
                <div class="strip-item">
                    <span class="strip-label">Current</span>
                    <span class="strip-value" id="cpCurrent">—</span>
                </div>
                <div class="strip-item">
                    <span class="strip-label">P&L</span>
                    <span class="strip-value" id="cpPnl">—</span>
                </div>
                <div class="strip-item">
                    <span class="strip-label">P&L %</span>
                    <span class="strip-value" id="cpPnlPct">—</span>
                </div>
                <div class="strip-item">
                    <span class="strip-label">R:R Ratio</span>
                    <span class="strip-value" id="cpRR">—</span>
                </div>
                <div class="strip-item">
                    <span class="strip-label">Timeframe</span>
                    <span class="strip-value" id="cpTimeframe">—</span>
                </div>
                <div class="strip-item">
                    <span class="strip-label">Trade Date</span>
                    <span class="strip-value" id="cpDate">—</span>
                </div>
            </div>

            <!-- Chart + Levels -->
            <div id="chartAndLevels">

                <!-- TradingView chart -->
                <div id="tvChartWrap">
                    <div id="tvChartLoading">
                        <div class="spinner"></div>
                        <span id="tvChartLoadingText">Loading chart…</span>
                    </div>
                    <div id="tvChartError">
                        <span class="err-icon">📊</span>
                        <span class="err-title">Chart unavailable</span>
                        <span class="err-sub" id="tvChartErrorMsg">Could not load chart for this symbol.</span>
                    </div>
                    <!-- iframe injected by JS -->
                </div>

                <!-- Price levels sidebar -->
                <div id="levelsBar">
                    <div class="levels-title">Price Levels</div>
                    <div id="levelsList">
                        <!-- Populated by JS in price order -->
                    </div>
                    <div id="priceScale">
                        <!-- Zone bars populated by JS -->
                    </div>
                </div>

            </div>
        </div>
    </div>

    <!-- Close Trade Modal -->
    <div id="closeModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3 class="card-title">Close Trade</h3>
                <p class="card-subtitle" style="margin-top:4px;">Enter the price and date at which you closed this position</p>
            </div>
            <div class="form-group">
                <label class="form-label">Close Price ($)</label>
                <input type="number" id="closePrice" step="0.01" min="0" class="form-input">
            </div>
            <div class="form-group">
                <label class="form-label">Close Date</label>
                <input type="date" id="closeDate" class="form-input">
            </div>
            <div style="display:flex;gap:var(--sp-3);margin-top:var(--sp-4);">
                <button class="btn btn-primary" onclick="confirmCloseTrade()">Close Trade</button>
                <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
            </div>
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
                    renderAllocationChart();
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
                    renderAllocationChart();
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
                        <td class="ticker-cell"><a class="ticker-link" onclick="openChartModal(${trade.id})">${trade.ticker}</a></td>
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
                        <td class="ticker-cell"><a class="ticker-link" onclick="openChartModal(${trade.id})">${trade.ticker}</a></td>
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
                        <td class="ticker-cell"><a class="ticker-link" onclick="openChartModal(${trade.id})">${trade.ticker}</a></td>
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

        // ── Allocation pie chart ──────────────────────────────────────────────
        const TICKER_CATEGORY = {
            // Crypto
            BTC:'Crypto', ETH:'Crypto', SOL:'Crypto', XRP:'Crypto', ADA:'Crypto',
            DOGE:'Crypto', AVAX:'Crypto', DOT:'Crypto', LINK:'Crypto', MATIC:'Crypto',
            // Software / Tech
            AAPL:'Software', MSFT:'Software', GOOGL:'Software', GOOG:'Software',
            META:'Software', AMZN:'Software', NVDA:'Software', TSLA:'Software',
            NFLX:'Software', ADBE:'Software', CRM:'Software', ORCL:'Software',
            SHOP:'Software', SNOW:'Software', NOW:'Software', PLTR:'Software',
            // Security
            PANW:'Security', CRWD:'Security', ZS:'Security', FTNT:'Security',
            OKTA:'Security', S:'Security', CYBR:'Security', NET:'Security',
            // Energy
            XOM:'Energy', CVX:'Energy', OKE:'Energy', ET:'Energy',
            EPD:'Energy', MPC:'Energy', PSX:'Energy', VLO:'Energy',
            // Finance
            JPM:'Finance', BAC:'Finance', GS:'Finance', MS:'Finance',
            V:'Finance', MA:'Finance', PYPL:'Finance', BLK:'Finance',
            // Healthcare
            JNJ:'Healthcare', PFE:'Healthcare', MRK:'Healthcare', ABBV:'Healthcare',
            UNH:'Healthcare', CVS:'Healthcare', AMGN:'Healthcare', GILD:'Healthcare',
        };
        const CATEGORY_COLORS = {
            Crypto:     '#F7931A',
            Software:   '#5B7CFF',
            Security:   '#FF6B6B',
            Energy:     '#FFB800',
            Finance:    '#00C9A7',
            Healthcare: '#A78BFA',
            Other:      '#8B92A8',
            Cash:       '#2DD4BF',
        };

        let _allocChart = null;

        function normalizeTicker(ticker) {
            // Strip crypto suffixes like -USD, -USDT, -BTC so BTC-USD matches BTC
            return ticker.toUpperCase().replace(/-(USD|USDT|BTC|ETH)$/, '');
        }

        function renderAllocationChart() {
            const openTrades = allTrades.filter(t => !t.is_closed);
            const buckets = {};
            openTrades.forEach(t => {
                const cat = TICKER_CATEGORY[normalizeTicker(t.ticker)] || 'Other';
                buckets[cat] = (buckets[cat] || 0) + parseFloat(t.position_size || 0);
            });
            // Add uninvested cash
            const invested = Object.values(buckets).reduce((a, b) => a + b, 0);
            const cashVal = Math.max(0, portfolioCash - invested);
            if (cashVal > 0) buckets['Cash'] = cashVal;

            const labels = Object.keys(buckets);
            const values = labels.map(k => buckets[k]);
            const colors = labels.map(k => CATEGORY_COLORS[k] || CATEGORY_COLORS.Other);

            const ctx = document.getElementById('allocPieCanvas').getContext('2d');
            if (_allocChart) _allocChart.destroy();
            _allocChart = new Chart(ctx, {
                type: 'doughnut',
                data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 0 }] },
                options: {
                    responsive: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: ctx => {
                                    const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                                    const pct = total > 0 ? (ctx.raw / total * 100).toFixed(1) : 0;
                                    return ' $' + ctx.raw.toLocaleString('en-US', {minimumFractionDigits: 0, maximumFractionDigits: 0}) + ' (' + pct + '%)';
                                }
                            }
                        }
                    },
                    cutout: '60%',
                },
            });

            // Custom legend
            const legendEl = document.getElementById('allocLegend');
            const total = values.reduce((a, b) => a + b, 0);
            legendEl.innerHTML = labels.map((lbl, i) => {
                const pct = total > 0 ? (values[i] / total * 100).toFixed(1) : 0;
                return '<div style="display:flex;align-items:center;gap:8px;">' +
                    '<span style="width:12px;height:12px;border-radius:50%;background:' + colors[i] + ';flex-shrink:0;"></span>' +
                    '<span style="color:#8B92A8;">' + lbl + '</span>' +
                    '<span style="margin-left:auto;color:#E2E8F0;font-weight:600;">$' +
                        values[i].toLocaleString('en-US', {minimumFractionDigits:0,maximumFractionDigits:0}) +
                        ' <span style="color:#8B92A8;font-weight:400;">(' + pct + '%)</span></span>' +
                    '</div>';
            }).join('');
        }

        // Logout
        async function logout() {
            await fetch('/api/logout');
            window.location.href = '/login';
        }

        // ── Chart Modal ───────────────────────────────────────────────────────

        /**
         * Map a portfolio ticker to a TradingView symbol.
         * TradingView accepts "EXCHANGE:SYMBOL" or bare "SYMBOL".
         * For crypto, strip the -USD / -USDT suffix and prepend COINBASE:.
         * For common stocks, default to NASDAQ: and fall back to NYSE: silently.
         */
        const CRYPTO_TICKERS = new Set([
            'BTC','ETH','SOL','XRP','ADA','DOGE','AVAX','DOT','LINK','MATIC',
            'LTC','BCH','UNI','ATOM','FTM','NEAR','ALGO','VET','HBAR','ICP',
            'SHIB','PEPE','APT','ARB','OP','SUI','INJ','TIA','PYTH'
        ]);
        const NYSE_TICKERS = new Set([
            'JPM','BAC','GS','MS','V','MA','BLK','C','WFC','AXP',
            'XOM','CVX','COP','SLB','HAL','OKE','ET','EPD','MPC','PSX','VLO',
            'JNJ','PFE','MRK','ABBV','UNH','CVS','AMGN','GILD','BMY','LLY',
            'BRK','WMT','TGT','HD','NKE','DIS','GE','BA','CAT','MMM','HON',
            'F','GM','T','VZ','NEE','SO','DUK','D'
        ]);

        function mapToTVSymbol(rawTicker) {
            // Strip common crypto quote suffixes: BTC-USD → BTC, ETH-USDT → ETH
            const base = rawTicker.toUpperCase().replace(/[-.](USD|USDT|BTC|ETH|BUSD|USDC)$/,'');

            if (CRYPTO_TICKERS.has(base)) {
                // Try COINBASE first; TradingView falls back gracefully
                return 'COINBASE:' + base + 'USD';
            }

            if (NYSE_TICKERS.has(base)) {
                return 'NYSE:' + base;
            }

            // Default: NASDAQ (covers AAPL, MSFT, GOOGL, NVDA, TSLA, etc.)
            return 'NASDAQ:' + base;
        }

        function buildTVEmbedURL(tvSymbol) {
            const params = new URLSearchParams({
                symbol:           tvSymbol,
                interval:         'D',
                theme:            'dark',
                style:            '1',       // candlestick
                locale:           'en',
                toolbar_bg:       '%230d0f1a',
                hide_top_toolbar: '0',
                hide_legend:      '0',
                save_image:       '0',
                allow_symbol_change: '1',
            });
            return 'https://www.tradingview.com/widgetsnippet/chart/?' + params.toString();
        }

        /** Format a price with $ and 2 decimals (or more for sub-$1 assets) */
        function fmtPrice(p) {
            if (p == null) return '—';
            const n = parseFloat(p);
            if (isNaN(n)) return '—';
            if (n < 1)    return '$' + n.toFixed(4);
            if (n < 100)  return '$' + n.toFixed(3);
            return '$' + n.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
        }

        function fmtPct(p) {
            if (p == null) return '—';
            const n = parseFloat(p);
            if (isNaN(n)) return '—';
            return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
        }

        function pctFromEntry(price, entry) {
            if (!price || !entry) return null;
            return ((parseFloat(price) - parseFloat(entry)) / parseFloat(entry)) * 100;
        }

        /** Determine trade direction from stop_loss vs buy_price.
         *  If stop_loss < buy_price → LONG (classic stop below entry).
         *  If stop_loss > buy_price → SHORT.
         *  If no stop_loss, assume LONG. */
        function tradeDirection(trade) {
            if (!trade.stop_loss) return 'LONG';
            return parseFloat(trade.stop_loss) < parseFloat(trade.buy_price) ? 'LONG' : 'SHORT';
        }

        function openChartModal(tradeId) {
            const trade = allTrades.find(t => t.id === tradeId);
            if (!trade) return;

            const direction = tradeDirection(trade);
            const isLong    = direction === 'LONG';
            const isClosed  = !!trade.is_closed;

            // ── Header ──────────────────────────────────────────────────────
            document.getElementById('cpTicker').textContent = trade.ticker;

            const sideBadge = document.getElementById('cpSideBadge');
            sideBadge.textContent  = direction;
            sideBadge.className    = 'chart-side-badge ' + direction.toLowerCase();

            const statusBadge = document.getElementById('cpStatusBadge');
            statusBadge.textContent = isClosed ? 'CLOSED' : 'OPEN';
            statusBadge.className   = 'chart-status-badge ' + (isClosed ? 'closed' : 'open');

            // ── Summary strip ────────────────────────────────────────────────
            const entry       = parseFloat(trade.buy_price)   || null;
            const sl          = trade.stop_loss  ? parseFloat(trade.stop_loss)  : null;
            const tp          = trade.take_profit ? parseFloat(trade.take_profit) : null;
            const currentP    = trade.current_price  ? parseFloat(trade.current_price)  : null;
            const closedAtP   = trade.close_price    ? parseFloat(trade.close_price)    : null;
            const displayPrice = isClosed ? closedAtP : currentP;

            document.getElementById('cpEntry').textContent     = fmtPrice(entry);
            document.getElementById('cpSL').textContent        = sl   ? fmtPrice(sl)  : 'None';
            document.getElementById('cpTP').textContent        = tp   ? fmtPrice(tp)  : 'None';
            document.getElementById('cpCurrent').textContent   = displayPrice ? fmtPrice(displayPrice) : '…';
            document.getElementById('cpTimeframe').textContent = trade.timeframe || '—';
            document.getElementById('cpDate').textContent      = trade.trade_date || '—';

            // P&L
            const pnl    = isClosed ? trade.realized_pnl    : trade.unrealized_pnl;
            const pnlPct = isClosed ? trade.realized_pnl_pct : trade.unrealized_pnl_pct;
            const pnlEl    = document.getElementById('cpPnl');
            const pnlPctEl = document.getElementById('cpPnlPct');
            if (pnl != null) {
                pnlEl.textContent  = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
                pnlEl.className    = 'strip-value ' + (pnl >= 0 ? 'pos' : 'neg');
                pnlPctEl.textContent = fmtPct(pnlPct);
                pnlPctEl.className   = 'strip-value ' + ((pnlPct||0) >= 0 ? 'pos' : 'neg');
            } else {
                pnlEl.textContent    = '—';
                pnlEl.className      = 'strip-value';
                pnlPctEl.textContent = '—';
                pnlPctEl.className   = 'strip-value';
            }

            // R:R
            const rrEl = document.getElementById('cpRR');
            if (trade.rr_ratio != null) {
                rrEl.textContent = parseFloat(trade.rr_ratio).toFixed(2) + 'x';
                rrEl.className   = 'strip-value ' + (parseFloat(trade.rr_ratio) >= 1.5 ? 'pos' : 'warn');
            } else {
                rrEl.textContent = '—';
                rrEl.className   = 'strip-value';
            }

            // ── Price Levels sidebar ─────────────────────────────────────────
            renderLevels(entry, sl, tp, displayPrice, isLong);

            // ── TradingView chart ────────────────────────────────────────────
            const tvSymbol = mapToTVSymbol(trade.ticker);
            loadTVChart(tvSymbol);

            // Show modal with animation
            document.getElementById('chartModal').classList.add('active');
            document.body.style.overflow = 'hidden';
        }

        function renderLevels(entry, sl, tp, current, isLong) {
            const list = document.getElementById('levelsList');

            // Build items with relative distance from entry
            const items = [];

            if (tp != null) {
                const diff = pctFromEntry(tp, entry);
                items.push({ cls: 'tp', label: 'Take Profit', price: tp, pct: diff });
            }
            if (entry != null) {
                items.push({ cls: 'entry', label: 'Entry', price: entry, pct: 0 });
            }
            if (current != null) {
                const diff = pctFromEntry(current, entry);
                items.push({ cls: 'current', label: 'Current', price: current, pct: diff });
            }
            if (sl != null) {
                const diff = pctFromEntry(sl, entry);
                items.push({ cls: 'sl', label: 'Stop Loss', price: sl, pct: diff });
            }

            // Sort by price descending (highest price at top of sidebar)
            items.sort((a, b) => b.price - a.price);

            list.innerHTML = items.map(item => {
                const pctStr = item.pct != null ? fmtPct(item.pct) : '';
                return `
                    <div class="level-row ${item.cls}">
                        <span class="level-label">${item.label}</span>
                        <span class="level-price">${fmtPrice(item.price)}</span>
                        ${item.pct !== 0 ? `<span class="level-pct">${pctStr} from entry</span>` : ''}
                    </div>
                `;
            }).join('');

            // ── Colour-zone scale (profit / entry / risk) ────────────────────
            const scaleEl = document.getElementById('priceScale');
            if (isLong) {
                // LONG: profit above entry, risk below
                scaleEl.innerHTML =
                    (tp ? `<div class="scale-zone profit-zone">▲ Profit Zone${tp ? '<br>' + fmtPrice(tp) : ''}</div>` : '') +
                    (tp && entry ? `<div class="scale-zone divider">— — —</div>` : '') +
                    `<div class="scale-zone entry-zone">● Entry ${fmtPrice(entry)}</div>` +
                    (sl && entry ? `<div class="scale-zone divider">— — —</div>` : '') +
                    (sl ? `<div class="scale-zone risk-zone">▼ Risk Zone<br>${fmtPrice(sl)}</div>` : '');
            } else {
                // SHORT: profit below entry, risk above
                scaleEl.innerHTML =
                    (sl ? `<div class="scale-zone risk-zone">▲ Risk Zone<br>${fmtPrice(sl)}</div>` : '') +
                    (sl && entry ? `<div class="scale-zone divider">— — —</div>` : '') +
                    `<div class="scale-zone entry-zone">● Entry ${fmtPrice(entry)}</div>` +
                    (tp && entry ? `<div class="scale-zone divider">— — —</div>` : '') +
                    (tp ? `<div class="scale-zone profit-zone">▼ Profit Zone<br>${fmtPrice(tp)}</div>` : '');
            }
        }

        function loadTVChart(tvSymbol) {
            const wrap    = document.getElementById('tvChartWrap');
            const loading = document.getElementById('tvChartLoading');
            const errDiv  = document.getElementById('tvChartError');
            const errMsg  = document.getElementById('tvChartErrorMsg');

            // Remove any previous iframe
            const prev = wrap.querySelector('iframe');
            if (prev) prev.remove();

            loading.style.display = 'flex';
            errDiv.style.display  = 'none';
            document.getElementById('tvChartLoadingText').textContent = 'Loading chart for ' + tvSymbol + '…';

            // Build iframe
            const iframe = document.createElement('iframe');
            iframe.style.cssText = 'width:100%;height:100%;border:none;display:none;';
            iframe.setAttribute('allowtransparency', 'true');
            iframe.setAttribute('allowfullscreen', '');

            // TradingView Advanced Chart widget URL
            const src = 'https://www.tradingview.com/widgetsnippet/chart/?symbol=' + encodeURIComponent(tvSymbol)
                + '&interval=D&theme=dark&style=1&locale=en'
                + '&toolbar_bg=%230d0f1a'
                + '&hide_top_toolbar=0'
                + '&hide_legend=0'
                + '&allow_symbol_change=1'
                + '&save_image=0';

            iframe.src = src;

            iframe.onload = function() {
                loading.style.display = 'none';
                iframe.style.display  = 'block';
            };

            // If the iframe fails to communicate (cross-origin), hide loading after 8s
            let fallbackTimer = setTimeout(() => {
                if (loading.style.display !== 'none') {
                    loading.style.display = 'none';
                    iframe.style.display  = 'block';
                }
            }, 8000);

            iframe.onerror = function() {
                clearTimeout(fallbackTimer);
                loading.style.display = 'none';
                errDiv.style.display  = 'flex';
                errMsg.textContent    = 'Symbol "' + tvSymbol + '" could not be loaded. Try editing the ticker.';
            };

            wrap.appendChild(iframe);
        }

        function closeChartModal() {
            document.getElementById('chartModal').classList.remove('active');
            document.body.style.overflow = '';
            // Remove iframe to stop media/network activity
            setTimeout(() => {
                const iframe = document.getElementById('tvChartWrap').querySelector('iframe');
                if (iframe) iframe.remove();
            }, 350);
        }

        function handleChartModalBackdrop(event) {
            if (event.target === document.getElementById('chartModal')) {
                closeChartModal();
            }
        }

        // Close with Escape key
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && document.getElementById('chartModal').classList.contains('active')) {
                closeChartModal();
            }
        });
    </script>
    <script src="/static/js/nav-mobile.js"></script>
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

            # Include current_price so the frontend chart modal can use it
            if current_price is not None:
                enriched['current_price'] = float(current_price)

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
        notes = (data.get('notes') or '').strip() or None
        
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
@app.route('/api/alerts/history', methods=['GET'])
@login_required
def get_alert_history():
    from models import AlertTrigger
    history = AlertTrigger.get_user_history(current_user.id)
    return jsonify({'success': True, 'history': [
        {
            'id': r['id'], 'ticker': r['ticker'], 'alert_type': r['alert_type'],
            'triggered_at': r['triggered_at'].isoformat() if r['triggered_at'] else None,
            'price_at_trigger': float(r['price_at_trigger']) if r['price_at_trigger'] else None,
            'explanation': r['explanation_text']
        } for r in history
    ]})

@app.route('/api/alerts/parse-text', methods=['POST'])
@login_required
def parse_alert_text():
    """Parse natural language text using AI"""
    try:
        from services.ai_nl_parser import ai_nl_parser
        
        data = request.json
        text = data.get('text', '').strip()
        
        if not text:
            return jsonify({'success': False, 'error': 'No text provided'}), 400
        
        # Use AI parser
        result = ai_nl_parser.parse(text)
        
        if not result.get('success'):
            return jsonify(result), 400
        
        # Build readable summary
        ticker = result['ticker']
        alert_type = result['alert_type']
        params = result['parameters']
        
        # Create human-readable summary
        if alert_type == 'price':
            direction = 'above' if params.get('direction') == 'up' else 'below' if params.get('direction') == 'down' else 'near'
            summary = f"Alert when {ticker} goes {direction} ${params['target_price']:.2f}"
        elif alert_type == 'ma':
            summary = f"Alert when {ticker} crosses MA{params['ma_period']}"
        elif alert_type == 'percent_change':
            direction = params.get('direction', 'both')
            threshold = params['threshold_pct']
            if direction == 'up':
                summary = f"Alert when {ticker} rises {threshold}%+ in 24h"
            elif direction == 'down':
                summary = f"Alert when {ticker} falls {threshold}%+ in 24h"
            else:
                summary = f"Alert when {ticker} moves {threshold}%+ (either direction) in 24h"
        else:
            summary = f"Alert for {ticker}"
        
        return jsonify({
            'success': True,
            'suggestion': {
                'ticker': result['ticker'],
                'alert_type': result['alert_type'],
                'params': result['parameters'],
                'summary': summary,
                'confidence': result.get('confidence', 0.8),
                'interpretation': result.get('interpretation', '')
            }
        })
    
    except Exception as e:
        logger.error(f"Error parsing alert text: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/alerts/create-from-suggestion', methods=['POST'])
@login_required
def create_alert_from_suggestion():
    """Create alert from AI NL parser suggestion (after user confirms)"""
    try:
        data = request.json
        ticker = data['ticker'].upper()
        alert_type = data['alert_type']
        params = data['params']
        
        logger.info(f"Creating alert from AI suggestion: {ticker} | Type: {alert_type}")
        
        # Validate alert type is supported
        if alert_type not in ['price', 'ma', 'percent_change']:
            return jsonify({
                'success': False,
                'error': f'Alert type "{alert_type}" not yet supported via AI parsing. Try price, MA, or percent alerts.'
            }), 400
        
        # Get current price (validates ticker exists)
        current_price = price_checker.get_price(ticker)
        if current_price is None:
            return jsonify({'success': False, 'error': f'Could not get price for {ticker}. Invalid ticker?'}), 400
        
        logger.info(f"Current price for {ticker}: ${current_price:.2f}")
        
        # Create alert based on type
        alert_id = None
        
        if alert_type == 'price':
            # PRICE ALERT
            target_price = float(params['target_price'])
            direction = params.get('direction', 'both')
            
            # Validate price
            if target_price <= 0:
                return jsonify({'success': False, 'error': 'Price must be greater than 0'}), 400
            
            # Determine direction if "both"
            if direction == 'both':
                # Default: if target > current, direction is up; otherwise down
                direction = 'up' if target_price > current_price else 'down'
            
            alert_id = Alert.create(
                user_id=current_user.id,
                ticker=ticker,
                target_price=target_price,
                current_price=current_price,
                direction=direction,
                alert_type='price'
            )
            
            logger.info(f"Created price alert #{alert_id}: {ticker} @ ${target_price:.2f} ({direction})")
        
        elif alert_type == 'ma':
            # MA ALERT
            ma_period = int(params.get('ma_period', 50))
            
            # Validate MA period
            if ma_period not in [20, 50, 150]:
                return jsonify({'success': False, 'error': 'MA period must be 20, 50, or 150'}), 400
            
            # Calculate current MA value
            ma_value = price_checker.get_moving_average(ticker, ma_period)
            
            if ma_value is None:
                return jsonify({
                    'success': False, 
                    'error': f'Could not calculate MA{ma_period} for {ticker}. Not enough historical data.'
                }), 400
            
            # Direction for MA alerts (default: up = cross above)
            direction = params.get('direction', 'up')
            
            alert_id = Alert.create(
                user_id=current_user.id,
                ticker=ticker,
                target_price=ma_value,
                current_price=current_price,
                direction=direction,
                alert_type='ma',
                ma_period=ma_period
            )
            
            logger.info(f"Created MA alert #{alert_id}: {ticker} MA{ma_period} @ ${ma_value:.2f}")
            target_price = ma_value

        elif alert_type == 'percent_change':
            # PERCENT CHANGE ALERT — convert to a derived price level
            threshold_pct = float(params.get('threshold_pct', params.get('percent', 5.0)))
            direction = params.get('direction', 'both')

            if threshold_pct <= 0:
                return jsonify({'success': False, 'error': 'Threshold must be greater than 0%'}), 400

            if direction == 'up':
                target_price = round(current_price * (1 + threshold_pct / 100), 4)
                alert_direction = 'up'
            elif direction == 'down':
                target_price = round(current_price * (1 - threshold_pct / 100), 4)
                alert_direction = 'down'
            else:
                # "both" — create two alerts (up and down)
                price_up   = round(current_price * (1 + threshold_pct / 100), 4)
                price_down = round(current_price * (1 - threshold_pct / 100), 4)
                alert_id = Alert.create(
                    user_id=current_user.id, ticker=ticker,
                    target_price=price_up, current_price=current_price,
                    direction='up', alert_type='price'
                )
                Alert.create(
                    user_id=current_user.id, ticker=ticker,
                    target_price=price_down, current_price=current_price,
                    direction='down', alert_type='price'
                )
                logger.info(f"Created bidirectional {threshold_pct}% alerts for {ticker}: ↑{price_up} / ↓{price_down}")
                return jsonify({
                    'success': True,
                    'alert': {'id': alert_id, 'ticker': ticker, 'alert_type': 'price',
                              'target_price': price_up, 'current_price': current_price, 'direction': 'both'},
                    'message': f'✓ Two {threshold_pct}% alerts created for {ticker} (↑ and ↓)'
                })

            alert_id = Alert.create(
                user_id=current_user.id, ticker=ticker,
                target_price=target_price, current_price=current_price,
                direction=alert_direction, alert_type='price'
            )
            logger.info(f"Created {threshold_pct}% change alert #{alert_id}: {ticker} @ ${target_price:.4f} ({alert_direction})")
            direction = alert_direction

        # Return success
        return jsonify({
            'success': True,
            'alert': {
                'id': alert_id,
                'ticker': ticker,
                'alert_type': alert_type,
                'target_price': target_price,
                'current_price': current_price,
                'direction': direction
            },
            'message': f'✓ Alert created for {ticker}'
        })
    
    except KeyError as e:
        logger.error(f"Missing parameter: {e}")
        return jsonify({'success': False, 'error': f'Missing required parameter: {e}'}), 400
    
    except ValueError as e:
        logger.error(f"Invalid value: {e}")
        return jsonify({'success': False, 'error': f'Invalid value: {e}'}), 400
    
    except Exception as e:
        logger.error(f"Error creating alert from suggestion: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/radar', methods=['GET'])
@login_required
def get_market_radar():
    from models import Anomaly
    anomalies = Anomaly.get_user_anomalies(current_user.id)
    return jsonify({'success': True, 'anomalies': [
        {
            'id': a['id'], 'ticker': a['ticker'], 'anomaly_type': a['anomaly_type'],
            'metrics': a['metrics_json'], 'severity': a.get('severity'),
            'detected_at': a['detected_at'].isoformat() if a['detected_at'] else None
        } for a in anomalies
    ]})

@app.route('/alerts/history')
@login_required
def alert_history_page():
    """Alert trigger history page with AI explanations"""
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Alert History — PulseAlerts</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="/static/css/theme.css">
    <style>
        body { padding: 0; }
    </style>
</head>
<body>
    <nav class="top-nav">
        <span class="top-nav-brand">📈 PulseAlerts</span>
        <a href="/dashboard" class="top-nav-link">📊 Alerts</a>
        <a href="/portfolio" class="top-nav-link">💼 Portfolio</a>
        <a href="/alerts/history" class="top-nav-link active">📜 History</a>
        <a href="/radar" class="top-nav-link">🚨 Radar</a>
        <a href="/bitcoin-scanner" class="top-nav-link">₿ Bitcoin</a>
        <a href="/forex-sessions" class="top-nav-link">🌐 Forex</a>
        <a href="/fundamentals" class="top-nav-link">📋 Fundamentals</a>
        <span class="top-nav-spacer"></span>
        <button class="top-nav-logout" onclick="logout()">Sign out</button>
    </nav>
    <div class="page-wrapper medium">
        <div class="page-header">
            <div class="page-header-left">
                <div class="page-eyebrow">History</div>
                <h1 class="page-title">Triggered Alerts</h1>
                <p class="page-subtitle">All alerts that have fired, with AI market insights</p>
            </div>
        </div>
        <div id="historyList">
            <div class="loading">Loading history...</div>
        </div>
    </div>

    <script>
        async function loadHistory() {
            const container = document.getElementById('historyList');
            try {
                const res = await fetch('/api/alerts/history');
                const data = await res.json();

                if (!data.success || data.history.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">📜</div>
                            <div class="empty-state-title">No History Yet</div>
                            <div class="empty-state-text">Triggered alerts will appear here once your price targets are hit.</div>
                        </div>`;
                    return;
                }

                container.innerHTML = data.history.map(record => {
                    const date = new Date(record.triggered_at).toLocaleString('en-US', {
                        month: 'short', day: 'numeric', year: 'numeric',
                        hour: '2-digit', minute: '2-digit'
                    });
                    const price = record.price_at_trigger?.toFixed(2) || 'N/A';

                    return `
                        <div class="history-card">
                            <div class="history-card-header">
                                <div>
                                    <div class="history-card-ticker">${record.ticker}</div>
                                    <div class="history-card-price">Triggered at <span style="color:var(--accent);">$${price}</span></div>
                                </div>
                                <div style="text-align:right;">
                                    <div class="history-card-time">${date}</div>
                                    <span class="badge badge-positive" style="margin-top:6px;">Fired</span>
                                </div>
                            </div>
                            ${record.explanation ? `
                            <div class="ai-insight">
                                <div class="ai-insight-label">🤖 AI Insight</div>
                                ${record.explanation}
                            </div>` : ''}
                        </div>`;
                }).join('');

            } catch (error) {
                console.error('Error loading history:', error);
                container.innerHTML = '<div class="empty">Failed to load history</div>';
            }
        }

        async function logout() {
            await fetch('/api/logout');
            window.location.href = '/login';
        }

        loadHistory();
    </script>
    <script src="/static/js/nav-mobile.js"></script>
</body>
</html>
    """
    return render_template_string(html)

@app.route('/radar')
@login_required
def radar_page():
    """Market anomaly radar page"""
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Market Radar — PulseAlerts</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="/static/css/theme.css">
    <style>
        body { padding: 0; }
        .anomaly-card {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-radius: var(--r-lg);
            padding: 20px 20px 20px 23px;
            margin-bottom: 10px;
            position: relative; overflow: hidden;
            transition: border-color 0.15s, box-shadow 0.15s;
        }
        .anomaly-card::before {
            content: ''; position: absolute; top: 0; left: 0;
            width: 3px; height: 100%;
            background: var(--accent);
        }
        .anomaly-card.high::before   { background: var(--negative); }
        .anomaly-card.medium::before { background: var(--warning); }
        .anomaly-card.low::before    { background: var(--positive); }
        .anomaly-card:hover { border-color: var(--border); box-shadow: var(--shadow-sm); }
    </style>
</head>
<body>
    <nav class="top-nav">
        <span class="top-nav-brand">📈 PulseAlerts</span>
        <a href="/dashboard" class="top-nav-link">📊 Alerts</a>
        <a href="/portfolio" class="top-nav-link">💼 Portfolio</a>
        <a href="/alerts/history" class="top-nav-link">📜 History</a>
        <a href="/radar" class="top-nav-link active">🚨 Radar</a>
        <a href="/bitcoin-scanner" class="top-nav-link">₿ Bitcoin</a>
        <a href="/forex-sessions" class="top-nav-link">🌐 Forex</a>
        <a href="/fundamentals" class="top-nav-link">📋 Fundamentals</a>
        <span class="top-nav-spacer"></span>
        <button class="top-nav-logout" onclick="logout()">Sign out</button>
    </nav>
    <div class="page-wrapper medium">
        <div class="page-header">
            <div class="page-header-left">
                <div class="page-eyebrow">Surveillance</div>
                <h1 class="page-title">Market Radar</h1>
                <p class="page-subtitle">Real-time anomaly detection across your watchlist</p>
            </div>
        </div>
        <div id="radarList">
            <div class="loading">Scanning for anomalies...</div>
        </div>
    </div>

    <script>
        async function loadRadar() {
            const container = document.getElementById('radarList');
            try {
                const res = await fetch('/api/radar');
                const data = await res.json();

                if (!data.success || data.anomalies.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">🔍</div>
                            <div class="empty-state-title">All Clear</div>
                            <div class="empty-state-text">No unusual market activity detected right now.</div>
                        </div>`;
                    return;
                }

                container.innerHTML = data.anomalies.map(anomaly => {
                    const metrics = anomaly.metrics || {};
                    const date = new Date(anomaly.detected_at).toLocaleString('en-US', {
                        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                    });
                    const sevBadge = anomaly.severity === 'high' ? 'badge-negative'
                                   : anomaly.severity === 'medium' ? 'badge-warning' : 'badge-positive';

                    return `
                        <div class="anomaly-card ${anomaly.severity || ''}">
                            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;">
                                <div>
                                    <span style="font-size:19px;font-weight:800;letter-spacing:-0.3px;">${anomaly.ticker}</span>
                                    <span class="badge ${sevBadge}" style="margin-left:8px;">${anomaly.severity || 'signal'}</span>
                                </div>
                                <span style="font-size:12px;color:var(--text-secondary);">${date}</span>
                            </div>
                            ${anomaly.anomaly_type === 'BIG_MOVE' ? `
                            <div style="font-size:14px;color:var(--text-secondary);">
                                Price moved <strong style="color:${metrics.direction === 'up' ? 'var(--positive)' : 'var(--negative)'};">
                                ${metrics.pct_change > 0 ? '+' : ''}${metrics.pct_change?.toFixed(2)}%
                                </strong> to <strong>$${metrics.current_price?.toFixed(2)}</strong>
                            </div>` : `<div style="font-size:13px;color:var(--text-secondary);">${anomaly.anomaly_type}</div>`}
                        </div>`;
                }).join('');

            } catch (error) {
                console.error('Error loading radar:', error);
                container.innerHTML = '<div class="empty">Failed to load radar data</div>';
            }
        }

        async function logout() {
            await fetch('/api/logout');
            window.location.href = '/login';
        }

        loadRadar();
        setInterval(loadRadar, 60000);
    </script>
    <script src="/static/js/nav-mobile.js"></script>
</body>
</html>
    """
    return render_template_string(html)

# ============================================
# SESSION BREAK ALERT ROUTES
# (replaces former Forex AMD routes)
# ============================================

# Legacy redirect: keep /forex-amd working
@app.route('/forex-amd')
@login_required
def forex_amd_redirect():
    return redirect(url_for('session_break_page'), code=301)


@app.route('/forex-sessions')
@login_required
def session_break_page():
    """Session Break Confirmation alert page (Asia + London)."""
    html = """
<!DOCTYPE html>
<html>
<head>
    <title>Session Break Alerts</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://unpkg.com/lightweight-charts@4/dist/lightweight-charts.standalone.production.js"></script>
    <link rel="stylesheet" href="/static/css/theme.css">
    <style>
        /* Forex Sessions page — minimal page-specific styles */
        .section { background: var(--bg-card); border: 1px solid var(--border-card); border-radius: var(--r-lg); padding: var(--sp-5); margin-bottom: var(--sp-4); }
        .section-title { font-size: 16px; font-weight: 700; margin-bottom: var(--sp-4); letter-spacing: -0.2px; }
        .alert-card { background: var(--bg-surface); border: 1px solid var(--border-card); border-radius: var(--r-md); padding: var(--sp-4); margin-bottom: var(--sp-3); }
        .alert-card.up   { border-left: 3px solid var(--positive); }
        .alert-card.down { border-left: 3px solid var(--negative); }
        .session-badge { display: inline-block; padding: 3px 10px; border-radius: 99px; font-size: 11px; font-weight: 700; background: rgba(91,124,255,0.15); color: var(--accent); }
        select.chart-select { padding: 8px 12px; border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--bg-surface); color: var(--text-primary); font-size: 13px; cursor: pointer; font-family: inherit; }
        #sb-chart { border-radius: var(--r-md); overflow: hidden; position: relative; }
        #chart-error { color: var(--negative); font-size: 13px; margin-top: 8px; display: none; }
        .mode-btn { padding: 6px 14px; font-size: 12px; font-weight: 600; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-surface); color: var(--text-muted); cursor: pointer; transition: background 0.15s, color 0.15s; font-family: inherit; }
        .mode-btn.active { background: var(--accent); color: #fff; border-color: transparent; }
        .mode-btn:hover:not(.active) { background: rgba(255,255,255,0.1); color: var(--text-primary); }
        .setup-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 24px; color: var(--text-muted); font-size: 13px; line-height: 1.7; }
        .watchlist-tag { display: inline-flex; align-items: center; gap: 8px; margin: 4px; padding: 6px 14px; background: var(--bg-surface); border: 1px solid var(--border-card); border-radius: var(--r-sm); font-size: 13px; font-weight: 600; }
        .watchlist-tag-remove { padding: 2px 7px; font-size: 11px; background: rgba(255,71,87,0.15); color: var(--negative); border: none; border-radius: 4px; cursor: pointer; font-family: inherit; }
        .chart-legend { margin-top: 10px; font-size: 12px; color: var(--text-muted); line-height: 2; }
        /* ── Mobile ── */
        @media (max-width: 768px) {
            .section { padding: var(--sp-4); }
            .setup-grid { grid-template-columns: 1fr; gap: 4px 0; }
            #sb-chart { height: 320px !important; }
        }
        @media (max-width: 480px) {
            #sb-chart { height: 260px !important; }
        }
    </style>
</head>
<body>
    <nav class="top-nav">
        <span class="top-nav-brand">📈 PulseAlerts</span>
        <a href="/dashboard" class="top-nav-link">📊 Alerts</a>
        <a href="/portfolio" class="top-nav-link">💼 Portfolio</a>
        <a href="/alerts/history" class="top-nav-link">📜 History</a>
        <a href="/radar" class="top-nav-link">🚨 Radar</a>
        <a href="/bitcoin-scanner" class="top-nav-link">₿ Bitcoin</a>
        <a href="/forex-sessions" class="top-nav-link active">🌐 Forex</a>
        <a href="/fundamentals" class="top-nav-link">📋 Fundamentals</a>
        <span class="top-nav-spacer"></span>
        <button class="top-nav-logout" onclick="logout()">Sign out</button>
    </nav>
    <div class="page-wrapper">
        <div class="page-header" style="margin-bottom: var(--sp-6);">
            <div class="page-eyebrow">Forex</div>
            <h1 class="page-title">Session Break Alerts</h1>
            <p class="page-subtitle">Asia (00:00–09:00 UTC) &amp; London (08:00–17:00 UTC) — wick-only break detection on 5M candles</p>
        </div>

        <div class="section">
            <div class="section-title">Watchlist</div>
            <div style="display:flex;gap:var(--sp-3);margin-bottom:var(--sp-4);flex-wrap:wrap;">
                <input type="text" id="symbolInput" placeholder="Add symbol (e.g., EURUSD or XAU/USD)" class="form-input" style="flex:1;min-width:200px;">
                <button class="btn btn-primary" onclick="addSymbol()">Add Symbol</button>
            </div>
            <div id="watchlistContainer"></div>
        </div>

        <div class="section">
            <div class="section-title">Session Break Alerts</div>
            <div id="alertsContainer">
                <div class="loading">Loading alerts...</div>
            </div>
        </div>

        <div class="section" id="chart-section">
            <!-- ── Mode selector row ── -->
            <div style="display:flex;align-items:center;gap:var(--sp-3);margin-bottom:var(--sp-4);flex-wrap:wrap;">
                <div class="section-title" style="margin:0;">Chart (5M)</div>
                <select id="chartSymbolSelect" class="chart-select" onchange="onSymbolChange()">
                    <option value="">-- Select symbol --</option>
                </select>
                <div id="mode-btn-group" style="display:flex;gap:6px;">
                    <button class="mode-btn active" data-mode="current"
                            onclick="setMode('current')">Current</button>
                    <button class="mode-btn" data-mode="last_triggered"
                            onclick="setMode('last_triggered')">Last Triggered</button>
                    <button class="mode-btn" data-mode="date"
                            onclick="setMode('date')">Pick Date</button>
                </div>
                <!-- Date picker (visible only in Pick Date mode) -->
                <div id="date-picker-row" style="display:none;align-items:center;gap:8px;">
                    <input type="date" id="pickDate" class="chart-select"
                           style="padding:6px 10px;">
                    <select id="pickSessionType" class="chart-select">
                        <option value="asia">Asia</option>
                        <option value="london">London</option>
                    </select>
                    <button class="btn btn-primary" onclick="loadOverlays()"
                            style="padding:6px 14px;font-size:13px;">Load</button>
                </div>
            </div>
            <!-- ── Chart canvas ── -->
            <div id="sb-chart" style="height:440px;width:100%;"></div>
            <div id="chart-error"></div>
            <!-- ── Setup Card ── -->
            <div id="setup-card" style="display:none;margin-top:var(--sp-4);padding:var(--sp-4);
                 background:var(--bg-surface);border:1px solid var(--border-card);
                 border-radius:var(--r-md);font-size:13px;"></div>
            <!-- ── Legend ── -->
            <div class="chart-legend">
                <span style="color:#FFB800;">&#9472;&#9472;</span> Sess H &nbsp;
                <span style="color:#5B7CFF;">&#9472;&#9472;</span> Sess L &nbsp;
                <span style="color:#00D4AA;">&#9472;&#9472;</span> Sweep Level &nbsp;
                <span style="color:#FF9F43;">&#9472;&#9472;</span> Confirm &nbsp;
                <span style="color:#00FFA3;">&#9650;</span> UP &nbsp;
                <span style="color:#FF6B6B;">&#9660;</span> DOWN
            </div>
        </div>
    </div>

    <script>
        // ── Watchlist ────────────────────────────────────────────────────────
        async function loadWatchlist() {
            const res = await fetch('/api/session-break/watchlist');
            const data = await res.json();
            const container = document.getElementById('watchlistContainer');
            if (!data.symbols || data.symbols.length === 0) {
                container.innerHTML = '<p style="color:#8B92A8;">No symbols in watchlist. Add some above.</p>';
            } else {
                container.innerHTML = data.symbols.map(s => `
                    <span class="watchlist-tag">
                        ${s}
                        <button class="watchlist-tag-remove" onclick="removeSymbol('${s}')" title="Remove">&#x2715;</button>
                    </span>
                `).join('');
            }
            updateChartSymbolSelect(data.symbols || []);
        }

        async function removeSymbol(symbol) {
            await fetch('/api/session-break/watchlist', {
                method: 'DELETE',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({symbol})
            });
            loadWatchlist();
        }

        async function addSymbol() {
            const input = document.getElementById('symbolInput');
            const symbol = input.value.trim().toUpperCase();
            if (!symbol) return;
            const res = await fetch('/api/session-break/watchlist', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({symbol})
            });
            const data = await res.json();
            if (!data.success) {
                alert('Error: ' + (data.error || 'Unknown error'));
                return;
            }
            input.value = '';
            loadWatchlist();
        }

        // ── Alerts ───────────────────────────────────────────────────────────
        async function loadAlerts() {
            const res = await fetch('/api/session-break/alerts');
            const data = await res.json();
            const container = document.getElementById('alertsContainer');
            if (!data.alerts || data.alerts.length === 0) {
                container.innerHTML = '<div style="text-align:center;padding:40px;color:#8B92A8;">No session break alerts triggered yet</div>';
                return;
            }
            container.innerHTML = data.alerts.map(a => {
                const dirClass = a.direction === 'UP' ? 'up' : 'down';
                const dirColor = a.direction === 'UP' ? '#00FFA3' : '#FF6B6B';
                const dt = new Date(a.triggered_at).toLocaleString();
                const fb = a.first_break_level ? parseFloat(a.first_break_level).toFixed(5) : '—';
                const cb = a.confirm_break_level ? parseFloat(a.confirm_break_level).toFixed(5) : '—';
                const sh = a.session_high ? parseFloat(a.session_high).toFixed(5) : '—';
                const sl = a.session_low  ? parseFloat(a.session_low).toFixed(5)  : '—';
                return `
                    <div class="alert-card ${dirClass}">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                            <span style="font-size:20px;font-weight:700;">${a.symbol}</span>
                            <span class="session-badge">${a.session_type.toUpperCase()} / ${a.session_date}</span>
                        </div>
                        <div style="margin-bottom:8px;">
                            <strong style="color:${dirColor};">${a.direction}</strong>
                            &nbsp;Session Break Confirmed
                        </div>
                        <div style="font-size:13px;color:#8B92A8;line-height:1.8;">
                            Session High: <strong>${sh}</strong> &nbsp;|&nbsp; Session Low: <strong>${sl}</strong><br>
                            First Break: <strong>${fb}</strong> @ ${a.first_break_ts ? new Date(a.first_break_ts).toLocaleTimeString() : '—'}<br>
                            Confirm Break: <strong>${cb}</strong> @ ${a.confirm_break_ts ? new Date(a.confirm_break_ts).toLocaleTimeString() : '—'}
                        </div>
                        <div style="font-size:12px;color:#666;margin-top:8px;">Triggered: ${dt}</div>
                    </div>
                `;
            }).join('');
        }

        async function logout() {
            await fetch('/api/logout');
            window.location.href = '/login';
        }

        // ── Chart state ──────────────────────────────────────────────────────
        let _chart = null, _candleSeries = null, _overlayMode = 'current';
        let _sessionBoxState = null;  // {fromTs, toTs, high, low} – redrawn on scroll/zoom

        const COLORS = {
            sessionHigh:  '#FFB800',
            sessionLow:   '#5B7CFF',
            sweepLevel:   '#00D4AA',
            confirmLevel: '#FF9F43',
            up:           '#00FFA3',
            down:         '#FF6B6B',
        };

        // ── OverlayManager ────────────────────────────────────────────────────
        // Tracks every chart object created so we can wipe them all before
        // re-rendering. Prevents stacking of labels / lines across refreshes.
        const OverlayMgr = {
            priceLines: [],
            boxEls:     [],

            clear() {
                this.priceLines.forEach(pl => {
                    try { _candleSeries.removePriceLine(pl); } catch(_) {}
                });
                this.priceLines = [];
                if (_candleSeries) _candleSeries.setMarkers([]);
                this.boxEls.forEach(el => {
                    if (el.parentNode) el.parentNode.removeChild(el);
                });
                this.boxEls = [];
                _sessionBoxState = null;
            },

            addPriceLine(opts) {
                if (!_candleSeries) return;
                this.priceLines.push(_candleSeries.createPriceLine(opts));
            },

            setMarkers(arr) {
                if (!_candleSeries) return;
                _candleSeries.setMarkers(arr.slice().sort((a, b) => a.time - b.time));
            },
        };

        // ── Session box (HTML div positioned over the chart canvas) ───────────
        // drawSessionBox() stores the logical state; _renderSessionBox() converts
        // to pixel coords and redraws. _renderSessionBox is called on every
        // scroll/zoom/resize so the rectangle always tracks the viewport.
        function drawSessionBox(fromTs, toTs, high, low) {
            _sessionBoxState = { fromTs, toTs, high, low };
            _renderSessionBox();
        }

        function _renderSessionBox() {
            // Remove any existing box elements
            OverlayMgr.boxEls.forEach(el => { if (el.parentNode) el.parentNode.removeChild(el); });
            OverlayMgr.boxEls = [];
            if (!_sessionBoxState || !_chart || !_candleSeries) return;
            const { fromTs, toTs, high, low } = _sessionBoxState;
            const el = document.getElementById('sb-chart');
            const x1 = _chart.timeScale().timeToCoordinate(fromTs);
            const x2 = _chart.timeScale().timeToCoordinate(toTs);
            const y1 = _candleSeries.priceToCoordinate(high);
            const y2 = _candleSeries.priceToCoordinate(low);
            if (x1 == null || x2 == null || y1 == null || y2 == null) return;
            const L = Math.min(x1, x2), T = Math.min(y1, y2);
            const W = Math.abs(x2 - x1),  H = Math.abs(y2 - y1);
            if (W < 2 || H < 2) return;
            const box = document.createElement('div');
            box.style.cssText =
                'position:absolute;pointer-events:none;z-index:1;border-radius:2px;' +
                'left:' + L + 'px;top:' + T + 'px;' +
                'width:' + W + 'px;height:' + H + 'px;' +
                'background:rgba(91,124,255,0.09);' +
                'border:1px solid rgba(91,124,255,0.28);';
            el.appendChild(box);
            OverlayMgr.boxEls.push(box);
        }

        // ── Setup Card helpers ────────────────────────────────────────────────
        function fmt(v, dp) {
            return (v != null) ? parseFloat(v).toFixed(dp != null ? dp : 5) : '\u2014';
        }
        function fmtTs(iso) {
            if (!iso) return '\u2014';
            const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
            return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
        }
        function fmtIL(iso) {
            if (!iso) return '';
            try {
                const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
                return d.toLocaleString('he-IL', {
                    timeZone: 'Asia/Jerusalem',
                    year: 'numeric', month: '2-digit', day: '2-digit',
                    hour: '2-digit', minute: '2-digit',
                });
            } catch(_) { return ''; }
        }

        // ── Setup Card renderer ───────────────────────────────────────────────
        function renderSetupCard(setup) {
            const card = document.getElementById('setup-card');
            if (!setup || setup.status === 'NO_SETUP') {
                card.style.display = 'none';
                card.innerHTML = '';
                return;
            }
            const STATUS_COLOR = {
                WAIT_SWEEP:   '#8B92A8',
                IN_SWEEP:     '#FFB800',
                WAIT_CONFIRM: '#FF9F43',
                TRIGGERED:    '#00FFA3',
            };
            const sc  = STATUS_COLOR[setup.status] || '#8B92A8';
            const dir = setup.sweep && setup.sweep.direction;
            const dc  = dir === 'DOWN' ? COLORS.down : COLORS.up;
            const sLbl = ((setup.session_type || '').toUpperCase()) + ' \u00b7 ' + (setup.session_date || '');

            let html =
                '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">' +
                  '<span style="font-size:15px;font-weight:700;">' + (setup.symbol || '') +
                    ' <span class="session-badge">' + sLbl + '</span></span>' +
                  '<span style="color:' + sc + ';font-weight:700;">' + setup.status + '</span>' +
                '</div>' +
                '<div class="setup-grid">' +
                  '<span>Session High: <strong style="color:#FFB800;">' + fmt(setup.session_high) + '</strong></span>' +
                  '<span>Session Low: <strong style="color:#5B7CFF;">' + fmt(setup.session_low) + '</strong></span>';

            if (dir) {
                const sl = setup.sweep;
                html += '<span>Direction: <strong style="color:' + dc + ';">' + dir + '</strong></span>';
                html += '<span>Sweep Level: <strong style="color:#00D4AA;">' + fmt(sl.first_sweep_level) + '</strong></span>';
                if (sl.sweep_start_ts)
                    html += '<span>Sweep Start: <strong>' + fmtTs(sl.sweep_start_ts) + '</strong></span><span></span>';
                if (sl.sweep_end_ts)
                    html += '<span>Re-entry: <strong>' + fmtTs(sl.sweep_end_ts) + '</strong></span><span></span>';
            }
            if (setup.confirm) {
                const c = setup.confirm;
                html += '<span>Confirm Level: <strong style="color:#FF9F43;">' + fmt(c.confirm_break_level) + '</strong></span>';
                html += '<span>Confirm Time: <strong>' + fmtTs(c.confirm_break_ts) + '</strong></span>';
            }
            if (setup.trigger) {
                const t = setup.trigger;
                html += '<span style="color:#00FFA3;font-weight:600;">Trigger (UTC): <strong>' + fmtTs(t.trigger_ts) + '</strong></span>';
                html += '<span style="color:#00FFA3;font-weight:600;">Trigger (IL): <strong>' + fmtIL(t.trigger_ts) + '</strong></span>';
            }
            html += '</div>';

            card.innerHTML = html;
            card.style.display = 'block';
            card.style.borderLeft = '4px solid ' + (setup.status === 'TRIGGERED' ? dc : sc);
        }

        // ── Chart init ────────────────────────────────────────────────────────
        function initChart() {
            const el = document.getElementById('sb-chart');
            if (!el || typeof LightweightCharts === 'undefined') return;
            const chartHeight = window.innerWidth <= 480 ? 260 : window.innerWidth <= 768 ? 320 : 440;
            _chart = LightweightCharts.createChart(el, {
                width: el.clientWidth,
                height: chartHeight,
                layout: { background: { color: '#0d1117' }, textColor: '#8B92A8' },
                grid: {
                    vertLines: { color: 'rgba(255,255,255,0.04)' },
                    horzLines: { color: 'rgba(255,255,255,0.04)' },
                },
                crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
                rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
                timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: true, secondsVisible: false },
            });
            _candleSeries = _chart.addCandlestickSeries({
                upColor: '#00FFA3', downColor: '#FF6B6B',
                borderUpColor: '#00FFA3', borderDownColor: '#FF6B6B',
                wickUpColor: '#00FFA3', wickDownColor: '#FF6B6B',
            });
            new ResizeObserver(() => {
                if (_chart) _chart.applyOptions({ width: el.clientWidth });
                _renderSessionBox();
            }).observe(el);
            _chart.timeScale().subscribeVisibleLogicalRangeChange(_renderSessionBox);
            _chart.subscribeCrosshairMove(_renderSessionBox);
        }

        function updateChartSymbolSelect(symbols) {
            const sel = document.getElementById('chartSymbolSelect');
            const prev = sel.value;
            sel.innerHTML = '<option value="">-- Select symbol --</option>';
            symbols.forEach(s => {
                const opt = document.createElement('option');
                opt.value = s; opt.textContent = s;
                if (s === prev) opt.selected = true;
                sel.appendChild(opt);
            });
            if (!sel.value && symbols.length) { sel.value = symbols[0]; loadChart(); }
        }

        // ── loadOverlays – fetches ONE setup, clears old drawings, renders fresh
        async function loadOverlays() {
            const sym = document.getElementById('chartSymbolSelect').value;
            if (!sym || !_candleSeries) return;

            // Always clear before rendering – prevents stacked labels
            OverlayMgr.clear();
            document.getElementById('setup-card').style.display = 'none';

            // Build URL with cache-bust so stale data is never served
            let url = '/api/session-sweep/overlay'
                    + '?symbol=' + encodeURIComponent(sym)
                    + '&mode='   + encodeURIComponent(_overlayMode)
                    + '&_t='     + Date.now();
            if (_overlayMode === 'date') {
                const d  = document.getElementById('pickDate').value;
                const st = document.getElementById('pickSessionType').value;
                if (!d) return;
                url += '&date=' + encodeURIComponent(d) + '&session_type=' + encodeURIComponent(st);
            }

            let setup;
            try { const r = await fetch(url); setup = await r.json(); }
            catch(_) { return; }

            if (!setup || setup.status === 'NO_SETUP') {
                renderSetupCard(null);
                return;
            }

            // 1) Session box (shaded rectangle over session candles)
            const sb = setup.session_box;
            if (sb && sb.enabled && setup.session_high != null && setup.session_low != null) {
                drawSessionBox(sb.from_ts, sb.to_ts, setup.session_high, setup.session_low);
            }

            // 2) Price lines (session H/L, sweep level, confirm level)
            const LS = LightweightCharts.LineStyle;
            const lineStyleMap = {
                session_high:      LS.Dashed,
                session_low:       LS.Dashed,
                first_sweep_level: LS.Solid,
                confirm_level:     LS.Dotted,
            };
            const colorMap = {
                sessionHigh:  COLORS.sessionHigh,
                sessionLow:   COLORS.sessionLow,
                sweepLevel:   COLORS.sweepLevel,
                confirmLevel: COLORS.confirmLevel,
            };
            const titleMap = {
                session_high:      'Sess H',
                session_low:       'Sess L',
                first_sweep_level: 'Sweep',
                confirm_level:     'Confirm',
            };
            (setup.levels_to_draw || []).forEach(l => {
                OverlayMgr.addPriceLine({
                    price:            l.price,
                    color:            colorMap[l.color_key] || '#888',
                    lineWidth:        l.type === 'first_sweep_level' ? 2 : 1,
                    lineStyle:        lineStyleMap[l.type] != null ? lineStyleMap[l.type] : LS.Dotted,
                    axisLabelVisible: true,
                    title:            titleMap[l.type] || l.type,
                });
            });

            // 3) Markers (SWEEP, RE-ENTRY, CONFIRM, TRIGGER)
            const dir = setup.sweep && setup.sweep.direction;
            const isUp = dir === 'UP';
            const mColorMap = {
                'SWEEP':    COLORS.sweepLevel,
                'RE-ENTRY': '#FFB800',
                'CONFIRM':  COLORS.confirmLevel,
                'TRIGGER':  isUp ? COLORS.up : COLORS.down,
            };
            const markers = (setup.markers || []).map(m => ({
                time:     m.ts,
                position: m.position || (isUp ? 'belowBar' : 'aboveBar'),
                color:    mColorMap[m.text] || '#888',
                shape:    m.shape || (isUp ? 'arrowUp' : 'arrowDown'),
                text:     m.text,
            }));
            if (markers.length) OverlayMgr.setMarkers(markers);

            // 4) Setup Card
            renderSetupCard(setup);
        }

        // ── Mode selector ─────────────────────────────────────────────────────
        function setMode(mode) {
            _overlayMode = mode;
            document.querySelectorAll('.mode-btn').forEach(b =>
                b.classList.toggle('active', b.dataset.mode === mode));
            document.getElementById('date-picker-row').style.display =
                mode === 'date' ? 'flex' : 'none';
            if (mode !== 'date') loadOverlays();
        }

        function onSymbolChange() { loadChart(); }

        // ── loadChart – fetches candles then overlays ─────────────────────────
        async function loadChart() {
            const sym = document.getElementById('chartSymbolSelect').value;
            const errEl = document.getElementById('chart-error');
            errEl.style.display = 'none';
            if (!sym) return;
            if (!_chart) initChart();
            if (!_chart) {
                errEl.textContent = 'LightweightCharts library not loaded.';
                errEl.style.display = 'block';
                return;
            }
            try {
                const res = await fetch(
                    '/api/session-break/candles?symbol=' + encodeURIComponent(sym)
                    + '&limit=288&_t=' + Date.now()
                );
                const data = await res.json();
                if (data.error) throw new Error(data.error);
                _candleSeries.setData(data);
                _chart.timeScale().fitContent();
                await loadOverlays();
            } catch(e) {
                errEl.textContent = 'Chart error: ' + e.message;
                errEl.style.display = 'block';
            }
        }

        // ── Boot ─────────────────────────────────────────────────────────────
        loadWatchlist();
        loadAlerts();
        setInterval(loadAlerts, 60000);
    </script>
    <script src="/static/js/nav-mobile.js"></script>
</body>
</html>
    """
    return render_template_string(html)


@app.route('/api/session-break/watchlist', methods=['GET', 'POST', 'DELETE'])
@login_required
def manage_session_break_watchlist():
    """Manage user's forex watchlist for session break alerts."""
    if request.method == 'POST':
        raw_symbol = request.json.get('symbol', '').strip()
        if not raw_symbol:
            return jsonify({'success': False, 'error': 'Symbol required'}), 400

        from services.forex_data_provider import normalize_symbol
        symbol, norm_err = normalize_symbol(raw_symbol)
        if norm_err:
            return jsonify({'success': False, 'error': norm_err}), 400

        try:
            db.execute(
                """
                INSERT INTO forex_watchlist (user_id, symbol)
                VALUES (%s, %s)
                ON CONFLICT (user_id, symbol) DO NOTHING
                """,
                (current_user.id, symbol),
            )
            return jsonify({'success': True, 'symbol': symbol})
        except Exception as e:
            logger.error(f"[SESSION_BREAK] watchlist add error: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    elif request.method == 'DELETE':
        symbol = request.json.get('symbol')
        db.execute(
            "DELETE FROM forex_watchlist WHERE user_id = %s AND symbol = %s",
            (current_user.id, symbol),
        )
        return jsonify({'success': True})

    else:  # GET
        watchlist = db.execute(
            "SELECT symbol FROM forex_watchlist WHERE user_id = %s ORDER BY added_at DESC",
            (current_user.id,),
            fetchall=True,
        )
        return jsonify({
            'success': True,
            'symbols': [w['symbol'] for w in watchlist] if watchlist else [],
        })


# Keep legacy endpoint working (old clients may call it)
@app.route('/api/forex-amd/watchlist', methods=['GET', 'POST', 'DELETE'])
@login_required
def manage_forex_watchlist_legacy():
    """Legacy alias – delegates to session break watchlist."""
    return manage_session_break_watchlist()


@app.route('/api/session-break/alerts')
@login_required
def get_session_break_alerts():
    """Get user's session break alert history (last 50 triggers)."""
    try:
        rows = db.execute(
            """
            SELECT symbol, session_type, session_date, direction,
                   session_high, session_low,
                   first_break_ts, first_break_level,
                   confirm_break_ts, confirm_break_level,
                   triggered_at
            FROM session_break_history
            WHERE user_id = %s
            ORDER BY triggered_at DESC
            LIMIT 50
            """,
            (current_user.id,),
            fetchall=True,
        )
        alerts = []
        for r in (rows or []):
            d = dict(r)
            for k in ('first_break_ts', 'confirm_break_ts', 'triggered_at'):
                if d.get(k):
                    d[k] = d[k].isoformat()
            if d.get('session_date'):
                d['session_date'] = str(d['session_date'])
            alerts.append(d)
        return jsonify({'success': True, 'alerts': alerts})
    except Exception as e:
        logger.error(f"[SESSION_BREAK] alerts endpoint error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session-break/health')
@login_required
def session_break_health():
    """Session Break scanner health – last run timestamps + error info."""
    try:
        from datetime import datetime, timezone
        from services.session_break_detector import SessionBreakConfig
        row = db.execute(
            "SELECT * FROM session_break_health WHERE id = 1",
            fetchone=True,
        )
        threshold_min = SessionBreakConfig.UNHEALTHY_THRESHOLD_MINUTES
        healthy = False
        age_min = None
        if row and row.get('last_ok_at'):
            last_ok = row['last_ok_at']
            if last_ok.tzinfo is None:
                last_ok = last_ok.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - last_ok).total_seconds() / 60
            healthy = age_min <= threshold_min
        return jsonify({
            'success':            True,
            'healthy':            healthy,
            'threshold_minutes':  threshold_min,
            'age_minutes':        round(age_min, 1) if age_min is not None else None,
            'last_run_at':    row['last_run_at'].isoformat()    if row and row['last_run_at']    else None,
            'last_ok_at':     row['last_ok_at'].isoformat()     if row and row['last_ok_at']     else None,
            'last_error_at':  row['last_error_at'].isoformat()  if row and row['last_error_at']  else None,
            'last_error_msg': row['last_error_msg']             if row else None,
            'last_symbols_count': row['last_symbols_count']     if row else 0,
        })
    except Exception as e:
        logger.error(f"[SESSION_BREAK] health endpoint error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session-break/state')
@login_required
def session_break_state_snapshot():
    """Current session-break state per (symbol, session_type, session_date)."""
    try:
        rows = db.execute(
            """
            SELECT symbol, session_type, session_date, state, direction,
                   session_high, session_low, first_break_ts, first_break_level,
                   triggered_at, updated_at
            FROM session_break_state
            WHERE user_id = %s
            ORDER BY session_date DESC, symbol, session_type
            LIMIT 100
            """,
            (current_user.id,),
            fetchall=True,
        )
        states = []
        for r in (rows or []):
            d = dict(r)
            for k in ('first_break_ts', 'triggered_at', 'updated_at'):
                if d.get(k):
                    d[k] = d[k].isoformat()
            if d.get('session_date'):
                d['session_date'] = str(d['session_date'])
            states.append(d)
        return jsonify({'success': True, 'states': states, 'count': len(states)})
    except Exception as e:
        logger.error(f"[SESSION_BREAK] state endpoint error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# In-memory candle cache: cache_key -> (monotonic_timestamp, data_list)
# ---------------------------------------------------------------------------
_candle_cache: dict = {}
_CANDLE_CACHE_TTL = 60  # seconds


@app.route('/api/session-break/candles')
@login_required
def session_break_candles():
    """OHLC 5M candles for LightweightCharts (sourced from TradingView PEPPERSTONE).
    GET /api/session-break/candles?symbol=EURUSD&limit=288
    Returns [{time, open, high, low, close}, …] ascending.
    """
    from services.tradingview_provider import tradingview_provider

    symbol = request.args.get('symbol', '').strip().upper()
    try:
        limit = min(int(request.args.get('limit', 288)), 576)
    except ValueError:
        limit = 288

    if not symbol:
        return jsonify({'error': 'symbol required'}), 400

    cache_key = f"{symbol}:5m:tv"
    now_mono = time.monotonic()
    cached = _candle_cache.get(cache_key)
    if cached and (now_mono - cached[0]) < _CANDLE_CACHE_TTL:
        return jsonify(cached[1])

    candles = tradingview_provider.get_candles(symbol, count=limit)
    if not candles:
        return jsonify({'error': f'No candle data available for {symbol}'}), 404

    result = sorted(
        [
            {
                'time':  int(c['timestamp'].timestamp()),
                'open':  c['open'],
                'high':  c['high'],
                'low':   c['low'],
                'close': c['close'],
            }
            for c in candles
        ],
        key=lambda x: x['time'],
    )
    _candle_cache[cache_key] = (now_mono, result)
    return jsonify(result)


@app.route('/api/session-break/overlay')
@login_required
def session_break_overlay():
    """Session-break overlay data for chart annotations.
    GET /api/session-break/overlay?symbol=EURUSD
    Returns recent session states (session_high/low, first_break, trigger).
    """
    symbol = request.args.get('symbol', '').strip().upper()
    if not symbol:
        return jsonify({'error': 'symbol required'}), 400

    try:
        rows = db.execute(
            """
            SELECT session_type, session_date, state, direction,
                   session_high, session_low,
                   first_break_ts, first_break_level,
                   confirm_break_ts, triggered_at
            FROM session_break_state
            WHERE user_id = %s AND symbol = %s
            ORDER BY session_date DESC, session_type
            LIMIT 10
            """,
            (current_user.id, symbol),
            fetchall=True,
        )
        sessions = []
        for r in (rows or []):
            d = dict(r)
            for k in ('first_break_ts', 'confirm_break_ts', 'triggered_at'):
                if d.get(k):
                    d[k] = d[k].isoformat()
            if d.get('session_date'):
                d['session_date'] = str(d['session_date'])
            sessions.append(d)
        return jsonify({'success': True, 'symbol': symbol, 'sessions': sessions})
    except Exception as e:
        logger.error(f"[SESSION_BREAK] overlay endpoint error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/forex-sessions/debug')
@login_required
def session_break_debug_page():
    """Read-only session break debug / monitoring page."""
    html = """<!DOCTYPE html>
<html>
<head>
  <title>Session Break Debug</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link rel="stylesheet" href="/static/css/theme.css">
  <style>
    body { font-family: monospace; }
    h2   { color:#5B7CFF; margin-bottom:16px; }
    h3   { color:#8B92A8; font-size:14px; margin-bottom:10px; }
    .debug-card { background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.1);
           border-radius:10px; padding:16px; margin-bottom:16px; }
    .ok   { color:#00FFA3; }
    .err  { color:#FF6B6B; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th,td { text-align:left; padding:6px 10px; border-bottom:1px solid rgba(255,255,255,.07); }
    th    { color:#5B7CFF; }
    pre   { white-space:pre-wrap; font-size:12px; color:#aaa; }
    .debug-content { max-width:1200px; margin:0 auto; padding:80px 20px 40px; }
    .refresh-note { font-size:11px; color:#8B92A8; margin-left:auto; }
  </style>
</head>
<body>
  <nav class="top-nav">
    <span class="top-nav-brand">📈 PulseAlerts</span>
    <a href="/dashboard" class="top-nav-link">📊 Alerts</a>
    <a href="/portfolio" class="top-nav-link">💼 Portfolio</a>
    <a href="/forex-sessions" class="top-nav-link active">🌐 Forex</a>
    <a href="/fundamentals" class="top-nav-link">📋 Fundamentals</a>
    <span class="top-nav-spacer"></span>
    <button class="top-nav-logout" onclick="logout()">Sign out</button>
  </nav>
  <div class="debug-content">
    <div style="margin-bottom:20px;display:flex;align-items:center;gap:16px;">
      <h2 style="margin-bottom:0">Session Break Debug Dashboard</h2>
      <span class="refresh-note" id="last-refresh"></span>
    </div>

    <div class="debug-card">
      <h3>Scanner Health</h3>
      <pre id="health-data">Loading...</pre>
    </div>

    <div class="debug-card">
      <h3>Current States</h3>
      <table>
        <thead><tr>
          <th>Symbol</th><th>Session</th><th>Date</th><th>State</th>
          <th>Direction</th><th>Session H/L</th><th>First Break</th><th>Updated</th>
        </tr></thead>
        <tbody id="state-rows"><tr><td colspan="8">Loading...</td></tr></tbody>
      </table>
    </div>

    <div class="debug-card">
      <h3>Recent Triggers (last 20)</h3>
      <table>
        <thead><tr>
          <th>Symbol</th><th>Session</th><th>Date</th>
          <th>Dir</th><th>First Break</th><th>Confirm</th><th>Triggered At</th>
        </tr></thead>
        <tbody id="event-rows"><tr><td colspan="7">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>

<script>
async function load() {
  try {
    const h = await fetch('/api/session-break/health').then(r => r.json());
    document.getElementById('health-data').textContent = JSON.stringify(h, null, 2);
  } catch(e) { document.getElementById('health-data').textContent = 'Error: ' + e; }

  try {
    const s = await fetch('/api/session-break/state').then(r => r.json());
    document.getElementById('state-rows').innerHTML =
      (s.states && s.states.length)
        ? s.states.map(r =>
            '<tr>' +
            '<td>' + r.symbol + '</td>' +
            '<td>' + r.session_type + '</td>' +
            '<td>' + r.session_date + '</td>' +
            '<td style="color:' + stateColor(r.state) + '">' + (r.state || '—') + '</td>' +
            '<td>' + (r.direction || '—') + '</td>' +
            '<td>' + (r.session_high ? parseFloat(r.session_high).toFixed(5) : '—') + ' / ' +
                     (r.session_low  ? parseFloat(r.session_low).toFixed(5)  : '—') + '</td>' +
            '<td>' + (r.first_break_level ? parseFloat(r.first_break_level).toFixed(5) : '—') + '</td>' +
            '<td>' + (r.updated_at || '—') + '</td>' +
            '</tr>'
          ).join('')
        : '<tr><td colspan="8" style="color:#555">No state records yet</td></tr>';
  } catch(e) {
    document.getElementById('state-rows').innerHTML = '<tr><td colspan="8" class="err">Error: ' + e + '</td></tr>';
  }

  try {
    const ev = await fetch('/api/session-break/alerts').then(r => r.json());
    document.getElementById('event-rows').innerHTML =
      (ev.alerts && ev.alerts.length)
        ? ev.alerts.slice(0, 20).map(e =>
            '<tr>' +
            '<td>' + e.symbol + '</td>' +
            '<td>' + e.session_type + '</td>' +
            '<td>' + e.session_date + '</td>' +
            '<td class="' + (e.direction === 'UP' ? 'ok' : 'err') + '">' + e.direction + '</td>' +
            '<td>' + (e.first_break_level ? parseFloat(e.first_break_level).toFixed(5) : '—') + '</td>' +
            '<td>' + (e.confirm_break_level ? parseFloat(e.confirm_break_level).toFixed(5) : '—') + '</td>' +
            '<td>' + (e.triggered_at || '—') + '</td>' +
            '</tr>'
          ).join('')
        : '<tr><td colspan="7" style="color:#555">No triggers yet</td></tr>';
  } catch(e) {
    document.getElementById('event-rows').innerHTML = '<tr><td colspan="7" class="err">Error: ' + e + '</td></tr>';
  }

  document.getElementById('last-refresh').textContent =
    'Auto-refresh 30s — Last: ' + new Date().toLocaleTimeString();
}

function stateColor(s) {
  const m = {
    POST_SESSION: '#8B92A8',
    WAIT_CONFIRM_UP: '#00FFA3',
    WAIT_CONFIRM_DOWN: '#FF6B6B',
    TRIGGERED: '#FFB800',
  };
  return m[s] || '#ccc';
}

load();
setInterval(load, 30000);

async function logout() {
  await fetch('/api/logout');
  window.location.href = '/login';
}
</script>
<script src="/static/js/nav-mobile.js"></script>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Session Sweep Replay API
# ---------------------------------------------------------------------------

@app.route('/api/session-sweep/replay')
@login_required
def session_sweep_replay():
    """
    Run the Session Liquidity Sweep detector step-by-step on historical
    candles and return a structured event timeline.

    Query parameters
    ----------------
    symbol        required  e.g. EURUSD or XAU/USD
    session_type  required  asia | london
    date          required  YYYY-MM-DD  (Israel local date)
    format        optional  json (default) | table
    show_updates  optional  0 | 1 (default 1) – include SWEEP_UPDATE events
    candles       optional  integer, default 500 (max 1000)

    Returns JSON (or plain-text table) with event timeline.
    """
    from services.session_break_detector import (
        _session_window_utc,
        _session_candles,
        _post_session_candles,
    )
    from services.session_sweep_replay import replay_sweep, render_table
    from services.tradingview_provider import tradingview_provider, normalize_to_tv
    import uuid as _uuid

    # ── parse params ──────────────────────────────────────────────────────
    symbol = request.args.get('symbol', '').strip().upper()
    session_type = request.args.get('session_type', '').strip().lower()
    date_str = request.args.get('date', '').strip()
    output_format = request.args.get('format', 'json').strip().lower()
    show_updates = request.args.get('show_updates', '1').strip() != '0'
    try:
        candle_count = min(int(request.args.get('candles', 500)), 1000)
    except (ValueError, TypeError):
        candle_count = 500

    errors = []
    if not symbol:
        errors.append("'symbol' is required (e.g. EURUSD)")
    if session_type not in ('asia', 'london'):
        errors.append("'session_type' must be 'asia' or 'london'")
    if not date_str:
        errors.append("'date' is required (YYYY-MM-DD)")
    else:
        try:
            from datetime import datetime as _dt
            session_date = _dt.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            errors.append(f"'date' must be YYYY-MM-DD, got '{date_str}'")
            session_date = None

    if errors:
        return jsonify({'success': False, 'errors': errors}), 400

    # ── resolve TradingView symbol for logging / output ────────────────────
    _tv_symbol, _norm_err = normalize_to_tv(symbol)
    if _norm_err:
        return jsonify({'success': False, 'error': f'Symbol error: {_norm_err}'}), 400

    # ── session UTC window ────────────────────────────────────────────────
    try:
        start_utc, end_utc = _session_window_utc(session_type, session_date)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Session window error: {e}'}), 500

    # ── fetch candles (TradingView PEPPERSTONE) ───────────────────────────
    try:
        all_candles = tradingview_provider.get_candles(symbol, count=candle_count)
    except Exception as e:
        logger.error('[SESSION_SWEEP] replay candle fetch error symbol=%s err=%s', symbol, e)
        return jsonify({'success': False, 'error': f'Candle fetch failed: {e}'}), 502

    if not all_candles:
        return jsonify({
            'success': False,
            'error': f'No candles returned for {symbol} '
                     f'(TradingView: PEPPERSTONE:{_tv_symbol}). '
                     'Check symbol spelling and TV_USERNAME/TV_PASSWORD if set.',
        }), 404

    # ── partition ─────────────────────────────────────────────────────────
    ses_candles  = _session_candles(all_candles, start_utc, end_utc)
    post_candles = _post_session_candles(all_candles, end_utc)

    if not ses_candles:
        return jsonify({
            'success': False,
            'error': (
                f'No candles found inside session window '
                f'{start_utc.isoformat()} → {end_utc.isoformat()}. '
                f'Try a more recent date or fetch more candles.'
            ),
            'fetched_candles': len(all_candles),
            'session_start_utc': start_utc.isoformat(),
            'session_end_utc':   end_utc.isoformat(),
        }), 404

    # ── replay ────────────────────────────────────────────────────────────
    run_id = _uuid.uuid4().hex[:12]
    try:
        result = replay_sweep(
            session_candles    = ses_candles,
            post_candles       = post_candles,
            session_type       = session_type,
            session_date       = session_date,
            session_start_utc  = start_utc,
            session_end_utc    = end_utc,
            show_sweep_updates = show_updates,
            run_id             = run_id,
        )
    except Exception as e:
        logger.error('[SESSION_SWEEP] replay engine error symbol=%s err=%s', symbol, e,
                     exc_info=True)
        return jsonify({'success': False, 'error': f'Replay engine error: {e}'}), 500

    result['symbol']          = symbol
    result['fetched_candles'] = len(all_candles)
    result['provider']        = 'TRADINGVIEW'
    result['tv_exchange']     = 'PEPPERSTONE'
    result['tv_symbol']       = _tv_symbol
    if all_candles:
        _fc = all_candles[0]
        _lc = all_candles[-1]
        result['first_fetched_candle'] = {
            'ts':    _fc['timestamp'].isoformat(),
            'open':  _fc['open'],  'high': _fc['high'],
            'low':   _fc['low'],   'close': _fc['close'],
        }
        result['last_fetched_candle'] = {
            'ts':    _lc['timestamp'].isoformat(),
            'open':  _lc['open'],  'high': _lc['high'],
            'low':   _lc['low'],   'close': _lc['close'],
        }

    if output_format == 'table':
        try:
            table_str = render_table(result, show_sweep_updates=show_updates)
        except Exception as e:
            table_str = f'[render error: {e}]'
        return table_str, 200, {'Content-Type': 'text/plain; charset=utf-8'}

    return jsonify({'success': True, **result})


@app.route('/api/session-sweep/reset', methods=['POST'])
@login_required
def session_sweep_reset():
    """
    Dev endpoint: delete session sweep state and history rows matching the
    supplied filters.  Only touches session_break_state and
    session_break_history – no other alert systems are affected.

    Body (all fields optional):
        user_id      integer
        symbol       string   (e.g. "XAUUSD")
        from_date    string   YYYY-MM-DD
        to_date      string   YYYY-MM-DD
        session_type string   asia | london
    """
    import logging as _log
    _rlog = _log.getLogger(__name__)

    body        = request.get_json(silent=True) or {}
    f_user_id   = body.get('user_id')
    f_symbol    = body.get('symbol')
    f_from_date = body.get('from_date')
    f_to_date   = body.get('to_date')
    f_sess_type = body.get('session_type')

    conditions: list = []
    params: list     = []

    if f_user_id is not None:
        conditions.append("user_id = %s")
        params.append(f_user_id)
    if f_symbol is not None:
        conditions.append("symbol = %s")
        params.append(f_symbol.upper())
    if f_from_date is not None:
        conditions.append("session_date >= %s")
        params.append(f_from_date)
    if f_to_date is not None:
        conditions.append("session_date <= %s")
        params.append(f_to_date)
    if f_sess_type is not None:
        conditions.append("session_type = %s")
        params.append(f_sess_type)

    where = (" AND ".join(conditions)) if conditions else "TRUE"

    deleted_state_rows   = db.execute(
        f"DELETE FROM session_break_state   WHERE {where} RETURNING id",
        params, fetchall=True,
    ) or []
    deleted_history_rows = db.execute(
        f"DELETE FROM session_break_history WHERE {where} RETURNING id",
        params, fetchall=True,
    ) or []

    deleted_state   = len(deleted_state_rows)
    deleted_history = len(deleted_history_rows)

    _rlog.info(
        "[SESSION_SWEEP][RESET] user=%s symbol=%s from_date=%s to_date=%s "
        "session_type=%s deleted_state=%d deleted_history=%d",
        f_user_id, f_symbol, f_from_date, f_to_date,
        f_sess_type, deleted_state, deleted_history,
    )

    return jsonify({
        'status':          'ok',
        'deleted_state':   deleted_state,
        'deleted_history': deleted_history,
        'filters': {
            'user_id':      f_user_id,
            'symbol':       f_symbol,
            'from_date':    f_from_date,
            'to_date':      f_to_date,
            'session_type': f_sess_type,
        },
    })


@app.route('/api/session-sweep/overlay')
@login_required
def session_sweep_overlay():
    """
    Return a SINGLE setup object for the chart overlay.

    Query parameters
    ----------------
    symbol       required  e.g. XAUUSD
    mode         optional  current (default) | last_triggered | date
    session_type required when mode=date  asia | london
    date         required when mode=date  YYYY-MM-DD (Israel local date)

    Selection rules
    ---------------
    current       – latest session that is NOT triggered; falls back to the
                    most-recently-updated row if everything is triggered.
    last_triggered – most recently triggered session (triggered_at DESC).
    date          – exact (symbol, session_type, session_date) lookup.

    Returns a single setup object or {status:"NO_SETUP"} when nothing found.
    The response is never cached (caller must add ?_t=… for cache-busting).
    """
    from services.session_break_detector import _session_window_utc
    from datetime import datetime as _dtp

    symbol = request.args.get('symbol', '').strip().upper()
    mode   = request.args.get('mode',   'current').strip().lower()

    if not symbol:
        return jsonify({'error': 'symbol required'}), 400
    if mode not in ('current', 'last_triggered', 'date'):
        return jsonify({'error': "mode must be 'current', 'last_triggered', or 'date'"}), 400

    _no_setup = {
        'status': 'NO_SETUP', 'symbol': symbol, 'mode': mode,
        'session_high': None, 'session_low': None,
        'levels_to_draw': [], 'markers': [],
        'sweep': None, 'confirm': None, 'trigger': None, 'session_box': None,
    }

    try:
        row = None

        if mode == 'current':
            # Prefer the latest in-progress (non-triggered) setup
            row = db.execute(
                """
                SELECT * FROM session_break_state
                WHERE user_id = %s AND symbol = %s AND triggered_at IS NULL
                ORDER BY session_date DESC, updated_at DESC NULLS LAST
                LIMIT 1
                """,
                (current_user.id, symbol), fetchone=True,
            )
            if not row:
                # All triggered or empty – show most recent overall
                row = db.execute(
                    """
                    SELECT * FROM session_break_state
                    WHERE user_id = %s AND symbol = %s
                    ORDER BY session_date DESC, COALESCE(triggered_at, updated_at) DESC NULLS LAST
                    LIMIT 1
                    """,
                    (current_user.id, symbol), fetchone=True,
                )

        elif mode == 'last_triggered':
            row = db.execute(
                """
                SELECT * FROM session_break_state
                WHERE user_id = %s AND symbol = %s AND triggered_at IS NOT NULL
                ORDER BY triggered_at DESC
                LIMIT 1
                """,
                (current_user.id, symbol), fetchone=True,
            )

        elif mode == 'date':
            session_type = request.args.get('session_type', '').strip().lower()
            date_str     = request.args.get('date', '').strip()
            if session_type not in ('asia', 'london'):
                return jsonify({'error': "session_type must be 'asia' or 'london'"}), 400
            if not date_str:
                return jsonify({'error': 'date required (YYYY-MM-DD)'}), 400
            row = db.execute(
                """
                SELECT * FROM session_break_state
                WHERE user_id = %s AND symbol = %s
                  AND session_type = %s AND session_date = %s
                """,
                (current_user.id, symbol, session_type, date_str), fetchone=True,
            )

        if not row:
            return jsonify(_no_setup)

        d = dict(row)

        # ── Compute session UTC window from stored session_type + session_date ──
        try:
            sd = d['session_date']
            if isinstance(sd, str):
                sd = _dtp.strptime(sd, '%Y-%m-%d').date()
            start_utc, end_utc = _session_window_utc(d['session_type'], sd)
            box_from_ts       = int(start_utc.timestamp())
            box_to_ts         = int(end_utc.timestamp())
            session_start_utc = start_utc.isoformat()
            session_end_utc   = end_utc.isoformat()
        except Exception:
            box_from_ts = box_to_ts = None
            session_start_utc = session_end_utc = None

        # ── Map DB state → clean status string ───────────────────────────────
        db_state = d.get('state') or 'WAIT_SWEEP_START'
        if d.get('triggered_at'):
            status = 'TRIGGERED'
        elif db_state in ('UP_WAIT_CONFIRM', 'DOWN_WAIT_CONFIRM'):
            status = 'WAIT_CONFIRM'
        elif db_state in ('UP_IN_SWEEP', 'DOWN_IN_SWEEP'):
            status = 'IN_SWEEP'
        else:
            status = 'WAIT_SWEEP'

        direction = d.get('direction')

        def _f(key):
            v = d.get(key)
            return float(v) if v is not None else None

        def _ts(key):
            v = d.get(key)
            if v is None:
                return None
            return v.isoformat() if hasattr(v, 'isoformat') else str(v)

        def _unix(key):
            v = d.get(key)
            if v is None:
                return None
            return int(v.timestamp()) if hasattr(v, 'timestamp') else None

        # ── Price levels ─────────────────────────────────────────────────────
        levels = []
        if d.get('session_high') is not None:
            levels.append({'type': 'session_high',      'price': _f('session_high'),
                           'color_key': 'sessionHigh'})
        if d.get('session_low') is not None:
            levels.append({'type': 'session_low',       'price': _f('session_low'),
                           'color_key': 'sessionLow'})
        if d.get('first_sweep_level') is not None:
            levels.append({'type': 'first_sweep_level', 'price': _f('first_sweep_level'),
                           'color_key': 'sweepLevel',   'only_if_present': True})
        if d.get('confirm_break_level') is not None:
            levels.append({'type': 'confirm_level',     'price': _f('confirm_break_level'),
                           'color_key': 'confirmLevel', 'only_if_present': True})

        # ── Markers (one per key event, minimal set) ─────────────────────────
        markers = []
        if d.get('sweep_start_ts'):
            markers.append({
                'ts':       _unix('sweep_start_ts'),
                'position': 'belowBar' if direction == 'UP' else 'aboveBar',
                'shape':    'arrowUp'  if direction == 'UP' else 'arrowDown',
                'text':     'SWEEP',
            })
        if d.get('sweep_end_ts'):
            markers.append({
                'ts':       _unix('sweep_end_ts'),
                'position': 'aboveBar' if direction == 'UP' else 'belowBar',
                'shape':    'circle',
                'text':     'RE-ENTRY',
            })
        if d.get('confirm_break_ts'):
            label = 'TRIGGER' if d.get('triggered_at') else 'CONFIRM'
            markers.append({
                'ts':       _unix('confirm_break_ts'),
                'position': 'belowBar' if direction == 'UP' else 'aboveBar',
                'shape':    'arrowUp'  if direction == 'UP' else 'arrowDown',
                'text':     label,
            })

        # ── Sweep / confirm / trigger sub-objects ─────────────────────────────
        sweep_obj = None
        if direction:
            sweep_obj = {
                'direction':         direction,
                'sweep_start_ts':    _ts('sweep_start_ts'),
                'sweep_end_ts':      _ts('sweep_end_ts'),
                'first_sweep_level': _f('first_sweep_level'),
                'reentry_ts':        _ts('sweep_end_ts'),
            }

        confirm_obj = None
        if d.get('confirm_break_ts'):
            confirm_obj = {
                'confirm_break_ts':    _ts('confirm_break_ts'),
                'confirm_break_level': _f('confirm_break_level'),
            }

        trigger_obj = None
        if d.get('triggered_at'):
            trigger_obj = {
                'triggered_at':  _ts('triggered_at'),
                'trigger_ts':    _ts('confirm_break_ts'),
                'trigger_price': _f('confirm_break_level'),
            }

        session_box = None
        if box_from_ts and box_to_ts:
            session_box = {'enabled': True, 'from_ts': box_from_ts, 'to_ts': box_to_ts}

        return jsonify({
            'symbol':            symbol,
            'provider':          'TRADINGVIEW',
            'feed':              'PEPPERSTONE',
            'session_type':      d.get('session_type'),
            'session_date':      str(d['session_date']),
            'timezone':          'Asia/Jerusalem',
            'session_start_utc': session_start_utc,
            'session_end_utc':   session_end_utc,
            'session_high':      _f('session_high'),
            'session_low':       _f('session_low'),
            'status':            status,
            'db_state':          db_state,
            'mode':              mode,
            'sweep':             sweep_obj,
            'confirm':           confirm_obj,
            'trigger':           trigger_obj,
            'levels_to_draw':    levels,
            'markers':           markers,
            'session_box':       session_box,
        })

    except Exception as exc:
        logger.error('[SESSION_SWEEP] overlay endpoint error: %s', exc)
        return jsonify({'error': str(exc)}), 500


# Gunicorn will run the app, this is only for local testing
if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
