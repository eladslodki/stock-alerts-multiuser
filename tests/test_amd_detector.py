"""
Unit + integration tests for ForexAMDDetector (services/forex_amd_detector.py)

Tests are organised in two groups:

  1. Pure detection-function tests (no DB): accumulation, sweep,
     displacement, IFVG.  These only call detector methods with synthetic
     candle arrays.

  2. State-machine tests: patch `services.forex_amd_detector.db` so the
     whole state machine can run without a real database.  Each test
     covers one specific state transition or timeout/reset path.

Run with:
    cd /path/to/stock-alerts-multiuser
    python -m pytest tests/test_amd_detector.py -v
"""

import sys
import os

# ---------------------------------------------------------------------------
# Stub out database + psycopg2 BEFORE importing the detector, so the test
# module can be collected without a real PostgreSQL connection.
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock

_fake_psycopg2 = MagicMock()
_fake_psycopg2.connect.return_value = MagicMock()
sys.modules.setdefault("psycopg2", _fake_psycopg2)
sys.modules.setdefault("psycopg2.extras", MagicMock())

_fake_db_module = MagicMock()
sys.modules.setdefault("database", _fake_db_module)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call

from services.forex_amd_detector import ForexAMDDetector, AMDState, AMDConfig


# ===========================================================================
# ── Candle factory helpers ──────────────────────────────────────────────────
# ===========================================================================

BASE_TS = datetime(2024, 6, 10, 9, 0)   # 09:00 UTC → London session


def make_candle(offset_bars: int, o: float, h: float, l: float, c: float,
                base_ts: datetime = BASE_TS, bar_minutes: int = 15) -> dict:
    """Create a single OHLC candle dict."""
    return {
        "timestamp": base_ts + timedelta(minutes=bar_minutes * offset_bars),
        "open": o, "high": h, "low": l, "close": c,
        "volume": 1000.0,
    }


def background_candles(n: int = 20, base: float = 1.0800,
                        range_size: float = 0.0050) -> list:
    """
    Produce `n` moderately volatile background candles.

    ATR ≈ range_size = 0.0050 (50 pips) → sufficient volatility.
    Alternates slightly bullish / bearish to avoid directional bias.
    """
    candles = []
    for i in range(n):
        if i % 2 == 0:
            candles.append(make_candle(i, base, base + range_size,
                                       base, base + range_size * 0.4))
        else:
            candles.append(make_candle(i, base + range_size * 0.4,
                                       base + range_size,
                                       base, base + range_size * 0.1))
    return candles


def accumulation_candles(start_offset: int, accum_low: float = 1.0820,
                          accum_high: float = 1.0835, n: int = 8) -> list:
    """
    8 candles forming a tight consolidation range.

    Range  = accum_high - accum_low = 0.0015 (15 pips)
    ATR    ≈ 0.0050 (from background) → range / ATR = 0.30 ≤ 0.50 threshold ✓
    Boundary touches: 3 high touches + 3 low touches ✓
    Directional bias: minimal ✓
    """
    mid = (accum_high + accum_low) / 2
    pattern = [
        # (o,  h,          l,          c)       # notes
        (mid + 0.0003, accum_high,    accum_low + 0.0002, mid + 0.0003),  # touch high
        (mid + 0.0003, accum_high - 0.0002, accum_low,   mid - 0.0003),  # touch low
        (mid - 0.0002, accum_high,    accum_low + 0.0003, mid + 0.0005),  # touch high
        (mid + 0.0005, accum_high - 0.0002, accum_low,   mid - 0.0002),  # touch low
        (mid - 0.0001, accum_high - 0.0001, accum_low + 0.0001, mid + 0.0002),
        (mid + 0.0002, accum_high,    accum_low + 0.0002, mid - 0.0001),  # touch high
        (mid - 0.0001, accum_high - 0.0003, accum_low,   mid + 0.0001),  # touch low
        (mid + 0.0001, accum_high - 0.0002, accum_low + 0.0002, mid),
    ]
    return [
        make_candle(start_offset + i, o, h, lo, c)
        for i, (o, h, lo, c) in enumerate(pattern[:n])
    ]


def bullish_sweep_candle(offset: int, accum_low: float = 1.0820,
                          below_by: float = 0.0010) -> dict:
    """
    Sweep candle that dips `below_by` under accum_low with a long lower wick
    and closes back above accum_low.

    wick_pct = (close - low) / (high - low) = 0.0015 / 0.0020 = 75% > 40% ✓
    sweep_distance = 10 pips > 5 pip minimum ✓
    close back above accum_low ✓
    """
    low  = accum_low - below_by
    high = accum_low + 0.0010
    o    = accum_low + 0.0006
    c    = accum_low + 0.0005   # close above accum_low
    return make_candle(offset, o, high, low, c)


