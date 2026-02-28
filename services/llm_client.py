"""
LLM client for the Fundamentals Reports feature.

Interface
---------
  LLMClient.complete(prompt, max_tokens) -> str

Two concrete implementations:
  MockLLMClient        – returns a deterministic stub; zero external calls
  AnthropicLLMClient  – calls claude-opus-4-6 (or configurable model)

Factory function:
  get_llm_client() -> LLMClient
    Returns AnthropicLLMClient when AI_API_KEY is set and LLM_USE_MOCK is not "1".
    Returns MockLLMClient otherwise.

Prompts
-------
MAP_PROMPT_TEMPLATE    – extract facts from one text chunk  (map step)
REDUCE_PROMPT_TEMPLATE – combine facts bags into ReportData/v1 (reduce step)
FIX_SCHEMA_PROMPT      – repair JSON that failed schema validation
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# =========================================================================== #
# Extraction prompts
# =========================================================================== #

MAP_PROMPT_TEMPLATE = """\
You are a financial data extraction AI. Read the SEC filing excerpt below and \
pull out every concrete financial fact, figure, and key quote into a structured \
JSON "facts bag".

FILING EXCERPT:
{chunk_text}

Return ONLY a JSON object with this exact structure (no markdown, no explanation):
{{
  "revenue_items":      [{{"period": "...", "value": "...", "change": "..."}}],
  "profitability_items":[{{"metric": "...", "value": "...", "change": "..."}}],
  "cash_flow_items":    [{{"category": "...", "value": "..."}}],
  "balance_sheet_items":[{{"item": "...", "value": "..."}}],
  "guidance_items":     [{{"topic": "...", "statement": "..."}}],
  "risk_items":         [{{"title": "...", "description": "...", "severity": "high|medium|low"}}],
  "management_quotes":  [{{"quote": "...", "context": "..."}}],
  "segment_items":      [{{"name": "...", "revenue": "...", "share_pct": null}}],
  "key_metrics": {{
    "revenue": null, "gross_profit": null, "operating_income": null,
    "net_income": null, "eps_diluted": null, "ebitda": null,
    "free_cash_flow": null, "net_debt": null
  }},
  "period_info": {{"period_end": null, "filing_type": null, "company_name": null}},
  "raw_quotes": []
}}

RULES:
- Extract ONLY what is explicitly stated. Do NOT invent or estimate numbers.
- If a field is not present in the excerpt, set it to null or [].
- Return ONLY the JSON object.
"""

REDUCE_PROMPT_TEMPLATE = """\
You are a senior financial analyst AI. Using the structured facts extracted from \
a SEC filing, generate a complete, investor-ready financial analysis report in \
JSON format following the ReportData/v1 schema.

COMPANY INFO:
  Ticker:       {ticker}
  Company Name: {company_name}
  Filing Type:  {filing_type}
  Period End:   {period_end}

EXTRACTED FACTS:
{facts_bag}

INSTRUCTIONS:
1. ALL user-facing strings (labels, titles, narratives, insight texts, segment names,
   risk titles/descriptions, guidance statements, quote contexts, card labels) MUST be
   written in Hebrew (RTL). Company names and direct English quotes may stay in English.
2. JSON keys stay in English exactly as shown in the schema.
3. Do NOT invent figures. If a fact is missing use null or omit the field.
4. insight.text fields may contain ONLY these HTML tags: <strong> <mark> <br> <em>.
   No other tags, no links, no scripts.
5. Return ONLY the JSON object — no markdown fences, no explanation.

