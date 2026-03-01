"""
Flask Blueprint – Fundamentals Reports routes.

Register in app.py:
    from fundamentals_routes import fundamentals_bp
    app.register_blueprint(fundamentals_bp)

Routes
------
GET  /fundamentals                          – Tab landing page (ticker search + filing list)
GET  /api/filings/<ticker>                  – JSON list of available filings
POST /api/reports/generate                  – Generate (or return cached) report
GET  /api/reports/<ticker>/<filing_id>      – Return cached ReportData/v1 JSON
GET  /reports/<ticker>/<filing_id>          – Render cached HTML report
"""

import json
import logging
import threading

from flask import (
    Blueprint, jsonify, render_template, render_template_string,
    request, abort, current_app,
)
from flask_login import login_required

from providers.sec_provider import list_filings as sec_list_filings
from providers.consensus_provider import get_consensus
from services.report_generator import (
    generate_report,
    get_cached_report_json,
    get_cached_report_html,
)
from services.llm_client import get_llm_client, PRE_EARNINGS_PROMPT

logger = logging.getLogger(__name__)

fundamentals_bp = Blueprint("fundamentals", __name__)

# --------------------------------------------------------------------------- #
# Async generation state  (in-process; safe with --workers 1)
# --------------------------------------------------------------------------- #
_gen_lock   = threading.Lock()
_gen_status: dict = {}  # filing_id -> {"status": "generating"|"done"|"error", ...}


def _run_generation(app, ticker: str, filing_id: str, force: bool) -> None:
    """Generate a report in a background thread, updating _gen_status when done."""
    with app.app_context():
        try:
            result = generate_report(
                ticker=ticker,
                filing_id=filing_id,
                force=force,
                render_fn=render_template,
            )
            with _gen_lock:
                if result.get("status") == "error":
                    _gen_status[filing_id] = {
                        "status": "error",
                        "error":  result.get("error", "Unknown error"),
                    }
                else:
                    _gen_status[filing_id] = {
                        "status":   "done",
                        "url_html": result.get("url_html", ""),
                        "url_json": result.get("url_json", ""),
                    }
        except Exception as exc:
            logger.exception("Background generation failed for %s %s", ticker, filing_id)
            with _gen_lock:
                _gen_status[filing_id] = {"status": "error", "error": str(exc)}


# =========================================================================== #
# Fundamentals landing page
# =========================================================================== #

