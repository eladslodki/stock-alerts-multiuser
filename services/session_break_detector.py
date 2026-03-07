"""
Session Liquidity Sweep Detector – Asia + London (Israel time)

Detects ICT-style "Session Liquidity Sweep" setups:
  1. Session builds a high/low during the session window (tracked by wick).
  2. After the session a candle wicks beyond the session level → sweep starts.
  3. Additional candles continue to extend the sweep extreme (first_sweep_level
     = the HIGHEST wick for UP, LOWEST wick for DOWN across the *entire* sweep
     move – not just the first breakout candle).
  4. Sweep ends (re-entry) when a later candle wicks back inside the session
     level: low <= session_high (UP) or high >= session_low (DOWN).
  5. Confirmation: a strictly-later candle breaks the locked first_sweep_level.

Data source : TradingView PEPPERSTONE – M5 candles (OHLC, UTC open time)
Timezone    : Asia/Jerusalem (DST-aware).  Sessions are in Israel local time.
Sessions    : ASIA   03:00–07:00 IL
              LONDON 09:00–12:00 IL
Break def.  : WICK only  (candle.high / candle.low – NOT close)

State per (user_id, symbol, session_type, session_date):
  - session_high / session_low  : tracked from session candles (wicks)
  - direction                   : UP or DOWN (locked on first sweep)
  - sweep_start_ts              : first candle whose wick broke session level
  - first_sweep_level           : aggregated extreme of the entire sweep move
  - sweep_end_ts                : re-entry candle (sweep locked here)
  - confirm_break_ts / level    : trigger candle
  - triggered_at                : set when confirmation is detected
  - Anti-spam: only 1 trigger per (user_id, symbol, session_type, session_date, direction)

Logging tags used:
  [SESSION_SWEEP][RUN_START]
  [SESSION_SWEEP][SESSION_TRACK]
  [SESSION_SWEEP][SESSION_END]
  [SESSION_SWEEP][SWEEP_START]
  [SESSION_SWEEP][SWEEP_UPDATE]
  [SESSION_SWEEP][SWEEP_END]
  [SESSION_SWEEP][CONFIRM]
  [SESSION_SWEEP][TRIGGER]
  [SESSION_SWEEP][HEARTBEAT]
"""

from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Timezone support – prefer stdlib zoneinfo (Python 3.9+), fall back to pytz
# ---------------------------------------------------------------------------
try:
    from zoneinfo import ZoneInfo                    # Python 3.9+
    _IL_TZ = ZoneInfo("Asia/Jerusalem")

    def _utc_to_il(dt: datetime) -> datetime:
        """Convert a naive-UTC datetime to a timezone-aware Israel datetime."""
        return dt.replace(tzinfo=timezone.utc).astimezone(_IL_TZ)

    def _il_to_utc_naive(dt_il) -> datetime:
        """Convert a tzinfo-aware Israel datetime to naive UTC."""
        return dt_il.astimezone(timezone.utc).replace(tzinfo=None)

except ImportError:
    import pytz as _pytz
    _IL_TZ = _pytz.timezone("Asia/Jerusalem")

    def _utc_to_il(dt: datetime) -> datetime:
        return _pytz.utc.localize(dt).astimezone(_IL_TZ)

    def _il_to_utc_naive(dt_il) -> datetime:
        return dt_il.astimezone(_pytz.utc).replace(tzinfo=None)


from database import db
from services.forex_data_provider import normalize_symbol  # kept for watchlist validation
from services.tradingview_provider import tradingview_provider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration – sessions defined in Israel local time (DST-aware)
# ---------------------------------------------------------------------------

class SessionSweepConfig:
    """Configuration for the Session Liquidity Sweep detector."""

    # Sessions defined in Israel local time (hour, minute)
    SESSIONS: Dict[str, Dict] = {
        "asia": {
            "start_h": 3,  "start_m": 0,   # 03:00 IL
            "end_h":   7,  "end_m":   0,   # 07:00 IL
        },
        "london": {
            "start_h": 9,  "start_m": 0,   # 09:00 IL
            "end_h":  12,  "end_m":   0,   # 12:00 IL
        },
    }

    # How many 5M candles to fetch per symbol.
    # 500 candles × 5 min ≈ 41 hours – covers current + previous sessions.
    CANDLE_COUNT = 500

    # Health monitoring
    UNHEALTHY_THRESHOLD_MINUTES = 30

    LOG_PREFIX = "[SESSION_SWEEP]"


# Backward-compat alias used by alert_processor.py
SessionBreakConfig = SessionSweepConfig


# ---------------------------------------------------------------------------
# Pure helper functions (no DB, no I/O – easy to test)
# ---------------------------------------------------------------------------

