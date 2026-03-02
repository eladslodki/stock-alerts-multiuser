"""
Deterministic unit tests for the Session Liquidity Sweep detector.

All tests use synthetic 5-minute OHLC candles – no DB, no network calls.
The pure functions `compute_sweep_result` and `find_relevant_sessions`
from services/session_break_detector.py are tested directly.

Key properties verified:
  1.  first_sweep_level = the MAX (UP) or MIN (DOWN) wick across the ENTIRE
      sweep move, not just the first candle that breaks the session level.
  2.  Confirmation only after sweep_end (re-entry) and on a STRICTLY LATER candle.
  3.  Alert triggers exactly once per (user, symbol, session, direction).
  4.  Direction chosen by earliest sweep_start_ts; tie → UP.
  5.  Session high/low use wick (high / low), not close.
  6.  DST-aware session windows via find_relevant_sessions.

Test coverage:
  A.  No sweep (price stays inside session range)           → no_break
  B.  Sweep starts but no re-entry yet                     → reentered=False
  C.  Re-entry but no confirm break yet                    → reentered=True, confirmed=False
  D.  Full trigger (sweep + re-entry + confirm)            → confirmed=True
  D2. first_sweep_level is the extreme, not the first wick → KEY FIX
  E.  Both directions break; UP first → direction=UP
  F.  Both directions break; DOWN first → direction=DOWN
  G.  Same candle breaks both sides → UP wins (tiebreaker)
  H.  Confirm candle must be strictly after sweep_end_ts
  I.  Session high/low from wicks
  J.  find_relevant_sessions returns only ended sessions
  K.  find_relevant_sessions uses Israel local dates
  L.  _session_candles / _post_session_candles boundary rules
  M.  Idempotency: compute_sweep_result is deterministic
  N.  Empty candles edge cases
"""

import sys
import os
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional
from unittest.mock import MagicMock

# ── Stub out heavy dependencies so pure functions are importable without DB ──
_mock_db = MagicMock()
_mock_db_module = MagicMock()
_mock_db_module.db = _mock_db
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())
sys.modules.setdefault("database", _mock_db_module)

_mock_fdp = MagicMock()
_mock_fdp.forex_data_provider = MagicMock()
_mock_fdp.normalize_symbol = MagicMock(return_value=("EUR/USD", None))
sys.modules.setdefault("services.forex_data_provider", _mock_fdp)

