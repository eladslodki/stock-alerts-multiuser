"""
Unit tests for normalize_symbol() in services/forex_data_provider.py

Run with:
    cd /path/to/stock-alerts-multiuser
    python -m pytest tests/test_symbol_normalization.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from services.forex_data_provider import normalize_symbol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ok(raw, expected):
    """Assert normalize_symbol(raw) == (expected, None)."""
    result, err = normalize_symbol(raw)
    assert err is None, f"Unexpected error for {raw!r}: {err}"
    assert result == expected, f"normalize_symbol({raw!r}) = {result!r}, want {expected!r}"


def fail(raw):
    """Assert normalize_symbol(raw) returns (None, <some-error-string>)."""
    result, err = normalize_symbol(raw)
    assert result is None, f"Expected failure for {raw!r} but got result={result!r}"
    assert err and isinstance(err, str), f"Expected non-empty error string for {raw!r}"


# ---------------------------------------------------------------------------
# ── Positive: compact 6-char formats ─────────────────────────────────────
# ---------------------------------------------------------------------------

class TestCompactFormat:
    def test_eurusd_lower(self):     ok("eurusd",   "EUR/USD")
    def test_eurusd_upper(self):     ok("EURUSD",   "EUR/USD")
    def test_xauusd_lower(self):     ok("xauusd",   "XAU/USD")
    def test_xauusd_upper(self):     ok("XAUUSD",   "XAU/USD")
    def test_gbpjpy(self):           ok("GBPJPY",   "GBP/JPY")
    def test_usdjpy(self):           ok("USDJPY",   "USD/JPY")
    def test_xagusd(self):           ok("xagusd",   "XAG/USD")
    def test_audusd(self):           ok("audusd",   "AUD/USD")
    def test_usdchf(self):           ok("USDCHF",   "USD/CHF")
    def test_nzdusd(self):           ok("NZDUSD",   "NZD/USD")


# ---------------------------------------------------------------------------
# ── Positive: slash-separated formats ────────────────────────────────────
# ---------------------------------------------------------------------------

class TestSlashFormat:
    def test_eur_usd_slash(self):    ok("EUR/USD",  "EUR/USD")
    def test_xau_usd_slash(self):    ok("XAU/USD",  "XAU/USD")
    def test_lower_slash(self):      ok("eur/usd",  "EUR/USD")
    def test_spaces_around_slash(self): ok("EUR / USD", "EUR/USD")
    def test_usd_jpy_slash(self):    ok("USD/JPY",  "USD/JPY")


# ---------------------------------------------------------------------------
# ── Positive: dash / underscore / space separators ───────────────────────
# ---------------------------------------------------------------------------

class TestSeparatorFormats:
    def test_eur_dash_usd(self):     ok("EUR-USD",  "EUR/USD")
    def test_xau_dash_usd(self):     ok("XAU-USD",  "XAU/USD")
    def test_eur_underscore(self):   ok("EUR_USD",  "EUR/USD")
    def test_xau_underscore(self):   ok("XAU_USD",  "XAU/USD")
    def test_usd_space_jpy(self):    ok("USD JPY",  "USD/JPY")
    def test_usd_space_jpy_lower(self): ok("usd jpy", "USD/JPY")
    def test_mixed_case_dash(self):  ok("Xau-Usd",  "XAU/USD")


# ---------------------------------------------------------------------------
# ── Positive: leading/trailing whitespace ────────────────────────────────
# ---------------------------------------------------------------------------

class TestWhitespace:
    def test_leading_spaces(self):   ok("  EURUSD",  "EUR/USD")
    def test_trailing_spaces(self):  ok("EURUSD  ",  "EUR/USD")
    def test_both_spaces(self):      ok(" EUR/USD ", "EUR/USD")


# ---------------------------------------------------------------------------
# ── Negative: empty / None ───────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestEmpty:
    def test_empty_string(self):     fail("")
    def test_spaces_only(self):      fail("   ")
    def test_none_type(self):        fail(None)


# ---------------------------------------------------------------------------
# ── Negative: structural failures ────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestStructuralFailures:
    def test_too_short_no_sep(self):       fail("EUUS")       # 4 chars
    def test_too_long_no_sep(self):        fail("EURUSDX")    # 7 chars
    def test_numeric_in_code(self):        fail("EU1USD")     # digits
    def test_same_base_quote(self):        fail("USDUSD")     # base == quote
    def test_same_slash(self):             fail("USD/USD")    # base == quote via /
    def test_bad_slash_format_one_part(self): fail("EURUSD/") # empty quote
    def test_bad_slash_format_three(self): fail("EUR/USD/CHF")  # >1 slash

    def test_base_too_short_slash(self):
        """Slash format with 2-char base → structural failure."""
        result, err = normalize_symbol("EU/USD")
        assert result is None
        assert err is not None


# ---------------------------------------------------------------------------
# ── Negative: unknown currency codes ─────────────────────────────────────
# ---------------------------------------------------------------------------

class TestUnknownCurrency:
    def test_unknown_base(self):      fail("ABCUSD")
    def test_unknown_quote(self):     fail("USDXYZ")
    def test_both_unknown(self):      fail("ABCXYZ")
    def test_unknown_slash(self):     fail("ABC/USD")


# ---------------------------------------------------------------------------
# ── Return-value contract ────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestReturnContract:
    def test_success_returns_tuple_two(self):
        result = normalize_symbol("EURUSD")
        assert isinstance(result, tuple) and len(result) == 2

    def test_success_error_is_none(self):
        _, err = normalize_symbol("EURUSD")
        assert err is None

    def test_failure_result_is_none(self):
        result, _ = normalize_symbol("BADXXX")
        assert result is None

    def test_failure_error_is_str(self):
        _, err = normalize_symbol("BADXXX")
        assert isinstance(err, str) and len(err) > 0
