"""
Actual Metrics Extractor — deterministic, no LLM.

Pulls structured numeric values out of an already-generated ReportData/v1 JSON
by searching through s2 (metrics_table), s4 (profitability_cards), and s7 (guidance).

Public API
----------
extract_actuals(report_json: dict) -> dict
    Returns:
    {
      "eps_actual":         float | None,
      "revenue_actual":     float | None,
      "ebitda_actual":      float | None,
      "guidance_midpoint":  float | None,
    }
    Never raises.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Hebrew metric name fragments to match against row["metric"] or card["label"]
_EPS_HINTS      = ("eps", "earnings per share", "רווח למניה", "eps מדולל", "eps בסיסי")
_REVENUE_HINTS  = ("הכנסות", "revenue", "net revenues", "net sales", "מכירות")
_EBITDA_HINTS   = ("ebitda", "adjusted ebitda", "ebitda מותאם")
_GUIDE_HINTS    = ("guidance", "outlook", "תחזית", "full year", "שנתי", "annual")


# =========================================================================== #
# Value parser
# =========================================================================== #

def _parse_value(s: str) -> Optional[float]:
    """
    Convert a formatted financial string to a raw float (USD).

    Handles:
      "$4.8B"   → 4_800_000_000.0
      "$980M"   → 980_000_000.0
      "$1.05"   → 1.05
      "−$340M"  → -340_000_000.0  (Unicode minus)
      "4.8B"    → 4_800_000_000.0
      "43.8%"   → 43.8   (percentage kept as-is)
      "1.2x"    → None   (ratios not useful as actuals)
    """
    if not isinstance(s, str):
        return None

    text = s.strip().replace("\u2212", "-").replace("−", "-").replace(",", "")

    # Reject ratios / ranges
    if re.search(r"[x×\-]{1,3}\d", text.lower()) and "%" not in text:
        # Allow plain negatives like "-$340M" but reject "2.5x" or "19-20B"
        if re.search(r"\d\s*[x×]|\d\s*[-–]\s*\d.*[bm]", text, re.I):
            return None

    # Extract sign
    sign = -1.0 if text.startswith("-") else 1.0
    text = text.lstrip("-").lstrip()

    # Strip currency symbols
    text = text.lstrip("$€£¥").strip()

    # Percentage
    if text.endswith("%"):
        try:
            return float(text[:-1])
        except ValueError:
            return None

    # Multiplier suffix
    multipliers = {"b": 1e9, "m": 1e6, "k": 1e3, "t": 1e12}
    if text and text[-1].lower() in multipliers:
        mult = multipliers[text[-1].lower()]
        try:
            return sign * float(text[:-1]) * mult
        except ValueError:
            return None

    # Plain number
    try:
        return sign * float(text)
    except ValueError:
        return None


# =========================================================================== #
# Section walkers
# =========================================================================== #

def _find_in_metrics_table(sections: list, hints: tuple) -> Optional[float]:
    """Search s2 metrics_table rows for a metric matching any hint."""
    for sec in sections:
        if sec.get("type") != "metrics_table":
            continue
        for row in sec.get("rows", []):
            metric = (row.get("metric") or "").lower()
            if any(h in metric for h in hints):
                return _parse_value(row.get("current") or "")
    return None


def _find_in_profitability_cards(sections: list, hints: tuple) -> Optional[float]:
    """Search s4 profitability_cards for a card label matching any hint."""
    for sec in sections:
        if sec.get("type") != "profitability_cards":
            continue
        for card in sec.get("cards", []):
            label = (card.get("label") or "").lower()
            if any(h in label for h in hints):
                return _parse_value(card.get("value") or "")
    return None


def _find_guidance_midpoint(sections: list) -> Optional[float]:
    """
    Scan s7 guidance items for a revenue / earnings guidance and extract
    a rough midpoint from strings like "$19–20B" or "$4.6-4.8B".
    """
    for sec in sections:
        if sec.get("type") != "guidance":
            continue
        for item in sec.get("items", []):
            topic     = (item.get("topic") or "").lower()
            statement = (item.get("statement") or "")
            if not any(h in topic for h in _GUIDE_HINTS + _REVENUE_HINTS):
                continue
            # Try to find a range like "19-20B" or "$4.6–4.8B"
            m = re.search(
                r"\$?([\d.]+)\s*[-–]\s*\$?([\d.]+)\s*([bBmMtT]?)",
                statement,
            )
            if m:
                lo_str  = m.group(1) + m.group(3)
                hi_str  = m.group(2) + m.group(3)
                lo, hi  = _parse_value(lo_str), _parse_value(hi_str)
                if lo is not None and hi is not None:
                    return (lo + hi) / 2
            # Single value
            m = re.search(r"\$?([\d.]+)\s*([bBmMtT])", statement)
            if m:
                return _parse_value(m.group(1) + m.group(2))
    return None


# =========================================================================== #
# Public API
# =========================================================================== #

def extract_actuals(report_json: dict) -> dict:
    """
    Pull actual reported metrics from a ReportData/v1 JSON.
    Uses only deterministic parsing — never calls LLM.
    """
    try:
        sections = report_json.get("sections") or []

        eps      = _find_in_metrics_table(sections, _EPS_HINTS)
        revenue  = _find_in_metrics_table(sections, _REVENUE_HINTS)
        ebitda   = (
            _find_in_metrics_table(sections, _EBITDA_HINTS)
            or _find_in_profitability_cards(sections, _EBITDA_HINTS)
        )
        guidance = _find_guidance_midpoint(sections)

        result = {
            "eps_actual":        eps,
            "revenue_actual":    revenue,
            "ebitda_actual":     ebitda,
            "guidance_midpoint": guidance,
        }
        logger.debug("extract_actuals: %s", result)
        return result
    except Exception as exc:
        logger.warning("extract_actuals failed: %s", exc)
        return {
            "eps_actual":        None,
            "revenue_actual":    None,
            "ebitda_actual":     None,
            "guidance_midpoint": None,
        }