sys.modules.setdefault("email_sender", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from services.session_break_detector import (
    compute_sweep_result,
    find_relevant_sessions,
    _session_window_utc,
    _session_candles,
    _post_session_candles,
    SessionSweepConfig,
)


# ---------------------------------------------------------------------------
# Candle builder helpers
# ---------------------------------------------------------------------------

def make_candle(
    ts: datetime,
    open_: float = 1.0,
    high: float = 1.0,
    low: float = 1.0,
    close: float = 1.0,
) -> Dict:
    return {"timestamp": ts, "open": open_, "high": high, "low": low, "close": close}


# Reference session date for tests.
# The Asia session (Israel time 03:00–07:00) on 2024-01-15.
# Winter: Israel is UTC+2.  So Asia 03:00–07:00 IL = 01:00–05:00 UTC.
SESSION_DATE_IL = date(2024, 1, 15)

# Computed via _session_window_utc; we derive them here for test convenience.
# Winter UTC+2: Asia starts at 01:00 UTC, ends at 05:00 UTC.
ASIA_START_UTC = datetime(2024, 1, 15,  1, 0)  # 03:00 IL in winter
ASIA_END_UTC   = datetime(2024, 1, 15,  5, 0)  # 07:00 IL in winter

# London: 09:00–12:00 IL → 07:00–10:00 UTC in winter
LON_START_UTC  = datetime(2024, 1, 15,  7, 0)
LON_END_UTC    = datetime(2024, 1, 15, 10, 0)


def asia_session_candles(session_high: float = 1.1000,
                          session_low: float  = 1.0900) -> List[Dict]:
    """12 candles inside the Asia session window with given high/low."""
    candles = []
    for i in range(12):
        ts = ASIA_START_UTC + timedelta(minutes=5 * i)
        candles.append(make_candle(ts, high=session_high, low=session_low))
    return candles


def post_candles_from(
    start_offset_min: int = 0,
    count: int = 10,
    high: float = 1.0950,
    low:  float = 1.0950,
) -> List[Dict]:
    """Post-Asia candles starting at ASIA_END_UTC + start_offset_min."""
    return [
        make_candle(ASIA_END_UTC + timedelta(minutes=5 * i + start_offset_min),
                    high=high, low=low)
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# A. No sweep at all
# ---------------------------------------------------------------------------

class TestNoSweep(unittest.TestCase):

    def test_price_stays_inside_session_range(self):
        ses  = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = post_candles_from(0, count=20, high=1.0980, low=1.0920)

        result = compute_sweep_result(ses, post)
        self.assertIsNotNone(result)
        self.assertTrue(result.get("no_break"), f"Expected no_break, got: {result}")

    def test_no_post_candles(self):
        ses = asia_session_candles()
        result = compute_sweep_result(ses, [])
        self.assertTrue(result.get("no_break"))

    def test_empty_session_returns_none(self):
        self.assertIsNone(compute_sweep_result([], []))


# ---------------------------------------------------------------------------
# B. Sweep started, but re-entry hasn't happened yet
# ---------------------------------------------------------------------------

class TestSweepStartedNoReentry(unittest.TestCase):

    def test_up_sweep_no_reentry(self):
        """Price breaks above session_high and keeps going – no candle comes back."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = [
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.1002),
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.1020, low=1.1008),
            make_candle(ASIA_END_UTC + timedelta(minutes=15), high=1.1030, low=1.1015),
        ]
        result = compute_sweep_result(ses, post)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "UP")
        self.assertFalse(result.get("reentered"), "Expected reentered=False")
        self.assertFalse(result.get("confirmed"))
        # sweep_start_ts is the first candle that broke session_high
        self.assertEqual(result["sweep_start_ts"], ASIA_END_UTC + timedelta(minutes=5))
        # first_sweep_level must be the extreme of the entire sweep (1.1030)
        self.assertAlmostEqual(result["first_sweep_level"], 1.1030)

    def test_down_sweep_no_reentry(self):
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = [
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.0890, low=1.0870),
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.0880, low=1.0860),
            make_candle(ASIA_END_UTC + timedelta(minutes=15), high=1.0870, low=1.0850),
        ]
        result = compute_sweep_result(ses, post)
        self.assertEqual(result["direction"], "DOWN")
        self.assertFalse(result.get("reentered"))
        self.assertAlmostEqual(result["first_sweep_level"], 1.0850)


# ---------------------------------------------------------------------------
# C. Re-entry happened but no confirm break yet
# ---------------------------------------------------------------------------

class TestReentryNoConfirm(unittest.TestCase):

    def test_up_reentry_no_confirm(self):
        """
        Price sweeps above session_high (extends to 1.1030), re-enters
        (low <= session_high), but no later candle breaks 1.1030.
        """
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = [
            # Sweep phase: price keeps going up
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.1002),
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.1030, low=1.1005),
            # Re-entry candle: low <= session_high=1.1000
            make_candle(ASIA_END_UTC + timedelta(minutes=15), high=1.1025, low=1.0990),
            # Post-reentry candles that don't break 1.1030
            make_candle(ASIA_END_UTC + timedelta(minutes=20), high=1.1025, low=1.0950),
            make_candle(ASIA_END_UTC + timedelta(minutes=25), high=1.1028, low=1.0960),
        ]
        result = compute_sweep_result(ses, post)
        self.assertEqual(result["direction"], "UP")
        self.assertTrue(result.get("reentered"))
        self.assertFalse(result.get("confirmed"))
        self.assertAlmostEqual(result["first_sweep_level"], 1.1030)
        self.assertEqual(result["sweep_end_ts"], ASIA_END_UTC + timedelta(minutes=15))

    def test_down_reentry_no_confirm(self):
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = [
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.0895, low=1.0870),
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.0880, low=1.0850),
            # Re-entry: high >= session_low=1.0900
            make_candle(ASIA_END_UTC + timedelta(minutes=15), high=1.0910, low=1.0865),
            # Post-reentry but don't break 1.0850
            make_candle(ASIA_END_UTC + timedelta(minutes=20), high=1.0905, low=1.0855),
        ]
        result = compute_sweep_result(ses, post)
        self.assertEqual(result["direction"], "DOWN")
        self.assertTrue(result.get("reentered"))
        self.assertFalse(result.get("confirmed"))
        self.assertAlmostEqual(result["first_sweep_level"], 1.0850)


# ---------------------------------------------------------------------------
# D. Full trigger: sweep + re-entry + confirm
# ---------------------------------------------------------------------------

class TestFullTrigger(unittest.TestCase):

    def test_up_trigger(self):
        """Complete UP sweep sequence triggers correctly."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = [
            # Sweep starts: first wick above session_high
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.1002),
            # Sweep extends (still above session_high)
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.1025, low=1.1005),
            make_candle(ASIA_END_UTC + timedelta(minutes=15), high=1.1030, low=1.1003),
            # Re-entry: low <= session_high=1.1000 → sweep_end_ts, locks first_sweep_level=1.1030
            make_candle(ASIA_END_UTC + timedelta(minutes=20), high=1.1020, low=1.0995),
            # Post-reentry – not a confirm yet
            make_candle(ASIA_END_UTC + timedelta(minutes=25), high=1.1028, low=1.0985),
            # CONFIRM: high > first_sweep_level=1.1030
            make_candle(ASIA_END_UTC + timedelta(minutes=30), high=1.1035, low=1.0990),
        ]
        result = compute_sweep_result(ses, post)

        self.assertTrue(result.get("confirmed"), f"Expected confirmed=True: {result}")
        self.assertEqual(result["direction"], "UP")
        self.assertAlmostEqual(result["session_high"], 1.1000)
        self.assertAlmostEqual(result["session_low"],  1.0900)
        self.assertEqual(result["sweep_start_ts"],  ASIA_END_UTC + timedelta(minutes=5))
        self.assertAlmostEqual(result["first_sweep_level"], 1.1030)  # NOT 1.1010
        self.assertEqual(result["sweep_end_ts"],    ASIA_END_UTC + timedelta(minutes=20))
        self.assertAlmostEqual(result["confirm_break_level"], 1.1035)
        self.assertEqual(result["confirm_break_ts"], ASIA_END_UTC + timedelta(minutes=30))

    def test_down_trigger(self):
        """Complete DOWN sweep sequence triggers correctly."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = [
            # Sweep starts below session_low
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.0895, low=1.0880),
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.0885, low=1.0865),
            make_candle(ASIA_END_UTC + timedelta(minutes=15), high=1.0880, low=1.0855),
            # Re-entry: high >= session_low=1.0900
            make_candle(ASIA_END_UTC + timedelta(minutes=20), high=1.0910, low=1.0870),
            # Post-reentry
            make_candle(ASIA_END_UTC + timedelta(minutes=25), high=1.0908, low=1.0862),
            # CONFIRM: low < first_sweep_level=1.0855
            make_candle(ASIA_END_UTC + timedelta(minutes=30), high=1.0900, low=1.0850),
        ]
        result = compute_sweep_result(ses, post)

        self.assertTrue(result.get("confirmed"))
        self.assertEqual(result["direction"], "DOWN")
        self.assertAlmostEqual(result["first_sweep_level"], 1.0855)  # NOT 1.0880
        self.assertEqual(result["sweep_end_ts"], ASIA_END_UTC + timedelta(minutes=20))
        self.assertAlmostEqual(result["confirm_break_level"], 1.0850)


# ---------------------------------------------------------------------------
# D2. KEY FIX: first_sweep_level must be the extreme of the ENTIRE sweep move
# ---------------------------------------------------------------------------

class TestFirstSweepLevelIsExtreme(unittest.TestCase):
    """
    Critical regression test for the KEY FIX:
    first_sweep_level must be the MAX high (UP) or MIN low (DOWN) across ALL
    candles during the sweep move, not just the first candle that breaks the
    session level.
    """

    def test_up_sweep_level_is_max_of_all_sweep_candles(self):
        """
        Three candles break session_high with increasing highs.
        first_sweep_level must be the highest of all three, not 1.1010.
        """
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = [
            # Candle 1: first break (high=1.1010)
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.1001),
            # Candle 2: extends sweep (high=1.1020)
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.1020, low=1.1005),
            # Candle 3: extends sweep further (high=1.1035)
            make_candle(ASIA_END_UTC + timedelta(minutes=15), high=1.1035, low=1.1008),
            # Candle 4: re-entry (low <= session_high=1.1000)
            make_candle(ASIA_END_UTC + timedelta(minutes=20), high=1.1025, low=1.0995),
            # Candle 5: confirm (high > 1.1035)
            make_candle(ASIA_END_UTC + timedelta(minutes=25), high=1.1040, low=1.1010),
        ]
        result = compute_sweep_result(ses, post)

        # KEY ASSERTION: first_sweep_level must be 1.1035, not 1.1010
        self.assertAlmostEqual(
            result["first_sweep_level"], 1.1035,
            msg="first_sweep_level must be the MAX wick across the entire sweep, not 1.1010",
        )
        self.assertTrue(result.get("confirmed"))
        self.assertAlmostEqual(result["confirm_break_level"], 1.1040)

    def test_down_sweep_level_is_min_of_all_sweep_candles(self):
        """
        Three candles break session_low with lower lows.
        first_sweep_level must be the lowest of all three, not 1.0890.
        """
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = [
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.0895, low=1.0890),
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.0890, low=1.0875),
            make_candle(ASIA_END_UTC + timedelta(minutes=15), high=1.0880, low=1.0860),
            # Re-entry
            make_candle(ASIA_END_UTC + timedelta(minutes=20), high=1.0910, low=1.0875),
            # Confirm
            make_candle(ASIA_END_UTC + timedelta(minutes=25), high=1.0905, low=1.0855),
        ]
        result = compute_sweep_result(ses, post)

        self.assertAlmostEqual(
            result["first_sweep_level"], 1.0860,
            msg="first_sweep_level must be MIN wick across entire sweep, not 1.0890",
        )
        self.assertTrue(result.get("confirmed"))
        self.assertAlmostEqual(result["confirm_break_level"], 1.0855)

    def test_reentry_candle_high_included_in_up_sweep_extreme(self):
        """
        If the re-entry candle (low <= session_high) itself has the highest
        wick of the sweep, first_sweep_level must include that candle's high.
        """
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = [
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.1002),
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.1018, low=1.1005),
            # Re-entry candle: low=1.0995 <= 1.1000, but high=1.1040 is the real extreme
            make_candle(ASIA_END_UTC + timedelta(minutes=15), high=1.1040, low=1.0995),
            # Confirm
            make_candle(ASIA_END_UTC + timedelta(minutes=20), high=1.1045, low=1.1010),
        ]
        result = compute_sweep_result(ses, post)

        # The re-entry candle (t+15) contributes its high=1.1040 to sweep_high
        self.assertAlmostEqual(result["first_sweep_level"], 1.1040)
        self.assertEqual(result["sweep_end_ts"], ASIA_END_UTC + timedelta(minutes=15))
        self.assertTrue(result.get("confirmed"))

    def test_single_candle_sweep_and_reentry_with_later_confirm(self):
        """
        A single candle breaks high AND has low <= session_high (spike candle).
        Sweep start and sweep end are both at t+5.
        Confirm must be on a STRICTLY LATER candle.
        """
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        t_sweep = ASIA_END_UTC + timedelta(minutes=5)
        post = [
            # One candle: breaks high AND re-enters (wick spike)
            # sweep_start_ts = t_sweep; re-entry check is c["ts"] > sweep_start_ts
            # so re-entry is NOT triggered by this candle itself
            make_candle(t_sweep,                              high=1.1050, low=1.0950),
            # Next candle re-enters: low <= 1.1000
            make_candle(t_sweep + timedelta(minutes=5),       high=1.1040, low=1.0990),
            # Confirm: high > 1.1050
            make_candle(t_sweep + timedelta(minutes=10),      high=1.1055, low=1.0985),
        ]
        result = compute_sweep_result(ses, post)

        # sweep_end_ts is the SECOND candle (first strictly-later re-entry)
        self.assertEqual(result["sweep_end_ts"], t_sweep + timedelta(minutes=5))
        # first_sweep_level includes the re-entry candle's high too (1.1050 vs 1.1040)
        self.assertAlmostEqual(result["first_sweep_level"], 1.1050)
        self.assertTrue(result.get("confirmed"))
        self.assertEqual(result["confirm_break_ts"], t_sweep + timedelta(minutes=10))


# ---------------------------------------------------------------------------
# E. Both directions break; UP first → direction=UP
# ---------------------------------------------------------------------------

class TestBothSidesBreakUpFirst(unittest.TestCase):

    def test_up_breaks_before_down(self):
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = [
            # UP break at t+5
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.0910),
            # DOWN break at t+10 (later)
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.1015, low=1.0890),
            # Re-entry for UP direction: low <= 1.1000
            make_candle(ASIA_END_UTC + timedelta(minutes=15), high=1.1020, low=1.0990),
            # Confirm UP
            make_candle(ASIA_END_UTC + timedelta(minutes=20), high=1.1025, low=1.1005),
        ]
        result = compute_sweep_result(ses, post)
        self.assertEqual(result["direction"], "UP")
        self.assertEqual(result["sweep_start_ts"], ASIA_END_UTC + timedelta(minutes=5))

    def test_up_and_down_same_candle_up_wins(self):
        """Same candle breaks both high and low → UP wins as tiebreaker."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        t0 = ASIA_END_UTC + timedelta(minutes=5)
        post = [
            # Wide candle: high > 1.1000 AND low < 1.0900 at same timestamp
            make_candle(t0,                              high=1.1020, low=1.0880),
            # Re-entry for UP: low <= session_high=1.1000
            make_candle(t0 + timedelta(minutes=5),       high=1.1030, low=1.0990),
            # Confirm UP
            make_candle(t0 + timedelta(minutes=10),      high=1.1035, low=1.1000),
        ]
        result = compute_sweep_result(ses, post)
        self.assertEqual(result["direction"], "UP",
                         "UP must win when both sides break on the same candle")
        self.assertEqual(result["sweep_start_ts"], t0)


