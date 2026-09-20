from datetime import date

import pytest

from fixed_income.cashflows.schedule import (
    BusinessDayConvention,
    add_months,
    adjust_business_day,
    generate_schedule,
    generate_schedule_dates,
    is_business_day,
    subtract_business_days,
)
from fixed_income.conventions.calendar import UnitedStatesFederalCalendar
from fixed_income.conventions.frequency import Frequency


def test_add_months_clamps_to_month_length():
    # Jan 31 + 1 month -> Feb has only 28/29 days
    assert add_months(date(2023, 1, 31), 1) == date(2023, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2024, 1, 31), -1) == date(2023, 12, 31)


def test_generate_schedule_dates_exact_multiple_has_no_stub():
    dates = generate_schedule_dates(date(2020, 1, 15), date(2025, 1, 15), Frequency.SEMI_ANNUAL)
    assert dates[0] == date(2020, 1, 15)
    assert dates[-1] == date(2025, 1, 15)
    assert len(dates) == 11  # 10 periods
    # every consecutive gap is 6 months
    for i in range(len(dates) - 1):
        assert add_months(dates[i], 6) == dates[i + 1]


def test_generate_schedule_dates_stub_period_at_front():
    # 4 years 3 months issue-to-maturity with semi-annual frequency: stub at front
    dates = generate_schedule_dates(date(2020, 4, 15), date(2025, 1, 15), Frequency.SEMI_ANNUAL)
    assert dates[0] == date(2020, 4, 15)
    assert dates[-1] == date(2025, 1, 15)
    # first period (stub) is shorter than 6 months
    first_gap_months = (dates[1].year - dates[0].year) * 12 + (dates[1].month - dates[0].month)
    assert first_gap_months < 6
    # all subsequent periods are regular 6-month steps
    for i in range(1, len(dates) - 1):
        assert add_months(dates[i], 6) == dates[i + 1]


def test_generate_schedule_dates_requires_issue_before_maturity():
    with pytest.raises(ValueError):
        generate_schedule_dates(date(2025, 1, 15), date(2020, 1, 15), Frequency.ANNUAL)


def test_generate_schedule_period_count_and_payment_dates():
    periods = generate_schedule(date(2020, 1, 15), date(2022, 1, 15), Frequency.SEMI_ANNUAL)
    assert len(periods) == 4
    assert periods[0].accrual_start == date(2020, 1, 15)
    assert periods[-1].accrual_end == date(2022, 1, 15)
    for i, period in enumerate(periods):
        assert period.period_index == i
        # payment_date is always a business day
        assert is_business_day(period.payment_date)


def test_adjust_business_day_following_rolls_weekend_forward():
    saturday = date(2024, 1, 13)
    assert adjust_business_day(saturday, BusinessDayConvention.FOLLOWING) == date(2024, 1, 15)


def test_adjust_business_day_preceding_rolls_weekend_backward():
    sunday = date(2024, 1, 14)
    assert adjust_business_day(sunday, BusinessDayConvention.PRECEDING) == date(2024, 1, 12)


def test_adjust_business_day_none_is_identity():
    saturday = date(2024, 1, 13)
    assert adjust_business_day(saturday, BusinessDayConvention.NONE) == saturday


def test_adjust_business_day_modified_following_stays_in_month():
    # Dec 31 2023 is a Sunday; following would roll into January, so
    # modified-following should instead roll backward to stay in December.
    dec_31 = date(2023, 12, 31)
    assert adjust_business_day(dec_31, BusinessDayConvention.MODIFIED_FOLLOWING) == date(2023, 12, 29)


def test_subtract_business_days_zero_is_identity_even_off_business_day():
    saturday = date(2024, 1, 13)
    assert subtract_business_days(saturday, 0) == saturday


def test_subtract_business_days_skips_weekend():
    # Monday 2024-01-15 minus 1 business day is Friday 2024-01-12, not
    # Sunday 2024-01-14 (a naive timedelta(days=1) subtraction).
    monday = date(2024, 1, 15)
    assert subtract_business_days(monday, 1) == date(2024, 1, 12)


def test_subtract_business_days_from_a_weekend_start():
    # 2 business days back from Sunday 2024-01-14: Sat(skip), Fri(1), Thu(2).
    sunday = date(2024, 1, 14)
    assert subtract_business_days(sunday, 2) == date(2024, 1, 11)


def test_adjust_business_day_with_calendar_rolls_past_a_holiday():
    """Regression for #18: business-day adjustment used to know only about
    weekends. July 4, 2024 is a Thursday -- a business day under the
    weekend-only default, but a US federal holiday."""
    july_4th_2024 = date(2024, 7, 4)
    us_calendar = UnitedStatesFederalCalendar()
    assert adjust_business_day(july_4th_2024, BusinessDayConvention.FOLLOWING) == july_4th_2024
    assert adjust_business_day(
        july_4th_2024, BusinessDayConvention.FOLLOWING, us_calendar
    ) == date(2024, 7, 5)


def test_subtract_business_days_with_calendar_skips_a_holiday():
    us_calendar = UnitedStatesFederalCalendar()
    friday_after = date(2024, 7, 5)
    # 1 business day back from Friday 2024-07-05: under weekend-only that's
    # Thursday 2024-07-04, but that Thursday is a federal holiday.
    assert subtract_business_days(friday_after, 1) == date(2024, 7, 4)
    assert subtract_business_days(friday_after, 1, us_calendar) == date(2024, 7, 3)


def test_generate_schedule_with_calendar_moves_payment_date_off_a_holiday():
    us_calendar = UnitedStatesFederalCalendar()
    periods_weekend_only = generate_schedule(
        date(2024, 1, 4), date(2025, 1, 4), Frequency.SEMI_ANNUAL
    )
    periods_us_calendar = generate_schedule(
        date(2024, 1, 4), date(2025, 1, 4), Frequency.SEMI_ANNUAL,
        calendar=us_calendar,
    )
    # July 4, 2024 (an accrual boundary here) is a business day under
    # weekend-only rules but a US federal holiday.
    assert periods_weekend_only[0].payment_date == date(2024, 7, 4)
    assert periods_us_calendar[0].payment_date == date(2024, 7, 5)
    for period in periods_us_calendar:
        assert is_business_day(period.payment_date, us_calendar)
