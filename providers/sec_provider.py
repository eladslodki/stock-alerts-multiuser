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
import os
import re
import time
import logging
from typing import Optional, List, Dict, Any

import requests

# Max bytes to download from a single filing document.
# 10-K filings can be 50-200 MB; 8 MB is enough to capture the key sections
# while preventing OOM kills in a memory-constrained worker.
MAX_FILING_BYTES = int(os.getenv("SEC_MAX_FILING_BYTES", str(8 * 1024 * 1024)))

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


def _get(url: str, *, as_json: bool = True, timeout: int = 30) -> Any:
    """GET with automatic retry / backoff. Raises RuntimeError on failure."""
    last_exc: Exception = RuntimeError("Unknown error")
    for attempt in range(_RETRIES):
        try:
            resp = _session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.json() if as_json else resp
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status == 404:
                raise RuntimeError(f"SEC returned 404 for {url}") from exc
            last_exc = exc
        except requests.exceptions.RequestException as exc:
            last_exc = exc

        if attempt < _RETRIES - 1:
            time.sleep(_BACKOFF[attempt])

    raise RuntimeError(f"SEC EDGAR unavailable after {_RETRIES} attempts: {last_exc}") from last_exc


# --------------------------------------------------------------------------- #
# CIK resolution
# --------------------------------------------------------------------------- #
_CIK_CACHE: Dict[str, str] = {}


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

    return results


# --------------------------------------------------------------------------- #
# Filing content
# --------------------------------------------------------------------------- #
def fetch_filing_content(source_url: str) -> Dict[str, str]:
    """
    Download the primary filing document, capped at MAX_FILING_BYTES.

    Streams the response so that large 10-K filings (50-200 MB) do not
    load entirely into memory before we can truncate them.

    Returns a dict with keys:
        html  – raw HTML string (may be empty)
        text  – plain-text string (may be empty)

    Raises RuntimeError if the download fails.
    """
    if not source_url:
        return {"html": "", "text": ""}

    try:
        resp = _session.get(source_url, timeout=90, stream=True)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Cannot fetch filing document: {exc}") from exc

    # Stream-read with a hard byte cap to prevent OOM
    byte_chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65_536):
        byte_chunks.append(chunk)
        total += len(chunk)
        if total >= MAX_FILING_BYTES:
            logger.warning(
                "Filing download truncated at %d bytes (cap: %d): %s",
                total, MAX_FILING_BYTES, source_url,
            )
            break
    resp.close()

    raw_text = b"".join(byte_chunks).decode("utf-8", errors="replace")
    content_type = resp.headers.get("content-type", "").lower()

    if "html" in content_type or re.search(r"\.(htm|html)$", source_url, re.I):
        return {"html": raw_text, "text": ""}
    elif "text" in content_type or source_url.endswith(".txt"):
        return {"html": "", "text": raw_text}
    else:
        # Best-effort: treat as HTML
        return {"html": raw_text, "text": ""}