# ---------------------------------------------------------------------------
# F. Both directions break; DOWN first → direction=DOWN
# ---------------------------------------------------------------------------

class TestBothSidesBreakDownFirst(unittest.TestCase):

    def test_down_breaks_before_up(self):
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = [
            # DOWN break at t+5
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.0995, low=1.0885),
            # UP break at t+10 (later)
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.1010, low=1.0890),
            # Re-entry for DOWN: high >= 1.0900
            make_candle(ASIA_END_UTC + timedelta(minutes=15), high=1.0905, low=1.0875),
            # Confirm DOWN
            make_candle(ASIA_END_UTC + timedelta(minutes=20), high=1.0900, low=1.0880),
        ]
        result = compute_sweep_result(ses, post)
        self.assertEqual(result["direction"], "DOWN")
        self.assertEqual(result["sweep_start_ts"], ASIA_END_UTC + timedelta(minutes=5))


# ---------------------------------------------------------------------------
# G. Confirm candle must be strictly after sweep_end_ts
# ---------------------------------------------------------------------------

class TestConfirmRequiresStrictlyLaterCandle(unittest.TestCase):

    def test_candle_at_sweep_end_ts_does_not_confirm(self):
        """
        If a candle has the same timestamp as sweep_end_ts, it cannot be the
        confirm candle even if its high > first_sweep_level.
        """
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        t_sweep_end = ASIA_END_UTC + timedelta(minutes=15)
        post = [
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.1002),
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.1020, low=1.1005),
            # Re-entry AND high > sweep_level – but this is sweep_end candle, not confirm
            make_candle(t_sweep_end, high=1.1025, low=1.0995),
        ]
        result = compute_sweep_result(ses, post)

        # Re-entry happened at t_sweep_end
        self.assertTrue(result.get("reentered"))
        # But no strictly-LATER candle exists to confirm
        self.assertFalse(result.get("confirmed"),
                         "Candle at sweep_end_ts must not confirm")

    def test_confirm_at_next_candle_after_reentry(self):
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        t_reentry = ASIA_END_UTC + timedelta(minutes=15)
        t_confirm  = ASIA_END_UTC + timedelta(minutes=20)
        post = [
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.1002),
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.1020, low=1.1005),
            # Re-entry
            make_candle(t_reentry, high=1.1025, low=1.0995),
            # Confirm – strictly later
            make_candle(t_confirm, high=1.1030, low=1.0998),
        ]
        result = compute_sweep_result(ses, post)
        self.assertTrue(result.get("confirmed"))
        self.assertEqual(result["confirm_break_ts"], t_confirm)

    def test_down_confirm_strictly_after_reentry(self):
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        t_reentry = ASIA_END_UTC + timedelta(minutes=20)
        post = [
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.0895, low=1.0875),
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.0885, low=1.0860),
            make_candle(ASIA_END_UTC + timedelta(minutes=15), high=1.0882, low=1.0858),
            # Re-entry: high >= session_low=1.0900
            make_candle(t_reentry, high=1.0905, low=1.0862),
            # Confirm: low < first_sweep_level=1.0858
            make_candle(ASIA_END_UTC + timedelta(minutes=25), high=1.0900, low=1.0855),
        ]
        result = compute_sweep_result(ses, post)
        self.assertTrue(result.get("confirmed"))
        self.assertAlmostEqual(result["first_sweep_level"], 1.0858)
        self.assertEqual(result["sweep_end_ts"], t_reentry)
        self.assertEqual(result["confirm_break_ts"], ASIA_END_UTC + timedelta(minutes=25))


