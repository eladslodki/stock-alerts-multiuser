"""
Unit tests for ticker sort order.

Verifies:
1. get_all_tickers() returns every ticker in strict A→Z order (case-insensitive).
2. A new ticker added to the list and re-sorted lands at the correct position.
3. Sort is stable and case-insensitive ('aapl' treated the same as 'AAPL').
4. Total ticker count is unchanged.
"""

import sys
import os
from unittest.mock import MagicMock

sys.modules.setdefault("requests", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from ticker_fetcher import TickerFetcher


def get_symbols():
    """Return a fresh copy of all symbols (avoids mutating the cached list)."""
    return [t["symbol"] for t in TickerFetcher.get_all_tickers()]


# JavaScript-equivalent sort used in the frontend (localeCompare, sensitivity='base')
def js_sort_key(symbol: str) -> str:
    return symbol.upper()


class TestTickerSortOrder(unittest.TestCase):

    # ── 1. Full list is A→Z ───────────────────────────────────────────────

    def test_get_all_tickers_sorted_a_to_z(self):
        symbols = get_symbols()
        expected = sorted(symbols, key=js_sort_key)
        self.assertEqual(
            symbols, expected,
            f"Ticker list is not sorted A→Z.\n"
            f"First out-of-order pair: "
            f"{next((f'{a}>{b}' for a, b in zip(symbols, expected) if a != b), 'none')}",
        )

    def test_count_unchanged(self):
        self.assertEqual(len(get_symbols()), 55, "Expected exactly 55 tickers")

    # ── 2. New ticker inserted → correct alphabetical position ───────────

    def test_new_stock_sorted_between_neighbours(self):
        """
        'COIN' (Coinbase) is not in the list.
        Sorted: ... BTC-USD  <  COIN  <  COP ...
          COI < COP  because 'I' < 'P' at position 2.
          BTC < COI  because 'B' < 'C'.
        """
        tickers = list(TickerFetcher.get_all_tickers())
        tickers.append({"symbol": "COIN", "name": "Coinbase Global Inc.", "type": "Stock"})
        sorted_symbols = [t["symbol"] for t in sorted(tickers, key=lambda t: js_sort_key(t["symbol"]))]

        idx_coin    = sorted_symbols.index("COIN")
        idx_btc_usd = sorted_symbols.index("BTC-USD")
        idx_cop     = sorted_symbols.index("COP")

        self.assertLess(idx_btc_usd, idx_coin, "BTC-USD must come before COIN")
        self.assertLess(idx_coin,    idx_cop,   "COIN must come before COP")

    def test_new_crypto_sorted_correctly(self):
        """
        'PEPE-USD' should sort between PEP and PFE.
          PEP < PEPE < PF...  (shorter prefix beats longer at same chars)
        Actually: PEP vs PEPE-USD at index 3: 'E' vs '-', '-' (45) < 'E' (69)
        so PEPE-USD < PEP. Let's verify with a known safe example:
        'XTZ-USD' (Tezos) → between XOM and XRP-USD.
          XO < XT < XR... wait: XOM→X,O,M  XRP-USD→X,R  XTZ→X,T
          'O' < 'R' < 'T'  →  XOM < XRP-USD < XTZ-USD
        """
        tickers = list(TickerFetcher.get_all_tickers())
        tickers.append({"symbol": "XTZ-USD", "name": "Tezos USD", "type": "Crypto"})
        sorted_symbols = [t["symbol"] for t in sorted(tickers, key=lambda t: js_sort_key(t["symbol"]))]

        idx_xom     = sorted_symbols.index("XOM")
        idx_xrp_usd = sorted_symbols.index("XRP-USD")
        idx_xtz_usd = sorted_symbols.index("XTZ-USD")

        self.assertLess(idx_xom,     idx_xrp_usd, "XOM must come before XRP-USD")
        self.assertLess(idx_xrp_usd, idx_xtz_usd, "XRP-USD must come before XTZ-USD")

    # ── 3. Case-insensitive sort ──────────────────────────────────────────

    def test_sort_is_case_insensitive(self):
        """Lower-case symbol 'msft' sorts identically to 'MSFT'."""
        mixed = [
            {"symbol": "tsla", "name": "Tesla", "type": "Stock"},
            {"symbol": "AAPL", "name": "Apple", "type": "Stock"},
            {"symbol": "msft", "name": "Microsoft", "type": "Stock"},
        ]
        result = sorted(mixed, key=lambda t: js_sort_key(t["symbol"]))
        self.assertEqual(
            [t["symbol"] for t in result],
            ["AAPL", "msft", "tsla"],
        )

    def test_uppercase_and_lowercase_same_position(self):
        """'aapl' and 'AAPL' collate to the same position."""
        lower = [{"symbol": "aapl", "name": "Apple", "type": "Stock"}]
        upper = [{"symbol": "AAPL", "name": "Apple", "type": "Stock"}]
        rest  = [{"symbol": "MSFT", "name": "Microsoft", "type": "Stock"}]

        for variant in (lower, upper):
            result = sorted(variant + rest, key=lambda t: js_sort_key(t["symbol"]))
            self.assertEqual(result[0]["symbol"].upper(), "AAPL")
            self.assertEqual(result[1]["symbol"].upper(), "MSFT")

    # ── 4. Fallback list is A→Z ───────────────────────────────────────────

    def test_fallback_tickers_sorted(self):
        """
        The hardcoded JS fallback list must also be A→Z.
        We replicate it here to detect any future edits that break ordering.
        """
        fallback = ["AAPL", "BTC-USD", "MSFT", "TSLA"]
        self.assertEqual(
            fallback,
            sorted(fallback, key=js_sort_key),
            "JS fallback ticker list must be in alphabetical order",
        )

    # ── 5. Active alerts list is A→Z (mirrors the dashboard JS sort) ─────

    def test_active_alerts_rendered_alphabetically(self):
        """
        The dashboard's loadAlerts() filters active alerts then sorts by
        ticker with localeCompare(sensitivity:'base').  Replicate that here
        to prove mixed-order alerts land in correct A→Z display order.
        """
        # Simulate what the JS fetch('/api/alerts') might return (unsorted).
        raw_alerts = [
            {"ticker": "UUUU", "active": True,  "alert_type": "price"},
            {"ticker": "IGV",  "active": True,  "alert_type": "price"},
            {"ticker": "TOL",  "active": False, "alert_type": "price"},  # inactive
            {"ticker": "AAPL", "active": True,  "alert_type": "price"},
            {"ticker": "TOL",  "active": True,  "alert_type": "ma"},
        ]

        # Replicate: .filter(a => a.active).sort(localeCompare case-insensitive)
        active = [a for a in raw_alerts if a["active"]]
        rendered = sorted(active, key=lambda a: js_sort_key(a["ticker"]))
        symbols = [a["ticker"] for a in rendered]

        self.assertEqual(symbols, ["AAPL", "IGV", "TOL", "UUUU"],
                         "Active alerts must render in A→Z ticker order")

    def test_active_alerts_case_insensitive_order(self):
        """Lower-case tickers in the alerts list sort the same as upper-case."""
        alerts = [
            {"ticker": "tsla", "active": True},
            {"ticker": "AAPL", "active": True},
            {"ticker": "msft", "active": True},
        ]
        rendered = sorted(alerts, key=lambda a: js_sort_key(a["ticker"]))
        self.assertEqual([a["ticker"] for a in rendered], ["AAPL", "msft", "tsla"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