def bearish_sweep_candle(offset: int, accum_high: float = 1.0835,
                          above_by: float = 0.0010) -> dict:
    """
    Bearish sweep: spikes above accum_high, closes back below.

    wick_pct = (high - close) / (high - low) = 0.0015/0.0020 = 75% ✓
    """
    high = accum_high + above_by
    low  = accum_high - 0.0010
    o    = accum_high - 0.0005
    c    = accum_high - 0.0005   # close below accum_high
    return make_candle(offset, o, high, low, c)


def bullish_displacement_candle(offset: int, close_from: float = 1.0825,
                                 body_pts: float = 0.0040) -> dict:
    """
    Strong bullish candle: body = 40 pips >> 1.5× typical avg body of ~5 pips.
    """
    o = close_from
    c = close_from + body_pts
    h = c + 0.0005
    l = o - 0.0005
    return make_candle(offset, o, h, l, c)


def bearish_displacement_candle(offset: int, close_from: float = 1.0835,
                                  body_pts: float = 0.0040) -> dict:
    o = close_from
    c = close_from - body_pts
    h = o + 0.0005
    l = c - 0.0005
    return make_candle(offset, o, h, l, c)


def ifvg_gap_and_retest(start_offset: int, base: float = 1.0860,
                         direction: str = "bullish") -> list:
    """
    3 candles that create a FVG gap + 1 retest candle.

    Bullish IFVG: candles[i-1].low > candles[i+1].high
    (gap_high = candles[i-1].low = base+0.0010,
     gap_low  = candles[i+1].high = base+0.0005)
    gap_size = 0.0005 = 5 pips > 3 pip minimum ✓
    Retest: candle[i+2].low = base+0.0008 ≤ gap_high ✓
    """
    if direction == "bullish":
        prev = make_candle(start_offset,     base, base + 0.0020,
                           base + 0.0010, base + 0.0015)   # low = base+0.0010
        mid  = make_candle(start_offset + 1, base + 0.0015,
                           base + 0.0025, base + 0.0010, base + 0.0020)
        nxt  = make_candle(start_offset + 2, base + 0.0010,
                           base + 0.0005, base,         base + 0.0003)  # high = base+0.0005 < prev.low
        rtest = make_candle(start_offset + 3, base + 0.0012,
                            base + 0.0015, base + 0.0008, base + 0.0009)  # low ≤ gap_high
        return [prev, mid, nxt, rtest]
    else:  # bearish
        prev = make_candle(start_offset,     base - 0.0015,
                           base - 0.0010, base - 0.0020, base - 0.0015)  # high = base-0.0010
        mid  = make_candle(start_offset + 1, base - 0.0020,
                           base - 0.0010, base - 0.0025, base - 0.0020)
        nxt  = make_candle(start_offset + 2, base - 0.0005,
                           base + 0.0005, base,          base - 0.0003)  # low = base
        rtest = make_candle(start_offset + 3, base - 0.0008,
                            base - 0.0005, base - 0.0012, base - 0.0009)
        return [prev, mid, nxt, rtest]


# ===========================================================================
# ── 1. Pure detection-function tests (no DB) ───────────────────────────────
# ===========================================================================

@pytest.fixture
def detector():
    return ForexAMDDetector()


# ── Accumulation ────────────────────────────────────────────────────────────

