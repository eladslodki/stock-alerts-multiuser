# QA Guide – Session Liquidity Sweep Detector

**Version:** Session Liquidity Sweep v2 (sweep-extreme state machine)
**File under test:** `services/session_break_detector.py`
**Replay engine:** `services/session_sweep_replay.py`
**CLI:** `scripts/replay_session_sweep.py`
**API endpoint:** `GET /api/session-sweep/replay`

---

## 1. Prerequisites

| Item | Detail |
|---|---|
| `TWELVEDATA_API_KEY` | Must be set in environment for live candle fetches |
| Python 3.9+ | `zoneinfo` (stdlib); no pytz required |
| PostgreSQL | Only needed for integration tests; unit tests are DB-free |
| Test symbols | `XAU/USD` (gold, volatile), `EUR/USD` (high liquidity) |

Run unit tests first (zero dependencies on DB or network):

```bash
python -m unittest tests.test_session_break_detector -v
# Expected: 36 tests, 0 failures, 0 errors
```

---

## 2. DST Boundary Verification

Session windows shift when Israel switches between Standard (UTC+2) and
Daylight (IDT, UTC+3) time.

| Season | Israel offset | Asia UTC window | London UTC window |
|---|---|---|---|
| Winter (Jan) | UTC+2 | 01:00–05:00 | 07:00–10:00 |
| Summer (Jul) | UTC+3 (DST) | 00:00–04:00 | 06:00–09:00 |

### CLI Commands

```bash
# Winter
python scripts/replay_session_sweep.py --symbol EURUSD --session-type asia --date 2024-01-15 --no-sweep-updates

# Summer (DST active)
python scripts/replay_session_sweep.py --symbol EURUSD --session-type asia --date 2024-07-15 --no-sweep-updates
```

### ✅ Pass Conditions

- Winter Asia SESSION_END shows `session_start_utc: 2024-01-15T01:00:00`
- Summer Asia SESSION_END shows `session_start_utc: 2024-07-15T00:00:00`
- No "session candles not found" errors for valid dates with data

---

## 3. Core Property Checklist

### 3.1  Session High/Low Uses Wicks (Not Close)

**What to check:** `session_high` and `session_low` in the SESSION_END event must
equal the max high wick and min low wick across all session candles.

**Log to search:**

```
[SESSION_SWEEP][SESSION_END] ... session_high=X session_low=Y
```

**API check:**

```bash
curl -s "http://localhost:8080/api/session-sweep/replay?symbol=XAUUSD&session_type=asia&date=2024-01-15&format=json" | python3 -m json.tool | grep -E "session_high|session_low"
```

**✅ Pass:** `session_high` = highest candle.high in the session window; `session_low` = lowest candle.low.
**❌ Fail:** Values match candle close prices instead.

---

### 3.2  `first_sweep_level` Is the Extreme of the Entire Sweep, Not the First Candle

This is the KEY FIX. The sweep extreme must accumulate across **every candle**
from `sweep_start_ts` to `sweep_end_ts` (inclusive), not stop at the first candle.

**Log to search:**

```
[SESSION_SWEEP][SWEEP_START]  → logs initial_sweep_extreme (first candle only)
[SESSION_SWEEP][SWEEP_UPDATE] → logs cumulative sweep_extreme per candle
[SESSION_SWEEP][SWEEP_END]    → logs first_sweep_level (must equal final cumulative extreme)
```

**What to verify in replay output:**

- Look at the SWEEP_UPDATE events. Find the row with `extreme_changed=true` and
  the highest `sweep_extreme` (UP) or lowest `sweep_extreme` (DOWN).
- `first_sweep_level` in SWEEP_END must **equal** that last `extreme_changed` value.
- `first_sweep_level` must **not** equal `initial_sweep_extreme` from SWEEP_START
  unless the first candle happened to be the global extreme.

**Example sequence that proves the fix:**

