"""Day-count conventions.

A day-count convention answers two related questions for a period
``[start, end)``:

1. How many "days" elapsed, under the convention's counting rule
   (:meth:`DayCountConvention.day_count`)?
2. What fraction of a year does that represent
   (:meth:`DayCountConvention.year_fraction`)?

Year fractions are the building block for accrual, coupon sizing, and
discounting throughout the library. Every other module accesses a
convention through the :class:`DayCountConvention` interface, never through
convention-specific branching, so a new convention can be added by writing
one class and registering it below.

Supported conventions
----------------------

``ACT/360`` (:class:`Actual360`)
    ``year_fraction = (end - start).days / 360``.
    Common on money-market instruments and floating-rate notes.

``ACT/365`` (:class:`Actual365Fixed`)
    ``year_fraction = (end - start).days / 365``.
    Fixed 365-day year regardless of leap years ("Actual/365 Fixed").

``30/360`` (:class:`Thirty360US`)
    The "30/360 Bond Basis" (ISDA / US municipal) convention, which treats
    every month as having 30 days:

    ``days = (Y2-Y1)*360 + (M2-M1)*30 + (D2-D1)``

    with the standard end-of-month adjustment: if ``D1`` is the 31st (or
    the last day of February) it is set to 30; if ``D2`` is 31 and ``D1``
    was already adjusted to 30, ``D2`` is also set to 30.
    ``year_fraction = days / 360``.
"""

from __future__ import annotations

import calendar
from abc import ABC, abstractmethod
from datetime import date
from enum import Enum


class DayCountConvention(ABC):
    """Interface for day-count conventions."""

    name: str

    @abstractmethod
    def day_count(self, start: date, end: date) -> int:
        """Number of days between ``start`` and ``end`` per this convention."""

    @abstractmethod
    def year_fraction(self, start: date, end: date) -> float:
        """Fraction of a year between ``start`` and ``end`` per this convention."""

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"{self.__class__.__name__}({self.name!r})"


class Actual360(DayCountConvention):
    """ACT/360: actual elapsed days divided by a 360-day year."""

    name = "ACT/360"

    def day_count(self, start: date, end: date) -> int:
        return (end - start).days

    def year_fraction(self, start: date, end: date) -> float:
        return self.day_count(start, end) / 360.0


class Actual365Fixed(DayCountConvention):
    """ACT/365 (Fixed): actual elapsed days divided by a fixed 365-day year."""

    name = "ACT/365"

    def day_count(self, start: date, end: date) -> int:
        return (end - start).days

    def year_fraction(self, start: date, end: date) -> float:
        return self.day_count(start, end) / 365.0


class Thirty360US(DayCountConvention):
    """30/360 Bond Basis: every month treated as having 30 days."""

    name = "30/360"

    def day_count(self, start: date, end: date) -> int:
        d1, d2 = start.day, end.day
        m1, m2 = start.month, end.month
        y1, y2 = start.year, end.year

        if d1 == 31 or _is_last_day_of_february(start):
            d1 = 30
        if d2 == 31 and d1 == 30:
            d2 = 30

        return (y2 - y1) * 360 + (m2 - m1) * 30 + (d2 - d1)

    def year_fraction(self, start: date, end: date) -> float:
        return self.day_count(start, end) / 360.0


def _is_last_day_of_february(d: date) -> bool:
    if d.month != 2:
        return False
    last_day_of_february = calendar.monthrange(d.year, d.month)[1]
    return d.day == last_day_of_february


class DayCount(str, Enum):
    """Convenience enum for selecting a convention by name."""

    ACT_360 = "ACT/360"
    ACT_365 = "ACT/365"
    THIRTY_360 = "30/360"


_REGISTRY: dict[str, DayCountConvention] = {
    DayCount.ACT_360.value: Actual360(),
    DayCount.ACT_365.value: Actual365Fixed(),
    DayCount.THIRTY_360.value: Thirty360US(),
}


def get_day_count_convention(convention: DayCountConvention | DayCount | str) -> DayCountConvention:
    """Resolve a convention passed as an instance, :class:`DayCount`, or string name."""
    if isinstance(convention, DayCountConvention):
        return convention
    key = convention.value if isinstance(convention, DayCount) else str(convention)
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"Unknown day-count convention {key!r}. Known conventions: {known}") from exc


def register_day_count_convention(key: str, convention: DayCountConvention) -> None:
    """Register an additional day-count convention under ``key``.

    Allows extending the system (e.g. ACT/ACT ISDA) without modifying this module.
    """
    _REGISTRY[key] = convention
