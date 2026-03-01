"""
SEC EDGAR data provider.

Responsibilities
----------------
- ticker → CIK resolution
- List 10-Q / 10-K filings for a company
- Fetch filing HTML / text content

All network calls go to:
  https://data.sec.gov  (EDGAR submissions & data)
  https://www.sec.gov   (filing documents)

SEC requires a User-Agent header with your app name and email.
Set SEC_USER_AGENT env var, e.g.:
  SEC_USER_AGENT="MyApp/1.0 contact@example.com"
"""
import codecs
import io
import os
import re
import time
import logging
from typing import Optional, List, Dict, Any

import requests

# Hard network cap for filing content downloads.
# 2.5 MB is enough to capture all key narrative sections (MD&A, Risk Factors,
# Outlook) from any 10-Q/10-K while staying well within RAM constraints.
MAX_FILING_BYTES = int(os.getenv("SEC_MAX_FILING_BYTES", str(2_500_000)))

logger = logging.getLogger(__name__)

SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "StockAlertsApp/1.0 admin@stockalerts.app"
)
EDGAR_API_BASE  = "https://data.sec.gov"
EDGAR_DOC_BASE  = "https://www.sec.gov"
TICKERS_JSON    = f"{EDGAR_DOC_BASE}/files/company_tickers.json"