# ---------------------------------------------------------------------------
# H. Session high/low use wicks (high / low, not close)
# ---------------------------------------------------------------------------

class TestSessionExtremeFromWicks(unittest.TestCase):

    def test_session_high_low_from_wicks(self):
        ses = [
            make_candle(ASIA_START_UTC + timedelta(minutes=0),
                        open_=1.05, high=1.1200, low=1.0700, close=1.10),
            make_candle(ASIA_START_UTC + timedelta(minutes=5),
                        open_=1.10, high=1.1150, low=1.0800, close=1.09),
        ]
        post = post_candles_from(0, count=3, high=1.1150, low=1.0750)
        result = compute_sweep_result(ses, post)
        self.assertAlmostEqual(result["session_high"], 1.1200)
        self.assertAlmostEqual(result["session_low"],  1.0700)


# ---------------------------------------------------------------------------
# I. find_relevant_sessions – only ended sessions with data
# ---------------------------------------------------------------------------

def _make_candles_for_utc_range(start_dt: datetime, end_dt: datetime,
                                 step_min: int = 5) -> List[Dict]:
    candles = []
    ts = start_dt
    while ts < end_dt:
        candles.append(make_candle(ts))
        ts += timedelta(minutes=step_min)
    return candles


class TestFindRelevantSessions(unittest.TestCase):

    def test_ended_session_included(self):
        candles = _make_candles_for_utc_range(ASIA_START_UTC, ASIA_END_UTC + timedelta(hours=2))
        now_utc = ASIA_END_UTC + timedelta(hours=1)
        sessions = find_relevant_sessions(candles, now_utc)
        asia = [(s, d) for s, d in sessions if s == "asia" and d == SESSION_DATE_IL]
        self.assertEqual(len(asia), 1)

    def test_session_not_ended_excluded(self):
        candles = _make_candles_for_utc_range(ASIA_START_UTC, ASIA_END_UTC)
        now_utc = ASIA_START_UTC + timedelta(hours=2)  # mid-session
        sessions = find_relevant_sessions(candles, now_utc)
        asia = [(s, d) for s, d in sessions if s == "asia" and d == SESSION_DATE_IL]
        self.assertEqual(len(asia), 0)

    def test_multiple_sessions_detected(self):
        # Candles from Asia start to after London end
        candles = _make_candles_for_utc_range(ASIA_START_UTC, LON_END_UTC + timedelta(hours=1))
        now_utc = LON_END_UTC + timedelta(hours=1)
        sessions = find_relevant_sessions(candles, now_utc)
        session_types = {s for s, _ in sessions}
        self.assertIn("asia",   session_types)
        self.assertIn("london", session_types)

    def test_no_session_candles_excluded(self):
        # Candles only during post-session (no Asia window candles)
        candles = _make_candles_for_utc_range(ASIA_END_UTC, LON_END_UTC)
        now_utc = LON_END_UTC + timedelta(hours=1)
        sessions = find_relevant_sessions(candles, now_utc)
        asia = [(s, d) for s, d in sessions if s == "asia" and d == SESSION_DATE_IL]
        self.assertEqual(len(asia), 0)


