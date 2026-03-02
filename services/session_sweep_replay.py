"""
Session Liquidity Sweep – Replay / Debug Engine

Walks through historical 5M candles one-by-one for a given
(symbol, session_type, session_date) and emits a structured event
timeline so you can verify every state-machine transition matches the
chart visually.

Public API
----------
replay_sweep(session_candles, post_candles, session_type, session_date,
             session_start_utc, session_end_utc,
             show_sweep_updates=True, run_id=None)
    → ReplayResult  (dict with 'events', 'final_state', 'triggered', …)

render_table(result)
    → str   human-friendly ASCII timeline

This module is pure computation – no DB, no network.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Dict, List, Optional


# ─── sentinel ────────────────────────────────────────────────────────────────

_INF  = float("inf")
_NINF = float("-inf")


# ─── helpers ─────────────────────────────────────────────────────────────────

def _fmt(v: Optional[float], decimals: int = 5) -> str:
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"


def _fmts(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


# ─── core replay ─────────────────────────────────────────────────────────────

def replay_sweep(
    session_candles: List[Dict],
    post_candles: List[Dict],
    session_type: str,
    session_date: date,
    session_start_utc: datetime,
    session_end_utc: datetime,
    show_sweep_updates: bool = True,
    run_id: Optional[str] = None,
) -> Dict:
    """
    Walk through candles one-by-one and emit a structured event timeline.

    Parameters
    ----------
    session_candles     : candles inside the session window (for high/low)
    post_candles        : candles after session end, sorted oldest→newest
    session_type        : "asia" | "london"
    session_date        : Israel local date of the session
    session_start_utc   : naive-UTC session start datetime
    session_end_utc     : naive-UTC session end datetime
    show_sweep_updates  : if True, emit SWEEP_UPDATE for every post-start candle
    run_id              : optional correlation id; auto-generated if None

    Returns
    -------
    dict with keys:
        run_id, symbol (None – filled by caller), session_type, session_date,
        timezone, session_start_utc, session_end_utc,
        session_high, session_low,
        session_candle_count, post_candle_count,
        events          : list of event dicts (see below)
        final_state     : str  e.g. "TRIGGERED", "IN_SWEEP", "WAIT_CONFIRM",
                                    "WAIT_SWEEP_START", "NO_SESSION_DATA"
        triggered       : bool
        direction       : "UP" | "DOWN" | None
        sweep_start_ts  : ISO str | None
        first_sweep_level : float | None
        sweep_end_ts    : ISO str | None
        confirm_break_ts  : ISO str | None
        confirm_break_level : float | None

    Event shapes
    ~~~~~~~~~~~~
    SESSION_END:    {event, session_high, session_low, session_start_utc,
                     session_end_utc, candle_count}
    SWEEP_START:    {event, ts, direction, session_level_broken,
                     candle_high, candle_low, initial_sweep_extreme}
    SWEEP_UPDATE:   {event, ts, direction, candle_extreme,
                     sweep_extreme, extreme_changed}
    SWEEP_END:      {event, ts, direction, first_sweep_level,
                     reentry_candle_extreme, session_level, reentered}
    CONFIRM:        {event, ts, direction, confirm_level,
                     first_sweep_level, breakout_amount}
    TRIGGER:        {event, ts, direction, first_sweep_level,
                     confirm_break_level, sweep_start_ts, sweep_end_ts}
    NO_SWEEP:       {event, reason}
    NO_REENTRY:     {event, reason, current_sweep_extreme}
    NO_CONFIRM:     {event, reason, first_sweep_level, sweep_end_ts}
    """

    run_id = run_id or uuid.uuid4().hex[:12]
    events: List[Dict] = []

    base = {
        "run_id":           run_id,
        "symbol":           None,
        "session_type":     session_type,
        "session_date":     str(session_date),
        "timezone":         "Asia/Jerusalem",
        "session_start_utc": _iso(session_start_utc),
        "session_end_utc":   _iso(session_end_utc),
        "triggered":        False,
        "direction":        None,
        "sweep_start_ts":   None,
        "first_sweep_level": None,
        "sweep_end_ts":     None,
        "confirm_break_ts": None,
        "confirm_break_level": None,
    }

    # ── Guard: no session data ─────────────────────────────────────────────
    if not session_candles:
        return {
            **base,
            "session_high":        None,
            "session_low":         None,
            "session_candle_count": 0,
            "post_candle_count":    len(post_candles),
            "events":              events,
            "final_state":         "NO_SESSION_DATA",
        }

    # ── STATE 1: build session extremes ───────────────────────────────────
    session_high = max(c["high"] for c in session_candles)
    session_low  = min(c["low"]  for c in session_candles)

    events.append({
        "event":            "SESSION_END",
        "session_high":     session_high,
        "session_low":      session_low,
        "session_start_utc": _iso(session_start_utc),
        "session_end_utc":   _iso(session_end_utc),
        "candle_count":     len(session_candles),
    })

    if not post_candles:
        return {
            **base,
            "session_high":         session_high,
            "session_low":          session_low,
            "session_candle_count": len(session_candles),
            "post_candle_count":    0,
            "events":               events,
            "final_state":          "WAIT_SWEEP_START",
        }

    # ── STATE 2: find first UP / DOWN sweep start ──────────────────────────
    first_up_ts:   Optional[datetime] = None
    first_down_ts: Optional[datetime] = None

    for c in post_candles:
        if first_up_ts is None and c["high"] > session_high:
            first_up_ts = c["timestamp"]
        if first_down_ts is None and c["low"] < session_low:
            first_down_ts = c["timestamp"]
        if first_up_ts and first_down_ts:
            break

    if first_up_ts is None and first_down_ts is None:
        events.append({
            "event":  "NO_SWEEP",
            "reason": "Price never broke the session range after session end",
        })
        return {
            **base,
            "session_high":         session_high,
            "session_low":          session_low,
            "session_candle_count": len(session_candles),
            "post_candle_count":    len(post_candles),
            "events":               events,
            "final_state":          "WAIT_SWEEP_START",
        }

    # Choose direction (earliest wins; tie → UP)
    if first_up_ts and first_down_ts:
        if first_up_ts <= first_down_ts:
            direction, sweep_start_ts = "UP",   first_up_ts
        else:
            direction, sweep_start_ts = "DOWN", first_down_ts
    elif first_up_ts:
        direction, sweep_start_ts = "UP",   first_up_ts
    else:
        direction, sweep_start_ts = "DOWN", first_down_ts

    # Find the sweep-start candle object for the SWEEP_START event
    sweep_start_candle = next(
        c for c in post_candles if c["timestamp"] == sweep_start_ts
    )

    session_level_broken = session_high if direction == "UP" else session_low
    initial_extreme = (sweep_start_candle["high"]
                       if direction == "UP"
                       else sweep_start_candle["low"])

    events.append({
        "event":                "SWEEP_START",
        "ts":                   _iso(sweep_start_ts),
        "direction":            direction,
        "session_level_broken": session_level_broken,
        "candle_high":          sweep_start_candle["high"],
        "candle_low":           sweep_start_candle["low"],
        "initial_sweep_extreme": initial_extreme,
    })

    # ── STATE 3: IN_SWEEP – walk candles, aggregate extreme ───────────────
    sweep_extreme: float = initial_extreme
    sweep_end_ts:  Optional[datetime] = None
    first_sweep_level: Optional[float] = None

    if direction == "UP":
        sweep_extreme = _NINF
        for c in post_candles:
            if c["timestamp"] < sweep_start_ts:
                continue

            prev_extreme  = sweep_extreme
            sweep_extreme = max(sweep_extreme, c["high"])
            changed       = sweep_extreme != prev_extreme

            if show_sweep_updates:
                events.append({
                    "event":          "SWEEP_UPDATE",
                    "ts":             _iso(c["timestamp"]),
                    "direction":      "UP",
                    "candle_extreme": c["high"],
                    "sweep_extreme":  sweep_extreme,
                    "extreme_changed": changed,
                })

            # Re-entry: strictly after sweep_start_ts, low <= session_high
            if c["timestamp"] > sweep_start_ts and c["low"] <= session_high:
                first_sweep_level = sweep_extreme
                sweep_end_ts      = c["timestamp"]
                events.append({
                    "event":                 "SWEEP_END",
                    "ts":                    _iso(sweep_end_ts),
                    "direction":             "UP",
                    "first_sweep_level":     first_sweep_level,
                    "reentry_candle_extreme": c["low"],
                    "session_level":         session_high,
                    "reentered":             True,
                })
                break

    else:  # DOWN
        sweep_extreme = _INF
        for c in post_candles:
            if c["timestamp"] < sweep_start_ts:
                continue

            prev_extreme  = sweep_extreme
            sweep_extreme = min(sweep_extreme, c["low"])
            changed       = sweep_extreme != prev_extreme

            if show_sweep_updates:
                events.append({
                    "event":          "SWEEP_UPDATE",
                    "ts":             _iso(c["timestamp"]),
                    "direction":      "DOWN",
                    "candle_extreme": c["low"],
                    "sweep_extreme":  sweep_extreme,
                    "extreme_changed": changed,
                })

            # Re-entry: strictly after sweep_start_ts, high >= session_low
            if c["timestamp"] > sweep_start_ts and c["high"] >= session_low:
                first_sweep_level = sweep_extreme
                sweep_end_ts      = c["timestamp"]
                events.append({
                    "event":                 "SWEEP_END",
                    "ts":                    _iso(sweep_end_ts),
                    "direction":             "DOWN",
                    "first_sweep_level":     first_sweep_level,
                    "reentry_candle_extreme": c["high"],
                    "session_level":         session_low,
                    "reentered":             True,
                })
                break

    # No re-entry yet
    if sweep_end_ts is None:
        events.append({
            "event":               "NO_REENTRY",
            "reason":              "Sweep in progress – no re-entry candle yet",
            "current_sweep_extreme": sweep_extreme,
        })
        return {
            **base,
            "session_high":         session_high,
            "session_low":          session_low,
            "session_candle_count": len(session_candles),
            "post_candle_count":    len(post_candles),
            "events":               events,
            "final_state":          f"{direction}_IN_SWEEP",
            "direction":            direction,
            "sweep_start_ts":       _iso(sweep_start_ts),
            "first_sweep_level":    sweep_extreme,  # current best-known extreme
        }

    # ── STATE 4: WAIT_CONFIRM ─────────────────────────────────────────────
    confirm_ts:    Optional[datetime] = None
    confirm_level: Optional[float]   = None

    for c in post_candles:
        if c["timestamp"] <= sweep_end_ts:
            continue  # strictly after re-entry candle

        if direction == "UP" and c["high"] > first_sweep_level:
            confirm_ts    = c["timestamp"]
            confirm_level = c["high"]
            break
        if direction == "DOWN" and c["low"] < first_sweep_level:
            confirm_ts    = c["timestamp"]
            confirm_level = c["low"]
            break

    if confirm_ts is None:
        events.append({
            "event":            "NO_CONFIRM",
            "reason":           "Re-entry done – waiting for confirm break of first_sweep_level",
            "first_sweep_level": first_sweep_level,
            "sweep_end_ts":      _iso(sweep_end_ts),
        })
        return {
            **base,
            "session_high":         session_high,
            "session_low":          session_low,
            "session_candle_count": len(session_candles),
            "post_candle_count":    len(post_candles),
            "events":               events,
            "final_state":          f"{direction}_WAIT_CONFIRM",
            "direction":            direction,
            "sweep_start_ts":       _iso(sweep_start_ts),
            "first_sweep_level":    first_sweep_level,
            "sweep_end_ts":         _iso(sweep_end_ts),
        }

    # ── TRIGGERED ─────────────────────────────────────────────────────────
    breakout_amount = abs(confirm_level - first_sweep_level)
    events.append({
        "event":               "CONFIRM",
        "ts":                  _iso(confirm_ts),
        "direction":           direction,
        "confirm_level":       confirm_level,
        "first_sweep_level":   first_sweep_level,
        "breakout_amount":     round(breakout_amount, 5),
    })
    events.append({
        "event":               "TRIGGER",
        "ts":                  _iso(confirm_ts),
        "direction":           direction,
        "first_sweep_level":   first_sweep_level,
        "confirm_break_level": confirm_level,
        "sweep_start_ts":      _iso(sweep_start_ts),
        "sweep_end_ts":        _iso(sweep_end_ts),
    })

    return {
        **base,
        "session_high":         session_high,
        "session_low":          session_low,
        "session_candle_count": len(session_candles),
        "post_candle_count":    len(post_candles),
        "events":               events,
        "final_state":          "TRIGGERED",
        "triggered":            True,
        "direction":            direction,
        "sweep_start_ts":       _iso(sweep_start_ts),
        "first_sweep_level":    first_sweep_level,
        "sweep_end_ts":         _iso(sweep_end_ts),
        "confirm_break_ts":     _iso(confirm_ts),
        "confirm_break_level":  confirm_level,
    }


# ─── ASCII table renderer ─────────────────────────────────────────────────────

_W = 76  # total table width


def _rule(char: str = "─") -> str:
    return char * _W


def _header(result: Dict) -> List[str]:
    lines = [
        _rule("═"),
        "  SESSION LIQUIDITY SWEEP REPLAY",
        f"  Symbol   : {result.get('symbol') or '—'}  │  "
        f"Session: {result['session_type'].upper()}  │  "
        f"Date: {result['session_date']}",
        f"  Run-ID   : {result['run_id']}",
        f"  Timezone : Asia/Jerusalem (Israel)  │  "
        f"Session UTC: {(result.get('session_start_utc') or '—')[:16]} → "
        f"{(result.get('session_end_utc') or '—')[:16]}",
        _rule("═"),
    ]
    return lines


def _footer(result: Dict) -> List[str]:
    state  = result.get("final_state", "—")
    trig   = "YES ✓" if result.get("triggered") else "NO"
    lines  = [
        _rule("═"),
        f"  FINAL STATE  : {state}",
        f"  Triggered    : {trig}",
    ]
    if result.get("direction"):
        lines.append(f"  Direction    : {result['direction']}")
    if result.get("first_sweep_level") is not None:
        lines.append(f"  Sweep Extreme: {_fmt(result['first_sweep_level'])}")
    if result.get("confirm_break_level") is not None:
        lines.append(f"  Confirm Lvl  : {_fmt(result['confirm_break_level'])}")
    lines.append(_rule("═"))
    return lines


def render_table(result: Dict, show_sweep_updates: bool = True) -> str:
    """
    Render a replay result as a human-friendly ASCII timeline.

    Parameters
    ----------
    result             : dict returned by replay_sweep()
    show_sweep_updates : if False, SWEEP_UPDATE events are omitted

    Returns a multi-line string ready for print() or logging.
    """
    rows: List[str] = []
    rows.extend(_header(result))

    sh   = result.get("session_high")
    sl   = result.get("session_low")

    for ev in result.get("events", []):
        name = ev["event"]

        if name == "SESSION_END":
            rows.append(
                f"  [SESSION_END]   session_high={_fmt(sh)}  "
                f"session_low={_fmt(sl)}  "
                f"candles={ev['candle_count']}"
            )
            rows.append(_rule())

        elif name == "SWEEP_START":
            d = ev["direction"]
            rows.append(
                f"  [SWEEP_START]   direction={d}  "
                f"ts={ev['ts'][:19]}"
            )
            rows.append(
                f"                  session_level={_fmt(ev['session_level_broken'])}  "
                f"candle_{'high' if d=='UP' else 'low'}="
                f"{_fmt(ev['candle_high'] if d=='UP' else ev['candle_low'])}  "
                f"initial_extreme={_fmt(ev['initial_sweep_extreme'])}"
            )
            rows.append(_rule())

        elif name == "SWEEP_UPDATE":
            if not show_sweep_updates:
                continue
            changed_mark = " ▲ NEW EXTREME" if ev["direction"] == "UP" and ev.get("extreme_changed") \
                      else " ▼ NEW EXTREME" if ev["direction"] == "DOWN" and ev.get("extreme_changed") \
                      else ""
            rows.append(
                f"  [SWEEP_UPDATE]  {ev['ts'][:19]}  "
                f"candle_extreme={_fmt(ev['candle_extreme'])}  "
                f"sweep_extreme={_fmt(ev['sweep_extreme'])}"
                f"{changed_mark}"
            )

        elif name == "SWEEP_END":
            rows.append(_rule())
            d = ev["direction"]
            side = "low" if d == "UP" else "high"
            rows.append(
                f"  [SWEEP_END]     direction={d}  "
                f"ts={ev['ts'][:19]}  reentered=True"
            )
            rows.append(
                f"                  first_sweep_level={_fmt(ev['first_sweep_level'])}  "
                f"reentry_{side}={_fmt(ev['reentry_candle_extreme'])}  "
                f"session_level={_fmt(ev['session_level'])}"
            )
            rows.append(_rule())

        elif name == "CONFIRM":
            rows.append(
                f"  [CONFIRM]       direction={ev['direction']}  "
                f"ts={ev['ts'][:19]}"
            )
            rows.append(
                f"                  confirm_level={_fmt(ev['confirm_level'])}  "
                f"first_sweep_level={_fmt(ev['first_sweep_level'])}  "
                f"breakout={_fmt(ev['breakout_amount'])}"
            )

        elif name == "TRIGGER":
            rows.append(
                f"  [TRIGGER]       direction={ev['direction']}  "
                f"ts={ev['ts'][:19]}"
            )
            rows.append(_rule())

        elif name == "NO_SWEEP":
            rows.append(f"  [NO_SWEEP]      {ev['reason']}")

        elif name == "NO_REENTRY":
            rows.append(
                f"  [NO_REENTRY]    {ev['reason']}  "
                f"current_extreme={_fmt(ev['current_sweep_extreme'])}"
            )

        elif name == "NO_CONFIRM":
            rows.append(
                f"  [NO_CONFIRM]    {ev['reason']}"
            )
            rows.append(
                f"                  first_sweep_level={_fmt(ev['first_sweep_level'])}  "
                f"sweep_end={ev['sweep_end_ts'][:19] if ev.get('sweep_end_ts') else '—'}"
            )

    rows.extend(_footer(result))
    return "\n".join(rows)
