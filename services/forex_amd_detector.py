"""
Institutional-grade Forex AMD detector with ICT-style logic
"""

import logging
import os
import uuid
import time as _time
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
from database import db
import json

logger = logging.getLogger(__name__)


# ============================================
# CONFIGURATION
# ============================================

class AMDConfig:
    """Configuration for AMD detection"""
    
    # Session Windows (UTC)
    LONDON_START = time(8, 0)   # 8:00 AM UTC
    LONDON_END = time(16, 0)    # 4:00 PM UTC
    NEWYORK_START = time(13, 0) # 1:00 PM UTC
    NEWYORK_END = time(21, 0)   # 9:00 PM UTC
    
    # Displacement Filters
    DISPLACEMENT_BODY_MULTIPLIER = 1.5  # Must be 1.5x avg body
    DISPLACEMENT_ATR_MULTIPLIER = 1.5   # Must be 1.5x ATR
    BODY_LOOKBACK = 10  # Compare to last 10 candles
    
    # Sweep Filters
    MIN_WICK_PERCENTAGE = 40  # Wick must be 40% of range
    MIN_SWEEP_DISTANCE_PIPS = 5  # Minimum sweep distance
    
    # Volatility Filters
    MIN_ATR_THRESHOLD = 0.0010  # Minimum ATR (10 pips for most pairs)
    ATR_PERIOD = 14
    
    # Accumulation Quality
    ACCUM_MIN_CANDLES = 5
    ACCUM_MAX_CANDLES = 20
    ACCUM_RANGE_THRESHOLD = 0.5  # Max 50% of recent ATR (legacy, no longer used)
    ACCUM_DIRECTIONAL_THRESHOLD = 0.3  # Max 30% directional bias

    # Accumulation – fixed window spec (2 hours of 15-min candles)
    ACCUM_FIXED_WINDOW = 8         # candles in the look-back window
    ACCUM_MAX_RANGE_POINTS = 5200  # max range in points (1 pt = 0.0001 price units)
    
    # IFVG Quality
    IFVG_MIN_GAP_PIPS = 3
    IFVG_RETEST_WINDOW_CANDLES = 10
    
    # State Timeouts
    MAX_SWEEP_TO_DISPLACEMENT_CANDLES = 5
    MAX_DISPLACEMENT_TO_IFVG_CANDLES = 10
    
    # Quality Scoring
    MIN_QUALITY_SCORE = 6  # Out of 10

    # ── Observability ──────────────────────────────────────────────
    LOG_PREFIX = "[AMD_FOREX]"
    UNHEALTHY_THRESHOLD_MINUTES = 30   # flag stuck if no ok run in X min


# ============================================
# STATE DEFINITIONS
# ============================================

class AMDState:
    IDLE = 0
    ACCUMULATION = 1
    SWEEP_DETECTED = 2
    DISPLACEMENT_CONFIRMED = 3
    WAIT_IFVG = 4


# ============================================
# MAIN DETECTOR CLASS
# ============================================