class TestDetectAccumulation:

    def test_valid_accumulation_detected(self, detector):
        """8 tight-range candles with boundary touches → accumulation found.

        Uses high-volatility background (150 pip range) so that ATR is large
        enough for the 15-pip accumulation range to pass the 50%-ATR check.
        """
        bg = background_candles(20, range_size=0.0150)  # ATR ≈ 67 pips
        ac = accumulation_candles(20)                   # range = 15 pips < 33 pip threshold
        candles = bg + ac
        result = detector.detect_accumulation(candles)
        assert result is not None, "Expected accumulation to be detected"
        assert result["high"] == pytest.approx(1.0835, abs=1e-4)
        assert result["low"]  == pytest.approx(1.0820, abs=1e-4)
        assert result["quality_score"] >= 6

    def test_range_too_wide_returns_none(self, detector):
        """Range > ACCUM_MAX_RANGE_POINTS (5200 pts = 0.52 price units) → None.

        6000 pts (0.60 price units) is clearly above the 5200-pt threshold.
        """
        bg = background_candles(20)
        # range = 1.6200 - 1.0800 = 0.6000 = 6000 pts >> 5200-pt threshold
        wide = [make_candle(20 + i, 1.0800, 1.6200, 1.0800, 1.3000)
                for i in range(8)]
        result = detector.detect_accumulation(bg + wide)
        assert result is None

    def test_too_directional_returns_none(self, detector):
        """Strongly trending candles fail directional-bias check."""
        bg = background_candles(20)
        # Each candle moves 0.0010 in same direction → heavy directional bias
        trending = [make_candle(20 + i, 1.0800 + i * 0.0010,
                                1.0810 + i * 0.0010,
                                1.0800 + i * 0.0010,
                                1.0810 + i * 0.0010)
                    for i in range(8)]
        result = detector.detect_accumulation(bg + trending)
        assert result is None

    def test_too_few_candles_returns_none(self, detector):
        """Fewer than ACCUM_FIXED_WINDOW (8) candles → None."""
        result = detector.detect_accumulation(background_candles(3))
        assert result is None

    def test_insufficient_boundary_touches(self, detector):
        """Only one candle touches the low boundary → touches_low < 2 → not detected.

        All 8 candles touch the high (1.0835) but their lows are spread across
        13 pips so only the very first candle is within the touch tolerance of
        the minimum low.  The touches_low count stays at 1 < 2 → rejected.
        """
        bg = background_candles(20, range_size=0.0150)
        # Strictly increasing lows (2 pips per step) guarantee that in ANY
        # sub-window only the FIRST candle can be within touch-tolerance of
        # the sub-window minimum → touches_low stays at 1 < 2 → rejected.
        one_sided = [
            make_candle(20, 1.0825, 1.0835, 1.0822, 1.0830),  # low=1.0822
            make_candle(21, 1.0828, 1.0835, 1.0824, 1.0832),  # low=1.0824
            make_candle(22, 1.0830, 1.0835, 1.0826, 1.0828),  # low=1.0826
            make_candle(23, 1.0826, 1.0835, 1.0828, 1.0827),  # low=1.0828
            make_candle(24, 1.0827, 1.0835, 1.0829, 1.0830),  # low=1.0829
            make_candle(25, 1.0825, 1.0835, 1.0830, 1.0828),  # low=1.0830
            make_candle(26, 1.0826, 1.0835, 1.0831, 1.0832),  # low=1.0831
            make_candle(27, 1.0828, 1.0835, 1.0832, 1.0830),  # low=1.0832
        ]
        result = detector.detect_accumulation(bg + one_sided)
        assert result is None, (
            f"Expected no accumulation (only 1 low touch per sub-window); "
            f"got quality={result.get('quality_score') if result else 'N/A'}"
        )


# ── Sweep ────────────────────────────────────────────────────────────────────

class TestDetectSweep:

    ACCUM_HIGH = 1.0835
    ACCUM_LOW  = 1.0820

    def _candles_with_last(self, last_candle):
        bg = background_candles(10)
        bg.append(last_candle)
        return bg

    def test_bullish_sweep_valid(self, detector):
        """Wick ≥ 40%, close above accum_low → bullish sweep detected."""
        sweep = bullish_sweep_candle(10, accum_low=self.ACCUM_LOW)
        candles = self._candles_with_last(sweep)
        result = detector.detect_sweep(candles, self.ACCUM_HIGH, self.ACCUM_LOW)
        assert result is not None
        assert result["direction"] == "bullish"
        assert result["wick_pct"] > 40
        assert result["strength"] > 0

    def test_bearish_sweep_valid(self, detector):
        """Wick ≥ 40%, close below accum_high → bearish sweep detected."""
        sweep = bearish_sweep_candle(10, accum_high=self.ACCUM_HIGH)
        candles = self._candles_with_last(sweep)
        result = detector.detect_sweep(candles, self.ACCUM_HIGH, self.ACCUM_LOW)
        assert result is not None
        assert result["direction"] == "bearish"

    def test_weak_wick_below_threshold(self, detector):
        """Small wick (10%) → sweep rejected."""
        # low barely breaks accum_low but close is also very low (small wick)
        weak = make_candle(10, 1.0819, 1.0830, 1.0810, 1.0811)
        # wick_pct = (1.0811 - 1.0810) / (1.0830 - 1.0810) * 100 = 5% < 40%
        candles = self._candles_with_last(weak)
        result = detector.detect_sweep(candles, self.ACCUM_HIGH, self.ACCUM_LOW)
        assert result is None

    def test_close_not_back_inside_range(self, detector):
        """Candle dips below accum_low but closes below too → no rejection."""
        no_rejection = make_candle(10, 1.0820, 1.0830, 1.0810, 1.0815)
        # close (1.0815) < accum_low (1.0820) → invalid bullish sweep
        candles = self._candles_with_last(no_rejection)
        result = detector.detect_sweep(candles, self.ACCUM_HIGH, self.ACCUM_LOW)
        assert result is None

    def test_no_level_broken_returns_none(self, detector):
        """Candle stays inside range → no sweep."""
        inside = make_candle(10, 1.0825, 1.0834, 1.0821, 1.0828)
        candles = self._candles_with_last(inside)
        result = detector.detect_sweep(candles, self.ACCUM_HIGH, self.ACCUM_LOW)
        assert result is None

    def test_sweep_distance_too_small(self, detector):
        """Sweep only 1 pip below accum_low → below MIN_SWEEP_DISTANCE_PIPS (5)."""
        too_close = make_candle(10, 1.0820, 1.0830, 1.08191, 1.0825)
        # distance = 1.0820 - 1.08191 = 0.00009 < 5 pips (0.0005)
        candles = self._candles_with_last(too_close)
        result = detector.detect_sweep(candles, self.ACCUM_HIGH, self.ACCUM_LOW)
        assert result is None


