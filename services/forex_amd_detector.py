"""
Institutional-grade Forex AMD detector with ICT-style logic
"""

import logging
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
    ACCUM_RANGE_THRESHOLD = 0.5  # Max 50% of recent ATR
    ACCUM_DIRECTIONAL_THRESHOLD = 0.3  # Max 30% directional bias
    
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

        symbols = [row['symbol'] for row in watchlist]
        result['symbols'] = len(symbols)

        for symbol in symbols:
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
        Detect quality accumulation phase
        
        Requirements:
        - Range compression (< 50% of ATR)
        - No strong directional bias
        - Multiple touches of boundaries
        - Duration: 5-20 candles
        
        Returns: {
            'start_idx': int,
            'end_idx': int,
            'high': float,
            'low': float,
            'range': float,
            'quality_score': float (0-10)
        }
        """
        if len(candles) < self.config.ACCUM_MIN_CANDLES:
            return None
        
        # Calculate ATR for context
        atr = self._calculate_atr(candles[-self.config.ATR_PERIOD:])
        
        # Scan for accumulation windows
        for window_size in range(self.config.ACCUM_MIN_CANDLES, 
                                 self.config.ACCUM_MAX_CANDLES + 1):
            
            window = candles[-window_size:]
            
            # 1. Range compression check
            high = max(c['high'] for c in window)
            low = min(c['low'] for c in window)
            range_pips = high - low
            
            if range_pips > (atr * self.config.ACCUM_RANGE_THRESHOLD):
                continue  # Too wide
            
            # 2. Directional bias check
            net_movement = window[-1]['close'] - window[0]['close']
            directional_pct = abs(net_movement) / range_pips if range_pips > 0 else 1
            
            if directional_pct > self.config.ACCUM_DIRECTIONAL_THRESHOLD:
                continue  # Too directional
            
            # 3. Boundary touches check
            touches_high = sum(1 for c in window if abs(c['high'] - high) < range_pips * 0.1)
            touches_low = sum(1 for c in window if abs(c['low'] - low) < range_pips * 0.1)
            
            if touches_high < 2 or touches_low < 2:
                continue  # Not enough consolidation
            
            # Calculate quality score
            quality = self._score_accumulation(window, atr, range_pips, directional_pct)
            
            if quality >= 6:  # Minimum quality threshold
                return {
                    'start_idx': len(candles) - window_size,
                    'end_idx': len(candles) - 1,
                    'high': high,
                    'low': low,
                    'range': range_pips,
                    'quality_score': quality
                }
        
        return None
    
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
            # Check volatility first
            if not self.check_volatility(candles):
                logger.debug(
                    "[AMD_FOREX][STATE] run_id=%s user=%s symbol=%s state=IDLE "
                    "skip=low_volatility",
                    run_id, user_id, symbol,
                )
                return None

            # Look for accumulation
            accum = self.detect_accumulation(candles)
            if accum:
                # Transition to ACCUMULATION
                self._save_state(user_id, symbol, AMDState.ACCUMULATION, {
                    'accumulation': accum,
                    'timestamp': candles[-1]['timestamp']
                })
                logger.info(
                    "[AMD_FOREX][ACCUM] run_id=%s user=%s symbol=%s "
                    "range_high=%.5f range_low=%.5f range_pts=%.5f "
                    "window_candles=%d quality=%.1f state=IDLE->ACCUMULATION",
                    run_id, user_id, symbol,
                    accum['high'], accum['low'], accum['range'],
                    accum['end_idx'] - accum['start_idx'] + 1, accum['quality_score'],
                )
            else:
                logger.debug(
                    "[AMD_FOREX][STATE] run_id=%s user=%s symbol=%s state=IDLE no_accum",
                    run_id, user_id, symbol,
                )

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
                self._save_state(user_id, symbol, AMDState.SWEEP_DETECTED, {
                    'accumulation': accum_data,
                    'sweep': sweep,
                    'sweep_candle_idx': len(candles) - 1
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
            sweep_data = state_data.get('data', {}).get('sweep')
            sweep_idx = state_data.get('data', {}).get('sweep_candle_idx')

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


# Global instance
forex_amd_detector = ForexAMDDetector()