def _session_window_utc(session_type: str, session_date: date) -> Tuple[datetime, datetime]:
    """
    Return (start_dt_utc, end_dt_utc) as naive-UTC datetimes for a session on
    a given *Israel local* date.  Handles DST automatically.
    """
    cfg = SessionSweepConfig.SESSIONS[session_type]

    # Build timezone-aware datetimes in Israel local time
    import datetime as _dt_mod
    # We need to construct the local datetime carefully to get DST right.
    # Use ZoneInfo / pytz localize.
    try:
        from zoneinfo import ZoneInfo
        il = ZoneInfo("Asia/Jerusalem")
        start_il = _dt_mod.datetime(
            session_date.year, session_date.month, session_date.day,
            cfg["start_h"], cfg["start_m"],
            tzinfo=il,
        )
        end_il = _dt_mod.datetime(
            session_date.year, session_date.month, session_date.day,
            cfg["end_h"], cfg["end_m"],
            tzinfo=il,
        )
    except ImportError:
        import pytz
        il = pytz.timezone("Asia/Jerusalem")
        start_il = il.localize(_dt_mod.datetime(
            session_date.year, session_date.month, session_date.day,
            cfg["start_h"], cfg["start_m"],
        ))
        end_il = il.localize(_dt_mod.datetime(
            session_date.year, session_date.month, session_date.day,
            cfg["end_h"], cfg["end_m"],
        ))

    start_utc = _il_to_utc_naive(start_il)
    end_utc   = _il_to_utc_naive(end_il)
    return start_utc, end_utc


def _session_candles(candles: List[Dict], start_dt: datetime, end_dt: datetime) -> List[Dict]:
    """Return candles whose timestamp (naive UTC) is in [start_dt, end_dt)."""
    return [c for c in candles if start_dt <= c["timestamp"] < end_dt]


def _post_session_candles(candles: List[Dict], end_dt: datetime) -> List[Dict]:
    """Return candles whose timestamp >= end_dt, ordered oldest→newest."""
    return sorted(
        [c for c in candles if c["timestamp"] >= end_dt],
        key=lambda c: c["timestamp"],
    )


def _compute_one_direction(
    direction: str,
    session_level: float,
    post_candles: List[Dict],
) -> Dict:
    """
    Evaluate a single sweep direction from post-session candles.

    Returns a dict with at least one of:
      {"no_break": True}                 – session level never broken
      {"direction", "sweep_start_ts", "first_sweep_level",
       "reentered": False, "confirmed": False}
      {... "sweep_end_ts", "reentered": True, "confirmed": False}
      {... "confirm_break_ts", "confirm_break_level", "confirmed": True}
    """
    # STATE 2: Find first candle that breaks session_level
    sweep_start_ts: Optional[datetime] = None
    for c in post_candles:
        if direction == "UP" and c["high"] > session_level:
            sweep_start_ts = c["timestamp"]
            break
        elif direction == "DOWN" and c["low"] < session_level:
            sweep_start_ts = c["timestamp"]
            break

    if sweep_start_ts is None:
        return {"no_break": True}

    # STATE 3: Aggregate the extreme across the entire sweep until re-entry
    sweep_end_ts: Optional[datetime] = None
    if direction == "UP":
        sweep_extreme: float = -float("inf")
        for c in post_candles:
            if c["timestamp"] < sweep_start_ts:
                continue
            sweep_extreme = max(sweep_extreme, c["high"])
            if c["timestamp"] > sweep_start_ts and c["low"] <= session_level:
                sweep_end_ts = c["timestamp"]
                break
    else:  # DOWN
        sweep_extreme = float("inf")
        for c in post_candles:
            if c["timestamp"] < sweep_start_ts:
                continue
            sweep_extreme = min(sweep_extreme, c["low"])
            if c["timestamp"] > sweep_start_ts and c["high"] >= session_level:
                sweep_end_ts = c["timestamp"]
                break

    first_sweep_level = sweep_extreme

    if sweep_end_ts is None:
        return {
            "direction":         direction,
            "sweep_start_ts":    sweep_start_ts,
            "first_sweep_level": first_sweep_level,
            "reentered":         False,
            "confirmed":         False,
        }

    # STATE 4: Find confirmation break after re-entry
    for c in post_candles:
        if c["timestamp"] <= sweep_end_ts:
            continue
        if direction == "UP" and c["high"] > first_sweep_level:
            return {
                "direction":           direction,
                "sweep_start_ts":      sweep_start_ts,
                "first_sweep_level":   first_sweep_level,
                "sweep_end_ts":        sweep_end_ts,
                "reentered":           True,
                "confirmed":           True,
                "confirm_break_ts":    c["timestamp"],
                "confirm_break_level": c["high"],
            }
        if direction == "DOWN" and c["low"] < first_sweep_level:
            return {
                "direction":           direction,
                "sweep_start_ts":      sweep_start_ts,
                "first_sweep_level":   first_sweep_level,
                "sweep_end_ts":        sweep_end_ts,
                "reentered":           True,
                "confirmed":           True,
                "confirm_break_ts":    c["timestamp"],
                "confirm_break_level": c["low"],
            }

    return {
        "direction":         direction,
        "sweep_start_ts":    sweep_start_ts,
        "first_sweep_level": first_sweep_level,
        "sweep_end_ts":      sweep_end_ts,
        "reentered":         True,
        "confirmed":         False,
    }


