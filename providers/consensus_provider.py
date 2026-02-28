"""
Consensus Expectations Provider — Yahoo Finance.

Fetches analyst consensus estimates (EPS, Revenue, EBITDA) for a ticker.
Results are cached in-process for 24 hours to avoid hammering Yahoo Finance.

Public API
----------
get_consensus(ticker: str) -> dict
    Returns:
    {
      "eps_estimate":     float | None,
      "revenue_estimate": float | None,
      "ebitda_estimate":  float | None,
      "currency":         "USD",
      "source":           "yahoo" | "mock",
      "period":           "YYYY-MM-DD" | None,
    }
    Never raises — returns nulls on any failure.
"""

import logging
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_YAHOO_URL  = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
_MODULES    = "earningsTrend,financialData"
_TTL        = 86_400            # 24 hours
_CACHE: Dict[str, tuple] = {}  # ticker -> (data_dict, expires_at)
_HEADERS    = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; StockAlerts/1.0; "
        "+https://github.com/eladslodki/stock-alerts-multiuser)"
    ),
    "Accept": "application/json",
}


def _raw(node: Any, *keys: str) -> Optional[float]:
    """Safely dig into Yahoo Finance nested dicts and return .raw float."""
    cur = node
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    if isinstance(cur, dict):
        v = cur.get("raw")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    try:
        return float(cur) if cur is not None else None
    except (TypeError, ValueError):
        return None


def _fetch_yahoo(ticker: str) -> dict:
    """
    Hit Yahoo Finance quoteSummary and parse consensus data.
    Returns a dict matching the public schema.
    """
    url    = _YAHOO_URL.format(ticker=ticker.upper())
    params = {"modules": _MODULES, "crumb": ""}

    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        logger.warning("Yahoo Finance fetch failed for %s: %s", ticker, exc)
        return _null_consensus()

    try:
        result = (body.get("quoteSummary") or {}).get("result") or []
        if not result:
            return _null_consensus()
        data = result[0]

        # ---- earningsTrend: current-quarter estimates (period "0q") --------
        eps_est = None
        rev_est = None
        period  = None
        trend_list = (data.get("earningsTrend") or {}).get("trend") or []
        for entry in trend_list:
            if entry.get("period") in ("0q", "+1q"):
                eps_est = _raw(entry, "earningsEstimate", "avg")
                rev_est = _raw(entry, "revenueEstimate",  "avg")
                period  = entry.get("endDate")
                break

        # ---- financialData: EBITDA (trailing, used as proxy for estimate) --
        fin      = data.get("financialData") or {}
        ebitda_e = _raw(fin, "ebitda")    # trailing EBITDA — best proxy

        return {
            "eps_estimate":     eps_est,
            "revenue_estimate": rev_est,
            "ebitda_estimate":  ebitda_e,
            "currency":         "USD",
            "source":           "yahoo",
            "period":           period,
        }
    except Exception as exc:
        logger.warning("Yahoo Finance parse error for %s: %s", ticker, exc)
        return _null_consensus()


def _null_consensus(source: str = "yahoo") -> dict:
    return {
        "eps_estimate":     None,
        "revenue_estimate": None,
        "ebitda_estimate":  None,
        "currency":         "USD",
        "source":           source,
        "period":           None,
    }


def get_consensus(ticker: str) -> dict:
    """
    Return analyst consensus estimates for *ticker*, cached for 24 h.
    Never raises.
    """
    ticker = ticker.upper().strip()
    now    = time.time()

    if ticker in _CACHE:
        data, expires_at = _CACHE[ticker]
        if now < expires_at:
            logger.debug("Consensus cache HIT for %s", ticker)
            return data

    logger.info("Fetching consensus for %s from Yahoo Finance", ticker)
    data = _fetch_yahoo(ticker)
    _CACHE[ticker] = (data, now + _TTL)
    return data


def invalidate_cache(ticker: str) -> None:
    """Force-expire a cached entry (useful in tests)."""
    _CACHE.pop(ticker.upper().strip(), None)
