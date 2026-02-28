"""
Report generation orchestration for the Fundamentals Reports feature.

Flow
----
generate_report(ticker, filing_id, force, render_fn)
  1. Check cache  →  return immediately if hit
  2. Resolve company + filing metadata from SEC
  3. Fetch & clean filing text  (cached in fn_filing_text)
  4. Map-reduce LLM extraction  →  ReportData/v1 JSON
  5. Validate + sanitize JSON
  6. Render HTML via render_fn("report.html", report=...)
  7. Persist to fn_report_outputs

Caching
-------
- If fn_report_outputs has valid JSON + HTML  →  return "cached"
- If fn_filing_text exists but output missing →  skip fetch, jump to LLM
- Per-filing threading.Lock prevents concurrent duplicate generation

Security
--------
insight.text fields are sanitized via bleach (allow: strong, mark, br, em).
All other strings are rendered {{ x }} (auto-escaped by Jinja2).
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import bleach

from fundamentals_db import get_db
from fundamentals_models import Company, Filing, FilingText, ReportOutput
from providers.sec_provider import (
    list_filings as sec_list_filings,
    fetch_filing_content,
    ticker_to_cik,
    get_company_info,
)
from services.extract_text import prepare_filing_text
from services.llm_client import (
    get_llm_client,
    MAP_PROMPT_TEMPLATE,
    REDUCE_PROMPT_TEMPLATE,
    FIX_SCHEMA_PROMPT,
)

logger = logging.getLogger(__name__)

# ---- bleach config --------------------------------------------------------- #
ALLOWED_TAGS       = ["strong", "mark", "br", "em"]
ALLOWED_ATTRIBUTES = {}   # no attributes on any allowed tag

# ---- generation locks (one per filing_id string) -------------------------- #
_locks: Dict[str, threading.Lock] = {}
_locks_mutex = threading.Lock()


def _get_lock(filing_id: str) -> threading.Lock:
    with _locks_mutex:
        if filing_id not in _locks:
            _locks[filing_id] = threading.Lock()
        return _locks[filing_id]


# =========================================================================== #
# Sanitization & validation
# =========================================================================== #

def sanitize_insight(text: str) -> str:
    """Strip all HTML except the small safe set; return clean string."""
    if not isinstance(text, str):
        return ""
    return bleach.clean(text, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)


def sanitize_report_json(data: dict) -> dict:
    """Walk the report and sanitize every insight.text field in-place."""
    for section in data.get("sections", []):
        for insight in section.get("insights", []):
            if "text" in insight:
                insight["text"] = sanitize_insight(insight["text"])
    return data


def validate_report_json(data: dict) -> List[str]:
    """
    Return a list of validation error strings.
    An empty list means the report is valid.
    """
    errors: List[str] = []

    if data.get("schema") != "ReportData/v1":
        errors.append(f"schema must be 'ReportData/v1', got {data.get('schema')!r}")

    cover = data.get("cover")
    if not isinstance(cover, dict):
        errors.append("cover must be an object")
    else:
        kpis = cover.get("kpis", [])
        if len(kpis) != 4:
            errors.append(f"cover.kpis must have exactly 4 items, got {len(kpis)}")

    toc = data.get("toc")
    if not isinstance(toc, dict):
        errors.append("toc must be an object")
    else:
        toc_items = toc.get("items", [])
        if len(toc_items) != 10:
            errors.append(f"toc.items must have exactly 10 items, got {len(toc_items)}")

    sections = data.get("sections", [])
    if len(sections) != 10:
        errors.append(f"sections must have exactly 10 items, got {len(sections)}")
    else:
        for i, sec in enumerate(sections):
            expected = f"s{i + 1}"
            if sec.get("id") != expected:
                errors.append(f"sections[{i}].id = {sec.get('id')!r}, expected {expected!r}")

    return errors


# =========================================================================== #
# LLM map-reduce
# =========================================================================== #

def _parse_llm_json(raw: str) -> dict:
    """Strip optional markdown fences then parse JSON."""
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
        elif len(parts) == 2:
            text = parts[1]
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def _merge_facts_bags(bags: List[dict]) -> dict:
    """Merge multiple map-step facts bags into one unified bag."""
    merged: Dict[str, Any] = {
        "revenue_items":       [],
        "profitability_items": [],
        "cash_flow_items":     [],
        "balance_sheet_items": [],
        "guidance_items":      [],
        "risk_items":          [],
        "management_quotes":   [],
        "segment_items":       [],
        "key_metrics":         {},
        "period_info":         {},
        "raw_quotes":          [],
    }

    list_keys = [
        "revenue_items", "profitability_items", "cash_flow_items",
        "balance_sheet_items", "guidance_items", "risk_items",
        "management_quotes", "segment_items", "raw_quotes",
    ]

    for bag in bags:
        for key in list_keys:
            merged[key].extend(bag.get(key, []))
        # Prefer first non-null value for scalar metrics
        for k, v in bag.get("key_metrics", {}).items():
            if v is not None and merged["key_metrics"].get(k) is None:
                merged["key_metrics"][k] = v
        for k, v in bag.get("period_info", {}).items():
            if v is not None and merged["period_info"].get(k) is None:
                merged["period_info"][k] = v

    # Deduplicate by JSON fingerprint
    for key in list_keys:
        seen: set = set()
        deduped: List = []
        for item in merged[key]:
            fp = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if fp not in seen:
                seen.add(fp)
                deduped.append(item)
        merged[key] = deduped

    return merged


def _run_map_reduce(
    chunks: List[str],
    ticker: str,
    filing_type: str,
    period_end: str,
    company_name: str,
    llm,
) -> dict:
    """
    Map step: extract facts from up to 6 chunks (≈18 k chars of context).
    Reduce step: combine into ReportData/v1 JSON.
    """
    facts_bags: List[dict] = []
    for i, chunk in enumerate(chunks[:6]):
        try:
            prompt   = MAP_PROMPT_TEMPLATE.format(chunk_text=chunk)
            response = llm.complete(prompt, max_tokens=2_000)
            facts    = _parse_llm_json(response)
            facts_bags.append(facts)
            logger.info("Map chunk %d/%d: OK", i + 1, min(len(chunks), 6))
        except Exception as exc:
            logger.warning("Map chunk %d failed (%s) — skipping", i + 1, exc)

    if not facts_bags:
        logger.warning("All map chunks failed; using empty facts bag for reduce step.")
        facts_bags = [{}]

    merged = _merge_facts_bags(facts_bags)
    facts_str = json.dumps(merged, ensure_ascii=False, indent=2)

    reduce_prompt = REDUCE_PROMPT_TEMPLATE.format(
        ticker=ticker,
        company_name=company_name,
        filing_type=filing_type,
        period_end=period_end,
        facts_bag=facts_str,
    )
    response = llm.complete(reduce_prompt, max_tokens=8_000)
    return _parse_llm_json(response)


# =========================================================================== #
# DB helpers
# =========================================================================== #

def _upsert_company(db, ticker: str, cik=None, name=None, exchange=None) -> Company:
    company = db.query(Company).filter_by(ticker=ticker.upper()).first()
    if not company:
        company = Company(ticker=ticker.upper(), cik=cik, name=name, exchange=exchange)
        db.add(company)
        db.flush()
    else:
        if cik and not company.cik:         company.cik      = cik
        if name and not company.name:       company.name     = name
        if exchange and not company.exchange: company.exchange = exchange
    return company


def _upsert_filing(db, company: Company, fd: dict) -> Filing:
    filing = db.query(Filing).filter_by(filing_id=fd["filing_id"]).first()
    if not filing:
        period_end = None
        if fd.get("period_end"):
            try:
                period_end = datetime.strptime(fd["period_end"], "%Y-%m-%d").date()
            except ValueError:
                pass

        filed_at = None
        if fd.get("filed_at"):
            try:
                filed_at = datetime.strptime(fd["filed_at"], "%Y-%m-%d")
            except ValueError:
                pass

        filing = Filing(
            company_id=company.id,
            filing_id=fd["filing_id"],
            filing_type=fd["filing_type"],
            period_end=period_end,
            filed_at=filed_at,
            source_url=fd.get("source_url", ""),
            source_provider=fd.get("source_provider", "sec"),
        )
        db.add(filing)
        db.flush()
    return filing


# =========================================================================== #
# Public API
# =========================================================================== #

def generate_report(
    ticker: str,
    filing_id: str,
    force: bool = False,
    render_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Main orchestration function.

    Parameters
    ----------
    ticker    : stock ticker symbol
    filing_id : SEC accession number (with dashes)
    force     : ignore cached output and regenerate
    render_fn : callable(template_name, **ctx) → str
                Pass flask.render_template here.

    Returns
    -------
    dict with keys: status, filing_id, url_html, url_json
              or  : status, error, code
    """
    ticker = ticker.upper().strip()
    lock   = _get_lock(filing_id)

    if not lock.acquire(blocking=False):
        return {
            "status":    "generating",
            "filing_id": filing_id,
            "message":   "Report generation already in progress for this filing.",
        }

    try:
        return _generate_inner(ticker, filing_id, force, render_fn)
    finally:
        lock.release()