def compute_sweep_result_dual(
    session_candles: List[Dict],
    post_candles: List[Dict],
) -> Optional[Dict]:
    """
    Evaluate BOTH UP and DOWN sweep paths independently.

    This is the main entry point used by _process_session().
    compute_sweep_result() (single-direction) is kept intact for tests.

    Returns None if session_candles is empty, otherwise:
      {
        "session_high": float,
        "session_low":  float,
        "up":   _compute_one_direction("UP",   session_high, post_candles),
        "down": _compute_one_direction("DOWN", session_low,  post_candles),
      }
    """
    if not session_candles:
        return None

    session_high = max(c["high"] for c in session_candles)
    session_low  = min(c["low"]  for c in session_candles)

    if not post_candles:
        return {
            "session_high": session_high,
            "session_low":  session_low,
            "up":           {"no_break": True},
            "down":         {"no_break": True},
        }

    return {
        "session_high": session_high,
        "session_low":  session_low,
        "up":           _compute_one_direction("UP",   session_high, post_candles),
        "down":         _compute_one_direction("DOWN", session_low,  post_candles),
    }


def compute_sweep_result(
    session_candles: List[Dict],
    post_candles: List[Dict],
) -> Optional[Dict]:
    """
    Pure functional implementation of the Session Liquidity Sweep state machine.

    State machine progression (virtual – evaluated per run from raw candles):
      STATE 1: IN_SESSION_TRACK  → builds session_high / session_low from wicks
      STATE 2: POST_SESSION_WAIT_SWEEP_START → watches for first wick beyond session level
      STATE 3_UP/DOWN_IN_SWEEP   → aggregates the sweep extreme (KEY FIX)
      STATE 4_UP/DOWN_WAIT_CONFIRM → waits for re-entry then confirm break

    Parameters
    ----------
    session_candles : candles during the session window (used for session_high/low)
    post_candles    : candles after the session window, sorted oldest→newest

    Returns None if session_candles is empty.

    Otherwise returns a dict containing at least:
      session_high, session_low

    Plus additional keys depending on progress:
      no_break=True            → no sweep started
      direction, sweep_start_ts, first_sweep_level
      reentered=False          → sweep started but no re-entry yet
      sweep_end_ts, reentered=True
      confirmed=True, confirm_break_ts, confirm_break_level  → full trigger
    """
    if not session_candles:
        return None

    # ── STATE 1: build session extremes from wicks ──────────────────────────
    session_high = max(c["high"] for c in session_candles)
    session_low  = min(c["low"]  for c in session_candles)

    if not post_candles:
        return {"session_high": session_high, "session_low": session_low, "no_break": True}

    # ── STATE 2: POST_SESSION_WAIT_SWEEP_START ───────────────────────────────
    # Find the first UP sweep start and DOWN sweep start chronologically.
    first_up_ts:   Optional[datetime] = None
    first_down_ts: Optional[datetime] = None

    for c in post_candles:
        if first_up_ts is None and c["high"] > session_high:
            first_up_ts = c["timestamp"]
        if first_down_ts is None and c["low"] < session_low:
            first_down_ts = c["timestamp"]
        if first_up_ts is not None and first_down_ts is not None:
            break

    if first_up_ts is None and first_down_ts is None:
        return {"session_high": session_high, "session_low": session_low, "no_break": True}

    # Choose direction: earliest sweep start wins; tie → UP
    if first_up_ts is not None and first_down_ts is not None:
        if first_up_ts <= first_down_ts:
            direction = "UP"
            sweep_start_ts = first_up_ts
        else:
            direction = "DOWN"
            sweep_start_ts = first_down_ts
    elif first_up_ts is not None:
        direction = "UP"
        sweep_start_ts = first_up_ts
    else:
        direction = "DOWN"
        sweep_start_ts = first_down_ts

    # ── STATE 3: IN_SWEEP – aggregate the extreme across the whole sweep ─────
    # KEY FIX: first_sweep_level = MAX(high) for UP, MIN(low) for DOWN,
    # computed across ALL candles from sweep_start until re-entry.
    # Re-entry: a LATER candle (ts > sweep_start_ts) whose low <= session_high (UP)
    #           or high >= session_low (DOWN).
    sweep_end_ts: Optional[datetime] = None

    if direction == "UP":
        sweep_high = -float("inf")
        for c in post_candles:
            if c["timestamp"] < sweep_start_ts:
                continue                        # strictly before sweep – skip
            sweep_high = max(sweep_high, c["high"])
            # Re-entry check: strictly after sweep_start_ts
            if c["timestamp"] > sweep_start_ts and c["low"] <= session_high:
                sweep_end_ts = c["timestamp"]
                break
        first_sweep_level = sweep_high          # locked extreme of entire sweep

        if sweep_end_ts is None:
            # Sweep started but re-entry hasn't happened yet
            return {
                "session_high":      session_high,
                "session_low":       session_low,
                "direction":         "UP",
                "sweep_start_ts":    sweep_start_ts,
                "first_sweep_level": first_sweep_level,
                "reentered":         False,
                "confirmed":         False,
            }

        # ── STATE 4_UP: WAIT_CONFIRM after re-entry ──────────────────────────
        for c in post_candles:
            if c["timestamp"] <= sweep_end_ts:
                continue          # must be strictly after sweep_end (re-entry) candle
            if c["high"] > first_sweep_level:
                return {
                    "session_high":        session_high,
                    "session_low":         session_low,
                    "direction":           "UP",
                    "sweep_start_ts":      sweep_start_ts,
                    "first_sweep_level":   first_sweep_level,
                    "sweep_end_ts":        sweep_end_ts,
                    "reentered":           True,
                    "confirm_break_ts":    c["timestamp"],
                    "confirm_break_level": c["high"],
                    "confirmed":           True,
                }

        # Re-entry happened but no confirm break yet
        return {
            "session_high":      session_high,
            "session_low":       session_low,
            "direction":         "UP",
            "sweep_start_ts":    sweep_start_ts,
            "first_sweep_level": first_sweep_level,
            "sweep_end_ts":      sweep_end_ts,
            "reentered":         True,
            "confirmed":         False,
        }

    else:  # direction == "DOWN"
        sweep_low = float("inf")
        for c in post_candles:
            if c["timestamp"] < sweep_start_ts:
                continue
            sweep_low = min(sweep_low, c["low"])
            # Re-entry check: strictly after sweep_start_ts
            if c["timestamp"] > sweep_start_ts and c["high"] >= session_low:
                sweep_end_ts = c["timestamp"]
                break
        first_sweep_level = sweep_low           # locked extreme of entire sweep

        if sweep_end_ts is None:
            return {
                "session_high":      session_high,
                "session_low":       session_low,
                "direction":         "DOWN",
                "sweep_start_ts":    sweep_start_ts,
                "first_sweep_level": first_sweep_level,
                "reentered":         False,
                "confirmed":         False,
            }

        # ── STATE 4_DOWN: WAIT_CONFIRM after re-entry ────────────────────────
        for c in post_candles:
            if c["timestamp"] <= sweep_end_ts:
                continue
            if c["low"] < first_sweep_level:
                return {
                    "session_high":        session_high,
                    "session_low":         session_low,
                    "direction":           "DOWN",
                    "sweep_start_ts":      sweep_start_ts,
                    "first_sweep_level":   first_sweep_level,
                    "sweep_end_ts":        sweep_end_ts,
                    "reentered":           True,
                    "confirm_break_ts":    c["timestamp"],
                    "confirm_break_level": c["low"],
                    "confirmed":           True,
                }

        return {
            "session_high":      session_high,
            "session_low":       session_low,
            "direction":         "DOWN",
            "sweep_start_ts":    sweep_start_ts,
            "first_sweep_level": first_sweep_level,
            "sweep_end_ts":      sweep_end_ts,
            "reentered":         True,
            "confirmed":         False,
        }