# ── Displacement ─────────────────────────────────────────────────────────────

class TestDetectDisplacement:

    def _build_candles(self, last_candle, n_bg=20, base=1.0800):
        """
        Background candles with tight bodies (~2-3 pips), so a 40-pip
        displacement body is easily 1.5× the average.
        """
        bg = []
        for i in range(n_bg):
            bg.append(make_candle(i, base, base + 0.0050, base, base + 0.0003))
        bg.append(last_candle)
        return bg

    def test_bullish_displacement_detected(self, detector):
        disp = bullish_displacement_candle(20, body_pts=0.0040)
        candles = self._build_candles(disp)
        result = detector.detect_displacement(candles, "bullish")
        assert result is not None
        assert result["vs_avg_body"] >= AMDConfig.DISPLACEMENT_BODY_MULTIPLIER

    def test_bearish_displacement_detected(self, detector):
        disp = bearish_displacement_candle(20, body_pts=0.0040)
        candles = self._build_candles(disp)
        result = detector.detect_displacement(candles, "bearish")
        assert result is not None
        assert result["body_size"] == pytest.approx(0.0040, abs=1e-5)

    def test_wrong_direction_rejected(self, detector):
        """Bullish candle in bearish context → rejected."""
        disp = bullish_displacement_candle(20, body_pts=0.0040)
        candles = self._build_candles(disp)
        result = detector.detect_displacement(candles, "bearish")
        assert result is None

    def test_small_body_rejected(self, detector):
        """3-pip body when avg is 3 pips → ratio ≈ 1.0 < 1.5 threshold."""
        small = make_candle(20, 1.0820, 1.0826, 1.0818, 1.0823)
        # body = 0.0003, avg_body ≈ 0.0003 → ratio ≈ 1.0 < 1.5
        candles = self._build_candles(small)
        result = detector.detect_displacement(candles, "bullish")
        assert result is None

    def test_candle_idx_points_to_last(self, detector):
        """candle_idx must reference the final candle in the list."""
        disp = bullish_displacement_candle(20, body_pts=0.0040)
        candles = self._build_candles(disp)
        result = detector.detect_displacement(candles, "bullish")
        assert result is not None
        assert result["candle_idx"] == len(candles) - 1


# ── IFVG ─────────────────────────────────────────────────────────────────────

