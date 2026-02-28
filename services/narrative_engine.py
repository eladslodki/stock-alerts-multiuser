"""
Narrative Change Engine.

Compares the current quarter's ReportData/v1 JSON against the most recent
prior-quarter report stored in the database and asks the LLM to characterise
the shift in tone, risk profile, and strategic focus.

Only runs when a prior report exists for the same company.
Results are stored in fn_report_outputs.narrative_change_json.

Public API
----------
run_narrative_change(db, company_id, current_filing_db_id,
                     current_report_json, llm) -> dict | None
    Returns the narrative change dict, or None if no prior report exists.
    Never raises.
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Maximum characters taken from each summary to stay within context limits
_MAX_SUMMARY_CHARS = 4_000


def _summarise_report(report_json: dict) -> str:
    """
    Extract a compact text summary from a ReportData/v1 JSON.
    Covers: cover KPIs, s1 narrative, s7 guidance, s8 risks.
    """
    lines = []

    cover = report_json.get("cover", {})
    lines.append(
        f"Filing: {cover.get('ticker', '')} {cover.get('filingType', '')} "
        f"period={cover.get('periodEnd', '')} filed={cover.get('filedAt', '')}"
    )

    kpis = cover.get("kpis", [])
    if kpis:
        kpi_str = " | ".join(
            f"{k.get('label', '')}: {k.get('value', '')} ({k.get('change', '')})"
            for k in kpis
        )
        lines.append(f"KPIs: {kpi_str}")

    for sec in report_json.get("sections", []):
        sid = sec.get("id", "")

        if sid == "s1":
            narr = sec.get("narrative", "")
            if narr:
                lines.append(f"Executive Summary: {narr[:600]}")

        elif sid == "s7":
            narr = sec.get("narrative", "")
            if narr:
                lines.append(f"Guidance Narrative: {narr[:400]}")
            for item in sec.get("items", [])[:4]:
                lines.append(
                    f"  Guidance [{item.get('type', '')}] {item.get('topic', '')}: "
                    f"{item.get('statement', '')}"
                )

        elif sid == "s8":
            for risk in sec.get("risks", [])[:5]:
                lines.append(
                    f"  Risk [{risk.get('severity', '')}] {risk.get('title', '')}: "
                    f"{risk.get('description', '')}"
                )

        elif sid == "s10":
            rating = sec.get("ratingHebrew") or sec.get("rating", "")
            pt     = sec.get("priceTarget", "")
            if rating or pt:
                lines.append(f"Analyst View: {rating} / target {pt}")

    return "\n".join(lines)[:_MAX_SUMMARY_CHARS]


def _find_prior_report_json(db, company_id: int, current_filing_db_id: int) -> Optional[dict]:
    """
    Query for the most recent prior report for the same company.
    Returns the report_json or None.
    """
    from fundamentals_models import Filing, ReportOutput

    # Find all filings for this company except the current one
    prior_filings = (
        db.query(Filing)
        .filter(Filing.company_id == company_id)
        .filter(Filing.id != current_filing_db_id)
        .order_by(Filing.period_end.desc().nullslast())
        .limit(5)
        .all()
    )

    for pf in prior_filings:
        output = (
            db.query(ReportOutput)
            .filter_by(filing_id=pf.id)
            .order_by(ReportOutput.created_at.desc())
            .first()
        )
        if output and output.report_json:
            logger.info(
                "Narrative engine: found prior report for filing_id=%s period=%s",
                pf.filing_id, pf.period_end,
            )
            return output.report_json

    return None


def run_narrative_change(
    db,
    company_id: int,
    current_filing_db_id: int,
    current_report_json: dict,
    llm,
) -> Optional[dict]:
    """
    Compare current vs prior report and return narrative change dict.
    Returns None if no prior report is available.
    """
    try:
        prior_json = _find_prior_report_json(db, company_id, current_filing_db_id)
        if not prior_json:
            logger.info("Narrative engine: no prior report found — skipping.")
            return None

        current_summary = _summarise_report(current_report_json)
        prior_summary   = _summarise_report(prior_json)

        from services.llm_client import NARRATIVE_CHANGE_PROMPT
        prompt   = NARRATIVE_CHANGE_PROMPT.format(
            prior_summary=prior_summary,
            current_summary=current_summary,
        )
        raw      = llm.complete(prompt, max_tokens=2_000)

        # parse
        from services.report_generator import _parse_llm_json
        result   = _parse_llm_json(raw)

        # Validate minimal keys
        required = {"narrative_shift", "new_risks", "removed_risks",
                    "new_growth_focus", "management_tone_change"}
        missing  = required - set(result.keys())
        if missing:
            logger.warning("Narrative LLM response missing keys: %s", missing)
            for k in missing:
                result[k] = [] if "risks" in k else ""

        return result

    except Exception as exc:
        logger.warning("run_narrative_change failed: %s", exc)
        return None
