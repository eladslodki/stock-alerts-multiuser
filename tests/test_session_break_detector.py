"""
Deterministic unit tests for the Session Liquidity Sweep + Confirmation detector.

All tests use synthetic 5M OHLC candles – no DB, no network, no real timezone data
required beyond what the system provides.  The pure functions
`compute_sweep_confirmation` and `find_relevant_sessions` are tested directly.

Test cases:
  1.  No sweep at all                      → WAIT_FIRST_SWEEP (no trigger)
  2.  Sweep found, no reentry              → REQUIRE_REENTRY (no trigger)
  3.  Sweep + reentry, no confirm          → WAIT_CONFIRM_BREAK (no trigger)
  4.  Full path: sweep → reentry → confirm → TRIGGERED (confirmed=True)
  5.  Idempotency                          → same result on re-run
  6.  UP sweep first, DOWN later           → direction=UP locked
  7.  DOWN sweep first, UP later           → direction=DOWN locked
  8.  Same-candle UP+DOWN                  → UP wins (tiebreaker)
  9.  Wick-only: close inside range        → no sweep (close doesn't matter)
  10. Reentry is wick-based (low/high)     → close doesn't matter
  11. Confirm candle can be reentry candle → simultaneous reentry+confirm allowed
  12. find_relevant_sessions               → only ended sessions, Israel dates
  13. _session_window_utc DST sanity       → winter vs summer UTC offsets differ
  14. _candle_israel_date                  → correct Israel date conversion
"""

import sys
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional
from unittest.mock import MagicMock

# ── Stub heavy dependencies before importing the module under test ──────────
_mock_db = MagicMock()
_mock_db_module = MagicMock()
_mock_db_module.db = _mock_db
sys.modules.setdefault("psycopg2",        MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())
sys.modules.setdefault("database",        _mock_db_module)

