from datetime import date

import pytest

from fixed_income.cashflows.generator import generate_bullet_cashflows
from fixed_income.cashflows.schedule import generate_schedule
from fixed_income.conventions.day_count import (
    Actual360,
    Actual365Fixed,
    ActualActualICMA,
    DayCount,
    ScheduleContext,
    Thirty360US,
    get_day_count_convention,
)
from fixed_income.conventions.frequency import Frequency


def test_actual_360_year_fraction():
    dc = Actual360()
    assert dc.day_count(date(2024, 1, 1), date(2024, 7, 1)) == 182
    assert dc.year_fraction(date(2024, 1, 1), date(2024, 7, 1)) == pytest.approx(182 / 360)


def test_actual_365_year_fraction():
    dc = Actual365Fixed()
    assert dc.day_count(date(2023, 1, 1), date(2024, 1, 1)) == 365
    assert dc.year_fraction(date(2023, 1, 1), date(2024, 1, 1)) == pytest.approx(1.0)
    # Fixed 365 basis: a leap-year span still divides by 365, not 366.
    assert dc.year_fraction(date(2024, 1, 1), date(2025, 1, 1)) == pytest.approx(366 / 365)


def test_thirty_360_regular_month():
    dc = Thirty360US()
    assert dc.day_count(date(2024, 1, 15), date(2024, 2, 15)) == 30


def test_thirty_360_end_of_month_clamp():
    dc = Thirty360US()
    # 31st clamps to 30
    assert dc.day_count(date(2024, 1, 31), date(2024, 2, 28)) == 28
    # Both month-ends 31 -> both clamp to 30 -> exactly 30 days
    assert dc.day_count(date(2024, 1, 31), date(2024, 3, 31)) == 60


def test_thirty_360_last_day_of_february_clamps():
    dc = Thirty360US()
    # Non-leap year: Feb 28 is last day -> treated as day 30, so
    # Feb28->Mar28 is (30 days in month) - 2 = 28, not the naive 30.
    assert dc.day_count(date(2023, 2, 28), date(2023, 3, 28)) == 28
    # Leap year: Feb 29 is last day -> clamps to 30, and Mar 31 then also
    # clamps to 30 (per the d2==31-after-d1-clamped-to-30 rule) -> exactly 30.
    assert dc.day_count(date(2024, 2, 29), date(2024, 3, 31)) == 30


@pytest.mark.parametrize(
    "key",
    [DayCount.ACT_360, DayCount.ACT_365, DayCount.THIRTY_360, "ACT/360", "ACT/365", "30/360"],
)
def test_get_day_count_convention_resolves_all_known_keys(key):
    convention = get_day_count_convention(key)
    assert convention.year_fraction(date(2024, 1, 1), date(2024, 7, 1)) > 0


def test_get_day_count_convention_passthrough_for_instance():
    dc = Actual360()
    assert get_day_count_convention(dc) is dc


def test_get_day_count_convention_unknown_raises():
    with pytest.raises(ValueError):
        get_day_count_convention("ACT/ACT-ISDA")


@pytest.mark.parametrize("dc", [Actual360(), Actual365Fixed(), Thirty360US()])
def test_year_fraction_ignores_schedule_context_for_existing_conventions(dc):
    """Regression for #14: year_fraction() gains an optional ScheduleContext
    parameter, but every convention that exists today must produce exactly
    the same result with or without one."""
    start, end = date(2024, 1, 15), date(2024, 7, 15)
    context = ScheduleContext(
        reference_period_start=start, reference_period_end=end, frequency=Frequency.SEMI_ANNUAL
    )
    assert dc.year_fraction(start, end, context) == dc.year_fraction(start, end)


def test_actual_actual_icma_requires_schedule_context():
    with pytest.raises(ValueError):
        ActualActualICMA().year_fraction(date(2024, 1, 15), date(2024, 7, 15))


def test_actual_actual_icma_regular_period_equals_one_over_frequency():
    # A full reference period ([start, end] == the reference period itself)
    # reduces ICMA's formula to exactly 1/frequency, same as the market
    # convention for a regular semi-annual coupon.
    start, end = date(2024, 1, 15), date(2024, 7, 15)
    context = ScheduleContext(start, end, Frequency.SEMI_ANNUAL)
    assert ActualActualICMA().year_fraction(start, end, context) == pytest.approx(0.5)


def test_actual_actual_icma_rejects_non_positive_reference_period():
    context = ScheduleContext(date(2024, 7, 15), date(2024, 7, 15), Frequency.SEMI_ANNUAL)
    with pytest.raises(ValueError):
        ActualActualICMA().year_fraction(date(2024, 7, 15), date(2024, 7, 15), context)


def test_actual_actual_icma_stub_matches_hand_derived_fraction():
    """Reference case: derivation.engine=manual (ICMA Rule 251 / ISMA-99
    formula, applied by hand independently of the implementation),
    tolerance=1e-12. A short front stub prorates by actual days in the stub
    over actual days in the *regular* reference period it's a fragment of --
    not the stub's own (shorter) span."""
    dc = ActualActualICMA()
    calc_start, calc_end = date(2020, 3, 1), date(2020, 7, 15)
    reference_start, reference_end = date(2020, 1, 15), date(2020, 7, 15)
    context = ScheduleContext(reference_start, reference_end, Frequency.SEMI_ANNUAL)

    calc_days = (calc_end - calc_start).days
    reference_days = (reference_end - reference_start).days
    expected = calc_days / (2 * reference_days)

    assert dc.year_fraction(calc_start, calc_end, context) == pytest.approx(expected, rel=1e-12)


def test_eur_bond_stub_coupon_under_act_act_icma_matches_hand_derived_reference():
    """Reference case for #15 (ROADMAP Bloque 5's "bono EUR bajo ACT/ACT
    ICMA"): derivation.engine=manual (ICMA Rule 251), tolerance=1e-9. A
    semi-annual EUR-style bond (5% coupon, 100 face) issued mid-period
    (2020-03-01) into a regular 2020-01-15/2020-07-15 semi-annual grid: the
    first (stub) coupon must be the regular semi-annual coupon prorated by
    actual days in the stub over actual days in the full reference period --
    not the flat half-coupon a regular period would pay -- and every
    subsequent regular period pays the flat semi-annual coupon.
    """
    schedule = generate_schedule(date(2020, 3, 1), date(2025, 1, 15), Frequency.SEMI_ANNUAL)
    dc = ActualActualICMA()
    cfs = generate_bullet_cashflows(100.0, 0.05, schedule, dc, frequency=Frequency.SEMI_ANNUAL)

    stub = schedule[0]
    reference_start = date(2020, 1, 15)
    calc_days = (stub.accrual_end - stub.accrual_start).days
    reference_days = (stub.accrual_end - reference_start).days
    expected_stub_coupon = 100.0 * 0.05 * calc_days / (2 * reference_days)

    assert cfs[0].coupon == pytest.approx(expected_stub_coupon, rel=1e-9)
    assert cfs[1].coupon == pytest.approx(100.0 * 0.05 / 2)


def test_get_day_count_convention_resolves_act_act_icma_key():
    convention = get_day_count_convention("ACT/ACT-ICMA")
    assert isinstance(convention, ActualActualICMA)
    assert get_day_count_convention(DayCount.ACT_ACT_ICMA) is convention