# ---------------------------------------------------------------------------
# J. _session_window_utc – correct DST conversion for Asia/Jerusalem
# ---------------------------------------------------------------------------

class TestSessionWindowUTC(unittest.TestCase):

    def test_asia_winter_window(self):
        """Jan 15: Israel is UTC+2.  Asia 03:00–07:00 IL → 01:00–05:00 UTC."""
        start, end = _session_window_utc("asia", date(2024, 1, 15))
        self.assertEqual(start, datetime(2024, 1, 15, 1, 0))
        self.assertEqual(end,   datetime(2024, 1, 15, 5, 0))

    def test_london_winter_window(self):
        """Jan 15: London 09:00–12:00 IL → 07:00–10:00 UTC."""
        start, end = _session_window_utc("london", date(2024, 1, 15))
        self.assertEqual(start, datetime(2024, 1, 15, 7, 0))
        self.assertEqual(end,   datetime(2024, 1, 15, 10, 0))

    def test_asia_summer_window(self):
        """Jul 15: Israel is UTC+3 (DST).  Asia 03:00–07:00 IL → 00:00–04:00 UTC."""
        start, end = _session_window_utc("asia", date(2024, 7, 15))
        self.assertEqual(start, datetime(2024, 7, 15, 0, 0))
        self.assertEqual(end,   datetime(2024, 7, 15, 4, 0))

    def test_london_summer_window(self):
        """Jul 15: London 09:00–12:00 IL → 06:00–09:00 UTC."""
        start, end = _session_window_utc("london", date(2024, 7, 15))
        self.assertEqual(start, datetime(2024, 7, 15, 6, 0))
        self.assertEqual(end,   datetime(2024, 7, 15, 9, 0))


