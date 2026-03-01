"""
Session Break Confirmation Detector – Asia + London

Replaces the old AMD/IFVG/sweep logic with a single, clearly-defined alert:
  "Session Break Confirmation" – when price first breaks a session's high/low
  by WICK and then a later candle confirms that break with another wick.

Data source : Twelve Data – 5M candles (OHLC)
Sessions    : Asia (00:00–09:00 UTC) and London (08:00–17:00 UTC)
Break def.  : WICK only  (candle.high / candle.low – NOT close)

State per (user_id, symbol, session_type, session_date):
  - session_high / session_low : tracked from session candles
  - direction                  : UP or DOWN (locked on first break)
  - first_break_ts / level     : first wick that exceeds the session extreme
  - triggered_at               : set when confirm break is detected
  - Anti-spam: only 1 trigger per (user_id, symbol, session_type, session_date)

Logging tags used:
  [SESSION_BREAK][RUN_START]
  [SESSION_BREAK][SESSION_TRACK]
  [SESSION_BREAK][SESSION_END]
  [SESSION_BREAK][FIRST_BREAK]
  [SESSION_BREAK][CONFIRM_BREAK]
  [SESSION_BREAK][TRIGGER]
  [SESSION_BREAK][HEARTBEAT]
"""

from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from database import db
from services.forex_data_provider import forex_data_provider, normalize_symbol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration – all session times in UTC
# ---------------------------------------------------------------------------

class SessionBreakConfig:
    # Session windows (UTC)
    SESSIONS: Dict[str, Dict] = {
        "asia": {
            "start": time(0, 0),   # 00:00 UTC
            "end":   time(9, 0),   # 09:00 UTC
        },
        "london": {
            "start": time(8, 0),   # 08:00 UTC
            "end":   time(17, 0),  # 17:00 UTC
        },
    }

    # How many 5M candles to fetch per symbol.
    # 500 candles × 5 min ≈ 41 hours – covers current + previous sessions.
    CANDLE_COUNT = 500

    # Health monitoring
    UNHEALTHY_THRESHOLD_MINUTES = 30

    LOG_PREFIX = "[SESSION_BREAK]"


# ---------------------------------------------------------------------------
# Pure helper functions (no DB, no I/O – easy to test)
# ---------------------------------------------------------------------------

def _session_window(session_type: str, session_date: date) -> Tuple[datetime, datetime]:
    """Return (start_dt, end_dt) UTC datetimes for a session on a given date."""
    cfg = SessionBreakConfig.SESSIONS[session_type]
    start_dt = datetime.combine(session_date, cfg["start"])
    end_dt   = datetime.combine(session_date, cfg["end"])
    return start_dt, end_dt


def _session_candles(candles: List[Dict], start_dt: datetime, end_dt: datetime) -> List[Dict]:
    """Return candles whose timestamp is in [start_dt, end_dt)."""
    return [c for c in candles if start_dt <= c["timestamp"] < end_dt]


def _post_session_candles(candles: List[Dict], end_dt: datetime) -> List[Dict]:
    """Return candles whose timestamp >= end_dt, ordered oldest→newest."""
    return sorted(
        [c for c in candles if c["timestamp"] >= end_dt],
        key=lambda c: c["timestamp"],
    )