_TAB_HTML = """
<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Fundamentals — Stock Alerts</title>
  <link rel="stylesheet" href="/static/css/theme.css">
  <style>
    body { background: #0A0E1A; color: #E2E8F0; font-family: 'Inter', sans-serif; }
    .page-wrap   { max-width: 900px; margin: 0 auto; padding: 40px 24px; }
    .page-title  { font-size: 24px; font-weight: 700; margin-bottom: 8px; }
    .page-sub    { color: #64748B; margin-bottom: 32px; font-size: 14px; }
    .search-row  { display: flex; gap: 12px; margin-bottom: 32px; }
    .search-row input {
      flex: 1; padding: 12px 16px; border-radius: 10px;
      background: #111827; border: 1px solid #1E2D45;
      color: #E2E8F0; font-size: 15px; font-family: inherit;
    }
    .search-row input:focus { outline: none; border-color: #5B7CFF; }
    .btn {
      padding: 12px 24px; border-radius: 10px; border: none;
      background: #5B7CFF; color: #fff; font-size: 14px; font-weight: 600;
      cursor: pointer; font-family: inherit;
    }
    .btn:hover { background: #4A6AE8; }
    .btn:disabled { opacity: .5; cursor: not-allowed; }
    .filings-section { display: none; }
    .filings-header  { font-size: 13px; font-weight: 600; color: #64748B;
                        text-transform: uppercase; letter-spacing: .5px;
                        margin-bottom: 12px; }
    .filing-card {
      display: flex; align-items: center; justify-content: space-between;
      gap: 12px; padding: 16px 20px;
      background: #111827; border: 1px solid #1E2D45; border-radius: 10px;
      margin-bottom: 8px; transition: border-color .2s;
    }
    .filing-card:hover { border-color: #5B7CFF; }
    .filing-badge {
      padding: 3px 10px; border-radius: 6px; font-size: 11px; font-weight: 700;
      background: rgba(91,124,255,.15); color: #5B7CFF; flex-shrink: 0;
    }
    .filing-period { font-size: 13px; color: #94A3B8; }
    .filing-title  { font-size: 14px; font-weight: 500; flex: 1; }
    .filing-actions { display: flex; gap: 8px; }
    .btn-sm {
      padding: 7px 14px; border-radius: 8px; border: none; cursor: pointer;
      font-size: 12px; font-weight: 600; font-family: inherit;
    }
    .btn-view { background: rgba(91,124,255,.15); color: #5B7CFF; }
    .btn-view:hover { background: rgba(91,124,255,.3); }
    .btn-gen  { background: #5B7CFF; color: #fff; }
    .btn-gen:hover { background: #4A6AE8; }
    .status-box {
      padding: 12px 16px; border-radius: 8px; font-size: 13px;
      margin-top: 16px; display: none;
    }
    .status-box.info    { background: rgba(91,124,255,.1); color: #5B7CFF; border: 1px solid rgba(91,124,255,.3); }
    .status-box.success { background: rgba(0,208,132,.1);  color: #00D084; border: 1px solid rgba(0,208,132,.3); }
    .status-box.error   { background: rgba(255,71,87,.1);  color: #FF4757; border: 1px solid rgba(255,71,87,.3); }
    .spinner {
      display: inline-block; width: 14px; height: 14px;
      border: 2px solid rgba(91,124,255,.3); border-top-color: #5B7CFF;
      border-radius: 50%; animation: spin .6s linear infinite;
      vertical-align: middle; margin-left: 8px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .error-msg { color: #FF4757; font-size: 13px; margin-top: 8px; display: none; }
  </style>
</head>
<body>
<nav class="top-nav wide">
  <span class="top-nav-brand">📈 PulseAlerts</span>
  <a href="/dashboard" class="top-nav-link">📊 Alerts</a>
  <a href="/portfolio" class="top-nav-link">💼 Portfolio</a>
  <a href="/alerts/history" class="top-nav-link">📜 History</a>
  <a href="/radar" class="top-nav-link">🚨 Radar</a>
  <a href="/bitcoin-scanner" class="top-nav-link">₿ Bitcoin</a>
  <a href="/forex-amd" class="top-nav-link">🌐 Forex</a>
  <a href="/fundamentals" class="top-nav-link active">📋 Fundamentals</a>
  <span class="top-nav-spacer"></span>
  <button class="top-nav-logout" onclick="logout()">Sign out</button>
</nav>
<div class="page-wrap">
  <h1 class="page-title">📊 דוחות פונדמנטליים</h1>
  <p class="page-sub">בחר טיקר וצפה בדוחות SEC 10-K / 10-Q עם ניתוח AI</p>

  <div class="search-row">
    <input id="ticker-input" type="text" placeholder="הקלד טיקר (לדוגמה: AAPL, OKE, MSFT)"
           autocomplete="off" autocapitalize="characters">
    <button class="btn" id="search-btn" onclick="searchFilings()">חפש</button>
  </div>
  <div class="error-msg" id="search-error"></div>

  <div class="filings-section" id="filings-section">
    <div class="filings-header" id="filings-header">דוחות זמינים</div>
    <div id="filings-list"></div>
  </div>

  <div class="status-box" id="status-box"></div>
</div>

<script>
const statusBox = document.getElementById('status-box');
const searchErr  = document.getElementById('search-error');

function showStatus(msg, type) {
  statusBox.className = 'status-box ' + type;
  statusBox.innerHTML = msg;
  statusBox.style.display = 'block';
}

function hideStatus() { statusBox.style.display = 'none'; }

async function searchFilings() {
  const ticker = document.getElementById('ticker-input').value.trim().toUpperCase();
  if (!ticker) return;
  searchErr.style.display = 'none';
  hideStatus();

  const btn = document.getElementById('search-btn');
  btn.disabled = true;
  btn.textContent = 'מחפש...';

  try {
    const res  = await fetch('/api/filings/' + encodeURIComponent(ticker));
    const data = await res.json();

    if (!res.ok) {
      searchErr.textContent = data.error || 'שגיאה בחיפוש';
      searchErr.style.display = 'block';
      return;
    }

    const filings = data.filings || [];
    const sec = document.getElementById('filings-section');
    const hdr = document.getElementById('filings-header');
    const lst = document.getElementById('filings-list');

    hdr.textContent = ticker + ' — ' + filings.length + ' דוחות';
    lst.innerHTML   = '';

    if (!filings.length) {
      lst.innerHTML = '<p style="color:#64748B;font-size:13px;">לא נמצאו דוחות עבור הטיקר הזה.</p>';
    } else {
      filings.forEach(function (f) {
        const card = document.createElement('div');
        card.className = 'filing-card';
        card.innerHTML =
          '<span class="filing-badge">' + f.filing_type + '</span>' +
          '<div style="flex:1">' +
            '<div class="filing-title">' + f.title + '</div>' +
            '<div class="filing-period">הוגש: ' + (f.filed_at || '—') + '</div>' +
          '</div>' +
          '<div class="filing-actions">' +
            '<button class="btn-sm btn-view _view-btn">צפה</button>' +
            '<button class="btn-sm btn-gen _gen-btn">ייצר</button>' +
          '</div>';
        card.querySelector('._view-btn').addEventListener('click', function () { viewReport(ticker, f.filing_id); });
        card.querySelector('._gen-btn').addEventListener('click', function () { generateReport(ticker, f.filing_id); });
        lst.appendChild(card);
      });
    }
    sec.style.display = 'block';
  } catch (e) {
    searchErr.textContent = 'שגיאת רשת: ' + e;
    searchErr.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = 'חפש';
  }
}

const _pollTimers = {};

async function generateReport(ticker, filingId) {
  showStatus('שולח בקשה... <span class="spinner"></span>', 'info');
  try {
    const res  = await fetch('/api/reports/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker: ticker, filing_id: filingId, force: false }),
    });
    const data = await res.json();

    if (!res.ok) {
      showStatus('שגיאה: ' + (data.error || 'אירעה שגיאה'), 'error');
      return;
    }

    if (data.status === 'done') {
      showStatus(
        'הדוח מוכן — <a href="' + data.url_html + '" target="_blank" style="color:inherit;text-decoration:underline">פתח דוח HTML</a>',
        'success'
      );
      return;
    }

    // status === 'generating' → start polling
    _startPolling(filingId);
  } catch (e) {
    showStatus('שגיאת רשת: ' + e, 'error');
  }
}

function _startPolling(filingId) {
  showStatus('מייצר דוח... <span class="spinner"></span>', 'info');
  if (_pollTimers[filingId]) clearInterval(_pollTimers[filingId]);
  _pollTimers[filingId] = setInterval(async function () {
    try {
      const res  = await fetch('/api/reports/status/' + encodeURIComponent(filingId));
      const data = await res.json();
      if (data.status === 'done') {
        clearInterval(_pollTimers[filingId]);
        delete _pollTimers[filingId];
        showStatus(
          'הדוח מוכן — <a href="' + data.url_html + '" target="_blank" style="color:inherit;text-decoration:underline">פתח דוח HTML</a>',
          'success'
        );
      } else if (data.status === 'error') {
        clearInterval(_pollTimers[filingId]);
        delete _pollTimers[filingId];
        showStatus('שגיאה בייצור הדוח: ' + (data.error || 'שגיאה לא ידועה'), 'error');
      }
      // 'generating' or 'not_started' → keep polling
    } catch (_) { /* network glitch — keep polling */ }
  }, 3000);
}

function viewReport(ticker, filingId) {
  window.open('/reports/' + encodeURIComponent(ticker) + '/' + encodeURIComponent(filingId), '_blank');
}

document.getElementById('ticker-input').addEventListener('keydown', function (e) {
  if (e.key === 'Enter') searchFilings();
});

async function logout() {
  await fetch('/api/logout');
  window.location.href = '/login';
}
</script>
</body>
</html>
"""


