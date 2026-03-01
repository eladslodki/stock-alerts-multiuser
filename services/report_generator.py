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
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

try:
    import psutil as _psutil
    _PROC = _psutil.Process(os.getpid())
except ImportError:
    _psutil = None
    _PROC   = None


def _rss_mb() -> str:
    """Current process RSS in MB, or '?' if psutil not installed."""
    if _PROC is None:
        return "?"
    return f"{_PROC.memory_info().rss / 1_048_576:.1f}"

import bleach

from fundamentals_db import get_db
from fundamentals_models import Company, Filing, FilingText, ReportOutput
from providers.sec_provider import (
    list_filings as sec_list_filings,
    fetch_filing_content,
    fetch_company_facts,
    extract_facts_for_period,
    ticker_to_cik,
    get_company_info,
)
from services.extract_text import prepare_filing_text
from services.generation_lock import acquire_lock, release_lock
from services.llm_client import (
    get_llm_client,
    LLMAuthError,
    ANTI_HALLUCINATION_SYSTEM_PROMPT,
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

# (in-process threading.Lock replaced by DB-backed GenerationLock with TTL)


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


# Extracts significant digit sequences from formatted value strings like "$4.8B", "$980M".
_VALUE_NUM_RE = re.compile(r'\$?([\d,]+(?:\.\d+)?)')


def _grounding_check(facts_bag: dict, chunk_text: str) -> int:
    """
    Warn about facts items whose numeric values are not present in the source chunk.

    For each item in the facts lists (revenue, profitability, cash flow, balance
    sheet), the significant digit sequence of the "value" field is compared to
    the chunk text (with commas stripped from both sides).  A WARNING is logged
    for every item whose digits cannot be found.

    This is a best-effort diagnostic: items are NOT removed, and false positives
    may occur when a value is expressed in different units (e.g. "$4.8B" vs
    "4,800,000,000").  The count returned helps detect hallucinated numbers.

    Returns
    -------
    int – count of ungrounded numeric claims detected.
    """
    ungrounded    = 0
    chunk_no_comma = chunk_text.replace(",", "")
    checked_fields = [
        "revenue_items", "profitability_items",
        "cash_flow_items", "balance_sheet_items",
    ]

    for field in checked_fields:
        for item in facts_bag.get(field, []):
            value_str = str(item.get("value", "") or "").strip()
            if not value_str or value_str.lower() in ("null", "none", "—", "-", "n/a"):
                continue

            # Extract numeric digit sequences (≥2 chars after stripping commas).
            nums = [
                m.group(1).replace(",", "")
                for m in _VALUE_NUM_RE.finditer(value_str)
                if len(m.group(1).replace(",", "")) >= 2
            ]
            if not nums:
                continue

            if not any(n in chunk_no_comma for n in nums):
                ungrounded += 1
                logger.warning(
                    "Grounding miss: %s value=%r not found in chunk (chunk_len=%d)",
                    field, value_str[:60], len(chunk_text),
                )

    return ungrounded


def _run_map_reduce(
    chunks: List[str],
    ticker: str,
    filing_type: str,
    period_end: str,
    company_name: str,
    llm,
    quarter_label: Optional[str] = None,
) -> dict:
    """
    Map step: extract facts from up to MAX_CHUNKS chunks.
    Reduce step: combine into ReportData/v1 JSON.

    quarter_label: if provided (e.g. "2025 Q3"), replaces filing_type in the
    reduce prompt so the LLM embeds the quarter label in the report cover
    rather than the raw SEC form type (10-Q / 10-K).
    """
    display_type = quarter_label if quarter_label else filing_type
    facts_bags: List[dict] = []
    for i, chunk in enumerate(chunks[:6]):
        try:
            prompt   = MAP_PROMPT_TEMPLATE.format(chunk_text=chunk)
            response = llm.complete(
                prompt,
                max_tokens=2_000,
                system_prompt=ANTI_HALLUCINATION_SYSTEM_PROMPT,
            )
            facts   = _parse_llm_json(response)
            missed  = _grounding_check(facts, chunk)
            facts_bags.append(facts)
            logger.info(
                "Map chunk %d/%d: OK (grounding_misses=%d)",
                i + 1, min(len(chunks), 6), missed,
            )
        except LLMAuthError:
            # Auth failure is unrecoverable — abort immediately, do not try
            # remaining chunks or proceed to reduce with empty bag.
            logger.error("Map chunk %d/%d: LLMAuthError — aborting map-reduce",
                         i + 1, min(len(chunks), 6))
            raise
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
        filing_type=display_type,
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
    quarter_label: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main orchestration function.

    Parameters
    ----------
    ticker        : stock ticker symbol
    filing_id     : SEC accession number (with dashes)
    force         : ignore cached output and regenerate
    render_fn     : callable(template_name, **ctx) → str; pass flask.render_template
    quarter_label : user-facing period label, e.g. "2025 Q3". When provided it
                    replaces the raw SEC form type in the LLM prompt and report
                    cover, so users never see "10-Q" or "10-K".

    Returns
    -------
    dict with keys: status, filing_id, url_html, url_json
              or  : status, error, code
    """
    ticker = ticker.upper().strip()

    logger.info(
        "STEP 0 begin generate_report: ticker=%s filing_id=%s force=%s "
        "quarter_label=%r [MEM: %s MB]",
        ticker, filing_id, force, quarter_label, _rss_mb(),
    )

    # STEP 2: acquire DB generation lock (5-minute TTL)
    logger.info("STEP 2 begin acquire_lock: key=%s", filing_id)
    if not acquire_lock(filing_id, ttl_seconds=300):
        logger.warning("STEP 2 lock busy: filing_id=%s", filing_id)
        return {
            "status":      "error",
            "error":       "Generation already in progress for this filing",
            "code":        409,
            "retry_after": 15,
        }
    logger.info("STEP 2 done acquire_lock: key=%s", filing_id)

    try:
        return _generate_inner(ticker, filing_id, force, render_fn, quarter_label)
    finally:
        release_lock(filing_id)


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


def _generate_inner(ticker, filing_id, force, render_fn, quarter_label=None):
    t_total = time.monotonic()
    logger.info(
        "STEP 0 done / _generate_inner begin: ticker=%s filing_id=%s [MEM: %s MB]",
        ticker, filing_id, _rss_mb(),
    )
    with get_db() as db:

        # ------------------------------------------------------------------ #
        # STEP 1: DB layered cache check
        # ------------------------------------------------------------------ #
        logger.info("STEP 1 begin DB cache check: ticker=%s filing_id=%s", ticker, filing_id)
        t1 = time.monotonic()
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
                logger.info(
                    "STEP 1 done DB cache check: full cache hit → early return [%.2fs]",
                    time.monotonic() - t1,
                )
                return {
                    "status":    "cached",
                    "filing_id": filing_id,
                    "url_html":  f"/reports/{ticker}/{filing_id}",
                    "url_json":  f"/api/reports/{ticker}/{filing_id}",
                }

        skip_llm      = (not force
                         and existing_output is not None
                         and existing_output.report_json is not None)
        skip_analysis = (not force
                         and existing_output is not None
                         and existing_output.market_analysis_json is not None)
        logger.info(
            "STEP 1 done DB cache check: skip_llm=%s skip_analysis=%s [%.2fs]",
            skip_llm, skip_analysis, time.monotonic() - t1,
        )

        # ------------------------------------------------------------------ #
        # STEP 2 (SEC fetch + text extraction + LLM) — skipped when cached
        # ------------------------------------------------------------------ #
        fd          = None
        company     = None
        filing_text = None

        if not skip_llm:
            # Resolve filing metadata (cache hit expected here)
            logger.info(
                "STEP 2 begin list_filings: ticker=%s (looking for filing_id=%s)",
                ticker, filing_id,
            )
            t2 = time.monotonic()
            try:
                filings = sec_list_filings(ticker)
            except (ValueError, RuntimeError) as exc:
                logger.error("STEP 2 failed list_filings [%.2fs]: %s",
                             time.monotonic() - t2, exc)
                return {"status": "error", "error": str(exc), "code": 502}

            fd = next((f for f in filings if f["filing_id"] == filing_id), None)
            del filings   # free 2-4 MB submissions list immediately
            if not fd:
                logger.error(
                    "STEP 2 failed: filing '%s' not found for ticker '%s'",
                    filing_id, ticker,
                )
                return {
                    "status": "error",
                    "error":  f"Filing '{filing_id}' not found for ticker '{ticker}'.",
                    "code":   404,
                }
            logger.info(
                "STEP 2 done list_filings: filing_type=%s period_end=%s "
                "source_url=%.80s [%.2fs]",
                fd["filing_type"], fd.get("period_end"), fd.get("source_url", ""),
                time.monotonic() - t2,
            )

            # DB upsert company + filing, check FilingText cache
            logger.info("STEP 3 begin DB upsert + FilingText check")
            t3 = time.monotonic()
            company    = _upsert_company(db, ticker,
                                         cik=fd.get("cik"),
                                         name=fd.get("company_name"),
                                         exchange=fd.get("exchange"))
            filing_rec = _upsert_filing(db, company, fd)
            filing_text = db.query(FilingText).filter_by(filing_id=filing_rec.id).first()
            filing_text_cached = filing_text is not None and not force
            logger.info(
                "STEP 3 done DB upsert + FilingText check: filing_text_cached=%s [%.2fs]",
                filing_text_cached, time.monotonic() - t3,
            )

            if not filing_text or force:
                # STEP 3b: Fetch filing content from SEC
                source_url = fd.get("source_url", "")
                logger.info(
                    "STEP 3b begin fetch_filing_content [MEM: %s MB]: url=%.120s",
                    _rss_mb(), source_url,
                )
                t3b = time.monotonic()
                try:
                    raw = fetch_filing_content(source_url)
                except RuntimeError as exc:
                    logger.error(
                        "STEP 3b failed fetch_filing_content [%.2fs]: %s",
                        time.monotonic() - t3b, exc,
                    )
                    return {"status": "error", "error": str(exc), "code": 502}
                logger.info(
                    "STEP 3b done fetch_filing_content: html=%d chars text=%d chars "
                    "[%.2fs] [MEM: %s MB]",
                    len(raw.get("html", "")), len(raw.get("text", "")),
                    time.monotonic() - t3b, _rss_mb(),
                )

                # STEP 3b.5: fetch deterministic XBRL facts for cross-check
                if fd.get("cik"):
                    logger.info(
                        "STEP 3b.5 begin fetch_company_facts: CIK=%s accn=%s",
                        fd["cik"], filing_id,
                    )
                    t3b5 = time.monotonic()
                    facts_data = fetch_company_facts(fd["cik"])
                    if facts_data:
                        xbrl_facts = extract_facts_for_period(facts_data, filing_id)
                        found_count = sum(1 for v in xbrl_facts.values() if v is not None)
                        logger.info(
                            "STEP 3b.5 done: %d/%d XBRL facts found for this filing "
                            "[%.2fs]: %s",
                            found_count, len(xbrl_facts),
                            time.monotonic() - t3b5,
                            {k: v for k, v in xbrl_facts.items() if v is not None},
                        )
                    else:
                        xbrl_facts = {}
                        logger.info(
                            "STEP 3b.5 done: companyfacts unavailable [%.2fs]",
                            time.monotonic() - t3b5,
                        )
                    facts_data = None   # free large JSON immediately

                # STEP 4-7: prestrip → html_to_text → xbrl_filter → extract → chunk
                # (detailed STEP 4-7 logs emitted by extract_text.prepare_filing_text)
                result = prepare_filing_text(raw.get("html", ""), raw.get("text", ""))

                _relevant = result["relevant_text"]
                _chunks   = result["chunks"]
                raw = result = None  # noqa: F841  — free raw HTML + full clean_text
                logger.info(
                    "STEP 7 done (pipeline): relevant=%d chars chunks=%d [MEM: %s MB]",
                    len(_relevant), len(_chunks), _rss_mb(),
                )

                if filing_text:
                    filing_text.raw_html     = ""
                    filing_text.clean_text   = _relevant
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

            # STEP 8: LLM map-reduce
            llm    = get_llm_client()
            chunks = (filing_text.chunks_json or []) if filing_text else []
            logger.info(
                "STEP 8 begin LLM map-reduce: model=%s chunks=%d ticker=%s "
                "filing_type=%s [MEM: %s MB]",
                os.getenv("AI_MODEL", "mock"), len(chunks), ticker,
                fd["filing_type"], _rss_mb(),
            )
            t8 = time.monotonic()
            try:
                report_json = _run_map_reduce(
                    chunks        = chunks,
                    ticker        = ticker,
                    filing_type   = fd["filing_type"],
                    period_end    = fd.get("period_end", ""),
                    company_name  = fd.get("company_name", ticker),
                    llm           = llm,
                    quarter_label = quarter_label,
                )
                logger.info(
                    "STEP 8 done LLM map-reduce: sections=%d [%.2fs] [MEM: %s MB]",
                    len(report_json.get("sections", [])),
                    time.monotonic() - t8, _rss_mb(),
                )
            except LLMAuthError as exc:
                logger.error(
                    "STEP 8 failed LLM_AUTH [%.2fs]: %s",
                    time.monotonic() - t8, exc,
                )
                return {
                    "status":  "error",
                    "error":   "LLM_AUTH",
                    "message": str(exc),
                    "hint":    "Check ANTHROPIC_API_KEY in production env",
                    "code":    500,
                }
            except json.JSONDecodeError as exc:
                logger.error("STEP 8 failed LLM map-reduce (JSON decode) [%.2fs]: %s",
                             time.monotonic() - t8, exc)
                return {"status": "error", "error": f"LLM returned invalid JSON: {exc}", "code": 500}
            except Exception as exc:
                logger.exception("STEP 8 failed LLM map-reduce [%.2fs]: %s",
                                 time.monotonic() - t8, exc)
                return {"status": "error", "error": f"LLM error: {exc}", "code": 500}

            # STEP 9: validate JSON schema
            logger.info("STEP 9 begin schema validation")
            t9 = time.monotonic()
            errors = validate_report_json(report_json)
            if errors:
                logger.warning(
                    "STEP 9 schema errors (attempting 1-shot fix): %s", errors
                )
                try:
                    fix_prompt  = FIX_SCHEMA_PROMPT.format(
                        errors="\n".join(errors),
                        current_json=json.dumps(report_json, ensure_ascii=False),
                    )
                    report_json = _parse_llm_json(llm.complete(fix_prompt, max_tokens=8_000))
                    errors      = validate_report_json(report_json)
                except Exception as fix_exc:
                    logger.error("STEP 9 fix attempt failed: %s", fix_exc)
                if errors:
                    logger.error("STEP 9 still invalid after fix: %s", errors)
                else:
                    logger.info("STEP 9 fix succeeded")
            else:
                logger.info("STEP 9 done schema validation: OK [%.2fs]",
                            time.monotonic() - t9)

            # STEP 10: sanitize insights HTML
            logger.info("STEP 10 begin sanitize_report_json")
            t10 = time.monotonic()
            insight_count = sum(
                len(s.get("insights", [])) for s in report_json.get("sections", [])
            )
            report_json = sanitize_report_json(report_json)
            logger.info(
                "STEP 10 done sanitize_report_json: %d insights sanitized [%.2fs] [MEM: %s MB]",
                insight_count, time.monotonic() - t10, _rss_mb(),
            )

        else:
            report_json = existing_output.report_json
            llm         = get_llm_client()
            logger.info("STEP 8-10 skipped (report_json cached)")

        # Ensure filing_rec and company are loaded even in skip_llm path
        if filing_rec is None:
            filing_rec = db.query(Filing).filter_by(filing_id=filing_id).first()
        if filing_rec and company is None:
            company = filing_rec.company

        # ------------------------------------------------------------------ #
        # STEP 11 (part a): Earnings Expectations & Market Reaction Engine
        # ------------------------------------------------------------------ #
        if not skip_analysis:
            logger.info("STEP 11a begin earnings/market analysis: ticker=%s", ticker)
            t11a = time.monotonic()

            consensus = _fetch_consensus_safe(ticker)
            actuals   = extract_actuals(report_json)
            surprise  = compute_all_surprises(actuals, consensus)

            market_reaction = _run_market_reaction(
                actuals, consensus, surprise, report_json, llm
            )

            narrative_change = None
            if filing_rec and company:
                narrative_change = run_narrative_change(
                    db                   = db,
                    company_id           = company.id,
                    current_filing_db_id = filing_rec.id,
                    current_report_json  = report_json,
                    llm                  = llm,
                )

            logger.info(
                "STEP 11a done earnings/market analysis [%.2fs] [MEM: %s MB]",
                time.monotonic() - t11a, _rss_mb(),
            )
        else:
            consensus        = existing_output.consensus_json or {}
            actuals          = extract_actuals(report_json)
            surprise         = existing_output.surprise_json or {}
            market_reaction  = existing_output.market_analysis_json or {}
            narrative_change = existing_output.narrative_change_json
            logger.info("STEP 11a skipped (analysis cached)")

        # ------------------------------------------------------------------ #
        # STEP 11 (part b): Render HTML
        # ------------------------------------------------------------------ #
        need_render = not skip_llm or not skip_analysis or not (
            existing_output and existing_output.rendered_html
        )

        if need_render:
            logger.info("STEP 11b begin render_template: ticker=%s", ticker)
            t11b = time.monotonic()
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
                logger.info(
                    "STEP 11b done render_template: %d chars [%.2fs]",
                    len(rendered_html), time.monotonic() - t11b,
                )
            except Exception as exc:
                logger.error("STEP 11b failed render_template [%.2fs]: %s",
                             time.monotonic() - t11b, exc)
                rendered_html = (
                    f"<html><body><pre>Rendering error: {exc}</pre></body></html>"
                )
        else:
            rendered_html = existing_output.rendered_html
            logger.info("STEP 11b skipped (rendered_html cached)")

        # ------------------------------------------------------------------ #
        # STEP 12: Persist everything to DB
        # ------------------------------------------------------------------ #
        logger.info("STEP 12 begin DB persist: ticker=%s filing_id=%s", ticker, filing_id)
        t12 = time.monotonic()
        llm_model = "mock"
        if os.getenv("AI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"):
            llm_model = os.getenv("AI_MODEL", "claude-opus-4-6")

        if existing_output and (force or skip_llm):
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
        logger.info(
            "STEP 12 done DB persist: status=%s [%.2fs] [MEM: %s MB] "
            "[total elapsed: %.1fs]",
            status, time.monotonic() - t12, _rss_mb(),
            time.monotonic() - t_total,
        )
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
        if not output:
            return None
        html = output.rendered_html
        # Treat render-error placeholder as uncached so the user is prompted to regenerate
        if html and html.startswith("<html><body><pre>Rendering error:"):
            return None
        return html
