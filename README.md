# Stock Alerts — Production Environment Variables

## Required

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (`postgresql://user:pass@host/db`). Falls back to `sqlite:///fundamentals.db` for local dev. |
| `ANTHROPIC_API_KEY` | Anthropic API key for LLM report generation. Must start with `sk-ant-`. Without this the app falls back to mock data. |
| `SECRET_KEY` | Flask session secret. Set to a long random string in production. |

## Optional / Feature flags

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_API_KEY` | — | Alias for `ANTHROPIC_API_KEY` (checked second). |
| `AI_MODEL` | `claude-opus-4-6` | Anthropic model ID to use for generation. |
| `LLM_USE_MOCK` | `0` | Set to `1` to force mock LLM responses (no API calls, free). |
| `SEC_USER_AGENT` | `StockAlertsApp/1.0 admin@stockalerts.app` | SEC EDGAR requires a `User-Agent` header with contact info. Override with your own. |
| `SEC_MAX_FILING_BYTES` | `2500000` | Hard cap on SEC filing download size (bytes). |
| `DEBUG_TOKEN` | — | If set, enables `GET /api/debug/env?token=<value>` for env inspection. Do not set in production unless actively debugging. |

## Common issues

### `anthropic.AuthenticationError: 401 invalid x-api-key`

The API key is present in the env but incorrect or whitespace-padded.

1. Verify the key starts with `sk-ant-api03-` (or similar prefix for your account).
2. Check for leading/trailing spaces: Railway and Heroku env vars sometimes include them.
3. Confirm with the debug endpoint:
   ```
   GET /api/debug/env?token=<DEBUG_TOKEN>
   ```
   Response `"ANTHROPIC_API_KEY_set": true` means the variable is present and non-empty after stripping. If this is `true` and you still get 401, the key value itself is wrong.

### Report generation shows no progress / hangs

Check Railway logs for the last `STEP N begin` breadcrumb:

| Last log seen | Root cause |
|---------------|------------|
| `STEP 0 begin` | Lock acquire or DB connection stall |
| `STEP 1 done` + no STEP 2 | `list_filings` network stall (SEC EDGAR) |
| `STEP 3b begin` | `fetch_filing_content` network stall (SEC doc server) |
| `STEP 4 begin` | HTML pre-stripping CPU stall (very large filing) |
| `STEP 8 begin` | LLM API call stall or rate limit |

### Mock data in reports

If reports show Hebrew stub data instead of real analysis, `LLM_USE_MOCK=1` is set or `ANTHROPIC_API_KEY` is missing/empty.

## Gunicorn (Procfile)

```
web: gunicorn app:app \
  --timeout 300 \
  --workers 1 \
  --threads 4 \
  --worker-class gthread \
  --max-requests 50 \
  --max-requests-jitter 20 \
  --bind 0.0.0.0:$PORT
```

- `--workers 1` — required; the in-process generation state (`_gen_status` dict) is not shared across workers.
- `--threads 4` / `--worker-class gthread` — allows SEC/LLM I/O to run concurrently with HTTP requests.
- `--timeout 300` — LLM generation can take 60–120 s; 300 s gives ample headroom.
- `--max-requests 50` — periodic worker restart prevents RSS memory creep from large filings.
