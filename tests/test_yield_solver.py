from datetime import date

import pytest

from fixed_income.conventions.day_count import Actual365Fixed
from fixed_income.conventions.frequency import Frequency
from fixed_income.instruments.bond import Bond, ZeroCouponBond
from fixed_income.pricing.yield_convention import YieldConvention
from fixed_income.pricing.yield_solver import (
    YieldSolverError,
    price_from_yield,
    solve_yield_to_maturity,
)


@pytest.fixture
def bond():
    return Bond(100.0, 0.05, date(2020, 1, 15), date(2030, 1, 15), Frequency.SEMI_ANNUAL, Actual365Fixed())


def _cfs_and_yc(bond, settlement):
    return bond.cash_flows_after(settlement), YieldConvention.street(bond.frequency)


@pytest.mark.parametrize("target_yield", [0.01, 0.03, 0.05, 0.08, 0.15])
def test_yield_round_trip_recovers_original_yield(bond, target_yield):
    settlement = date(2024, 1, 16)
    cfs, yc = _cfs_and_yc(bond, settlement)
    price = price_from_yield(cfs, bond.face_value, settlement, target_yield, yc, bond.day_count)
    solved = solve_yield_to_maturity(cfs, bond.face_value, settlement, price, yc, bond.day_count)
    assert solved == pytest.approx(target_yield, abs=1e-8)


def test_par_bond_prices_near_100_when_yield_equals_coupon(bond):
    settlement = bond.issue_date
    cfs, yc = _cfs_and_yc(bond, settlement)
    price = price_from_yield(cfs, bond.face_value, settlement, bond.coupon_rate, yc, bond.day_count)
    assert price == pytest.approx(100.0, abs=0.05)


@pytest.mark.xfail(
    reason=(
        "present_value discounts to the business-day-adjusted payment_date instead of "
        "the yield convention's unadjusted coupon-period time; a coupon falling on a "
        "weekend (see the bond fixture) inflates the discount exponent and biases price "
        "away from par. Fixed by Bloque 1's Accrual/Yield/DiscountCurve split (issue #4)."
    ),
    strict=True,
)
def test_par_bond_prices_to_exactly_100(bond):
    settlement = bond.issue_date
    cfs, yc = _cfs_and_yc(bond, settlement)
    price = price_from_yield(cfs, bond.face_value, settlement, bond.coupon_rate, yc, bond.day_count)
    assert price == pytest.approx(100.0, abs=1e-9)


def test_higher_yield_implies_lower_price(bond):
    settlement = date(2024, 1, 16)
    cfs, yc = _cfs_and_yc(bond, settlement)
    low_yield_price = price_from_yield(cfs, bond.face_value, settlement, 0.03, yc, bond.day_count)
    high_yield_price = price_from_yield(cfs, bond.face_value, settlement, 0.07, yc, bond.day_count)
    assert high_yield_price < low_yield_price


def test_zero_coupon_bond_prices_below_par_for_positive_yield():
    zcb = ZeroCouponBond(100.0, 0.0, date(2020, 1, 15), date(2030, 1, 15))
    settlement = zcb.issue_date
    cfs, yc = zcb.cash_flows_after(settlement), YieldConvention.street(zcb.frequency)
    price = price_from_yield(cfs, zcb.face_value, settlement, 0.05, yc, zcb.day_count)
    assert 0 < price < 100.0


def test_solver_raises_on_empty_cash_flow_list(bond):
    yc = YieldConvention.street(bond.frequency)
    with pytest.raises(YieldSolverError):
        solve_yield_to_maturity([], bond.face_value, bond.issue_date, 100.0, yc, bond.day_count)


def test_solver_raises_when_target_price_unreachable_in_bracket(bond):
    settlement = date(2024, 1, 16)
    cfs, yc = _cfs_and_yc(bond, settlement)
    with pytest.raises(YieldSolverError):
        solve_yield_to_maturity(
            cfs, bond.face_value, settlement, target_dirty_price=1e9, yield_convention=yc,
            day_count=bond.day_count, bracket=(-0.5, 1.0),
        )