```
SWEEP_START  initial_sweep_extreme=2021.600
SWEEP_UPDATE sweep_extreme=2021.600  extreme_changed=false
SWEEP_UPDATE sweep_extreme=2022.300  extreme_changed=true   ← higher
SWEEP_UPDATE sweep_extreme=2022.800  extreme_changed=true   ← highest
SWEEP_END    first_sweep_level=2022.800   ← must match last true extreme, NOT 2021.600
CONFIRM      first_sweep_level=2022.800   confirm_level=2022.900
```

**✅ Pass:** `first_sweep_level` in SWEEP_END equals the max/min across ALL SWEEP_UPDATE rows.
**❌ Fail:** `first_sweep_level` equals the level from the first SWEEP_UPDATE (initial candle).

---

### 3.3  Sweep-End Only on Re-Entry

The sweep ends when a candle strictly after `sweep_start_ts` has:
- **UP:**   `candle.low  <= session_high`
- **DOWN:** `candle.high >= session_low`

**Log to search:**

```
[SESSION_SWEEP][SWEEP_END] ... reentered=True reentry_candle_extreme=X session_level=Y
```

**Check in replay:** The SWEEP_END event's `reentry_candle_extreme` must satisfy the
re-entry condition against `session_level`:
- UP:   `reentry_candle_extreme (low) <= session_level (session_high)` ← must be true
- DOWN: `reentry_candle_extreme (high) >= session_level (session_low)` ← must be true

**✅ Pass:** Condition holds for the re-entry candle.
**❌ Fail:** SWEEP_END fires on a candle where the re-entry condition does not hold.

---

### 3.4  Confirm Candle Is Strictly After `sweep_end_ts`

**Log to search:**

```
[SESSION_SWEEP][CONFIRM] ts=... first_sweep_level=X confirm_level=Y
```

**Check:** The CONFIRM event `ts` must be strictly greater than the SWEEP_END `ts`.
Both must appear in the events list. Confirm must NOT fire at the same timestamp as
SWEEP_END.

**How to test:** Use a date where re-entry and confirm happen within a few candles.
Look at the `ts` fields in the JSON events list and verify chronological ordering:

```
SWEEP_END  ts=2024-01-15T05:25:00   ← re-entry candle
...
CONFIRM    ts=2024-01-15T05:35:00   ← must be LATER (>05:25:00)
```

**✅ Pass:** `CONFIRM.ts > SWEEP_END.ts`
**❌ Fail:** `CONFIRM.ts == SWEEP_END.ts` or `CONFIRM.ts < SWEEP_END.ts`

---

### 3.5  No Trigger If No Re-Entry

**Test:** Find a date where price swept above/below the session level but never
came back. The replay should show `NO_REENTRY` event and `final_state=<DIR>_IN_SWEEP`.

```bash
python scripts/replay_session_sweep.py --symbol EURUSD --session-type asia --date <date> --no-sweep-updates
```

**✅ Pass:** Output ends with `NO_REENTRY`, no `TRIGGER` event, exit code 2.
**❌ Fail:** TRIGGER fires without a SWEEP_END event preceding it.

---

### 3.6  No Trigger If No Confirm Break

**Test:** Find a date where re-entry happened but price never broke `first_sweep_level`.
The replay should show SWEEP_END followed by `NO_CONFIRM` and `final_state=<DIR>_WAIT_CONFIRM`.

**✅ Pass:** `final_state` ends in `_WAIT_CONFIRM`, no TRIGGER event.
**❌ Fail:** TRIGGER fires even though no candle with high > first_sweep_level (UP) exists.

---

### 3.7  Anti-Spam: Exactly 1 Trigger Per Session

The DB state machine enforces one trigger per `(user_id, symbol, session_type, session_date)`.

**How to verify:**
1. Allow the detector to trigger once (check `triggered_at` in `session_break_state`).
2. Run `schedule_session_break_detection` again (or wait for next scheduler tick).
3. Check logs for:

```
[SESSION_SWEEP][SESSION_TRACK] ... already_triggered
```

4. Confirm no second email is sent and the DB row's `triggered_at` is unchanged.

