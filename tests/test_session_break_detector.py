"""
Deterministic unit tests for the Session Break Confirmation detector.

All tests use synthetic 5M OHLC candles – no DB, no network calls.
The pure functions `compute_session_result` and `find_relevant_sessions`
from services/session_break_detector.py are tested directly.

Test cases required by spec:
  1.  no break                  -> no trigger
  2.  first break only          -> no trigger (returns confirmed=False)
  3.  confirm break             -> trigger once  (confirmed=True)
  4a. both sides break          -> choose first by time, lock direction
  4b. both at same candle       -> UP wins (tiebreaker)
  5.  idempotency               -> no double trigger on re-runs
  6.  session_high / session_low computed correctly from wicks
  7.  find_relevant_sessions    -> only returns ended sessions
  8.  post-session candles      -> only candles AFTER session end
  9.  confirm candle must be    -> strictly AFTER first_break_ts
  10. edge: empty candles       -> returns None
"""

import sys
import os
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional
from unittest.mock import MagicMock

# ── Stub out heavy dependencies so pure functions are importable without DB ──
# Must happen BEFORE importing the module under test.
_mock_db = MagicMock()
_mock_db_module = MagicMock()
_mock_db_module.db = _mock_db
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())
sys.modules.setdefault("database", _mock_db_module)

# forex_data_provider uses requests – stub it too
_mock_fdp = MagicMock()
_mock_fdp.forex_data_provider = MagicMock()
_mock_fdp.normalize_symbol = MagicMock(return_value=("EUR/USD", None))
sys.modules.setdefault("services.forex_data_provider", _mock_fdp)

# email_sender
sys.modules.setdefault("email_sender", MagicMock())

# Make sure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from services.session_break_detector import (
    compute_session_result,
    find_relevant_sessions,
    _session_window,
    _session_candles,
    _post_session_candles,
    SessionBreakConfig,
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


# A reference session date for tests
SESSION_DATE = date(2024, 1, 15)

# Asia session for SESSION_DATE: 00:00–09:00 UTC
ASIA_START = datetime(2024, 1, 15, 0, 0)
ASIA_END   = datetime(2024, 1, 15, 9, 0)

# London session for SESSION_DATE: 08:00–17:00 UTC
LON_START = datetime(2024, 1, 15, 8, 0)
LON_END   = datetime(2024, 1, 15, 17, 0)


def asia_session_candles(session_high=1.1000, session_low=1.0900) -> List[Dict]:
    """A simple Asia session: 12 candles, high=session_high, low=session_low."""
    candles = []
    for i in range(12):
        ts = ASIA_START + timedelta(minutes=5 * i)
        candles.append(make_candle(ts, high=session_high, low=session_low))
    return candles


def post_session_candles_from(start_offset_min: int, count: int = 10,
                               high: float = 1.0950, low: float = 1.0950) -> List[Dict]:
    """Post-session candles starting at ASIA_END + start_offset_min."""
    candles = []
    for i in range(count):
        ts = ASIA_END + timedelta(minutes=5 * i + start_offset_min)
        candles.append(make_candle(ts, high=high, low=low))
    return candles


# ---------------------------------------------------------------------------
# 1. No break at all
# ---------------------------------------------------------------------------