def compute_session_result(
    session_candles: List[Dict],
    post_candles: List[Dict],
) -> Optional[Dict]:
    """
    Pure functional computation of the session-break state.

    Parameters
    ----------
    session_candles : candles during the session window
    post_candles    : candles after the session window (ordered oldest→newest)

    Returns None if no trigger, otherwise a dict with:
      {
        "session_high": float,
        "session_low":  float,
        "direction":    "UP" | "DOWN",
        "first_break_ts":    datetime,
        "first_break_level": float,
        "confirm_break_ts":    datetime,
        "confirm_break_level": float,
      }
    Returns a partial dict (without confirm_* keys) when only the first break
    was found but not yet confirmed, to allow state persistence.
    Returns {"session_high": .., "session_low": .., "no_break": True}
    when no break was found.
    """
    if not session_candles:
        return None

    session_high = max(c["high"] for c in session_candles)
    session_low  = min(c["low"]  for c in session_candles)

    if not post_candles:
        # Session just ended, no post-session data yet
        return {"session_high": session_high, "session_low": session_low, "no_break": True}

    # ------------------------------------------------------------------
    # Step 1: find first break (wick only, chronologically)
    # ------------------------------------------------------------------
    first_up_break: Optional[Tuple[datetime, float]] = None    # (ts, level)
    first_down_break: Optional[Tuple[datetime, float]] = None

    for c in post_candles:
        if first_up_break is None and c["high"] > session_high:
            first_up_break = (c["timestamp"], c["high"])
        if first_down_break is None and c["low"] < session_low:
            first_down_break = (c["timestamp"], c["low"])
        if first_up_break and first_down_break:
            break  # Found both, stop scanning

    if first_up_break is None and first_down_break is None:
        return {"session_high": session_high, "session_low": session_low, "no_break": True}

    # Choose first break chronologically; tiebreak: UP wins
    if first_up_break and first_down_break:
        if first_up_break[0] <= first_down_break[0]:
            direction = "UP"
            first_break_ts, first_break_level = first_up_break
        else:
            direction = "DOWN"
            first_break_ts, first_break_level = first_down_break
    elif first_up_break:
        direction = "UP"
        first_break_ts, first_break_level = first_up_break
    else:
        direction = "DOWN"
        first_break_ts, first_break_level = first_down_break

    # ------------------------------------------------------------------
    # Step 2: find confirmation break (must be a LATER candle)
    # ------------------------------------------------------------------
    confirm_ts: Optional[datetime] = None
    confirm_level: Optional[float] = None

    for c in post_candles:
        if c["timestamp"] <= first_break_ts:
            continue  # Must be strictly after first break
        if direction == "UP" and c["high"] > first_break_level:
            confirm_ts    = c["timestamp"]
            confirm_level = c["high"]
            break
        if direction == "DOWN" and c["low"] < first_break_level:
            confirm_ts    = c["timestamp"]
            confirm_level = c["low"]
            break

    if confirm_ts is None:
        # First break found but not yet confirmed
        return {
            "session_high":       session_high,
            "session_low":        session_low,
            "direction":          direction,
            "first_break_ts":     first_break_ts,
            "first_break_level":  first_break_level,
            "confirmed":          False,
        }

    return {
        "session_high":         session_high,
        "session_low":          session_low,
        "direction":            direction,
        "first_break_ts":       first_break_ts,
        "first_break_level":    first_break_level,
        "confirm_break_ts":     confirm_ts,
        "confirm_break_level":  confirm_level,
        "confirmed":            True,
    }


def find_relevant_sessions(
    candles: List[Dict],
    now_utc: datetime,
) -> List[Tuple[str, date]]:
    """
    Return all (session_type, session_date) pairs that:
      - have at least one session candle in the data, AND
      - the session has already ended (end_dt <= now_utc).
    """
    results: List[Tuple[str, date]] = []

    # Gather all unique dates present in candle data
    all_dates = sorted({c["timestamp"].date() for c in candles})

    for session_type in SessionBreakConfig.SESSIONS:
        for d in all_dates:
            start_dt, end_dt = _session_window(session_type, d)
            # Session must have ended
            if now_utc < end_dt:
                continue
            # Must have at least one session candle (otherwise not meaningful)
            ses_candles = _session_candles(candles, start_dt, end_dt)
            if not ses_candles:
                continue
            results.append((session_type, d))

    # Sort by (session_type, date) to process consistently
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
    # Build SET clause from fields
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
    """Save a triggered event to the history table."""
    db.execute(
        """
        INSERT INTO session_break_history (
            user_id, symbol, session_type, session_date,
            direction,
            session_high, session_low,
            first_break_ts, first_break_level,
            confirm_break_ts, confirm_break_level,
            triggered_at
        ) VALUES (%s,%s,%s,%s, %s, %s,%s, %s,%s, %s,%s, NOW())
        ON CONFLICT DO NOTHING
        """,
        (
            user_id, symbol, session_type, str(session_date),
            result["direction"],
            result["session_high"], result["session_low"],
            result["first_break_ts"], result["first_break_level"],
            result["confirm_break_ts"], result["confirm_break_level"],
        ),
    )


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def _send_alert_email(user_email: str, symbol: str, session_type: str,
                      session_date: date, result: Dict) -> bool:
    """Send the session-break confirmation alert email."""
    from email_sender import email_sender
    return email_sender.send_session_break_email(
        to_email=user_email,
        symbol=symbol,
        session_type=session_type,
        session_date=str(session_date),
        direction=result["direction"],
        session_high=result["session_high"],
        session_low=result["session_low"],
        first_break_ts=result["first_break_ts"].isoformat(),
        first_break_level=result["first_break_level"],
        confirm_break_ts=result["confirm_break_ts"].isoformat(),
        confirm_break_level=result["confirm_break_level"],
    )


# ---------------------------------------------------------------------------
# Main detector class
# ---------------------------------------------------------------------------

