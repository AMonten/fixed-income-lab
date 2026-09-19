from datetime import date

import pytest

from fixed_income.cashflows.generator import (
    cash_flows_after,
    generate_bullet_cashflows,
    generate_variable_rate_cashflows,
    generate_zero_coupon_cashflow,
)
from fixed_income.cashflows.schedule import generate_schedule
from fixed_income.conventions.day_count import Actual365Fixed, ScheduleContext
from fixed_income.conventions.frequency import Frequency


@pytest.fixture
def schedule():
    return generate_schedule(date(2020, 1, 15), date(2025, 1, 15), Frequency.SEMI_ANNUAL)


def test_bullet_cashflows_only_repay_principal_at_final_period(schedule):
    cfs = generate_bullet_cashflows(100.0, 0.05, schedule, Actual365Fixed())
    assert len(cfs) == len(schedule)
    for cf in cfs[:-1]:
        assert cf.principal == 0.0
        assert cf.begin_principal == 100.0
        assert cf.end_principal == 100.0
    assert cfs[-1].principal == 100.0
    assert cfs[-1].end_principal == 0.0


def test_bullet_cashflow_coupon_matches_year_fraction(schedule):
    dc = Actual365Fixed()
    cfs = generate_bullet_cashflows(100.0, 0.05, schedule, dc)
    for period, cf in zip(schedule, cfs, strict=True):
        expected = 100.0 * 0.05 * dc.year_fraction(period.accrual_start, period.accrual_end)
        assert cf.coupon == pytest.approx(expected)
        assert cf.total == pytest.approx(cf.coupon + cf.principal)


def test_variable_rate_cashflows_length_mismatch_raises(schedule):
    with pytest.raises(ValueError):
        generate_variable_rate_cashflows(100.0, [0.05, 0.06], schedule, Actual365Fixed())


def test_variable_rate_cashflows_matches_bullet_when_rate_is_constant(schedule):
    dc = Actual365Fixed()
    bullet = generate_bullet_cashflows(100.0, 0.05, schedule, dc)
    variable = generate_variable_rate_cashflows(100.0, [0.05] * len(schedule), schedule, dc)
    assert [cf.coupon for cf in bullet] == pytest.approx([cf.coupon for cf in variable])


def test_zero_coupon_cashflow_is_single_redemption_payment():
    cfs = generate_zero_coupon_cashflow(100.0, date(2020, 1, 15), date(2025, 1, 15))
    assert len(cfs) == 1
    cf = cfs[0]
    assert cf.coupon == 0.0
    assert cf.principal == 100.0
    assert cf.begin_principal == 100.0
    assert cf.end_principal == 0.0


def test_stub_period_coupon_receives_schedule_context():
    """Regression for #14: a stub period's year_fraction() call must carry a
    ScheduleContext describing that same period and the bond's frequency --
    the interface a future ACT/ACT ICMA convention needs to size a stub."""

    class _SpyDayCount(Actual365Fixed):
        def __init__(self):
            self.received_contexts: list[ScheduleContext | None] = []

        def year_fraction(self, start, end, context=None):
            self.received_contexts.append(context)
            return super().year_fraction(start, end)

    # 2020-03-01 to 2025-01-15 semi-annual isn't an exact multiple of 6
    # months, so the first period (2020-03-01 -> 2020-07-15) is a stub.
    stub_schedule = generate_schedule(date(2020, 3, 1), date(2025, 1, 15), Frequency.SEMI_ANNUAL)
    spy = _SpyDayCount()
    generate_bullet_cashflows(100.0, 0.05, stub_schedule, spy, frequency=Frequency.SEMI_ANNUAL)

    stub_period = stub_schedule[0]
    assert spy.received_contexts[0] == ScheduleContext(
        stub_period.accrual_start, stub_period.accrual_end, Frequency.SEMI_ANNUAL
    )
    # Regular periods never call year_fraction() at all (flat amount instead).
    assert len(spy.received_contexts) == 1


def test_cash_flows_after_filters_strictly_after_settlement(schedule):
    dc = Actual365Fixed()
    cfs = generate_bullet_cashflows(100.0, 0.05, schedule, dc)
    remaining = cash_flows_after(cfs, cfs[2].payment_date)
    assert all(cf.payment_date > cfs[2].payment_date for cf in remaining)
    assert len(remaining) == len(cfs) - 3
