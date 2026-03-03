#!/usr/bin/env python3
"""
CLI Replay Tool – Session Liquidity Sweep Detector

Fetches live 5M candles from Twelve Data for a given symbol + session date,
then runs the sweep detector step-by-step and prints a human-readable
timeline so you can verify every state-machine transition matches the chart.

Usage
-----
# Text table (default)
python scripts/replay_session_sweep.py \\
    --symbol XAUUSD \\
    --session-type asia \\
    --date 2024-01-15

# JSON output
python scripts/replay_session_sweep.py \\
    --symbol EURUSD \\
    --session-type london \\
    --date 2024-07-15 \\
    --format json

# Hide per-candle sweep updates (cleaner output)
python scripts/replay_session_sweep.py \\
    --symbol XAUUSD \\
    --session-type asia \\
    --date 2024-01-15 \\
    --no-sweep-updates

# Custom candle count (default 500)
python scripts/replay_session_sweep.py \\
    --symbol EURUSD \\
    --session-type asia \\
    --date 2024-01-15 \\
    --candles 300

Environment variables required
-------------------------------
TWELVEDATA_API_KEY   – Twelve Data API key

DST handling
------------
Sessions are in Asia/Jerusalem time (DST-aware).
Winter: UTC+2  Summer (IDT): UTC+3
  Asia   03:00–07:00 IL
  London 09:00–12:00 IL
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timezone

# ── allow running from project root or scripts/ directory ────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── stub the db dependency so we can import the service without a live DB ───
from unittest.mock import MagicMock
_db_mock = MagicMock()
sys.modules.setdefault("database", type(sys)("database"))
sys.modules["database"].db = _db_mock
sys.modules.setdefault("email_sender", MagicMock())

from services.forex_data_provider import forex_data_provider, normalize_symbol
from services.session_break_detector import (
    _session_window_utc,
    _session_candles,
    _post_session_candles,
    _utc_to_il,
)
from services.session_sweep_replay import replay_sweep, render_table


# ── logging: only show errors from libraries; replay output goes to stdout ───
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Session Liquidity Sweep – replay / debug tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--symbol", required=True,
        help="Forex symbol, e.g. EURUSD or XAU/USD",
    )
    p.add_argument(
        "--session-type", required=True, choices=["asia", "london"],
        dest="session_type",
        help="Session to replay",
    )
    p.add_argument(
        "--date", required=True,
        help="Israel local session date  YYYY-MM-DD",
    )
    p.add_argument(
        "--format", choices=["table", "json"], default="table",
        dest="output_format",
        help="Output format (default: table)",
    )
    p.add_argument(
        "--no-sweep-updates", action="store_true", dest="no_updates",
        help="Hide per-candle SWEEP_UPDATE events (cleaner output)",
    )
    p.add_argument(
        "--candles", type=int, default=500, metavar="N",
        help="Number of 5M candles to fetch from Twelve Data (default: 500)",
    )
    return p.parse_args()


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        sys.exit(f"ERROR: invalid date '{s}' – use YYYY-MM-DD")


def main() -> None:
    args = parse_args()

    # ── validate API key ─────────────────────────────────────────────────
    if not os.getenv("TWELVEDATA_API_KEY"):
        sys.exit(
            "ERROR: TWELVEDATA_API_KEY environment variable not set.\n"
            "Export it before running:  export TWELVEDATA_API_KEY=your_key"
        )

    session_date = _parse_date(args.date)
    show_updates = not args.no_updates

    # ── compute session UTC window ───────────────────────────────────────
    try:
        start_utc, end_utc = _session_window_utc(args.session_type, session_date)
    except KeyError:
        sys.exit(f"ERROR: unknown session type '{args.session_type}'")

    # ── resolve and print normalized symbol ─────────────────────────────
    _METAL_CODES = frozenset({"XAU", "XAG", "XPT", "XPD"})
    _norm_sym, _norm_err = normalize_symbol(args.symbol)
    _td_sym = _norm_sym if _norm_sym else args.symbol.upper().strip()
    if _norm_sym:
        _base, _quote = _norm_sym.split("/")
        _asset_class = "forex/metal" if (_base in _METAL_CODES or _quote in _METAL_CODES) else "forex"
    else:
        _asset_class = "unknown"

    print(
        f"\nFetching {args.candles} × 5M candles  "
        f"symbol={args.symbol}  session={args.session_type}  date={session_date}",
        flush=True,
    )
    _rp_start_il = _utc_to_il(start_utc)
    _rp_end_il   = _utc_to_il(end_utc)
    print(
        f"Session UTC window: {start_utc.isoformat()} → {end_utc.isoformat()}\n"
        f"Session IL  window: {_rp_start_il.isoformat()} → {_rp_end_il.isoformat()}\n"
        f"Inclusion rule: session_start <= candle.ts < session_end  (end is EXCLUSIVE)",
        flush=True,
    )
    # 1) Normalized symbol sent to Twelve Data
    print(
        f"symbol_raw={args.symbol!r}  normalized={_td_sym!r}  "
        f"provider=twelvedata  asset_class={_asset_class}",
        flush=True,
    )

    # ── fetch candles ────────────────────────────────────────────────────
    all_candles = forex_data_provider.get_recent_candles(
        args.symbol, timeframe="5m", count=args.candles
    )

    if not all_candles:
        sys.exit(
            f"ERROR: no candles returned for {args.symbol}.\n"
            "Check symbol spelling, API key, and rate limits."
        )

    # 2) First and last fetched candles from Twelve Data (ts with UTC tzinfo)
    _fc = all_candles[0]
    _lc = all_candles[-1]
    _fc_ts = _fc["timestamp"].replace(tzinfo=timezone.utc)
    _lc_ts = _lc["timestamp"].replace(tzinfo=timezone.utc)
    print(
        f"Fetched {len(all_candles)} candles\n"
        f"  first_candle: ts={_fc_ts.isoformat()}  "
        f"open={_fc['open']:.5f}  high={_fc['high']:.5f}  "
        f"low={_fc['low']:.5f}  close={_fc['close']:.5f}\n"
        f"  last_candle:  ts={_lc_ts.isoformat()}  "
        f"open={_lc['open']:.5f}  high={_lc['high']:.5f}  "
        f"low={_lc['low']:.5f}  close={_lc['close']:.5f}",
        flush=True,
    )

    # ── split into session + post-session ────────────────────────────────
    ses_candles  = _session_candles(all_candles, start_utc, end_utc)
    post_candles = _post_session_candles(all_candles, end_utc)

    if not ses_candles:
        sys.exit(
            f"ERROR: no session candles found inside the window "
            f"{start_utc.isoformat()} → {end_utc.isoformat()}.\n"
            f"Try fetching more candles (--candles) or a more recent date."
        )

    # 3) First and last candles inside the session window (ts with UTC tzinfo)
    _sorted_ses = sorted(ses_candles, key=lambda c: c["timestamp"])
    _fs = _sorted_ses[0]
    _ls = _sorted_ses[-1]
    _fs_ts = _fs["timestamp"].replace(tzinfo=timezone.utc)
    _ls_ts = _ls["timestamp"].replace(tzinfo=timezone.utc)
    _rp_top5h = sorted(ses_candles, key=lambda c: c["high"], reverse=True)[:5]
    _rp_bot5l = sorted(ses_candles, key=lambda c: c["low"])[:5]
    print(
        f"Session candles: {len(ses_candles)}  Post-session candles: {len(post_candles)}\n"
        f"  first_session_candle: ts={_fs_ts.isoformat()}  "
        f"high={_fs['high']:.5f}  low={_fs['low']:.5f}\n"
        f"  last_session_candle:  ts={_ls_ts.isoformat()}  "
        f"high={_ls['high']:.5f}  low={_ls['low']:.5f}\n"
        f"  top5_highs_in_session  :\n"
        + "".join(
            f"    [{i+1}] ts={c['timestamp'].replace(tzinfo=timezone.utc).isoformat()}  high={c['high']:.5f}\n"
            for i, c in enumerate(_rp_top5h)
        )
        + f"  bottom5_lows_in_session:\n"
        + "".join(
            f"    [{i+1}] ts={c['timestamp'].replace(tzinfo=timezone.utc).isoformat()}  low={c['low']:.5f}\n"
            for i, c in enumerate(_rp_bot5l)
        ).rstrip("\n"),
        flush=True,
    )

    # ── run replay ───────────────────────────────────────────────────────
    result = replay_sweep(
        session_candles    = ses_candles,
        post_candles       = post_candles,
        session_type       = args.session_type,
        session_date       = session_date,
        session_start_utc  = start_utc,
        session_end_utc    = end_utc,
        show_sweep_updates = show_updates,
    )
    result["symbol"] = args.symbol.upper()

    # ── output ───────────────────────────────────────────────────────────
    if args.output_format == "json":
        print(json.dumps(result, indent=2, default=str))
    else:
        print()
        print(render_table(result, show_sweep_updates=show_updates))
        print()

    # Exit code: 0 if triggered, 2 if not (useful for scripting)
    sys.exit(0 if result.get("triggered") else 2)


if __name__ == "__main__":
    main()