class TestNoBreak(unittest.TestCase):

    def test_no_break_returns_no_break_flag(self):
        """Post-session candles that never breach session_high or session_low."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        # Post candles stay inside the session range
        post = post_session_candles_from(0, count=20, high=1.0980, low=1.0920)

        result = compute_session_result(ses, post)
        self.assertIsNotNone(result)
        self.assertTrue(result.get("no_break"), f"Expected no_break flag, got: {result}")

    def test_no_post_candles_returns_no_break(self):
        """Session just ended, no post-session data yet."""
        ses = asia_session_candles()
        result = compute_session_result(ses, [])
        self.assertIsNotNone(result)
        self.assertTrue(result.get("no_break"))

    def test_empty_session_returns_none(self):
        """No session candles at all."""
        result = compute_session_result([], [])
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 2. First break only – no confirmation
# ---------------------------------------------------------------------------

class TestFirstBreakOnly(unittest.TestCase):

    def test_up_first_break_not_confirmed(self):
        """One wick above session_high, no later candle surpasses it."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)

        # Post: first candle breaks high (wick to 1.1010), no later candle exceeds 1.1010
        post = [
            make_candle(ASIA_END + timedelta(minutes=5),  high=1.1010, low=1.0950),  # first break
            make_candle(ASIA_END + timedelta(minutes=10), high=1.1005, low=1.0940),  # below 1.1010
            make_candle(ASIA_END + timedelta(minutes=15), high=1.1008, low=1.0945),  # below 1.1010
        ]

        result = compute_session_result(ses, post)
        self.assertIsNotNone(result)
        self.assertFalse(result.get("confirmed", True), f"Should not be confirmed: {result}")
        self.assertEqual(result["direction"], "UP")
        self.assertAlmostEqual(result["first_break_level"], 1.1010)

    def test_down_first_break_not_confirmed(self):
        """One wick below session_low, no later candle goes lower."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)

        post = [
            make_candle(ASIA_END + timedelta(minutes=5),  high=1.0950, low=1.0890),  # first break
            make_candle(ASIA_END + timedelta(minutes=10), high=1.0960, low=1.0895),  # not below 1.0890
            make_candle(ASIA_END + timedelta(minutes=15), high=1.0970, low=1.0900),  # not below 1.0890
        ]

        result = compute_session_result(ses, post)
        self.assertIsNotNone(result)
        self.assertFalse(result.get("confirmed", True))
        self.assertEqual(result["direction"], "DOWN")
        self.assertAlmostEqual(result["first_break_level"], 1.0890)


# ---------------------------------------------------------------------------
# 3. Full confirm break -> trigger
# ---------------------------------------------------------------------------

class TestConfirmBreak(unittest.TestCase):

    def test_up_confirm_triggers(self):
        """First break UP, then a later candle surpasses it -> confirmed=True."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)

        post = [
            make_candle(ASIA_END + timedelta(minutes=5),  high=1.1010, low=1.0950),  # first break UP
            make_candle(ASIA_END + timedelta(minutes=10), high=1.1005, low=1.0940),  # below 1.1010
            make_candle(ASIA_END + timedelta(minutes=15), high=1.1015, low=1.0945),  # CONFIRM (>1.1010)
        ]

        result = compute_session_result(ses, post)
        self.assertIsNotNone(result)
        self.assertTrue(result.get("confirmed"), f"Expected confirmed=True: {result}")
        self.assertEqual(result["direction"], "UP")
        self.assertAlmostEqual(result["session_high"], 1.1000)
        self.assertAlmostEqual(result["first_break_level"], 1.1010)
        self.assertAlmostEqual(result["confirm_break_level"], 1.1015)
        self.assertEqual(result["confirm_break_ts"], ASIA_END + timedelta(minutes=15))

    def test_down_confirm_triggers(self):
        """First break DOWN, then a later candle goes lower -> confirmed=True."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)

        post = [
            make_candle(ASIA_END + timedelta(minutes=5),  high=1.0960, low=1.0890),  # first break DOWN
            make_candle(ASIA_END + timedelta(minutes=10), high=1.0970, low=1.0895),  # above 1.0890
            make_candle(ASIA_END + timedelta(minutes=15), high=1.0965, low=1.0885),  # CONFIRM (<1.0890)
        ]

        result = compute_session_result(ses, post)
        self.assertIsNotNone(result)
        self.assertTrue(result.get("confirmed"))
        self.assertEqual(result["direction"], "DOWN")
        self.assertAlmostEqual(result["first_break_level"], 1.0890)
        self.assertAlmostEqual(result["confirm_break_level"], 1.0885)

    def test_confirm_candle_must_be_strictly_after_first_break(self):
        """A candle at the SAME timestamp as first_break does not confirm."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)

        fb_ts = ASIA_END + timedelta(minutes=5)
        post = [
            make_candle(fb_ts, high=1.1050, low=1.0950),  # first break, also a "confirm" but same ts
        ]

        result = compute_session_result(ses, post)
        # The single candle that breaks also has the first_break_ts; no LATER candle exists
        self.assertIsNotNone(result)
        self.assertFalse(result.get("confirmed", True),
                         "Confirm must require a strictly later candle")

    def test_session_high_low_from_wicks(self):
        """session_high and session_low use candle.high and candle.low (wicks)."""
        # Session candles have higher highs and lower lows than their bodies
        ses = [
            make_candle(ASIA_START + timedelta(minutes=0),  open_=1.05, high=1.12, low=1.08, close=1.10),
            make_candle(ASIA_START + timedelta(minutes=5),  open_=1.10, high=1.11, low=1.07, close=1.09),
            make_candle(ASIA_START + timedelta(minutes=10), open_=1.09, high=1.10, low=1.09, close=1.10),
        ]
        post = post_session_candles_from(0, count=3, high=1.0950, low=1.0950)
        result = compute_session_result(ses, post)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["session_high"], 1.12, places=5)
        self.assertAlmostEqual(result["session_low"],  1.07, places=5)


