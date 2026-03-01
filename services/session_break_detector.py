"""
Session Liquidity Sweep + Confirmation Detector – Asia + London (Israel time)

Replaces the former Session Break logic with a 4-state machine:
  STATE 1: IN_SESSION_TRACK    – track session_high/low during session
  STATE 2: WAIT_FIRST_SWEEP    – detect first wick break after session ends
  STATE 3: REQUIRE_REENTRY     – price must pull back before confirmation counts
  STATE 4: WAIT_CONFIRM_BREAK  – look for confirmation wick after reentry

Data source : Twelve Data – 5M candles (OHLC)
Sessions    : Asia 03:00–07:00 and London 09:00–12:00 (Asia/Jerusalem, DST-aware)
Break def.  : WICK only (candle.high / candle.low – NOT close)

Reentry rules (wick-based):
  UP  direction: reentered when later candle has  low  <= session_high
  DOWN direction: reentered when later candle has  high >= session_low

State persisted per (user_id, symbol, session_type, session_date).
session_date = Israel local date of the session (DST-correct).
Anti-spam: 1 trigger per (user_id, symbol, session_type, session_date).

Logging tags:
  [SESSION_SWEEP][SESSION_TRACK]
  [SESSION_SWEEP][SESSION_END]
  [SESSION_SWEEP][FIRST_SWEEP]
  [SESSION_SWEEP][REENTRY]
  [SESSION_SWEEP][CONFIRM]
  [SESSION_SWEEP][TRIGGER]
  [SESSION_SWEEP][HEARTBEAT]
"""

from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, time, timezone
from typing import Dict, List, Optional, Set, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9 fallback
    from backports.zoneinfo import ZoneInfo  # type: ignore

from database import db
from services.forex_data_provider import forex_data_provider, normalize_symbol

logger = logging.getLogger(__name__)

# Israel timezone (handles DST automatically via zoneinfo)
IL_TZ = ZoneInfo("Asia/Jerusalem")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class SessionSweepConfig:
    """Session times in Israel local time (Asia/Jerusalem). DST is handled at runtime."""

    SESSIONS: Dict[str, Dict] = {
        "asia": {
            "start": time(3, 0),   # 03:00 Israel
            "end":   time(7, 0),   # 07:00 Israel
        },
        "london": {
            "start": time(9, 0),   # 09:00 Israel
            "end":   time(12, 0),  # 12:00 Israel
        },
    }

    # 500 × 5 min ≈ 41 hours – covers current + previous sessions
    CANDLE_COUNT = 500

    UNHEALTHY_THRESHOLD_MINUTES = 30
    LOG_PREFIX = "[SESSION_SWEEP]"


# Backwards-compat alias (used in alert_processor.py)
SessionBreakConfig = SessionSweepConfig


# ---------------------------------------------------------------------------
# Timezone helpers
# ---------------------------------------------------------------------------

def _session_window_utc(session_type: str, session_date: date) -> Tuple[datetime, datetime]:
    """
    Convert Israel-local session times to UTC naive datetimes for the given
    Israel local date.  DST is handled correctly by zoneinfo.
    """
    cfg = SessionSweepConfig.SESSIONS[session_type]
    # Build timezone-aware datetimes in Israel time
    start_aware = datetime.combine(session_date, cfg["start"]).replace(tzinfo=IL_TZ)
    end_aware   = datetime.combine(session_date, cfg["end"]).replace(tzinfo=IL_TZ)
    # Strip tzinfo after converting so the rest of the code works with naive UTC
    start_utc = start_aware.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc   = end_aware.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def _candle_israel_date(utc_dt: datetime) -> date:
    """Return the Israel local date for a (naive) UTC datetime."""
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(IL_TZ).date()


def _israel_dates_in_candles(candles: List[Dict]) -> Set[date]:
    return {_candle_israel_date(c["timestamp"]) for c in candles}


# ---------------------------------------------------------------------------
# Candle partitioning
# ---------------------------------------------------------------------------

