"""
Report generation orchestration for the Fundamentals Reports feature.

Flow  (extended with Earnings Expectations & Market Reaction Engine)
----------------------------------------------------------------------
generate_report(ticker, filing_id, force, render_fn)
  1.  Cache check  →  return "cached" if report+HTML+market_analysis_json all exist
  2.  Resolve company + filing metadata from SEC  [skipped if report_json cached]
  3.  Fetch & clean filing text                  [skipped if cached]
  4.  Map-reduce LLM  →  ReportData/v1 JSON      [skipped if cached]
  5.  Validate + sanitize JSON
  5b. Fetch consensus expectations  (Yahoo Finance 24 h cache)
  5c. Extract actual metrics  (deterministic parser, no LLM)
  5d. Compute surprise percentages
  5e. Market reaction LLM call  →  market_analysis_json
  5f. Narrative change LLM call  (only if prior report in DB)
  6.  Build template analysis block + render HTML
  7.  Persist all columns

Caching tiers
  Full    : report_json + rendered_html + market_analysis_json  → instant return
  Partial : report_json + rendered_html, no analysis            → steps 5b-6 + re-render
  No HTML : report_json only                                    → steps 5b-6 + render
  Nothing : full generation
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
    MARKET_REACTION_PROMPT,
)
from providers.consensus_provider import get_consensus
from services.metrics_extractor import extract_actuals
from services.surprise_engine import (
    compute_all_surprises,
    fmt_surprise,
    surprise_sentiment,
)
from services.narrative_engine import run_narrative_change

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


# =========================================================================== #
# Analysis helpers  (steps 5b-5f)
# =========================================================================== #

def _fmt_financial(v: Optional[float]) -> str:
    """Format a raw float into a display string like '$4.8B'."""
    if v is None:
        return "—"
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.0f}M"
    return f"${v:.2f}"


def _fetch_consensus_safe(ticker: str) -> dict:
    try:
        return get_consensus(ticker)
    except Exception as exc:
        logger.warning("Consensus fetch failed for %s: %s", ticker, exc)
        return {"eps_estimate": None, "revenue_estimate": None,
                "ebitda_estimate": None, "currency": "USD", "source": "error"}


def _run_market_reaction(
    actuals: dict,
    consensus: dict,
    surprise: dict,
    report_json: dict,
    llm,
) -> dict:
    """Call LLM for market reaction analysis. Returns {} on any failure."""
    try:
        # Build guidance text from s7
        guidance_lines = []
        for sec in report_json.get("sections", []):
            if sec.get("id") == "s7":
                if sec.get("narrative"):
                    guidance_lines.append(sec["narrative"])
                for item in sec.get("items", []):
                    guidance_lines.append(
                        f"{item.get('topic', '')}: {item.get('statement', '')}"
                    )
                break
        guidance_text = "\n".join(guidance_lines)[:800] or "N/A"

        prompt = MARKET_REACTION_PROMPT.format(
            actuals_json=json.dumps(actuals,   ensure_ascii=False),
            consensus_json=json.dumps(consensus, ensure_ascii=False),
            surprise_json=json.dumps(surprise,  ensure_ascii=False),
            guidance_text=guidance_text,
        )
        raw    = llm.complete(prompt, max_tokens=1_500)
        result = _parse_llm_json(raw)

        # Validate required keys
        for k in ("reaction_driver", "bull_view", "bear_view",
                  "quality_of_beat", "guidance_signal"):
            result.setdefault(k, "")
        return result
    except Exception as exc:
        logger.warning("Market reaction LLM failed: %s", exc)
        return {}


def _build_template_analysis(
    consensus: dict,
    actuals: dict,
    surprise: dict,
    market_reaction: dict,
    narrative_change: Optional[dict],
) -> dict:
    """
    Build the `analysis` dict passed to report.html for s11 rendering.
    Pre-formats all display strings so the template stays logic-free.
    """
    # Expectations vs Reality table rows
    rows = []

    def _row(label, actual_raw, expected_raw, surp_pct):
        return {
            "metric":       label,
            "actual":       _fmt_financial(actual_raw),
            "expected":     _fmt_financial(expected_raw),
            "surprise":     fmt_surprise(surp_pct),
            "sentiment":    surprise_sentiment(surp_pct),
        }

    rows.append(_row(
        "הכנסות",
        actuals.get("revenue_actual"),
        consensus.get("revenue_estimate"),
        surprise.get("revenue_surprise_pct"),
    ))
    rows.append(_row(
        "EPS מדולל",
        actuals.get("eps_actual"),
        consensus.get("eps_estimate"),
        surprise.get("eps_surprise_pct"),
    ))
    rows.append(_row(
        "EBITDA",
        actuals.get("ebitda_actual"),
        consensus.get("ebitda_estimate"),
        surprise.get("ebitda_surprise_pct"),
    ))

    # guidance_midpoint vs consensus revenue (proxy for guidance surprise)
    gm = actuals.get("guidance_midpoint")
    if gm is not None:
        rows.append({
            "metric":    "נקודת אמצע תחזית הנהלה",
            "actual":    _fmt_financial(gm),
            "expected":  "—",
            "surprise":  "—",
            "sentiment": "neu",
        })

    return {
        "table_rows":       rows,
        "market_reaction":  market_reaction,
        "narrative_change": narrative_change,
        "guidance_signal":  market_reaction.get("guidance_signal", "neutral"),
        "source":           consensus.get("source", "yahoo"),
    }


def _generate_inner(ticker, filing_id, force, render_fn):
    with get_db() as db:

        # ------------------------------------------------------------------ #
        # 1. Layered cache check
        # ------------------------------------------------------------------ #
        filing_rec = db.query(Filing).filter_by(filing_id=filing_id).first()
        existing_output = None
        if filing_rec:
            existing_output = (
                db.query(ReportOutput)
                .filter_by(filing_id=filing_rec.id)
                .order_by(ReportOutput.created_at.desc())
                .first()
            )

        # Full cache: report + HTML + analysis all present
        if not force and existing_output:
            if (existing_output.report_json
                    and existing_output.rendered_html
                    and existing_output.market_analysis_json is not None):
                return {
                    "status":    "cached",
                    "filing_id": filing_id,
                    "url_html":  f"/reports/{ticker}/{filing_id}",
                    "url_json":  f"/api/reports/{ticker}/{filing_id}",
                }

        # Determine what work needs to be done
        skip_llm      = (not force
                         and existing_output is not None
                         and existing_output.report_json is not None)
        skip_analysis = (not force
                         and existing_output is not None
                         and existing_output.market_analysis_json is not None)

        # ------------------------------------------------------------------ #
        # 2–4. SEC fetch + text extraction + LLM  (skipped when cached)
        # ------------------------------------------------------------------ #
        fd          = None   # filing metadata dict from SEC
        company     = None
        filing_text = None

        if not skip_llm:
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

            company    = _upsert_company(db, ticker,
                                         cik=fd.get("cik"),
                                         name=fd.get("company_name"),
                                         exchange=fd.get("exchange"))
            filing_rec = _upsert_filing(db, company, fd)

            # Fetch filing text
            filing_text = db.query(FilingText).filter_by(filing_id=filing_rec.id).first()
            if not filing_text or force:
                try:
                    raw = fetch_filing_content(fd.get("source_url", ""))
                except RuntimeError as exc:
                    return {"status": "error", "error": str(exc), "code": 502}

                result = prepare_filing_text(raw.get("html", ""), raw.get("text", ""))

                # Only keep the small derived artifacts (relevant_text ~55 KB,
                # chunks ~56 KB). Storing the full clean_text (2+ MB) in the ORM
                # session keeps it pinned in memory for the entire request lifetime.
                _relevant = result["relevant_text"]
                _chunks   = result["chunks"]

                # Release the large raw HTML and full clean_text NOW so Python can
                # GC them before the expensive LLM calls and rendering steps.
                raw = result = None  # noqa: F841

                if filing_text:
                    filing_text.raw_html     = ""          # never read back; don't waste RAM
                    filing_text.clean_text   = _relevant   # ~55 KB instead of ~2 MB
                    filing_text.chunks_json  = _chunks
                    filing_text.extracted_at = datetime.now(timezone.utc)
                else:
                    filing_text = FilingText(
                        filing_id   = filing_rec.id,
                        raw_html    = "",
                        clean_text  = _relevant,
                        chunks_json = _chunks,
                    )
                    db.add(filing_text)
                db.flush()

            # LLM map-reduce
            llm    = get_llm_client()
            chunks = (filing_text.chunks_json or []) if filing_text else []
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

            # Validate + one-shot fix
            errors = validate_report_json(report_json)
            if errors:
                logger.warning("Schema errors — attempting fix: %s", errors)
                try:
                    fix_prompt  = FIX_SCHEMA_PROMPT.format(
                        errors="\n".join(errors),
                        current_json=json.dumps(report_json, ensure_ascii=False),
                    )
                    report_json = _parse_llm_json(llm.complete(fix_prompt, max_tokens=8_000))
                    errors      = validate_report_json(report_json)
                except Exception as fix_exc:
                    logger.error("Fix attempt failed: %s", fix_exc)
                if errors:
                    logger.error("Report still invalid after fix: %s", errors)

            report_json = sanitize_report_json(report_json)

        else:
            # Use cached report JSON
            report_json = existing_output.report_json
            llm         = get_llm_client()   # needed for analysis LLM calls

        # Ensure filing_rec and company are loaded even in skip_llm path
        if filing_rec is None:
            filing_rec = db.query(Filing).filter_by(filing_id=filing_id).first()
        if filing_rec and company is None:
            company = filing_rec.company

        # ------------------------------------------------------------------ #
        # 5b–5f. Earnings Expectations & Market Reaction Engine
        # ------------------------------------------------------------------ #
        if not skip_analysis:
            # 5b. Consensus
            consensus = _fetch_consensus_safe(ticker)

            # 5c. Extract actuals (deterministic)
            actuals = extract_actuals(report_json)

            # 5d. Surprise
            surprise = compute_all_surprises(actuals, consensus)

            # 5e. Market reaction LLM
            market_reaction = _run_market_reaction(
                actuals, consensus, surprise, report_json, llm
            )

            # 5f. Narrative change (only if prior report exists)
            narrative_change = None
            if filing_rec and company:
                narrative_change = run_narrative_change(
                    db              = db,
                    company_id      = company.id,
                    current_filing_db_id = filing_rec.id,
                    current_report_json  = report_json,
                    llm             = llm,
                )
        else:
            # Reconstruct from cached columns
            consensus        = existing_output.consensus_json or {}
            actuals          = extract_actuals(report_json)   # fast, no LLM
            surprise         = existing_output.surprise_json or {}
            market_reaction  = existing_output.market_analysis_json or {}
            narrative_change = existing_output.narrative_change_json

        # ------------------------------------------------------------------ #
        # 6. Render HTML  (always re-render if LLM ran or analysis ran)
        # ------------------------------------------------------------------ #
        need_render = not skip_llm or not skip_analysis or not (
            existing_output and existing_output.rendered_html
        )

        if need_render:
            if render_fn is None:
                from flask import render_template as render_fn  # type: ignore

            template_analysis = _build_template_analysis(
                consensus, actuals, surprise, market_reaction, narrative_change
            )
            try:
                rendered_html = render_fn(
                    "report.html",
                    report=report_json,
                    analysis=template_analysis,
                )
            except Exception as exc:
                logger.error("Template rendering error: %s", exc)
                rendered_html = (
                    f"<html><body><pre>Rendering error: {exc}</pre></body></html>"
                )
        else:
            rendered_html = existing_output.rendered_html

        # ------------------------------------------------------------------ #
        # 7. Persist everything
        # ------------------------------------------------------------------ #
        llm_model = "mock"
        if os.getenv("AI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"):
            llm_model = os.getenv("AI_MODEL", "claude-opus-4-6")

        if existing_output and (force or skip_llm):
            # Update in place
            if not skip_llm:
                existing_output.report_json   = report_json
                existing_output.llm_model     = llm_model
            if not skip_analysis:
                existing_output.consensus_json        = consensus
                existing_output.surprise_json         = surprise
                existing_output.market_analysis_json  = market_reaction
                existing_output.narrative_change_json = narrative_change
            existing_output.rendered_html = rendered_html
            existing_output.created_at    = datetime.now(timezone.utc)
        else:
            new_output = ReportOutput(
                filing_id             = filing_rec.id,
                schema_version        = "ReportData/v1",
                report_json           = report_json,
                rendered_html         = rendered_html,
                llm_model             = llm_model,
                consensus_json        = consensus        if not skip_analysis else None,
                surprise_json         = surprise         if not skip_analysis else None,
                market_analysis_json  = market_reaction  if not skip_analysis else None,
                narrative_change_json = narrative_change if not skip_analysis else None,
            )
            db.add(new_output)

        status = "generated" if not skip_llm else ("enriched" if not skip_analysis else "cached")
        return {
            "status":    status,
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
