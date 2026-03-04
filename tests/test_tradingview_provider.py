"""
Unit tests for the TradingView (Pepperstone) candle provider.

Run with:
    cd /path/to/stock-alerts-multiuser
    python -m pytest tests/test_tradingview_provider.py -v

Tests cover:
  1. normalize_to_tv()        – symbol normalization to TradingView compact format
  2. _parse_df()              – DataFrame → candle dict list, correct timestamps
  3. _drop_incomplete()       – in-progress bar detection and removal
  4. Routing / wiring         – Forex Sessions always goes through TradingViewProvider
  5. Integration              – detect_for_user routes to tradingview_provider
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# ── Stubs ─────────────────────────────────────────────────────────────────────
sys.modules.setdefault("database", MagicMock())
sys.modules["database"].db = MagicMock()
sys.modules.setdefault("email_sender", MagicMock())

# Force-set the tvdatafeed stub (not setdefault) so it overrides any prior state.
_fake_tvdatafeed = MagicMock()
_fake_tvdatafeed.TvDatafeed = MagicMock()
_fake_tvdatafeed.Interval.in_5_minute = "in_5_minute"
sys.modules["tvdatafeed"] = _fake_tvdatafeed

from services.tradingview_provider import normalize_to_tv, TradingViewProvider, tradingview_provider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ok(raw: str, expected: str) -> None:
    """Assert normalize_to_tv(raw) returns (expected, None)."""
    result, err = normalize_to_tv(raw)
    assert err is None, f"Unexpected error for {raw!r}: {err}"
    assert result == expected, (
        f"normalize_to_tv({raw!r}) = {result!r}, want {expected!r}"
    )


def fail(raw) -> None:
    """Assert normalize_to_tv(raw) returns (None, <error>)."""
    result, err = normalize_to_tv(raw)
    assert result is None, (
        f"Expected failure for {raw!r} but got result={result!r}"
    )
    assert err and isinstance(err, str), (
        f"Expected non-empty error string for {raw!r}, got err={err!r}"
    )


def _make_provider() -> TradingViewProvider:
    """Return a TradingViewProvider with a mocked client."""
    prov = TradingViewProvider.__new__(TradingViewProvider)
    prov._client = MagicMock()
    return prov


# ---------------------------------------------------------------------------
# 1. normalize_to_tv – positive cases
# ---------------------------------------------------------------------------

class TestNormalizeToTvPositive:

    # Compact 6-char (the TradingView native format)
    def test_eurusd_upper(self):      ok("EURUSD",  "EURUSD")
    def test_eurusd_lower(self):      ok("eurusd",  "EURUSD")
    def test_xauusd_upper(self):      ok("XAUUSD",  "XAUUSD")
    def test_xauusd_lower(self):      ok("xauusd",  "XAUUSD")
    def test_gbpjpy(self):            ok("GBPJPY",  "GBPJPY")
    def test_usdjpy(self):            ok("USDJPY",  "USDJPY")
    def test_xagusd(self):            ok("xagusd",  "XAGUSD")
    def test_audusd(self):            ok("audusd",  "AUDUSD")
    def test_usdchf(self):            ok("USDCHF",  "USDCHF")
    def test_nzdusd(self):            ok("NZDUSD",  "NZDUSD")
    def test_usdcad(self):            ok("USDCAD",  "USDCAD")
    def test_eurgbp(self):            ok("EURGBP",  "EURGBP")

    # Slash-separated
    def test_eur_usd_slash(self):     ok("EUR/USD", "EURUSD")
    def test_xau_usd_slash(self):     ok("XAU/USD", "XAUUSD")
    def test_lower_slash(self):       ok("eur/usd", "EURUSD")
    def test_spaces_slash(self):      ok("EUR / USD", "EURUSD")

    # Dash-separated
    def test_eur_dash_usd(self):      ok("EUR-USD", "EURUSD")
    def test_xau_dash_usd(self):      ok("XAU-USD", "XAUUSD")

    # Underscore-separated
    def test_eur_underscore(self):    ok("EUR_USD", "EURUSD")
    def test_xau_underscore(self):    ok("XAU_USD", "XAUUSD")
    def test_gbp_underscore(self):    ok("GBP_JPY", "GBPJPY")

    # Space-separated
    def test_usd_space_jpy(self):     ok("USD JPY", "USDJPY")
    def test_lower_space(self):       ok("usd jpy", "USDJPY")

    # Mixed case
    def test_mixed_dash(self):        ok("Xau-Usd", "XAUUSD")
    def test_mixed_slash(self):       ok("Gbp/Jpy", "GBPJPY")

    # Whitespace trimming
    def test_leading_spaces(self):    ok("  EURUSD",  "EURUSD")
    def test_trailing_spaces(self):   ok("EURUSD  ",  "EURUSD")
    def test_both_spaces(self):       ok(" EUR/USD ", "EURUSD")

    def test_no_slash_in_output(self):
        result, err = normalize_to_tv("EUR/USD")
        assert err is None
        assert "/" not in result, f"Output must not contain slash: {result!r}"

    def test_no_underscore_in_output(self):
        result, err = normalize_to_tv("EUR_USD")
        assert err is None
        assert "_" not in result, f"Output must not contain underscore: {result!r}"

    def test_output_is_6_chars(self):
        for raw in ("EURUSD", "XAU/USD", "gbpjpy"):
            result, err = normalize_to_tv(raw)
            assert err is None
            assert len(result) == 6, f"Expected 6-char result for {raw!r}, got {result!r}"


# ---------------------------------------------------------------------------
# 2. normalize_to_tv – failure cases
# ---------------------------------------------------------------------------

class TestNormalizeToTvFailures:

    def test_empty_string(self):      fail("")
    def test_spaces_only(self):       fail("   ")
    def test_none_type(self):         fail(None)
    def test_too_short(self):         fail("EUUS")
    def test_too_long(self):          fail("EURUSDX")
    def test_same_base_quote(self):   fail("USDUSD")
    def test_unknown_base(self):      fail("ABCUSD")
    def test_unknown_quote(self):     fail("USDXYZ")

    def test_result_none_on_failure(self):
        result, _ = normalize_to_tv("BADXXX")
        assert result is None

    def test_error_str_on_failure(self):
        _, err = normalize_to_tv("BADXXX")
        assert isinstance(err, str) and len(err) > 0


# ---------------------------------------------------------------------------
# 3. _parse_df – DataFrame parsing and timestamp correctness
# ---------------------------------------------------------------------------

class TestParseDF:
    """
    _parse_df() must convert a tvdatafeed DataFrame into the internal format
    with naive-UTC timestamps representing the candle OPEN time.
    """

    def _make_df(self, rows: list):
        """Build a minimal DataFrame that mimics tvdatafeed output."""
        import pandas as pd
        index = [r[0] for r in rows]
        data  = {
            "open":   [r[1] for r in rows],
            "high":   [r[2] for r in rows],
            "low":    [r[3] for r in rows],
            "close":  [r[4] for r in rows],
            "volume": [r[5] for r in rows],
        }
        return pd.DataFrame(data, index=pd.DatetimeIndex(index))

    def test_basic_parse(self):
        df = self._make_df([
            (datetime(2024, 1, 15, 9, 0), 1.10, 1.11, 1.09, 1.105, 1000),
            (datetime(2024, 1, 15, 9, 5), 1.11, 1.12, 1.10, 1.115, 1100),
        ])
        candles = TradingViewProvider._parse_df(df)
        assert len(candles) == 2
        assert candles[0]["timestamp"] == datetime(2024, 1, 15, 9, 0)
        assert candles[1]["timestamp"] == datetime(2024, 1, 15, 9, 5)

    def test_naive_utc_no_tzinfo(self):
        """Parsed timestamps must be naive (tzinfo is None)."""
        df = self._make_df([
            (datetime(2024, 1, 15, 9, 0, tzinfo=timezone.utc), 1.10, 1.11, 1.09, 1.105, 0),
        ])
        candles = TradingViewProvider._parse_df(df)
        assert candles[0]["timestamp"].tzinfo is None

    def test_tz_aware_input_normalized_to_utc(self):
        """tz-aware timestamps (UTC) must become naive UTC, not shifted."""
        ts_utc = datetime(2024, 7, 15, 6, 30, tzinfo=timezone.utc)
        df = self._make_df([
            (ts_utc, 1.08, 1.09, 1.07, 1.085, 500),
        ])
        candles = TradingViewProvider._parse_df(df)
        assert candles[0]["timestamp"] == datetime(2024, 7, 15, 6, 30)

    def test_sorted_oldest_first(self):
        """Output must be sorted oldest → newest."""
        df = self._make_df([
            (datetime(2024, 1, 15, 9, 5), 1.11, 1.12, 1.10, 1.115, 100),
            (datetime(2024, 1, 15, 9, 0), 1.10, 1.11, 1.09, 1.105, 200),
        ])
        candles = TradingViewProvider._parse_df(df)
        assert candles[0]["timestamp"] < candles[1]["timestamp"]

    def test_ohlc_values(self):
        df = self._make_df([
            (datetime(2024, 1, 15, 9, 0), 1.10000, 1.10500, 1.09800, 1.10200, 999),
        ])
        candles = TradingViewProvider._parse_df(df)
        c = candles[0]
        assert c["open"]   == pytest.approx(1.10000)
        assert c["high"]   == pytest.approx(1.10500)
        assert c["low"]    == pytest.approx(1.09800)
        assert c["close"]  == pytest.approx(1.10200)
        assert c["volume"] == pytest.approx(999.0)

    def test_timestamp_is_open_time(self):
        """
        The timestamp must be the OPEN time of the bar, not the close.
        A 5-min bar at 09:00 covers [09:00, 09:05); timestamp = 09:00.
        """
        df = self._make_df([
            (datetime(2024, 1, 15, 9, 0), 1.10, 1.11, 1.09, 1.105, 0),
        ])
        candles = TradingViewProvider._parse_df(df)
        ts = candles[0]["timestamp"]
        assert ts.hour == 9 and ts.minute == 0, (
            "Timestamp must be the bar OPEN time (09:00), not close time (09:05)"
        )


# ---------------------------------------------------------------------------
# 4. _drop_incomplete – in-progress bar removal
# ---------------------------------------------------------------------------

class TestDropIncomplete:

    def _c(self, ts: datetime) -> dict:
        return {"timestamp": ts, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0}

    def test_drops_current_forming_bar(self):
        """Last candle at the current 5-min bucket must be dropped."""
        now = datetime.utcnow()
        bucket_min = (now.minute // 5) * 5
        current_bucket = now.replace(minute=bucket_min, second=0, microsecond=0)

        candles = [
            self._c(current_bucket - timedelta(minutes=5)),
            self._c(current_bucket),   # <- this is the forming bar
        ]
        result = TradingViewProvider._drop_incomplete(candles)
        assert len(result) == 1
        assert result[0]["timestamp"] == current_bucket - timedelta(minutes=5)

    def test_keeps_complete_bar(self):
        """A candle clearly in the past must not be dropped."""
        past_ts = datetime(2020, 1, 1, 0, 0)
        candles = [self._c(past_ts)]
        result = TradingViewProvider._drop_incomplete(candles)
        assert len(result) == 1

    def test_empty_list_unchanged(self):
        assert TradingViewProvider._drop_incomplete([]) == []


# ---------------------------------------------------------------------------
# 5. Routing – Forex Sessions always uses TradingViewProvider
# ---------------------------------------------------------------------------

class TestRouting:

    def test_session_break_detector_imports_tradingview_not_oanda(self):
        import services.session_break_detector as sbd
        assert hasattr(sbd, "tradingview_provider"), (
            "session_break_detector must import tradingview_provider"
        )
        assert not hasattr(sbd, "oanda_provider"), (
            "session_break_detector must NOT reference oanda_provider"
        )

    def test_detector_calls_get_candles_not_get_recent_candles(self):
        import inspect
        import services.session_break_detector as sbd
        src = inspect.getsource(sbd)
        assert "tradingview_provider.get_candles" in src
        assert "get_recent_candles" not in src

    def test_singleton_is_tradingview_provider_instance(self):
        from services.tradingview_provider import tradingview_provider as tp
        assert isinstance(tp, TradingViewProvider)

    def test_normalize_to_tv_is_exported(self):
        from services.tradingview_provider import normalize_to_tv as ntt
        assert callable(ntt)

    def test_get_candles_method_exists(self):
        assert hasattr(TradingViewProvider, "get_candles")
        assert callable(TradingViewProvider.get_candles)

    def test_get_candles_returns_empty_when_client_none(self):
        prov = TradingViewProvider.__new__(TradingViewProvider)
        prov._client = None
        assert prov.get_candles("EURUSD") == []

    def test_get_candles_returns_empty_on_invalid_symbol(self):
        prov = _make_provider()
        assert prov.get_candles("BADXXX") == []

    def test_get_candles_never_raises(self):
        """get_candles must never propagate exceptions (scheduler-safe)."""
        prov = _make_provider()
        prov._client.get_hist.side_effect = RuntimeError("network failure")
        result = prov.get_candles("EURUSD")
        assert result == []

    def test_no_oanda_provider_file(self):
        """services/oanda_provider.py must not exist after rollback."""
        import pathlib
        oanda_file = pathlib.Path(__file__).parent.parent / "services" / "oanda_provider.py"
        assert not oanda_file.exists(), (
            "services/oanda_provider.py should have been deleted in rollback"
        )


# ---------------------------------------------------------------------------
# 6. Integration – detect_for_user calls tradingview_provider.get_candles
# ---------------------------------------------------------------------------

class TestDetectorCallsTradingView:

    def test_detect_for_user_uses_tradingview_provider(self):
        import services.session_break_detector as sbd
        from services.session_break_detector import SessionBreakDetector

        mock_db = MagicMock()
        mock_db.execute.return_value = [{"symbol": "EURUSD"}]

        captured = []

        def fake_get_candles(symbol, count=500):
            captured.append({"symbol": symbol, "count": count})
            return []

        with patch.object(sbd.tradingview_provider, "get_candles", side_effect=fake_get_candles):
            with patch.object(sbd, "db", mock_db):
                detector = SessionBreakDetector()
                detector.detect_for_user(
                    user_id=1,
                    user_email="test@example.com",
                    candle_cache={},
                    run_id="test-run",
                )

        assert len(captured) == 1
        assert captured[0]["symbol"] == "EURUSD"
        assert captured[0]["count"] == 500