def _session_candles(candles: List[Dict], start_utc: datetime, end_utc: datetime) -> List[Dict]:
    """Return candles in [start_utc, end_utc)."""
    return [c for c in candles if start_utc <= c["timestamp"] < end_utc]


def _post_session_candles(candles: List[Dict], end_utc: datetime) -> List[Dict]:
    """Return candles at or after end_utc, sorted oldest→newest."""
    return sorted(
        [c for c in candles if c["timestamp"] >= end_utc],
        key=lambda c: c["timestamp"],
    )


def find_relevant_sessions(
    candles: List[Dict],
    now_utc: datetime,
) -> List[Tuple[str, date]]:
    """
    Return (session_type, israel_session_date) pairs that:
      - have at least one candle inside the session window, AND
      - the session has already ended (end_utc <= now_utc).
    session_date is the Israel local date of the session.
    """
    results: List[Tuple[str, date]] = []
    for session_type in SessionSweepConfig.SESSIONS:
        for d in sorted(_israel_dates_in_candles(candles)):
            start_utc, end_utc = _session_window_utc(session_type, d)
            if now_utc < end_utc:
                continue  # session not yet over
            if not _session_candles(candles, start_utc, end_utc):
                continue  # no session data in this window
            results.append((session_type, d))
    return sorted(results, key=lambda x: (x[1], x[0]))


# ---------------------------------------------------------------------------
# Core 4-state detection (pure functions – no DB, no I/O)
# ---------------------------------------------------------------------------

