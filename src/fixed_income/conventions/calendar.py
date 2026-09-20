"""Business-day calendars.

A :class:`Calendar` answers one question: is a given date a business day?
Everything that rolls a date onto (or steps a date across) business days —
:func:`~fixed_income.cashflows.schedule.adjust_business_day`,
:func:`~fixed_income.cashflows.schedule.subtract_business_days`,
:func:`~fixed_income.cashflows.schedule.generate_schedule` — takes a
``Calendar`` and defers to it, rather than hardcoding a rule.

:class:`WeekendOnlyCalendar` (``WEEKEND_ONLY``, the library default) is V1's
original weekend-only rule, kept as the default so existing call sites don't
change behavior. :class:`UnitedStatesFederalCalendar` is the first calendar
with real holidays, added to prove the seam actually works end-to-end
(issue #18) — reconciling against a specific market (payment systems,
custodian, a given bond market's own calendar) may need a different holiday
set than the US federal one; that's a separate calendar to add later, not a
reason to block this one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cache


class Calendar(ABC):
    """Determines whether a date is a business day."""

    @abstractmethod
    def is_business_day(self, d: date) -> bool: ...


@dataclass(frozen=True)
class WeekendOnlyCalendar(Calendar):
    """Saturday/Sunday are non-business days; nothing else is. No holidays."""

    def is_business_day(self, d: date) -> bool:
        return d.weekday() < 5


WEEKEND_ONLY = WeekendOnlyCalendar()


@dataclass(frozen=True)
class UnitedStatesFederalCalendar(Calendar):
    """Weekends plus US federal holidays (5 U.S.C. § 6103), each rolled onto
    the nearest weekday when it falls on a weekend (Saturday -> observed the
    preceding Friday, Sunday -> observed the following Monday).

    Juneteenth (June 19) is included only from 2021 onward, matching when it
    became a federal holiday.

    This is the *federal* calendar, not a market-specific one -- e.g. SIFMA's
    US bond-market calendar also closes for Good Friday, which is not a
    federal holiday. Swap in a market-specific calendar where that
    distinction matters.
    """

    def is_business_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in _us_federal_holidays(d.year)


def _observed(d: date) -> date:
    """Roll a holiday landing on a weekend onto the adjacent weekday."""
    if d.weekday() == 5:  # Saturday -> preceding Friday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday -> following Monday
        return d + timedelta(days=1)
    return d


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """The ``n``-th occurrence (1-indexed) of ``weekday`` (Monday=0) in ``month``."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """The last occurrence of ``weekday`` (Monday=0) in ``month``."""
    next_month_first = date(year + (month == 12), month % 12 + 1, 1)
    last_day = next_month_first - timedelta(days=1)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=offset)


@cache
def _us_federal_holidays(year: int) -> frozenset[date]:
    holidays = {
        _observed(date(year, 1, 1)),  # New Year's Day
        _nth_weekday_of_month(year, 1, 0, 3),  # Birthday of Martin Luther King, Jr.
        _nth_weekday_of_month(year, 2, 0, 3),  # Washington's Birthday
        _last_weekday_of_month(year, 5, 0),  # Memorial Day
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday_of_month(year, 9, 0, 1),  # Labor Day
        _nth_weekday_of_month(year, 10, 0, 2),  # Columbus Day
        _observed(date(year, 11, 11)),  # Veterans Day
        _nth_weekday_of_month(year, 11, 3, 4),  # Thanksgiving Day
        _observed(date(year, 12, 25)),  # Christmas Day
    }
    if year >= 2021:
        holidays.add(_observed(date(year, 6, 19)))  # Juneteenth
    return frozenset(holidays)
