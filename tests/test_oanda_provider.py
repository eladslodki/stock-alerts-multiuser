"""
Unit tests for the OANDA candle provider.

Run with:
    cd /path/to/stock-alerts-multiuser
    python -m pytest tests/test_oanda_provider.py -v

Tests cover:
  1. normalize_to_oanda()  – symbol normalization to OANDA instrument format
  2. OandaProvider._parse_candle()  – timestamp correctness (UTC open time)
  3. Routing assertions   – Forex Sessions always goes through OandaProvider
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

# Stub database before importing the service modules (no live DB needed)
sys.modules.setdefault("database", MagicMock())
sys.modules["database"].db = MagicMock()
sys.modules.setdefault("email_sender", MagicMock())

from services.oanda_provider import normalize_to_oanda, OandaProvider, oanda_provider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ok(raw: str, expected: str) -> None:
    """Assert normalize_to_oanda(raw) returns (expected, None)."""
    result, err = normalize_to_oanda(raw)
    assert err is None, f"Unexpected error for {raw!r}: {err}"
    assert result == expected, (
        f"normalize_to_oanda({raw!r}) = {result!r}, want {expected!r}"
    )


def fail(raw) -> None:
    """Assert normalize_to_oanda(raw) returns (None, <error>)."""
    result, err = normalize_to_oanda(raw)
    assert result is None, (
        f"Expected failure for {raw!r} but got result={result!r}"
    )
    assert err and isinstance(err, str), (
        f"Expected non-empty error string for {raw!r}, got err={err!r}"
    )


# ---------------------------------------------------------------------------
# 1. normalize_to_oanda – positive cases
# ---------------------------------------------------------------------------

class TestNormalizeToOandaPositive:
    """EURUSD / EUR/USD / EUR-USD / EUR_USD all → EUR_USD."""

    # Compact 6-char
    def test_eurusd_upper(self):      ok("EURUSD",   "EUR_USD")
    def test_eurusd_lower(self):      ok("eurusd",   "EUR_USD")
    def test_xauusd_upper(self):      ok("XAUUSD",   "XAU_USD")
    def test_xauusd_lower(self):      ok("xauusd",   "XAU_USD")
    def test_gbpjpy(self):            ok("GBPJPY",   "GBP_JPY")
    def test_usdjpy(self):            ok("USDJPY",   "USD_JPY")
    def test_xagusd(self):            ok("xagusd",   "XAG_USD")
    def test_audusd(self):            ok("audusd",   "AUD_USD")
    def test_usdchf(self):            ok("USDCHF",   "USD_CHF")
    def test_nzdusd(self):            ok("NZDUSD",   "NZD_USD")
    def test_usdcad(self):            ok("USDCAD",   "USD_CAD")
    def test_eurgbp(self):            ok("EURGBP",   "EUR_GBP")

    # Slash-separated
    def test_eur_usd_slash(self):     ok("EUR/USD",  "EUR_USD")
    def test_xau_usd_slash(self):     ok("XAU/USD",  "XAU_USD")
    def test_lower_slash(self):       ok("eur/usd",  "EUR_USD")
    def test_spaces_around_slash(self): ok("EUR / USD", "EUR_USD")

    # Dash-separated
    def test_eur_dash_usd(self):      ok("EUR-USD",  "EUR_USD")
    def test_xau_dash_usd(self):      ok("XAU-USD",  "XAU_USD")

    # Underscore-separated (OANDA format already)
    def test_eur_underscore(self):    ok("EUR_USD",  "EUR_USD")
    def test_xau_underscore(self):    ok("XAU_USD",  "XAU_USD")
    def test_gbp_underscore(self):    ok("GBP_JPY",  "GBP_JPY")

    # Space-separated
    def test_usd_space_jpy(self):     ok("USD JPY",  "USD_JPY")
    def test_usd_space_jpy_lower(self): ok("usd jpy", "USD_JPY")

    # Mixed case
    def test_mixed_case_dash(self):   ok("Xau-Usd",  "XAU_USD")
    def test_mixed_slash(self):       ok("Gbp/Jpy",  "GBP_JPY")

    # Whitespace trimming
    def test_leading_spaces(self):    ok("  EURUSD",  "EUR_USD")
    def test_trailing_spaces(self):   ok("EURUSD  ",  "EUR_USD")
    def test_both_spaces(self):       ok(" EUR/USD ", "EUR_USD")


# ---------------------------------------------------------------------------
# 2. normalize_to_oanda – negative / failure cases
# ---------------------------------------------------------------------------

class TestNormalizeToOandaFailures:

    def test_empty_string(self):       fail("")
    def test_spaces_only(self):        fail("   ")
    def test_none_type(self):          fail(None)
    def test_too_short(self):          fail("EUUS")
    def test_too_long(self):           fail("EURUSDX")
    def test_same_base_quote(self):    fail("USDUSD")
    def test_unknown_base(self):       fail("ABCUSD")
    def test_unknown_quote(self):      fail("USDXYZ")
    def test_both_unknown(self):       fail("ABCXYZ")

    def test_result_is_none_on_failure(self):
        result, err = normalize_to_oanda("BADXXX")
        assert result is None

    def test_error_is_str_on_failure(self):
        _, err = normalize_to_oanda("BADXXX")
        assert isinstance(err, str) and len(err) > 0

    def test_uses_underscore_not_slash(self):
        result, err = normalize_to_oanda("EURUSD")
        assert err is None
        assert "/" not in result, f"Expected underscore, got {result!r}"
        assert "_" in result


# ---------------------------------------------------------------------------
# 3. Return value contract
# ---------------------------------------------------------------------------

class TestNormalizeReturnContract:

    def test_success_returns_tuple_two(self):
        result = normalize_to_oanda("EURUSD")
        assert isinstance(result, tuple) and len(result) == 2

    def test_success_second_element_none(self):
        _, err = normalize_to_oanda("EURUSD")
        assert err is None

    def test_failure_first_element_none(self):
        result, _ = normalize_to_oanda("BADXXX")
        assert result is None


# ---------------------------------------------------------------------------
# 4. Timestamp correctness  –  _parse_candle
# ---------------------------------------------------------------------------

class TestTimestampParsing:
    """
    OANDA candle timestamps are in RFC 3339 with nanoseconds and 'Z' suffix.
    _parse_candle() must parse them to naive UTC datetimes (no tzinfo)
    representing the candle OPEN time.
    """

    def _make_provider(self):
        """Return an OandaProvider without triggering env-var warnings."""
        with patch.dict(os.environ, {"OANDA_API_KEY": "test-key", "OANDA_ENV": "practice"}):
            return OandaProvider()

    def _raw(self, ts_str: str) -> dict:
        return {
            "time": ts_str,
            "mid": {"o": "1.10000", "h": "1.10100", "l": "1.09900", "c": "1.10050"},
            "volume": 100,
            "complete": True,
        }

    def test_nanosecond_format(self):
        p = self._make_provider()
        c = p._parse_candle(self._raw("2024-01-15T09:00:00.000000000Z"))
        assert c["timestamp"] == datetime(2024, 1, 15, 9, 0, 0)

    def test_microsecond_format(self):
        p = self._make_provider()
        c = p._parse_candle(self._raw("2024-07-15T06:30:00.123456Z"))
        assert c["timestamp"] == datetime(2024, 7, 15, 6, 30, 0, 123456)

    def test_no_fractional_seconds(self):
        p = self._make_provider()
        c = p._parse_candle(self._raw("2024-03-20T14:05:00Z"))
        assert c["timestamp"] == datetime(2024, 3, 20, 14, 5, 0)

    def test_naive_utc(self):
        """Parsed timestamp must be naive (tzinfo is None)."""
        p = self._make_provider()
        c = p._parse_candle(self._raw("2024-01-15T09:00:00.000000000Z"))
        assert c["timestamp"].tzinfo is None

    def test_is_open_time(self):
        """The parsed timestamp must be the candle OPEN time (start of bar)."""
        p = self._make_provider()
        c = p._parse_candle(self._raw("2024-01-15T09:00:00.000000000Z"))
        # A 5-min bar starting at 09:00 is the OPEN time, not 09:05
        assert c["timestamp"].hour == 9
        assert c["timestamp"].minute == 0

    def test_ohlc_values(self):
        p = self._make_provider()
        c = p._parse_candle(self._raw("2024-01-15T09:00:00.000000000Z"))
        assert c["open"]  == pytest.approx(1.10000)
        assert c["high"]  == pytest.approx(1.10100)
        assert c["low"]   == pytest.approx(1.09900)
        assert c["close"] == pytest.approx(1.10050)
        assert c["volume"] == 100.0


# ---------------------------------------------------------------------------
# 5. Routing – Forex Sessions always uses OandaProvider
# ---------------------------------------------------------------------------

class TestRouting:
    """
    Verify that the Forex Sessions detector imports and uses OandaProvider,
    not the Twelve Data ForexDataProvider.
    """

    def test_session_break_detector_imports_oanda_not_twelve_data(self):
        """session_break_detector must not import forex_data_provider for candles."""
        import importlib
        import services.session_break_detector as sbd_module

        # The oanda_provider singleton must be present in the module
        assert hasattr(sbd_module, "oanda_provider"), (
            "session_break_detector must import oanda_provider"
        )

    def test_session_break_detector_does_not_call_get_recent_candles(self):
        """
        The detector must call oanda_provider.get_candles(), not
        forex_data_provider.get_recent_candles().
        """
        import inspect
        import services.session_break_detector as sbd_module

        source = inspect.getsource(sbd_module)
        # oanda_provider.get_candles must appear
        assert "oanda_provider.get_candles" in source, (
            "Detector must call oanda_provider.get_candles()"
        )
        # get_recent_candles must NOT appear (Twelve Data)
        assert "get_recent_candles" not in source, (
            "Detector must not call get_recent_candles (Twelve Data)"
        )

    def test_oanda_provider_singleton_is_oanda_provider_instance(self):
        """Module-level singleton must be an OandaProvider."""
        from services.oanda_provider import oanda_provider as op
        assert isinstance(op, OandaProvider)

    def test_normalize_to_oanda_is_exported(self):
        """normalize_to_oanda must be importable from oanda_provider."""
        from services.oanda_provider import normalize_to_oanda as nto
        assert callable(nto)

    def test_get_candles_method_exists(self):
        """OandaProvider must expose get_candles()."""
        assert hasattr(OandaProvider, "get_candles")
        assert callable(OandaProvider.get_candles)

    def test_get_candles_returns_empty_without_api_key(self):
        """get_candles() must return [] (not raise) when API key is missing."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OANDA_API_KEY", None)
            prov = OandaProvider()
        result = prov.get_candles("EURUSD", count=10)
        assert result == []

    def test_get_candles_returns_empty_on_invalid_symbol(self):
        """get_candles() must return [] for an unknown symbol."""
        with patch.dict(os.environ, {"OANDA_API_KEY": "test-key", "OANDA_ENV": "practice"}):
            prov = OandaProvider()
        result = prov.get_candles("BADXXX", count=10)
        assert result == []

    def test_get_candles_never_raises(self):
        """get_candles() must never propagate exceptions (scheduler-safe)."""
        with patch.dict(os.environ, {"OANDA_API_KEY": "test-key", "OANDA_ENV": "practice"}):
            prov = OandaProvider()
        # Force an HTTP error via mock
        with patch("services.oanda_provider.requests.get", side_effect=RuntimeError("boom")):
            result = prov.get_candles("EURUSD", count=10)
        assert result == []


