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
            .message {
                padding: 12px 16px;
                border-radius: 10px;
                margin-top: 15px;
                font-size: 14px;
                font-weight: 500;
            }
            .success {
                background: rgba(0,255,163,0.1);
                border: 1px solid rgba(0,255,163,0.2);
                color: #00FFA3;
            }
            
            .error {
                background: rgba(255,107,107,0.1);
                border: 1px solid rgba(255,107,107,0.2);
                color: #FF6B6B;
            }
            .link { text-align: center; margin-top: 20px; }
            /* Premium Fintech Additions */

            /* Alert Type Toggle */
            .alert-type-toggle {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 8px;
                margin-bottom: 24px;
                background: rgba(255,255,255,0.05);
                border-radius: 12px;
                padding: 4px;
            }
            
            .toggle-option {
                height: 44px;
                border-radius: 10px;
                background: transparent;
                border: none;
                color: #8B92A8;
                font-size: 14px;
                font-weight: 600;
                box-shadow: none;
                transition: all 0.3s ease;
                margin: 0;
                width: auto;
            }
            
            .toggle-option.active {
                background: #5B7CFF;
                color: #FFFFFF;
                box-shadow: 0 2px 12px rgba(91,124,255,0.3);
            }
            
            /* MA Selector */
            .ma-selector {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 8px;
            }
            
            .ma-option {
                height: 56px;
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 12px;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                gap: 2px;
                cursor: pointer;
                transition: all 0.3s ease;
            }
            
            .ma-option.active {
                background: rgba(0,217,255,0.1);
                border-color: #00D9FF;
                box-shadow: 0 0 0 4px rgba(0,217,255,0.1);
            }
            
            .ma-label {
                font-size: 15px;
                font-weight: 700;
                color: #FFFFFF;
            }
            
            .ma-sublabel {
                font-size: 11px;
                font-weight: 500;
                color: #8B92A8;
                text-transform: none;
            }
            
            .ma-option.active .ma-sublabel {
                color: #00D9FF;
            }
            
            /* Financial Values */
            .financial-value,
            .price-value,
            .summary-value {
                font-variant-numeric: tabular-nums;
                letter-spacing: -0.3px;
            }
            
            /* Alert Cards */
            .alert-card {
                background: rgba(255,255,255,0.05);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
                padding: 20px;
                margin-bottom: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.2);
                position: relative;
                overflow: hidden;
            }
            
            .alert-card::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                width: 4px;
                height: 100%;
                background: linear-gradient(180deg, #5B7CFF 0%, #7B5CFF 100%);
            }
            
            .alert-card.ma-alert::before {
                background: linear-gradient(180deg, #00D9FF 0%, #0099FF 100%);
            }
            
            /* Status Badges */
            .status-badge {
                font-size: 11px;
                font-weight: 600;
                padding: 4px 8px;
                border-radius: 6px;
                letter-spacing: 0.3px;
            }
            
            .status-badge.price {
                background: rgba(91,124,255,0.15);
                color: #5B7CFF;
                border: 1px solid rgba(91,124,255,0.25);
            }
            
            .status-badge.ma {
                background: rgba(0,217,255,0.15);
                color: #00D9FF;
                border: 1px solid rgba(0,217,255,0.25);
            }
            
            .status-indicator {
                font-size: 12px;
                font-weight: 600;
                padding: 6px 10px;
                border-radius: 8px;
                display: inline-flex;
                align-items: center;
                gap: 4px;
            }
            
            .status-indicator.above {
                background: rgba(0,255,163,0.1);
                color: #00FFA3;
                border: 1px solid rgba(0,255,163,0.2);
            }
            
            .status-indicator.below {
                background: rgba(255,107,107,0.1);
                color: #FF6B6B;
                border: 1px solid rgba(255,107,107,0.2);
            }
            
            .status-dot {
                width: 6px;
                height: 6px;
                border-radius: 50%;
                background: currentColor;
                box-shadow: 0 0 8px currentColor;
            }
            
            /* Price Display */
            .price-item {
                margin-bottom: 12px;
            }
            
            .price-label {
                font-size: 12px;
                font-weight: 500;
                color: #8B92A8;
                margin-bottom: 4px;
                text-transform: none;
            }
            
            .price-value {
                font-size: 20px;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
                letter-spacing: -0.3px;
            }
            
            .price-change {
                font-size: 13px;
                font-weight: 600;
                margin-top: 4px;
            }
            
            .price-change.positive {
                color: #00FFA3;
            }
            
            .price-change.negative {
                color: #FF6B6B;
            }
            
            /* Autocomplete Dropdown */
            .autocomplete-dropdown {
                background: rgba(14,20,32,0.98);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(91,124,255,0.3);
                border-radius: 12px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.4);
            }
            
            .autocomplete-item:hover {
                background: rgba(91,124,255,0.1);
            }
            
            .ticker-symbol {
                font-weight: 700;
                color: #5B7CFF;
            }
            
            .ticker-name {
                color: #8B92A8;
            }
            
            .ticker-type {
                background: rgba(91,124,255,0.15);
                color: #5B7CFF;
                font-weight: 600;
            }
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
            button {
                width: 100%;
                padding: 14px;
                background: linear-gradient(135deg, #5B7CFF 0%, #7B5CFF 100%);
                color: white;
                border: none;
                border-radius: 12px;
                font-weight: 700;
                cursor: pointer;
                font-size: 15px;
                transition: all 0.2s ease;
                margin-top: 10px;
                box-shadow: 0 4px 24px rgba(91,124,255,0.35), 0 2px 8px rgba(0,0,0,0.2);
            }
            
            button:hover {
                box-shadow: 0 6px 32px rgba(91,124,255,0.45), 0 2px 8px rgba(0,0,0,0.3);
            }
            
            button:active {
                transform: scale(0.98);
            }
            .message {
                padding: 12px 16px;
                border-radius: 10px;
                margin-top: 15px;
                font-size: 14px;
                font-weight: 500;
            }
            .success {
                background: rgba(0,255,163,0.1);
                border: 1px solid rgba(0,255,163,0.2);
                color: #00FFA3;
            }
            
            .error {
                background: rgba(255,107,107,0.1);
                border: 1px solid rgba(255,107,107,0.2);
                color: #FF6B6B;
            }
            .link { text-align: center; margin-top: 20px; }
                        /* Alert Type Toggle */
            .alert-type-toggle {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 8px;
                margin-bottom: 24px;
                background: rgba(255,255,255,0.05);
                border-radius: 12px;
                padding: 4px;
            }
            
            .toggle-option {
                height: 44px;
                border-radius: 10px;
                background: transparent;
                border: none;
                color: #8B92A8;
                font-size: 14px;
                font-weight: 600;
                box-shadow: none;
                transition: all 0.3s ease;
                margin: 0;
                width: auto;
            }
            
            .toggle-option.active {
                background: #5B7CFF;
                color: #FFFFFF;
                box-shadow: 0 2px 12px rgba(91,124,255,0.3);
            }
            
            /* MA Selector */
            .ma-selector {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 8px;
            }
            
            .ma-option {
                height: 56px;
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 12px;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                gap: 2px;
                cursor: pointer;
                transition: all 0.3s ease;
            }
            
            .ma-option.active {
                background: rgba(0,217,255,0.1);
                border-color: #00D9FF;
                box-shadow: 0 0 0 4px rgba(0,217,255,0.1);
            }
            
            .ma-label {
                font-size: 15px;
                font-weight: 700;
                color: #FFFFFF;
            }
            
            .ma-sublabel {
                font-size: 11px;
                font-weight: 500;
                color: #8B92A8;
                text-transform: none;
            }
            
            .ma-option.active .ma-sublabel {
                color: #00D9FF;
            }
            
            /* Financial Values */
            .financial-value,
            .price-value,
            .summary-value {
                font-variant-numeric: tabular-nums;
                letter-spacing: -0.3px;
            }
            
            /* Alert Cards */
            .alert-card {
                background: rgba(255,255,255,0.05);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
                padding: 20px;
                margin-bottom: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.2);
                position: relative;
                overflow: hidden;
            }
            
            .alert-card::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                width: 4px;
                height: 100%;
                background: linear-gradient(180deg, #5B7CFF 0%, #7B5CFF 100%);
            }
            
            .alert-card.ma-alert::before {
                background: linear-gradient(180deg, #00D9FF 0%, #0099FF 100%);
            }
            
            /* Status Badges */
            .status-badge {
                font-size: 11px;
                font-weight: 600;
                padding: 4px 8px;
                border-radius: 6px;
                letter-spacing: 0.3px;
            }
            
            .status-badge.price {
                background: rgba(91,124,255,0.15);
                color: #5B7CFF;
                border: 1px solid rgba(91,124,255,0.25);
            }
            
            .status-badge.ma {
                background: rgba(0,217,255,0.15);
                color: #00D9FF;
                border: 1px solid rgba(0,217,255,0.25);
            }
            
            .status-indicator {
                font-size: 12px;
                font-weight: 600;
                padding: 6px 10px;
                border-radius: 8px;
                display: inline-flex;
                align-items: center;
                gap: 4px;
            }
            
            .status-indicator.above {
                background: rgba(0,255,163,0.1);
                color: #00FFA3;
                border: 1px solid rgba(0,255,163,0.2);
            }
            
            .status-indicator.below {
                background: rgba(255,107,107,0.1);
                color: #FF6B6B;
                border: 1px solid rgba(255,107,107,0.2);
            }
            
            .status-dot {
                width: 6px;
                height: 6px;
                border-radius: 50%;
                background: currentColor;
                box-shadow: 0 0 8px currentColor;
            }
            
            /* Price Display */
            .price-item {
                margin-bottom: 12px;
            }
            
            .price-label {
                font-size: 12px;
                font-weight: 500;
                color: #8B92A8;
                margin-bottom: 4px;
                text-transform: none;
            }
            
            .price-value {
                font-size: 20px;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
                letter-spacing: -0.3px;
            }
            
            .price-change {
                font-size: 13px;
                font-weight: 600;
                margin-top: 4px;
            }
            
            .price-change.positive {
                color: #00FFA3;
            }
            
            .price-change.negative {
                color: #FF6B6B;
            }
            
            /* Autocomplete Dropdown */
            .autocomplete-dropdown {
                background: rgba(14,20,32,0.98);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(91,124,255,0.3);
                border-radius: 12px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.4);
            }
            
            .autocomplete-item:hover {
                background: rgba(91,124,255,0.1);
            }
            
            .ticker-symbol {
                font-weight: 700;
                color: #5B7CFF;
            }
            
            .ticker-name {
                color: #8B92A8;
            }
            
            .ticker-type {
                background: rgba(91,124,255,0.15);
                color: #5B7CFF;
                font-weight: 600;
            }
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
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', system-ui, sans-serif;
            background: #0A0E1A;
            background-image: radial-gradient(circle at 50% 0%, #1a1f2e 0%, #0a0e1a 50%);
            min-height: 100vh;
            color: #FFFFFF;
            padding: 20px;
            -webkit-font-smoothing: antialiased;
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
            color: #8B92A8;
            text-decoration: none;
            font-weight: 600;
            font-size: 14px;
            transition: color 0.3s;
        }
        
        .nav a:hover { color: #5B7CFF; }

        .header {
            padding: 0;
            margin-bottom: 30px;
        }

        .header h1 {
            font-size: 32px;
            font-weight: 700;
            letter-spacing: -0.5px;
            margin-bottom: 24px;
        }

        .header p {
            opacity: 0.9;
            font-size: 14px;
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
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 16px;
            padding: 25px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            margin-bottom: 20px;
        }

        .card h2 {
            font-size: 20px;
            font-weight: 700;
            margin-bottom: 20px;
            letter-spacing: -0.3px;
            color: #FFFFFF;
        }

        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #8B92A8;
            font-size: 13px;
            letter-spacing: 0.2px;
            text-transform: uppercase;
        }

        input, select, textarea {
            width: 100%;
            height: 56px;
            padding: 0 16px;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            color: #FFFFFF;
            font-size: 16px;
            font-weight: 500;
            font-family: inherit;
            transition: all 0.3s ease;
        }
        
        textarea {
            height: auto;
            min-height: 80px;
            padding: 16px;
        }
            
        input:focus, select:focus, textarea:focus {
            outline: none;
            border-color: #5B7CFF;
            background: rgba(91,124,255,0.05);
            box-shadow: 0 0 0 4px rgba(91,124,255,0.1);
        }
        
        input::placeholder {
            color: #4A5568;
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
            background: linear-gradient(135deg, #5B7CFF 0%, #7B5CFF 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-weight: 700;
            cursor: pointer;
            font-size: 15px;
            transition: all 0.2s ease;
            margin-top: 10px;
            box-shadow: 0 4px 24px rgba(91,124,255,0.35), 0 2px 8px rgba(0,0,0,0.2);
        }
        
        button:hover {
            box-shadow: 0 6px 32px rgba(91,124,255,0.45), 0 2px 8px rgba(0,0,0,0.3);
        }
        
        button:active {
            transform: scale(0.98);
        }
            
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
            
        .message {
            padding: 12px 16px;
            border-radius: 10px;
            margin-top: 15px;
            font-size: 14px;
            font-weight: 500;
        }
        .success {
            background: rgba(0,255,163,0.1);
            border: 1px solid rgba(0,255,163,0.2);
            color: #00FFA3;
        }
        
        .error {
            background: rgba(255,107,107,0.1);
            border: 1px solid rgba(255,107,107,0.2);
            color: #FF6B6B;
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
            border: 3px solid rgba(91,124,255,0.1);
            border-top: 3px solid #5B7CFF;
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
                    /* Alert Type Toggle */
            .alert-type-toggle {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 8px;
                margin-bottom: 24px;
                background: rgba(255,255,255,0.05);
                border-radius: 12px;
                padding: 4px;
            }
            
            .toggle-option {
                height: 44px;
                border-radius: 10px;
                background: transparent;
                border: none;
                color: #8B92A8;
                font-size: 14px;
                font-weight: 600;
                box-shadow: none;
                transition: all 0.3s ease;
                margin: 0;
                width: auto;
            }
            
            .toggle-option.active {
                background: #5B7CFF;
                color: #FFFFFF;
                box-shadow: 0 2px 12px rgba(91,124,255,0.3);
            }
            
            /* MA Selector */
            .ma-selector {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 8px;
            }
            
            .ma-option {
                height: 56px;
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 12px;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                gap: 2px;
                cursor: pointer;
                transition: all 0.3s ease;
            }
            
            .ma-option.active {
                background: rgba(0,217,255,0.1);
                border-color: #00D9FF;
                box-shadow: 0 0 0 4px rgba(0,217,255,0.1);
            }
            
            .ma-label {
                font-size: 15px;
                font-weight: 700;
                color: #FFFFFF;
            }
            
            .ma-sublabel {
                font-size: 11px;
                font-weight: 500;
                color: #8B92A8;
                text-transform: none;
            }
            
            .ma-option.active .ma-sublabel {
                color: #00D9FF;
            }
            
            /* Financial Values */
            .financial-value,
            .price-value,
            .summary-value {
                font-variant-numeric: tabular-nums;
                letter-spacing: -0.3px;
            }
            
            /* Alert Cards */
            .alert-card {
                background: rgba(255,255,255,0.05);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
                padding: 20px;
                margin-bottom: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.2);
                position: relative;
                overflow: hidden;
            }
            
            .alert-card::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                width: 4px;
                height: 100%;
                background: linear-gradient(180deg, #5B7CFF 0%, #7B5CFF 100%);
            }
            
            .alert-card.ma-alert::before {
                background: linear-gradient(180deg, #00D9FF 0%, #0099FF 100%);
            }
            
            /* Status Badges */
            .status-badge {
                font-size: 11px;
                font-weight: 600;
                padding: 4px 8px;
                border-radius: 6px;
                letter-spacing: 0.3px;
            }
            
            .status-badge.price {
                background: rgba(91,124,255,0.15);
                color: #5B7CFF;
                border: 1px solid rgba(91,124,255,0.25);
            }
            
            .status-badge.ma {
                background: rgba(0,217,255,0.15);
                color: #00D9FF;
                border: 1px solid rgba(0,217,255,0.25);
            }
            
            .status-indicator {
                font-size: 12px;
                font-weight: 600;
                padding: 6px 10px;
                border-radius: 8px;
                display: inline-flex;
                align-items: center;
                gap: 4px;
            }
            
            .status-indicator.above {
                background: rgba(0,255,163,0.1);
                color: #00FFA3;
                border: 1px solid rgba(0,255,163,0.2);
            }
            
            .status-indicator.below {
                background: rgba(255,107,107,0.1);
                color: #FF6B6B;
                border: 1px solid rgba(255,107,107,0.2);
            }
            
            .status-dot {
                width: 6px;
                height: 6px;
                border-radius: 50%;
                background: currentColor;
                box-shadow: 0 0 8px currentColor;
            }
            
            /* Price Display */
            .price-item {
                margin-bottom: 12px;
            }
            
            .price-label {
                font-size: 12px;
                font-weight: 500;
                color: #8B92A8;
                margin-bottom: 4px;
                text-transform: none;
            }
            
            .price-value {
                font-size: 20px;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
                letter-spacing: -0.3px;
            }
            
            .price-change {
                font-size: 13px;
                font-weight: 600;
                margin-top: 4px;
            }
            
            .price-change.positive {
                color: #00FFA3;
            }
            
            .price-change.negative {
                color: #FF6B6B;
            }
            
            /* Autocomplete Dropdown */
            .autocomplete-dropdown {
                background: rgba(14,20,32,0.98);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(91,124,255,0.3);
                border-radius: 12px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.4);
            }
            
            .autocomplete-item:hover {
                background: rgba(91,124,255,0.1);
            }
            
            .ticker-symbol {
                font-weight: 700;
                color: #5B7CFF;
            }
            
            .ticker-name {
                color: #8B92A8;
            }
            
            .ticker-type {
                background: rgba(91,124,255,0.15);
                color: #5B7CFF;
                font-weight: 600;
            }
    </style>
</head>
<body>
    <div class="container">
        <div class="nav">
            <a href="/dashboard">📊 Stock Alerts</a>
            <a href="/alerts/history">📜 History</a>
            <a href="/radar">🚨 Radar</a>
            <a href="/bitcoin-scanner">₿ Bitcoin Scanner</a>
            <a href="/forex-amd">🌐 Forex AMD</a>
            <a href="/portfolio">💼 Portfolio</a>
            <a href="#" onclick="logout()">Logout</a>
        </div>
       
        <div class="header" style="padding: 56px 0 24px; position: relative;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="font-size: 15px; font-weight: 500; color: #8B92A8; letter-spacing: -0.2px;">Good Evening</div>
            </div>
            <h1 style="font-size: 32px; font-weight: 700; letter-spacing: -0.5px; margin-bottom: 24px;">Dashboard</h1>
        </div>
        
        <div class="grid">
            <div class="card">
    <h2>Create New Alert</h2>
    
    <!-- NEW: Alert Type Selection -->
    <div class="alert-type-toggle">
        <button id="priceTypeBtn" class="toggle-option active" onclick="switchAlertType('price')">Price Alert</button>
        <button id="maTypeBtn" class="toggle-option" onclick="switchAlertType('ma')">MA Alert</button>
    </div>
    
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
    
    <!-- Price Alert Fields (shown by default) -->
    <div id="priceAlertFields">
        <label>Target Price ($)</label>
        <input type="number" id="targetPrice" placeholder="Enter target price" step="0.01" />
        
        <p style="color: #888; font-size: 13px; margin-top: 10px;">
            Alert will trigger when price crosses the target price (either direction).
        </p>
    </div>
    
    <!-- NEW: MA Alert Fields (hidden by default) -->
    <div id="maAlertFields" style="display: none;">
        <label>Moving Average Period</label>
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
    
        <p style="color: #888; font-size: 13px; margin-top: 10px;">
            Alert will trigger when price crosses above the selected moving average.
        </p>
    </div>
    
    <button onclick="createAlert()" id="createBtn">
        Create Alert
    </button>
                
                <div id="message"></div>
            </div>
            <!-- NEW: Natural Language Alert Creator -->
            <div class="card">
                <h2>✨ Create Alert from Text</h2>
                <p style="color: #8B92A8; font-size: 13px; margin-bottom: 12px;">
                    Try: "Alert me if TSLA breaks 200" or "Tell me when AAPL dumps hard"
                </p>
    
                <input 
                    type="text" 
                    id="nlAlertInput" 
                    placeholder="Type your alert in plain English..."
                    style="width: 100%; margin-bottom: 12px;"
                />
    
               <button onclick="parseNLAlert()" id="parseBtn">Parse Alert</button>

               <!-- Preview Section (hidden initially) -->
               <div id="nlPreview" style="display: none; margin-top: 16px; padding: 16px; background: rgba(91,124,255,0.1); border-radius: 12px; border: 1px solid rgba(91,124,255,0.2);">
                   <div style="font-size: 13px; font-weight: 600; color: #5B7CFF; margin-bottom: 8px;">Preview:</div>
                   <div id="nlSummary" style="margin-bottom: 12px;"></div>
                   <button onclick="confirmNLAlert()" id="confirmBtn">Confirm & Create</button>
                   <button onclick="cancelNLAlert()" class="btn-secondary" style="margin-left: 8px;">Cancel</button>
              </div>
    
              <div id="nlMessage"></div>
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
                    document.getElementById('alertType').value = 'price';
                    toggleAlertFields();  // Reset to price view
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
        
        const active = data.alerts.filter(a => a.active);
        
        if (active.length === 0) {
            alertsEl.innerHTML = '<div class="empty">No active alerts. Create one to get started!</div>';
            return;
        }
        
        // Generate unique key for each render to force update
        const renderKey = Math.random().toString(36).substring(7);
        
        alertsEl.innerHTML = active.map(alert => {
        const current = alert.current_price || 0;
        const target = alert.target_price || 0;
        const alertType = alert.alert_type || 'price';
        const maPeriod = alert.ma_period;
        
        // Calculate status (above/below)
        const isAbove = current >= target;
        
        // Calculate percentage difference
        const diff = Math.abs(current - target);
        const pct = target > 0 ? ((diff / target) * 100).toFixed(1) : '0.0';
        
        // Determine colors and labels
        const accentClass = alertType === 'ma' ? 'ma-alert' : '';
        const badgeLabel = alertType === 'ma' ? `MA ${maPeriod}` : 'PRICE';
        const badgeClass = alertType === 'ma' ? 'ma' : 'price';
        const targetLabel = alertType === 'ma' ? `MA${maPeriod}` : 'Target';
        
        return `
            <div class="alert-card ${accentClass}" style="background: rgba(255,255,255,0.05); backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 20px; margin-bottom: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); position: relative; overflow: hidden;">
                
                <!-- Header Row -->
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 18px; font-weight: 700; letter-spacing: -0.3px; color: #FFFFFF;">${alert.ticker}</span>
                        <span class="status-badge ${badgeClass}" style="font-size: 11px; font-weight: 600; padding: 4px 8px; border-radius: 6px;">${badgeLabel}</span>
                    </div>
                    
                    <div class="status-indicator ${isAbove ? 'above' : 'below'}" style="font-size: 12px; font-weight: 600; padding: 6px 10px; border-radius: 8px; display: inline-flex; align-items: center; gap: 4px;">
                        <span class="status-dot" style="width: 6px; height: 6px; border-radius: 50%; background: currentColor; box-shadow: 0 0 8px currentColor;"></span>
                        ${isAbove ? 'Above' : 'Below'}
                    </div>
                </div>
                
                <!-- Prices Grid -->
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                    <div>
                        <div style="font-size: 12px; font-weight: 500; color: #8B92A8; margin-bottom: 4px;">Current Price</div>
                        <div style="font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; letter-spacing: -0.3px; color: #FFFFFF;">$${current.toFixed(2)}</div>
                    </div>
                    <div>
                        <div style="font-size: 12px; font-weight: 500; color: #8B92A8; margin-bottom: 4px;">${targetLabel}</div>
                        <div style="font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; letter-spacing: -0.3px; color: #FFFFFF;">$${target.toFixed(2)}</div>
                    </div>
                </div>
                
                <!-- Distance Info -->
                <div style="margin-top: 12px; font-size: 13px; color: #8B92A8;">
                    ${pct}% away from ${targetLabel.toLowerCase()}
                </div>
                
                <!-- Delete Button -->
                <button onclick="deleteAlert(${alert.id})" style="width: 100%; margin-top: 16px; padding: 10px; background: rgba(255,107,107,0.15); border: 1px solid rgba(255,107,107,0.25); border-radius: 8px; color: #FF6B6B; font-size: 13px; font-weight: 600;">
                    Delete Alert
                </button>
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
    <html>
    <head>
        <title>Bitcoin Scanner - Stock Alerts</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', system-ui, sans-serif;
                background: #0A0E1A;
                background-image: radial-gradient(circle at 50% 0%, #1a1f2e 0%, #0a0e1a 50%);
                min-height: 100vh;
                color: #FFFFFF;
                padding: 20px;
                -webkit-font-smoothing: antialiased;
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
                color: #8B92A8;
                text-decoration: none;
                font-weight: 600;
                font-size: 14px;
                transition: color 0.3s;
            }
            
            .nav a:hover { color: #5B7CFF; }
            .container { max-width: 1200px; margin: 0 auto; }
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 30px;
                border-radius: 15px;
                margin-bottom: 30px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.3);
            }
            .header h1 {
                font-size: 32px;
                font-weight: 700;
                letter-spacing: -0.5px;
                margin-bottom: 24px;
            }
            .card {
                background: rgba(255,255,255,0.05);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
                padding: 25px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.2);
                margin-bottom: 20px;
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
                font-weight: 600;
                color: #8B92A8;
                font-size: 13px;
                letter-spacing: 0.2px;
                text-transform: uppercase;
            }
            input, select, textarea {
                width: 100%;
                height: 56px;
                padding: 0 16px;
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 12px;
                color: #FFFFFF;
                font-size: 16px;
                font-weight: 500;
                font-family: inherit;
                transition: all 0.3s ease;
            }
            
            textarea {
                height: auto;
                min-height: 80px;
                padding: 16px;
            }
                
            input:focus, select:focus, textarea:focus {
                outline: none;
                border-color: #5B7CFF;
                background: rgba(91,124,255,0.05);
                box-shadow: 0 0 0 4px rgba(91,124,255,0.1);
            }
            
            input::placeholder {
                color: #4A5568;
            }
            button {
                width: 100%;
                padding: 14px;
                background: linear-gradient(135deg, #5B7CFF 0%, #7B5CFF 100%);
                color: white;
                border: none;
                border-radius: 12px;
                font-weight: 700;
                cursor: pointer;
                font-size: 15px;
                transition: all 0.2s ease;
                margin-top: 10px;
                box-shadow: 0 4px 24px rgba(91,124,255,0.35), 0 2px 8px rgba(0,0,0,0.2);
            }
            
            button:hover {
                box-shadow: 0 6px 32px rgba(91,124,255,0.45), 0 2px 8px rgba(0,0,0,0.3);
            }
            
            button:active {
                transform: scale(0.98);
            }
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
                        /* Alert Type Toggle */
            .alert-type-toggle {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 8px;
                margin-bottom: 24px;
                background: rgba(255,255,255,0.05);
                border-radius: 12px;
                padding: 4px;
            }
            
            .toggle-option {
                height: 44px;
                border-radius: 10px;
                background: transparent;
                border: none;
                color: #8B92A8;
                font-size: 14px;
                font-weight: 600;
                box-shadow: none;
                transition: all 0.3s ease;
                margin: 0;
                width: auto;
            }
            
            .toggle-option.active {
                background: #5B7CFF;
                color: #FFFFFF;
                box-shadow: 0 2px 12px rgba(91,124,255,0.3);
            }
            
            /* MA Selector */
            .ma-selector {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 8px;
            }
            
            .ma-option {
                height: 56px;
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 12px;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                gap: 2px;
                cursor: pointer;
                transition: all 0.3s ease;
            }
            
            .ma-option.active {
                background: rgba(0,217,255,0.1);
                border-color: #00D9FF;
                box-shadow: 0 0 0 4px rgba(0,217,255,0.1);
            }
            
            .ma-label {
                font-size: 15px;
                font-weight: 700;
                color: #FFFFFF;
            }
            
            .ma-sublabel {
                font-size: 11px;
                font-weight: 500;
                color: #8B92A8;
                text-transform: none;
            }
            
            .ma-option.active .ma-sublabel {
                color: #00D9FF;
            }
            
            /* Financial Values */
            .financial-value,
            .price-value,
            .summary-value {
                font-variant-numeric: tabular-nums;
                letter-spacing: -0.3px;
            }
            
            /* Alert Cards */
            .alert-card {
                background: rgba(255,255,255,0.05);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
                padding: 20px;
                margin-bottom: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.2);
                position: relative;
                overflow: hidden;
            }
            
            .alert-card::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                width: 4px;
                height: 100%;
                background: linear-gradient(180deg, #5B7CFF 0%, #7B5CFF 100%);
            }
            
            .alert-card.ma-alert::before {
                background: linear-gradient(180deg, #00D9FF 0%, #0099FF 100%);
            }
            
            /* Status Badges */
            .status-badge {
                font-size: 11px;
                font-weight: 600;
                padding: 4px 8px;
                border-radius: 6px;
                letter-spacing: 0.3px;
            }
            
            .status-badge.price {
                background: rgba(91,124,255,0.15);
                color: #5B7CFF;
                border: 1px solid rgba(91,124,255,0.25);
            }
            
            .status-badge.ma {
                background: rgba(0,217,255,0.15);
                color: #00D9FF;
                border: 1px solid rgba(0,217,255,0.25);
            }
            
            .status-indicator {
                font-size: 12px;
                font-weight: 600;
                padding: 6px 10px;
                border-radius: 8px;
                display: inline-flex;
                align-items: center;
                gap: 4px;
            }
            
            .status-indicator.above {
                background: rgba(0,255,163,0.1);
                color: #00FFA3;
                border: 1px solid rgba(0,255,163,0.2);
            }
            
            .status-indicator.below {
                background: rgba(255,107,107,0.1);
                color: #FF6B6B;
                border: 1px solid rgba(255,107,107,0.2);
            }
            
            .status-dot {
                width: 6px;
                height: 6px;
                border-radius: 50%;
                background: currentColor;
                box-shadow: 0 0 8px currentColor;
            }
            
            /* Price Display */
            .price-item {
                margin-bottom: 12px;
            }
            
            .price-label {
                font-size: 12px;
                font-weight: 500;
                color: #8B92A8;
                margin-bottom: 4px;
                text-transform: none;
            }
            
            .price-value {
                font-size: 20px;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
                letter-spacing: -0.3px;
            }
            
            .price-change {
                font-size: 13px;
                font-weight: 600;
                margin-top: 4px;
            }
            
            .price-change.positive {
                color: #00FFA3;
            }
            
            .price-change.negative {
                color: #FF6B6B;
            }
            
            /* Autocomplete Dropdown */
            .autocomplete-dropdown {
                background: rgba(14,20,32,0.98);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(91,124,255,0.3);
                border-radius: 12px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.4);
            }
            
            .autocomplete-item:hover {
                background: rgba(91,124,255,0.1);
            }
            
            .ticker-symbol {
                font-weight: 700;
                color: #5B7CFF;
            }
            
            .ticker-name {
                color: #8B92A8;
            }
            
            .ticker-type {
                background: rgba(91,124,255,0.15);
                color: #5B7CFF;
                font-weight: 600;
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

            <div class="header" style="padding: 56px 0 24px;">
                <div style="font-size: 15px; font-weight: 500; color: #8B92A8; margin-bottom: 8px;">Blockchain Analysis</div>
                <h1 style="font-size: 32px; font-weight: 700; letter-spacing: -0.5px; margin-bottom: 24px;">Bitcoin Scanner</h1>
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
            <select id="timeRange">
                <option value="24">Last 24 Hours</option>
                <option value="168">Last Week</option>
                <option value="720">Last Month</option>
                <option value="4320">Last 6 Months</option>
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
                const timeRange = document.getElementById('timeRange').value; // Remove parseInt, keep as string
                const resultsEl = document.getElementById('results');
                const scanBtn = document.getElementById('scanBtn');
                
                scanBtn.disabled = true;
                scanBtn.textContent = 'Scanning...';
                resultsEl.innerHTML = '<div class="loading">🔍 Scanning Bitcoin blockchain...</div>';
                
                try {
                    const res = await fetch('/api/bitcoin/scan', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ min_amount: minAmount, timeframe: timeRange })
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
            // loadTickers();
            // loadAlerts();
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
<html>
<head>
    <title>Portfolio Management - Stock Alerts</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', system-ui, sans-serif;
            background: #0A0E1A;
            background-image: radial-gradient(circle at 50% 0%, #1a1f2e 0%, #0a0e1a 50%);
            min-height: 100vh;
            color: #FFFFFF;
            padding: 20px;
            -webkit-font-smoothing: antialiased;
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
            color: #8B92A8;
            text-decoration: none;
            font-weight: 600;
            font-size: 14px;
            transition: color 0.3s;
        }
        
        .nav a:hover { color: #5B7CFF; }
        
        /* Header */
        .header {
            padding: 0;
            margin-bottom: 30px;
        }
        
        /* Card Styles */
        .card {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 16px;
            padding: 25px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            margin-bottom: 20px;
        }
        
        .card h2 {
            font-size: 20px;
            font-weight: 700;
            margin-bottom: 20px;
            letter-spacing: -0.3px;
            color: #FFFFFF;
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
            font-weight: 600;
            color: #8B92A8;
            font-size: 13px;
            letter-spacing: 0.2px;
            text-transform: uppercase;
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
            padding: 12px 16px;
            border-radius: 10px;
            margin-top: 15px;
            font-size: 14px;
            font-weight: 500;
        }
        .success {
            background: rgba(0,255,163,0.1);
            border: 1px solid rgba(0,255,163,0.2);
            color: #00FFA3;
        }
        
        .error {
            background: rgba(255,107,107,0.1);
            border: 1px solid rgba(255,107,107,0.2);
            color: #FF6B6B;
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
                    /* Alert Type Toggle */
            .alert-type-toggle {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 8px;
                margin-bottom: 24px;
                background: rgba(255,255,255,0.05);
                border-radius: 12px;
                padding: 4px;
            }
            
            .toggle-option {
                height: 44px;
                border-radius: 10px;
                background: transparent;
                border: none;
                color: #8B92A8;
                font-size: 14px;
                font-weight: 600;
                box-shadow: none;
                transition: all 0.3s ease;
                margin: 0;
                width: auto;
            }
            
            .toggle-option.active {
                background: #5B7CFF;
                color: #FFFFFF;
                box-shadow: 0 2px 12px rgba(91,124,255,0.3);
            }
            
            /* MA Selector */
            .ma-selector {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 8px;
            }
            
            .ma-option {
                height: 56px;
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 12px;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                gap: 2px;
                cursor: pointer;
                transition: all 0.3s ease;
            }
            
            .ma-option.active {
                background: rgba(0,217,255,0.1);
                border-color: #00D9FF;
                box-shadow: 0 0 0 4px rgba(0,217,255,0.1);
            }
            
            .ma-label {
                font-size: 15px;
                font-weight: 700;
                color: #FFFFFF;
            }
            
            .ma-sublabel {
                font-size: 11px;
                font-weight: 500;
                color: #8B92A8;
                text-transform: none;
            }
            
            .ma-option.active .ma-sublabel {
                color: #00D9FF;
            }
            
            /* Financial Values */
            .financial-value,
            .price-value,
            .summary-value {
                font-variant-numeric: tabular-nums;
                letter-spacing: -0.3px;
            }
            
            /* Alert Cards */
            .alert-card {
                background: rgba(255,255,255,0.05);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
                padding: 20px;
                margin-bottom: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.2);
                position: relative;
                overflow: hidden;
            }
            
            .alert-card::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                width: 4px;
                height: 100%;
                background: linear-gradient(180deg, #5B7CFF 0%, #7B5CFF 100%);
            }
            
            .alert-card.ma-alert::before {
                background: linear-gradient(180deg, #00D9FF 0%, #0099FF 100%);
            }
            
            /* Status Badges */
            .status-badge {
                font-size: 11px;
                font-weight: 600;
                padding: 4px 8px;
                border-radius: 6px;
                letter-spacing: 0.3px;
            }
            
            .status-badge.price {
                background: rgba(91,124,255,0.15);
                color: #5B7CFF;
                border: 1px solid rgba(91,124,255,0.25);
            }
            
            .status-badge.ma {
                background: rgba(0,217,255,0.15);
                color: #00D9FF;
                border: 1px solid rgba(0,217,255,0.25);
            }
            
            .status-indicator {
                font-size: 12px;
                font-weight: 600;
                padding: 6px 10px;
                border-radius: 8px;
                display: inline-flex;
                align-items: center;
                gap: 4px;
            }
            
            .status-indicator.above {
                background: rgba(0,255,163,0.1);
                color: #00FFA3;
                border: 1px solid rgba(0,255,163,0.2);
            }
            
            .status-indicator.below {
                background: rgba(255,107,107,0.1);
                color: #FF6B6B;
                border: 1px solid rgba(255,107,107,0.2);
            }
            
            .status-dot {
                width: 6px;
                height: 6px;
                border-radius: 50%;
                background: currentColor;
                box-shadow: 0 0 8px currentColor;
            }
            
            /* Price Display */
            .price-item {
                margin-bottom: 12px;
            }
            
            .price-label {
                font-size: 12px;
                font-weight: 500;
                color: #8B92A8;
                margin-bottom: 4px;
                text-transform: none;
            }
            
            .price-value {
                font-size: 20px;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
                letter-spacing: -0.3px;
            }
            
            .price-change {
                font-size: 13px;
                font-weight: 600;
                margin-top: 4px;
            }
            
            .price-change.positive {
                color: #00FFA3;
            }
            
            .price-change.negative {
                color: #FF6B6B;
            }
            
            /* Autocomplete Dropdown */
            .autocomplete-dropdown {
                background: rgba(14,20,32,0.98);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(91,124,255,0.3);
                border-radius: 12px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.4);
            }
            
            .autocomplete-item:hover {
                background: rgba(91,124,255,0.1);
            }
            
            .ticker-symbol {
                font-weight: 700;
                color: #5B7CFF;
            }
            
            .ticker-name {
                color: #8B92A8;
            }
            
            .ticker-type {
                background: rgba(91,124,255,0.15);
                color: #5B7CFF;
                font-weight: 600;
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
        <div class="header" style="padding: 56px 0 24px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="font-size: 15px; font-weight: 500; color: #8B92A8;">Portfolio</div>
            </div>
            <h1 style="font-size: 32px; font-weight: 700; letter-spacing: -0.5px; margin-bottom: 24px;">Trading Performance</h1>
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
        if alert_type not in ['price', 'ma']:
            return jsonify({
                'success': False, 
                'error': f'Alert type "{alert_type}" not yet supported via AI parsing. Try price or MA alerts.'
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
        
        # Return success
        return jsonify({
            'success': True,
            'alert': {
                'id': alert_id,
                'ticker': ticker,
                'alert_type': alert_type,
                'target_price': target_price if alert_type == 'price' else ma_value,
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
<html>
<head>
    <title>Alert History</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', sans-serif;
            background: #0A0E1A;
            background-image: radial-gradient(circle at 50% 0%, #1a1f2e 0%, #0a0e1a 50%);
            color: #FFFFFF;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .nav {
            display: flex;
            gap: 20px;
            margin-bottom: 30px;
            padding: 15px;
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
        }
        .nav a {
            color: #8B92A8;
            text-decoration: none;
            font-weight: 600;
            font-size: 14px;
        }
        .nav a:hover { color: #5B7CFF; }
        .history-card {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 16px;
        }
        .explanation {
            background: rgba(91,124,255,0.1);
            border-left: 3px solid #5B7CFF;
            padding: 12px;
            margin-top: 12px;
            border-radius: 8px;
            font-size: 14px;
            line-height: 1.6;
        }
        .loading { text-align: center; padding: 40px; color: #8B92A8; }
        .empty { text-align: center; padding: 60px; color: #8B92A8; }
    </style>
</head>
<body>
    <div class="container">
        <div class="nav">
            <a href="/dashboard">📊 Dashboard</a>
            <a href="/alerts/history">📜 History</a>
            <a href="/radar">🚨 Radar</a>
            <a href="/portfolio">💼 Portfolio</a>
            <a href="/bitcoin-scanner">₿ Bitcoin</a>
            <a href="#" onclick="logout()">Logout</a>
        </div>
        
        <h1 style="font-size: 32px; font-weight: 700; margin-bottom: 24px;">Triggered Alerts</h1>
        
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
                    container.innerHTML = '<div class="empty">No triggered alerts yet</div>';
                    return;
                }
                
                container.innerHTML = data.history.map(record => {
                    const date = new Date(record.triggered_at).toLocaleString();
                    
                    return `
                        <div class="history-card">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
                                <span style="font-size: 20px; font-weight: 700;">${record.ticker}</span>
                                <span style="font-size: 13px; color: #8B92A8;">${date}</span>
                            </div>
                            
                            <div style="font-size: 18px; font-weight: 600; margin-bottom: 12px;">
                                Triggered at: $${record.price_at_trigger?.toFixed(2) || 'N/A'}
                            </div>
                            
                            ${record.explanation ? `
                            <div class="explanation">
                                <strong>🤖 AI Insight:</strong> ${record.explanation}
                            </div>
                            ` : ''}
                        </div>
                    `;
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
<html>
<head>
    <title>Market Radar</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', sans-serif;
            background: #0A0E1A;
            background-image: radial-gradient(circle at 50% 0%, #1a1f2e 0%, #0a0e1a 50%);
            color: #FFFFFF;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .nav {
            display: flex;
            gap: 20px;
            margin-bottom: 30px;
            padding: 15px;
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
        }
        .nav a {
            color: #8B92A8;
            text-decoration: none;
            font-weight: 600;
            font-size: 14px;
        }
        .nav a:hover { color: #5B7CFF; }
        .anomaly-card {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 12px;
            position: relative;
        }
        .anomaly-card.high::before {
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            width: 4px;
            height: 100%;
            background: #FF6B6B;
        }
        .loading { text-align: center; padding: 40px; color: #8B92A8; }
        .empty { text-align: center; padding: 60px; color: #8B92A8; }
    </style>
</head>
<body>
    <div class="container">
        <div class="nav">
            <a href="/dashboard">📊 Dashboard</a>
            <a href="/alerts/history">📜 History</a>
            <a href="/radar">🚨 Radar</a>
            <a href="/portfolio">💼 Portfolio</a>
            <a href="/bitcoin-scanner">₿ Bitcoin</a>
            <a href="#" onclick="logout()">Logout</a>
        </div>
        
        <h1 style="font-size: 32px; font-weight: 700; margin-bottom: 8px;">Market Radar</h1>
        <p style="color: #8B92A8; font-size: 14px; margin-bottom: 24px;">Unusual activity in your watchlist</p>
        
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
                    container.innerHTML = '<div class="empty">No anomalies detected</div>';
                    return;
                }
                
                container.innerHTML = data.anomalies.map(anomaly => {
                    const metrics = anomaly.metrics || {};
                    const date = new Date(anomaly.detected_at).toLocaleString();
                    
                    return `
                        <div class="anomaly-card ${anomaly.severity}">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
                                <span style="font-size: 20px; font-weight: 700;">${anomaly.ticker}</span>
                                <span style="font-size: 13px; color: #8B92A8;">${date}</span>
                            </div>
                            
                            ${anomaly.anomaly_type === 'BIG_MOVE' ? `
                            <div style="font-size: 14px; color: #8B92A8;">
                                Price moved <strong style="color: ${metrics.direction === 'up' ? '#00FFA3' : '#FF6B6B'};">
                                ${metrics.pct_change > 0 ? '+' : ''}${metrics.pct_change?.toFixed(2)}%
                                </strong> to $${metrics.current_price?.toFixed(2)}
                            </div>
                            ` : ''}
                        </div>
                    `;
                }).join('');
                
            } catch (error) {
                console.error('Error loading radar:', error);
                container.innerHTML = '<div class="empty">Failed to load radar</div>';
            }
        }
        
        async function logout() {
            await fetch('/api/logout');
            window.location.href = '/login';
        }
        
        loadRadar();
        setInterval(loadRadar, 60000);
    </script>
</body>
</html>
    """
    return render_template_string(html)

# ============================================
# FOREX AMD ROUTES
# ============================================

@app.route('/forex-amd')
@login_required
def forex_amd_page():
    """Forex AMD detection page"""
    html = """
<!DOCTYPE html>
<html>
<head>
    <title>Forex AMD Scanner</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://unpkg.com/lightweight-charts@4/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', sans-serif;
            background: #0A0E1A;
            background-image: radial-gradient(circle at 50% 0%, #1a1f2e 0%, #0a0e1a 50%);
            color: #FFFFFF;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        .nav {
            display: flex;
            gap: 20px;
            margin-bottom: 30px;
            padding: 15px;
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
        }
        .nav a {
            color: #8B92A8;
            text-decoration: none;
            font-weight: 600;
            font-size: 14px;
        }
        .nav a:hover { color: #5B7CFF; }
        .section {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 20px;
        }
        .amd-card {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
        }
        .amd-card.bullish { border-left: 4px solid #00FFA3; }
        .amd-card.bearish { border-left: 4px solid #FF6B6B; }
        .quality-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        .quality-high { background: rgba(0,255,163,0.2); color: #00FFA3; }
        .quality-medium { background: rgba(255,184,0,0.2); color: #FFB800; }
        input {
            padding: 12px;
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            background: rgba(255,255,255,0.05);
            color: white;
            font-size: 14px;
        }
        button {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-weight: 600;
            cursor: pointer;
        }
        button:hover { opacity: 0.9; }
        .tf-btn { padding: 8px 18px; font-size: 13px; }
        .tf-btn.active { background: linear-gradient(135deg, #00FFA3, #00B37A); }
        select.chart-select {
            padding: 8px 12px;
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            background: rgba(255,255,255,0.05);
            color: white;
            font-size: 14px;
            cursor: pointer;
        }
        #amd-chart { border-radius: 8px; overflow: hidden; }
        #chart-error { color: #FF6B6B; font-size: 13px; margin-top: 8px; display: none; }
    </style>
</head>
<body>
    <div class="container">
        <div class="nav">
            <a href="/dashboard">📊 Dashboard</a>
            <a href="/alerts/history">📜 History</a>
            <a href="/radar">🚨 Radar</a>
            <a href="/forex-amd">🌐 Forex AMD</a>
            <a href="/forex-amd/debug">🔬 AMD Debug</a>
            <a href="/portfolio">💼 Portfolio</a>
            <a href="#" onclick="logout()">Logout</a>
        </div>

        <h1 style="font-size: 32px; font-weight: 700; margin-bottom: 8px;">Forex AMD Scanner</h1>
        <p style="color: #8B92A8; font-size: 14px; margin-bottom: 24px;">
            Institutional-grade AMD detection: Accumulation → Manipulation → Displacement → IFVG
        </p>
        
        <div class="section">
            <h2 style="margin-bottom: 16px;">Watchlist</h2>
            <div style="display: flex; gap: 12px; margin-bottom: 16px;">
                <input type="text" id="symbolInput" placeholder="Add symbol (e.g., EURUSD)" style="flex: 1;">
                <button onclick="addSymbol()">Add to Watchlist</button>
            </div>
            <div id="watchlistContainer"></div>
        </div>
        
        <div class="section">
            <h2 style="margin-bottom: 16px;">AMD Setups</h2>
            <div id="alertsContainer">
                <div style="text-align: center; padding: 40px; color: #8B92A8;">
                    Loading...
                </div>
            </div>
        </div>

        <!-- ── Candlestick Chart ─────────────────────────────────────────── -->
        <div class="section">
            <div style="display:flex; align-items:center; gap:16px; margin-bottom:16px; flex-wrap:wrap;">
                <h2>Chart</h2>
                <select id="chartSymbolSelect" class="chart-select" onchange="loadChart()">
                    <option value="">-- Select symbol --</option>
                </select>
                <div style="display:flex; gap:8px;">
                    <button id="tf-5min"  class="tf-btn" onclick="setTf('5min')">5M</button>
                    <button id="tf-15min" class="tf-btn active" onclick="setTf('15min')">15M</button>
                    <button id="tf-1h"    class="tf-btn" onclick="setTf('1h')">1H</button>
                </div>
                <span id="chart-state-badge" style="font-size:12px; color:#8B92A8;"></span>
            </div>
            <div id="amd-chart" style="height:420px; width:100%;"></div>
            <div id="chart-error"></div>
            <div style="margin-top:10px; font-size:12px; color:#555; line-height:1.6;">
                <span style="color:#FFB800;">&#9472;&#9472;</span> Accum box &nbsp;
                <span style="color:#00FFA3;">&#9472;&#9472;</span> Sweep (bull) &nbsp;
                <span style="color:#FF6B6B;">&#9472;&#9472;</span> Sweep (bear) &nbsp;
                <span style="color:#5B7CFF;">&#9472;&#9472;</span> IFVG zone &nbsp;
                &#9650; Trigger
            </div>
        </div>
    </div>
    
    <script>
        // ── Watchlist ────────────────────────────────────────────────────────
        async function loadWatchlist() {
            const res = await fetch('/api/forex-amd/watchlist');
            const data = await res.json();

            const container = document.getElementById('watchlistContainer');
            if (data.symbols.length === 0) {
                container.innerHTML = '<p style="color: #8B92A8;">No symbols in watchlist. Add some above.</p>';
            } else {
                container.innerHTML = data.symbols.map(s => `
                    <span style="display:inline-flex;align-items:center;gap:8px;margin:4px;padding:8px 16px;background:rgba(255,255,255,0.1);border-radius:8px;">
                        ${s}
                        <button onclick="removeSymbol('${s}')" style="padding:2px 8px;font-size:12px;background:rgba(255,107,107,0.3);border-radius:4px;cursor:pointer;" title="Remove">&#x2715;</button>
                    </span>
                `).join('');
            }
            updateChartSymbolSelect(data.symbols || []);
        }

        async function removeSymbol(symbol) {
            await fetch('/api/forex-amd/watchlist', {
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
            await fetch('/api/forex-amd/watchlist', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({symbol})
            });
            input.value = '';
            loadWatchlist();
        }

        // ── AMD Setups ───────────────────────────────────────────────────────
        async function loadAlerts() {
            const res = await fetch('/api/forex-amd/alerts');
            const data = await res.json();
            const container = document.getElementById('alertsContainer');
            if (data.alerts.length === 0) {
                container.innerHTML = '<div style="text-align:center;padding:40px;color:#8B92A8;">No AMD setups detected yet</div>';
                return;
            }
            container.innerHTML = data.alerts.map(alert => {
                const qualityClass = alert.setup_quality >= 8 ? 'quality-high' : 'quality-medium';
                const dirClass = alert.direction === 'bullish' ? 'bullish' : 'bearish';
                const date = new Date(alert.detected_at).toLocaleString();
                return `
                    <div class="amd-card ${dirClass}">
                        <div style="display:flex;justify-content:space-between;margin-bottom:12px;">
                            <span style="font-size:20px;font-weight:700;">${alert.symbol}</span>
                            <span class="quality-badge ${qualityClass}">Quality: ${alert.setup_quality}/10</span>
                        </div>
                        <div style="margin-bottom:8px;">
                            <strong style="color:${alert.direction==='bullish'?'#00FFA3':'#FF6B6B'};">
                                ${alert.direction.toUpperCase()}
                            </strong> setup detected during ${alert.session} session
                        </div>
                        <div style="font-size:13px;color:#8B92A8;">
                            Sweep: ${alert.sweep_level} | IFVG: ${alert.ifvg_low} - ${alert.ifvg_high}
                        </div>
                        <div style="font-size:12px;color:#666;margin-top:8px;">${date}</div>
                    </div>
                `;
            }).join('');
        }

        async function logout() {
            await fetch('/api/logout');
            window.location.href = '/login';
        }

        // ── Candlestick Chart ────────────────────────────────────────────────
        let _chart = null;
        let _candleSeries = null;
        let _currentTf = '15min';
        let _priceLines = [];

        function initChart() {
            const el = document.getElementById('amd-chart');
            if (!el || typeof LightweightCharts === 'undefined') return;
            _chart = LightweightCharts.createChart(el, {
                width: el.clientWidth,
                height: 420,
                layout: {
                    background: { color: '#0d1117' },
                    textColor: '#8B92A8',
                },
                grid: {
                    vertLines: { color: 'rgba(255,255,255,0.04)' },
                    horzLines: { color: 'rgba(255,255,255,0.04)' },
                },
                crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
                rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
                timeScale: {
                    borderColor: 'rgba(255,255,255,0.1)',
                    timeVisible: true,
                    secondsVisible: false,
                },
            });
            _candleSeries = _chart.addCandlestickSeries({
                upColor:        '#00FFA3',
                downColor:      '#FF6B6B',
                borderUpColor:  '#00FFA3',
                borderDownColor:'#FF6B6B',
                wickUpColor:    '#00FFA3',
                wickDownColor:  '#FF6B6B',
            });
            new ResizeObserver(() => {
                if (_chart) _chart.applyOptions({ width: el.clientWidth });
            }).observe(el);
        }

        function setTf(tf) {
            _currentTf = tf;
            ['5min','15min','1h'].forEach(t => {
                const b = document.getElementById('tf-' + t);
                if (b) b.className = 'tf-btn' + (t === tf ? ' active' : '');
            });
            loadChart();
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
            if (!sel.value && symbols.length) {
                sel.value = symbols[0];
                loadChart();
            }
        }

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
                    '/api/forex-amd/candles?symbol=' + encodeURIComponent(sym) +
                    '&interval=' + _currentTf + '&limit=200'
                );
                const data = await res.json();
                if (data.error) throw new Error(data.error);
                _candleSeries.setData(data);
                _chart.timeScale().fitContent();
                await loadOverlays(sym);
            } catch(e) {
                errEl.textContent = 'Chart error: ' + e.message;
                errEl.style.display = 'block';
            }
        }

        async function loadOverlays(sym) {
            // Remove old price lines
            _priceLines.forEach(pl => { try { _candleSeries.removePriceLine(pl); } catch(_) {} });
            _priceLines = [];
            _candleSeries.setMarkers([]);

            const badge = document.getElementById('chart-state-badge');
            if (badge) badge.textContent = '';

            try {
                const res = await fetch('/api/forex-amd/overlay?symbol=' + encodeURIComponent(sym));
                const data = await res.json();
                if (!data.success) return;
                const ov = data.overlay;

                if (badge && ov.state) badge.textContent = 'State: ' + ov.state;

                // Accumulation box – two dotted lines
                if (ov.accumulation && ov.accumulation.high != null) {
                    _priceLines.push(_candleSeries.createPriceLine({
                        price: ov.accumulation.high, color: '#FFB800', lineWidth: 1,
                        lineStyle: LightweightCharts.LineStyle.Dotted,
                        axisLabelVisible: true, title: 'Accum H',
                    }));
                    _priceLines.push(_candleSeries.createPriceLine({
                        price: ov.accumulation.low, color: '#FFB800', lineWidth: 1,
                        lineStyle: LightweightCharts.LineStyle.Dotted,
                        axisLabelVisible: true, title: 'Accum L',
                    }));
                }

                // Sweep level – dashed line
                if (ov.sweep && ov.sweep.level != null) {
                    const sweepColor = ov.sweep.direction === 'bullish' ? '#00FFA3' : '#FF6B6B';
                    _priceLines.push(_candleSeries.createPriceLine({
                        price: ov.sweep.level, color: sweepColor, lineWidth: 2,
                        lineStyle: LightweightCharts.LineStyle.Dashed,
                        axisLabelVisible: true,
                        title: 'Sweep (' + (ov.sweep.direction || '') + ')',
                    }));
                }

                // IFVG zone – two dashed blue lines
                if (ov.ifvg && ov.ifvg.high != null) {
                    _priceLines.push(_candleSeries.createPriceLine({
                        price: ov.ifvg.high, color: '#5B7CFF', lineWidth: 1,
                        lineStyle: LightweightCharts.LineStyle.Dashed,
                        axisLabelVisible: true, title: 'IFVG H',
                    }));
                    _priceLines.push(_candleSeries.createPriceLine({
                        price: ov.ifvg.low, color: '#5B7CFF', lineWidth: 1,
                        lineStyle: LightweightCharts.LineStyle.Dashed,
                        axisLabelVisible: true, title: 'IFVG L',
                    }));
                }

                // Trigger marker
                if (ov.trigger && ov.trigger.time) {
                    const ts = Math.floor(new Date(ov.trigger.time).getTime() / 1000);
                    _candleSeries.setMarkers([{
                        time:     ts,
                        position: ov.trigger.direction === 'bullish' ? 'belowBar' : 'aboveBar',
                        color:    ov.trigger.direction === 'bullish' ? '#00FFA3' : '#FF6B6B',
                        shape:    ov.trigger.direction === 'bullish' ? 'arrowUp' : 'arrowDown',
                        text:     'AMD',
                    }]);
                }
            } catch(_) { /* overlay errors are non-fatal */ }
        }

        // ── Boot ─────────────────────────────────────────────────────────────
        loadWatchlist();
        loadAlerts();
        setInterval(loadAlerts, 60000);
    </script>
</body>
</html>
    """
    return render_template_string(html)


@app.route('/api/forex-amd/watchlist', methods=['GET', 'POST', 'DELETE'])
@login_required
def manage_forex_watchlist():
    """Manage user's forex watchlist"""
    if request.method == 'POST':
        symbol = request.json.get('symbol', '').upper().strip()
        
        if not symbol:
            return jsonify({'success': False, 'error': 'Symbol required'}), 400
        
        try:
            db.execute("""
                INSERT INTO forex_watchlist (user_id, symbol)
                VALUES (%s, %s)
                ON CONFLICT (user_id, symbol) DO NOTHING
            """, (current_user.id, symbol))
            
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"Error adding to watchlist: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'DELETE':
        symbol = request.json.get('symbol')
        db.execute("""
            DELETE FROM forex_watchlist
            WHERE user_id = %s AND symbol = %s
        """, (current_user.id, symbol))
        return jsonify({'success': True})
    
    else:  # GET
        watchlist = db.execute("""
            SELECT symbol FROM forex_watchlist
            WHERE user_id = %s
            ORDER BY added_at DESC
        """, (current_user.id,), fetchall=True)
        
        return jsonify({
            'success': True,
            'symbols': [w['symbol'] for w in watchlist] if watchlist else []
        })


@app.route('/api/forex-amd/alerts')
@login_required
def get_forex_amd_alerts():
    """Get user's AMD alerts"""
    try:
        alerts = db.execute("""
            SELECT * FROM forex_amd_alerts
            WHERE user_id = %s
            ORDER BY detected_at DESC
            LIMIT 50
        """, (current_user.id,), fetchall=True)
        
        return jsonify({
            'success': True,
            'alerts': alerts if alerts else []
        })
    except Exception as e:
        logger.error(f"Error fetching AMD alerts: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/forex-amd/health')
@login_required
def forex_amd_health():
    """AMD scanner health — last run timestamps + error info."""
    try:
        row = db.execute(
            "SELECT * FROM forex_amd_health WHERE id = 1",
            fetchone=True,
        )
        from services.forex_amd_detector import AMDConfig
        from datetime import datetime, timezone
        threshold_min = AMDConfig.UNHEALTHY_THRESHOLD_MINUTES
        healthy = False
        age_min = None
        if row and row.get('last_ok_at'):
            last_ok = row['last_ok_at']
            if last_ok.tzinfo is None:
                last_ok = last_ok.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - last_ok).total_seconds() / 60
            healthy = age_min <= threshold_min
        return jsonify({
            'success': True,
            'healthy': healthy,
            'threshold_minutes': threshold_min,
            'age_minutes': round(age_min, 1) if age_min is not None else None,
            'last_run_at':    row['last_run_at'].isoformat()    if row and row['last_run_at']    else None,
            'last_ok_at':     row['last_ok_at'].isoformat()     if row and row['last_ok_at']     else None,
            'last_error_at':  row['last_error_at'].isoformat()  if row and row['last_error_at']  else None,
            'last_error_msg': row['last_error_msg']             if row else None,
            'last_symbols_count': row['last_symbols_count']     if row else 0,
        })
    except Exception as e:
        logger.error(f"[AMD_FOREX] health endpoint error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/forex-amd/state')
@login_required
def forex_amd_state_snapshot():
    """Current state-machine snapshot per symbol for the logged-in user."""
    try:
        STATE_NAMES = {
            0: 'IDLE', 1: 'ACCUMULATION', 2: 'SWEEP_DETECTED',
            3: 'DISPLACEMENT_CONFIRMED', 4: 'WAIT_IFVG',
        }
        rows = db.execute("""
            SELECT symbol, current_state, last_update
            FROM forex_amd_state
            WHERE user_id = %s
            ORDER BY symbol
        """, (current_user.id,), fetchall=True)
        states = [
            {
                'symbol':      r['symbol'],
                'state_id':    r['current_state'],
                'state_name':  STATE_NAMES.get(r['current_state'], 'UNKNOWN'),
                'last_update': r['last_update'].isoformat() if r['last_update'] else None,
            }
            for r in (rows or [])
        ]
        return jsonify({'success': True, 'states': states, 'count': len(states)})
    except Exception as e:
        logger.error(f"[AMD_FOREX] state endpoint error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/forex-amd/recent-events')
@login_required
def forex_amd_recent_events():
    """Last 20 AMD alerts/triggers for the logged-in user (read-only history)."""
    try:
        rows = db.execute("""
            SELECT symbol, direction, session, setup_quality,
                   sweep_level, ifvg_high, ifvg_low, detected_at
            FROM forex_amd_alerts
            WHERE user_id = %s
            ORDER BY detected_at DESC
            LIMIT 20
        """, (current_user.id,), fetchall=True)
        events = [dict(r) for r in (rows or [])]
        for ev in events:
            if ev.get('detected_at'):
                ev['detected_at'] = ev['detected_at'].isoformat()
        return jsonify({'success': True, 'events': events})
    except Exception as e:
        logger.error(f"[AMD_FOREX] recent-events endpoint error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# In-memory candle cache: cache_key -> (monotonic_timestamp, data_list)
# ---------------------------------------------------------------------------
_candle_cache: dict = {}
_CANDLE_CACHE_TTL = 60  # seconds – refresh at most once per minute per symbol+tf


@app.route('/api/forex-amd/candles')
@login_required
def forex_amd_candles():
    """OHLC candles for LightweightCharts.
    GET /api/forex-amd/candles?symbol=EURUSD&interval=15min&limit=200
    Returns [{time, open, high, low, close}, …] sorted ascending by time.
    """
    from services.forex_data_provider import forex_data_provider

    symbol = request.args.get('symbol', '').strip().upper()
    interval = request.args.get('interval', '15min').strip().lower()
    try:
        limit = min(int(request.args.get('limit', 200)), 500)
    except ValueError:
        limit = 200

    if not symbol:
        return jsonify({'error': 'symbol required'}), 400

    _IV = {
        '5m': '5m', '5min': '5m',
        '15m': '15m', '15min': '15m',
        '1h': '1h', '1hour': '1h',
    }
    tf = _IV.get(interval, '15m')

    cache_key = f"{symbol}:{tf}"
    now_mono = time.monotonic()
    cached = _candle_cache.get(cache_key)
    if cached and (now_mono - cached[0]) < _CANDLE_CACHE_TTL:
        return jsonify(cached[1])

    candles = forex_data_provider.get_recent_candles(symbol, timeframe=tf, count=limit)
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


@app.route('/api/forex-amd/overlay')
@login_required
def forex_amd_overlay():
    """Current state-machine overlay data for drawing on the chart.
    Returns accumulation box, sweep level, IFVG zone, and trigger marker.
    GET /api/forex-amd/overlay?symbol=EURUSD
    """
    symbol = request.args.get('symbol', '').strip().upper()
    if not symbol:
        return jsonify({'error': 'symbol required'}), 400

    try:
        state_row = db.execute(
            """SELECT current_state, accumulation_data, sweep_data, last_update
               FROM forex_amd_state
               WHERE user_id = %s AND symbol = %s""",
            (current_user.id, symbol), fetchone=True,
        )
        alert_row = db.execute(
            """SELECT sweep_level, sweep_time, ifvg_high, ifvg_low, ifvg_time,
                      direction, detected_at
               FROM forex_amd_alerts
               WHERE user_id = %s AND symbol = %s
               ORDER BY detected_at DESC LIMIT 1""",
            (current_user.id, symbol), fetchone=True,
        )

        STATE_NAMES = {
            0: 'IDLE', 1: 'ACCUMULATION', 2: 'SWEEP_DETECTED',
            3: 'DISPLACEMENT_CONFIRMED', 4: 'WAIT_IFVG',
        }

        overlay = {'state': None, 'accumulation': None, 'sweep': None,
                   'ifvg': None, 'trigger': None}

        if state_row:
            overlay['state'] = STATE_NAMES.get(state_row['current_state'], 'UNKNOWN')

            if state_row['accumulation_data']:
                raw = state_row['accumulation_data']
                accum = json.loads(raw) if isinstance(raw, str) else raw
                overlay['accumulation'] = {
                    'high': accum.get('high'),
                    'low':  accum.get('low'),
                }

            if state_row['sweep_data']:
                raw = state_row['sweep_data']
                sweep = json.loads(raw) if isinstance(raw, str) else raw
                overlay['sweep'] = {
                    'level':     sweep.get('level'),
                    'direction': sweep.get('direction'),
                }

        if alert_row:
            overlay['ifvg'] = {
                'high': float(alert_row['ifvg_high']) if alert_row.get('ifvg_high') else None,
                'low':  float(alert_row['ifvg_low'])  if alert_row.get('ifvg_low')  else None,
                'time': alert_row['ifvg_time'].isoformat() if alert_row.get('ifvg_time') else None,
            }
            overlay['trigger'] = {
                'time':      alert_row['detected_at'].isoformat() if alert_row.get('detected_at') else None,
                'direction': alert_row.get('direction'),
            }
            if alert_row.get('sweep_level') and not overlay['sweep']:
                overlay['sweep'] = {
                    'level':     float(alert_row['sweep_level']),
                    'direction': alert_row.get('direction'),
                }

        return jsonify({'success': True, 'symbol': symbol, 'overlay': overlay})
    except Exception as e:
        logger.error(f"[AMD_FOREX] overlay endpoint error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/forex-amd/debug')
@login_required
def forex_amd_debug_page():
    """Read-only AMD debug/monitoring page."""
    html = """<!DOCTYPE html>
<html>
<head>
  <title>AMD Debug</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    * { margin:0; padding:0; box-sizing:border-box; }
    body { font-family: monospace; background:#0A0E1A; color:#ccc; padding:20px; }
    h2   { color:#5B7CFF; margin-bottom:16px; }
    h3   { color:#8B92A8; font-size:14px; margin-bottom:10px; }
    .card{ background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.1);
           border-radius:10px; padding:16px; margin-bottom:16px; }
    .ok   { color:#00FFA3; }
    .err  { color:#FF6B6B; }
    .warn { color:#FFB800; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th,td { text-align:left; padding:6px 10px;
            border-bottom:1px solid rgba(255,255,255,.07); }
    th    { color:#5B7CFF; }
    pre   { white-space:pre-wrap; font-size:12px; color:#aaa; }
    .nav  { display:flex; gap:20px; margin-bottom:24px;
            padding:12px; background:rgba(255,255,255,.05); border-radius:10px; }
    .nav a{ color:#8B92A8; text-decoration:none; font-weight:600; font-size:14px; }
    .nav a:hover { color:#5B7CFF; }
    .badge{ display:inline-block; padding:3px 10px; border-radius:8px;
            font-size:12px; font-weight:700; }
    .badge-ok  { background:rgba(0,255,163,.15); color:#00FFA3; }
    .badge-err { background:rgba(255,107,107,.15); color:#FF6B6B; }
    .refresh-note { font-size:11px; color:#555; margin-left:auto; }
  </style>
</head>
<body>
  <div class="nav">
    <a href="/forex-amd">&larr; Forex AMD</a>
    <a href="/dashboard">Dashboard</a>
    <span class="refresh-note" id="last-refresh"></span>
  </div>

  <h2>AMD Debug Dashboard</h2>

  <div class="card" id="health-card">
    <h3>Scanner Health <span id="health-badge"></span></h3>
    <pre id="health-data">Loading...</pre>
  </div>

  <div class="card">
    <h3>State Machine Snapshot</h3>
    <table>
      <thead><tr><th>Symbol</th><th>State</th><th>Last Update</th></tr></thead>
      <tbody id="state-rows"><tr><td colspan="3">Loading...</td></tr></tbody>
    </table>
  </div>

  <div class="card">
    <h3>Recent Triggers (last 20)</h3>
    <table>
      <thead><tr>
        <th>Symbol</th><th>Direction</th><th>Quality</th>
        <th>Session</th><th>Detected At</th>
      </tr></thead>
      <tbody id="event-rows"><tr><td colspan="5">Loading...</td></tr></tbody>
    </table>
  </div>

<script>
const STATE_COLOR = {
  IDLE: '#8B92A8',
  ACCUMULATION: '#FFB800',
  SWEEP_DETECTED: '#5B7CFF',
  DISPLACEMENT_CONFIRMED: '#00FFA3',
  WAIT_IFVG: '#FF6B6B'
};

async function load() {
  try {
    const h = await fetch('/api/forex-amd/health').then(r => r.json());
    const badge = document.getElementById('health-badge');
    badge.innerHTML = h.healthy
      ? '<span class="badge badge-ok">HEALTHY</span>'
      : '<span class="badge badge-err">UNHEALTHY</span>';
    document.getElementById('health-data').textContent = JSON.stringify({
      healthy:            h.healthy,
      age_minutes:        h.age_minutes,
      threshold_minutes:  h.threshold_minutes,
      last_run_at:        h.last_run_at,
      last_ok_at:         h.last_ok_at,
      last_error_at:      h.last_error_at,
      last_error_msg:     h.last_error_msg,
      last_symbols_count: h.last_symbols_count
    }, null, 2);
  } catch(e) {
    document.getElementById('health-data').textContent = 'Error: ' + e;
  }

  try {
    const s = await fetch('/api/forex-amd/state').then(r => r.json());
    document.getElementById('state-rows').innerHTML =
      (s.states && s.states.length)
        ? s.states.map(r =>
            '<tr><td>' + r.symbol + '</td>' +
            '<td style="color:' + (STATE_COLOR[r.state_name] || '#ccc') + '">' + r.state_name + '</td>' +
            '<td>' + (r.last_update || '-') + '</td></tr>'
          ).join('')
        : '<tr><td colspan="3" style="color:#555">No symbols in watchlist</td></tr>';
  } catch(e) {
    document.getElementById('state-rows').innerHTML =
      '<tr><td colspan="3" class="err">Error: ' + e + '</td></tr>';
  }

  try {
    const ev = await fetch('/api/forex-amd/recent-events').then(r => r.json());
    document.getElementById('event-rows').innerHTML =
      (ev.events && ev.events.length)
        ? ev.events.map(e =>
            '<tr><td>' + e.symbol + '</td>' +
            '<td class="' + (e.direction === 'bullish' ? 'ok' : 'err') + '">' + e.direction + '</td>' +
            '<td>' + e.setup_quality + '/10</td>' +
            '<td>' + e.session + '</td>' +
            '<td>' + e.detected_at + '</td></tr>'
          ).join('')
        : '<tr><td colspan="5" style="color:#555">No triggers yet</td></tr>';
  } catch(e) {
    document.getElementById('event-rows').innerHTML =
      '<tr><td colspan="5" class="err">Error: ' + e + '</td></tr>';
  }

  document.getElementById('last-refresh').textContent =
    'Auto-refreshes every 30s — Last: ' + new Date().toLocaleTimeString();
}

load();
setInterval(load, 30000);
</script>
</body>
</html>"""
    return html


# Gunicorn will run the app, this is only for local testing
if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