@fundamentals_bp.route("/fundamentals")
@login_required
def fundamentals_tab():
    """Landing page: ticker search → filing list → generate / view."""
    return render_template_string(_TAB_HTML)


# =========================================================================== #
# API — list filings
# =========================================================================== #

@fundamentals_bp.route("/api/filings/<ticker>")
@login_required
def api_list_filings(ticker: str):
    """
    GET /api/filings/<ticker>

    Returns:
        200 { "ticker": "OKE", "filings": [...] }
        502 { "error": "..." }
        400 { "error": "..." }
    """
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        return jsonify({"error": "Invalid ticker"}), 400

    try:
        filings = sec_list_filings(ticker)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        logger.error("SEC EDGAR error for %s: %s", ticker, exc)
        return jsonify({"error": str(exc)}), 502

    result = [
        {
            "filing_id":   f["filing_id"],
            "filing_type": f["filing_type"],
            "period_end":  f["period_end"],
            "filed_at":    f["filed_at"],
            "title":       f["title"],
        }
        for f in filings
    ]
    return jsonify({"ticker": ticker, "filings": result})


# =========================================================================== #
# API — generate report
# =========================================================================== #

@fundamentals_bp.route("/api/reports/generate", methods=["POST"])
@login_required
def api_generate_report():
    """
    POST /api/reports/generate
    Body: { "ticker": "OKE", "filing_id": "0001...", "force": false }

    Returns immediately (HTTP 202) and runs generation in a background thread.
    The caller should poll GET /api/reports/status/<filing_id> for completion.

        202 { "status": "generating" }
        200 { "status": "done", "url_html": "...", "url_json": "..." }
        400 { "error": "..." }
    """
    body      = request.get_json(silent=True) or {}
    ticker    = (body.get("ticker") or "").upper().strip()
    filing_id = (body.get("filing_id") or "").strip()
    force     = bool(body.get("force", False))

    if not ticker or not filing_id:
        return jsonify({"error": "ticker and filing_id are required"}), 400

    with _gen_lock:
        current = _gen_status.get(filing_id)

    # Already finished (and not forcing a re-run) → return cached result immediately
    if current and current["status"] == "done" and not force:
        return jsonify(current), 200

    # Already running → tell client to keep polling
    if current and current["status"] == "generating":
        return jsonify({"status": "generating"}), 202

    # Start background thread
    with _gen_lock:
        _gen_status[filing_id] = {"status": "generating"}

    app = current_app._get_current_object()
    t   = threading.Thread(
        target=_run_generation,
        args=(app, ticker, filing_id, force),
        daemon=True,
    )
    t.start()

    return jsonify({"status": "generating"}), 202