REQUIRED SCHEMA (ReportData/v1):
{{
  "schema": "ReportData/v1",
  "generated_at": "<ISO-8601 timestamp>",
  "cover": {{
    "ticker": "{ticker}",
    "companyName": "<English company name>",
    "filingType": "{filing_type}",
    "periodEnd": "{period_end}",
    "filedAt": "<YYYY-MM-DD>",
    "kpis": [
      {{"label": "<Hebrew>", "value": "<formatted>", "change": "<+/-X%>", "positive": true}},
      {{"label": "<Hebrew>", "value": "<formatted>", "change": "<+/-X%>", "positive": true}},
      {{"label": "<Hebrew>", "value": "<formatted>", "change": "<+/-X%>", "positive": false}},
      {{"label": "<Hebrew>", "value": "<formatted>", "change": "<+/-X%>", "positive": false}}
    ]
  }},
  "toc": {{
    "items": [
      {{"id": "s1",  "title": "סקירה מנהלתית"}},
      {{"id": "s2",  "title": "תוצאות כספיות"}},
      {{"id": "s3",  "title": "פילוח הכנסות"}},
      {{"id": "s4",  "title": "רווחיות ושולי רווח"}},
      {{"id": "s5",  "title": "תזרים מזומנים"}},
      {{"id": "s6",  "title": "מאזן ונזילות"}},
      {{"id": "s7",  "title": "תחזיות והנחיות הנהלה"}},
      {{"id": "s8",  "title": "גורמי סיכון"}},
      {{"id": "s9",  "title": "ציטוטי הנהלה"}},
      {{"id": "s10", "title": "המלצות אנליסטים"}}
    ]
  }},
  "sections": [
    {{
      "id": "s1", "title": "סקירה מנהלתית", "type": "overview",
      "narrative": "<2-3 sentence Hebrew executive summary>",
      "insights": [
        {{"text": "<Hebrew fact — may use strong/mark/em/br>", "isAnalyst": false}},
        {{"text": "<Hebrew analyst commentary>",               "isAnalyst": true}}
      ]
    }},
    {{
      "id": "s2", "title": "תוצאות כספיות", "type": "metrics_table",
      "rows": [
        {{"metric": "<Hebrew>", "current": "<val>", "prior": "<val>", "change": "<+/-X%>", "positive": true}}
      ],
      "insights": [{{"text": "<Hebrew>", "isAnalyst": false}}]
    }},
    {{
      "id": "s3", "title": "פילוח הכנסות", "type": "segment_bars",
      "segments": [
        {{"name": "<Hebrew>", "value": "<val>", "share_pct": 0, "change": "<+/-X%>", "positive": true}}
      ],
      "insights": [{{"text": "<Hebrew>", "isAnalyst": false}}]
    }},
    {{
      "id": "s4", "title": "רווחיות ושולי רווח", "type": "profitability_cards",
      "cards": [
        {{"label": "<Hebrew>", "value": "<val>", "subtext": "<Hebrew>", "positive": true}}
      ],
      "donut": {{
        "title": "<Hebrew>",
        "items": [
          {{"label": "<Hebrew>", "pct": 0, "color": "#5B7CFF"}},
          {{"label": "<Hebrew>", "pct": 0, "color": "#00D084"}},
          {{"label": "<Hebrew>", "pct": 0, "color": "#FFB800"}},
          {{"label": "<Hebrew>", "pct": 0, "color": "#FF4757"}}
        ]
      }},
      "insights": [{{"text": "<Hebrew>", "isAnalyst": true}}]
    }},
    {{
      "id": "s5", "title": "תזרים מזומנים", "type": "cash_flow_timeline",
      "items": [
        {{"label": "<Hebrew>", "value": "<val>", "positive": true, "icon": "▲"}}
      ],
      "insights": [{{"text": "<Hebrew>", "isAnalyst": false}}]
    }},
    {{
      "id": "s6", "title": "מאזן ונזילות", "type": "balance_sheet_cards",
      "assets":      [{{"label": "<Hebrew>", "value": "<val>"}}],
      "liabilities": [{{"label": "<Hebrew>", "value": "<val>"}}],
      "equity": "<total equity value>",
      "insights": [{{"text": "<Hebrew>", "isAnalyst": false}}]
    }},
    {{
      "id": "s7", "title": "תחזיות והנחיות הנהלה", "type": "guidance",
      "narrative": "<Hebrew guidance narrative>",
      "items": [
        {{"topic": "<Hebrew>", "statement": "<Hebrew>", "type": "positive|negative|neutral"}}
      ],
      "insights": [{{"text": "<Hebrew>", "isAnalyst": true}}]
    }},
    {{
      "id": "s8", "title": "גורמי סיכון", "type": "risk_factors",
      "risks": [
        {{"title": "<Hebrew>", "description": "<Hebrew>", "severity": "high|medium|low"}}
      ],
      "insights": [{{"text": "<Hebrew>", "isAnalyst": true}}]
    }},
    {{
      "id": "s9", "title": "ציטוטי הנהלה", "type": "management_quotes",
      "quotes": [
        {{"quote": "<English direct quote>", "role": "<Hebrew role>", "context": "<Hebrew context>"}}
      ],
      "insights": [
        {{"text": "<Hebrew>", "isAnalyst": false}},
        {{"text": "<Hebrew>", "isAnalyst": true}}
      ]
    }},
    {{
      "id": "s10", "title": "המלצות אנליסטים", "type": "analyst_takeaways",
      "rating": "Buy|Hold|Sell",
      "ratingHebrew": "קנה|המתן|מכור",
      "priceTarget": "<$XX or null>",
      "cards": [
        {{"label": "<Hebrew>", "value": "<Hebrew>", "subtext": "<Hebrew>", "type": "positive|negative|neutral"}}
      ],
      "insights": [{{"text": "<Hebrew>", "isAnalyst": true}}]
    }}
  ]
}}

