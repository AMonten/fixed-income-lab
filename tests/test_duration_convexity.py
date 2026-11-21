from datetime import date

import pytest

from fixed_income.conventions.day_count import Actual365Fixed
from fixed_income.conventions.frequency import Frequency
from fixed_income.instruments.bond import Bond, ZeroCouponBond
from fixed_income.pricing.yield_convention import CompoundingConvention, YieldConvention
from fixed_income.pricing.yield_solver import price_from_yield
from fixed_income.risk.convexity import convexity
from fixed_income.risk.duration import (
    dv01,
    macaulay_duration,
    modified_duration,
    modified_duration_from_macaulay,
)


@pytest.fixture
def bond():
    return Bond(100.0, 0.05, date(2020, 1, 15), date(2030, 1, 15), Frequency.SEMI_ANNUAL, Actual365Fixed())


def test_zero_coupon_bond_macaulay_duration_equals_time_to_maturity():
    zcb = ZeroCouponBond(100.0, date(2020, 1, 15), date(2030, 1, 15), day_count=Actual365Fixed())
    settlement = zcb.issue_date
    cfs = zcb.cash_flows_after(settlement)
    yc = YieldConvention.street(zcb.frequency)
    mac = macaulay_duration(cfs, settlement, 0.05, yc, zcb.day_count)
    expected_years = zcb.day_count.year_fraction(settlement, zcb.maturity_date)
    assert mac == pytest.approx(expected_years, rel=1e-9)


def test_modified_duration_continuous_equals_macaulay(bond):
    settlement = date(2024, 1, 16)
    cfs = bond.cash_flows_after(settlement)
    yc = YieldConvention(CompoundingConvention.CONTINUOUS)
    mac = macaulay_duration(cfs, settlement, 0.05, yc, bond.day_count)
    mod = modified_duration_from_macaulay(mac, 0.05, yc)
    assert mod == pytest.approx(mac)


def test_modified_duration_periodic_less_than_macaulay(bond):
    settlement = date(2024, 1, 16)
    cfs = bond.cash_flows_after(settlement)
    yc = YieldConvention.street(bond.frequency)
    mac = macaulay_duration(cfs, settlement, 0.05, yc, bond.day_count)
    mod = modified_duration(cfs, settlement, 0.05, yc, bond.day_count)
    assert mod < mac


def test_dv01_matches_modified_duration_approximation(bond):
    settlement = date(2024, 1, 16)
    cfs = bond.cash_flows_after(settlement)
    yc = YieldConvention.street(bond.frequency)
    y0 = 0.05
    price = price_from_yield(cfs, bond.face_value, settlement, y0, yc, bond.day_count)
    mod = modified_duration(cfs, settlement, y0, yc, bond.day_count)
    d01 = dv01(cfs, bond.face_value, settlement, y0, yc, bond.day_count)
    assert d01 == pytest.approx(mod * price * 1e-4, rel=1e-3)


def test_convexity_is_positive_for_a_plain_bond(bond):
    settlement = date(2024, 1, 16)
    cfs = bond.cash_flows_after(settlement)
    yc = YieldConvention.street(bond.frequency)
    conv = convexity(cfs, settlement, 0.05, yc, bond.day_count)
    assert conv > 0


def test_taylor_expansion_with_convexity_beats_duration_only(bond):
    settlement = date(2024, 1, 16)
    cfs = bond.cash_flows_after(settlement)
    yc = YieldConvention.street(bond.frequency)
    y0 = 0.05
    p0 = price_from_yield(cfs, bond.face_value, settlement, y0, yc, bond.day_count)
    mod = modified_duration(cfs, settlement, y0, yc, bond.day_count)
    conv = convexity(cfs, settlement, y0, yc, bond.day_count)

    shock = 0.02
    full = price_from_yield(cfs, bond.face_value, settlement, y0 + shock, yc, bond.day_count)
    duration_only = p0 * (1 - mod * shock)
    with_convexity = p0 * (1 - mod * shock + 0.5 * conv * shock**2)

    assert abs(full - with_convexity) < abs(full - duration_only)


def test_duration_raises_when_no_cash_flows_remain(bond):
    yc = YieldConvention.street(bond.frequency)
    with pytest.raises(ValueError):
        macaulay_duration([], bond.maturity_date, 0.05, yc, bond.day_count)


@pytest.mark.parametrize(
    ("convention", "divisor"),
    [
        (YieldConvention(CompoundingConvention.ANNUAL), 1.05),
        (YieldConvention(CompoundingConvention.PERIODIC, periods_per_year=2), 1.025),
        (YieldConvention(CompoundingConvention.PERIODIC, periods_per_year=4), 1.0125),
    ],
    ids=["annual", "semi-annual", "quarterly"],
)
def test_macaulay_shortcut_divides_by_one_plus_periodic_yield(convention, divisor):
    """The shortcut is exact for the uniform compounding rules — one factor per
    compounding frequency."""
    assert modified_duration_from_macaulay(7.5, 0.05, convention) == pytest.approx(7.5 / divisor, rel=1e-15)


def test_modified_duration_and_convexity_reject_a_zero_present_value(bond):
    """A zero PV has no percentage sensitivity to report: fail loudly instead of
    dividing by zero."""
    settlement = date(2024, 1, 16)
    yc = YieldConvention.street(bond.frequency)
    with pytest.raises(ValueError, match="present value of cash flows is zero"):
        modified_duration([], settlement, 0.05, yc, bond.day_count)
    with pytest.raises(ValueError, match="present value of cash flows is zero"):
        convexity([], settlement, 0.05, yc, bond.day_count)


def test_macaulay_shortcut_refuses_the_treasury_auction_convention(bond):
    """#61: dividing Macaulay by ``1 + y/m`` is exact only while the discount
    function is an exponential in t. Under the Treasury convention it is not,
    so the shortcut would be wrong by a small, undisclosed amount — it raises
    instead of returning a plausible number."""
    settlement = date(2024, 1, 16)
    cfs = bond.cash_flows_after(settlement)
    yc = YieldConvention.treasury_auction(bond.frequency)
    mac = macaulay_duration(cfs, settlement, 0.05, yc, bond.day_count)
    with pytest.raises(ValueError, match="does not convert to modified duration"):
        modified_duration_from_macaulay(mac, 0.05, yc)
    # The full computation is defined, and lands near — but not on — the shortcut.
    mod = modified_duration(cfs, settlement, 0.05, yc, bond.day_count)
    assert mod == pytest.approx(mac / 1.025, rel=1e-3)
    assert mod != mac / 1.025


def test_treasury_auction_risk_measures_match_full_repricing(bond):
    """Both analytic sensitivities checked against central differences of the
    library's own price function under the same convention — an independent
    check on the derivatives that #61 made necessary."""
    settlement = date(2024, 1, 16)
    cfs = bond.cash_flows_after(settlement)
    yc = YieldConvention.treasury_auction(bond.frequency)
    y, h = 0.05, 1e-5
    p0 = price_from_yield(cfs, bond.face_value, settlement, y, yc, bond.day_count)
    up = price_from_yield(cfs, bond.face_value, settlement, y + h, yc, bond.day_count)
    down = price_from_yield(cfs, bond.face_value, settlement, y - h, yc, bond.day_count)

    assert modified_duration(cfs, settlement, y, yc, bond.day_count) == pytest.approx(
        -(up - down) / (2 * h) / p0, rel=1e-7
    )
    assert convexity(cfs, settlement, y, yc, bond.day_count) == pytest.approx(
        (up - 2 * p0 + down) / (h * h) / p0, rel=1e-5
    )