class TestDetectIFVG:

    def test_bullish_ifvg_with_retest(self, detector):
        """
        Valid bullish IFVG: candles[i-1].low > candles[i+1].high,
        gap ≥ 3 pips, retest occurs within 10 candles.
        """
        bg = background_candles(20)
        disp = bullish_displacement_candle(20, body_pts=0.0040)
        gap_candles = ifvg_gap_and_retest(21, base=disp["close"], direction="bullish")
        candles = bg + [disp] + gap_candles

        displacement_idx = len(bg)          # index 20
        result = detector.detect_ifvg(candles, displacement_idx, "bullish")
        assert result is not None
        assert result["gap_size"] >= detector._pips(AMDConfig.IFVG_MIN_GAP_PIPS)
        assert result["retest_idx"] is not None

    def test_bearish_ifvg_with_retest(self, detector):
        bg = background_candles(20)
        disp = bearish_displacement_candle(20, body_pts=0.0040)
        gap_candles = ifvg_gap_and_retest(21, base=disp["close"], direction="bearish")
        candles = bg + [disp] + gap_candles

        displacement_idx = len(bg)
        result = detector.detect_ifvg(candles, displacement_idx, "bearish")
        assert result is not None
        assert result["gap_size"] >= detector._pips(AMDConfig.IFVG_MIN_GAP_PIPS)

    def test_no_gap_returns_none(self, detector):
        """Overlapping candles after displacement → no IFVG."""
        bg = background_candles(20)
        disp = bullish_displacement_candle(20, body_pts=0.0040)
        base_price = disp["close"]
        # Overlapping candles: no gap condition satisfied
        no_gap = [
            make_candle(21, base_price, base_price + 0.0010, base_price - 0.0005, base_price + 0.0005),
            make_candle(22, base_price + 0.0005, base_price + 0.0015, base_price, base_price + 0.0010),
            make_candle(23, base_price + 0.0010, base_price + 0.0020, base_price + 0.0005, base_price + 0.0015),
        ]
        candles = bg + [disp] + no_gap
        result = detector.detect_ifvg(candles, len(bg), "bullish")
        assert result is None

    def test_gap_too_small_returns_none(self, detector):
        """Gap exists but < 3 pips → rejected."""
        bg = background_candles(20)
        disp = bullish_displacement_candle(20, body_pts=0.0040)
        base_price = disp["close"]
        # Create a tiny gap (1 pip = 0.0001)
        tiny_gap = [
            make_candle(21, base_price, base_price + 0.0010,
                        base_price + 0.0002, base_price + 0.0005),   # prev.low = base+0.0002
            make_candle(22, base_price + 0.0005, base_price + 0.0015,
                        base_price, base_price + 0.0010),              # mid
            make_candle(23, base_price + 0.0010, base_price + 0.0001,  # high = base+0.0001 < prev.low
                        base_price - 0.0005, base_price),
            make_candle(24, base_price + 0.0001, base_price + 0.0003,  # retest candidate
                        base_price, base_price + 0.0002),
        ]
        candles = bg + [disp] + tiny_gap
        result = detector.detect_ifvg(candles, len(bg), "bullish")
        assert result is None

    def test_no_retest_returns_none(self, detector):
        """Valid gap but price never retests → None."""
        bg = background_candles(20)
        disp = bullish_displacement_candle(20, body_pts=0.0040)
        base_price = disp["close"]
        # Gap: prev.low = base+0.0010, next.high = base+0.0005 → valid
        # But price keeps going up, never drops to gap_high
        gap_no_retest = [
            make_candle(21, base_price, base_price + 0.0020,
                        base_price + 0.0010, base_price + 0.0015),   # prev.low = base+0.0010
            make_candle(22, base_price + 0.0015, base_price + 0.0030,
                        base_price + 0.0015, base_price + 0.0025),   # mid
            make_candle(23, base_price + 0.0020, base_price + 0.0005,
                        base_price, base_price + 0.0003),             # next.high = base+0.0005
            # Retest window: price only goes higher, never back to gap_high = base+0.0010
            make_candle(24, base_price + 0.0030, base_price + 0.0050,
                        base_price + 0.0025, base_price + 0.0045),
            make_candle(25, base_price + 0.0045, base_price + 0.0060,
                        base_price + 0.0040, base_price + 0.0055),
        ]
        candles = bg + [disp] + gap_no_retest
        result = detector.detect_ifvg(candles, len(bg), "bullish")
        assert result is None


# ===========================================================================
# ── 2. State machine tests (mocked DB) ─────────────────────────────────────
# ===========================================================================