CONSTRAINT CHECKLIST (you MUST satisfy all):
  ✓ schema == "ReportData/v1"
  ✓ cover.kpis  has EXACTLY 4 items
  ✓ toc.items   has EXACTLY 10 items  (ids s1..s10)
  ✓ sections    has EXACTLY 10 items  (ids s1..s10 in order)
  ✓ All Hebrew strings contain actual Hebrew characters
  ✓ Output is valid JSON — no trailing commas, no comments
"""

FIX_SCHEMA_PROMPT = """\
The JSON below failed ReportData/v1 schema validation. Fix ONLY the structural \
issues listed and return the corrected JSON object. Do not change content unless \
necessary to satisfy the schema.

VALIDATION ERRORS:
{errors}

CURRENT JSON:
{current_json}

Return ONLY the corrected JSON object. No explanation, no markdown.
"""

# =========================================================================== #
# Market Reaction Analysis prompt  (second LLM call)
# =========================================================================== #

MARKET_REACTION_PROMPT = """\
You are an institutional equity analyst. Given the data below, explain the \
likely market reaction to this earnings release.

ACTUAL METRICS:
{actuals_json}

CONSENSUS EXPECTATIONS:
{consensus_json}

SURPRISE DATA:
{surprise_json}

GUIDANCE SUMMARY:
{guidance_text}

Return ONLY a JSON object (no markdown, no explanation):
{{
  "reaction_driver":  "<which single metric most likely drove price action — in Hebrew>",
  "bull_view":        "<2-3 sentence bull interpretation — in Hebrew>",
  "bear_view":        "<2-3 sentence bear interpretation — in Hebrew>",
  "quality_of_beat":  "<demand-driven | cost-driven | mixed | no beat — explain briefly in Hebrew>",
  "guidance_signal":  "positive | neutral | negative"
}}

RULES:
- All values must be in Hebrew except guidance_signal.
- Do NOT invent metrics not present in the input.
- Return ONLY the JSON object.
"""

# =========================================================================== #
# Narrative Change Detection prompt  (second LLM call on prior vs current)
# =========================================================================== #

NARRATIVE_CHANGE_PROMPT = """\
You are a narrative analysis AI comparing two consecutive quarterly earnings reports \
for the same company. Identify changes in tone, strategic focus, and risk profile.

PRIOR QUARTER SUMMARY:
{prior_summary}

CURRENT QUARTER SUMMARY:
{current_summary}

Return ONLY a JSON object (no markdown, no explanation):
{{
  "narrative_shift":         "more bullish | more cautious | unchanged",
  "new_risks":               ["<Hebrew risk description>"],
  "removed_risks":           ["<Hebrew risk description>"],
  "new_growth_focus":        "<Hebrew — what new growth theme emerged, or empty string>",
  "management_tone_change":  "<Hebrew — how management language changed>"
}}

RULES:
- All string values must be in Hebrew.
- new_risks and removed_risks are arrays of short Hebrew descriptions (max 5 each).
- Return ONLY the JSON object.
"""

# =========================================================================== #
# Pre-Earnings Mode prompt  (consensus-only, no filing text needed)
# =========================================================================== #

PRE_EARNINGS_PROMPT = """\
You are a buy-side equity analyst preparing a pre-earnings brief for investors.
Using ONLY the consensus data below, produce a pre-earnings expectations summary.

TICKER: {ticker}
CONSENSUS DATA:
{consensus_json}