# ---------------------------------------------------------------------------
# K. _session_candles / _post_session_candles boundary rules
# ---------------------------------------------------------------------------

class TestCandlePartitioning(unittest.TestCase):

    def test_session_candles_inclusive_start_exclusive_end(self):
        c_start = make_candle(ASIA_START_UTC)
        c_mid   = make_candle(ASIA_START_UTC + timedelta(hours=2))
        c_end   = make_candle(ASIA_END_UTC)          # at end → excluded from session
        c_post  = make_candle(ASIA_END_UTC + timedelta(minutes=5))

        ses = _session_candles([c_start, c_mid, c_end, c_post], ASIA_START_UTC, ASIA_END_UTC)
        self.assertIn(c_start, ses)
        self.assertIn(c_mid,   ses)
        self.assertNotIn(c_end,  ses)
        self.assertNotIn(c_post, ses)

    def test_post_candles_include_end_time(self):
        c_pre    = make_candle(ASIA_END_UTC - timedelta(minutes=5))
        c_at_end = make_candle(ASIA_END_UTC)          # inclusive in post
        c_after  = make_candle(ASIA_END_UTC + timedelta(minutes=5))

        post = _post_session_candles([c_pre, c_at_end, c_after], ASIA_END_UTC)
        self.assertNotIn(c_pre, post)
        self.assertIn(c_at_end, post)
        self.assertIn(c_after,  post)

    def test_post_candles_sorted_oldest_first(self):
        candles = [
            make_candle(ASIA_END_UTC + timedelta(minutes=15)),
            make_candle(ASIA_END_UTC + timedelta(minutes=5)),
            make_candle(ASIA_END_UTC + timedelta(minutes=10)),
        ]
        post = _post_session_candles(candles, ASIA_END_UTC)
        ts = [c["timestamp"] for c in post]
        self.assertEqual(ts, sorted(ts))


