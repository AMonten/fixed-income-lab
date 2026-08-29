from datetime import date

import pytest

from fixed_income.conventions.day_count import (
    Actual360,
    Actual365Fixed,
    DayCount,
    Thirty360US,
    get_day_count_convention,
)


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