# ---------------------------------------------------------------------------
# 4a. Both sides break – first chronologically wins
# ---------------------------------------------------------------------------

class TestBothSidesBreak(unittest.TestCase):

    def test_up_breaks_first(self):
        """UP break happens at minute 5, DOWN break at minute 10 -> direction=UP."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)

        post = [
            make_candle(ASIA_END + timedelta(minutes=5),  high=1.1010, low=1.0910),  # UP break first
            make_candle(ASIA_END + timedelta(minutes=10), high=1.1005, low=1.0885),  # DOWN break later
            make_candle(ASIA_END + timedelta(minutes=15), high=1.1015, low=1.0890),  # UP confirm
        ]

        result = compute_session_result(ses, post)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "UP")
        self.assertEqual(result["first_break_ts"], ASIA_END + timedelta(minutes=5))
        self.assertTrue(result.get("confirmed"))
        # Confirm is for UP direction (high > first_break_level=1.1010)
        self.assertAlmostEqual(result["confirm_break_level"], 1.1015)

    def test_down_breaks_first(self):
        """DOWN break happens at minute 5, UP break at minute 10 -> direction=DOWN."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)

        post = [
            make_candle(ASIA_END + timedelta(minutes=5),  high=1.0990, low=1.0885),  # DOWN break first
            make_candle(ASIA_END + timedelta(minutes=10), high=1.1010, low=1.0890),  # UP break later
            make_candle(ASIA_END + timedelta(minutes=15), high=1.0980, low=1.0880),  # DOWN confirm
        ]

        result = compute_session_result(ses, post)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "DOWN")
        self.assertEqual(result["first_break_ts"], ASIA_END + timedelta(minutes=5))
        self.assertTrue(result.get("confirmed"))
        self.assertAlmostEqual(result["confirm_break_level"], 1.0880)


# ---------------------------------------------------------------------------
# 4b. Both break at the SAME candle -> UP wins (tiebreaker)
# ---------------------------------------------------------------------------

class TestBothBreakSameCandle(unittest.TestCase):

    def test_up_wins_when_same_candle(self):
        """Wide candle breaks both session_high and session_low simultaneously -> UP wins."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)

        fb_ts = ASIA_END + timedelta(minutes=5)
        post = [
            # Same candle: high > 1.1000 AND low < 1.0900
            make_candle(fb_ts, high=1.1020, low=1.0880),
            # Later candle confirms UP
            make_candle(ASIA_END + timedelta(minutes=10), high=1.1025, low=1.0890),
        ]

        result = compute_session_result(ses, post)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "UP",
                         "When both break same candle, UP should win as tiebreaker")
        self.assertEqual(result["first_break_ts"], fb_ts)
        self.assertTrue(result.get("confirmed"))

    def test_no_confirm_if_only_one_candle(self):
        """Wide candle breaks both sides but is the only candle -> not confirmed."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)

        post = [make_candle(ASIA_END + timedelta(minutes=5), high=1.1020, low=1.0880)]

        result = compute_session_result(ses, post)
        self.assertFalse(result.get("confirmed", True))


# ---------------------------------------------------------------------------
# 5. Idempotency – triggered flag prevents re-run from triggering again
# ---------------------------------------------------------------------------