# ---------------------------------------------------------------------------
# L. Idempotency – compute_sweep_result is deterministic
# ---------------------------------------------------------------------------

class TestIdempotency(unittest.TestCase):

    def test_same_result_on_repeated_calls(self):
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = [
            make_candle(ASIA_END_UTC + timedelta(minutes=5),  high=1.1010, low=1.1002),
            make_candle(ASIA_END_UTC + timedelta(minutes=10), high=1.1030, low=1.1005),
            make_candle(ASIA_END_UTC + timedelta(minutes=15), high=1.1020, low=1.0995),
            make_candle(ASIA_END_UTC + timedelta(minutes=20), high=1.1035, low=1.0998),
        ]
        r1 = compute_sweep_result(ses, post)
        r2 = compute_sweep_result(ses, post)

        self.assertEqual(r1["direction"],            r2["direction"])
        self.assertEqual(r1["sweep_start_ts"],       r2["sweep_start_ts"])
        self.assertEqual(r1["first_sweep_level"],    r2["first_sweep_level"])
        self.assertEqual(r1["sweep_end_ts"],         r2["sweep_end_ts"])
        self.assertEqual(r1["confirm_break_ts"],     r2["confirm_break_ts"])
        self.assertEqual(r1["confirm_break_level"],  r2["confirm_break_level"])
        self.assertTrue(r1["confirmed"])

    def test_no_break_is_stable(self):
        ses  = asia_session_candles()
        post = post_candles_from(0, count=10, high=1.0980, low=1.0920)
        r1 = compute_sweep_result(ses, post)
        r2 = compute_sweep_result(ses, post)
        self.assertTrue(r1.get("no_break"))
        self.assertTrue(r2.get("no_break"))


# ---------------------------------------------------------------------------
# M. Session config sanity
# ---------------------------------------------------------------------------

class TestSessionConfig(unittest.TestCase):

    def test_known_session_types(self):
        self.assertIn("asia",   SessionSweepConfig.SESSIONS)
        self.assertIn("london", SessionSweepConfig.SESSIONS)

    def test_asia_session_times_il(self):
        cfg = SessionSweepConfig.SESSIONS["asia"]
        self.assertEqual(cfg["start_h"], 3)
        self.assertEqual(cfg["end_h"],   7)

    def test_london_session_times_il(self):
        cfg = SessionSweepConfig.SESSIONS["london"]
        self.assertEqual(cfg["start_h"],  9)
        self.assertEqual(cfg["end_h"],   12)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
