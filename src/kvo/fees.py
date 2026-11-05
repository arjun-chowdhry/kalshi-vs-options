"""Kalshi trading fees.

The formula
-----------
Kalshi charges a fee when you trade, not when a contract settles. For a taker (someone who
trades against an order already resting in the book) the fee on ``C`` contracts at price ``P``
dollars is

    fee = rate * multiplier * C * P * (1 - P)

The ``P * (1 - P)`` part makes the fee largest at 50 cents (most uncertain) and close to zero
near 1 or 99 cents. At the general rate of 0.07, a 50-cent contract costs 1.75 cents in fees.

Where each number comes from (details and sources in docs/FEASIBILITY.md):
- ``rate = 0.07``: the general taker rate in Kalshi's published fee schedule. We could not open
  the PDF itself (it returned HTTP 429), so this comes from several secondary sources that quote
  it. Some older sources quote a halved rate (0.035) for S&P markets. We default to the higher
  0.07 so that any edge we find is not flattered by a fee assumption.
- ``multiplier = 1``: what Kalshi's public API reports for the KXINXU series
  (``fee_type: quadratic, fee_multiplier: 1``, effective 2026-07-03).

Rounding
--------
Kalshi's docs say the fee is computed to $0.000001, and then an account with cent precision is
charged in whole cents, with rounding leftovers rebated across the fills of one order. So over
one order the cost is the exact fee rounded *up* to the next cent. That is our default
(``round_to_cent=True``): one contract at 50 cents costs 2 cents, but 100 contracts cost $1.75,
not $2.00. Rounding up is also the conservative choice.

Why taker fees only: a paper trade that buys at the ask is a taker by definition. Resting as a
maker could be cheaper but might never fill, and we can't simulate fills honestly.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = ["TAKER_RATE", "fee_per_contract", "taker_fee"]

TAKER_RATE = 0.07


def taker_fee(
    price: ArrayLike,
    contracts: ArrayLike = 1,
    *,
    rate: float = TAKER_RATE,
    multiplier: float = 1.0,
    round_to_cent: bool = True,
) -> NDArray:
    """Total taker fee in dollars for buying ``contracts`` at ``price`` (dollars, 0 < P < 1)."""
    price = np.asarray(price, dtype=float)
    contracts = np.asarray(contracts, dtype=float)
    if np.any((price <= 0) | (price >= 1)):
        raise ValueError("price must be strictly between 0 and 1 dollar")
    if np.any(contracts <= 0):
        raise ValueError("contracts must be positive")
    fee = rate * multiplier * contracts * price * (1 - price)
    if round_to_cent:
        # The tiny tolerance stops float noise (1.7500000000000002) from adding a cent.
        fee = np.ceil(fee * 100 - 1e-9) / 100
    return fee[()]


def fee_per_contract(
    price: ArrayLike,
    contracts: ArrayLike = 1,
    **kwargs,
) -> NDArray:
    """``taker_fee`` divided by the number of contracts: the fee drag on each contract."""
    return (taker_fee(price, contracts, **kwargs) / np.asarray(contracts, dtype=float))[()]
