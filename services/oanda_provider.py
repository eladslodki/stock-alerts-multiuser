"""
OANDA v20 candle provider for the Forex Sessions / Session Sweep feature.

Replaces Twelve Data as the candle source for ALL Forex Sessions
functionality: session tracking, sweep detection, replay, chart overlays,
alerts.  All other parts of the app (stocks, crypto, Yahoo Finance) are
unchanged.

Required env vars
-----------------
OANDA_API_KEY      Personal Access Token (v20 PAT)
OANDA_ACCOUNT_ID   Account ID (informational; stored in logs)
OANDA_ENV          "practice" (default) or "live"

Public interface
----------------
normalize_to_oanda(raw_symbol)
    → (instrument: str, None)  on success, e.g. ("EUR_USD", None)
    → (None, error_msg: str)   on failure

oanda_provider.get_candles(symbol_raw, count=500)
    → list of dicts, oldest → newest:
      {
          'timestamp': datetime (naive UTC, candle OPEN time),
          'open':      float,
          'high':      float,
          'low':       float,
          'close':     float,
          'volume':    float,
      }
    Returns [] on any error (never raises, never crashes the scheduler).

Logging tags
------------
[PROVIDER_ROUTE]  symbol routing info (one per call)
[OANDA_FEED]      successful fetch stats
[OANDA_ERROR]     any error (instrument, status, message)
"""

from __future__ import annotations

import logging
import os
import time as _time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

from services.forex_data_provider import normalize_symbol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OANDA REST API base URLs
# ---------------------------------------------------------------------------

_OANDA_URLS: Dict[str, str] = {
    "live":     "https://api-fxtrade.oanda.com/v3",
    "practice": "https://api-fxpractice.oanda.com/v3",
}

# OANDA returns a maximum of 5000 candles per request but recommends ≤500
_MAX_CANDLES_PER_REQUEST = 500

# Retry config (exponential back-off)
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECS = (1.0, 2.0, 4.0)

# HTTP status codes that are worth retrying
_RETRYABLE_STATUSES = frozenset({429, 503, 504})


# ---------------------------------------------------------------------------
# Symbol normalization  (public)
# ---------------------------------------------------------------------------

