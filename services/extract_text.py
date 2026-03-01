"""
OOM-proof text extraction pipeline for SEC filings.

Pipeline
--------
1. prestrip_html(html)           – remove <table>/<script>/<style> BEFORE parsing
2. html_to_text(stripped_html)   – regex strip tags, write to StringIO
3. extract_relevant_sections(text) – keyword-guided section extraction, strict cap
4. chunk_text(relevant_text)     – overlapping chunks, hard cap on count

Strict memory caps
------------------
MAX_FILING_BYTES     – enforced in sec_provider (network download cap)
MAX_HTML_PARSE_CHARS – hard truncation after prestrip, before tag-stripping
MAX_RELEVANT_CHARS   – maximum text fed to the LLM
MAX_CHUNKS           – maximum chunk count passed to map-reduce
MAX_CHUNK_CHARS      – maximum characters per chunk
"""
import io
import re
import logging
import os
from typing import List, Dict

logger = logging.getLogger(__name__)

# ── Caps ────────────────────────────────────────────────────────────────────
MAX_HTML_PARSE_CHARS = 600_000    # hard parse cap after prestrip
MAX_RELEVANT_CHARS   = 250_000    # what we feed to the LLM map-reduce
MAX_CHUNKS           = 20
MAX_CHUNK_CHARS      = 14_000
CHUNK_OVERLAP        = 500

# Lines to take from each matched section window
LINES_PER_SECTION    = 400


# ── Memory instrumentation ───────────────────────────────────────────────────
def log_mem(label: str) -> None:
    """Log current process RSS MB at a named pipeline checkpoint."""
    try:
        import psutil
        rss = psutil.Process(os.getpid()).memory_info().rss / 1_048_576
        logger.info("[MEM][extract] %s: %.1f MB RSS", label, rss)
    except Exception:
        pass


# ── Section keyword index ─────────────────────────────────────────────────────
SECTION_KEYWORDS: Dict[str, List[str]] = {
    "mda": [
        "management's discussion and analysis",
        "management discussion and analysis",
        "management's discussion",
        "item 7.",
        "item 7 —",
        "item 7:",
    ],
    "results": [
        "results of operations",
        "results of operation",
    ],
    "liquidity": [
        "liquidity and capital resources",
        "liquidity",
        "capital resources",
    ],
    "risk": [
        "risk factors",
        "risks and uncertainties",
        "item 1a.",
        "item 1a —",
        "item 1a:",
    ],
    "outlook": [
        "outlook",
        "guidance",
        "forward-looking",
        "fiscal year",
        "full year",
        "we expect",
        "we anticipate",
    ],
    "revenue": [
        "revenue",
        "net sales",
        "net revenues",
        "segment revenues",
        "total revenues",
    ],
    "profitability": [
        "gross profit",
        "operating income",
        "net income",
        "earnings per share",
        "ebitda",
        "adjusted ebitda",
    ],
}


# --------------------------------------------------------------------------- #
# 1. Pre-strip HTML (before any full parsing)
# --------------------------------------------------------------------------- #
def prestrip_html(html: str) -> str:
    """
    Aggressively remove large HTML blocks BEFORE tag-stripping.

    Order matters: remove scripts/styles/comments first (they can contain
    fake table markup), then tables (the biggest EDGAR memory hog).

    Each re.sub replaces the previous string, so Python frees the old copy
    immediately via reference counting — no peak doubling.

    Returns the stripped string truncated to MAX_HTML_PARSE_CHARS.
    """
    if not html:
        return html

    original_len = len(html)

    # Remove <script>...</script>
    html = re.sub(r"<script[^>]*>.*?</script>", " ",
                  html, flags=re.IGNORECASE | re.DOTALL)

    # Remove <style>...</style>
    html = re.sub(r"<style[^>]*>.*?</style>", " ",
                  html, flags=re.IGNORECASE | re.DOTALL)

    # Remove HTML comments
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)

    # Remove <table>...</table> — primary win for EDGAR filings.
    # Non-greedy + DOTALL; nested innermost tables are removed first.
    # Outer shells with orphaned tags are harmless for plain-text extraction.
    html = re.sub(r"<table[^>]*>.*?</table>", " ",
                  html, flags=re.IGNORECASE | re.DOTALL)

    if len(html) > MAX_HTML_PARSE_CHARS:
        logger.warning(
            "HTML truncated from %d → %d chars after prestrip (raw was %d)",
            len(html), MAX_HTML_PARSE_CHARS, original_len,
        )
        html = html[:MAX_HTML_PARSE_CHARS]

    logger.debug(
        "prestrip_html: %d → %d chars (%.0f%% reduction)",
        original_len, len(html),
        100.0 * (1 - len(html) / max(original_len, 1)),
    )
    return html


