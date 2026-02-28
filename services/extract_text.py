"""
Text extraction pipeline for SEC filings.

Steps
-----
1. HTML  → clean plain-text  (via BeautifulSoup if available, regex fallback)
2. plain-text → relevant sections  (keyword-guided selection)
3. relevant text → overlapping chunks  (for map-step LLM calls)
"""
import re
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup
    _BS4 = True
except ImportError:
    _BS4 = False
    logger.warning("beautifulsoup4 not installed – falling back to regex HTML stripping.")

# ---- tuneable constants --------------------------------------------------- #
CHUNK_SIZE    = 3_500   # chars per chunk sent to the map-LLM
CHUNK_OVERLAP = 400     # overlap between adjacent chunks
MAX_RELEVANT  = 55_000  # max chars kept after section extraction
LINES_PER_SECTION = 220 # how many lines to take from each matched section
# Hard cap on HTML fed into any parser; matches the download cap in sec_provider.
MAX_HTML_PARSE = 3 * 1024 * 1024
# Below this threshold we use BS4 (accurate script/style removal).
# Above it we use regex — 5-10× less peak memory, safe for OOM-constrained workers.
_BS4_MAX_INPUT = 200_000  # 200 KB


# ---- section keyword index ------------------------------------------------- #
SECTION_KEYWORDS: Dict[str, List[str]] = {
    "mda": [
        "management's discussion", "management discussion",
        "results of operations", "discussion and analysis",
    ],
    "revenue": [
        "revenue", "net sales", "net revenues", "segment revenues",
        "total revenues",
    ],
    "profitability": [
        "gross profit", "operating income", "net income",
        "earnings per share", "ebitda", "adjusted ebitda",
    ],
    "cash_flow": [
        "cash flows", "liquidity", "capital resources", "free cash flow",
        "cash provided by operating",
    ],
    "guidance": [
        "outlook", "guidance", "forward-looking", "fiscal year",
        "full year", "expect to", "we anticipate",
    ],
    "risk_factors": [
        "risk factors", "risks and uncertainties",
        "forward-looking statements",
    ],
    "balance_sheet": [
        "total assets", "total liabilities", "stockholders equity",
        "shareholders equity", "long-term debt",
    ],
}


# --------------------------------------------------------------------------- #
# 1. HTML → plain text
# --------------------------------------------------------------------------- #
def html_to_text(html: str) -> str:
    """Convert an HTML string to clean plain text.

    For inputs <= _BS4_MAX_INPUT (200 KB): use BeautifulSoup for accurate
    script/style removal.  For larger inputs (all real EDGAR filings after
    truncation): use regex, which uses ~2× the input size in peak memory vs
    5–10× for BeautifulSoup with html.parser.
    """
    if not html:
        return ""

    if len(html) > MAX_HTML_PARSE:
        logger.warning(
            "HTML input truncated from %d to %d chars before parsing",
            len(html), MAX_HTML_PARSE,
        )
        html = html[:MAX_HTML_PARSE]

    if _BS4 and len(html) <= _BS4_MAX_INPUT:
        try:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup.find_all(["script", "style", "header", "footer", "nav", "noscript"]):
                tag.decompose()
            raw = soup.get_text(separator="\n", strip=True)
        except Exception:
            raw = re.sub(r"<[^>]+>", " ", html)
    else:
        # Regex path: safe for large EDGAR filings, low memory overhead
        raw = re.sub(r"<[^>]+>", " ", html)

    # Collapse SEC filing artefacts: long runs of dots / dashes used as separators
    raw = re.sub(r"[.\-_]{4,}", " ", raw)
    # Collapse whitespace runs
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 2. Extract most-relevant sections
# --------------------------------------------------------------------------- #
def extract_relevant_sections(text: str, max_chars: int = MAX_RELEVANT) -> str:
    """
    Return a concatenation of the most financially relevant sections.
    Falls back to the first *max_chars* characters if no sections are found.
    """
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
        logger.debug("No named sections found; using first %d chars.", max_chars)
        return text[:max_chars]

    chunks: List[str] = []
    chars_used = 0
    per_section_max = max_chars // max(len(section_starts), 1)

    for sec_key, start_idx in sorted(section_starts.items(), key=lambda x: x[1]):
        section_lines = lines[start_idx: start_idx + LINES_PER_SECTION]
        snippet = "\n".join(section_lines)[:per_section_max]
        chunks.append(f"\n\n### {sec_key.upper()} ###\n{snippet}")
        chars_used += len(snippet)
        if chars_used >= max_chars:
            break

    combined = "".join(chunks)
    return combined[:max_chars]


# --------------------------------------------------------------------------- #
# 3. Chunking
# --------------------------------------------------------------------------- #
def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split *text* into overlapping chunks of ≤ *chunk_size* characters."""
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    length = len(text)

    while start < length:
        end = min(start + chunk_size, length)
        chunks.append(text[start:end])
        start = end - overlap
        if start <= 0 or start >= length:
            break

    return chunks


# --------------------------------------------------------------------------- #
# Combined pipeline
# --------------------------------------------------------------------------- #
def prepare_filing_text(html: str, raw_text: str = "") -> Dict:
    """
    Full pipeline:
      raw HTML (or plain text)  →  clean_text  →  relevant_text  →  chunks

    Returns:
        {
            "clean_text":    str,   # full cleaned text
            "relevant_text": str,   # section-filtered subset
            "chunks":        list[str],
        }
    """
    if html:
        clean_text = html_to_text(html)
    elif raw_text:
        clean_text = raw_text
    else:
        clean_text = ""

    relevant_text = extract_relevant_sections(clean_text)
    chunks = chunk_text(relevant_text)

    logger.info(
        "Text pipeline: %d raw chars → %d clean → %d relevant → %d chunks",
        len(html or raw_text), len(clean_text), len(relevant_text), len(chunks),
    )
    return {
        "clean_text":    clean_text,
        "relevant_text": relevant_text,
        "chunks":        chunks,
    }