class TestIdempotency(unittest.TestCase):
    """
    The idempotency guarantee in the detector comes from the DB layer
    (triggered_at is set before the email is sent, and is checked at the
    start of every run).  Here we verify that `compute_session_result` is
    pure and deterministic: running it twice with the same candles yields
    the same result.
    """

    def test_same_result_on_rerun(self):
        """compute_session_result is deterministic for fixed candles."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = [
            make_candle(ASIA_END + timedelta(minutes=5),  high=1.1010, low=1.0950),
            make_candle(ASIA_END + timedelta(minutes=15), high=1.1015, low=1.0945),
        ]

        r1 = compute_session_result(ses, post)
        r2 = compute_session_result(ses, post)

        self.assertEqual(r1["direction"],          r2["direction"])
        self.assertEqual(r1["first_break_ts"],     r2["first_break_ts"])
        self.assertEqual(r1["confirm_break_ts"],   r2["confirm_break_ts"])
        self.assertEqual(r1["confirm_break_level"],r2["confirm_break_level"])
        self.assertTrue(r1["confirmed"])
        self.assertTrue(r2["confirmed"])

    def test_no_break_is_stable(self):
        """A no-break result is also stable across multiple runs."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        post = post_session_candles_from(0, count=10, high=1.0980, low=1.0920)

        r1 = compute_session_result(ses, post)
        r2 = compute_session_result(ses, post)

        self.assertTrue(r1.get("no_break"))
        self.assertTrue(r2.get("no_break"))


# ---------------------------------------------------------------------------
# 6. find_relevant_sessions
# ---------------------------------------------------------------------------

class TestFindRelevantSessions(unittest.TestCase):

    def _make_candles_for_date_range(self, start_dt: datetime, end_dt: datetime,
                                     step_min: int = 5) -> List[Dict]:
        candles = []
        ts = start_dt
        while ts < end_dt:
            candles.append(make_candle(ts))
            ts += timedelta(minutes=step_min)
        return candles

    def test_only_ended_sessions_returned(self):
        """Sessions that have NOT ended (session_end > now_utc) are excluded."""
        # Candles span SESSION_DATE 00:00–09:00 (Asia session day)
        candles = self._make_candles_for_date_range(ASIA_START, ASIA_END)
        # now_utc is BEFORE Asia session ends
        now_utc = ASIA_START + timedelta(hours=4)
        sessions = find_relevant_sessions(candles, now_utc)
        # Asia session for SESSION_DATE has not ended yet
        asia_sessions = [(s, d) for s, d in sessions if s == "asia" and d == SESSION_DATE]
        self.assertEqual(len(asia_sessions), 0)

    def test_ended_session_included(self):
        """A session that has ended is included."""
        # Candles cover the full Asia session + post-session
        candles = self._make_candles_for_date_range(ASIA_START, ASIA_END + timedelta(hours=2))
        now_utc = ASIA_END + timedelta(hours=1)
        sessions = find_relevant_sessions(candles, now_utc)
        asia_sessions = [(s, d) for s, d in sessions if s == "asia" and d == SESSION_DATE]
        self.assertEqual(len(asia_sessions), 1)

    def test_multiple_sessions_detected(self):
        """Both Asia and London sessions are detected when candles span both."""
        # Candles from 00:00 to 18:00 UTC on SESSION_DATE
        candles = self._make_candles_for_date_range(
            ASIA_START,
            datetime(2024, 1, 15, 18, 0),
        )
        now_utc = datetime(2024, 1, 15, 18, 0)
        sessions = find_relevant_sessions(candles, now_utc)
        session_types = {s for s, _ in sessions}
        self.assertIn("asia",   session_types)
        self.assertIn("london", session_types)

    def test_no_session_candles_excluded(self):
        """A session date where no session candles exist is excluded."""
        # Candles only during post-session hours (09:00–17:00), no Asia candles
        candles = self._make_candles_for_date_range(ASIA_END, LON_END)
        now_utc = LON_END + timedelta(hours=1)
        sessions = find_relevant_sessions(candles, now_utc)
        # Asia session has no candles in 00:00–09:00 -> not included
        asia_sessions = [(s, d) for s, d in sessions if s == "asia" and d == SESSION_DATE]
        self.assertEqual(len(asia_sessions), 0)


# ---------------------------------------------------------------------------
# 7. _session_candles / _post_session_candles helpers
# ---------------------------------------------------------------------------