def compute_sweep_confirmation(
    session_candles: List[Dict],
    post_candles: List[Dict],
) -> Optional[Dict]:
    """
    Apply the 4-state sweep-and-confirm machine to pre-partitioned candle lists.

    Parameters
    ----------
    session_candles : candles during the session window (already sorted)
    post_candles    : candles after session window, sorted oldest→newest

    Returns None if no session candles.
    Otherwise returns a dict with at minimum:
      state           – 'WAIT_FIRST_SWEEP' | 'REQUIRE_REENTRY' |
                        'WAIT_CONFIRM_BREAK' | 'TRIGGERED'
      session_high    – float
      session_low     – float
      confirmed       – bool
    Additional keys present depending on how far the state machine advanced.
    """
    if not session_candles:
        return None

    session_high = max(c["high"] for c in session_candles)
    session_low  = min(c["low"]  for c in session_candles)

    if not post_candles:
        return {
            "state":        "WAIT_FIRST_SWEEP",
            "session_high": session_high,
            "session_low":  session_low,
            "confirmed":    False,
        }

    # ── STATE 2: find first sweep (UP or DOWN) ────────────────────────────
    first_up:   Optional[Tuple[datetime, float]] = None  # (ts, level)
    first_down: Optional[Tuple[datetime, float]] = None

    for c in post_candles:
        if first_up is None and c["high"] > session_high:
            first_up = (c["timestamp"], c["high"])
        if first_down is None and c["low"] < session_low:
            first_down = (c["timestamp"], c["low"])
        if first_up and first_down:
            break

    if first_up is None and first_down is None:
        return {
            "state":        "WAIT_FIRST_SWEEP",
            "session_high": session_high,
            "session_low":  session_low,
            "confirmed":    False,
        }

    # Chronological tiebreak: UP wins on same candle
    if first_up and first_down:
        if first_up[0] <= first_down[0]:
            direction, first_sweep_ts, first_sweep_level = "UP",   first_up[0],   first_up[1]
        else:
            direction, first_sweep_ts, first_sweep_level = "DOWN", first_down[0], first_down[1]
    elif first_up:
        direction, first_sweep_ts, first_sweep_level = "UP",   first_up[0],   first_up[1]
    else:
        direction, first_sweep_ts, first_sweep_level = "DOWN", first_down[0], first_down[1]

    # ── STATE 3 + 4: reentry check then confirmation ──────────────────────
    reentered   = False
    reentry_ts: Optional[datetime] = None

    for c in post_candles:
        if c["timestamp"] <= first_sweep_ts:
            continue  # must be strictly after first sweep

        # STATE 3: detect reentry (wick-based pullback)
        if not reentered:
            if direction == "UP"   and c["low"]  <= session_high:
                reentered  = True
                reentry_ts = c["timestamp"]
            elif direction == "DOWN" and c["high"] >= session_low:
                reentered  = True
                reentry_ts = c["timestamp"]

        # STATE 4: detect confirmation (only once reentered)
        if reentered:
            if direction == "UP" and c["high"] > first_sweep_level:
                return {
                    "state":             "TRIGGERED",
                    "session_high":      session_high,
                    "session_low":       session_low,
                    "direction":         direction,
                    "first_sweep_ts":    first_sweep_ts,
                    "first_sweep_level": first_sweep_level,
                    "reentered":         True,
                    "reentry_ts":        reentry_ts,
                    "confirm_ts":        c["timestamp"],
                    "confirm_level":     c["high"],
                    "confirmed":         True,
                }
            if direction == "DOWN" and c["low"] < first_sweep_level:
                return {
                    "state":             "TRIGGERED",
                    "session_high":      session_high,
                    "session_low":       session_low,
                    "direction":         direction,
                    "first_sweep_ts":    first_sweep_ts,
                    "first_sweep_level": first_sweep_level,
                    "reentered":         True,
                    "reentry_ts":        reentry_ts,
                    "confirm_ts":        c["timestamp"],
                    "confirm_level":     c["low"],
                    "confirmed":         True,
                }

    # Not yet triggered
    return {
        "state":             "WAIT_CONFIRM_BREAK" if reentered else "REQUIRE_REENTRY",
        "session_high":      session_high,
        "session_low":       session_low,
        "direction":         direction,
        "first_sweep_ts":    first_sweep_ts,
        "first_sweep_level": first_sweep_level,
        "reentered":         reentered,
        "reentry_ts":        reentry_ts,
        "confirmed":         False,
    }


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _load_state(user_id: int, symbol: str, session_type: str,
                session_date: date) -> Optional[Dict]:
    row = db.execute(
        """
        SELECT * FROM session_break_state
        WHERE user_id = %s AND symbol = %s
          AND session_type = %s AND session_date = %s
        """,
        (user_id, symbol, session_type, session_date),
        fetchone=True,
    )
    return dict(row) if row else None


def _upsert_state(user_id: int, symbol: str, session_type: str,
                  session_date: date, **fields) -> None:
    set_parts = ", ".join(f"{k} = %s" for k in fields)
    values    = list(fields.values())
    db.execute(
        f"""
        INSERT INTO session_break_state
            (user_id, symbol, session_type, session_date,
             {', '.join(fields.keys())}, updated_at)
        VALUES
            (%s, %s, %s, %s,
             {', '.join(['%s'] * len(fields))}, NOW())
        ON CONFLICT (user_id, symbol, session_type, session_date) DO UPDATE
          SET {set_parts}, updated_at = NOW()
        """,
        [user_id, symbol, session_type, str(session_date)] + values + values,
    )


def _save_history(user_id: int, symbol: str, session_type: str,
                  session_date: date, result: Dict) -> Optional[int]:
    row = db.execute(
        """
        INSERT INTO session_break_history (
            user_id, symbol, session_type, session_date,
            direction, session_high, session_low,
            first_break_ts, first_break_level,
            confirm_break_ts, confirm_break_level,
            triggered_at
        ) VALUES (%s, %s, %s, %s,  %s,  %s, %s,  %s, %s,  %s, %s,  NOW())
        ON CONFLICT (user_id, symbol, session_type, session_date) DO NOTHING
        RETURNING id
        """,
        (
            user_id, symbol, session_type, str(session_date),
            result["direction"],
            result["session_high"], result["session_low"],
            result["first_sweep_ts"], result["first_sweep_level"],
            result["confirm_ts"],     result["confirm_level"],
        ),
        fetchone=True,
    )
    return row["id"] if row else None