def normalize_to_oanda(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Normalize a user-supplied forex / metal symbol to the OANDA instrument
    format (underscore separator, e.g. EUR_USD, XAU_USD, GBP_JPY).

    Accepts the same input formats as ``normalize_symbol()``:
      EURUSD, EUR/USD, EUR-USD, EUR_USD, eurusd,
      XAUUSD, XAU/USD, XAU-USD, XAUUSD, …

    Returns
    -------
    (instrument, None)   on success – e.g. ("EUR_USD", None)
    (None, error_msg)    on failure – e.g. (None, "Invalid base currency …")
    """
    slash_form, err = normalize_symbol(raw)
    if err:
        return None, err
    # EUR/USD → EUR_USD
    instrument = slash_form.replace("/", "_")
    return instrument, None


# ---------------------------------------------------------------------------
# OANDA provider class
# ---------------------------------------------------------------------------

class OandaProvider:
    """
    Fetches M5 OHLC candles from the OANDA v20 REST API.
    Used exclusively by the Forex Sessions / Session Sweep feature.
    """

    def __init__(self) -> None:
        self.api_key: Optional[str] = os.getenv("OANDA_API_KEY")
        self.account_id: Optional[str] = os.getenv("OANDA_ACCOUNT_ID")

        _env_raw = (os.getenv("OANDA_ENV") or "practice").strip().lower()
        if _env_raw not in _OANDA_URLS:
            logger.warning(
                "[OANDA_ERROR] instrument=config status=invalid_env "
                "message=Unknown_OANDA_ENV=%r_defaulting_to_practice",
                _env_raw,
            )
            _env_raw = "practice"
        self.env: str = _env_raw
        self.base_url: str = _OANDA_URLS[_env_raw]

        if not self.api_key:
            logger.warning(
                "[OANDA_ERROR] instrument=config status=missing_api_key "
                "message=OANDA_API_KEY_not_set_Forex_Sessions_data_unavailable"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_candles(
        self,
        symbol_raw: str,
        count: int = 500,
    ) -> List[Dict]:
        """
        Fetch recent M5 OHLC candles from OANDA for the given symbol.

        Parameters
        ----------
        symbol_raw : user-supplied symbol in any supported format
                     (e.g. 'EURUSD', 'EUR/USD', 'XAU_USD', 'xauusd')
        count      : number of candles to fetch (capped at 500 per OANDA limit)

        Returns
        -------
        List of dicts ordered **oldest → newest**:

            {
                'timestamp': datetime (naive UTC, candle OPEN time),
                'open':  float,
                'high':  float,
                'low':   float,
                'close': float,
                'volume': float,
            }

        Returns [] on any error.  Never raises.
        """
        if not self.api_key:
            logger.error(
                "[OANDA_ERROR] instrument=%s status=no_api_key "
                "message=OANDA_API_KEY_not_set",
                symbol_raw,
            )
            return []

        # ── 1. Normalize symbol → OANDA instrument ────────────────────────
        instrument, norm_err = normalize_to_oanda(symbol_raw)
        if norm_err:
            logger.error(
                "[OANDA_ERROR] instrument=%s status=invalid_symbol message=%s",
                symbol_raw, norm_err,
            )
            return []

        logger.info(
            "[PROVIDER_ROUTE] symbol_raw=%s normalized=%s provider=OANDA instrument=%s",
            symbol_raw, instrument, instrument,
        )

        # ── 2. Fetch (with retry / back-off) ─────────────────────────────
        fetch_count = min(count, _MAX_CANDLES_PER_REQUEST)
        return self._fetch_with_retry(instrument, fetch_count)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_with_retry(self, instrument: str, count: int) -> List[Dict]:
        """Fetch OANDA candles with exponential-backoff retries."""
        url = f"{self.base_url}/instruments/{instrument}/candles"
        params = {
            "count":       count,
            "granularity": "M5",
            "price":       "M",   # mid-point of bid/ask
        }
        headers = {
            "Authorization":           f"Bearer {self.api_key}",
            "Content-Type":            "application/json",
            "Accept-Datetime-Format":  "RFC3339",
        }

        last_exc: Optional[Exception] = None

        for attempt in range(_MAX_RETRIES + 1):
            if attempt > 0:
                sleep_s = _RETRY_BACKOFF_SECS[min(attempt - 1, len(_RETRY_BACKOFF_SECS) - 1)]
                logger.info(
                    "[OANDA_FEED] instrument=%s retry=%d/%d sleeping=%.1fs",
                    instrument, attempt, _MAX_RETRIES, sleep_s,
                )
                _time.sleep(sleep_s)

            t0 = _time.monotonic()
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=15)
                elapsed_ms = int((_time.monotonic() - t0) * 1000)

                if resp.status_code in _RETRYABLE_STATUSES:
                    logger.warning(
                        "[OANDA_ERROR] instrument=%s status=%d "
                        "message=retryable_error elapsed_ms=%d",
                        instrument, resp.status_code, elapsed_ms,
                    )
                    last_exc = Exception(f"HTTP {resp.status_code}")
                    continue  # retry

                if resp.status_code != 200:
                    body_snippet = resp.text[:400]
                    logger.error(
                        "[OANDA_ERROR] instrument=%s status=%d message=%s elapsed_ms=%d",
                        instrument, resp.status_code, body_snippet, elapsed_ms,
                    )
                    return []  # non-retryable client error

                payload = resp.json()
                raw_candles = payload.get("candles", [])

                if not raw_candles:
                    logger.warning(
                        "[OANDA_FEED] instrument=%s granularity=M5 count=%d "
                        "candles=0 elapsed_ms=%d",
                        instrument, count, elapsed_ms,
                    )
                    return []

                # Parse + sort oldest→newest; skip incomplete (in-progress) bars
                parsed: List[Dict] = []
                for c in raw_candles:
                    if not c.get("complete", True):
                        continue
                    try:
                        parsed.append(self._parse_candle(c))
                    except Exception as parse_exc:
                        logger.warning(
                            "[OANDA_ERROR] instrument=%s status=parse_error "
                            "message=%s raw=%s",
                            instrument, parse_exc, c,
                        )
                parsed.sort(key=lambda c: c["timestamp"])

                first_ts = parsed[0]["timestamp"].isoformat() if parsed else None
                last_ts  = parsed[-1]["timestamp"].isoformat() if parsed else None
                first_c  = parsed[0]  if parsed else {}
                last_c   = parsed[-1] if parsed else {}

                logger.info(
                    "[OANDA_FEED] instrument=%s granularity=M5 count=%d "
                    "first_ts=%s last_ts=%s candles=%d elapsed_ms=%d",
                    instrument, count,
                    first_ts, last_ts,
                    len(parsed), elapsed_ms,
                )
                if parsed:
                    logger.info(
                        "[OANDA_FEED] first_candle O=%.5f H=%.5f L=%.5f C=%.5f  "
                        "last_candle O=%.5f H=%.5f L=%.5f C=%.5f",
                        first_c["open"], first_c["high"],
                        first_c["low"],  first_c["close"],
                        last_c["open"],  last_c["high"],
                        last_c["low"],   last_c["close"],
                    )

                return parsed

            except requests.exceptions.Timeout:
                elapsed_ms = int((_time.monotonic() - t0) * 1000)
                logger.warning(
                    "[OANDA_ERROR] instrument=%s status=timeout elapsed_ms=%d",
                    instrument, elapsed_ms,
                )
                last_exc = Exception("timeout")

            except requests.exceptions.RequestException as exc:
                elapsed_ms = int((_time.monotonic() - t0) * 1000)
                logger.error(
                    "[OANDA_ERROR] instrument=%s status=network_error "
                    "message=%s elapsed_ms=%d",
                    instrument, exc, elapsed_ms,
                )
                last_exc = exc

            except Exception as exc:
                logger.error(
                    "[OANDA_ERROR] instrument=%s status=unexpected_error message=%s",
                    instrument, exc,
                )
                return []  # non-retryable

        logger.error(
            "[OANDA_ERROR] instrument=%s status=max_retries_exceeded message=%s",
            instrument, last_exc,
        )
        return []

    # ------------------------------------------------------------------
    # Candle parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_candle(raw: Dict) -> Dict:
        """
        Parse one OANDA candle dict into the internal OHLC format.

        OANDA time format (RFC 3339 with nanoseconds, always UTC):
          "2024-01-15T09:00:00.000000000Z"

        This is the candle OPEN time (start of the 5-minute bar),
        matching the semantics of Twelve Data's "datetime" field.

        The parsed datetime is **naive UTC** (no tzinfo), consistent with
        the rest of the app's candle format.
        """
        ts_str: str = raw["time"]

        # Strip trailing 'Z' and truncate to at most 6 decimal places
        # "2024-01-15T09:00:00.000000000Z" → "2024-01-15T09:00:00.000000"
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1]
        if "." in ts_str:
            dot_idx = ts_str.index(".")
            # Keep up to 6 decimal digits (microseconds)
            ts_str = ts_str[: dot_idx + 7]

        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            # Last resort: drop fractional seconds entirely
            ts = datetime.fromisoformat(ts_str.split(".")[0])

        # Ensure naive (no tzinfo attached)
        ts = ts.replace(tzinfo=None)

        mid = raw.get("mid", {})
        return {
            "timestamp": ts,
            "open":      float(mid.get("o", 0)),
            "high":      float(mid.get("h", 0)),
            "low":       float(mid.get("l", 0)),
            "close":     float(mid.get("c", 0)),
            "volume":    float(raw.get("volume", 0) or 0),
        }


# ---------------------------------------------------------------------------
# Module-level singleton  (used by the detector, API endpoints, and CLI)
# ---------------------------------------------------------------------------

oanda_provider = OandaProvider()