def find_relevant_sessions(
    candles: List[Dict],
    now_utc: datetime,
) -> List[Tuple[str, date]]:
    """
    Return all (session_type, session_date) pairs where:
      - session_date is the Israel local date
      - The session has at least one candle inside the session window, AND
      - The session has ended (session_end_utc <= now_utc).

    Candle timestamps are treated as naive UTC.
    """
    results: List[Tuple[str, date]] = []

    # Discover unique Israel local dates from candle timestamps
    il_dates: set = set()
    for c in candles:
        il_dt = _utc_to_il(c["timestamp"])
        il_dates.add(il_dt.date())

    for session_type in SessionSweepConfig.SESSIONS:
        for d in sorted(il_dates):
            start_utc, end_utc = _session_window_utc(session_type, d)
            # Session must have ended
            if now_utc < end_utc:
                continue
            # Must have at least one candle inside the session window
            ses_candles = _session_candles(candles, start_utc, end_utc)
            if not ses_candles:
                continue
            results.append((session_type, d))

    return sorted(results, key=lambda x: (x[1], x[0]))


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _load_state(user_id: int, symbol: str, session_type: str, session_date: date) -> Optional[Dict]:
    """Load state row from DB, returns None if not found."""
    row = db.execute(
        """
        SELECT *
        FROM session_break_state
        WHERE user_id = %s AND symbol = %s
          AND session_type = %s AND session_date = %s
        """,
        (user_id, symbol, session_type, session_date),
        fetchone=True,
    )
    return dict(row) if row else None


def _upsert_state(user_id: int, symbol: str, session_type: str, session_date: date,
                  **fields) -> None:
    """Insert or update state row."""
    set_parts = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values())

    db.execute(
        f"""
        INSERT INTO session_break_state (user_id, symbol, session_type, session_date, {', '.join(fields.keys())}, updated_at)
        VALUES (%s, %s, %s, %s, {', '.join(['%s'] * len(fields))}, NOW())
        ON CONFLICT (user_id, symbol, session_type, session_date) DO UPDATE
          SET {set_parts}, updated_at = NOW()
        """,
        [user_id, symbol, session_type, str(session_date)] + values + values,
    )