**DB query to confirm:**

```sql
SELECT symbol, session_type, session_date, state, triggered_at
FROM session_break_state
WHERE triggered_at IS NOT NULL
ORDER BY triggered_at DESC LIMIT 10;
```

**✅ Pass:** Each `(symbol, session_type, session_date)` row has exactly one `triggered_at` value.
**❌ Fail:** Multiple rows for the same tuple, or `triggered_at` is updated on re-runs.

---

### 3.8  Idempotency – Replaying Twice Gives the Same Result

```bash
python scripts/replay_session_sweep.py --symbol XAUUSD --session-type asia --date 2024-01-15 --format json > run1.json
python scripts/replay_session_sweep.py --symbol XAUUSD --session-type asia --date 2024-01-15 --format json > run2.json
diff run1.json run2.json
# Expected: no diff (ignoring run_id which is random)
```

**✅ Pass:** `first_sweep_level`, `sweep_end_ts`, `confirm_break_ts`, `final_state`,
and all event `ts` fields are identical between runs.
**❌ Fail:** Any of those fields differ.

---

## 4. Log Searchability

All significant events are prefixed `[SESSION_SWEEP]`. Use these patterns to filter
production logs:

| Tag | Meaning |
|---|---|
| `[SESSION_SWEEP][RUN_START]` | Scheduler run began |
| `[SESSION_SWEEP][SESSION_END]` | Session frozen, post-session phase begins |
| `[SESSION_SWEEP][SWEEP_START]` | First wick beyond session level |
| `[SESSION_SWEEP][SWEEP_UPDATE]` | Per-candle sweep extreme update |
| `[SESSION_SWEEP][SWEEP_END]` | Re-entry candle; first_sweep_level locked |
| `[SESSION_SWEEP][CONFIRM]` | Confirm break detected |
| `[SESSION_SWEEP][TRIGGER]` | Alert fired; email being sent |
| `[SESSION_SWEEP][HEARTBEAT]` | End-of-run summary |

**Example grep:**

```bash
# On Heroku / Railway
heroku logs --tail | grep '\[SESSION_SWEEP\]'

# Local
grep -E '\[SESSION_SWEEP\]\[(SWEEP_END|CONFIRM|TRIGGER)\]' app.log
```

**Check first_sweep_level ≠ initial candle:** Compare SWEEP_START `initial_sweep_extreme`
against SWEEP_END `first_sweep_level` in the logs. If they differ, the aggregation is
working correctly.

---

## 5. Replay Tool Reference

### CLI

```bash
# Full timeline with per-candle sweep updates
python scripts/replay_session_sweep.py --symbol XAUUSD --session-type asia --date 2024-01-15

# Clean table (no per-candle updates)
python scripts/replay_session_sweep.py --symbol XAUUSD --session-type asia --date 2024-01-15 --no-sweep-updates

# JSON output for programmatic inspection
python scripts/replay_session_sweep.py --symbol EURUSD --session-type london --date 2024-07-15 --format json | python3 -m json.tool

# Exit codes: 0 = triggered, 2 = not triggered
```

### API Endpoint (authenticated)

```
GET /api/session-sweep/replay

Parameters:
  symbol        EURUSD | XAUUSD | ...
  session_type  asia | london
  date          2024-01-15
  format        json (default) | table
  show_updates  1 (default) | 0
  candles       integer, 1–1000 (default 500)

Example:
  /api/session-sweep/replay?symbol=XAUUSD&session_type=asia&date=2024-01-15&format=table&show_updates=0
```

### Interpreting the Table Output