# --------------------------------------------------------------------------- #
# Shared session
# --------------------------------------------------------------------------- #
_session = requests.Session()
_session.headers.update({
    "User-Agent": SEC_USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json, text/html, */*",
})

_RETRIES = 3
_BACKOFF  = [1.5, 3.0, 6.0]


def _get(
    url: str,
    *,
    as_json: bool = True,
    timeout: tuple = (10, 30),  # (connect_s, read_s)
) -> Any:
    """GET with automatic retry / backoff. Raises RuntimeError on failure."""
    last_exc: Exception = RuntimeError("Unknown error")
    for attempt in range(_RETRIES):
        try:
            logger.debug("SEC GET attempt %d/%d: %s", attempt + 1, _RETRIES, url)
            resp = _session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.json() if as_json else resp
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            logger.warning("SEC GET HTTP %d (attempt %d): %s", status, attempt + 1, url)
            if status == 404:
                raise RuntimeError(f"SEC returned 404 for {url}") from exc
            last_exc = exc
        except requests.exceptions.Timeout as exc:
            logger.warning("SEC GET timeout (attempt %d): %s — %s", attempt + 1, url, exc)
            last_exc = exc
        except requests.exceptions.RequestException as exc:
            logger.warning("SEC GET %s (attempt %d): %s — %s",
                           type(exc).__name__, attempt + 1, url, exc)
            last_exc = exc

        if attempt < _RETRIES - 1:
            time.sleep(_BACKOFF[attempt])

    raise RuntimeError(
        f"SEC EDGAR unavailable after {_RETRIES} attempts: {last_exc}"
    ) from last_exc


# --------------------------------------------------------------------------- #
# CIK resolution
# --------------------------------------------------------------------------- #
_CIK_CACHE: Dict[str, str] = {}

# Cache for list_filings results.
# The submissions JSON for large companies is 1–3 MB; re-downloading it inside
# _generate_inner (called seconds after the user's /api/filings search) spikes
# memory by 4–8 MB at the exact moment the baseline is already high.
# A 5-minute TTL covers the normal search→click→generate user flow.
_FILINGS_CACHE: Dict[str, Dict] = {}   # ticker_upper -> {"ts": float, "data": list}
_FILINGS_CACHE_TTL = 300               # seconds


def ticker_to_cik(ticker: str) -> Optional[str]:
    """
    Resolve a ticker symbol to a zero-padded 10-digit CIK string.
    Returns None if not found.
    """
    ticker_upper = ticker.upper().strip()
    if ticker_upper in _CIK_CACHE:
        return _CIK_CACHE[ticker_upper]

    try:
        data = _get(TICKERS_JSON)
    except RuntimeError as exc:
        logger.error("ticker_to_cik: cannot fetch tickers list: %s", exc)
        return None

    for entry in data.values():
        if entry.get("ticker", "").upper() == ticker_upper:
            cik = str(entry["cik_str"]).zfill(10)
            _CIK_CACHE[ticker_upper] = cik
            logger.info("Resolved %s → CIK %s", ticker_upper, cik)
            return cik

    logger.warning("ticker_to_cik: %s not found in SEC tickers list", ticker_upper)
    return None


def get_company_info(cik: str) -> Dict[str, str]:
    """Return company name and primary exchange from EDGAR submissions."""
    try:
        data = _get(f"{EDGAR_API_BASE}/submissions/CIK{cik}.json")
        exchanges = data.get("exchanges") or []
        return {
            "name":     data.get("name", ""),
            "exchange": exchanges[0] if exchanges else "",
            "cik":      cik,
        }
    except RuntimeError as exc:
        logger.error("get_company_info(%s): %s", cik, exc)
        return {"name": "", "exchange": "", "cik": cik}


# --------------------------------------------------------------------------- #
# Filing list
# --------------------------------------------------------------------------- #
def list_filings(
    ticker: str,
    form_types: Optional[List[str]] = None,
    max_results: int = 20,
) -> List[Dict[str, Any]]:
    """
    Return up to *max_results* recent 10-Q / 10-K filings for *ticker*.

    Each item in the returned list contains:
        filing_id       – accession number with dashes  (e.g. "0000012345-24-000010")
        filing_type     – "10-Q" or "10-K"
        period_end      – "YYYY-MM-DD" or ""
        filed_at        – "YYYY-MM-DD"
        source_url      – direct URL to primary document
        title           – human-readable label
        cik             – zero-padded CIK
        company_name    – company display name
        exchange        – primary exchange
    """
    if form_types is None:
        form_types = ["10-Q", "10-K"]

    ticker_upper = ticker.upper().strip()

    # Return cached result if fresh — avoids re-downloading the submissions JSON
    # when generate is called shortly after the user's filing search.
    cached = _FILINGS_CACHE.get(ticker_upper)
    if cached and (time.time() - cached["ts"]) < _FILINGS_CACHE_TTL:
        logger.debug("list_filings: cache hit for %s", ticker_upper)
        return cached["data"]

    cik = ticker_to_cik(ticker)
    if not cik:
        raise ValueError(f"Cannot resolve ticker '{ticker}' to a CIK number.")

    try:
        data = _get(f"{EDGAR_API_BASE}/submissions/CIK{cik}.json")
    except RuntimeError as exc:
        raise RuntimeError(f"SEC EDGAR unavailable: {exc}") from exc

    company_name = data.get("name", "")
    exchanges    = data.get("exchanges") or []
    exchange     = exchanges[0] if exchanges else ""

    recent = data.get("filings", {}).get("recent", {})
    if not recent:
        return []

    forms        = recent.get("form", [])
    accessions   = recent.get("accessionNumber", [])
    filed_dates  = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])

    results: List[Dict[str, Any]] = []
    cik_int = int(cik)

    for i, form in enumerate(forms):
        if form not in form_types:
            continue

        accession   = accessions[i]   if i < len(accessions)   else ""
        filed_date  = filed_dates[i]  if i < len(filed_dates)  else ""
        report_date = report_dates[i] if i < len(report_dates) else ""
        primary_doc = primary_docs[i] if i < len(primary_docs) else ""

        # Build document URL (remove dashes for directory path)
        accession_nodash = accession.replace("-", "")
        source_url = (
            f"{EDGAR_DOC_BASE}/Archives/edgar/data/{cik_int}"
            f"/{accession_nodash}/{primary_doc}"
            if primary_doc else ""
        )

        results.append({
            "filing_id":    accession,
            "filing_type":  form,
            "period_end":   report_date,
            "filed_at":     filed_date,
            "source_url":   source_url,
            "title":        f"{form} — {report_date or filed_date}",
            "cik":          cik,
            "company_name": company_name,
            "exchange":     exchange,
        })

        if len(results) >= max_results:
            break

    _FILINGS_CACHE[ticker_upper] = {"ts": time.time(), "data": results}
    return results


# --------------------------------------------------------------------------- #
# Filing content
# --------------------------------------------------------------------------- #
def fetch_filing_content(source_url: str) -> Dict[str, str]:
    """
    Download the primary filing document, capped at MAX_FILING_BYTES.

    Streams the response and decodes each chunk incrementally into a StringIO
    buffer.  This avoids holding both the raw bytes list AND the joined/decoded
    string in memory simultaneously (which was 2× the filing size at peak).

    Returns a dict with keys:
        html  – raw HTML string (may be empty)
        text  – plain-text string (may be empty)

    Raises RuntimeError if the download fails.
    """
    if not source_url:
        return {"html": "", "text": ""}

    # (connect_timeout=10s, read_timeout=60s per chunk)
    logger.info("FETCH begin: url=%s", source_url)
    resp = None
    try:
        try:
            resp = _session.get(source_url, timeout=(10, 60), stream=True)
            resp.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise RuntimeError(
                f"SEC filing fetch timed out ({type(exc).__name__}): {source_url}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(
                f"Cannot fetch filing document ({type(exc).__name__}): {exc}"
            ) from exc

        content_type   = resp.headers.get("content-type", "").lower()
        content_length = resp.headers.get("content-length", "unknown")
        logger.info(
            "FETCH headers: status=%d content-type=%r content-length=%s url=%s",
            resp.status_code, content_type, content_length, source_url,
        )

        # Decode each 64 KB chunk into StringIO immediately — avoids the
        # bytes-list → joined-bytes → decoded-str triple allocation.
        decoder   = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buf       = io.StringIO()
        total     = 0
        truncated = False

        for chunk in resp.iter_content(chunk_size=65_536):
            buf.write(decoder.decode(chunk, final=False))
            total += len(chunk)
            if total >= MAX_FILING_BYTES:
                truncated = True
                break

        buf.write(decoder.decode(b"", final=True))   # flush partial multibyte char

        raw_text = buf.getvalue()
        buf.close()

        if truncated:
            logger.warning(
                "FETCH truncated at %d bytes (cap=%d): %s",
                total, MAX_FILING_BYTES, source_url,
            )
        else:
            logger.info("FETCH done: %d bytes read, %d chars decoded: %s",
                        total, len(raw_text), source_url)

    finally:
        if resp is not None:
            resp.close()

    if "html" in content_type or re.search(r"\.(htm|html)$", source_url, re.I):
        return {"html": raw_text, "text": ""}
    elif "text" in content_type or source_url.endswith(".txt"):
        return {"html": "", "text": raw_text}
    else:
        return {"html": raw_text, "text": ""}


# --------------------------------------------------------------------------- #
# XBRL company facts  (deterministic numeric extraction)
# --------------------------------------------------------------------------- #

# Ordered list of XBRL concept names to try for each financial metric.
# The first concept found for the filing wins.
_KEY_CONCEPTS: Dict[str, List[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "eps_diluted": [
        "EarningsPerShareDiluted",
        "EarningsPerShareBasicAndDiluted",
    ],
    "eps_basic": [
        "EarningsPerShareBasic",
    ],
    "operating_income": [
        "OperatingIncomeLoss",
    ],
    "gross_profit": [
        "GrossProfit",
    ],
    "total_assets": [
        "Assets",
    ],
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
    ],
}


def fetch_company_facts(cik: str) -> Dict[str, Any]:
    """
    Fetch structured XBRL company facts from the SEC companyfacts endpoint.

    URL: https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json

    Returns the raw companyfacts JSON dict, or {} on any error.  The response
    can be large (5–20 MB for large companies); callers should process it with
    extract_facts_for_period() and then discard the full payload.

    Response structure::

        {
          "cik": int,
          "entityName": str,
          "facts": {
            "us-gaap": {
              "ConceptName": {
                "label": str,
                "units": {
                  "USD": [{"end": "YYYY-MM-DD", "val": float, "accn": "...", ...}]
                }
              }
            }
          }
        }
    """
    url = f"{EDGAR_API_BASE}/api/xbrl/companyfacts/CIK{cik}.json"
    logger.info("fetch_company_facts: CIK=%s", cik)
    try:
        data = _get(url, timeout=(10, 45))
        concept_count = len(data.get("facts", {}).get("us-gaap", {}))
        logger.info(
            "fetch_company_facts: CIK=%s entity=%r us-gaap concepts=%d",
            cik, data.get("entityName", ""), concept_count,
        )
        return data
    except RuntimeError as exc:
        logger.warning("fetch_company_facts(%s) failed: %s", cik, exc)
        return {}


def extract_facts_for_period(
    facts_data: Dict[str, Any],
    accession_number: str,
) -> Dict[str, Optional[float]]:
    """
    Extract key financial metrics from a companyfacts response for one filing.

    Matches entries by accession number (dashes optional — both formats accepted).

    Parameters
    ----------
    facts_data       : full response from fetch_company_facts()
    accession_number : SEC accession number, e.g. "0000012345-24-000010"

    Returns
    -------
    Dict mapping metric names (from _KEY_CONCEPTS) to raw numeric values, or
    None when the concept is not present for this filing.  Monetary values are
    in USD; EPS values are per-share amounts as reported.

    Example return value::

        {
            "revenue":            48_000_000_000.0,
            "net_income":          7_600_000_000.0,
            "eps_diluted":                    2.45,
            "eps_basic":                      2.50,
            "operating_income":    9_800_000_000.0,
            "gross_profit":       21_000_000_000.0,
            "total_assets":      450_000_000_000.0,
            "cash_and_equivalents": 34_000_000_000.0,
        }
    """
    result: Dict[str, Optional[float]] = {k: None for k in _KEY_CONCEPTS}
    if not facts_data:
        return result

    accn_norm = accession_number.replace("-", "")
    us_gaap   = facts_data.get("facts", {}).get("us-gaap", {})

    for metric_key, concepts in _KEY_CONCEPTS.items():
        for concept_name in concepts:
            concept_data = us_gaap.get(concept_name)
            if not concept_data:
                continue
            # Search across all unit types (USD, shares, pure)
            for unit_entries in concept_data.get("units", {}).values():
                for entry in unit_entries:
                    if entry.get("accn", "").replace("-", "") == accn_norm:
                        result[metric_key] = entry.get("val")
                        break
                if result[metric_key] is not None:
                    break
            if result[metric_key] is not None:
                break

    found = sum(1 for v in result.values() if v is not None)
    logger.debug(
        "extract_facts_for_period: accn=%s found %d/%d metrics",
        accession_number, found, len(result),
    )
    return result
