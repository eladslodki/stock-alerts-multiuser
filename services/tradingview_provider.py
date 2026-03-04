"""
TradingView (Pepperstone) candle provider for the Forex Sessions / Session Sweep feature.

Uses tvdatafeed to fetch M5 OHLC candles from TradingView's PEPPERSTONE feed
so prices exactly match the TradingView PEPPERSTONE chart and alerts are
anchored to the same price data the user sees.

All other parts of the app (stocks, crypto, Yahoo Finance) are unchanged.

Optional env vars
-----------------
TV_USERNAME   TradingView username  (omit to use anonymous mode)
TV_PASSWORD   TradingView password  (omit to use anonymous mode)

Public interface
----------------
normalize_to_tv(raw_symbol)
    → (tv_symbol: str, None)   on success, e.g. ("EURUSD", None)
    → (None, error_msg: str)   on failure

tradingview_provider.get_candles(symbol_raw, count=500)
    → list of dicts, oldest → newest:
      {
          'timestamp': datetime (naive UTC, candle OPEN time),
          'open':      float,
          'high':      float,
          'low':       float,
          'close':     float,
          'volume':    float,
      }
    Returns [] on any error.  Never raises, never crashes the scheduler.

Logging tags
------------
[PROVIDER_ROUTE]  emitted once per call – symbol routing decision
[TV_FETCH]        emitted on successful fetch (count, timestamps, elapsed)
[TV_ERROR]        emitted on any error (symbol, error detail)
"""

from __future__ import annotations

import logging
import os
import time as _time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from services.forex_data_provider import normalize_symbol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TV_EXCHANGE = "PEPPERSTONE"

# Retry config
_MAX_RETRIES    = 2
_RETRY_BACKOFF  = (2.0, 4.0)   # seconds between attempts


# ---------------------------------------------------------------------------
# Symbol normalisation (public)
# ---------------------------------------------------------------------------

