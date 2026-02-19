"""
Forex data provider - fetches OHLC candles from Twelve Data.
Used exclusively by the Forex AMD feature; all other parts of the
app (stocks, crypto, alerts, portfolio, scanners) continue to use
Yahoo Finance unchanged.
"""

import os
import requests
import logging
import time as _time
from datetime import datetime
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known currency / commodity codes (used for whitelist validation)
# ---------------------------------------------------------------------------

KNOWN_CURRENCIES: frozenset = frozenset({
    # G10 / Majors
    "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD",
    # Other liquid FX
    "SGD", "HKD", "SEK", "NOK", "DKK", "MXN", "ZAR", "TRY",
    "PLN", "CZK", "HUF", "INR", "BRL", "KRW", "CNH", "CNY",
    # Precious metals (ISO 4217 commodity codes)
    "XAU", "XAG", "XPT", "XPD",
})


# ---------------------------------------------------------------------------
# Symbol normalisation (public)
# ---------------------------------------------------------------------------

def normalize_symbol(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Robustly normalize a forex/metal symbol to Twelve Data ``BASE/QUOTE`` format.

    Accepted input formats (all case-insensitive):
    - ``EURUSD``, ``eurusd``          → ``EUR/USD``
    - ``XAU-USD``, ``XAU_USD``        → ``XAU/USD``
    - ``USD JPY``, ``usd jpy``        → ``USD/JPY``
    - ``EUR/USD``, ``EUR / USD``      → ``EUR/USD``

    Returns
    -------
    (normalized, None)   on success, e.g. ("EUR/USD", None)
    (None, error_msg)    on failure, e.g. (None, "Invalid base currency …")
    """
    if not raw or not isinstance(raw, str):
        return None, "Symbol is required"

    s = raw.upper().strip()
    if not s:
        return None, "Symbol is required"

    # --- Step 1: split into base / quote ---
    if "/" in s:
        parts = [p.strip() for p in s.split("/", 1)]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return None, f"Invalid format '{raw}': use BASE/QUOTE (e.g. EUR/USD)"
        base, quote = parts[0], parts[1]
    else:
        # Remove common separators: dash, underscore, space
        cleaned = s.replace("-", "").replace("_", "").replace(" ", "")
        if len(cleaned) != 6:
            return (
                None,
                f"Cannot parse '{raw}': expected 6-char compact (EURUSD) "
                f"or separated (EUR-USD, EUR_USD, EUR/USD)",
            )
        base, quote = cleaned[:3], cleaned[3:]

    # --- Step 2: structural validation ---
    if not base.isalpha() or len(base) != 3:
        return None, f"Invalid base currency '{base}': must be exactly 3 letters"
    if not quote.isalpha() or len(quote) != 3:
        return None, f"Invalid quote currency '{quote}': must be exactly 3 letters"
    if base == quote:
        return None, f"Base and quote currencies cannot be the same ({base})"

    # --- Step 3: whitelist validation ---
    unknown = [c for c in (base, quote) if c not in KNOWN_CURRENCIES]
    if unknown:
        supported = "USD EUR GBP JPY CHF AUD NZD CAD XAU XAG (and others)"
        return (
            None,
            f"Unrecognized currency code(s): {', '.join(unknown)}. "
            f"Supported: {supported}",
        )

    return f"{base}/{quote}", None


# ---------------------------------------------------------------------------
# Internal helper kept for backward-compat with existing callers
# ---------------------------------------------------------------------------

def _normalise_symbol(symbol: str) -> str:
    """
    Internal wrapper used by ForexDataProvider.  Delegates to the public
    ``normalize_symbol`` and falls back to the raw (uppercased) string on
    parse failure so the API can return a proper error message.
    """
    normalized, _err = normalize_symbol(symbol)
    if normalized:
        return normalized
    # Fallback: uppercase + strip so the Twelve Data call fails gracefully
    return symbol.upper().strip()


# ---------------------------------------------------------------------------
# Twelve Data interval mapping
# ---------------------------------------------------------------------------

_TIMEFRAME_MAP = {
    "5m":  "5min",
    "15m": "15min",
    "1h":  "1h",
    # allow caller to pass Twelve Data keys directly
    "5min":  "5min",
    "15min": "15min",
}


class ForexDataProvider:
    """Fetches OHLC candle data from Twelve Data for the Forex AMD feature."""

    BASE_URL = "https://api.twelvedata.com/time_series"

    def __init__(self):
        self.api_key: Optional[str] = os.getenv("TWELVEDATA_API_KEY")
        if not self.api_key:
            logger.warning(
                "TWELVEDATA_API_KEY not set – Forex AMD data will be unavailable"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_recent_candles(
        self,
        symbol: str,
        timeframe: str = "15m",
        count: int = 100,
    ) -> List[Dict]:
        """
        Fetch recent OHLC candles from Twelve Data.

        Parameters
        ----------
        symbol    : compact symbol, e.g. ``EURUSD`` or ``XAUUSD``
        timeframe : ``'5m'``, ``'15m'``, or ``'1h'``
        count     : number of candles to return (max 5000 on paid plans)

        Returns
        -------
        List of dicts ordered **oldest → newest**::

            [
                {
                    'timestamp': datetime,
                    'open': float,
                    'high': float,
                    'low': float,
                    'close': float,
                    'volume': float,
                },
                ...
            ]
        """
        if not self.api_key:
            logger.error("Cannot fetch forex candles: TWELVEDATA_API_KEY not set")
            return []

        td_symbol = _normalise_symbol(symbol)
        interval = _TIMEFRAME_MAP.get(timeframe, timeframe)

        params = {
            "symbol":     td_symbol,
            "interval":   interval,
            "outputsize": count,
            "apikey":     self.api_key,
            "format":     "JSON",
            "order":      "ASC",   # oldest first
        }

        _log_ctx = f"[AMD_FOREX][TD] symbol={td_symbol} interval={interval} count={count}"
        logger.debug("%s request_start", _log_ctx)
        _t0 = _time.monotonic()

        try:
            resp = requests.get(
                self.BASE_URL,
                params=params,
                timeout=15,
            )
            _elapsed_ms = int((_time.monotonic() - _t0) * 1000)
            resp.raise_for_status()
            payload = resp.json()

            if payload.get("status") == "error":
                msg = payload.get("message", "unknown")
                _is_rate_limit = "rate" in msg.lower() or "limit" in msg.lower() or "credit" in msg.lower()
                _is_invalid    = "invalid" in msg.lower() or "not found" in msg.lower()
                if _is_rate_limit:
                    logger.warning("%s rate_limit msg=%s elapsed_ms=%d", _log_ctx, msg, _elapsed_ms)
                elif _is_invalid:
                    logger.warning("%s invalid_symbol msg=%s elapsed_ms=%d", _log_ctx, msg, _elapsed_ms)
                else:
                    logger.error("%s api_error msg=%s elapsed_ms=%d", _log_ctx, msg, _elapsed_ms)
                return []

            values = payload.get("values", [])
            if not values:
                logger.warning("%s no_candles elapsed_ms=%d", _log_ctx, _elapsed_ms)
                return []

            logger.debug(
                "%s response_ok candles=%d elapsed_ms=%d",
                _log_ctx, len(values), _elapsed_ms,
            )
            return [self._parse_candle(c) for c in values]

        except requests.exceptions.Timeout:
            _elapsed_ms = int((_time.monotonic() - _t0) * 1000)
            logger.error("%s timeout elapsed_ms=%d", _log_ctx, _elapsed_ms)
            return []
        except requests.exceptions.RequestException as exc:
            _elapsed_ms = int((_time.monotonic() - _t0) * 1000)
            logger.error("%s http_error err=%s elapsed_ms=%d", _log_ctx, exc, _elapsed_ms)
            return []
        except Exception as exc:
            logger.error("%s unexpected_error err=%s", _log_ctx, exc)
            return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_candle(raw: Dict) -> Dict:
        """Convert a raw Twelve Data candle dict to the internal format."""
        return {
            "timestamp": datetime.strptime(raw["datetime"], "%Y-%m-%d %H:%M:%S"),
            "open":      float(raw["open"]),
            "high":      float(raw["high"]),
            "low":       float(raw["low"]),
            "close":     float(raw["close"]),
            "volume":    float(raw.get("volume", 0) or 0),
        }


# Module-level singleton used by forex_amd_detector
forex_data_provider = ForexDataProvider()
