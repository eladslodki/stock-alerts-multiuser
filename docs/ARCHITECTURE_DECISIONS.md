# Analyst Stocks AI — Architecture Decisions

This document captures the product vision and every major architectural
decision made during development, the specific problem each one solved,
and the reasoning behind the chosen approach. It exists so that future
contributors (or the founder six months from now) can understand *why*
the system looks the way it does — not just *what* it does.

Last updated: 2026-03-22

---

## Part 1: Product Vision & Target Audience

### Who is this for?

Retail swing traders. People who hold positions for days to weeks, not
seconds. They want to make informed, fundamental-based trades but lack
the time or expertise to read through hours of financial news, earnings
transcripts, and macro reports every morning. They are not day traders
(speed doesn't matter), and they are not institutional analysts (they
don't have Bloomberg terminals or 10-person research teams).

### What is the product?

An "Explainable Analyst in your pocket." The system monitors financial
news in real time, reasons about which companies are affected and why,
and delivers actionable investment insights with clear fundamental
reasoning attached.

The dashboard (`/dashboard`) is a development and monitoring tool. The
real product is **push/email alerts**: a user tracking NVDA gets a
notification that says "TSMC ↑ — Alphabet just announced $50B in AI
infrastructure spend. TSMC manufactures their chips. Confidence: 0.72.
Regime: Risk-On." That notification — with its 2-3 sentence
explanation — is the entire product experience.

### Core UX principle: Explainable AI

Every signal comes with a human-readable reasoning chain. We do not
produce black-box buy/sell signals. The user can read *why* the system
thinks NVDA is bullish and decide whether they agree. This builds trust,
educates the user over time, and differentiates the product from every
other retail signal service that shows a green or red arrow with no
explanation.

### The moat (what competitors can't easily replicate)

**1. The Knowledge Graph — hidden second-order opportunities.**
While every retail tool reacts to the obvious headline ("Nvidia beats
earnings"), our supply-chain graph catches the ripple effects that most
retail investors miss entirely. When hyperscalers announce $50B in AI
capex, the system doesn't just flag the hyperscaler — it propagates
through the graph to surface TSMC (foundry), ASML (lithography
equipment), and Micron (memory supplier) as beneficiaries before the
retail market connects those dots.

**2. Regime awareness — automatic risk management.**
The system knows whether the market is in risk-on or risk-off mode and
dynamically adjusts its signal confidence. During a panic (VIX > 25,
SPY declining), it automatically suppresses speculative bullish calls
and tells the user "macro headwinds may overwhelm this company-specific
tailwind." No other retail tool does this. Most retail tools are
permanently bullish because that's what users want to hear.

**3. Deep context at speed.**
Digesting a complex supply-chain news article into a structured,
multi-company investment thesis with confidence scores and risk factors
— delivered as a push notification within minutes of the article
publishing. A human analyst takes hours. Bloomberg costs $25,000/year.
This product delivers 80% of the analytical value at a fraction of the
cost and time.

### Initial domain focus

Semiconductors, AI infrastructure, and large US tech companies connected
to those sectors. Also energy (XOM, CVX, GEV, COP) and financials (JPM,
GS) where they intersect with macro events.

This domain was chosen because it has strong geopolitical sensitivity,
complex supply chains (which make the graph valuable), frequent policy
changes, and high retail investor interest. Expansion to other sectors
(pharma, EV, consumer) is deferred until accuracy on the core domain
exceeds 50% sustained hit rate.

---

## Part 2: Architecture Decision Log

Each entry follows the format: what was the problem, what was decided,
why, and what was the alternative.

---

### ADR-001: Two-Stage LLM Pipeline

**Date:** 2026-03 (initial architecture)

**Problem:** A single LLM call trying to simultaneously classify an
event, identify affected companies, determine direction, and provide
reasoning produces inconsistent, hard-to-debug output.

**Decision:** Split into two stages. Stage 1 (classify) determines
category, severity, sectors, and keywords using a focused prompt.
Stage 2 (analyze) receives the Stage 1 output plus knowledge base
context and produces per-company directional analysis.

**Reasoning:** Separation of concerns. Stage 1 can be evaluated
independently with simple accuracy metrics. Stage 2 gets a cleaner,
pre-structured input. Debugging is straightforward: if the company
identification is wrong, you know it's a Stage 2 problem; if the
category is wrong, it's Stage 1.

**Alternative rejected:** Single-stage monolithic prompt. Harder to
debug, harder to iterate on, and the classification accuracy was
measurably worse because the model was trying to do too many things
at once.

---

### ADR-002: Knowledge Graph with Typed Directional Edges

**Date:** 2026-03 (Phase 3-4)

**Problem:** The LLM identifies companies mentioned in the article but
misses companies that are indirectly affected through supply chain,
competitive, or customer relationships.

**Decision:** Build a NetworkX-based knowledge graph with typed edges
(`customer_of`, `supplies`, `competes_with`) loaded from
`relationships.json`. After Stage 2, run BFS traversal up to 2 hops,
propagating impact scores with hop decay and criticality weighting.
`competes_with` edges invert the signal direction.

**Reasoning:** The graph is the product's core differentiator. It
surfaces second-order effects (TSMC benefits when hyperscalers increase
capex) that the LLM alone misses. Typed edges allow different
propagation logic per relationship type.

**Key constraint:** LLM output is never modified by graph enrichment.
The graph layer is strictly additive — it can add new tickers but
cannot change the direction or confidence of LLM-identified companies.
This was established after a regression where the graph merger was
overwriting LLM directions, causing accuracy to drop.

---

### ADR-003: Severity Gate (Skip Stage 2 for Low-Impact Events)

**Date:** 2026-03-16

**Problem:** Approximately 40% of ingested RSS articles are low-severity
noise (minor corporate announcements, routine filings, analyst opinion
pieces). Running Stage 2 on these wastes LLM tokens and produces
low-quality signals that dilute the signal-to-noise ratio.

**Decision:** After Stage 1 classification, events with `severity=low`
return immediately. Stage 2 is never called, no signals are written.
`PipelineResult.severity_skipped=True` is set for traceability.

**Reasoning:** Stage 1 is cheap (classification only, smaller prompt).
Stage 2 is expensive (full financial reasoning with KB context). Gating
on severity eliminates ~40% of Stage 2 calls with zero accuracy loss
because low-severity events rarely produce actionable signals anyway.

**Alternative rejected:** Running everything through both stages and
filtering at the signal level. This preserves information but at 2-3x
the API cost for negligible benefit.

---

### ADR-004: Hybrid Model Routing (70B for Both Stages)

**Date:** 2026-03-16

**Problem:** API costs scale linearly with article volume. Stage 1
(classification) is a simpler task that might work with a smaller,
cheaper model.

**Decision:** Initially routed Stage 1 to `llama-3.1-8b-instant` (12x
cheaper per token) while keeping Stage 2 on `llama-3.3-70b-versatile`.
After P5 regression validation showed classification accuracy dropped
below the 5/6 gate on the 8B model, Stage 1 was reverted to 70B.

**Reasoning:** The cost savings were real (~50% overall reduction), but
classification accuracy is upstream of everything. A wrong category
assignment (e.g., corporate event classified as geopolitical) causes
Stage 2 to apply the wrong reasoning framework, which cascades into
wrong directional calls. The plumbing for model routing remains in
place — switching back is a one-line change to `_STAGE1_MODEL` — but
accuracy takes priority over cost at this stage.

**Current state:** Both stages use `llama-3.3-70b-versatile` via Groq.

---

### ADR-005: Three-Layer Deduplication

**Date:** 2026-03-16

**Problem:** The same event gets reported by multiple sources (Reuters,
CNBC, Bloomberg, Yahoo Finance) within the same RSS polling cycle. A
China tariff headline might appear 5-7 times in a single 10-minute
window. Without dedup, the system generates duplicate signals that
inflate the portfolio's conviction on stale information.

**Decision:** Three independent dedup layers, each catching a different
class of duplicates:

| Layer | Stage | Mechanism | What it catches |
|-------|-------|-----------|-----------------|
| 1 — Title hash | Pre-fetch | Exact string match on headline | Same headline from same feed |
| 2 — Text fingerprint | Pre-LLM | SHA-256 of first 500 normalized chars, 24h in-memory TTL | Same wire story from different publishers |
| 3 — Event signature | Post-Stage-1 | `date\|primary_entity\|event_type` composite key | Semantically identical events with different wording |

**Reasoning:** Each layer is cheap and catches duplicates that the
other layers miss. Layer 2 is the highest-value addition: it prevents
the most expensive operation (LLM calls) from running on content that's
effectively identical. The 24h TTL ensures the cache doesn't grow
unbounded.

---

### ADR-006: Pre-LLM Article Quality Filter

**Date:** 2026-03-17

**Problem:** Yahoo Finance RSS feeds contain a high volume of non-news
content: listicles ("7 Stocks to Buy Right Now"), personal finance
articles ("How to Maximize Your Social Security"), crypto speculation,
and job/career advice. These pass dedup (they're unique articles) but
never produce actionable signals.

**Decision:** A zero-cost, title-based regex filter with 18 compiled
patterns that runs after dedup and before any LLM call. Matching
articles are rejected immediately.

**Reasoning:** Pattern matching on titles is effectively free (< 1ms
per article). It eliminates ~8-10 articles per 10-minute polling cycle,
saving 6-7 seconds of Stage 1 LLM time and associated token costs.
False positives are acceptable because these article categories never
produce useful signals.

---

### ADR-007: Time-Decayed Opportunity Ranking

**Date:** 2026-03-16

**Problem:** A signal generated 30 hours ago should not carry the same
weight as one generated 2 hours ago. Financial news has a short
half-life — the market prices information quickly.

**Decision:** Apply exponential decay to signal scores:
`opportunity_score = |impact_score| × confidence × exp(−0.1 × hours)`.
Half-life is ~6.9 hours. After 24 hours a signal retains ~9% of its
original score. Signals older than 48 hours (decay < 0.01) are excluded
from portfolio aggregation entirely.

**Reasoning:** The decay constant (λ=0.1) was chosen to match the
typical information absorption window for the target user: swing traders
checking their alerts 1-3 times per day. A signal needs to remain
visible for 12-18 hours to be actionable, but should be nearly invisible
by 48 hours.

---

### ADR-008: Market Regime Context Injection (Phase 1)

**Date:** 2026-03-19

**Problem:** The system had a 19% overall hit rate, with a systematic
bearish bias. Analysis of 58 signal outcomes revealed the root cause:
the LLM was processing each article in a vacuum with no knowledge of
the broader market environment. In a bull market, it was calling every
negative headline as bearish — and being wrong 81% of the time.

**Decision:** Inject a structured market regime snapshot into every
Stage 2 prompt call. The snapshot includes SPY trailing returns at
1w/1m/3m windows, VIX level, and sector ETF momentum (SMH, XLF, XLE,
XLK). The regime is classified as RISK-ON, RISK-OFF, or TRANSITIONAL
based on SPY direction and VIX level. Regime-specific interpretation
rules are included in the injected block.

**Reasoning:** The prompt already contained sophisticated rules about
regime-dependent interpretation (e.g., "in a rate-cut-hopes regime,
strong economic data is bearish"). But the LLM had no data to determine
which regime was active. This was a context starvation problem, not a
reasoning quality problem. Injecting factual market data gave the LLM
the information a human analyst already has in their head.

**Implementation detail:** `get_regime_snapshot()` accepts an optional
`as_of_date` parameter for backtest simulation. Returns both a formatted
string (for prompt injection) and a `RegimeData` dataclass (for the
post-merge confidence clamp). Data is fetched via yfinance with a 4-hour
TTL cache.

**Impact:** Hit rate improved from 19% to 40.5% on the subsequent
evaluation of 2,421 signals.

---

### ADR-009: Active Signal Memory Injection (Phase 2)

**Date:** 2026-03-19

**Problem:** Each article was analyzed in isolation. The system had no
awareness of what signals it had already generated. This caused two
failures: (1) duplicate signal generation when multiple articles covered
the same event, and (2) inability to weigh conflicting micro vs. macro
signals against each other.

**Decision:** Before Stage 2 runs, query active signals (last 48 hours)
for all tickers relevant to the current article. Inject a summary block
showing signal count, net direction, and recent signal details per
ticker. Include interpretation rules telling the LLM to treat repeated
stories as diminished signals and to address contradictions explicitly.

**Reasoning:** This gives the LLM the ability to recognize "I already
said bearish on NVDA from three tariff articles — this fourth article
adds no new information" and to weigh "NVDA has 3 bearish signals but
this earnings beat is a strong counter-signal." The signal memory
context was placed inside the same cognitive frame as the article (under
a shared parent header) to ensure the LLM treats it as task input, not
background context.

---

### ADR-010: Prompt Positioning — Cognitive Frame Structure

**Date:** 2026-03-20

**Problem:** After deploying regime context and signal memory, the LLM
was still producing generic analysis with no reference to the injected
context. The reasoning field showed zero awareness of market regime
or active signals.

**Decision:** Restructured the Stage 2 prompt to place all context
blocks (regime, signal memory, calibration, KB, article) under a single
parent header `## Event Analysis Input`, with each block as a subsection.
Added a forcing function in the output instructions: "A reasoning that
does not reference the provided market context is INCOMPLETE."

**Reasoning:** LLMs have strongest attention at the prompt's beginning
(system instructions) and end (most recent content). Context blocks
placed between system rules and the article text fall into an attention
dead zone. Moving them inside the same cognitive frame as the article
— and explicitly requiring their use in the output — solved the
attention problem. After this change, 100% of reasoning outputs
referenced regime conditions and active signals.

**Key learning:** Injecting context into a prompt is necessary but not
sufficient. The model must be told (a) where to attend and (b) that
output quality is measured by whether the context was used.

---

### ADR-011: Confidence Calibration Context (Phase 3)

**Date:** 2026-03-20

**Problem:** The system outputs confidence scores (0.0-1.0) that have
no empirical grounding. A signal at confidence 0.8 is wrong just as
often as one at confidence 0.5.

**Decision:** Build a calibration module that queries historical
`signal_outcomes`, computes hit rates by category × direction, and
injects the empirical accuracy data into Stage 2. The LLM sees: "This
system's bearish calls on geopolitical events are correct only 19% of
the time."

**Reasoning:** The simplest possible learning loop — no gradient
descent, no fine-tuning, just feeding the model its own track record.
Gated behind a minimum sample size (30 outcomes per bucket) to avoid
injecting noisy statistics from small samples.

**Current state:** The module is deployed but returns empty string
because per-bucket sample sizes haven't reached the 30-outcome
threshold yet. It will automatically activate as data accumulates.

---

### ADR-012: Post-Merge Regime Confidence Clamp

**Date:** 2026-03-22

**Problem:** The LLM was correctly applying Rule 11 (suppress corporate
bullish confidence to 0.55 in risk-off regimes), but graph-propagated
signals bypassed the LLM entirely and were persisted with mechanically
computed confidence values (e.g., 0.729) that violated the regime
constraint. 50% of bullish signals exceeded the 0.55 cap because they
came from the graph, not the LLM.

**Decision:** Add a confidence clamp in `_persist_signals()` that runs
after the merge step and before signal storage. Counter-regime signals
(bullish in risk-off, bearish in risk-on) are capped at 0.55 for
LLM/both sources and 0.45 for pure graph sources. Impact scores are
preserved unchanged for debugging.

**Reasoning:** The graph traversal engine should remain context-free —
coupling it to the regime module would violate module isolation. Instead,
the clamp operates as a thin enforcement layer at the persistence
boundary, ensuring all signals (regardless of source) respect the same
regime-based constraints. Graph signals get a lower cap than LLM signals
because they carry less analytical context.

**Alternative rejected:** Injecting regime awareness into the graph
traversal algorithm. This would couple the graph engine to the context
modules and make the graph's behavior dependent on external state,
complicating testing and debugging.

---

### ADR-013: Explainer/Analysis Article Filter

**Date:** 2026-03-21

**Problem:** The system was generating duplicate signals from explainer
articles ("Why Section 301 probes matter") that covered events already
fully captured by earlier news articles. The event signature dedup
didn't catch these because the headlines were structurally different.

**Decision:** Added a prompt-level instruction in the signal memory
interpretation rules: if the article is an analysis/explainer/opinion
piece about an event already represented in active signals, return
an empty company list. Includes specific headline pattern indicators
("Why", "What X means for", "How to think about", "Analysis:").

**Reasoning:** This is cheaper and more flexible than building a fourth
dedup layer. The LLM can make a semantic judgment about whether an
article contains new information, which is something no hash-based
or fingerprint-based dedup can do. The signal memory context gives
the LLM the evidence it needs to make this judgment.

---

### ADR-014: Ticker Validation Gate

**Date:** 2026-03-20

**Problem:** The LLM occasionally hallucinates invalid tickers: literal
string "NONE", company names like "NUSCALE POWER", London Stock Exchange
tickers like "LLOY", and other garbage. These propagate to the price
checker, which fails on every lookup.

**Decision:** A validation function in `engine/validation/ticker_filter.py`
that rejects signals where the ticker is a sentinel value ("NONE",
"N/A"), contains spaces, exceeds 5 characters, or contains lowercase
letters. Runs after merge, before persistence. Rejected tickers are
logged at WARNING level for monitoring.

**Reasoning:** Defense in depth. The Stage 2 prompt was also updated to
constrain output to valid US exchange tickers, but prompt constraints
are suggestions, not guarantees. The validation gate is a hard
enforcement boundary.

---

### ADR-015: GOOG → GOOGL Alias Normalization

**Date:** 2026-03-21

**Problem:** The LLM sometimes outputs "GOOG" (Alphabet Class C) and
sometimes "GOOGL" (Class A). These are the same company but treated
as different entities by the KB lookup and signal persistence.

**Decision:** Added an `aliases` field to `companies.json` and a
normalization step in the pipeline that maps aliases to canonical
tickers before KB lookup, graph traversal, and signal persistence.

**Reasoning:** More general than a hardcoded GOOG→GOOGL mapping.
The alias system can handle any future cases (e.g., BRK.B vs BRK-B)
by adding entries to `companies.json` without code changes.

---

### ADR-016: Reflection Agent as Batch Script, Not Pipeline Module

**Date:** 2026-03-22

**Problem:** Need to identify systematic failure patterns in the
system's predictions and propose prompt rule improvements.

**Decision:** Built as a standalone script (`scripts/reflection_agent.py`)
that runs on-demand, analyzes wrong predictions grouped by category ×
direction, sends batches to an LLM for pattern analysis, and writes
a markdown report. The agent proposes rules; a human approves them.

**Reasoning:** The reflection agent reads outcome data and writes a
report. It does not auto-modify prompts or interact with the live
pipeline. This human-in-the-loop gate is non-negotiable at the current
data volume (<2,500 outcomes). Autonomous rule-writing requires a
validated A/B testing framework that doesn't exist yet.

**Output example:** The first reflection run analyzed 1,440 wrong
predictions and identified the Corporate + Bullish bucket (12.4% hit
rate, 514 failures) as the single largest accuracy drag. This directly
led to Rules 11-13 being added to the analyze prompt.

---

### ADR-017: Phase 5 as Scheduled Job, Not Third Pipeline Stage

**Date:** 2026-03-22 (design decision, not yet implemented)

**Problem:** Users tracking a stock need a synthesized "net assessment"
that weighs all active signals against each other, not a stream of
individual per-article signals that may conflict.

**Decision:** Multi-event synthesis runs as a separate scheduled process
every 6 hours, not as a third LLM call on every article. It produces
one net assessment per ticker by synthesizing all active signals,
regime context, and KB data.

**Reasoning:** Adding a third LLM call to every article would triple
per-event cost for marginal benefit (most articles only affect 2-3
tickers that may not have conflicting signals). A periodic synthesis
is cheaper (10-15 LLM calls per run vs. 100+ per day) and produces
the exact output the product needs: a portfolio-level briefing that
the alert system can deliver to users.

---

### ADR-018: Rules 11-13 — Data-Driven Prompt Rules from Reflection

**Date:** 2026-03-22

**Problem:** The reflection agent's first run identified three
systematic failure patterns. CTO review of the raw failure data
(not the LLM's generic suggestions) produced three concrete rules.

**Decisions:**

**Rule 11 — Corporate Events Are Subordinate to Macro Regime:** In
RISK-OFF, cap bullish corporate signals at confidence 0.55 and reduce
magnitude by one level. Rationale: Corporate + Bullish had a 12.4%
hit rate (514 failures) — the system was generating optimistic calls
on earnings beats and deal announcements while the macro environment
was deteriorating.

**Rule 12 — No Signal Without Surprise:** Before generating any
directional signal, check whether the event contains genuinely new,
quantifiable information. Repeated stories, vague implications, and
analysis pieces produce no signal. Rationale: multiple failure batches
showed signals generated on recycled or unquantifiable information.

**Rule 13 — Default to Neutral When Ambiguous:** If magnitude is LOW
and confidence below 0.6, set direction to NEUTRAL. Rationale: the
system was biased toward always making a directional call. 10.4% of
signals are now neutral (up from 0%), representing cases where the
honest answer is "I don't know."

---

### ADR-019: Self-Learning Feedback Loop (Price Outcome Tracker)

**Date:** 2026-03-17

**Problem:** Without ground truth, there's no way to measure whether
the system is improving or degrading over time.

**Decision:** An hourly background job fetches actual prices via
yfinance for signals that have passed their check horizons (24h, 3d,
7d). Compares the actual price movement direction to the predicted
direction and writes `signal_outcome` records to Supabase.

**Reasoning:** This is the foundation that everything else (calibration
context, reflection agent, accuracy dashboard) depends on. Without
measurable outcomes, every architectural change is a guess. The tracker
was gated behind an `ENABLE_PRICE_CHECKER` environment variable for
the initial deployment to avoid running before the pipeline was stable.

---

## Appendix: Key Principles

These emerged from repeated debugging and are now treated as
architectural invariants:

**1. Materiality over recall.** The LLM is the final decision-maker
regardless of retrieval quality. Prompt-level materiality filters are
higher-leverage than tightening KB retrieval.

**2. Strict data provenance.** LLM-identified outputs must never be
modified by graph enrichment — additive-only graph layer prevents
regression.

**3. Fix before full suite.** Validate targeted fixes with minimal
reruns before running full eval cycles to avoid wasted evaluation on
known-fixable issues.

**4. Module isolation.** New layers (news ingestion, graph traversal,
context injection) must be explicitly isolated from existing pipeline
and eval modules to prevent cross-contamination.

**5. Surgical iteration.** One fix at a time, targeted reruns, explicit
pass/fail gates before advancing phases.

**6. Context injection ≠ context utilization.** Adding data to a prompt
doesn't mean the model uses it. Always validate with reasoning output
inspection, and add forcing functions when attention is insufficient.