class ForexAMDDetector:
    """Detects institutional AMD patterns with quality filters"""
    
    def __init__(self):
        self.config = AMDConfig()
    
    # ========================================
    # PUBLIC METHODS
    # ========================================
    
    def detect_for_user(self, user_id: int, run_id: str = "") -> Dict:
        """
        Main detection loop for user's watchlist.

        Returns: {
            'alerts': List[Dict],
            'symbols': int,
            'candles_fetched': int,
            'symbols_skipped': int,
            'states_advanced': int,
        }
        """
        from services.forex_data_provider import forex_data_provider

        result: Dict = {
            'alerts': [],
            'symbols': 0,
            'candles_fetched': 0,
            'symbols_skipped': 0,
            'states_advanced': 0,
        }

        watchlist = db.execute("""
            SELECT symbol FROM forex_watchlist
            WHERE user_id = %s
            ORDER BY added_at
        """, (user_id,), fetchall=True)

        if not watchlist:
            return result

        from services.forex_data_provider import normalize_symbol as _norm_sym

        result['symbols'] = len(watchlist)

        for row in watchlist:
            symbol_raw = row['symbol']
            # Normalize to canonical form (e.g. XAUUSD → XAU/USD) so that
            # all DB state keys are consistent regardless of how the symbol
            # was stored when it was first added to the watchlist.
            _norm, _err = _norm_sym(symbol_raw)
            symbol = _norm if _norm else symbol_raw
            if symbol != symbol_raw:
                logger.info(
                    "[AMD_FOREX][NORM] run_id=%s user=%s symbol_raw=%s normalized=%s",
                    run_id, user_id, symbol_raw, symbol,
                )
            try:
                candles = forex_data_provider.get_recent_candles(
                    symbol, timeframe='15m', count=100
                )

                if not candles:
                    logger.warning(
                        "[AMD_FOREX][SKIP] run_id=%s user=%s symbol=%s reason=no_candles",
                        run_id, user_id, symbol,
                    )
                    result['symbols_skipped'] += 1
                    continue

                result['candles_fetched'] += len(candles)

                state_before = self._load_state(user_id, symbol).get(
                    'current_state', AMDState.IDLE
                )

                alert = self.process_state_machine(
                    user_id, symbol, candles, run_id=run_id
                )

                state_after = self._load_state(user_id, symbol).get(
                    'current_state', AMDState.IDLE
                )
                if state_after != state_before or alert:
                    result['states_advanced'] += 1

                if alert:
                    result['alerts'].append(alert)

            except Exception as exc:
                logger.error(
                    "[AMD_FOREX][SYMBOL_ERROR] run_id=%s user=%s symbol=%s err=%s",
                    run_id, user_id, symbol, exc, exc_info=True,
                )

        return result
    
    # ========================================
    # SESSION FILTERS
    # ========================================
    
    def is_active_session(self, timestamp: datetime) -> Optional[str]:
        """
        Check if timestamp is in high-liquidity session
        
        Returns: 'london', 'newyork', or None
        """
        utc_time = timestamp.time()
        
        if self.config.LONDON_START <= utc_time < self.config.LONDON_END:
            return 'london'
        
        if self.config.NEWYORK_START <= utc_time < self.config.NEWYORK_END:
            return 'newyork'
        
        # Overlap period counts as both (choose more active)
        if (self.config.NEWYORK_START <= utc_time < self.config.LONDON_END):
            return 'newyork'  # NY more volatile
        
        return None
    
    # ========================================
    # ACCUMULATION DETECTION
    # ========================================
    
    def detect_accumulation(self, candles: List[Dict]) -> Optional[Dict]:
        """
        Detect quality accumulation phase using a fixed 8-candle (2-hour) window.

        Requirements:
        - Fixed window: ACCUM_FIXED_WINDOW (8) candles
        - Range compression: range_pts <= ACCUM_MAX_RANGE_POINTS (5200 pts)
          where 1 pt = 0.0001 price units (e.g. 5200 pts = $0.52 for XAU/USD)
        - No strong directional bias (< 30%)
        - Multiple touches of boundaries (≥ 2 each side)

        Returns: {
            'start_idx': int,
            'end_idx': int,
            'high': float,
            'low': float,
            'range': float,          # in price units
            'quality_score': float   # 0-10
        }
        """
        _POINT = 0.0001
        window_size = self.config.ACCUM_FIXED_WINDOW

        if len(candles) < window_size:
            return None

        window = candles[-window_size:]
        atr = self._calculate_atr(candles[-self.config.ATR_PERIOD:])

        # 1. Range compression check (fixed point threshold)
        high = max(c['high'] for c in window)
        low  = min(c['low']  for c in window)
        range_price = high - low
        range_pts   = range_price / _POINT

        if range_pts > self.config.ACCUM_MAX_RANGE_POINTS:
            return None  # Too wide

        # 2. Directional bias check
        net_movement    = window[-1]['close'] - window[0]['close']
        directional_pct = abs(net_movement) / range_price if range_price > 0 else 1.0

        if directional_pct > self.config.ACCUM_DIRECTIONAL_THRESHOLD:
            return None  # Too directional

        # 3. Boundary touches check
        touches_high = sum(1 for c in window if abs(c['high'] - high) < range_price * 0.1)
        touches_low  = sum(1 for c in window if abs(c['low']  - low)  < range_price * 0.1)

        if touches_high < 2 or touches_low < 2:
            return None  # Not enough consolidation

        # 4. Quality score
        quality = self._score_accumulation(window, atr, range_price, directional_pct)

        if quality < self.config.MIN_QUALITY_SCORE:
            return None

        return {
            'start_idx':    len(candles) - window_size,
            'end_idx':      len(candles) - 1,
            'high':         high,
            'low':          low,
            'range':        range_price,
            'quality_score': quality,
        }
    
    # ========================================
    # SWEEP DETECTION
    # ========================================
    
    def detect_sweep(self, candles: List[Dict], accum_high: float, 
                     accum_low: float) -> Optional[Dict]:
        """
        Detect liquidity sweep with strength filter
        
        Requirements:
        - Wick ≥ 40% of candle range
        - Sweep distance ≥ 5 pips
        - Clear rejection (close back inside range)
        
        Returns: {
            'direction': 'bullish' | 'bearish',
            'level': float,
            'wick_pct': float,
            'strength': float (0-10)
        }
        """
        last_candle = candles[-1]
        
        # Check for sweep below accumulation (bullish setup)
        if last_candle['low'] < accum_low:
            wick_length = last_candle['close'] - last_candle['low']
            candle_range = last_candle['high'] - last_candle['low']
            
            if candle_range == 0:
                return None
            
            wick_pct = (wick_length / candle_range) * 100
            sweep_distance = accum_low - last_candle['low']
            
            # Apply filters
            if wick_pct < self.config.MIN_WICK_PERCENTAGE:
                return None
            
            if sweep_distance < self._pips(self.config.MIN_SWEEP_DISTANCE_PIPS):
                return None
            
            # Close must be back above accumulation low
            if last_candle['close'] <= accum_low:
                return None
            
            strength = self._score_sweep(wick_pct, sweep_distance)
            
            return {
                'direction': 'bullish',
                'level': last_candle['low'],
                'wick_pct': wick_pct,
                'strength': strength
            }
        
        # Check for sweep above accumulation (bearish setup)
        if last_candle['high'] > accum_high:
            wick_length = last_candle['high'] - last_candle['close']
            candle_range = last_candle['high'] - last_candle['low']
            
            if candle_range == 0:
                return None
            
            wick_pct = (wick_length / candle_range) * 100
            sweep_distance = last_candle['high'] - accum_high
            
            if wick_pct < self.config.MIN_WICK_PERCENTAGE:
                return None
            
            if sweep_distance < self._pips(self.config.MIN_SWEEP_DISTANCE_PIPS):
                return None
            
            if last_candle['close'] >= accum_high:
                return None
            
            strength = self._score_sweep(wick_pct, sweep_distance)
            
            return {
                'direction': 'bearish',
                'level': last_candle['high'],
                'wick_pct': wick_pct,
                'strength': strength
            }
        
        return None
    
    # ========================================
    # DISPLACEMENT DETECTION
    # ========================================
    
    def detect_displacement(self, candles: List[Dict], sweep_direction: str) -> Optional[Dict]:
        """
        Detect strong displacement candle after sweep
        
        Requirements:
        - Body > 1.5x average of last 10 candles
        OR Range > 1.5x ATR
        - Direction aligns with setup (bullish/bearish)
        - Strong momentum (minimal wicks)
        
        Returns: {
            'candle_idx': int,
            'body_size': float,
            'vs_avg_body': float (ratio),
            'vs_atr': float (ratio),
            'quality': float (0-10)
        }
        """
        if len(candles) < self.config.BODY_LOOKBACK + 1:
            return None
        
        current = candles[-1]
        lookback = candles[-(self.config.BODY_LOOKBACK + 1):-1]
        
        # Calculate reference values
        avg_body = sum(abs(c['close'] - c['open']) for c in lookback) / len(lookback)
        atr = self._calculate_atr(candles[-self.config.ATR_PERIOD:])
        
        # Current candle metrics
        body = abs(current['close'] - current['open'])
        range_val = current['high'] - current['low']
        
        # Direction check
        is_bullish = current['close'] > current['open']
        is_bearish = current['close'] < current['open']
        
        if sweep_direction == 'bullish' and not is_bullish:
            return None
        if sweep_direction == 'bearish' and not is_bearish:
            return None
        
        # Size requirements
        body_ratio = body / avg_body if avg_body > 0 else 0
        atr_ratio = range_val / atr if atr > 0 else 0
        
        passes_body_filter = body_ratio >= self.config.DISPLACEMENT_BODY_MULTIPLIER
        passes_atr_filter = atr_ratio >= self.config.DISPLACEMENT_ATR_MULTIPLIER
        
        if not (passes_body_filter or passes_atr_filter):
            return None
        
        # Quality scoring
        quality = self._score_displacement(body_ratio, atr_ratio, current)
        
        return {
            'candle_idx': len(candles) - 1,
            'body_size': body,
            'vs_avg_body': body_ratio,
            'vs_atr': atr_ratio,
            'quality': quality
        }
    
    # ========================================
    # IFVG DETECTION
    # ========================================
    
    def detect_ifvg(self, candles: List[Dict], displacement_idx: int, 
                    direction: str) -> Optional[Dict]:
        """
        Detect Inverse Fair Value Gap with quality checks
        
        Requirements:
        - Gap ≥ 3 pips
        - Retest within 10 candles
        - Structure alignment
        
        Returns: {
            'candle_idx': int,
            'gap_high': float,
            'gap_low': float,
            'gap_size': float,
            'retest_idx': int
        }
        """
        # Search for FVG pattern after displacement
        search_start = displacement_idx + 1
        search_end = min(len(candles), displacement_idx + self.config.MAX_DISPLACEMENT_TO_IFVG_CANDLES)
        
        for i in range(search_start, search_end - 2):
            # FVG = gap between candle[i-1].low and candle[i+1].high (bullish)
            # or gap between candle[i-1].high and candle[i+1].low (bearish)
            
            if direction == 'bullish':
                gap_low = candles[i + 1]['high']
                gap_high = candles[i - 1]['low']
                
                if gap_high > gap_low:  # Valid gap
                    gap_size = gap_high - gap_low
                    
                    if gap_size < self._pips(self.config.IFVG_MIN_GAP_PIPS):
                        continue
                    
                    # Check for retest
                    retest_idx = self._find_retest(candles, i + 2, search_end, 
                                                    gap_low, gap_high, 'bullish')
                    
                    if retest_idx:
                        return {
                            'candle_idx': i,
                            'gap_high': gap_high,
                            'gap_low': gap_low,
                            'gap_size': gap_size,
                            'retest_idx': retest_idx
                        }
            
            else:  # bearish
                gap_high = candles[i + 1]['low']
                gap_low = candles[i - 1]['high']
                
                if gap_high > gap_low:
                    gap_size = gap_high - gap_low
                    
                    if gap_size < self._pips(self.config.IFVG_MIN_GAP_PIPS):
                        continue
                    
                    retest_idx = self._find_retest(candles, i + 2, search_end,
                                                    gap_low, gap_high, 'bearish')
                    
                    if retest_idx:
                        return {
                            'candle_idx': i,
                            'gap_high': gap_high,
                            'gap_low': gap_low,
                            'gap_size': gap_size,
                            'retest_idx': retest_idx
                        }
        
        return None
    
    # ========================================
    # VOLATILITY FILTER
    # ========================================
    
    def check_volatility(self, candles: List[Dict]) -> bool:
        """
        Ensure market has sufficient volatility
        
        Returns: True if ATR above threshold
        """
        atr = self._calculate_atr(candles[-self.config.ATR_PERIOD:])
        return atr >= self.config.MIN_ATR_THRESHOLD
    
    # ========================================
    # STATE MACHINE
    # ========================================
    
    def process_state_machine(self, user_id: int, symbol: str,
                              candles: List[Dict],
                              run_id: str = "") -> Optional[Dict]:
        """
        Main state machine processor
        
        States:
        0. IDLE → scan for accumulation
        1. ACCUMULATION → wait for sweep
        2. SWEEP_DETECTED → wait for displacement
        3. DISPLACEMENT_CONFIRMED → wait for IFVG
        4. WAIT_IFVG → validate and alert
        
        Returns: AMD alert dict if complete, None otherwise
        """
        # Load current state from DB
        state_data = self._load_state(user_id, symbol)
        current_state = state_data.get('current_state', AMDState.IDLE)
        
        # State 0: IDLE
        if current_state == AMDState.IDLE:
            # ── Volatility check ────────────────────────────────────────────
            # Compute ATR once; reuse for the accumulation-miss log below.
            _PIP = 0.0001
            atr = self._calculate_atr(candles[-self.config.ATR_PERIOD:])
            vol_ok = atr >= self.config.MIN_ATR_THRESHOLD
            # Set AMD_BYPASS_VOLATILITY=1 in env to skip this gate for one-shot
            # debugging (e.g. validate the rest of the pipeline on a slow pair).
            _bypass_vol = os.getenv("AMD_BYPASS_VOLATILITY", "").lower() in (
                "1", "true", "yes"
            )
            logger.info(
                "[AMD_FOREX][VOL] run_id=%s user=%s symbol=%s "
                "atr=%.6f atr_pts=%.1f threshold=%.4f threshold_pts=%.1f "
                "pass=%s bypass=%s",
                run_id, user_id, symbol,
                atr, atr / _PIP,
                self.config.MIN_ATR_THRESHOLD,
                self.config.MIN_ATR_THRESHOLD / _PIP,
                vol_ok, _bypass_vol,
            )
            if not vol_ok and not _bypass_vol:
                return None

            # ── Accumulation scan ────────────────────────────────────────────
            accum = self.detect_accumulation(candles)
            if accum:
                # Transition to ACCUMULATION
                self._save_state(user_id, symbol, AMDState.ACCUMULATION, {
                    'accumulation': accum,
                    'timestamp': candles[-1]['timestamp']
                })
                logger.info(
                    "[AMD_FOREX][ACCUM] run_id=%s user=%s symbol=%s "
                    "range_high=%.5f range_low=%.5f "
                    "range_price=%.5f range_pts=%.1f multiplier=0.0001 threshold_pts=%d "
                    "window_candles=%d quality=%.1f state=IDLE->ACCUMULATION",
                    run_id, user_id, symbol,
                    accum['high'], accum['low'],
                    accum['range'], accum['range'] / _PIP,
                    self.config.ACCUM_MAX_RANGE_POINTS,
                    accum['end_idx'] - accum['start_idx'] + 1, accum['quality_score'],
                )
            else:
                self._log_accumulation_miss(candles, atr, run_id, user_id, symbol)

            return None
        
        # State 1: ACCUMULATION
        if current_state == AMDState.ACCUMULATION:
            accum_data = state_data.get('data', {}).get('accumulation')

            logger.debug(
                "[AMD_FOREX][STATE] run_id=%s user=%s symbol=%s state=ACCUMULATION",
                run_id, user_id, symbol,
            )

            # Look for sweep
            sweep = self.detect_sweep(candles, accum_data['high'], accum_data['low'])
            if sweep:
                # Transition to SWEEP_DETECTED
                # sweep_candle_idx is embedded inside the sweep dict so it
                # survives the DB serialisation round-trip via sweep_data JSON.
                self._save_state(user_id, symbol, AMDState.SWEEP_DETECTED, {
                    'accumulation': accum_data,
                    'sweep': {**sweep, 'sweep_candle_idx': len(candles) - 1},
                })
                logger.info(
                    "[AMD_FOREX][SWEEP] run_id=%s user=%s symbol=%s "
                    "direction=%s level_type=%s level_taken=%.5f "
                    "wick_pct=%.1f strength=%.1f state=ACCUMULATION->SWEEP_DETECTED",
                    run_id, user_id, symbol,
                    sweep['direction'],
                    'accum_low' if sweep['direction'] == 'bullish' else 'accum_high',
                    sweep['level'], sweep['wick_pct'], sweep['strength'],
                )

            # Reset if accumulation invalidated (strong breakout)
            if self._is_accumulation_broken(candles, accum_data):
                self._reset_state(user_id, symbol)
                logger.info(
                    "[AMD_FOREX][RESET] run_id=%s user=%s symbol=%s "
                    "reason=accumulation_broken",
                    run_id, user_id, symbol,
                )

            return None
        
        # State 2: SWEEP_DETECTED
        if current_state == AMDState.SWEEP_DETECTED:
            sweep_data = state_data.get('data', {}).get('sweep') or {}
            sweep_idx = sweep_data.get('sweep_candle_idx')

            # Check timeout
            candles_since_sweep = len(candles) - 1 - sweep_idx

            logger.debug(
                "[AMD_FOREX][STATE] run_id=%s user=%s symbol=%s state=SWEEP_DETECTED "
                "candles_since_sweep=%d max=%d",
                run_id, user_id, symbol,
                candles_since_sweep, self.config.MAX_SWEEP_TO_DISPLACEMENT_CANDLES,
            )

            if candles_since_sweep > self.config.MAX_SWEEP_TO_DISPLACEMENT_CANDLES:
                self._reset_state(user_id, symbol)
                logger.info(
                    "[AMD_FOREX][RESET] run_id=%s user=%s symbol=%s "
                    "reason=displacement_timeout candles_waited=%d",
                    run_id, user_id, symbol, candles_since_sweep,
                )
                return None

            # Look for displacement
            displacement = self.detect_displacement(candles, sweep_data['direction'])
            if displacement:
                # Transition to DISPLACEMENT_CONFIRMED
                full_data = state_data.get('data', {})
                full_data['displacement'] = displacement
                self._save_state(user_id, symbol, AMDState.DISPLACEMENT_CONFIRMED, full_data)
                logger.info(
                    "[AMD_FOREX][DISP] run_id=%s user=%s symbol=%s "
                    "body_size=%.5f vs_avg_body=%.2f vs_atr=%.2f quality=%.1f "
                    "passes_body=%s passes_atr=%s state=SWEEP->DISPLACEMENT_CONFIRMED",
                    run_id, user_id, symbol,
                    displacement['body_size'], displacement['vs_avg_body'],
                    displacement['vs_atr'], displacement['quality'],
                    displacement['vs_avg_body'] >= self.config.DISPLACEMENT_BODY_MULTIPLIER,
                    displacement['vs_atr'] >= self.config.DISPLACEMENT_ATR_MULTIPLIER,
                )

            return None
        
        # State 3: DISPLACEMENT_CONFIRMED
        if current_state == AMDState.DISPLACEMENT_CONFIRMED:
            displacement_data = state_data.get('data', {}).get('displacement')
            displacement_idx = displacement_data['candle_idx']
            direction = state_data.get('data', {}).get('sweep', {}).get('direction')

            # Check timeout
            candles_since_displacement = len(candles) - 1 - displacement_idx

            logger.debug(
                "[AMD_FOREX][STATE] run_id=%s user=%s symbol=%s "
                "state=DISPLACEMENT_CONFIRMED candles_since_displacement=%d max=%d",
                run_id, user_id, symbol,
                candles_since_displacement, self.config.MAX_DISPLACEMENT_TO_IFVG_CANDLES,
            )

            if candles_since_displacement > self.config.MAX_DISPLACEMENT_TO_IFVG_CANDLES:
                self._reset_state(user_id, symbol)
                logger.info(
                    "[AMD_FOREX][RESET] run_id=%s user=%s symbol=%s "
                    "reason=ifvg_timeout candles_waited=%d",
                    run_id, user_id, symbol, candles_since_displacement,
                )
                return None

            # Look for IFVG
            ifvg = self.detect_ifvg(candles, displacement_idx, direction)
            if ifvg:
                logger.info(
                    "[AMD_FOREX][IFVG] run_id=%s user=%s symbol=%s "
                    "gap_high=%.5f gap_low=%.5f gap_size=%.5f retest_idx=%s "
                    "inversion_confirmed=True",
                    run_id, user_id, symbol,
                    ifvg['gap_high'], ifvg['gap_low'], ifvg['gap_size'], ifvg['retest_idx'],
                )

                # Complete setup! Generate alert
                full_data = state_data.get('data', {})
                full_data['ifvg'] = ifvg

                alert = self._generate_alert(user_id, symbol, full_data, candles)

                # Reset state after alert
                self._reset_state(user_id, symbol)

                logger.info(
                    "[AMD_FOREX][TRIGGER] run_id=%s user=%s symbol=%s "
                    "direction=%s quality=%s history_written=True email_queued=True",
                    run_id, user_id, symbol,
                    alert.get('direction'), alert.get('quality_score'),
                )
                return alert

            return None
        
        return None
    
    # ========================================
    # HELPER METHODS
    # ========================================
    
    def _calculate_atr(self, candles: List[Dict]) -> float:
        """Calculate Average True Range"""
        if not candles:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(candles)):
            high = candles[i]['high']
            low = candles[i]['low']
            prev_close = candles[i-1]['close']
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0
    
    def _pips(self, value: float) -> float:
        """Convert pips to price for forex (assumes 5-decimal pairs)"""
        return value * 0.0001
    
    def _score_accumulation(self, window: List[Dict], atr: float, 
                           range_pips: float, directional_pct: float) -> float:
        """Score accumulation quality (0-10)"""
        score = 10.0
        
        # Penalize wide range
        range_ratio = range_pips / atr if atr > 0 else 1
        if range_ratio > 0.3:
            score -= 3
        
        # Penalize directional bias
        if directional_pct > 0.2:
            score -= 2
        
        # Reward duration
        if len(window) >= 10:
            score += 1
        
        return max(0, min(10, score))
    
    def _score_sweep(self, wick_pct: float, sweep_distance: float) -> float:
        """Score sweep strength (0-10)"""
        score = 5.0
        
        # Reward strong wick
        if wick_pct > 60:
            score += 3
        elif wick_pct > 50:
            score += 2
        
        # Reward distance
        if sweep_distance > self._pips(10):
            score += 2
        elif sweep_distance > self._pips(7):
            score += 1
        
        return min(10, score)
    
    def _score_displacement(self, body_ratio: float, atr_ratio: float, 
                           candle: Dict) -> float:
        """Score displacement quality (0-10)"""
        score = 5.0
        
        # Reward strong body
        if body_ratio > 2.0:
            score += 3
        elif body_ratio > 1.7:
            score += 2
        
        # Reward strong range
        if atr_ratio > 2.0:
            score += 2
        
        return min(10, score)
    
    def _find_retest(self, candles: List[Dict], start_idx: int, end_idx: int,
                    gap_low: float, gap_high: float, direction: str) -> Optional[int]:
        """Find if price retests the FVG"""
        for i in range(start_idx, end_idx):
            if direction == 'bullish':
                if candles[i]['low'] <= gap_high:
                    return i
            else:
                if candles[i]['high'] >= gap_low:
                    return i
        return None
    
    def _log_accumulation_miss(self, candles: List[Dict], atr: float,
                               run_id: str, user_id: int, symbol: str) -> None:
        """
        Emit ONE INFO log line explaining why detect_accumulation() returned None.

        Uses the same fixed 8-candle window and 5200-point threshold as
        detect_accumulation() so the log is always directly comparable.

        Log format:
          [AMD_FOREX][NO_ACCUM] … range_price=X.XXXXX range_pts=XXXX
            multiplier=0.0001 threshold_pts=5200 window_n=8 reject=REASON <extra>
        """
        _POINT = 0.0001
        window_size   = self.config.ACCUM_FIXED_WINDOW
        threshold_pts = self.config.ACCUM_MAX_RANGE_POINTS

        if len(candles) < window_size:
            logger.info(
                "[AMD_FOREX][NO_ACCUM] run_id=%s user=%s symbol=%s "
                "reject=insufficient_candles have=%d need=%d",
                run_id, user_id, symbol, len(candles), window_size,
            )
            return

        window      = candles[-window_size:]
        high        = max(c['high'] for c in window)
        low         = min(c['low']  for c in window)
        range_price = high - low
        range_pts   = range_price / _POINT

        # Determine rejection reason (same order as detect_accumulation)
        if range_pts > threshold_pts:
            reject = 'range_too_wide'
            extra  = ""
        else:
            net_movement    = window[-1]['close'] - window[0]['close']
            directional_pct = abs(net_movement) / range_price if range_price > 0 else 1.0

            if directional_pct > self.config.ACCUM_DIRECTIONAL_THRESHOLD:
                reject = 'too_directional'
                extra  = (f"directional_pct={round(directional_pct, 3)} "
                          f"max={self.config.ACCUM_DIRECTIONAL_THRESHOLD}")
            else:
                touches_high = sum(
                    1 for c in window if abs(c['high'] - high) < range_price * 0.1
                )
                touches_low = sum(
                    1 for c in window if abs(c['low']  - low)  < range_price * 0.1
                )
                if touches_high < 2 or touches_low < 2:
                    reject = 'insufficient_touches'
                    extra  = (f"touches_h={touches_high} "
                              f"touches_l={touches_low} need=2each")
                else:
                    quality = self._score_accumulation(
                        window, atr, range_price, directional_pct
                    )
                    reject = 'quality_too_low'
                    extra  = f"quality={quality} min_quality={self.config.MIN_QUALITY_SCORE}"

        logger.info(
            "[AMD_FOREX][NO_ACCUM] run_id=%s user=%s symbol=%s "
            "range_price=%.5f range_pts=%.1f multiplier=0.0001 threshold_pts=%d "
            "window_n=%d reject=%s %s",
            run_id, user_id, symbol,
            range_price, range_pts, threshold_pts,
            window_size, reject, extra,
        )

    def _is_accumulation_broken(self, candles: List[Dict], accum_data: Dict) -> bool:
        """Check if accumulation is invalidated"""
        last_candle = candles[-1]
        
        # Strong breakout above/below range
        if last_candle['close'] > accum_data['high'] * 1.01:
            return True
        if last_candle['close'] < accum_data['low'] * 0.99:
            return True
        
        return False
    
    def _load_state(self, user_id: int, symbol: str) -> Dict:
        """Load state from database"""
        result = db.execute("""
            SELECT current_state, accumulation_data, sweep_data, displacement_data
            FROM forex_amd_state
            WHERE user_id = %s AND symbol = %s
        """, (user_id, symbol), fetchone=True)
        
        if not result:
            return {'current_state': AMDState.IDLE}
        
        return {
            'current_state': result['current_state'],
            'data': {
                'accumulation': json.loads(result['accumulation_data'] or '{}'),
                'sweep': json.loads(result['sweep_data'] or '{}'),
                'displacement': json.loads(result['displacement_data'] or '{}')
            }
        }
    
    def _save_state(self, user_id: int, symbol: str, state: int, data: Dict):
        """Save state to database"""
        db.execute("""
            INSERT INTO forex_amd_state (user_id, symbol, current_state, 
                                        accumulation_data, sweep_data, displacement_data)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, symbol) 
            DO UPDATE SET 
                current_state = EXCLUDED.current_state,
                accumulation_data = EXCLUDED.accumulation_data,
                sweep_data = EXCLUDED.sweep_data,
                displacement_data = EXCLUDED.displacement_data,
                last_update = NOW()
        """, (
            user_id, symbol, state,
            json.dumps(data.get('accumulation', {})),
            json.dumps(data.get('sweep', {})),
            json.dumps(data.get('displacement', {}))
        ))
    
    def _reset_state(self, user_id: int, symbol: str):
        """Reset state to IDLE"""
        db.execute("""
            UPDATE forex_amd_state 
            SET current_state = %s, 
                accumulation_data = NULL,
                sweep_data = NULL,
                displacement_data = NULL
            WHERE user_id = %s AND symbol = %s
        """, (AMDState.IDLE, user_id, symbol))
    
    def _generate_alert(self, user_id: int, symbol: str, 
                       setup_data: Dict, candles: List[Dict]) -> Dict:
        """Generate final alert with all components"""
        
        accum = setup_data['accumulation']
        sweep = setup_data['sweep']
        displacement = setup_data['displacement']
        ifvg = setup_data['ifvg']
        
        # Calculate quality score
        quality_score = (
            accum['quality_score'] * 0.2 +
            sweep['strength'] * 0.3 +
            displacement['quality'] * 0.3 +
            8.0 * 0.2  # IFVG presence
        )
        
        atr = self._calculate_atr(candles[-self.config.ATR_PERIOD:])
        
        # Get session
        session = self.is_active_session(candles[-1]['timestamp'])
        
        # Store in database
        db.execute("""
            INSERT INTO forex_amd_alerts (
                user_id, symbol, direction, session,
                accumulation_start, accumulation_end, accumulation_range,
                sweep_time, sweep_level, sweep_strength,
                displacement_time, displacement_candle_body, displacement_vs_avg,
                ifvg_time, ifvg_high, ifvg_low,
                atr_at_setup, volatility_score, setup_quality
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s
            )
        """, (
            user_id, symbol, sweep['direction'], session,
            candles[accum['start_idx']]['timestamp'],
            candles[accum['end_idx']]['timestamp'],
            accum['range'],
            candles[-1]['timestamp'],  # sweep time
            sweep['level'],
            sweep['strength'],
            candles[displacement['candle_idx']]['timestamp'],
            displacement['body_size'],
            displacement['vs_avg_body'],
            candles[ifvg['candle_idx']]['timestamp'],
            ifvg['gap_high'],
            ifvg['gap_low'],
            atr,
            quality_score,
            int(quality_score)
        ))
        
        return {
            'symbol': symbol,
            'direction': sweep['direction'],
            'session': session,
            'sweep_level': sweep['level'],
            'displacement_time': candles[displacement['candle_idx']]['timestamp'],
            'ifvg_range': f"{ifvg['gap_low']:.5f} - {ifvg['gap_high']:.5f}",
            'quality_score': int(quality_score)
        }

    # ========================================
    # DRY-RUN / DEBUG MODE
    # ========================================

    def debug_run(self, user_id: int, symbol: str) -> Dict:
        """
        Run the AMD state machine in read-only dry-run mode.

        Fetches fresh candles from Twelve Data and evaluates every detection
        step (volatility, accumulation, sweep, displacement, IFVG) without
        writing anything to the database.

        Returns a structured JSON-serialisable report::

            {
                "symbol": "EUR/USD",
                "user_id": 42,
                "run_at": "2024-06-10T09:00:00",
                "candles_fetched": 100,
                "current_state": 0,
                "current_state_name": "IDLE",
                "metrics": {
                    "atr": 0.00480,
                    "atr_pips": 48.0,
                    "volatility_ok": true
                },
                "decisions": [
                    {"check": "volatility", "result": "PASS", "details": {...}},
                    {"check": "accumulation", "result": "FOUND", "details": {...}},
                    ...
                ],
                "would_advance_to": "ACCUMULATION",   # or null
                "error": null
            }
        """
        from services.forex_data_provider import forex_data_provider

        _STATE_NAMES = {
            AMDState.IDLE: "IDLE",
            AMDState.ACCUMULATION: "ACCUMULATION",
            AMDState.SWEEP_DETECTED: "SWEEP_DETECTED",
            AMDState.DISPLACEMENT_CONFIRMED: "DISPLACEMENT_CONFIRMED",
            AMDState.WAIT_IFVG: "WAIT_IFVG",
        }

        report: Dict = {
            "symbol": symbol,
            "user_id": user_id,
            "run_at": datetime.utcnow().isoformat(),
            "candles_fetched": 0,
            "current_state": None,
            "current_state_name": None,
            "metrics": {},
            "decisions": [],
            "would_advance_to": None,
            "error": None,
        }

        # -- fetch candles -------------------------------------------------
        candles = forex_data_provider.get_recent_candles(symbol, "15m", 100)
        report["candles_fetched"] = len(candles)

        if not candles:
            report["error"] = "No candles available from Twelve Data"
            return report

        # -- load current DB state (read-only) -----------------------------
        state_data = self._load_state(user_id, symbol)
        current_state = state_data.get("current_state", AMDState.IDLE)
        report["current_state"] = current_state
        report["current_state_name"] = _STATE_NAMES.get(current_state, str(current_state))

        # -- compute shared metrics ----------------------------------------
        atr = self._calculate_atr(candles[-self.config.ATR_PERIOD:])
        volatility_ok = atr >= self.config.MIN_ATR_THRESHOLD
        report["metrics"] = {
            "atr": round(atr, 6),
            "atr_pips": round(atr / 0.0001, 1),
            "volatility_ok": volatility_ok,
            "last_close": candles[-1]["close"],
            "last_ts": candles[-1]["timestamp"].isoformat(),
        }

        # -- state-specific analysis (no DB writes) ------------------------
        if current_state == AMDState.IDLE:
            report["decisions"].append({
                "check": "volatility",
                "result": "PASS" if volatility_ok else "FAIL",
                "details": {
                    "atr": round(atr, 6),
                    "threshold": self.config.MIN_ATR_THRESHOLD,
                },
            })
            if not volatility_ok:
                return report

            accum = self.detect_accumulation(candles)
            if accum:
                report["decisions"].append({
                    "check": "accumulation",
                    "result": "FOUND",
                    "details": {
                        "range_pts": round(accum["range"], 6),
                        "range_pips": round(accum["range"] / 0.0001, 1),
                        "high": round(accum["high"], 6),
                        "low": round(accum["low"], 6),
                        "quality_score": accum["quality_score"],
                        "window_candles": accum["end_idx"] - accum["start_idx"] + 1,
                        "atr_ratio": round(accum["range"] / atr, 3) if atr else None,
                    },
                })
                report["would_advance_to"] = "ACCUMULATION"
            else:
                report["decisions"].append({
                    "check": "accumulation",
                    "result": "NOT_FOUND",
                    "details": {
                        "reason": (
                            f"Last {self.config.ACCUM_FIXED_WINDOW} candles did not pass: "
                            f"range_pts <= {self.config.ACCUM_MAX_RANGE_POINTS} pts "
                            f"(1 pt = 0.0001 price units), "
                            f"directional bias < {self.config.ACCUM_DIRECTIONAL_THRESHOLD*100:.0f}%, "
                            "and 2+ boundary touches each side"
                        ),
                    },
                })

        elif current_state == AMDState.ACCUMULATION:
            accum_data = state_data.get("data", {}).get("accumulation", {})
            report["metrics"]["saved_accum_high"] = accum_data.get("high")
            report["metrics"]["saved_accum_low"] = accum_data.get("low")

            if not accum_data:
                report["error"] = "State is ACCUMULATION but saved accumulation data is missing"
                return report

            broken = self._is_accumulation_broken(candles, accum_data)
            report["decisions"].append({
                "check": "accumulation_still_valid",
                "result": "FAIL" if broken else "PASS",
                "details": {
                    "last_close": candles[-1]["close"],
                    "accum_high": accum_data.get("high"),
                    "accum_low": accum_data.get("low"),
                },
            })
            if broken:
                report["would_advance_to"] = "RESET (accumulation broken)"
                return report

            sweep = self.detect_sweep(candles, accum_data["high"], accum_data["low"])
            if sweep:
                report["decisions"].append({
                    "check": "sweep",
                    "result": "FOUND",
                    "details": {
                        "direction": sweep["direction"],
                        "level": round(sweep["level"], 6),
                        "wick_pct": round(sweep["wick_pct"], 1),
                        "strength": round(sweep["strength"], 1),
                        "min_wick_threshold_pct": self.config.MIN_WICK_PERCENTAGE,
                    },
                })
                report["would_advance_to"] = "SWEEP_DETECTED"
            else:
                last = candles[-1]
                report["decisions"].append({
                    "check": "sweep",
                    "result": "NOT_FOUND",
                    "details": {
                        "last_high": last["high"],
                        "last_low": last["low"],
                        "last_close": last["close"],
                        "accum_high": accum_data.get("high"),
                        "accum_low": accum_data.get("low"),
                        "reason": "Last candle did not break accum range with wick >= 40%",
                    },
                })

        elif current_state == AMDState.SWEEP_DETECTED:
            saved = state_data.get("data", {})
            sweep_data = saved.get("sweep", {})
            sweep_idx = saved.get("sweep_candle_idx", 0)
            candles_since_sweep = len(candles) - 1 - sweep_idx

            report["metrics"]["candles_since_sweep"] = candles_since_sweep
            report["metrics"]["sweep_timeout"] = self.config.MAX_SWEEP_TO_DISPLACEMENT_CANDLES

            if candles_since_sweep > self.config.MAX_SWEEP_TO_DISPLACEMENT_CANDLES:
                report["decisions"].append({
                    "check": "sweep_timeout",
                    "result": "TIMED_OUT",
                    "details": {
                        "candles_since_sweep": candles_since_sweep,
                        "max_allowed": self.config.MAX_SWEEP_TO_DISPLACEMENT_CANDLES,
                    },
                })
                report["would_advance_to"] = "RESET (displacement timeout)"
                return report

            disp = self.detect_displacement(candles, sweep_data.get("direction", "bullish"))
            if disp:
                avg_body = sum(
                    abs(c["close"] - c["open"])
                    for c in candles[-(self.config.BODY_LOOKBACK + 1):-1]
                ) / self.config.BODY_LOOKBACK
                report["decisions"].append({
                    "check": "displacement",
                    "result": "FOUND",
                    "details": {
                        "body_size": round(disp["body_size"], 6),
                        "body_pips": round(disp["body_size"] / 0.0001, 1),
                        "vs_avg_body": round(disp["vs_avg_body"], 2),
                        "vs_atr": round(disp["vs_atr"], 2),
                        "quality": round(disp["quality"], 1),
                        "avg_body_reference": round(avg_body, 6),
                        "threshold_body": self.config.DISPLACEMENT_BODY_MULTIPLIER,
                        "threshold_atr": self.config.DISPLACEMENT_ATR_MULTIPLIER,
                    },
                })
                report["would_advance_to"] = "DISPLACEMENT_CONFIRMED"
            else:
                last = candles[-1]
                body = abs(last["close"] - last["open"])
                avg_body = sum(
                    abs(c["close"] - c["open"])
                    for c in candles[-(self.config.BODY_LOOKBACK + 1):-1]
                ) / self.config.BODY_LOOKBACK
                report["decisions"].append({
                    "check": "displacement",
                    "result": "NOT_FOUND",
                    "details": {
                        "last_body_pips": round(body / 0.0001, 1),
                        "avg_body_pips": round(avg_body / 0.0001, 1),
                        "body_ratio": round(body / avg_body, 2) if avg_body else None,
                        "need_body_ratio_gte": self.config.DISPLACEMENT_BODY_MULTIPLIER,
                        "need_atr_ratio_gte": self.config.DISPLACEMENT_ATR_MULTIPLIER,
                        "sweep_direction": sweep_data.get("direction"),
                    },
                })

        elif current_state == AMDState.DISPLACEMENT_CONFIRMED:
            saved = state_data.get("data", {})
            disp_data = saved.get("displacement", {})
            sweep_data = saved.get("sweep", {})
            displacement_idx = disp_data.get("candle_idx", 0)
            candles_since_disp = len(candles) - 1 - displacement_idx

            report["metrics"]["candles_since_displacement"] = candles_since_disp
            report["metrics"]["ifvg_timeout"] = self.config.MAX_DISPLACEMENT_TO_IFVG_CANDLES

            if candles_since_disp > self.config.MAX_DISPLACEMENT_TO_IFVG_CANDLES:
                report["decisions"].append({
                    "check": "ifvg_timeout",
                    "result": "TIMED_OUT",
                    "details": {
                        "candles_since_displacement": candles_since_disp,
                        "max_allowed": self.config.MAX_DISPLACEMENT_TO_IFVG_CANDLES,
                    },
                })
                report["would_advance_to"] = "RESET (IFVG timeout)"
                return report

            direction = sweep_data.get("direction", "bullish")
            ifvg = self.detect_ifvg(candles, displacement_idx, direction)
            if ifvg:
                # Compute quality score preview
                accum_data = saved.get("accumulation", {})
                quality_score = (
                    accum_data.get("quality_score", 0) * 0.2
                    + sweep_data.get("strength", 0) * 0.3
                    + disp_data.get("quality", 0) * 0.3
                    + 8.0 * 0.2
                )
                report["decisions"].append({
                    "check": "ifvg",
                    "result": "FOUND",
                    "details": {
                        "gap_high": round(ifvg["gap_high"], 6),
                        "gap_low": round(ifvg["gap_low"], 6),
                        "gap_size_pips": round(ifvg["gap_size"] / 0.0001, 1),
                        "retest_idx": ifvg["retest_idx"],
                        "min_gap_pips": self.config.IFVG_MIN_GAP_PIPS,
                    },
                })
                report["would_advance_to"] = "ALERT_FIRED"
                report["alert_preview"] = {
                    "direction": direction,
                    "ifvg_range": f"{ifvg['gap_low']:.5f} - {ifvg['gap_high']:.5f}",
                    "estimated_quality": round(quality_score, 1),
                }
            else:
                report["decisions"].append({
                    "check": "ifvg",
                    "result": "NOT_FOUND",
                    "details": {
                        "search_start_idx": displacement_idx + 1,
                        "search_end_idx": min(
                            len(candles),
                            displacement_idx + self.config.MAX_DISPLACEMENT_TO_IFVG_CANDLES,
                        ),
                        "direction": direction,
                        "min_gap_pips": self.config.IFVG_MIN_GAP_PIPS,
                        "retest_window": self.config.IFVG_RETEST_WINDOW_CANDLES,
                    },
                })

        return report


# Global instance
forex_amd_detector = ForexAMDDetector()
