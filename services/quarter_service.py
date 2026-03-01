"""
Quarter service — maps SEC 10-Q / 10-K filings to user-facing year+quarter labels.

Quarter detection from period_end (fiscal, not calendar):
  month  1–3  → Q1
  month  4–6  → Q2
  month  7–9  → Q3
  month 10–12 → Q4  (sourced from 10-K annual; no 10-Q exists for Q4)

Public API
----------
  period_end_to_quarter(period_end: str) -> Optional[str]
  list_quarters(ticker: str) -> List[Dict[str, Any]]
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from providers.sec_provider import list_filings as _sec_list_filings

logger = logging.getLogger(__name__)


def period_end_to_quarter(period_end: str) -> Optional[str]:
    """
    Convert a YYYY-MM-DD period-end date to a quarter label (Q1..Q4).
    Returns None if the date cannot be parsed.
    """
    if not period_end:
        return None
    try:
        month = datetime.strptime(period_end, "%Y-%m-%d").month
    except ValueError:
        return None

    if month <= 3:
        return "Q1"
    elif month <= 6:
        return "Q2"
    elif month <= 9:
        return "Q3"
    else:
        return "Q4"


def _period_end_to_year(period_end: str) -> Optional[int]:
    if not period_end:
        return None
    try:
        return datetime.strptime(period_end, "%Y-%m-%d").year
    except ValueError:
        return None


def _get_completed_filing_ids(filing_ids: List[str]) -> Set[str]:
    """
    Return the subset of filing_ids (SEC accession numbers) that already
    have a completed ReportOutput row in the DB.
    """
    if not filing_ids:
        return set()
    try:
        from fundamentals_db import get_db
        from fundamentals_models import Filing, ReportOutput
        with get_db() as db:
            filings = (
                db.query(Filing)
                .filter(Filing.filing_id.in_(filing_ids))
                .all()
            )
            if not filings:
                return set()
            db_id_to_accession = {f.id: f.filing_id for f in filings}
            outputs = (
                db.query(ReportOutput.filing_id)
                .filter(
                    ReportOutput.filing_id.in_(db_id_to_accession.keys()),
                    ReportOutput.rendered_html.isnot(None),
                )
                .all()
            )
            completed_db_ids = {row.filing_id for row in outputs}
            return {
                acc for db_id, acc in db_id_to_accession.items()
                if db_id in completed_db_ids
            }
    except Exception as exc:
        logger.warning("_get_completed_filing_ids failed: %s", exc)
        return set()


def list_quarters(ticker: str) -> List[Dict[str, Any]]:
    """
    Return a list of fiscal quarters for *ticker*, newest-first.

    Each entry:
        year              – int
        quarter           – "Q1" | "Q2" | "Q3" | "Q4"
        label             – "2025 Q3"
        period_end        – "YYYY-MM-DD"
        filed_at          – "YYYY-MM-DD"
        source_filing_id  – SEC accession number (used internally)
        source_filing_type – "10-Q" or "10-K"
        has_report        – bool (True if a rendered report exists in DB)

    Q4 RULE: Q4 entries are sourced from 10-K filings only.
             Q1/Q2/Q3 entries are sourced from 10-Q filings only.
    """
    filings = _sec_list_filings(ticker)

    seen: Set[tuple] = set()
    quarters: List[Dict[str, Any]] = []

    for f in filings:
        period_end   = f.get("period_end") or ""
        filing_type  = f.get("filing_type", "")
        quarter      = period_end_to_quarter(period_end)
        year         = _period_end_to_year(period_end)

        if not quarter or not year:
            continue

        # Q4 must come from 10-K; Q1/Q2/Q3 must come from 10-Q
        if quarter == "Q4" and filing_type != "10-K":
            continue
        if quarter in ("Q1", "Q2", "Q3") and filing_type != "10-Q":
            continue

        key = (year, quarter)
        if key in seen:
            continue
        seen.add(key)

        quarters.append({
            "year":               year,
            "quarter":            quarter,
            "label":              f"{year} {quarter}",
            "period_end":         period_end,
            "filed_at":           f.get("filed_at", ""),
            "source_filing_id":   f["filing_id"],
            "source_filing_type": filing_type,
            "has_report":         False,   # filled in below
        })

    # Check DB for which filings already have reports
    all_filing_ids  = [q["source_filing_id"] for q in quarters]
    completed       = _get_completed_filing_ids(all_filing_ids)
    for q in quarters:
        q["has_report"] = q["source_filing_id"] in completed

    # Sort newest first: descending year, then Q4 > Q3 > Q2 > Q1
    quarters.sort(key=lambda q: (q["year"], q["quarter"]), reverse=True)
    return quarters


def resolve_quarter_to_filing(
    ticker: str, year: int, quarter: str
) -> Optional[Dict[str, Any]]:
    """
    Find the SEC filing dict for a given ticker + year + quarter.
    Returns None if not found.
    """
    try:
        quarters = list_quarters(ticker)
    except (ValueError, RuntimeError):
        return None
    for q in quarters:
        if q["year"] == year and q["quarter"] == quarter:
            return q
    return None