class TestStateMachine:
    """
    Tests for ForexAMDDetector.process_state_machine().

    DB is patched via `services.forex_amd_detector.db`.
    Each test configures `db.execute` to:
      - return the appropriate state dict when called as _load_state (fetchone=True)
      - act as a no-op (return None) for all INSERT/UPDATE calls

    We then assert that the saved state (via captured mock calls) reflects
    the expected transition.
    """

    USER_ID = 7
    SYMBOL  = "EUR/USD"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _state_row(state: int, accum=None, sweep=None, displacement=None) -> dict:
        """Build the dict that _load_state expects from db.execute(fetchone=True)."""
        return {
            "current_state":     state,
            "accumulation_data": json.dumps(accum or {}),
            "sweep_data":        json.dumps(sweep or {}),
            "displacement_data": json.dumps(displacement or {}),
        }

    @staticmethod
    def _mock_db(state_row):
        """
        Return a MagicMock for `db` whose `execute` side-effect:
          - returns state_row when called with fetchone=True
          - returns None otherwise
        """
        mock_db = MagicMock()
        def _execute(sql, params=None, fetchone=False, fetchall=False):
            if fetchone:
                return state_row
            return None
        mock_db.execute.side_effect = _execute
        return mock_db

    # ------------------------------------------------------------------
    # Transition: IDLE → ACCUMULATION
    # ------------------------------------------------------------------

    def test_idle_detects_accumulation_and_advances(self):
        """
        IDLE + valid accumulation pattern → state saved as ACCUMULATION,
        no alert returned.
        """
        bg = background_candles(20, range_size=0.0150)
        ac = accumulation_candles(20)
        candles = bg + ac

        db_mock = self._mock_db(self._state_row(AMDState.IDLE))
        with patch("services.forex_amd_detector.db", db_mock):
            detector = ForexAMDDetector()
            result = detector.process_state_machine(
                self.USER_ID, self.SYMBOL, candles
            )

        assert result is None   # no alert yet
        # _save_state must have been called with AMDState.ACCUMULATION
        calls_with_state = [
            c for c in db_mock.execute.call_args_list
            if c.args and "INSERT INTO forex_amd_state" in str(c.args[0])
               and len(c.args) > 1 and AMDState.ACCUMULATION in c.args[1]
        ]
        assert calls_with_state, (
            "Expected _save_state to be called with AMDState.ACCUMULATION; "
            f"db.execute calls:\n{db_mock.execute.call_args_list}"
        )

    def test_idle_no_accumulation_stays_idle(self):
        """IDLE with only volatile (non-consolidating) candles → no state save."""
        # Only background candles, no tight range → no accumulation
        candles = background_candles(20)

        db_mock = self._mock_db(self._state_row(AMDState.IDLE))
        with patch("services.forex_amd_detector.db", db_mock):
            detector = ForexAMDDetector()
            result = detector.process_state_machine(
                self.USER_ID, self.SYMBOL, candles
            )

        assert result is None
        # _save_state should NOT be called (no transition)
        insert_calls = [
            c for c in db_mock.execute.call_args_list
            if c.args and "INSERT INTO forex_amd_state" in str(c.args[0])
        ]
        assert not insert_calls, "Should not save state when no accumulation found"

    def test_idle_low_volatility_skips(self):
        """IDLE with ATR below threshold → return immediately, no detection."""
        # Flat candles: range ≈ 0 → ATR ≈ 0 < MIN_ATR_THRESHOLD
        flat = [make_candle(i, 1.0800, 1.0800, 1.0800, 1.0800) for i in range(20)]

        db_mock = self._mock_db(self._state_row(AMDState.IDLE))
        with patch("services.forex_amd_detector.db", db_mock):
            detector = ForexAMDDetector()
            result = detector.process_state_machine(
                self.USER_ID, self.SYMBOL, flat
            )

        assert result is None
        insert_calls = [
            c for c in db_mock.execute.call_args_list
            if c.args and "INSERT INTO forex_amd_state" in str(c.args[0])
        ]
        assert not insert_calls

    # ------------------------------------------------------------------
    # Transition: ACCUMULATION → SWEEP_DETECTED
    # ------------------------------------------------------------------

    def test_accumulation_detects_sweep_and_advances(self):
        """
        State=ACCUMULATION, last candle is a valid sweep → transition to
        SWEEP_DETECTED and _save_state called with AMDState.SWEEP_DETECTED.
        """
        accum_low = 1.0820
        accum_high = 1.0835
        bg = background_candles(20)
        ac = accumulation_candles(20)
        sweep = bullish_sweep_candle(28, accum_low=accum_low)
        candles = bg + ac + [sweep]

        saved_accum = {
            "start_idx": 20, "end_idx": 27,
            "high": accum_high, "low": accum_low,
            "range": accum_high - accum_low, "quality_score": 8.0,
        }
        db_mock = self._mock_db(
            self._state_row(AMDState.ACCUMULATION, accum=saved_accum)
        )
        with patch("services.forex_amd_detector.db", db_mock):
            detector = ForexAMDDetector()
            result = detector.process_state_machine(
                self.USER_ID, self.SYMBOL, candles
            )

        assert result is None
        calls_with_sweep_state = [
            c for c in db_mock.execute.call_args_list
            if c.args and "INSERT INTO forex_amd_state" in str(c.args[0])
               and len(c.args) > 1 and AMDState.SWEEP_DETECTED in c.args[1]
        ]
        assert calls_with_sweep_state, (
            "Expected _save_state with AMDState.SWEEP_DETECTED; "
            f"calls: {db_mock.execute.call_args_list}"
        )

    def test_accumulation_broken_resets_state(self):
        """Close > accum_high * 1.01 → accumulation is invalidated → RESET.

        _is_accumulation_broken uses a 1% price-level threshold.
        For EUR/USD at 1.0835 that means close > 1.094335 (~109 pips above
        accum_high), so we must use a 1.5%-above close.
        """
        accum_low = 1.0820
        accum_high = 1.0835
        bg = background_candles(20)
        # accum_high * 1.015 = ~1.0992, which is > accum_high * 1.01 = 1.0943
        breakout_close = accum_high * 1.015
        breakout = make_candle(20, accum_high, breakout_close + 0.0010,
                               accum_high, breakout_close)
        candles = bg + [breakout]

        saved_accum = {
            "start_idx": 10, "end_idx": 19,
            "high": accum_high, "low": accum_low,
            "range": 0.0015, "quality_score": 8.0,
        }
        db_mock = self._mock_db(
            self._state_row(AMDState.ACCUMULATION, accum=saved_accum)
        )
        with patch("services.forex_amd_detector.db", db_mock):
            detector = ForexAMDDetector()
            detector.process_state_machine(self.USER_ID, self.SYMBOL, candles)

        # _reset_state is called → UPDATE forex_amd_state SET current_state = 0
        reset_calls = [
            c for c in db_mock.execute.call_args_list
            if c.args and "UPDATE forex_amd_state" in str(c.args[0])
        ]
        assert reset_calls, (
            "Expected _reset_state (UPDATE) call on accumulation breakout; "
            f"calls: {db_mock.execute.call_args_list}"
        )

    def test_accumulation_no_sweep_stays(self):
        """State=ACCUMULATION, candle inside range → no transition."""
        accum_low = 1.0820
        accum_high = 1.0835
        bg = background_candles(20)
        inside = make_candle(20, 1.0825, 1.0834, 1.0821, 1.0828)
        candles = bg + [inside]

        saved_accum = {
            "start_idx": 10, "end_idx": 19,
            "high": accum_high, "low": accum_low,
            "range": 0.0015, "quality_score": 8.0,
        }
        db_mock = self._mock_db(
            self._state_row(AMDState.ACCUMULATION, accum=saved_accum)
        )
        with patch("services.forex_amd_detector.db", db_mock):
            detector = ForexAMDDetector()
            result = detector.process_state_machine(
                self.USER_ID, self.SYMBOL, candles
            )

        assert result is None
        save_calls = [
            c for c in db_mock.execute.call_args_list
            if c.args and "INSERT INTO forex_amd_state" in str(c.args[0])
        ]
        assert not save_calls

    # ------------------------------------------------------------------
    # Transition: SWEEP_DETECTED → DISPLACEMENT_CONFIRMED or timeout
    # ------------------------------------------------------------------

    def test_sweep_state_detects_displacement(self):
        """
        State=SWEEP_DETECTED, last candle is a strong bullish displacement.
        """
        bg = []
        for i in range(20):
            bg.append(make_candle(i, 1.0800, 1.0850, 1.0800, 1.0803))

        disp = bullish_displacement_candle(20, body_pts=0.0040)
        candles = bg + [disp]

        sweep_idx = 15  # pretend sweep was at idx 15 → 5 candles ago
        # sweep_candle_idx lives INSIDE sweep dict (fixed production code)
        raw_row = {
            "current_state": AMDState.SWEEP_DETECTED,
            "accumulation_data": json.dumps({
                "start_idx": 5, "end_idx": 14,
                "high": 1.0835, "low": 1.0820,
                "range": 0.0015, "quality_score": 8.0,
            }),
            "sweep_data": json.dumps({
                "direction": "bullish", "level": 1.0815,
                "wick_pct": 75.0, "strength": 8.0,
                "sweep_candle_idx": sweep_idx,   # ← embedded here now
            }),
            "displacement_data": json.dumps({}),
        }

        def _execute(sql, params=None, fetchone=False, fetchall=False):
            if fetchone:
                return raw_row
            return None

        db_mock2 = MagicMock()
        db_mock2.execute.side_effect = _execute

        with patch("services.forex_amd_detector.db", db_mock2):
            detector = ForexAMDDetector()
            result = detector.process_state_machine(
                self.USER_ID, self.SYMBOL, candles
            )

        assert result is None
        save_disp_calls = [
            c for c in db_mock2.execute.call_args_list
            if c.args and "INSERT INTO forex_amd_state" in str(c.args[0])
               and len(c.args) > 1 and AMDState.DISPLACEMENT_CONFIRMED in c.args[1]
        ]
        assert save_disp_calls, (
            "Expected save with AMDState.DISPLACEMENT_CONFIRMED; "
            f"calls: {db_mock2.execute.call_args_list}"
        )

    def test_sweep_timeout_resets(self):
        """
        sweep_candle_idx is far behind current length → timeout → RESET.
        MAX_SWEEP_TO_DISPLACEMENT_CANDLES = 5

        sweep_candle_idx is stored INSIDE the sweep dict (the JSON column),
        which is where the fixed production code now persists it.
        """
        candles = background_candles(30)  # 30 candles total

        # sweep_candle_idx = 0 → candles_since_sweep = 29 >> 5
        raw_row = {
            "current_state": AMDState.SWEEP_DETECTED,
            "accumulation_data": json.dumps({}),
            # sweep_candle_idx lives INSIDE sweep dict (fixed production code)
            "sweep_data": json.dumps({
                "direction": "bullish", "level": 1.0815,
                "wick_pct": 75.0, "strength": 8.0,
                "sweep_candle_idx": 0,   # ← embedded here now
            }),
            "displacement_data": json.dumps({}),
        }

        def _execute(sql, params=None, fetchone=False, fetchall=False):
            if fetchone:
                return raw_row
            return None

        db_mock = MagicMock()
        db_mock.execute.side_effect = _execute

        with patch("services.forex_amd_detector.db", db_mock):
            detector = ForexAMDDetector()
            result = detector.process_state_machine(
                self.USER_ID, self.SYMBOL, candles
            )

        assert result is None
        reset_calls = [
            c for c in db_mock.execute.call_args_list
            if c.args and "UPDATE forex_amd_state" in str(c.args[0])
        ]
        assert reset_calls, "Expected _reset_state on sweep timeout"

    # ------------------------------------------------------------------
    # Transition: DISPLACEMENT_CONFIRMED → ALERT or timeout
    # ------------------------------------------------------------------

    def test_displacement_timeout_resets(self):
        """
        displacement_idx is far behind → IFVG timeout → RESET.
        MAX_DISPLACEMENT_TO_IFVG_CANDLES = 10
        """
        candles = background_candles(30)

        # displacement at idx 0 → candles_since_displacement = 29 >> 10
        raw_row = {
            "current_state": AMDState.DISPLACEMENT_CONFIRMED,
            "accumulation_data": json.dumps({
                "start_idx": 0, "end_idx": 5,
                "high": 1.0835, "low": 1.0820,
                "range": 0.0015, "quality_score": 8.0,
            }),
            "sweep_data": json.dumps({
                "direction": "bullish", "level": 1.0815,
                "wick_pct": 75.0, "strength": 8.0,
            }),
            "displacement_data": json.dumps({
                "candle_idx": 0,
                "body_size": 0.0040, "vs_avg_body": 8.0,
                "vs_atr": 2.0, "quality": 9.0,
            }),
        }

        def _execute(sql, params=None, fetchone=False, fetchall=False):
            if fetchone:
                return raw_row
            return None

        db_mock = MagicMock()
        db_mock.execute.side_effect = _execute

        with patch("services.forex_amd_detector.db", db_mock):
            detector = ForexAMDDetector()
            result = detector.process_state_machine(
                self.USER_ID, self.SYMBOL, candles
            )

        assert result is None
        reset_calls = [
            c for c in db_mock.execute.call_args_list
            if c.args and "UPDATE forex_amd_state" in str(c.args[0])
        ]
        assert reset_calls, "Expected _reset_state on IFVG timeout"

    def test_full_sequence_fires_alert(self):
        """
        Happy-path integration test: DISPLACEMENT_CONFIRMED state with
        a valid IFVG + retest in the candle window → alert returned,
        DB written, state reset.

        Mocks:
        - services.forex_amd_detector.db.execute
        """
        # Build candle array:
        # idx 0-19: background
        # idx 20: displacement (candle_idx we'll tell the state machine about)
        # idx 21-24: gap + retest candles (IFVG)
        bg = []
        for i in range(20):
            bg.append(make_candle(i, 1.0800, 1.0850, 1.0800, 1.0803))

        disp = bullish_displacement_candle(20, close_from=1.0820, body_pts=0.0040)
        gap_candles = ifvg_gap_and_retest(21, base=disp["close"], direction="bullish")
        candles = bg + [disp] + gap_candles

        displacement_idx = 20   # index of disp in candles

        raw_row = {
            "current_state": AMDState.DISPLACEMENT_CONFIRMED,
            "accumulation_data": json.dumps({
                "start_idx": 5, "end_idx": 18,
                "high": 1.0835, "low": 1.0820,
                "range": 0.0015, "quality_score": 8.0,
            }),
            "sweep_data": json.dumps({
                "direction": "bullish", "level": 1.0815,
                "wick_pct": 75.0, "strength": 8.0,
            }),
            "displacement_data": json.dumps({
                "candle_idx": displacement_idx,
                "body_size": 0.0040, "vs_avg_body": 8.0,
                "vs_atr": 2.0, "quality": 9.0,
            }),
        }

        def _execute(sql, params=None, fetchone=False, fetchall=False):
            if fetchone:
                return raw_row
            return None

        db_mock = MagicMock()
        db_mock.execute.side_effect = _execute

        with patch("services.forex_amd_detector.db", db_mock):
            detector = ForexAMDDetector()
            alert = detector.process_state_machine(
                self.USER_ID, self.SYMBOL, candles
            )

        # ── 1. Alert returned ─────────────────────────────────────────
        assert alert is not None, "Expected alert to be fired"
        assert alert["direction"] == "bullish"
        assert alert["symbol"] == self.SYMBOL
        assert "ifvg_range" in alert
        assert isinstance(alert["quality_score"], int)

        # ── 2. History written (INSERT INTO forex_amd_alerts) ─────────
        alert_insert_calls = [
            c for c in db_mock.execute.call_args_list
            if c.args and "INSERT INTO forex_amd_alerts" in str(c.args[0])
        ]
        assert alert_insert_calls, "Expected INSERT INTO forex_amd_alerts"

        # ── 3. State reset (UPDATE forex_amd_state) ───────────────────
        reset_calls = [
            c for c in db_mock.execute.call_args_list
            if c.args and "UPDATE forex_amd_state" in str(c.args[0])
        ]
        assert reset_calls, "Expected state to be reset after alert"
