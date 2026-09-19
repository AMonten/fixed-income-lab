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

Schedule context
-----------------

``year_fraction(start, end)`` alone is structurally insufficient for
ACT/ACT ICMA (#15): its formula divides by the *reference coupon period*
containing ``[start, end]``, not just the two dates themselves, so a
period-based convention needs to know that period's own bounds and the
instrument's coupon frequency. :meth:`DayCountConvention.year_fraction`
therefore takes an optional :class:`ScheduleContext` — see its docstring for
which call sites can supply one and which can't.

Existing conventions (``ACT/360``, ``ACT/365``, ``30/360``) accept and
ignore ``context``: none of their formulas reference a reference period, so
threading it through changes no existing result (issue #14).

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

``ACT/ACT-ICMA`` (:class:`ActualActualICMA`)
    ``year_fraction = actual_days_in[start, end] / (frequency * actual_days_in_reference_period)``,
    where the reference period comes from a :class:`ScheduleContext` (see
    above) — this convention *requires* one and raises without it. Used by
    most fixed-rate non-USD sovereign and international bonds.
"""

from __future__ import annotations

import calendar
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from enum import Enum

from .frequency import Frequency


@dataclass(frozen=True)
class ScheduleContext:
    """The reference-period context surrounding a :meth:`DayCountConvention.year_fraction`
    calculation, needed by period-based conventions (ACT/ACT ICMA — see #15) that
    can't be computed from two isolated dates alone.

    ``reference_period_start``/``reference_period_end`` are the *regular*
    (nominal) coupon period that ``[start, end]`` sits inside — **not**
    necessarily ``[start, end]`` itself. For a regular period they coincide;
    for a stub (the actual calculation span is shorter than a full nominal
    period — V1 schedules only ever produce a *short* stub, always at the
    front, per :func:`fixed_income.cashflows.schedule.generate_schedule_dates`)
    they're the full nominal period the stub is a fragment of. ICMA's
    formula divides by the days in that *nominal* period, not the stub's own
    (shorter) span — passing the stub's own bounds here would make every
    stub coupon come out as a flat ``1/frequency``, exactly the proration
    ICMA exists to avoid.

    Only meaningful when ``[start, end]`` lies within a single coupon
    period — coupon sizing (:mod:`fixed_income.cashflows.generator`,
    :class:`~fixed_income.instruments.amortizing.AmortizingBond`). Settlement-
    to-arbitrary-payment-date calendar time (curve discounting, "true yield"
    discounting — see :mod:`fixed_income.pricing.present_value` and
    :mod:`fixed_income.pricing.yield_convention`) can span many coupon
    periods with no single reference period to hand; those call sites pass
    no context, by design, rather than a misleading one.

    Attributes:
        reference_period_start: Start of the regular (nominal) coupon period
            containing this calculation.
        reference_period_end: End of that same regular coupon period.
        frequency: The instrument's coupon frequency.
    """

    reference_period_start: date
    reference_period_end: date
    frequency: Frequency


class DayCountConvention(ABC):
    """Interface for day-count conventions."""

    name: str

    @abstractmethod
    def day_count(self, start: date, end: date) -> int:
        """Number of days between ``start`` and ``end`` per this convention."""

    @abstractmethod
    def year_fraction(self, start: date, end: date, context: ScheduleContext | None = None) -> float:
        """Fraction of a year between ``start`` and ``end`` per this convention.

        ``context``, when given, is the coupon period containing ``[start,
        end]`` — see :class:`ScheduleContext`. Conventions that don't need it
        (everything in V1 except the ACT/ACT ICMA planned in #15) ignore it.
        """

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"{self.__class__.__name__}({self.name!r})"


class Actual360(DayCountConvention):
    """ACT/360: actual elapsed days divided by a 360-day year."""

    name = "ACT/360"

    def day_count(self, start: date, end: date) -> int:
        return (end - start).days

    def year_fraction(self, start: date, end: date, context: ScheduleContext | None = None) -> float:
        return self.day_count(start, end) / 360.0


class Actual365Fixed(DayCountConvention):
    """ACT/365 (Fixed): actual elapsed days divided by a fixed 365-day year."""

    name = "ACT/365"

    def day_count(self, start: date, end: date) -> int:
        return (end - start).days

    def year_fraction(self, start: date, end: date, context: ScheduleContext | None = None) -> float:
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

    def year_fraction(self, start: date, end: date, context: ScheduleContext | None = None) -> float:
        return self.day_count(start, end) / 360.0


class ActualActualICMA(DayCountConvention):
    """ACT/ACT ICMA (ISMA-99 / ICMA Rule 251): the coupon-period-based
    actual/actual convention used by most fixed-rate non-USD sovereign and
    international bonds.

    ``year_fraction = actual_days_in[start, end] / (frequency * actual_days_in_reference_period)``

    where the reference period is the *regular* nominal coupon period
    containing ``[start, end]`` — supplied via :class:`ScheduleContext`,
    since this can't be derived from ``start``/``end`` alone (that's the
    whole reason this convention needs schedule context; see #14). For a
    regular period (``[start, end]`` == the reference period) this reduces
    to exactly ``1/frequency``; for a stub it prorates by actual days.
    """

    name = "ACT/ACT-ICMA"

    def day_count(self, start: date, end: date) -> int:
        return (end - start).days

    def year_fraction(self, start: date, end: date, context: ScheduleContext | None = None) -> float:
        if context is None:
            raise ValueError(
                "ActualActualICMA.year_fraction requires a ScheduleContext: it cannot be "
                "computed from two isolated dates alone. See ScheduleContext's docstring "
                "for which call sites can supply one."
            )
        reference_days = self.day_count(context.reference_period_start, context.reference_period_end)
        if reference_days <= 0:
            raise ValueError(
                f"Cannot compute ACT/ACT ICMA: non-positive reference period length "
                f"({context.reference_period_start} to {context.reference_period_end})"
            )
        return self.day_count(start, end) / (context.frequency.periods_per_year * reference_days)


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
    ACT_ACT_ICMA = "ACT/ACT-ICMA"


_REGISTRY: dict[str, DayCountConvention] = {
    DayCount.ACT_360.value: Actual360(),
    DayCount.ACT_365.value: Actual365Fixed(),
    DayCount.THIRTY_360.value: Thirty360US(),
    DayCount.ACT_ACT_ICMA.value: ActualActualICMA(),
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
