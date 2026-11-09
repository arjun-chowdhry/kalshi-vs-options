"""Milestone 3: paper trades on saved snapshots, settled against the actual close.

Nothing here places an order. A "trade" is a row in a table: one contract, bought at Kalshi's
price at the options' quote clock, held to settlement.

Two rules, run on the same M2 comparison table (``kvo.compare.comparison_table``):

- **strict**: trade only where M2 says the gap is beyond the resolution limit
  (``status == "beyond limit"``: ``|options - Kalshi mid| > half spread + fee + 2 sigma``).
  Strikes without option quotes of their own are never assessed, so they never trade.
- **naive**: buy YES when the options probability beats Kalshi's ask by more than the fee, and
  buy NO when it is below Kalshi's bid by more than the fee. No uncertainty band. Every strike
  in the table can trade, gap strikes included; ``in_gap`` marks those so they can be split out.

Both rules can buy either side. Buying NO at Kalshi costs ``1 - yes_bid``.

Cost per contract: the price paid plus Kalshi's taker fee for one contract, rounded up to the
cent (``kvo.fees.taker_fee``, the default): 2 cents at 50 cents. That is what a one-contract
order actually pays. The strict rule's threshold uses M2's exact fee instead; the difference
is under a cent.

P&L per contract: ``payout - price - fee``, where the payout is $1 if the contract wins at the
settlement value and $0 otherwise. A trade on a day whose settlement isn't known is kept but
not settled (``pnl`` is NaN).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from kvo.compare import BEYOND, NO_QUOTES, OVER
from kvo.fees import taker_fee

__all__ = ["RULES", "settle", "summarise", "trades"]

RULES = ("strict", "naive")
TRADE_COLUMNS = [
    "rule",
    "snapshot",
    "day",
    "strike",
    "side",
    "price",
    "fee",
    "p_options",
    "edge",
    "status",
    "in_gap",
]


def _fee(price) -> np.ndarray:
    return np.asarray(taker_fee(np.clip(np.asarray(price, dtype=float), 0.01, 0.99)), dtype=float)


def trades(table: pd.DataFrame, snapshot: str, day: str) -> pd.DataFrame:
    """Every paper trade both rules make on one snapshot's M2 comparison table.

    ``edge`` is the expected profit per contract if the options probability were right:
    ``p - ask - fee`` for YES, ``(1 - p) - (1 - bid) - fee`` for NO.
    """
    if table.empty or "status" not in table:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    t = table.reset_index(drop=True)
    p, bid, ask = t["p_options"].to_numpy(), t["yes_bid"].to_numpy(), t["yes_ask"].to_numpy()
    fee_yes, fee_no = _fee(ask), _fee(1 - bid)
    edge_yes = p - ask - fee_yes
    edge_no = (1 - p) - (1 - bid) - fee_no
    in_gap = t["status"].isin([NO_QUOTES, BEYOND]).to_numpy()
    over = (t["status"] == OVER).to_numpy()
    diff = t["diff"].to_numpy()

    picks = {
        "strict": (over & (diff > 0), over & (diff < 0)),
        "naive": (edge_yes > 0, edge_no > 0),
    }
    rows = []
    for rule, (yes, no) in picks.items():
        for side, mask, price, fee, edge in (
            ("yes", yes, ask, fee_yes, edge_yes),
            ("no", no, 1 - bid, fee_no, edge_no),
        ):
            for i in np.flatnonzero(mask):
                rows.append(
                    {
                        "rule": rule,
                        "snapshot": snapshot,
                        "day": day,
                        "strike": float(t.at[i, "strike"]),
                        "side": side,
                        "price": float(price[i]),
                        "fee": float(fee[i]),
                        "p_options": float(p[i]),
                        "edge": float(edge[i]),
                        "status": t.at[i, "status"],
                        "in_gap": bool(in_gap[i]),
                    }
                )
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def settle(book: pd.DataFrame, closes: dict[str, float]) -> pd.DataFrame:
    """Add ``close``, ``won`` and ``pnl`` (dollars per contract). Days missing from ``closes``
    (or NaN there) stay unsettled: ``pnl`` NaN.

    A YES contract on strike K wins if the close is at or above K (Kalshi's rule: "above
    7744.9999"), a NO contract if it is below.
    """
    out = book.copy()
    out["close"] = out["day"].map(closes).astype(float)
    known = out["close"].notna()
    above = out["close"] >= out["strike"]
    won = np.where(out["side"] == "yes", above, ~above)
    out["won"] = pd.Series(won, index=out.index).where(known)
    out["pnl"] = (out["won"].astype(float) - out["price"] - out["fee"]).where(known)
    return out


def summarise(settled: pd.DataFrame) -> pd.DataFrame:
    """One row per rule (and per rule outside the gap for the naive rule).

    - ``n_trades`` / ``n_settled``: all trades, and those whose day has a known close.
    - ``pnl_total``, ``pnl_mean`` (dollars per contract) over settled trades.
    - ``se_iid``: standard error of the mean treating every settled trade as independent.
      Too small: trades on one day all settle on the same close, so they move together.
    - ``se_day``: standard error of the mean P&L per trade across days (each day's mean P&L
      is one observation). NaN with fewer than 2 settled days that have trades, which is the
      honest answer: a day with no trades has no mean P&L per trade.
    - ``edge_mean``: the average P&L the options probabilities expected.
    """
    groups = [(rule, settled[settled["rule"] == rule]) for rule in RULES]
    naive = settled[settled["rule"] == "naive"]
    groups.append(("naive, assessed strikes only", naive[~naive["in_gap"].astype(bool)]))
    rows = []
    for name, g in groups:
        s = g[g["pnl"].notna()]
        n = len(s)
        days = s.groupby("day")["pnl"].mean()
        rows.append(
            {
                "rule": name,
                "n_trades": len(g),
                "n_yes": int((g["side"] == "yes").sum()),
                "n_no": int((g["side"] == "no").sum()),
                "n_snapshots": g["snapshot"].nunique(),
                "n_settled": n,
                "settled_days": len(days),
                "wins": int(s["won"].astype(bool).sum()) if n else 0,
                "pnl_total": float(s["pnl"].sum()) if n else 0.0,
                "pnl_mean": float(s["pnl"].mean()) if n else float("nan"),
                "se_iid": float(s["pnl"].std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan"),
                "se_day": float(days.std(ddof=1) / np.sqrt(len(days)))
                if len(days) > 1
                else float("nan"),
                "edge_mean": float(s["edge"].mean()) if n else float("nan"),
            }
        )
    return pd.DataFrame(rows)