def normalize_to_tv(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Normalize a user-supplied forex / metal symbol to TradingView compact format.

    TradingView / Pepperstone use 6-char compact uppercase symbols with no
    separators: EURUSD, XAUUSD, GBPJPY, USDJPY …

    Accepts the same input formats as normalize_symbol():
      EURUSD, EUR/USD, EUR-USD, EUR_USD, eurusd,
      XAUUSD, XAU/USD, XAU-USD, xauusd, …

    Returns
    -------
    (tv_symbol, None)   on success – e.g. ("EURUSD", None)
    (None, error_msg)   on failure – e.g. (None, "Invalid base currency …")
    """
    slash_form, err = normalize_symbol(raw)
    if err:
        return None, err
    # EUR/USD → EURUSD  (strip the slash)
    tv_symbol = slash_form.replace("/", "")
    return tv_symbol, None


# ---------------------------------------------------------------------------
# TvDatafeed client initialisation (lazy – called once at import time)
# ---------------------------------------------------------------------------

def _build_client():
    """
    Build and return a TvDatafeed client, or None on failure.

    Uses anonymous mode when TV_USERNAME / TV_PASSWORD are not set.
    Anonymous mode works for most forex symbols but may hit rate limits
    faster; providing credentials is recommended for production.
    """
    try:
        from tvDatafeed import TvDatafeed  # noqa: PLC0415
    except ImportError as exc:
        logger.error(
            "[TV_ERROR] tv=config error=tvdatafeed_not_installed "
            "message=%s  Install with: pip install tvdatafeed",
            exc,
        )
        return None

    username = (os.getenv("TV_USERNAME") or "").strip()
    password = (os.getenv("TV_PASSWORD") or "").strip()

    try:
        if username and password:
            client = TvDatafeed(username=username, password=password)
            logger.info("[TV_FEED] Authenticated as TradingView user=%s", username)
        else:
            client = TvDatafeed()
            logger.warning(
                "[TV_FEED] TV_USERNAME/TV_PASSWORD not set – using anonymous mode. "
                "Set these env vars to avoid rate-limiting."
            )
        return client
    except Exception as exc:
        logger.error(
            "[TV_ERROR] tv=config error=client_init_failed message=%s", exc
        )
        return None


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------

class TradingViewProvider:
    """
    Fetches M5 OHLC candles from TradingView PEPPERSTONE feed via tvdatafeed.
    Used exclusively by the Forex Sessions / Session Sweep feature.
    """

    def __init__(self) -> None:
        self._client = _build_client()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_candles(
        self,
        symbol_raw: str,
        count: int = 500,
    ) -> List[Dict]:
        """
        Fetch recent M5 OHLC candles from TradingView PEPPERSTONE.

        Parameters
        ----------
        symbol_raw : user-supplied symbol in any supported format
                     (e.g. 'EURUSD', 'EUR/USD', 'XAU_USD', 'xauusd')
        count      : number of candles (n_bars passed to tvdatafeed)

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
        if self._client is None:
            logger.error(
                "[TV_ERROR] tv=%s:%s error=client_not_initialized",
                _TV_EXCHANGE, symbol_raw,
            )
            return []

        # ── 1. Normalize symbol → TradingView compact format ─────────────
        tv_symbol, norm_err = normalize_to_tv(symbol_raw)
        if norm_err:
            logger.error(
                "[TV_ERROR] tv=%s:%s error=invalid_symbol message=%s",
                _TV_EXCHANGE, symbol_raw, norm_err,
            )
            return []

        logger.info(
            "[PROVIDER_ROUTE] provider=TRADINGVIEW symbol_raw=%s "
            "tv_exchange=%s tv_symbol=%s",
            symbol_raw, _TV_EXCHANGE, tv_symbol,
        )

        # ── 2. Fetch (with retry / back-off) ─────────────────────────────
        return self._fetch_with_retry(tv_symbol, count)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_with_retry(self, tv_symbol: str, count: int) -> List[Dict]:
        """Fetch candles with exponential-backoff retries."""
        last_exc: Optional[Exception] = None

        for attempt in range(_MAX_RETRIES + 1):
            if attempt > 0:
                sleep_s = _RETRY_BACKOFF[min(attempt - 1, len(_RETRY_BACKOFF) - 1)]
                logger.info(
                    "[TV_FETCH] tv=%s:%s retry=%d/%d sleeping=%.1fs",
                    _TV_EXCHANGE, tv_symbol, attempt, _MAX_RETRIES, sleep_s,
                )
                _time.sleep(sleep_s)

            t0 = _time.monotonic()
            try:
                from tvDatafeed import Interval  # noqa: PLC0415
                df = self._client.get_hist(
                    symbol   = tv_symbol,
                    exchange = _TV_EXCHANGE,
                    interval = Interval.in_5_minute,
                    n_bars   = count,
                )
                elapsed_ms = int((_time.monotonic() - t0) * 1000)

                if df is None or df.empty:
                    logger.warning(
                        "[TV_FETCH] tv=%s:%s interval=5m requested=%d returned=0 "
                        "elapsed_ms=%d",
                        _TV_EXCHANGE, tv_symbol, count, elapsed_ms,
                    )
                    return []

                candles = self._parse_df(df)
                candles = self._drop_incomplete(candles)

                first_ts = candles[0]["timestamp"].isoformat()  if candles else None
                last_ts  = candles[-1]["timestamp"].isoformat() if candles else None

                logger.info(
                    "[TV_FETCH] tv=%s:%s interval=5m requested=%d returned=%d "
                    "first_ts=%s last_ts=%s elapsed_ms=%d",
                    _TV_EXCHANGE, tv_symbol, count, len(candles),
                    first_ts, last_ts, elapsed_ms,
                )
                return candles

            except Exception as exc:
                elapsed_ms = int((_time.monotonic() - t0) * 1000)
                logger.warning(
                    "[TV_ERROR] tv=%s:%s error=%s elapsed_ms=%d",
                    _TV_EXCHANGE, tv_symbol, exc, elapsed_ms,
                )
                last_exc = exc

        logger.error(
            "[TV_ERROR] tv=%s:%s error=max_retries_exceeded last_error=%s",
            _TV_EXCHANGE, tv_symbol, last_exc,
        )
        return []

    # ------------------------------------------------------------------
    # DataFrame → candle list
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_df(df) -> List[Dict]:
        """
        Convert a tvdatafeed DataFrame to the internal candle list format.

        tvdatafeed's DatetimeIndex represents the candle OPEN time in UTC,
        matching what TradingView shows for each bar on the chart.
        Candles are returned sorted oldest → newest.
        """
        candles: List[Dict] = []
        for ts, row in df.iterrows():
            # Normalise to naive UTC regardless of tvdatafeed version
            if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
                try:
                    from datetime import timezone as _tz
                    ts_naive = ts.astimezone(_tz.utc).replace(tzinfo=None)
                except Exception:
                    ts_naive = ts.replace(tzinfo=None)
            else:
                ts_naive = ts.to_pydatetime().replace(tzinfo=None)

            candles.append({
                "timestamp": ts_naive,
                "open":      float(row["open"]),
                "high":      float(row["high"]),
                "low":       float(row["low"]),
                "close":     float(row["close"]),
                "volume":    float(row.get("volume", 0) or 0),
            })

        candles.sort(key=lambda c: c["timestamp"])
        return candles

    @staticmethod
    def _drop_incomplete(candles: List[Dict]) -> List[Dict]:
        """
        Drop the most recent candle if it is the currently-forming 5-minute bar.

        Safe rule: if the last candle's timestamp >= floor(utcnow, 5 min),
        that bar is still in progress and must be dropped to avoid using
        a partial high/low in the session sweep calculation.
        """
        if not candles:
            return candles

        now_utc      = datetime.utcnow()
        bucket_min   = (now_utc.minute // 5) * 5
        current_bucket = now_utc.replace(minute=bucket_min, second=0, microsecond=0)

        if candles[-1]["timestamp"] >= current_bucket:
            logger.debug(
                "[TV_FETCH] dropping_incomplete_candle ts=%s current_bucket=%s",
                candles[-1]["timestamp"].isoformat(),
                current_bucket.isoformat(),
            )
            return candles[:-1]

        return candles


# ---------------------------------------------------------------------------
# Module-level singleton  (shared across all callers in this process)
# ---------------------------------------------------------------------------

tradingview_provider = TradingViewProvider()
