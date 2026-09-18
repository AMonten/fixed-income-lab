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