class TestCandlePartitioning(unittest.TestCase):

    def test_session_candles_boundary_inclusive_start_exclusive_end(self):
        """[start, end) boundary: candle at start is IN, candle at end is OUT."""
        c_start = make_candle(ASIA_START)
        c_mid   = make_candle(ASIA_START + timedelta(hours=4))
        c_end   = make_candle(ASIA_END)        # This is at 09:00, excluded
        c_post  = make_candle(ASIA_END + timedelta(minutes=5))

        all_candles = [c_start, c_mid, c_end, c_post]
        ses = _session_candles(all_candles, ASIA_START, ASIA_END)

        self.assertIn(c_start, ses)
        self.assertIn(c_mid,   ses)
        self.assertNotIn(c_end,  ses,  "Candle at session end time should be excluded")
        self.assertNotIn(c_post, ses)

    def test_post_candles_start_from_session_end(self):
        """Post-session candles include the candle at session_end time."""
        c_in_session = make_candle(ASIA_END - timedelta(minutes=5))
        c_at_end     = make_candle(ASIA_END)   # inclusive in post-session
        c_after      = make_candle(ASIA_END + timedelta(minutes=5))

        all_candles = [c_in_session, c_at_end, c_after]
        post = _post_session_candles(all_candles, ASIA_END)

        self.assertNotIn(c_in_session, post)
        self.assertIn(c_at_end, post)
        self.assertIn(c_after,  post)

    def test_post_candles_sorted_oldest_first(self):
        """Post-session candles are always returned oldest→newest."""
        # Create in reverse order
        candles = [
            make_candle(ASIA_END + timedelta(minutes=15)),
            make_candle(ASIA_END + timedelta(minutes=5)),
            make_candle(ASIA_END + timedelta(minutes=10)),
        ]
        post = _post_session_candles(candles, ASIA_END)
        timestamps = [c["timestamp"] for c in post]
        self.assertEqual(timestamps, sorted(timestamps))


# ---------------------------------------------------------------------------
# 8. Edge: confirm break must be STRICTLY after first_break_ts
# ---------------------------------------------------------------------------

class TestConfirmMustBeStrictlyLater(unittest.TestCase):

    def test_candle_at_first_break_ts_does_not_confirm(self):
        """If a candle has the exact same ts as first_break, it is NOT the confirm."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)
        fb_ts = ASIA_END + timedelta(minutes=5)

        # Two candles with the same timestamp (pathological case)
        post = [
            make_candle(fb_ts, high=1.1050, low=1.0950),  # first break
            make_candle(fb_ts, high=1.1060, low=1.0940),  # same ts – should NOT confirm
        ]

        result = compute_session_result(ses, post)
        # First candle triggers first break; second has same ts so cannot confirm
        self.assertFalse(result.get("confirmed", True))

    def test_confirm_at_next_candle(self):
        """Confirm is detected at the very next candle after first break."""
        ses = asia_session_candles(session_high=1.1000, session_low=1.0900)

        t1 = ASIA_END + timedelta(minutes=5)
        t2 = ASIA_END + timedelta(minutes=10)

        post = [
            make_candle(t1, high=1.1010, low=1.0950),  # first break
            make_candle(t2, high=1.1020, low=1.0945),  # confirm
        ]

        result = compute_session_result(ses, post)
        self.assertTrue(result.get("confirmed"))
        self.assertEqual(result["confirm_break_ts"], t2)


# ---------------------------------------------------------------------------
# 9. Session window configuration sanity
# ---------------------------------------------------------------------------

class TestSessionConfig(unittest.TestCase):

    def test_asia_session_window(self):
        start, end = _session_window("asia", SESSION_DATE)
        self.assertEqual(start, datetime(2024, 1, 15, 0, 0))
        self.assertEqual(end,   datetime(2024, 1, 15, 9, 0))

    def test_london_session_window(self):
        start, end = _session_window("london", SESSION_DATE)
        self.assertEqual(start, datetime(2024, 1, 15, 8, 0))
        self.assertEqual(end,   datetime(2024, 1, 15, 17, 0))

    def test_known_session_types(self):
        self.assertIn("asia",   SessionBreakConfig.SESSIONS)
        self.assertIn("london", SessionBreakConfig.SESSIONS)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
