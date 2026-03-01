# Fundamentals Reports

AI-generated quarterly financial reports sourced from SEC EDGAR 10-Q / 10-K filings.

---

## Quarter Detection

Fiscal quarters are derived from the `period_end` (report date) of SEC filings:

| `period_end` month | Quarter |
|--------------------|---------|
| 1 – 3              | Q1      |
| 4 – 6              | Q2      |
| 7 – 9              | Q3      |
| 10 – 12            | Q4      |

**Q4 Rule:** Q4 is sourced exclusively from 10-K annual filings. No 10-Q exists for
the fourth fiscal quarter. Q1/Q2/Q3 are sourced from 10-Q filings only.

Quarter deduplication: if multiple filings map to the same `(year, quarter)` pair,
only the first one (most recent) is kept.

---

## API Reference

### `GET /api/quarters/<ticker>`

Returns fiscal quarters for a ticker, newest-first. Each entry includes:

```json
{
  "year": 2025,
  "quarter": "Q3",
  "label": "2025 Q3",
  "period_end": "2025-09-30",
  "filed_at": "2025-10-15",
  "source_filing_id": "0001234567-25-000042",
  "source_filing_type": "10-Q",
  "has_report": true
}
```

`has_report` is `true` when a rendered HTML report already exists in the DB.

---

### `POST /api/reports/generate`

Starts background generation for a specific quarter. Returns immediately (HTTP 202).

**Request body:**
```json
{ "ticker": "OKE", "year": 2025, "quarter": "Q3", "force": false }
```

**Response (202 — generation started):**
```json
{ "status": "generating", "filing_id": "0001234567-25-000042" }
```

**Response (200 — already cached):**
```json
{ "status": "done", "url_html": "/reports/OKE/0001234567-25-000042", "url_json": "..." }
```

Poll `GET /api/reports/status/<filing_id>` every 3 seconds until `status` is `"done"` or `"error"`.

---

### `GET /api/reports/status/<filing_id>`

```json
{ "status": "generating" }
{ "status": "done", "url_html": "...", "url_json": "..." }
{ "status": "error", "error": "..." }
{ "status": "not_started" }
```

---

### `GET /reports/<ticker>/<filing_id>`

Renders the cached HTML report. Returns 404 if not yet generated.

---

### `GET /api/reports/<ticker>/<filing_id>`

Returns the cached `ReportData/v1` JSON. Returns 404 if not generated.

---

## OOM-Proof Ingestion Pipeline

The filing text pipeline is engineered for a single-worker, memory-constrained
environment (~90 MB RSS limit). Intermediate strings are freed as soon as they
are no longer needed.

### Memory caps

| Cap | Value | Purpose |
|-----|-------|---------|
| `MAX_FILING_BYTES` | 2.5 MB | Network download limit (streamed) |
| `MAX_HTML_PARSE_CHARS` | 600 KB | Hard truncation after `prestrip_html` |
| `MAX_RELEVANT_CHARS` | 250 KB | Text fed to the LLM |
| `MAX_CHUNKS` | 20 | Max chunks for map-reduce |
| `MAX_CHUNK_CHARS` | 14 KB | Max characters per chunk |

### Pipeline stages

```
raw HTML (≤ 2.5 MB, streamed via io.StringIO)
    │
    ▼  prestrip_html()
remove <script>, <style>, HTML comments, <table> via regex
truncate to 600 KB
    │
    ▼  html_to_text()
strip remaining tags, collapse artefacts, emit clean lines to StringIO
    │
    ▼  extract_relevant_sections()
scan for section keywords (MD&A, Risk Factors, Outlook, Revenue, …)
take up to LINES_PER_SECTION lines per section
hard-cap result at 250 KB
    │
    ▼  chunk_text()
overlapping 14 KB chunks (500 char overlap), max 20 chunks
    │
    ▼  LLM map-reduce
map: extract facts from each chunk (max 6 chunks)
reduce: synthesise into ReportData/v1 JSON
```

### Why tables are stripped first

SEC filings are table-heavy. A single `<table>` element can be several MB.
`prestrip_html()` uses `re.sub` with `re.DOTALL` to remove all `<table>…</table>`
blocks *before* any further parsing. Because each `re.sub` call reassigns the
`html` variable, Python's reference-counting GC frees the previous string
immediately — no peak doubling.

### Filings cache

`sec_provider.list_filings()` caches the SEC submissions JSON per ticker for
5 minutes (`_FILINGS_CACHE_TTL = 300`). This prevents a second download of the
1–3 MB submissions JSON when the user clicks "ייצר" seconds after searching
(the search already populated the cache).

### `[MEM]` log checkpoints

The following `[MEM]` log lines are emitted for each generation:

```
[MEM] <ticker>/<filing_id> start: XX.X MB RSS
[MEM] <ticker> after_fetch: XX.X MB RSS
[MEM] <ticker> after extraction (freed): XX.X MB RSS
[MEM] <ticker> after LLM map-reduce: XX.X MB RSS
[MEM] <ticker>/<filing_id> done (generated|cached): XX.X MB RSS
```

Crashes between `start` and `after_fetch` indicate an OOM during the
`list_filings` call or filing content download. Crashes between `after_fetch`
and `after extraction` indicate OOM during HTML parsing.

---

## Report Schema

Reports use `ReportData/v1` schema with:
- `cover` — ticker, company, quarter label (e.g. "2025 Q3"), 4 KPIs
- `toc` — 10-item table of contents
- `sections` — 10 sections (s1–s10): revenue, profitability, cash flow,
  balance sheet, guidance, risks, segment breakdown, management quotes, outlook, appendix
- `analysis` (template only) — earnings surprise table, market reaction narrative,
  narrative change vs prior quarter

The `quarter_label` (e.g. "2025 Q3") is passed to the LLM reduce prompt as
`filing_type`, so the report cover shows the user-friendly quarter label instead
of "10-Q" or "10-K".