# ---------------------------------------------------------------------------
# 6. Integration: detect_for_user calls oanda_provider.get_candles
# ---------------------------------------------------------------------------

class TestDetectorCallsOanda:
    """Verify that SessionBreakDetector.detect_for_user() routes to OANDA."""

    def test_detect_for_user_uses_oanda_provider(self):
        """
        When detect_for_user is called with a candle_cache miss, it must
        call oanda_provider.get_candles(), not any Twelve Data method.
        """
        import services.session_break_detector as sbd
        from services.session_break_detector import SessionBreakDetector

        # Stub DB to return one symbol
        mock_db = MagicMock()
        mock_db.execute.return_value = [{"symbol": "EURUSD"}]

        captured_calls = []

        def fake_get_candles(symbol, count=500):
            captured_calls.append({"symbol": symbol, "count": count})
            return []  # no candles → nothing to process

        with patch.object(sbd.oanda_provider, "get_candles", side_effect=fake_get_candles):
            with patch.object(sbd, "db", mock_db):
                detector = SessionBreakDetector()
                detector.detect_for_user(
                    user_id=1,
                    user_email="test@example.com",
                    candle_cache={},
                    run_id="test-run",
                )

        assert len(captured_calls) == 1, (
            f"Expected 1 call to oanda_provider.get_candles, got {captured_calls}"
        )
        assert captured_calls[0]["symbol"] == "EURUSD"
        assert captured_calls[0]["count"] == 500