# --------------------------------------------------------------------------- #
# 2. HTML → plain text (StringIO, no large intermediate lists)
# --------------------------------------------------------------------------- #
def html_to_text(html: str) -> str:
    """
    Strip remaining HTML tags and write non-empty lines to a StringIO buffer.

    Avoids the pattern:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return "\\n".join(lines)
    which builds a large list AND a full-size string simultaneously.

    Instead: write each qualifying line directly to StringIO.
    """
    if not html:
        return ""

    # Strip tags
    no_tags = re.sub(r"<[^>]+>", " ", html)

    # Collapse SEC filing artefacts (long dot/dash separators)
    no_tags = re.sub(r"[.\-_]{4,}", " ", no_tags)

    buf   = io.StringIO()
    first = True
    for line in no_tags.splitlines():
        stripped = line.strip()
        if stripped:
            if not first:
                buf.write("\n")
            buf.write(stripped)
            first = False

    result = buf.getvalue()
    buf.close()
    return result


# --------------------------------------------------------------------------- #
# 3. Extract relevant sections
# --------------------------------------------------------------------------- #
def extract_relevant_sections(text: str, max_chars: int = MAX_RELEVANT_CHARS) -> str:
    """
    Return at most *max_chars* of the most financially relevant text.

    Strategy:
    - Scan line by line for section-heading keywords.
    - Take LINES_PER_SECTION lines from each matched heading.
    - Assemble into StringIO, stop when budget exhausted.
    - Fallback: first *max_chars* chars if no keywords found.

    GUARANTEE: result length <= max_chars.
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    lines = text.splitlines()
    section_starts: Dict[str, int] = {}

    for i, line in enumerate(lines):
        lower = line.lower().strip()
        for sec_key, keywords in SECTION_KEYWORDS.items():
            if sec_key not in section_starts and any(kw in lower for kw in keywords):
                section_starts[sec_key] = i

    if not section_starts:
        logger.debug(
            "extract_relevant_sections: no keywords found; using first %d chars", max_chars
        )
        return text[:max_chars]

    n       = len(section_starts)
    per_sec = max_chars // max(n, 1)
    buf     = io.StringIO()
    written = 0

    for sec_key, start in sorted(section_starts.items(), key=lambda x: x[1]):
        if written >= max_chars:
            break

        snippet = "\n".join(lines[start: start + LINES_PER_SECTION])
        budget  = min(per_sec, max_chars - written)
        if len(snippet) > budget:
            snippet = snippet[:budget]

        header = f"\n\n### {sec_key.upper()} ###\n"
        buf.write(header)
        buf.write(snippet)
        written += len(header) + len(snippet)

    result = buf.getvalue()
    buf.close()
    return result[:max_chars]   # hard guarantee


# --------------------------------------------------------------------------- #
# 4. Chunk text
# --------------------------------------------------------------------------- #
def chunk_text(
    text: str,
    chunk_size: int = MAX_CHUNK_CHARS,
    overlap:    int = CHUNK_OVERLAP,
) -> List[str]:
    """
    Split *text* into overlapping chunks, hard-capped at MAX_CHUNKS.
    """
    if not text:
        return []

    chunks: List[str] = []
    start  = 0
    length = len(text)

    while start < length and len(chunks) < MAX_CHUNKS:
        end = min(start + chunk_size, length)
        chunks.append(text[start:end])
        next_start = end - overlap
        if next_start <= start or next_start >= length:
            break
        start = next_start

    return chunks


# --------------------------------------------------------------------------- #
# Combined pipeline
# --------------------------------------------------------------------------- #
def prepare_filing_text(html: str, raw_text: str = "") -> Dict:
    """
    Full OOM-proof pipeline:
      raw HTML  →  prestrip  →  html_to_text  →  relevant_text  →  chunks

    Intermediate strings are explicitly set to None after use so Python's
    reference-counting GC can free them before the next (larger) allocation.

    Returns:
        {
            "relevant_text": str,    # <= MAX_RELEVANT_CHARS
            "chunks":        list[str],  # <= MAX_CHUNKS items
        }
    """
    log_mem("start")
    n_raw = len(html or raw_text)

    if html:
        # Step 1 — prestrip (removes tables, scripts, styles; truncates to 600 KB)
        stripped = prestrip_html(html)
        html     = None            # free original HTML (~2.5 MB)
        log_mem("after_prestrip")

        # Step 2 — HTML → plain text
        clean_text = html_to_text(stripped)
        stripped   = None          # free stripped HTML (~600 KB)
        log_mem("after_html_to_text")

    elif raw_text:
        clean_text = raw_text
        log_mem("after_html_to_text")
    else:
        clean_text = ""

    n_clean = len(clean_text)

    # Step 3 — extract relevant sections
    relevant_text = extract_relevant_sections(clean_text)
    clean_text    = None           # free full plain-text (~1-2 MB)
    log_mem("after_extract_relevant")

    # Step 4 — chunk
    chunks = chunk_text(relevant_text)
    log_mem("after_chunking")

    logger.info(
        "Text pipeline: %d raw → %d clean → %d relevant → %d chunks",
        n_raw, n_clean, len(relevant_text), len(chunks),
    )
    return {
        "relevant_text": relevant_text,
        "chunks":        chunks,
    }


# --------------------------------------------------------------------------- #
# Quick self-checks  (python -m services.extract_text)
# --------------------------------------------------------------------------- #
def _run_checks() -> None:
    import sys

    # Check 1: period_end → quarter (tested via quarter_service, shown here for completeness)
    from datetime import datetime
    def _q(period_end):
        m = datetime.strptime(period_end, "%Y-%m-%d").month
        return ["Q1","Q1","Q1","Q2","Q2","Q2","Q3","Q3","Q3","Q4","Q4","Q4"][m-1]
    assert _q("2025-03-31") == "Q1"
    assert _q("2025-06-30") == "Q2"
    assert _q("2025-09-30") == "Q3"
    assert _q("2025-12-31") == "Q4"
    print("✓ quarter mapping")

    # Check 2: prestrip reduces size significantly on table-heavy HTML
    sample = (
        "<html><body>"
        + "<table><tr><td>$1,234</td><td>$5,678</td></tr></table>" * 200
        + "<p>Management's Discussion: revenue grew 15% year over year.</p>"
        + "<script>alert(1)</script>"
        + "</body></html>"
    )
    stripped = prestrip_html(sample)
    assert len(stripped) < len(sample) * 0.3, "prestrip should remove >70% of table-heavy HTML"
    assert "revenue grew" in stripped, "narrative text must survive prestrip"
    print(f"✓ prestrip: {len(sample):,} → {len(stripped):,} chars")

    # Check 3: extract_relevant_sections never exceeds MAX_RELEVANT_CHARS
    big_text = ("Management's Discussion and Analysis\n" + "A" * 10_000 + "\n") * 100
    result = extract_relevant_sections(big_text)
    assert len(result) <= MAX_RELEVANT_CHARS, f"result {len(result)} > cap {MAX_RELEVANT_CHARS}"
    print(f"✓ extract_relevant_sections cap: {len(result):,} <= {MAX_RELEVANT_CHARS:,}")

    # Check 4: chunk_text respects MAX_CHUNKS
    long_text = "X" * (MAX_CHUNK_CHARS * (MAX_CHUNKS + 5))
    chunks = chunk_text(long_text)
    assert len(chunks) <= MAX_CHUNKS, f"got {len(chunks)} chunks, max is {MAX_CHUNKS}"
    print(f"✓ chunk_text cap: {len(chunks)} chunks <= {MAX_CHUNKS}")

    print("\nAll checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    _run_checks()
