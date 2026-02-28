"""
Earnings Surprise Engine.

Computes percentage surprise between actuals and consensus expectations,
then identifies the largest surprise driver.

Public API
----------
compute_surprise(actual, expected) -> float | None
    Single metric surprise in percent.

compute_all_surprises(actuals, consensus) -> dict
    {
      "eps_surprise_pct":      float | None,
      "revenue_surprise_pct":  float | None,
      "ebitda_surprise_pct":   float | None,
      "largest_surprise_driver": "eps" | "revenue" | "ebitda" | None,
      "largest_surprise_pct":  float | None,
    }
    Never raises.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def compute_surprise(actual: Optional[float], expected: Optional[float]) -> Optional[float]:
    """
    ((actual - expected) / |expected|) * 100

    Returns None if either input is None or expected is 0.
    """
    if actual is None or expected is None:
        return None
    if expected == 0:
        return None
    return round(((actual - expected) / abs(expected)) * 100, 2)


def compute_all_surprises(actuals: dict, consensus: dict) -> dict:
    """
    Compute surprise for EPS, Revenue, and EBITDA, and rank the biggest mover.
    """
    try:
        eps_s = compute_surprise(
            actuals.get("eps_actual"),
            consensus.get("eps_estimate"),
        )
        rev_s = compute_surprise(
            actuals.get("revenue_actual"),
            consensus.get("revenue_estimate"),
        )
        ebi_s = compute_surprise(
            actuals.get("ebitda_actual"),
            consensus.get("ebitda_estimate"),
        )

        # Find largest absolute surprise
        candidates = {
            "eps":     eps_s,
            "revenue": rev_s,
            "ebitda":  ebi_s,
        }
        valid = {k: abs(v) for k, v in candidates.items() if v is not None}
        if valid:
            driver     = max(valid, key=lambda k: valid[k])
            driver_pct = candidates[driver]
        else:
            driver     = None
            driver_pct = None

        result = {
            "eps_surprise_pct":        eps_s,
            "revenue_surprise_pct":    rev_s,
            "ebitda_surprise_pct":     ebi_s,
            "largest_surprise_driver": driver,
            "largest_surprise_pct":    driver_pct,
        }
        logger.debug("compute_all_surprises: %s", result)
        return result

    except Exception as exc:
        logger.warning("compute_all_surprises failed: %s", exc)
        return {
            "eps_surprise_pct":        None,
            "revenue_surprise_pct":    None,
            "ebitda_surprise_pct":     None,
            "largest_surprise_driver": None,
            "largest_surprise_pct":    None,
        }


def fmt_surprise(pct: Optional[float]) -> str:
    """Format a surprise percentage for display (e.g. '+5.2%', '−3.1%', '—')."""
    if pct is None:
        return "—"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def surprise_sentiment(pct: Optional[float]) -> str:
    """Return 'pos', 'neg', or 'neu' CSS class based on surprise direction."""
    if pct is None:
        return "neu"
    return "pos" if pct >= 0 else "neg"