@fundamentals_bp.route("/api/reports/status/<path:filing_id>")
@login_required
def api_report_status(filing_id: str):
    """
    GET /api/reports/status/<filing_id>

    Returns current generation status:
        { "status": "not_started" }
        { "status": "generating" }
        { "status": "done", "url_html": "...", "url_json": "..." }
        { "status": "error", "error": "..." }
    """
    with _gen_lock:
        status = _gen_status.get(filing_id)
    return jsonify(status or {"status": "not_started"}), 200


# =========================================================================== #
# API — get cached JSON
# =========================================================================== #

@fundamentals_bp.route("/api/reports/<ticker>/<path:filing_id>")
@login_required
def api_get_report(ticker: str, filing_id: str):
    """
    GET /api/reports/<ticker>/<filing_id>

    Returns the cached ReportData/v1 JSON or 404.
    """
    ticker = ticker.upper().strip()
    data   = get_cached_report_json(ticker, filing_id)
    if data is None:
        return jsonify({"error": "Report not found. Generate it first via POST /api/reports/generate"}), 404
    return jsonify(data)


# =========================================================================== #
# HTML — view rendered report
# =========================================================================== #

@fundamentals_bp.route("/reports/<ticker>/<path:filing_id>")
@login_required
def view_report(ticker: str, filing_id: str):
    """
    GET /reports/<ticker>/<filing_id>

    Returns the cached rendered HTML.
    If not cached, returns a 404 page directing the user to generate via the Fundamentals tab.
    """
    ticker = ticker.upper().strip()
    html   = get_cached_report_html(ticker, filing_id)

    if html:
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    return (
        "<html><body style='background:#0A0E1A;color:#E2E8F0;"
        "font-family:sans-serif;padding:40px;text-align:center'>"
        "<h2>Report not yet generated</h2>"
        "<p style='color:#94A3B8'>Use the Fundamentals page to generate this report first.</p>"
        "<a href='/fundamentals' style='color:#5B7CFF'>&#8592; Back to Fundamentals</a>"
        "</body></html>",
        404,
        {"Content-Type": "text/html; charset=utf-8"},
    )


# =========================================================================== #
# API — Pre-Earnings Mode  (Part 8)
# =========================================================================== #

@fundamentals_bp.route("/api/preearnings/<ticker>")
@login_required
def api_pre_earnings(ticker: str):
    """
    GET /api/preearnings/<ticker>

    Returns a pre-earnings brief generated from analyst consensus data ONLY.
    No SEC filing required. LLM adds narrative context around the numbers.

    Response:
        200 {
          "ticker": "OKE",
          "expected_eps": "$1.05",
          "expected_revenue": "$4.3B",
          "key_metric_to_watch": "...",
          "implied_market_expectation_summary": "...",
          "bull_scenario": "...",
          "bear_scenario": "...",
          "consensus_source": "yahoo",
          "consensus_period": "2024-09-30"
        }
        400 { "error": "..." }
        502 { "error": "..." }
    """
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        return jsonify({"error": "Invalid ticker"}), 400

    # 1. Fetch consensus data
    consensus = get_consensus(ticker)

    # 2. Call LLM with consensus only
    try:
        llm    = get_llm_client()
        prompt = PRE_EARNINGS_PROMPT.format(
            ticker=ticker,
            consensus_json=json.dumps(consensus, ensure_ascii=False, indent=2),
        )
        raw    = llm.complete(prompt, max_tokens=1_200)

        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text  = parts[1] if len(parts) >= 2 else text
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()

        brief = json.loads(text)
    except Exception as exc:
        logger.error("Pre-earnings LLM failed for %s: %s", ticker, exc)
        brief = {
            "expected_eps":                       None,
            "expected_revenue":                   None,
            "key_metric_to_watch":                None,
            "implied_market_expectation_summary": None,
            "bull_scenario":                      None,
            "bear_scenario":                      None,
        }

    brief["ticker"]           = ticker
    brief["consensus_source"] = consensus.get("source", "yahoo")
    brief["consensus_period"] = consensus.get("period")

    return jsonify(brief), 200
