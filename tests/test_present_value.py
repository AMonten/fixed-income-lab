import math
from datetime import date

import pytest

from fixed_income.conventions.day_count import Actual365Fixed
from fixed_income.instruments.bond import Bond
from fixed_income.pricing.curves import Interpolation, YieldCurve, present_value_from_curve
from fixed_income.pricing.present_value import (
    present_value,
    present_value_from_yield,
    price_per_100,
)
from fixed_income.pricing.yield_convention import CompoundingConvention, YieldConvention


def test_periodic_discount_factor_matches_formula():
    yc = YieldConvention(CompoundingConvention.PERIODIC, periods_per_year=2)
    assert yc.discount_factor(0.05, 1.0) == pytest.approx((1 + 0.05 / 2) ** -2)


def test_annual_discount_factor_matches_formula():
    yc = YieldConvention(CompoundingConvention.ANNUAL)
    assert yc.discount_factor(0.05, 2.0) == pytest.approx(1.05**-2)


def test_continuous_discount_factor_matches_formula():
    yc = YieldConvention(CompoundingConvention.CONTINUOUS)
    assert yc.discount_factor(0.05, 3.0) == pytest.approx(math.exp(-0.05 * 3))


def test_price_per_100_rescales_by_face_value():
    assert price_per_100(50.0, 1000.0) == pytest.approx(5.0)
    assert price_per_100(100.0, 100.0) == pytest.approx(100.0)


def test_present_value_from_true_yield_matches_manual_discounting_to_payment_date():
    bond = Bond(100.0, 0.05, date(2020, 1, 15), date(2022, 1, 15), day_count=Actual365Fixed())
    settlement = bond.issue_date
    cfs = bond.cash_flows_after(settlement)
    yc = YieldConvention.true_yield(bond.frequency)
    pv = present_value_from_yield(cfs, settlement, 0.05, yc, bond.day_count)

    manual = sum(
        cf.total * yc.discount_factor(0.05, bond.day_count.year_fraction(settlement, cf.payment_date))
        for cf in cfs
    )
    assert pv == pytest.approx(manual)


def test_present_value_from_street_yield_matches_hand_derived_quasi_coupon_pricing():
    """Reference case: derivation.engine=manual (ICMA quasi-coupon pricing
    formula), tolerance=1e-9. A semi-annual bond settling exactly mid-way
    through its first coupon period, priced at a yield away from the coupon,
    should match ``P = sum(CF_k / (1 + y/m)^(w+k))`` computed independently
    of the library, with ``w`` the fraction of the current period remaining.
    """
    bond = Bond(100.0, 0.06, date(2020, 1, 15), date(2022, 1, 15), day_count=Actual365Fixed())
    settlement = date(2020, 4, 15)  # exactly halfway between the Jan 15 and Jul 15 coupon dates
    cfs = bond.cash_flows_after(settlement)
    yc = YieldConvention.street(bond.frequency)
    y = 0.08

    w = 0.5
    m = bond.frequency.periods_per_year
    expected = sum(cf.total / (1 + y / m) ** (w + k) for k, cf in enumerate(cfs))

    pv = present_value_from_yield(cfs, settlement, y, yc, bond.day_count)
    assert pv == pytest.approx(expected, rel=1e-9)


def test_present_value_with_zero_discount_factor_equals_sum_of_flows():
    bond = Bond(100.0, 0.05, date(2020, 1, 15), date(2022, 1, 15), day_count=Actual365Fixed())
    cfs = bond.cash_flows()
    pv = present_value(cfs, bond.issue_date, lambda t: 1.0, bond.day_count)
    assert pv == pytest.approx(sum(cf.total for cf in cfs))


def test_yield_curve_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        YieldCurve(tenors=(1.0, 2.0), zero_rates=(0.03,))


def test_yield_curve_rejects_empty():
    with pytest.raises(ValueError):
        YieldCurve(tenors=(), zero_rates=())


def test_yield_curve_linear_interpolation_midpoint():
    curve = YieldCurve(tenors=(1.0, 3.0), zero_rates=(0.02, 0.04))
    assert curve.zero_rate(2.0) == pytest.approx(0.03)


def test_yield_curve_flat_extrapolation_outside_range():
    curve = YieldCurve(tenors=(1.0, 3.0), zero_rates=(0.02, 0.04))
    assert curve.zero_rate(0.5) == pytest.approx(0.02)
    assert curve.zero_rate(10.0) == pytest.approx(0.04)


def test_yield_curve_exact_pillar_point():
    curve = YieldCurve(tenors=(1.0, 2.0, 5.0), zero_rates=(0.02, 0.025, 0.035))
    assert curve.zero_rate(2.0) == pytest.approx(0.025)


def test_yield_curve_log_linear_interpolation():
    curve = YieldCurve(tenors=(1.0, 3.0), zero_rates=(0.02, 0.04), interpolation=Interpolation.LOG_LINEAR)
    expected = math.exp(math.log(0.02) * 0.5 + math.log(0.04) * 0.5)
    assert curve.zero_rate(2.0) == pytest.approx(expected)


def test_yield_curve_flat_interpolation_holds_left_pillar():
    curve = YieldCurve(tenors=(1.0, 3.0), zero_rates=(0.02, 0.04), interpolation=Interpolation.FLAT)
    assert curve.zero_rate(2.9) == pytest.approx(0.02)


def test_yield_curve_log_linear_rejects_negative_bracketing_rate():
    curve = YieldCurve(
        tenors=(1.0, 5.0), zero_rates=(-0.001, 0.02), interpolation=Interpolation.LOG_LINEAR
    )
    with pytest.raises(ValueError, match="strictly positive"):
        curve.zero_rate(3.0)


def test_yield_curve_log_linear_rejects_zero_bracketing_rate():
    curve = YieldCurve(tenors=(1.0, 5.0), zero_rates=(0.0, 0.02), interpolation=Interpolation.LOG_LINEAR)
    with pytest.raises(ValueError, match="strictly positive"):
        curve.zero_rate(3.0)


def test_yield_curve_log_linear_allows_positive_rates_outside_bracket():
    # A negative/zero rate elsewhere on the curve is fine as long as it
    # doesn't bracket the queried tenor.
    curve = YieldCurve(
        tenors=(1.0, 3.0, 5.0), zero_rates=(-0.001, 0.02, 0.03), interpolation=Interpolation.LOG_LINEAR
    )
    expected = math.exp(math.log(0.02) * 0.5 + math.log(0.03) * 0.5)
    assert curve.zero_rate(4.0) == pytest.approx(expected)


def test_present_value_from_curve_uses_per_maturity_zero_rate():
    bond = Bond(100.0, 0.0, date(2020, 1, 15), date(2025, 1, 15), day_count=Actual365Fixed())
    settlement = bond.issue_date
    curve = YieldCurve(tenors=(1.0, 10.0), zero_rates=(0.05, 0.05), compounding=CompoundingConvention.ANNUAL)
    pv = present_value_from_curve(bond.cash_flows_after(settlement), settlement, curve, bond.day_count)
    # zero-coupon bond, flat 5% curve for 5 years -> pv ~= 100 / 1.05^5
    assert pv == pytest.approx(100 / 1.05**5, rel=1e-3)