def _send_alert_email(user_email: str, symbol: str, session_type: str,
                      session_date: date, result: Dict) -> bool:
    from email_sender import email_sender
    return email_sender.send_session_break_email(
        to_email=user_email,
        symbol=symbol,
        session_type=session_type,
        session_date=str(session_date),
        direction=result["direction"],
        session_high=result["session_high"],
        session_low=result["session_low"],
        first_break_ts=result["first_sweep_ts"].isoformat(),
        first_break_level=result["first_sweep_level"],
        confirm_break_ts=result["confirm_ts"].isoformat(),
        confirm_break_level=result["confirm_level"],
    )


# ---------------------------------------------------------------------------
# Main detector orchestrator
# ---------------------------------------------------------------------------

class SessionBreakDetector:
    """
    Orchestrates sweep-confirmation detection across all users and their
    forex watchlists.  Designed to be called periodically by the scheduler.
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
        candle_cache is a shared dict {symbol: candles} for this scheduler run
        to avoid redundant Twelve Data API calls across users.
        """
        LP = SessionSweepConfig.LOG_PREFIX
        metrics = {"symbols": 0, "triggers": 0, "states_advanced": 0, "errors": 0}

        watchlist = db.execute(
            "SELECT symbol FROM forex_watchlist WHERE user_id = %s ORDER BY added_at",
            (user_id,), fetchall=True,
        )
        symbols = [r["symbol"] for r in (watchlist or [])]

        if not symbols:
            return metrics

        metrics["symbols"] = len(symbols)
        now_utc = datetime.utcnow()

        for symbol in symbols:
            try:
                if symbol not in candle_cache:
                    logger.debug(
                        "%s[SESSION_TRACK] user=%s symbol=%s fetching count=%d",
                        LP, user_id, symbol, SessionSweepConfig.CANDLE_COUNT,
                    )
                    candles = forex_data_provider.get_recent_candles(
                        symbol, timeframe="5m", count=SessionSweepConfig.CANDLE_COUNT
                    )
                    candle_cache[symbol] = candles or []
                else:
                    candles = candle_cache[symbol]

                if not candles:
                    logger.warning(
                        "%s[SESSION_TRACK] user=%s symbol=%s no_candles", LP, user_id, symbol
                    )
                    continue

                r = self._process_symbol(user_id, user_email, symbol, candles, now_utc, run_id)
                metrics["triggers"]        += r["triggers"]
                metrics["states_advanced"] += r["states_advanced"]

            except Exception as exc:
                metrics["errors"] += 1
                logger.error(
                    "%s[ERROR] run_id=%s user=%s symbol=%s err=%s",
                    LP, run_id, user_id, symbol, exc, exc_info=True,
                )

        return metrics

    def _process_symbol(self, user_id, user_email, symbol, candles, now_utc, run_id):
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
        LP = SessionSweepConfig.LOG_PREFIX

        # ── Anti-spam ─────────────────────────────────────────────────────
        existing = _load_state(user_id, symbol, session_type, session_date)
        if existing and existing.get("triggered_at"):
            return False, False

        start_utc, end_utc = _session_window_utc(session_type, session_date)
        ses_candles  = _session_candles(all_candles, start_utc, end_utc)
        post_candles = _post_session_candles(all_candles, end_utc)

        if not ses_candles:
            return False, False

        session_high = max(c["high"] for c in ses_candles)
        session_low  = min(c["low"]  for c in ses_candles)

        logger.debug(
            "%s[SESSION_END] user=%s symbol=%s session=%s/%s "
            "session_high=%.5f session_low=%.5f post_candles=%d",
            LP, user_id, symbol, session_type, session_date,
            session_high, session_low, len(post_candles),
        )

        computation = compute_sweep_confirmation(ses_candles, post_candles)
        if computation is None:
            return False, False

        # Always persist session high/low + current state
        state_fields: Dict = {
            "session_high": session_high,
            "session_low":  session_low,
            "state":        computation["state"],
        }

        if computation["state"] == "WAIT_FIRST_SWEEP":
            _upsert_state(user_id, symbol, session_type, session_date, **state_fields)
            return False, False

        # First sweep found
        direction          = computation["direction"]
        first_sweep_ts     = computation["first_sweep_ts"]
        first_sweep_level  = computation["first_sweep_level"]
        reentered          = computation["reentered"]
        reentry_ts         = computation.get("reentry_ts")

        logger.info(
            "%s[FIRST_SWEEP] user=%s symbol=%s session=%s/%s "
            "direction=%s ts=%s level=%.5f",
            LP, user_id, symbol, session_type, session_date,
            direction, first_sweep_ts.isoformat(), first_sweep_level,
        )

        state_fields.update({
            "direction":         direction,
            "first_break_ts":    first_sweep_ts,    # reuse existing column
            "first_break_level": first_sweep_level,
            "reentered":         reentered,
        })
        if reentry_ts:
            state_fields["reentry_ts"] = reentry_ts
            logger.info(
                "%s[REENTRY] user=%s symbol=%s session=%s/%s reentered=True ts=%s",
                LP, user_id, symbol, session_type, session_date, reentry_ts.isoformat(),
            )

        state_advanced = True

        if not computation.get("confirmed"):
            _upsert_state(user_id, symbol, session_type, session_date, **state_fields)
            return False, state_advanced

        # ── TRIGGER ───────────────────────────────────────────────────────
        confirm_ts    = computation["confirm_ts"]
        confirm_level = computation["confirm_level"]

        logger.info(
            "%s[CONFIRM] user=%s symbol=%s session=%s/%s "
            "direction=%s confirm_ts=%s confirm_level=%.5f",
            LP, user_id, symbol, session_type, session_date,
            direction, confirm_ts.isoformat(), confirm_level,
        )

        # Final race-condition guard
        existing_now = _load_state(user_id, symbol, session_type, session_date)
        if existing_now and existing_now.get("triggered_at"):
            return False, state_advanced

        trigger_time = datetime.utcnow()
        state_fields.update({
            "state":               "TRIGGERED",
            "confirm_break_ts":    confirm_ts,
            "confirm_break_level": confirm_level,
            "triggered_at":        trigger_time,
        })
        _upsert_state(user_id, symbol, session_type, session_date, **state_fields)

        history_id = _save_history(user_id, symbol, session_type, session_date, {
            **computation,
            "session_high":      session_high,
            "session_low":       session_low,
            "first_sweep_ts":    first_sweep_ts,
            "first_sweep_level": first_sweep_level,
        })

        logger.info(
            "%s[TRIGGER] user=%s symbol=%s session=%s/%s "
            "direction=%s sweep=%.5f@%s confirm=%.5f@%s history_id=%s",
            LP, user_id, symbol, session_type, session_date,
            direction,
            first_sweep_level, first_sweep_ts.isoformat(),
            confirm_level,     confirm_ts.isoformat(),
            history_id,
        )

        email_sent = False
        try:
            email_sent = _send_alert_email(user_email, symbol, session_type, session_date, {
                **computation,
                "session_high":      session_high,
                "session_low":       session_low,
                "first_sweep_ts":    first_sweep_ts,
                "first_sweep_level": first_sweep_level,
            })
        except Exception as email_exc:
            logger.error(
                "%s[TRIGGER] email_failed user=%s symbol=%s err=%s",
                LP, user_id, symbol, email_exc,
            )

        logger.info(
            "%s[TRIGGER] email_sent=%s user=%s symbol=%s",
            LP, email_sent, user_id, symbol,
        )
        return True, state_advanced


# Module-level singleton
session_break_detector = SessionBreakDetector()