def _save_history(user_id: int, symbol: str, session_type: str,
                  session_date: date, result: Dict) -> None:
    """Save a triggered event to the history table.

    Writes both the new sweep-model columns and the legacy first_break_*
    columns (back-filled from sweep data) so that UI queries that still
    read first_break_ts / first_break_level continue to display correctly.
    """
    # Back-fill legacy columns from sweep equivalents so NOT NULL constraints
    # (relaxed by migration) and old UI readers are both satisfied.
    first_break_ts    = result.get("sweep_start_ts")
    first_break_level = result.get("first_sweep_level")

    db.execute(
        """
        INSERT INTO session_break_history (
            user_id, symbol, session_type, session_date,
            direction,
            session_high, session_low,
            sweep_start_ts, first_sweep_level,
            sweep_end_ts,
            first_break_ts, first_break_level,
            confirm_break_ts, confirm_break_level,
            triggered_at
        ) VALUES (%s,%s,%s,%s, %s, %s,%s, %s,%s, %s, %s,%s, %s,%s, NOW())
        ON CONFLICT DO NOTHING
        """,
        (
            user_id, symbol, session_type, str(session_date),
            result["direction"],
            result["session_high"], result["session_low"],
            result.get("sweep_start_ts"), result.get("first_sweep_level"),
            result.get("sweep_end_ts"),
            first_break_ts, first_break_level,
            result.get("confirm_break_ts"), result.get("confirm_break_level"),
        ),
    )


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def _send_alert_email(user_email: str, symbol: str, session_type: str,
                      session_date: date, result: Dict) -> bool:
    """Send the session liquidity sweep alert email."""
    from email_sender import email_sender
    return email_sender.send_session_sweep_email(
        to_email=user_email,
        symbol=symbol,
        session_type=session_type,
        session_date=str(session_date),
        direction=result["direction"],
        session_high=result["session_high"],
        session_low=result["session_low"],
        sweep_start_ts=result["sweep_start_ts"].isoformat(),
        first_sweep_level=result["first_sweep_level"],
        sweep_end_ts=result["sweep_end_ts"].isoformat(),
        confirm_break_ts=result["confirm_break_ts"].isoformat(),
        confirm_break_level=result["confirm_break_level"],
    )


# ---------------------------------------------------------------------------
# Main detector class
# ---------------------------------------------------------------------------