Return ONLY a JSON object (no markdown, no explanation):
{{
  "expected_eps":     "<formatted string or null>",
  "expected_revenue": "<formatted string or null>",
  "key_metric_to_watch": "<Hebrew — the single most critical metric Wall Street is watching>",
  "implied_market_expectation_summary": "<Hebrew — 2-3 sentence summary of what the market is pricing in>",
  "bull_scenario":    "<Hebrew — what needs to happen for a positive surprise>",
  "bear_scenario":    "<Hebrew — what could disappoint>"
}}

RULES:
- All Hebrew strings must contain actual Hebrew characters.
- Do NOT invent numbers not present in the input.
- Return ONLY the JSON object.
"""


# =========================================================================== #
# Base interface
# =========================================================================== #
class LLMClient:
    """Minimal interface for LLM text completion."""

    def complete(self, prompt: str, max_tokens: int = 8_000) -> str:
        raise NotImplementedError

    @property
    def model_name(self) -> str:
        return "unknown"


# =========================================================================== #
# Mock implementation
# =========================================================================== #
class MockLLMClient(LLMClient):
    """Returns realistic stub data – no external calls."""

    @property
    def model_name(self) -> str:
        return "mock"

    def complete(self, prompt: str, max_tokens: int = 8_000) -> str:
        logger.info("MockLLMClient: returning stub response")
        p = prompt.lower()
        # Dispatch to the right stub by keyword fingerprints
        if "prior quarter summary" in p or "narrative_shift" in p:
            return json.dumps(self._narrative_stub(), ensure_ascii=False)
        if "reaction_driver" in p or "bull_view" in p or "quality_of_beat" in p:
            return json.dumps(self._market_reaction_stub(), ensure_ascii=False)
        if "pre-earnings" in p or "key_metric_to_watch" in p or "implied_market" in p:
            return json.dumps(self._pre_earnings_stub(), ensure_ascii=False)
        if "facts bag" in p or "extracted facts" in p:
            return json.dumps(self._reduce_stub(), ensure_ascii=False)
        return json.dumps(self._map_stub(), ensure_ascii=False)

    def _map_stub(self) -> dict:
        return {
            "revenue_items": [
                {"period": "Q3 2024", "value": "$4.8B", "change": "+12%"},
            ],
            "profitability_items": [
                {"metric": "Gross Profit",     "value": "$2.1B",  "change": "+9%"},
                {"metric": "Operating Income", "value": "$980M",  "change": "+7%"},
                {"metric": "Net Income",       "value": "$760M",  "change": "+5%"},
                {"metric": "EBITDA",           "value": "$1.2B",  "change": "+8%"},
            ],
            "cash_flow_items": [
                {"category": "Operating Cash Flow", "value": "$1.2B"},
                {"category": "Capital Expenditures","value": "-$340M"},
                {"category": "Free Cash Flow",      "value": "$860M"},
            ],
            "balance_sheet_items": [
                {"item": "Total Assets",        "value": "$45.2B"},
                {"item": "Total Debt",          "value": "$12.1B"},
                {"item": "Cash & Equivalents",  "value": "$3.4B"},
                {"item": "Total Equity",        "value": "$14.4B"},
            ],
            "guidance_items": [
                {"topic": "Full Year Revenue", "statement": "Expects $19–20B for FY2024"},
                {"topic": "CapEx",             "statement": "Capital expenditures of $1.3–1.5B"},
                {"topic": "Dividend",          "statement": "Plans to raise dividend 3–5% in 2025"},
            ],
            "risk_items": [
                {"title": "Commodity Price Risk",  "description": "Natural gas price volatility", "severity": "high"},
                {"title": "Regulatory Risk",        "description": "Pipeline regulation changes",  "severity": "medium"},
                {"title": "Interest Rate Risk",     "description": "Floating-rate debt exposure",  "severity": "low"},
            ],
            "management_quotes": [
                {
                    "quote":   "We delivered strong operational results this quarter with record throughput volumes of 5.3 Bcf/d.",
                    "context": "CEO opening remarks",
                },
                {
                    "quote":   "Our balance sheet remains strong and we continue to generate substantial free cash flow.",
                    "context": "CFO financial outlook",
                },
            ],
            "segment_items": [
                {"name": "Natural Gas Gathering & Processing", "revenue": "$1.8B", "share_pct": 37.5},
                {"name": "Natural Gas Liquids",               "revenue": "$2.1B", "share_pct": 43.75},
                {"name": "Natural Gas Pipelines",             "revenue": "$0.9B", "share_pct": 18.75},
            ],
            "key_metrics": {
                "revenue":          "$4.8B",
                "gross_profit":     "$2.1B",
                "operating_income": "$980M",
                "net_income":       "$760M",
                "eps_diluted":      "$1.05",
                "ebitda":           "$1.2B",
                "free_cash_flow":   "$860M",
                "net_debt":         "$8.7B",
            },
            "period_info": {
                "period_end":   "2024-09-30",
                "filing_type":  "10-Q",
                "company_name": "ONEOK, Inc.",
            },
            "raw_quotes": ["Record throughput of 5.3 Bcf/d"],
        }

    def _reduce_stub(self) -> dict:
        return {
            "schema":       "ReportData/v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cover": {
                "ticker":      "OKE",
                "companyName": "ONEOK, Inc.",
                "filingType":  "10-Q",
                "periodEnd":   "2024-09-30",
                "filedAt":     "2024-11-06",
                "kpis": [
                    {"label": "הכנסות",    "value": "$4.8B",  "change": "+12%", "positive": True},
                    {"label": "EBITDA",    "value": "$1.2B",  "change": "+8%",  "positive": True},
                    {"label": "EPS מדולל", "value": "$1.05",  "change": "+5%",  "positive": True},
                    {"label": "חוב נקי",   "value": "$8.7B",  "change": "+2%",  "positive": False},
                ],
            },
            "toc": {
                "items": [
                    {"id": "s1",  "title": "סקירה מנהלתית"},
                    {"id": "s2",  "title": "תוצאות כספיות"},
                    {"id": "s3",  "title": "פילוח הכנסות"},
                    {"id": "s4",  "title": "רווחיות ושולי רווח"},
                    {"id": "s5",  "title": "תזרים מזומנים"},
                    {"id": "s6",  "title": "מאזן ונזילות"},
                    {"id": "s7",  "title": "תחזיות והנחיות הנהלה"},
                    {"id": "s8",  "title": "גורמי סיכון"},
                    {"id": "s9",  "title": "ציטוטי הנהלה"},
                    {"id": "s10", "title": "המלצות אנליסטים"},
                ],
            },
            "sections": [
                {
                    "id": "s1", "title": "סקירה מנהלתית", "type": "overview",
                    "narrative": (
                        "ONEOK רשמה רבעון שלישי חזק עם הכנסות של 4.8 מיליארד דולר, גידול של 12% לעומת השנה הקודמת. "
                        "נפח התפוקה הגיע לשיא חדש של 5.3 מיליארד רגל מעוקב ביום, המשקף ביקוש גבוה בשוק האנרגיה. "
                        "החברה ממשיכה לייצר תזרים מזומנים חופשי חזק התומך במדיניות דיבידנד אגרסיבית."
                    ),
                    "insights": [
                        {"text": "הכנסות החברה <strong>עלו ב-12%</strong> לעומת הרבעון המקביל אשתקד.", "isAnalyst": False},
                        {"text": "<mark>נקודת חוזק:</mark> ה-EBITDA גדל ב-8% ותזרים המזומנים החופשי יציב ואמין.", "isAnalyst": True},
                    ],
                },
                {
                    "id": "s2", "title": "תוצאות כספיות", "type": "metrics_table",
                    "rows": [
                        {"metric": "הכנסות",        "current": "$4.8B",  "prior": "$4.3B",  "change": "+12%", "positive": True},
                        {"metric": "רווח גולמי",     "current": "$2.1B",  "prior": "$1.93B", "change": "+9%",  "positive": True},
                        {"metric": "הכנסה תפעולית", "current": "$980M",  "prior": "$916M",  "change": "+7%",  "positive": True},
                        {"metric": "רווח נקי",       "current": "$760M",  "prior": "$724M",  "change": "+5%",  "positive": True},
                        {"metric": "EBITDA",          "current": "$1.2B",  "prior": "$1.11B", "change": "+8%",  "positive": True},
                        {"metric": "EPS מדולל",       "current": "$1.05",  "prior": "$1.00",  "change": "+5%",  "positive": True},
                    ],
                    "insights": [
                        {"text": "כל מדדי הרווחיות <strong>עלו בעקביות</strong> לעומת הרבעון המקביל.", "isAnalyst": False},
                    ],
                },
                {
                    "id": "s3", "title": "פילוח הכנסות", "type": "segment_bars",
                    "segments": [
                        {"name": "נוזלי גז טבעי",          "value": "$2.1B", "share_pct": 43.75, "change": "+15%", "positive": True},
                        {"name": "איסוף ועיבוד גז טבעי",   "value": "$1.8B", "share_pct": 37.5,  "change": "+10%", "positive": True},
                        {"name": "צנרת גז טבעי",           "value": "$0.9B", "share_pct": 18.75, "change": "+5%",  "positive": True},
                    ],
                    "insights": [
                        {"text": "מגזר <strong>נוזלי גז טבעי</strong> הוא המנוע המוביל עם 43.75% מסך ההכנסות.", "isAnalyst": False},
                    ],
                },
                {
                    "id": "s4", "title": "רווחיות ושולי רווח", "type": "profitability_cards",
                    "cards": [
                        {"label": "שיעור רווח גולמי",    "value": "43.8%", "subtext": 'שיפור של 1.2 נ"ב', "positive": True},
                        {"label": "שיעור רווח תפעולי",   "value": "20.4%", "subtext": "יציב לעומת אשתקד",   "positive": True},
                        {"label": "שיעור רווח נקי",      "value": "15.8%", "subtext": 'גידול של 0.5 נ"ב',  "positive": True},
                    ],
                    "donut": {
                        "title": "הרכב ההוצאות",
                        "items": [
                            {"label": "עלות הכנסות",      "pct": 56.2, "color": "#5B7CFF"},
                            {"label": "הוצאות תפעוליות",  "pct": 23.4, "color": "#00D084"},
                            {"label": "פחת והפחתות",      "pct": 12.1, "color": "#FFB800"},
                            {"label": "מס ואחרים",         "pct":  8.3, "color": "#FF4757"},
                        ],
                    },
                    "insights": [
                        {"text": "<mark>שיפור בשוליים:</mark> יתרון תפעולי גובר ושיפור בתמהיל ההכנסות מסבירים את שיפור השוליים.", "isAnalyst": True},
                    ],
                },
                {
                    "id": "s5", "title": "תזרים מזומנים", "type": "cash_flow_timeline",
                    "items": [
                        {"label": "תזרים מפעילות שוטפת",  "value": "$1.2B",   "positive": True,  "icon": "▲"},
                        {"label": "הוצאות הון (CapEx)",    "value": "−$340M",  "positive": False, "icon": "▼"},
                        {"label": "תזרים מזומנים חופשי",  "value": "$860M",   "positive": True,  "icon": "▲"},
                        {"label": "דיבידנד ששולם",         "value": "−$420M",  "positive": False, "icon": "▼"},
                        {"label": "תזרים נטו",             "value": "$440M",   "positive": True,  "icon": "●"},
                    ],
                    "insights": [
                        {"text": "תזרים מזומנים חופשי <strong>חזק של $860M</strong> מאפשר הגדלת דיבידנד וצמצום חוב.", "isAnalyst": False},
                    ],
                },
                {
                    "id": "s6", "title": "מאזן ונזילות", "type": "balance_sheet_cards",
                    "assets": [
                        {"label": "סך נכסים",           "value": "$45.2B"},
                        {"label": "מזומן ושווי מזומן",   "value": "$3.4B"},
                        {"label": "חשבונות לגבייה",      "value": "$1.1B"},
                    ],
                    "liabilities": [
                        {"label": "סך התחייבויות",       "value": "$30.8B"},
                        {"label": "חוב לטווח ארוך",      "value": "$12.1B"},
                        {"label": "חשבונות לתשלום",      "value": "$890M"},
                    ],
                    "equity": "$14.4B",
                    "insights": [
                        {"text": "יחס חוב ל-EBITDA של <strong>2.5×</strong> נמצא בטווח הנוח לדירוג השקעה.", "isAnalyst": False},
                    ],
                },
                {
                    "id": "s7", "title": "תחזיות והנחיות הנהלה", "type": "guidance",
                    "narrative": (
                        "ההנהלה מאשרת את תחזיותיה לשנת 2024 עם ציפייה להכנסות שנתיות של 19–20 מיליארד דולר "
                        "ו-EBITDA מותאם של 4.6–4.8 מיליארד דולר. "
                        "ה-CapEx צפוי לנוע בין 1.3 ל-1.5 מיליארד דולר."
                    ),
                    "items": [
                        {"topic": "הכנסות שנתיות",   "statement": "צפי של $19–20B לשנת 2024",       "type": "positive"},
                        {"topic": "EBITDA מותאם",    "statement": "צפי של $4.6–4.8B",               "type": "positive"},
                        {"topic": "הוצאות הון",      "statement": "CapEx של $1.3–1.5B",             "type": "neutral"},
                        {"topic": "דיבידנד 2025",    "statement": "הגדלת דיבידנד ב-3–5% בשנת 2025", "type": "positive"},
                    ],
                    "insights": [
                        {"text": "תחזיות ההנהלה <mark>עקביות עם הציפיות</mark> ומשקפות ביטחון בצמיחה האורגנית.", "isAnalyst": True},
                    ],
                },
                {
                    "id": "s8", "title": "גורמי סיכון", "type": "risk_factors",
                    "risks": [
                        {
                            "title":       "סיכון מחיר סחורות",
                            "description": "חשיפה לתנודתיות במחירי גז טבעי ו-NGL עלולה להשפיע על הכנסות ה-Gathering & Processing.",
                            "severity":    "high",
                        },
                        {
                            "title":       "סיכון רגולטורי",
                            "description": "תקנות FERC חדשות עשויות להגביל תעריפי הצנרת ולפגוע ברווחיות.",
                            "severity":    "medium",
                        },
                        {
                            "title":       "סיכון ריבית",
                            "description": "חשיפה לחוב בריבית משתנה עלולה להגדיל הוצאות מימון בסביבת ריבית גבוהה.",
                            "severity":    "low",
                        },
                    ],
                    "insights": [
                        {"text": "סיכון מחיר הסחורות הוא <strong>הסיכון העיקרי</strong> הדורש מעקב צמוד בסביבת הריבית הנוכחית.", "isAnalyst": True},
                    ],
                },
                {
                    "id": "s9", "title": "ציטוטי הנהלה", "type": "management_quotes",
                    "quotes": [
                        {
                            "quote":   "We delivered strong operational results this quarter with record throughput volumes of 5.3 Bcf/d.",
                            "role":    'מנכ"ל',
                            "context": "תוצאות הרבעון השלישי",
                        },
                        {
                            "quote":   "Our balance sheet remains strong and we continue to generate substantial free cash flow to support our dividend and growth investments.",
                            "role":    'סמנכ"ל כספים',
                            "context": "מצב פיננסי ואסטרטגיית הון",
                        },
                    ],
                    "insights": [
                        {"text": "הנהלה מדגישה <strong>כוח ייצור תפעולי</strong> ואיתנות פיננסית כמנועים עיקריים.", "isAnalyst": False},
                        {"text": "<mark>קריאה בין השורות:</mark> הדגשת תזרים המזומנים מרמזת על תכניות לפעילות הון בקרוב.", "isAnalyst": True},
                    ],
                },
                {
                    "id": "s10", "title": "המלצות אנליסטים", "type": "analyst_takeaways",
                    "rating":       "Buy",
                    "ratingHebrew": "קנה",
                    "priceTarget":  "$95",
                    "cards": [
                        {
                            "label":   "מנוע צמיחה",
                            "value":   "חזק",
                            "subtext": "נפחי תפוקה שוברי שיאים תומכים בצמיחת הכנסות עקבית",
                            "type":    "positive",
                        },
                        {
                            "label":   "הערכת שווי",
                            "value":   "סביר",
                            "subtext": "נסחר ב-×12 EBITDA — פרמיה מוצדקת לאיכות הנכסים",
                            "type":    "neutral",
                        },
                        {
                            "label":   "סיכון עיקרי",
                            "value":   "מחיר גז",
                            "subtext": "ירידה חדה במחירי גז עלולה לפגוע בהכנסות ה-G&P",
                            "type":    "negative",
                        },
                    ],
                    "insights": [
                        {"text": "ONEOK מציגה <strong>פרופיל סיכון/תשואה אטרקטיבי</strong> עם תזרים יציב ותחזיות חיוביות.", "isAnalyst": True},
                    ],
                },
            ],
        }

    # ---- New analysis stubs ------------------------------------------------ #

    def _market_reaction_stub(self) -> dict:
        return {
            "reaction_driver":  "הכנסות גבוהות מהציפיות ב-11.6% הובילו את תגובת השוק החיובית",
            "bull_view": (
                "המשכיות הצמיחה בנפחי הגז מאשרת את הביקוש הבסיסי לתשתיות האנרגיה. "
                "תזרים המזומנים החופשי תומך בהגדלת הדיבידנד ובחזרת הון לבעלי המניות. "
                "ה-EBITDA החזק מבסס את יכולת המינוף לצמיחה עתידית."
            ),
            "bear_view": (
                "חלק ניכר מהעלייה בהכנסות נובע מתנודות מחיר סחורות ולא מצמיחה אורגנית. "
                "ה-CapEx הגבוה מגביל את הגמישות הפיננסית לטווח הקצר. "
                "חשיפת הריבית המשתנה עלולה ללחוץ על השוליים בסביבת ריבית גבוהה."
            ),
            "quality_of_beat":  "ביטהeat מבוסס ביקוש — עליית נפחים אורגנית, לא צמצום עלויות",
            "guidance_signal":  "positive",
        }

    def _narrative_stub(self) -> dict:
        return {
            "narrative_shift":        "more bullish",
            "new_risks":              [
                "חשיפה מוגברת לשוק ה-LNG לאחר הרחבת הפעילות הבינלאומית",
                "תלות גוברת בחוזים ספוטיים בשוק הגז הטבעי",
            ],
            "removed_risks":          [
                "סיכון הרגולציה הפדרלית שהוזכר ברבעון הקודם הוסר לאחר אישור ה-FERC",
            ],
            "new_growth_focus":       "ההנהלה מדגישה השקעות חדשות בתשתיות ה-NGL וצינורות הפצה לאוקלהומה",
            "management_tone_change": "מעבר משפה זהירה של 'אתגרים בשוק' לנרטיב התרחבות פרואקטיבי",
        }

    def _pre_earnings_stub(self) -> dict:
        return {
            "expected_eps":     "$1.05",
            "expected_revenue": "$4.3B",
            "key_metric_to_watch": (
                "נפח תפוקה הגז הטבעי (Bcf/d) — הוא המנוע האמיתי של הרווחיות ב-ONEOK"
            ),
            "implied_market_expectation_summary": (
                "השוק מתמחר צמיחה של כ-8-10% בהכנסות לעומת הרבעון המקביל. "
                "ציפיות מרומזות ל-EPS של כ-$1.05 וה-EBITDA ב-$1.1-1.15B. "
                "כל סטייה מעל 5% למעלה עשויה לייצר ראלי חד."
            ),
            "bull_scenario":    "EPS מעל $1.10 + אישור הגדלת דיבידנד = עלייה חדה של 5-8%",
            "bear_scenario":    "הכנסות מתחת ל-$4.0B + הורדת תחזית = ירידה של 4-7%",
        }


# =========================================================================== #
# Real Anthropic implementation
# =========================================================================== #
class AnthropicLLMClient(LLMClient):
    """Uses the anthropic SDK (already in requirements.txt)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self._api_key = api_key or os.getenv("AI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        self._model   = model or os.getenv("AI_MODEL", "claude-opus-4-6")
        self._client  = None

    @property
    def model_name(self) -> str:
        return self._model

    def _client_lazy(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise RuntimeError("anthropic package is not installed") from exc
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def complete(self, prompt: str, max_tokens: int = 8_000) -> str:
        client = self._client_lazy()
        try:
            msg = client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text
        except Exception as exc:
            logger.error("Anthropic API error: %s", exc)
            raise


# =========================================================================== #
# Factory
# =========================================================================== #
def get_llm_client() -> LLMClient:
    """
    Return the appropriate LLM client based on environment:
      - LLM_USE_MOCK=1  → always use mock
      - AI_API_KEY set  → AnthropicLLMClient
      - otherwise       → MockLLMClient
    """
    use_mock = os.getenv("LLM_USE_MOCK", "").lower() in ("1", "true", "yes")
    if use_mock:
        logger.info("LLM: using MockLLMClient (LLM_USE_MOCK=1)")
        return MockLLMClient()

    api_key = os.getenv("AI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.info("LLM: no API key found — using MockLLMClient")
        return MockLLMClient()

    logger.info("LLM: using AnthropicLLMClient (model=%s)", os.getenv("AI_MODEL", "claude-opus-4-6"))
    return AnthropicLLMClient(api_key=api_key)