class SessionBreakDetector:
    """
    Orchestrates session-break detection across all users and their watchlists.
    Designed to be called periodically by the scheduler.
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
        LP = SessionBreakConfig.LOG_PREFIX
        metrics = {"symbols": 0, "triggers": 0, "states_advanced": 0, "errors": 0}

        # Fetch user's watchlist
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
                # Fetch (or reuse cached) candles
                if symbol not in candle_cache:
                    logger.debug(
                        "%s[SESSION_TRACK] user=%s symbol=%s fetching_candles count=%d",
                        LP, user_id, symbol, SessionBreakConfig.CANDLE_COUNT,
                    )
                    candles = forex_data_provider.get_recent_candles(
                        symbol, timeframe="5m", count=SessionBreakConfig.CANDLE_COUNT
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

                # Process all relevant sessions
                result = self._process_symbol(
                    user_id, user_email, symbol, candles, now_utc, run_id
                )
                metrics["triggers"]       += result["triggers"]
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
        LP = SessionBreakConfig.LOG_PREFIX
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
        LP = SessionBreakConfig.LOG_PREFIX
        triggered = False
        state_advanced = False

        start_dt, end_dt = _session_window(session_type, session_date)

        # ---- 1. Check anti-spam ----
        existing = _load_state(user_id, symbol, session_type, session_date)
        if existing and existing.get("triggered_at"):
            logger.debug(
                "%s[SESSION_TRACK] user=%s symbol=%s session=%s/%s already_triggered",
                LP, user_id, symbol, session_type, session_date,
            )
            return False, False

        # ---- 2. Extract session candles + post-session candles ----
        ses_candles  = _session_candles(all_candles, start_dt, end_dt)
        post_candles = _post_session_candles(all_candles, end_dt)

        if not ses_candles:
            return False, False  # No session data in our window

        session_high = max(c["high"] for c in ses_candles)
        session_low  = min(c["low"]  for c in ses_candles)

        logger.debug(
            "%s[SESSION_END] user=%s symbol=%s session=%s/%s "
            "session_high=%.5f session_low=%.5f post_candles=%d",
            LP, user_id, symbol, session_type, session_date,
            session_high, session_low, len(post_candles),
        )

        # ---- 3. Compute result from candles ----
        computation = compute_session_result(ses_candles, post_candles)
        if computation is None:
            return False, False

        # Update state in DB with session high/low
        state_fields: Dict = {
            "session_high": session_high,
            "session_low":  session_low,
            "state":        "POST_SESSION",
        }

        if computation.get("no_break"):
            _upsert_state(user_id, symbol, session_type, session_date, **state_fields)
            return False, False

        # First break found
        direction         = computation["direction"]
        first_break_ts    = computation["first_break_ts"]
        first_break_level = computation["first_break_level"]

        logger.info(
            "%s[FIRST_BREAK] user=%s symbol=%s session=%s/%s "
            "direction=%s ts=%s level=%.5f",
            LP, user_id, symbol, session_type, session_date,
            direction, first_break_ts.isoformat(), first_break_level,
        )

        state_fields.update({
            "state":             "WAIT_CONFIRM_" + direction,
            "direction":         direction,
            "first_break_ts":    first_break_ts,
            "first_break_level": first_break_level,
        })
        state_advanced = True

        if not computation.get("confirmed"):
            _upsert_state(user_id, symbol, session_type, session_date, **state_fields)
            return False, state_advanced

        # ---- 4. Confirmation break – TRIGGER ----
        confirm_ts    = computation["confirm_break_ts"]
        confirm_level = computation["confirm_break_level"]

        logger.info(
            "%s[CONFIRM_BREAK] user=%s symbol=%s session=%s/%s "
            "direction=%s confirm_ts=%s confirm_level=%.5f",
            LP, user_id, symbol, session_type, session_date,
            direction, confirm_ts.isoformat(), confirm_level,
        )

        # Final anti-spam check (race condition guard): re-check DB
        existing_now = _load_state(user_id, symbol, session_type, session_date)
        if existing_now and existing_now.get("triggered_at"):
            return False, state_advanced  # Another run already fired

        # Mark triggered in DB BEFORE sending email (idempotency)
        trigger_time = datetime.utcnow()
        state_fields.update({
            "state":               "TRIGGERED",
            "confirm_break_ts":    confirm_ts,
            "confirm_break_level": confirm_level,
            "triggered_at":        trigger_time,
        })
        _upsert_state(user_id, symbol, session_type, session_date, **state_fields)

        # Save history
        _save_history(user_id, symbol, session_type, session_date, {
            **computation,
            "session_high": session_high,
            "session_low":  session_low,
        })

        logger.info(
            "%s[TRIGGER] user=%s symbol=%s session=%s/%s "
            "direction=%s first_break=%.5f@%s confirm=%.5f@%s",
            LP, user_id, symbol, session_type, session_date,
            direction,
            first_break_level, first_break_ts.isoformat(),
            confirm_level, confirm_ts.isoformat(),
        )

        # Send email
        try:
            _send_alert_email(user_email, symbol, session_type, session_date, {
                **computation,
                "session_high": session_high,
                "session_low":  session_low,
            })
        except Exception as email_exc:
            logger.error(
                "%s[TRIGGER] email_failed user=%s symbol=%s err=%s",
                LP, user_id, symbol, email_exc,
            )

        triggered = True
        return triggered, state_advanced


# Module-level singleton
session_break_detector = SessionBreakDetector()