```
════════════════════════════════════════════════════════════════════════════
  SESSION LIQUIDITY SWEEP REPLAY
  Symbol   : XAUUSD  │  Session: ASIA  │  Date: 2024-01-15
  Run-ID   : a1b2c3d4e5f6
  Timezone : Asia/Jerusalem (Israel)  │  Session UTC: 2024-01-15T01:00 → 2024-01-15T05:00
════════════════════════════════════════════════════════════════════════════
  [SESSION_END]   session_high=2021.500  session_low=2018.200  candles=48
────────────────────────────────────────────────────────────────────────────
  [SWEEP_START]   direction=UP  ts=2024-01-15 05:05:00
                  session_level=2021.500  candle_high=2021.800  initial_extreme=2021.800
────────────────────────────────────────────────────────────────────────────
  [SWEEP_UPDATE]  2024-01-15 05:05:00  candle_extreme=2021.800  sweep_extreme=2021.800
  [SWEEP_UPDATE]  2024-01-15 05:10:00  candle_extreme=2022.300  sweep_extreme=2022.300 ▲ NEW EXTREME
  [SWEEP_UPDATE]  2024-01-15 05:15:00  candle_extreme=2022.800  sweep_extreme=2022.800 ▲ NEW EXTREME
  [SWEEP_UPDATE]  2024-01-15 05:20:00  candle_extreme=2022.100  sweep_extreme=2022.800
────────────────────────────────────────────────────────────────────────────
  [SWEEP_END]     direction=UP  ts=2024-01-15 05:25:00  reentered=True
                  first_sweep_level=2022.800  reentry_low=2021.200  session_level=2021.500
────────────────────────────────────────────────────────────────────────────
  [CONFIRM]       direction=UP  ts=2024-01-15 05:35:00
                  confirm_level=2022.900  first_sweep_level=2022.800  breakout=0.10000
  [TRIGGER]       direction=UP  ts=2024-01-15 05:35:00
════════════════════════════════════════════════════════════════════════════
  FINAL STATE  : TRIGGERED
  Triggered    : YES ✓
  Direction    : UP
  Sweep Extreme: 2022.800     ← must match max of SWEEP_UPDATE rows
  Confirm Lvl  : 2022.900
════════════════════════════════════════════════════════════════════════════
```

Key things to cross-check against your chart:
1. `SESSION_END` high/low match the visible session range wicks
2. `SWEEP_START` ts matches the first bar that poked above/below the session level
3. `▲ NEW EXTREME` markers show where the sweep extended – the last one must equal `first_sweep_level`
4. `SWEEP_END` ts is the re-entry bar (its low dipped back below session_high for UP)
5. `CONFIRM` ts is strictly after `SWEEP_END` ts

---

## 6. Known Edge Cases

| Edge Case | Expected Behavior |
|---|---|
| Wide candle breaks high and re-enters in same bar | Re-entry check requires `ts > sweep_start_ts`, so the break candle itself never triggers re-entry; next candle can |
| Both high and low break on the same candle | UP direction wins (tiebreaker) |
| Re-entry candle has the highest wick (UP) | Its high is still included in `sweep_extreme` before re-entry is detected |
| Session has no post-session candles | `final_state=WAIT_SWEEP_START`, no events after SESSION_END |
| Missing candles / API gap | Detector logs warning and skips; no crash |
| Duplicate trigger (race condition) | DB re-check before marking `triggered_at`; second write is blocked by anti-spam guard |

---

## 7. QA Sign-Off Checklist

Copy this block and mark each item before deploying:

```
[ ] 36 unit tests pass: python -m unittest tests.test_session_break_detector -v
[ ] Winter DST window correct: asia 01:00–05:00 UTC on a Jan date
[ ] Summer DST window correct: asia 00:00–04:00 UTC on a Jul date
[ ] first_sweep_level = max/min across ALL sweep candles (not first)
[ ] confirm ts strictly > sweep_end ts
[ ] no trigger without re-entry
[ ] no trigger without confirm break
[ ] no duplicate trigger (DB re-check passes)
[ ] CLI table output renders correctly for a triggered case
[ ] API endpoint returns 200 JSON with correct event list
[ ] Email includes sweep_start_ts, first_sweep_level, sweep_end_ts, confirm fields
[ ] Log lines searchable with [SESSION_SWEEP][SWEEP_END] and [SESSION_SWEEP][TRIGGER]
```
