from datetime import date

from fixed_income.conventions.calendar import (
    WEEKEND_ONLY,
    UnitedStatesFederalCalendar,
    WeekendOnlyCalendar,
)


def test_weekend_only_calendar_knows_nothing_but_weekends():
    calendar = WeekendOnlyCalendar()
    assert calendar.is_business_day(date(2024, 7, 4))  # Thursday, a federal holiday
    assert not calendar.is_business_day(date(2024, 7, 6))  # Saturday
    assert not calendar.is_business_day(date(2024, 7, 7))  # Sunday


def test_weekend_only_is_the_module_default_instance():
    assert isinstance(WEEKEND_ONLY, WeekendOnlyCalendar)


def test_us_federal_calendar_still_rejects_weekends():
    calendar = UnitedStatesFederalCalendar()
    assert not calendar.is_business_day(date(2024, 7, 6))  # Saturday
    assert not calendar.is_business_day(date(2024, 7, 7))  # Sunday


def test_us_federal_calendar_rejects_fixed_date_holiday_on_a_weekday():
    calendar = UnitedStatesFederalCalendar()
    # July 4, 2024 is a Thursday -- a business day under weekend-only rules,
    # but a federal holiday.
    assert not calendar.is_business_day(date(2024, 7, 4))
    assert calendar.is_business_day(date(2024, 7, 5))


def test_us_federal_calendar_rejects_floating_holidays():
    calendar = UnitedStatesFederalCalendar()
    assert not calendar.is_business_day(date(2024, 1, 15))  # MLK Day
    assert not calendar.is_business_day(date(2024, 2, 19))  # Washington's Birthday
    assert not calendar.is_business_day(date(2024, 5, 27))  # Memorial Day
    assert not calendar.is_business_day(date(2024, 9, 2))  # Labor Day
    assert not calendar.is_business_day(date(2024, 10, 14))  # Columbus Day
    assert not calendar.is_business_day(date(2024, 11, 28))  # Thanksgiving


def test_us_federal_calendar_observes_saturday_holiday_on_preceding_friday():
    calendar = UnitedStatesFederalCalendar()
    # July 4, 2020 falls on a Saturday.
    assert calendar.is_business_day(date(2020, 7, 3)) is False
    assert calendar.is_business_day(date(2020, 7, 2)) is True


def test_us_federal_calendar_observes_sunday_holiday_on_following_monday():
    calendar = UnitedStatesFederalCalendar()
    # Juneteenth 2022 falls on a Sunday.
    assert calendar.is_business_day(date(2022, 6, 20)) is False
    assert calendar.is_business_day(date(2022, 6, 21)) is True


def test_us_federal_calendar_juneteenth_only_from_2021():
    calendar = UnitedStatesFederalCalendar()
    # June 19, 2020 (a Friday) predates Juneteenth becoming a federal holiday.
    assert calendar.is_business_day(date(2020, 6, 19)) is True
    assert calendar.is_business_day(date(2021, 6, 18)) is False  # observed Friday