_mock_fdp = MagicMock()
_mock_fdp.forex_data_provider = MagicMock()
_mock_fdp.normalize_symbol    = MagicMock(return_value=("EUR/USD", None))
sys.modules.setdefault("services.forex_data_provider", _mock_fdp)
sys.modules.setdefault("email_sender", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from services.session_break_detector import (
    compute_sweep_confirmation,
    find_relevant_sessions,
    _session_window_utc,
    _session_candles,
    _post_session_candles,
    _candle_israel_date,
    SessionSweepConfig,
)

# Also check the backwards-compat alias
from services.session_break_detector import SessionBreakConfig


# ---------------------------------------------------------------------------
# Candle builder
# ---------------------------------------------------------------------------

def c(ts: datetime, high: float, low: float,
      open_: float = None, close: float = None) -> Dict:
    mid = (high + low) / 2
    return {
        "timestamp": ts,
        "open":  open_  if open_  is not None else mid,
        "high":  high,
        "low":   low,
        "close": close  if close  is not None else mid,
    }


# Reference Israel date (winter → IST = UTC+2)
# Asia session 03:00–07:00 IST  = 01:00–05:00 UTC
# London session 09:00–12:00 IST = 07:00–10:00 UTC
IL_WINTER_DATE  = date(2024, 1, 15)
ASIA_START_UTC  = datetime(2024, 1, 15, 1, 0)   # 03:00 IST → 01:00 UTC
ASIA_END_UTC    = datetime(2024, 1, 15, 5, 0)   # 07:00 IST → 05:00 UTC
LON_START_UTC   = datetime(2024, 1, 15, 7, 0)   # 09:00 IST → 07:00 UTC
LON_END_UTC     = datetime(2024, 1, 15, 10, 0)  # 12:00 IST → 10:00 UTC


def build_session(sh: float = 1.1000, sl: float = 1.0900,
                  start: datetime = ASIA_START_UTC,
                  end:   datetime = ASIA_END_UTC) -> List[Dict]:
    """12 session candles with given high/low."""
    candles = []
    for i in range(12):
        ts = start + timedelta(minutes=5 * i)
        candles.append(c(ts, high=sh, low=sl))
    return candles


def post(start: datetime = ASIA_END_UTC,
         high: float = 1.0950, low: float = 1.0950,
         count: int = 5) -> List[Dict]:
    """Post-session candles all with the same high/low."""
    return [
        c(start + timedelta(minutes=5 * i), high=high, low=low)
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# 1. No sweep at all
# ---------------------------------------------------------------------------

class TestNoSweep(unittest.TestCase):

    def test_no_post_candles(self):
        ses = build_session(sh=1.1000, sl=1.0900)
        r = compute_sweep_confirmation(ses, [])
        self.assertEqual(r["state"], "WAIT_FIRST_SWEEP")
        self.assertFalse(r["confirmed"])

    def test_post_candles_inside_range(self):
        ses = build_session(sh=1.1000, sl=1.0900)
        pc  = post(high=1.0980, low=1.0920, count=20)
        r   = compute_sweep_confirmation(ses, pc)
        self.assertEqual(r["state"], "WAIT_FIRST_SWEEP")
        self.assertFalse(r["confirmed"])

    def test_empty_session(self):
        r = compute_sweep_confirmation([], [])
        self.assertIsNone(r)


# ---------------------------------------------------------------------------
# 2. Sweep found but no reentry
# ---------------------------------------------------------------------------

class TestSweepNoReentry(unittest.TestCase):

    def test_up_sweep_no_reentry(self):
        """UP sweep, but post-session candles never pull back below session_high."""
        ses = build_session(sh=1.1000, sl=1.0900)
        # First candle sweeps above session_high; all subsequent stay above
        pc = [
            c(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.1001),  # sweep UP
            c(ASIA_END_UTC + timedelta(minutes=10), high=1.1020, low=1.1002),  # no pullback
            c(ASIA_END_UTC + timedelta(minutes=15), high=1.1030, low=1.1003),  # no pullback
        ]
        r = compute_sweep_confirmation(ses, pc)
        self.assertEqual(r["state"], "REQUIRE_REENTRY")
        self.assertEqual(r["direction"], "UP")
        self.assertFalse(r["reentered"])
        self.assertFalse(r["confirmed"])

    def test_down_sweep_no_reentry(self):
        """DOWN sweep, but price stays below session_low."""
        ses = build_session(sh=1.1000, sl=1.0900)
        pc = [
            c(ASIA_END_UTC + timedelta(minutes=5),  high=1.0899, low=1.0880),  # sweep DOWN
            c(ASIA_END_UTC + timedelta(minutes=10), high=1.0895, low=1.0870),  # still below
        ]
        r = compute_sweep_confirmation(ses, pc)
        self.assertEqual(r["state"], "REQUIRE_REENTRY")
        self.assertEqual(r["direction"], "DOWN")
        self.assertFalse(r["reentered"])


# ---------------------------------------------------------------------------
# 3. Sweep + reentry, no confirmation yet
# ---------------------------------------------------------------------------

class TestSweepReentryNoConfirm(unittest.TestCase):

    def test_up_sweep_reentry_no_confirm(self):
        """UP sweep → reentry (low <= session_high) → no confirm wick yet."""
        ses = build_session(sh=1.1000, sl=1.0900)
        pc = [
            c(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.1001),  # sweep UP
            c(ASIA_END_UTC + timedelta(minutes=10), high=1.1005, low=1.0995),  # reentry (low<=1.1000)
            c(ASIA_END_UTC + timedelta(minutes=15), high=1.1008, low=1.1000),  # still below sweep
        ]
        r = compute_sweep_confirmation(ses, pc)
        self.assertEqual(r["state"], "WAIT_CONFIRM_BREAK")
        self.assertEqual(r["direction"], "UP")
        self.assertTrue(r["reentered"])
        self.assertFalse(r["confirmed"])
        self.assertEqual(r["reentry_ts"], ASIA_END_UTC + timedelta(minutes=10))

    def test_down_sweep_reentry_no_confirm(self):
        """DOWN sweep → reentry (high >= session_low) → no confirm wick yet."""
        ses = build_session(sh=1.1000, sl=1.0900)
        pc = [
            c(ASIA_END_UTC + timedelta(minutes=5),  high=1.0901, low=1.0885),  # sweep DOWN
            c(ASIA_END_UTC + timedelta(minutes=10), high=1.0902, low=1.0887),  # reentry (high>=1.0900)
            c(ASIA_END_UTC + timedelta(minutes=15), high=1.0895, low=1.0888),  # above sweep, no confirm
        ]
        r = compute_sweep_confirmation(ses, pc)
        self.assertEqual(r["state"], "WAIT_CONFIRM_BREAK")
        self.assertEqual(r["direction"], "DOWN")
        self.assertTrue(r["reentered"])
        self.assertFalse(r["confirmed"])


# ---------------------------------------------------------------------------
# 4. Full path: sweep → reentry → confirm → TRIGGERED
# ---------------------------------------------------------------------------

class TestFullTrigger(unittest.TestCase):

    def test_up_full_trigger(self):
        ses = build_session(sh=1.1000, sl=1.0900)
        sweep_ts   = ASIA_END_UTC + timedelta(minutes=5)
        reentry_ts = ASIA_END_UTC + timedelta(minutes=10)
        confirm_ts = ASIA_END_UTC + timedelta(minutes=15)

        pc = [
            c(sweep_ts,   high=1.1010, low=1.1001),  # sweep UP (first_sweep_level=1.1010)
            c(reentry_ts, high=1.1005, low=1.0995),  # reentry: low(1.0995)<=session_high(1.1000)
            c(confirm_ts, high=1.1020, low=1.0998),  # confirm: high(1.1020)>first_sweep(1.1010)
        ]

        r = compute_sweep_confirmation(ses, pc)
        self.assertEqual(r["state"],             "TRIGGERED")
        self.assertTrue(r["confirmed"])
        self.assertEqual(r["direction"],          "UP")
        self.assertAlmostEqual(r["first_sweep_level"], 1.1010)
        self.assertEqual(r["first_sweep_ts"],     sweep_ts)
        self.assertTrue(r["reentered"])
        self.assertEqual(r["reentry_ts"],         reentry_ts)
        self.assertEqual(r["confirm_ts"],         confirm_ts)
        self.assertAlmostEqual(r["confirm_level"],     1.1020)

    def test_down_full_trigger(self):
        ses = build_session(sh=1.1000, sl=1.0900)
        sweep_ts   = ASIA_END_UTC + timedelta(minutes=5)
        reentry_ts = ASIA_END_UTC + timedelta(minutes=10)
        confirm_ts = ASIA_END_UTC + timedelta(minutes=15)

        pc = [
            c(sweep_ts,   high=1.0901, low=1.0885),  # sweep DOWN (level=1.0885)
            c(reentry_ts, high=1.0902, low=1.0888),  # reentry: high(1.0902)>=session_low(1.0900)
            c(confirm_ts, high=1.0895, low=1.0880),  # confirm: low(1.0880)<first_sweep(1.0885)
        ]

        r = compute_sweep_confirmation(ses, pc)
        self.assertEqual(r["state"],   "TRIGGERED")
        self.assertTrue(r["confirmed"])
        self.assertEqual(r["direction"], "DOWN")
        self.assertAlmostEqual(r["first_sweep_level"], 1.0885)
        self.assertAlmostEqual(r["confirm_level"],     1.0880)

    def test_reentry_and_confirm_same_candle(self):
        """A single candle can both re-enter the range AND confirm the sweep."""
        ses = build_session(sh=1.1000, sl=1.0900)
        pc = [
            c(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.1001),  # sweep UP
            # Wide candle: low touches back to session_high (reentry) and high exceeds sweep (confirm)
            c(ASIA_END_UTC + timedelta(minutes=10), high=1.1025, low=1.0990),
        ]
        r = compute_sweep_confirmation(ses, pc)
        self.assertEqual(r["state"], "TRIGGERED")
        self.assertTrue(r["confirmed"])
        self.assertAlmostEqual(r["confirm_level"], 1.1025)


# ---------------------------------------------------------------------------
# 5. Idempotency – same candles → same result
# ---------------------------------------------------------------------------

class TestIdempotency(unittest.TestCase):

    def test_triggered_is_deterministic(self):
        ses = build_session(sh=1.1000, sl=1.0900)
        pc = [
            c(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.1001),
            c(ASIA_END_UTC + timedelta(minutes=10), high=1.1005, low=1.0995),
            c(ASIA_END_UTC + timedelta(minutes=15), high=1.1020, low=1.0998),
        ]
        r1 = compute_sweep_confirmation(ses, pc)
        r2 = compute_sweep_confirmation(ses, pc)

        self.assertEqual(r1["state"],         r2["state"])
        self.assertEqual(r1["direction"],     r2["direction"])
        self.assertEqual(r1["confirm_ts"],    r2["confirm_ts"])
        self.assertEqual(r1["confirm_level"], r2["confirm_level"])
        self.assertTrue(r1["confirmed"])

    def test_no_sweep_is_stable(self):
        ses = build_session()
        pc  = post(high=1.0980, low=1.0920)
        r1  = compute_sweep_confirmation(ses, pc)
        r2  = compute_sweep_confirmation(ses, pc)
        self.assertEqual(r1["state"], r2["state"])
        self.assertFalse(r1["confirmed"])


# ---------------------------------------------------------------------------
# 6+7. Direction locking: first chronological sweep wins
# ---------------------------------------------------------------------------

class TestDirectionLocking(unittest.TestCase):

    def test_up_before_down_locks_up(self):
        ses = build_session(sh=1.1000, sl=1.0900)
        pc = [
            c(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.0910),  # UP sweep first
            c(ASIA_END_UTC + timedelta(minutes=10), high=1.1005, low=1.0880),  # DOWN sweep later
            c(ASIA_END_UTC + timedelta(minutes=15), high=1.1005, low=1.0995),  # reentry for UP
            c(ASIA_END_UTC + timedelta(minutes=20), high=1.1015, low=1.0998),  # UP confirm
        ]
        r = compute_sweep_confirmation(ses, pc)
        self.assertEqual(r["direction"], "UP")
        self.assertTrue(r["confirmed"])

    def test_down_before_up_locks_down(self):
        ses = build_session(sh=1.1000, sl=1.0900)
        pc = [
            c(ASIA_END_UTC + timedelta(minutes=5),  high=1.0999, low=1.0880),  # DOWN sweep first
            c(ASIA_END_UTC + timedelta(minutes=10), high=1.1010, low=1.0885),  # UP sweep later
            c(ASIA_END_UTC + timedelta(minutes=15), high=1.0903, low=1.0888),  # reentry for DOWN
            c(ASIA_END_UTC + timedelta(minutes=20), high=1.0895, low=1.0875),  # DOWN confirm
        ]
        r = compute_sweep_confirmation(ses, pc)
        self.assertEqual(r["direction"], "DOWN")
        self.assertTrue(r["confirmed"])


# ---------------------------------------------------------------------------
# 8. Same-candle sweep of both sides → UP wins
# ---------------------------------------------------------------------------

class TestSameCandleTiebreak(unittest.TestCase):

    def test_up_wins_on_same_candle(self):
        ses = build_session(sh=1.1000, sl=1.0900)
        pc = [
            # Wide candle: high > session_high AND low < session_low simultaneously
            c(ASIA_END_UTC + timedelta(minutes=5),  high=1.1020, low=1.0880),
            c(ASIA_END_UTC + timedelta(minutes=10), high=1.1005, low=1.0995),  # reentry for UP
            c(ASIA_END_UTC + timedelta(minutes=15), high=1.1025, low=1.0998),  # UP confirm
        ]
        r = compute_sweep_confirmation(ses, pc)
        self.assertEqual(r["direction"], "UP")
        self.assertTrue(r["confirmed"])


# ---------------------------------------------------------------------------
# 9. Wick-only: close inside range does NOT constitute a sweep
# ---------------------------------------------------------------------------

class TestWickOnly(unittest.TestCase):

    def test_close_inside_range_not_a_sweep(self):
        """Even if close is above session_high, what matters is candle.high."""
        ses = build_session(sh=1.1000, sl=1.0900)
        # Candle that closes above session_high but whose HIGH is still below it
        # (physically impossible for a real OHLC – but ensures logic uses high, not close)
        # Simulate: high=1.0995 (below session_high=1.1000), close=1.1010 (not used)
        pc = [c(ASIA_END_UTC + timedelta(minutes=5), high=1.0995, low=1.0950,
                close=1.1010)]  # close above, but high is not
        r = compute_sweep_confirmation(ses, pc)
        self.assertEqual(r["state"], "WAIT_FIRST_SWEEP")

    def test_high_exactly_at_session_high_not_a_sweep(self):
        """high == session_high (not strictly greater) → NOT a sweep."""
        ses = build_session(sh=1.1000, sl=1.0900)
        pc  = [c(ASIA_END_UTC + timedelta(minutes=5), high=1.1000, low=1.0950)]
        r   = compute_sweep_confirmation(ses, pc)
        self.assertEqual(r["state"], "WAIT_FIRST_SWEEP")


# ---------------------------------------------------------------------------
# 10. Reentry is wick-based (low/high), close does not matter
# ---------------------------------------------------------------------------

class TestReentryWickBased(unittest.TestCase):

    def test_reentry_triggered_by_low_wick(self):
        """For UP direction, reentered=True when candle.low <= session_high."""
        ses = build_session(sh=1.1000, sl=1.0900)
        pc = [
            c(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.1002),  # sweep UP
            # Reentry: low=1.1000 (exactly session_high) – should trigger reentry
            c(ASIA_END_UTC + timedelta(minutes=10), high=1.1008, low=1.1000, close=1.1005),
        ]
        r = compute_sweep_confirmation(ses, pc)
        self.assertTrue(r["reentered"])

    def test_no_reentry_if_low_above_session_high(self):
        """low > session_high → NOT reentered for UP direction."""
        ses = build_session(sh=1.1000, sl=1.0900)
        pc = [
            c(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.1002),  # sweep UP
            c(ASIA_END_UTC + timedelta(minutes=10), high=1.1008, low=1.1001),  # low=1.1001>1.1000 NO reentry
        ]
        r = compute_sweep_confirmation(ses, pc)
        self.assertFalse(r["reentered"])
        self.assertEqual(r["state"], "REQUIRE_REENTRY")


# ---------------------------------------------------------------------------
# 11. Confirm candle must be strictly AFTER first sweep
# ---------------------------------------------------------------------------

class TestConfirmAfterSweep(unittest.TestCase):

    def test_confirm_requires_candle_after_sweep_ts(self):
        """A candle with ts == first_sweep_ts cannot be the confirm."""
        ses = build_session(sh=1.1000, sl=1.0900)
        sweep_ts = ASIA_END_UTC + timedelta(minutes=5)
        pc = [
            c(sweep_ts, high=1.1050, low=1.0990),  # sweep UP; also re-enters (low<=1.1000)
            # No LATER candle that exceeds 1.1050
        ]
        r = compute_sweep_confirmation(ses, pc)
        # sweep_ts candle itself provides reentry (low=1.0990<=1.1000) but cannot confirm itself
        # since there's no candle with ts > sweep_ts and high > 1.1050
        self.assertFalse(r.get("confirmed", True))


# ---------------------------------------------------------------------------
# 12. find_relevant_sessions
# ---------------------------------------------------------------------------

class TestFindRelevantSessions(unittest.TestCase):

    def _make_candles_range(self, start: datetime, end: datetime) -> List[Dict]:
        result = []
        ts = start
        while ts < end:
            result.append(c(ts, high=1.1, low=1.09))
            ts += timedelta(minutes=5)
        return result

    def test_ended_session_included(self):
        candles = self._make_candles_range(ASIA_START_UTC, ASIA_END_UTC + timedelta(hours=2))
        now_utc = ASIA_END_UTC + timedelta(hours=1)
        sessions = find_relevant_sessions(candles, now_utc)
        self.assertIn(("asia", IL_WINTER_DATE), sessions)

    def test_not_yet_ended_session_excluded(self):
        candles = self._make_candles_range(ASIA_START_UTC, ASIA_END_UTC)
        now_utc = ASIA_END_UTC - timedelta(minutes=30)  # session still active
        sessions = find_relevant_sessions(candles, now_utc)
        self.assertNotIn(("asia", IL_WINTER_DATE), sessions)

    def test_both_sessions_on_full_day(self):
        # Candles 01:00–11:00 UTC cover both Asia (01:00–05:00) and London (07:00–10:00)
        candles = self._make_candles_range(
            ASIA_START_UTC,
            datetime(2024, 1, 15, 11, 0),
        )
        now_utc = datetime(2024, 1, 15, 11, 0)
        sessions = find_relevant_sessions(candles, now_utc)
        stypes = {s for s, _ in sessions}
        self.assertIn("asia",   stypes)
        self.assertIn("london", stypes)

    def test_no_session_candles_excluded(self):
        """Only post-session candles → no session data → excluded."""
        # Candles only from 06:00 UTC onward (after Asia end 05:00 UTC)
        candles = self._make_candles_range(
            datetime(2024, 1, 15, 6, 0),
            datetime(2024, 1, 15, 11, 0),
        )
        now_utc = datetime(2024, 1, 15, 11, 0)
        sessions = find_relevant_sessions(candles, now_utc)
        # Asia session has no candles in 01:00-05:00 UTC
        self.assertNotIn(("asia", IL_WINTER_DATE), sessions)


# ---------------------------------------------------------------------------
# 13. _session_window_utc DST sanity: winter vs summer
# ---------------------------------------------------------------------------

class TestDSTConversion(unittest.TestCase):
    """
    Israel Standard Time (IST) = UTC+2  (winter, roughly Nov–Mar)
    Israel Daylight Time (IDT) = UTC+3  (summer, roughly Apr–Oct)

    Asia session 03:00 Israel:
      Winter → 01:00 UTC
      Summer → 00:00 UTC

    London session 09:00 Israel:
      Winter → 07:00 UTC
      Summer → 06:00 UTC
    """

    def test_winter_asia_start(self):
        start_utc, end_utc = _session_window_utc("asia", date(2024, 1, 15))
        # IST = UTC+2 → 03:00 IST = 01:00 UTC
        self.assertEqual(start_utc, datetime(2024, 1, 15, 1, 0))
        self.assertEqual(end_utc,   datetime(2024, 1, 15, 5, 0))

    def test_summer_asia_start(self):
        start_utc, end_utc = _session_window_utc("asia", date(2024, 7, 15))
        # IDT = UTC+3 → 03:00 IDT = 00:00 UTC
        self.assertEqual(start_utc, datetime(2024, 7, 15, 0, 0))
        self.assertEqual(end_utc,   datetime(2024, 7, 15, 4, 0))

    def test_winter_london_start(self):
        start_utc, end_utc = _session_window_utc("london", date(2024, 1, 15))
        self.assertEqual(start_utc, datetime(2024, 1, 15, 7, 0))
        self.assertEqual(end_utc,   datetime(2024, 1, 15, 10, 0))

    def test_summer_london_start(self):
        start_utc, end_utc = _session_window_utc("london", date(2024, 7, 15))
        self.assertEqual(start_utc, datetime(2024, 7, 15, 6, 0))
        self.assertEqual(end_utc,   datetime(2024, 7, 15, 9, 0))

    def test_winter_and_summer_differ(self):
        """Sanity: winter and summer UTC offsets must be different."""
        w_start, _ = _session_window_utc("asia", date(2024, 1, 15))
        s_start, _ = _session_window_utc("asia", date(2024, 7, 15))
        self.assertNotEqual(w_start.hour, s_start.hour,
                            "Winter and summer UTC start hours should differ (DST)")


# ---------------------------------------------------------------------------
# 14. _candle_israel_date
# ---------------------------------------------------------------------------

class TestCandleIsraelDate(unittest.TestCase):

    def test_winter_candle_date(self):
        # 23:00 UTC on Jan 14 = 01:00 IST on Jan 15 → Israel date = Jan 15
        utc_dt = datetime(2024, 1, 14, 23, 0)
        self.assertEqual(_candle_israel_date(utc_dt), date(2024, 1, 15))

    def test_summer_candle_date(self):
        # 21:00 UTC on Jul 14 = 00:00 IDT on Jul 15 → Israel date = Jul 15
        utc_dt = datetime(2024, 7, 14, 21, 0)
        self.assertEqual(_candle_israel_date(utc_dt), date(2024, 7, 15))

    def test_midnight_utc_winter(self):
        # 00:00 UTC Jan 15 = 02:00 IST Jan 15 → Israel date = Jan 15
        utc_dt = datetime(2024, 1, 15, 0, 0)
        self.assertEqual(_candle_israel_date(utc_dt), date(2024, 1, 15))


# ---------------------------------------------------------------------------
# 15. Config sanity
# ---------------------------------------------------------------------------

class TestConfig(unittest.TestCase):

    def test_sessions_defined(self):
        self.assertIn("asia",   SessionSweepConfig.SESSIONS)
        self.assertIn("london", SessionSweepConfig.SESSIONS)

    def test_backwards_compat_alias(self):
        self.assertIs(SessionBreakConfig, SessionSweepConfig)

    def test_session_times(self):
        self.assertEqual(SessionSweepConfig.SESSIONS["asia"]["start"],   time(3, 0))
        self.assertEqual(SessionSweepConfig.SESSIONS["asia"]["end"],     time(7, 0))
        self.assertEqual(SessionSweepConfig.SESSIONS["london"]["start"], time(9, 0))
        self.assertEqual(SessionSweepConfig.SESSIONS["london"]["end"],   time(12, 0))

    def test_session_high_low_from_wicks(self):
        """session_high/low use candle.high/low (wicks), not open/close."""
        ses = [
            c(ASIA_START_UTC,                          high=1.1200, low=1.0700, close=1.1000),
            c(ASIA_START_UTC + timedelta(minutes=5),   high=1.1100, low=1.0800, close=1.1050),
        ]
        r = compute_sweep_confirmation(ses, [])
        self.assertAlmostEqual(r["session_high"], 1.1200, places=4)
        self.assertAlmostEqual(r["session_low"],  1.0700, places=4)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
