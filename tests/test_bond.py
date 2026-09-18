from datetime import date

import pytest

from fixed_income.conventions.day_count import Actual365Fixed
from fixed_income.conventions.frequency import Frequency
from fixed_income.instruments.bond import Bond, ZeroCouponBond


def test_bond_rejects_non_positive_face_value():
    with pytest.raises(ValueError):
        Bond(0.0, 0.05, date(2020, 1, 1), date(2025, 1, 1))


def test_bond_rejects_issue_after_maturity():
    with pytest.raises(ValueError):
        Bond(100.0, 0.05, date(2025, 1, 1), date(2020, 1, 1))


def test_bond_cash_flows_sum_to_principal_plus_total_coupons():
    bond = Bond(100.0, 0.05, date(2020, 1, 15), date(2025, 1, 15), Frequency.SEMI_ANNUAL, Actual365Fixed())
    cfs = bond.cash_flows()
    assert sum(cf.principal for cf in cfs) == pytest.approx(100.0)
    assert cfs[-1].payment_date >= bond.maturity_date


def test_bond_cash_flows_after_excludes_paid_periods():
    bond = Bond(100.0, 0.05, date(2020, 1, 15), date(2025, 1, 15), Frequency.SEMI_ANNUAL, Actual365Fixed())
    all_cfs = bond.cash_flows()
    settlement = all_cfs[3].payment_date
    remaining = bond.cash_flows_after(settlement)
    assert len(remaining) == len(all_cfs) - 4


def test_bond_previous_and_next_coupon_date():
    bond = Bond(100.0, 0.05, date(2020, 1, 15), date(2025, 1, 15), Frequency.SEMI_ANNUAL, Actual365Fixed())
    mid_period_date = date(2022, 4, 1)  # inside the 2022-01-15 -> 2022-07-15 period
    assert bond.previous_coupon_date(mid_period_date) == date(2022, 1, 15)
    assert bond.next_coupon_date(mid_period_date) == date(2022, 7, 15)


def test_zero_coupon_bond_has_single_cash_flow_and_zero_coupon_rate():
    zcb = ZeroCouponBond(100.0, date(2020, 1, 15), date(2025, 1, 15))
    assert zcb.coupon_rate == 0.0
    cfs = zcb.cash_flows()
    assert len(cfs) == 1
    assert cfs[0].total == pytest.approx(100.0)
    assert cfs[0].payment_date == date(2025, 1, 15)


def test_zero_coupon_bond_constructor_rejects_coupon_rate():
    """Regression for #7: a zero-coupon bond has no coupon rate to configure,
    so unlike Bond, its constructor must not silently accept and discard one."""
    with pytest.raises(TypeError):
        ZeroCouponBond(100.0, 0.05, date(2020, 1, 15), date(2025, 1, 15))  # type: ignore[call-arg]


def test_zero_coupon_bond_schedule_and_cash_flows_agree_on_payment_date():
    """Regression for #7: schedule() and cash_flows() used to disagree when the
    unadjusted maturity date falls on a weekend -- schedule() returned it
    unadjusted while cash_flows() rolled it to the next business day."""
    zcb = ZeroCouponBond(100.0, date(2020, 1, 15), date(2025, 1, 18))  # 2025-01-18 is a Saturday
    schedule_payment_date = zcb.schedule()[0].payment_date
    cash_flow_payment_date = zcb.cash_flows()[0].payment_date
    assert schedule_payment_date == cash_flow_payment_date == date(2025, 1, 20)  # rolled to Monday


def test_zero_coupon_bond_schedule_is_single_period():
    zcb = ZeroCouponBond(100.0, date(2020, 1, 15), date(2025, 1, 15))
    schedule = zcb.schedule()
    assert len(schedule) == 1
    assert schedule[0].accrual_start == zcb.issue_date
    assert schedule[0].accrual_end == zcb.maturity_date