class SessionBreakDetector:
    """
    Orchestrates Session Liquidity Sweep detection across all users and their
    watchlists.  Designed to be called periodically by the scheduler.
    """

    def detect_for_user(
        self,
        user_id: int,
        user_email: str,
        candle_cache: Dict[str, List[Dict]],
        run_id: str = "",
    ) -> Dict:
        """
        Run detection for all symbols in a user's forex watchlist.

        Parameters
        ----------
        user_id      : DB user id
        user_email   : email address for notifications
        candle_cache : shared in-memory dict {symbol: [candles]} for this run

        Returns a metrics dict: {symbols, triggers, states_advanced, errors}
        """
        LP = SessionSweepConfig.LOG_PREFIX
        metrics = {"symbols": 0, "triggers": 0, "states_advanced": 0, "errors": 0}

        watchlist = db.execute(
            "SELECT symbol FROM forex_watchlist WHERE user_id = %s ORDER BY added_at",
            (user_id,),
            fetchall=True,
        )
        symbols = [r["symbol"] for r in (watchlist or [])]

        if not symbols:
            logger.debug("%s[SESSION_TRACK] user=%s no_symbols", LP, user_id)
            return metrics

        metrics["symbols"] = len(symbols)
        now_utc = datetime.utcnow()

        for symbol in symbols:
            try:
                if symbol not in candle_cache:
                    logger.debug(
                        "%s[SESSION_TRACK] user=%s symbol=%s fetching_candles count=%d provider=TRADINGVIEW",
                        LP, user_id, symbol, SessionSweepConfig.CANDLE_COUNT,
                    )
                    candles = tradingview_provider.get_candles(
                        symbol, count=SessionSweepConfig.CANDLE_COUNT
                    )
                    candle_cache[symbol] = candles
                else:
                    candles = candle_cache[symbol]

                if not candles:
                    logger.warning(
                        "%s[SESSION_TRACK] user=%s symbol=%s no_candles",
                        LP, user_id, symbol,
                    )
                    continue

                result = self._process_symbol(
                    user_id, user_email, symbol, candles, now_utc, run_id
                )
                metrics["triggers"]        += result["triggers"]
                metrics["states_advanced"] += result["states_advanced"]

            except Exception as exc:
                metrics["errors"] += 1
                logger.error(
                    "%s[ERROR] run_id=%s user=%s symbol=%s err=%s",
                    LP, run_id, user_id, symbol, exc, exc_info=True,
                )

        return metrics

    def _process_symbol(
        self,
        user_id: int,
        user_email: str,
        symbol: str,
        candles: List[Dict],
        now_utc: datetime,
        run_id: str,
    ) -> Dict:
        """Process all relevant sessions for one (user, symbol)."""
        LP = SessionSweepConfig.LOG_PREFIX
        result = {"triggers": 0, "states_advanced": 0}

        relevant = find_relevant_sessions(candles, now_utc)
        if not relevant:
            return result

        for session_type, session_date in relevant:
            try:
                triggered, advanced = self._process_session(
                    user_id, user_email, symbol, session_type, session_date,
                    candles, run_id,
                )
                if triggered:
                    result["triggers"] += 1
                if advanced:
                    result["states_advanced"] += 1
            except Exception as exc:
                logger.error(
                    "%s[ERROR] run_id=%s user=%s symbol=%s session=%s/%s err=%s",
                    LP, run_id, user_id, symbol, session_type, session_date,
                    exc, exc_info=True,
                )

        return result

    def _process_session(
        self,
        user_id: int,
        user_email: str,
        symbol: str,
        session_type: str,
        session_date: date,
        all_candles: List[Dict],
        run_id: str,
    ) -> Tuple[bool, bool]:
        """
        Process one (user, symbol, session_type, session_date).

        Returns (triggered: bool, state_advanced: bool).
        """
        LP = SessionSweepConfig.LOG_PREFIX
        triggered     = False
        state_advanced = False

        start_utc, end_utc = _session_window_utc(session_type, session_date)

        # ── 1. Anti-spam: skip only when BOTH directions are already triggered ──
        existing = _load_state(user_id, symbol, session_type, session_date)
        if existing:
            _up_done   = existing.get("up_triggered_at")   is not None
            _down_done = existing.get("down_triggered_at") is not None
            if _up_done and _down_done:
                logger.debug(
                    "%s[SESSION_TRACK] user=%s symbol=%s session=%s/%s both_directions_triggered",
                    LP, user_id, symbol, session_type, session_date,
                )
                return False, False

        # ── 1b. Log new session init (first time we see this session identity) ─
        if existing is None:
            logger.info(
                "%s[SESSION_INIT] user=%s symbol=%s session_type=%s session_date=%s reset_state=True",
                LP, user_id, symbol, session_type, session_date,
            )

        # ── 2. Extract session and post-session candles ──────────────────────
        ses_candles  = _session_candles(all_candles, start_utc, end_utc)
        post_candles = _post_session_candles(all_candles, end_utc)

        if not ses_candles:
            return False, False

        # ── DEBUG: London session detailed inspection ──────────────────────
        if session_type == "london":
            # 1) Session window in UTC and Israel time
            start_il = _utc_to_il(start_utc)
            end_il   = _utc_to_il(end_utc)
            logger.info(
                "%s[DEBUG_LONDON] symbol=%s date=%s\n"
                "  session_start_utc    = %s\n"
                "  session_end_utc      = %s\n"
                "  session_start_israel = %s\n"
                "  session_end_israel   = %s",
                LP, symbol, session_date,
                start_utc.isoformat(),
                end_utc.isoformat(),
                start_il.isoformat(),
                end_il.isoformat(),
            )

            # 2) First/last session candle timestamps (with UTC tzinfo) + count
            _sorted_ses = sorted(ses_candles, key=lambda c: c["timestamp"])
            _first_ts_utc = _sorted_ses[0]["timestamp"].replace(tzinfo=timezone.utc)
            _last_ts_utc  = _sorted_ses[-1]["timestamp"].replace(tzinfo=timezone.utc)
            logger.info(
                "%s[DEBUG_LONDON] symbol=%s candle_membership\n"
                "  first_session_candle_ts = %s  (tzinfo=%s)\n"
                "  last_session_candle_ts  = %s  (tzinfo=%s)\n"
                "  total_candle_count      = %d",
                LP, symbol,
                _first_ts_utc.isoformat(), _first_ts_utc.tzinfo,
                _last_ts_utc.isoformat(),  _last_ts_utc.tzinfo,
                len(_sorted_ses),
            )

            # 3) Top 5 candle highs within the session
            _top5_highs = sorted(ses_candles, key=lambda c: c["high"], reverse=True)[:5]
            _highs_lines = "\n".join(
                "  [{i}] ts={ts}  high={h:.5f}".format(
                    i=idx + 1,
                    ts=c["timestamp"].replace(tzinfo=timezone.utc).isoformat(),
                    h=c["high"],
                )
                for idx, c in enumerate(_top5_highs)
            )
            logger.info(
                "%s[DEBUG_LONDON] symbol=%s top5_candle_highs:\n%s",
                LP, symbol, _highs_lines,
            )

            # 4) Bottom 5 candle lows within the session
            _bot5_lows = sorted(ses_candles, key=lambda c: c["low"])[:5]
            _lows_lines = "\n".join(
                "  [{i}] ts={ts}  low={l:.5f}".format(
                    i=idx + 1,
                    ts=c["timestamp"].replace(tzinfo=timezone.utc).isoformat(),
                    l=c["low"],
                )
                for idx, c in enumerate(_bot5_lows)
            )
            logger.info(
                "%s[DEBUG_LONDON] symbol=%s bottom5_candle_lows:\n%s",
                LP, symbol, _lows_lines,
            )
        # ── END DEBUG: London session ──────────────────────────────────────

        session_high = max(c["high"] for c in ses_candles)
        session_low  = min(c["low"]  for c in ses_candles)

        # ── SESSION_DEBUG: candle membership proof (all sessions) ────────────
        _sd_sorted   = sorted(ses_candles, key=lambda c: c["timestamp"])
        _sd_start_il = _utc_to_il(start_utc)
        _sd_end_il   = _utc_to_il(end_utc)
        _sd_first_ts = _sd_sorted[0]["timestamp"].replace(tzinfo=timezone.utc)
        _sd_last_ts  = _sd_sorted[-1]["timestamp"].replace(tzinfo=timezone.utc)
        _sd_top5h = sorted(ses_candles, key=lambda c: c["high"], reverse=True)[:5]
        _sd_bot5l = sorted(ses_candles, key=lambda c: c["low"])[:5]
        logger.info(
            "%s[SESSION_DEBUG] user=%s symbol=%s session_type=%s session_date=%s\n"
            "  inclusion_rule         : session_start <= candle.ts < session_end  (end is EXCLUSIVE)\n"
            "  session_start_israel   : %s\n"
            "  session_end_israel     : %s\n"
            "  session_start_utc      : %s\n"
            "  session_end_utc        : %s\n"
            "  included_candles_count : %d\n"
            "  first_session_candle_ts: %s\n"
            "  last_session_candle_ts : %s\n"
            "  top5_highs_in_session  : %s\n"
            "  bottom5_lows_in_session: %s",
            LP, user_id, symbol, session_type, session_date,
            _sd_start_il.isoformat(),
            _sd_end_il.isoformat(),
            start_utc.isoformat(),
            end_utc.isoformat(),
            len(_sd_sorted),
            _sd_first_ts.isoformat(),
            _sd_last_ts.isoformat(),
            [(c["timestamp"].replace(tzinfo=timezone.utc).isoformat(), round(c["high"], 5))
             for c in _sd_top5h],
            [(c["timestamp"].replace(tzinfo=timezone.utc).isoformat(), round(c["low"], 5))
             for c in _sd_bot5l],
        )
        # ── END SESSION_DEBUG ─────────────────────────────────────────────────

        logger.debug(
            "%s[SESSION_END] user=%s symbol=%s session=%s/%s "
            "session_high=%.5f session_low=%.5f "
            "session_start_utc=%s session_end_utc=%s post_candles=%d",
            LP, user_id, symbol, session_type, session_date,
            session_high, session_low,
            start_utc.isoformat(), end_utc.isoformat(),
            len(post_candles),
        )

        # ── 3. Run DUAL sweep state machine (UP and DOWN independently) ────────
        computation = compute_sweep_result_dual(ses_candles, post_candles)
        if computation is None:
            return False, False

        up_result   = computation["up"]
        down_result = computation["down"]

        # Always persist session high/low; explicitly null all sweep fields so
        # that a re-processed session row never inherits stale values.
        state_fields: Dict = {
            "session_high":             session_high,
            "session_low":              session_low,
            "state":                    "WAIT_SWEEP_START",
            # Single-direction backwards-compat fields (set from primary direction below)
            "direction":                None,
            "sweep_start_ts":           None,
            "first_sweep_level":        None,
            "sweep_end_ts":             None,
            "confirm_break_ts":         None,
            "confirm_break_level":      None,
            # Per-direction columns (dual-direction support)
            "up_sweep_start_ts":        None,
            "up_first_sweep_level":     None,
            "up_sweep_end_ts":          None,
            "up_confirm_break_ts":      None,
            "up_confirm_break_level":   None,
            "down_sweep_start_ts":      None,
            "down_first_sweep_level":   None,
            "down_sweep_end_ts":        None,
            "down_confirm_break_ts":    None,
            "down_confirm_break_level": None,
        }

        up_no_break   = up_result.get("no_break", False)
        down_no_break = down_result.get("no_break", False)

        if up_no_break and down_no_break:
            _upsert_state(user_id, symbol, session_type, session_date, **state_fields)
            return False, False

        # ── Populate per-direction fields from computation ───────────────────
        if not up_no_break:
            state_fields.update({
                "up_sweep_start_ts":      up_result.get("sweep_start_ts"),
                "up_first_sweep_level":   up_result.get("first_sweep_level"),
                "up_sweep_end_ts":        up_result.get("sweep_end_ts"),
                "up_confirm_break_ts":    up_result.get("confirm_break_ts"),
                "up_confirm_break_level": up_result.get("confirm_break_level"),
            })
            logger.info(
                "%s[SWEEP_START] user=%s symbol=%s session=%s/%s "
                "direction=UP sweep_start_ts=%s session_high=%.5f",
                LP, user_id, symbol, session_type, session_date,
                up_result["sweep_start_ts"].isoformat(), session_high,
            )
            if up_result.get("reentered"):
                logger.info(
                    "%s[SWEEP_END] user=%s symbol=%s session=%s/%s "
                    "direction=UP first_sweep_level=%.5f sweep_end_ts=%s reentered=True",
                    LP, user_id, symbol, session_type, session_date,
                    up_result["first_sweep_level"],
                    up_result["sweep_end_ts"].isoformat(),
                )

        if not down_no_break:
            state_fields.update({
                "down_sweep_start_ts":      down_result.get("sweep_start_ts"),
                "down_first_sweep_level":   down_result.get("first_sweep_level"),
                "down_sweep_end_ts":        down_result.get("sweep_end_ts"),
                "down_confirm_break_ts":    down_result.get("confirm_break_ts"),
                "down_confirm_break_level": down_result.get("confirm_break_level"),
            })
            logger.info(
                "%s[SWEEP_START] user=%s symbol=%s session=%s/%s "
                "direction=DOWN sweep_start_ts=%s session_low=%.5f",
                LP, user_id, symbol, session_type, session_date,
                down_result["sweep_start_ts"].isoformat(), session_low,
            )
            if down_result.get("reentered"):
                logger.info(
                    "%s[SWEEP_END] user=%s symbol=%s session=%s/%s "
                    "direction=DOWN first_sweep_level=%.5f sweep_end_ts=%s reentered=True",
                    LP, user_id, symbol, session_type, session_date,
                    down_result["first_sweep_level"],
                    down_result["sweep_end_ts"].isoformat(),
                )

        # ── Choose "primary" direction for single-direction backwards-compat ──
        # Most-advanced state wins: confirmed(3) > reentered(2) > sweeping(1) > none(0)
        def _score(r: Dict) -> int:
            if r.get("no_break"):  return 0
            if r.get("confirmed"): return 3
            if r.get("reentered"): return 2
            return 1

        up_score   = _score(up_result)
        down_score = _score(down_result)
        primary    = "UP"   if up_score >= down_score else "DOWN"
        primary_r  = up_result if primary == "UP" else down_result

        if not primary_r.get("no_break"):
            state_name = (
                f"{primary}_IN_SWEEP"     if not primary_r.get("reentered") else
                f"{primary}_WAIT_CONFIRM" if not primary_r.get("confirmed") else
                "TRIGGERED"
            )
            state_fields.update({
                "state":             state_name,
                "direction":         primary,
                "sweep_start_ts":    primary_r.get("sweep_start_ts"),
                "first_sweep_level": primary_r.get("first_sweep_level"),
                "sweep_end_ts":      primary_r.get("sweep_end_ts"),
            })

        state_advanced = up_score > 0 or down_score > 0

        # ── 4. Trigger each confirmed direction independently ─────────────────
        # A sweep on one side does NOT prevent detection of the other side.
        for dir_key, dir_result, trig_col in (
            ("UP",   up_result,   "up_triggered_at"),
            ("DOWN", down_result, "down_triggered_at"),
        ):
            if dir_result.get("no_break") or not dir_result.get("confirmed"):
                continue

            # Per-direction anti-spam: skip if this direction was already triggered
            _existing_check = _load_state(user_id, symbol, session_type, session_date)
            if _existing_check and _existing_check.get(trig_col):
                logger.debug(
                    "%s[TRIGGER] user=%s symbol=%s session=%s/%s "
                    "direction=%s already_triggered – skipping",
                    LP, user_id, symbol, session_type, session_date, dir_key,
                )
                continue

            confirm_ts    = dir_result["confirm_break_ts"]
            confirm_level = dir_result["confirm_break_level"]
            sweep_start   = dir_result["sweep_start_ts"]
            sweep_level   = dir_result["first_sweep_level"]
            sweep_end     = dir_result.get("sweep_end_ts")

            logger.info(
                "%s[CONFIRM] user=%s symbol=%s session=%s/%s "
                "direction=%s confirm_level=%.5f confirm_ts=%s",
                LP, user_id, symbol, session_type, session_date,
                dir_key, confirm_level, confirm_ts.isoformat(),
            )

            # Mark triggered BEFORE sending email (idempotency)
            trigger_time = datetime.utcnow()
            state_fields[trig_col] = trigger_time
            state_fields.update({
                "state":               "TRIGGERED",
                "triggered_at":        trigger_time,
                "direction":           dir_key,
                "sweep_start_ts":      sweep_start,
                "first_sweep_level":   sweep_level,
                "sweep_end_ts":        sweep_end,
                "confirm_break_ts":    confirm_ts,
                "confirm_break_level": confirm_level,
            })
            _upsert_state(user_id, symbol, session_type, session_date, **state_fields)

            # Save to history (one row per direction per session)
            _save_history(user_id, symbol, session_type, session_date, {
                "direction":           dir_key,
                "session_high":        session_high,
                "session_low":         session_low,
                "sweep_start_ts":      sweep_start,
                "first_sweep_level":   sweep_level,
                "sweep_end_ts":        sweep_end,
                "confirm_break_ts":    confirm_ts,
                "confirm_break_level": confirm_level,
            })

            logger.info(
                "%s[TRIGGER] user=%s symbol=%s session=%s/%s "
                "direction=%s sweep_start_ts=%s first_sweep_level=%.5f "
                "sweep_end_ts=%s confirm_level=%.5f@%s",
                LP, user_id, symbol, session_type, session_date,
                dir_key,
                sweep_start.isoformat(), sweep_level,
                sweep_end.isoformat() if sweep_end else "None",
                confirm_level, confirm_ts.isoformat(),
            )

            try:
                _send_alert_email(user_email, symbol, session_type, session_date, {
                    "direction":           dir_key,
                    "session_high":        session_high,
                    "session_low":         session_low,
                    "sweep_start_ts":      sweep_start,
                    "first_sweep_level":   sweep_level,
                    "sweep_end_ts":        sweep_end,
                    "confirm_break_ts":    confirm_ts,
                    "confirm_break_level": confirm_level,
                })
            except Exception as email_exc:
                logger.error(
                    "%s[TRIGGER] email_failed user=%s symbol=%s direction=%s err=%s",
                    LP, user_id, symbol, dir_key, email_exc,
                )

            triggered = True

        # Persist state even when no new trigger fired
        if not triggered:
            _upsert_state(user_id, symbol, session_type, session_date, **state_fields)

        return triggered, state_advanced


# Module-level singleton
session_break_detector = SessionBreakDetector()
