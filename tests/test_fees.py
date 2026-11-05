"""Kalshi taker fee: 0.07 * C * P * (1 - P), rounded up to the cent per order."""

import numpy as np
import pytest

from kvo.fees import fee_per_contract, taker_fee


def test_one_contract_at_50_cents_costs_2_cents():
    # 0.07 * 0.5 * 0.5 = 0.0175, rounded up to the next cent
    assert taker_fee(0.5) == pytest.approx(0.02)


def test_hundred_contracts_at_50_cents_cost_175():
    # 0.07 * 100 * 0.25 = 1.75 exactly: no rounding up from float noise
    assert taker_fee(0.5, 100) == pytest.approx(1.75)


def test_hand_worked_value():
    # 0.07 * 10 * 0.1 * 0.9 = 0.063 -> 0.07
    assert taker_fee(0.10, 10) == pytest.approx(0.07)


def test_unrounded_fee_is_the_formula():
    assert taker_fee(0.5, round_to_cent=False) == pytest.approx(0.0175)
    assert taker_fee(0.5, rate=0.035, round_to_cent=False) == pytest.approx(0.00875)


def test_fee_is_symmetric_and_peaks_at_50_cents():
    p = np.linspace(0.01, 0.99, 99)
    fee = taker_fee(p, round_to_cent=False)
    np.testing.assert_allclose(fee, fee[::-1])
    assert p[np.argmax(fee)] == pytest.approx(0.5)


def test_per_contract_fee_shrinks_with_size_because_of_rounding():
    assert fee_per_contract(0.5, 1) == pytest.approx(0.02)
    assert fee_per_contract(0.5, 100) == pytest.approx(0.0175)


@pytest.mark.parametrize("price", [0.0, 1.0, -0.1, 1.5])
def test_rejects_prices_outside_0_1(price):
    with pytest.raises(ValueError):
        taker_fee(price)
