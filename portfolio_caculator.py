import logging
from price_checker import price_checker

logger = logging.getLogger(__name__)

class PortfolioCalculator:
    """Professional trading calculations and risk management"""
    
    @staticmethod
    def calculate_risk_reward_ratio(buy_price, stop_loss, take_profit):
        """
        Calculate Risk/Reward ratio
        R:R = (Take Profit - Buy Price) / (Buy Price - Stop Loss)
        """
        if not all([buy_price, stop_loss, take_profit]):
            return None
        
        buy_price = float(buy_price)
        stop_loss = float(stop_loss)
        take_profit = float(take_profit)
        
        risk = buy_price - stop_loss
        reward = take_profit - buy_price
        
        if risk <= 0:
            return None
        
        rr_ratio = reward / risk
        return round(rr_ratio, 2)
    
    @staticmethod
    def calculate_risk_percentage(risk_amount, portfolio_cash):
        """
        Calculate what percentage of portfolio is at risk
        Risk % = (Risk Amount / Portfolio Cash) * 100
        """
        if not portfolio_cash or portfolio_cash <= 0:
            return 0
        
        risk_pct = (float(risk_amount) / float(portfolio_cash)) * 100
        return round(risk_pct, 2)
    
    @staticmethod
    def calculate_position_percentage(position_size, portfolio_cash):
        """
        Calculate what percentage of portfolio is in this position
        Position % = (Position Size / Portfolio Cash) * 100
        """
        if not portfolio_cash or portfolio_cash <= 0:
            return 0
        
        position_pct = (float(position_size) / float(portfolio_cash)) * 100
        return round(position_pct, 2)
    
    @staticmethod
    def is_high_risk(risk_pct, rr_ratio=None):
        """
        Determine if a trade has unhealthy risk characteristics
        High risk if:
        - Risk > 2% of portfolio
        - R:R ratio < 1.5
        """
        warnings = []
        
        if risk_pct > 2.0:
            warnings.append({
                'type': 'high_risk',
                'message': f'High risk: {risk_pct}% of portfolio (recommended < 2%)',
                'severity': 'error' if risk_pct > 5.0 else 'warning'
            })
        
        if rr_ratio is not None and rr_ratio < 1.5:
            warnings.append({
                'type': 'low_rr',
                'message': f'Low R:R ratio: {rr_ratio} (recommended > 1.5)',
                'severity': 'warning'
            })
        
        return warnings
    
    @staticmethod
    def calculate_unrealized_pnl(buy_price, current_price, quantity):
        """
        Calculate unrealized P&L for open positions
        Returns: {'pnl_dollar': float, 'pnl_percent': float}
        """
        if not current_price:
            return None
        
        buy_price = float(buy_price)
        current_price = float(current_price)
        quantity = float(quantity)
        
        pnl_dollar = (current_price - buy_price) * quantity
        pnl_percent = ((current_price - buy_price) / buy_price) * 100
        
        return {
            'pnl_dollar': round(pnl_dollar, 2),
            'pnl_percent': round(pnl_percent, 2)
        }
    
    @staticmethod
    def calculate_realized_pnl(buy_price, close_price, quantity):
        """
        Calculate realized P&L for closed positions
        Returns: {'pnl_dollar': float, 'pnl_percent': float}
        """
        buy_price = float(buy_price)
        close_price = float(close_price)
        quantity = float(quantity)
        
        pnl_dollar = (close_price - buy_price) * quantity
        pnl_percent = ((close_price - buy_price) / buy_price) * 100
        
        return {
            'pnl_dollar': round(pnl_dollar, 2),
            'pnl_percent': round(pnl_percent, 2)
        }
    
    @staticmethod
    def enrich_trade_with_calculations(trade, portfolio_cash, current_price=None):
        """
        Add all calculated fields to a trade dictionary
        """
        enriched = dict(trade)
        
        # Risk percentage
        enriched['risk_pct'] = PortfolioCalculator.calculate_risk_percentage(
            trade['risk_amount'], portfolio_cash
        )
        
        # Position percentage
        enriched['position_pct'] = PortfolioCalculator.calculate_position_percentage(
            trade['position_size'], portfolio_cash
        )
        
        # R:R ratio
        if trade.get('stop_loss') and trade.get('take_profit'):
            enriched['rr_ratio'] = PortfolioCalculator.calculate_risk_reward_ratio(
                trade['buy_price'], trade['stop_loss'], trade['take_profit']
            )
        else:
            enriched['rr_ratio'] = None
        
        # Risk warnings
        enriched['warnings'] = PortfolioCalculator.is_high_risk(
            enriched['risk_pct'], enriched['rr_ratio']
        )
        
        # P&L calculation
        if trade.get('is_closed') and trade.get('close_price'):
            # Realized P&L for closed trades
            pnl = PortfolioCalculator.calculate_realized_pnl(
                trade['buy_price'], trade['close_price'], trade['quantity']
            )
            enriched['realized_pnl'] = pnl['pnl_dollar']
            enriched['realized_pnl_pct'] = pnl['pnl_percent']
            enriched['unrealized_pnl'] = None
            enriched['unrealized_pnl_pct'] = None
        else:
            # Unrealized P&L for open trades
            if current_price:
                pnl = PortfolioCalculator.calculate_unrealized_pnl(
                    trade['buy_price'], current_price, trade['quantity']
                )
                enriched['unrealized_pnl'] = pnl['pnl_dollar']
                enriched['unrealized_pnl_pct'] = pnl['pnl_percent']
            else:
                enriched['unrealized_pnl'] = None
                enriched['unrealized_pnl_pct'] = None
            enriched['realized_pnl'] = None
            enriched['realized_pnl_pct'] = None
        
        return enriched
    
    @staticmethod
    def calculate_portfolio_summary(trades, portfolio_cash):
        """
        Calculate aggregate portfolio metrics
        """
        open_trades = [t for t in trades if not t.get('is_closed')]
        closed_trades = [t for t in trades if t.get('is_closed')]
        
        # Calculate totals for open positions
        total_invested = sum(float(t['position_size']) for t in open_trades)
        total_risk = sum(float(t['risk_amount']) for t in open_trades)
        
        # Fetch current prices and calculate unrealized P&L
        total_unrealized_pnl = 0
        for trade in open_trades:
            try:
                current_price = price_checker.get_price(trade['ticker'])
                if current_price:
                    pnl = PortfolioCalculator.calculate_unrealized_pnl(
                        trade['buy_price'], current_price, trade['quantity']
                    )
                    total_unrealized_pnl += pnl['pnl_dollar']
            except Exception as e:
                logger.error(f"Error calculating P&L for {trade['ticker']}: {e}")
        
        # Calculate realized P&L from closed trades
        total_realized_pnl = 0
        for trade in closed_trades:
            if trade.get('close_price'):
                pnl = PortfolioCalculator.calculate_realized_pnl(
                    trade['buy_price'], trade['close_price'], trade['quantity']
                )
                total_realized_pnl += pnl['pnl_dollar']
        
        # Overall portfolio return
        total_pnl = total_realized_pnl + total_unrealized_pnl
        portfolio_return_pct = (total_pnl / portfolio_cash * 100) if portfolio_cash > 0 else 0
        
        return {
            'total_invested': round(total_invested, 2),
            'total_risk': round(total_risk, 2),
            'unrealized_pnl': round(total_unrealized_pnl, 2),
            'realized_pnl': round(total_realized_pnl, 2),
            'total_pnl': round(total_pnl, 2),
            'portfolio_return_pct': round(portfolio_return_pct, 2),
            'open_positions': len(open_trades),
            'closed_positions': len(closed_trades)
        }

portfolio_calculator = PortfolioCalculator()