def _generate_inner(ticker, filing_id, force, render_fn):
    with get_db() as db:

        # ------------------------------------------------------------------ #
        # 1. Cache check
        # ------------------------------------------------------------------ #
        filing_rec = db.query(Filing).filter_by(filing_id=filing_id).first()
        if filing_rec and not force:
            output = (
                db.query(ReportOutput)
                .filter_by(filing_id=filing_rec.id)
                .order_by(ReportOutput.created_at.desc())
                .first()
            )
            if output and output.report_json and output.rendered_html:
                return {
                    "status":    "cached",
                    "filing_id": filing_id,
                    "url_html":  f"/reports/{ticker}/{filing_id}",
                    "url_json":  f"/api/reports/{ticker}/{filing_id}",
                }

        # ------------------------------------------------------------------ #
        # 2. Resolve filing metadata from SEC
        # ------------------------------------------------------------------ #
        try:
            filings = sec_list_filings(ticker)
        except (ValueError, RuntimeError) as exc:
            return {"status": "error", "error": str(exc), "code": 502}

        fd = next((f for f in filings if f["filing_id"] == filing_id), None)
        if not fd:
            return {
                "status": "error",
                "error":  f"Filing '{filing_id}' not found for ticker '{ticker}'.",
                "code":   404,
            }

        # ------------------------------------------------------------------ #
        # 3. Persist company + filing records
        # ------------------------------------------------------------------ #
        company    = _upsert_company(db, ticker,
                                     cik=fd.get("cik"),
                                     name=fd.get("company_name"),
                                     exchange=fd.get("exchange"))
        filing_rec = _upsert_filing(db, company, fd)

        # ------------------------------------------------------------------ #
        # 4. Fetch + clean filing text  (cached in fn_filing_text)
        # ------------------------------------------------------------------ #
        filing_text = (
            db.query(FilingText).filter_by(filing_id=filing_rec.id).first()
        )
        if not filing_text or force:
            try:
                raw = fetch_filing_content(fd.get("source_url", ""))
            except RuntimeError as exc:
                return {"status": "error", "error": str(exc), "code": 502}

            result = prepare_filing_text(raw.get("html", ""), raw.get("text", ""))

            if filing_text:
                filing_text.raw_html     = (raw.get("html") or "")[:100_000]
                filing_text.clean_text   = result["clean_text"]
                filing_text.chunks_json  = result["chunks"]
                filing_text.extracted_at = datetime.now(timezone.utc)
            else:
                filing_text = FilingText(
                    filing_id   = filing_rec.id,
                    raw_html    = (raw.get("html") or "")[:100_000],
                    clean_text  = result["clean_text"],
                    chunks_json = result["chunks"],
                )
                db.add(filing_text)
            db.flush()

        # ------------------------------------------------------------------ #
        # 5. LLM generation
        # ------------------------------------------------------------------ #
        existing_output = (
            db.query(ReportOutput)
            .filter_by(filing_id=filing_rec.id)
            .order_by(ReportOutput.created_at.desc())
            .first()
        )

        if existing_output and existing_output.report_json and not force:
            report_json = existing_output.report_json
        else:
            llm    = get_llm_client()
            chunks = filing_text.chunks_json or []

            try:
                report_json = _run_map_reduce(
                    chunks       = chunks,
                    ticker       = ticker,
                    filing_type  = fd["filing_type"],
                    period_end   = fd.get("period_end", ""),
                    company_name = fd.get("company_name", ticker),
                    llm          = llm,
                )
            except json.JSONDecodeError as exc:
                return {"status": "error", "error": f"LLM returned invalid JSON: {exc}", "code": 500}
            except Exception as exc:
                logger.exception("LLM generation failed")
                return {"status": "error", "error": f"LLM error: {exc}", "code": 500}

            # Validate — attempt one LLM fix if needed
            errors = validate_report_json(report_json)
            if errors:
                logger.warning("Schema errors: %s — attempting fix", errors)
                try:
                    fix_prompt = FIX_SCHEMA_PROMPT.format(
                        errors="\n".join(errors),
                        current_json=json.dumps(report_json, ensure_ascii=False),
                    )
                    fixed_raw    = llm.complete(fix_prompt, max_tokens=8_000)
                    report_json  = _parse_llm_json(fixed_raw)
                    errors       = validate_report_json(report_json)
                except Exception as fix_exc:
                    logger.error("Fix attempt failed: %s", fix_exc)

                if errors:
                    logger.error("Report still invalid after fix: %s", errors)

            # Sanitize insight HTML
            report_json = sanitize_report_json(report_json)

        # ------------------------------------------------------------------ #
        # 6. Render HTML
        # ------------------------------------------------------------------ #
        if render_fn is None:
            from flask import render_template as render_fn  # type: ignore

        try:
            rendered_html = render_fn("report.html", report=report_json)
        except Exception as exc:
            logger.error("Template rendering error: %s", exc)
            rendered_html = f"<html><body><pre>Rendering error: {exc}</pre></body></html>"

        # ------------------------------------------------------------------ #
        # 7. Persist output
        # ------------------------------------------------------------------ #
        llm_model = "mock"
        if os.getenv("AI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"):
            llm_model = os.getenv("AI_MODEL", "claude-opus-4-6")

        if existing_output and force:
            existing_output.report_json   = report_json
            existing_output.rendered_html = rendered_html
            existing_output.llm_model     = llm_model
            existing_output.created_at    = datetime.now(timezone.utc)
        else:
            new_output = ReportOutput(
                filing_id     = filing_rec.id,
                schema_version= "ReportData/v1",
                report_json   = report_json,
                rendered_html = rendered_html,
                llm_model     = llm_model,
            )
            db.add(new_output)

        return {
            "status":    "generated",
            "filing_id": filing_id,
            "url_html":  f"/reports/{ticker}/{filing_id}",
            "url_json":  f"/api/reports/{ticker}/{filing_id}",
        }


# =========================================================================== #
# Read-only helpers (used by GET routes)
# =========================================================================== #

def get_cached_report_json(ticker: str, filing_id: str) -> Optional[dict]:
    """Return the cached ReportData/v1 JSON or None."""
    with get_db() as db:
        filing = db.query(Filing).filter_by(filing_id=filing_id).first()
        if not filing:
            return None
        output = (
            db.query(ReportOutput)
            .filter_by(filing_id=filing.id)
            .order_by(ReportOutput.created_at.desc())
            .first()
        )
        return output.report_json if output else None


def get_cached_report_html(ticker: str, filing_id: str) -> Optional[str]:
    """Return the cached rendered HTML or None."""
    with get_db() as db:
        filing = db.query(Filing).filter_by(filing_id=filing_id).first()
        if not filing:
            return None
        output = (
            db.query(ReportOutput)
            .filter_by(filing_id=filing.id)
            .order_by(ReportOutput.created_at.desc())
            .first()
        )
        return output.rendered_html if output else None
