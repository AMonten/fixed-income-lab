"""Payment-date schedule generation.

Schedules are generated *backward* from the maturity date in fixed month
steps determined by the coupon frequency — the standard bond-market
convention. Stepping backward (rather than forward from issue date) means
any irregular ("stub") period falls at the *front* of the schedule, next to
issue, which is where real-world bonds put it.

That front period is *short* by default: the odd days between issue and the
first grid date are paid on that date. Passing ``first_coupon_date`` to
:func:`generate_schedule_dates` instead folds them into a later coupon,
producing a **long first coupon** -- a period spanning more than one nominal
step, which the market still sizes and accrues one quasi-coupon period at a
time (:func:`quasi_coupon_boundaries`, issue #19).

Business-day adjustment defers to an injectable
:class:`~fixed_income.conventions.calendar.Calendar` (see that module). The
library default, :data:`~fixed_income.conventions.calendar.WEEKEND_ONLY`,
knows about weekends only — no holidays — which is why every function below
takes ``calendar`` as an optional argument rather than requiring one:
existing call sites keep V1's original behavior unless they opt into a real
holiday calendar (issue #18).
"""

from __future__ import annotations

import calendar as _stdlib_calendar
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from ..conventions.calendar import WEEKEND_ONLY, Calendar
from ..conventions.frequency import Frequency


class BusinessDayConvention(str, Enum):
    """How an accrual-end date is adjusted onto a business day for payment."""

    NONE = "none"
    FOLLOWING = "following"
    MODIFIED_FOLLOWING = "modified_following"
    PRECEDING = "preceding"


def is_business_day(d: date, calendar: Calendar = WEEKEND_ONLY) -> bool:
    """Business-day check, per ``calendar`` (weekend-only by default)."""
    return calendar.is_business_day(d)


def adjust_business_day(
    d: date, convention: BusinessDayConvention, calendar: Calendar = WEEKEND_ONLY
) -> date:
    """Roll ``d`` onto a business day per ``convention`` and ``calendar``."""
    if convention is BusinessDayConvention.NONE:
        return d
    if convention is BusinessDayConvention.FOLLOWING:
        return _following(d, calendar)
    if convention is BusinessDayConvention.PRECEDING:
        return _preceding(d, calendar)
    if convention is BusinessDayConvention.MODIFIED_FOLLOWING:
        following = _following(d, calendar)
        if following.month != d.month:
            return _preceding(d, calendar)
        return following
    raise ValueError(f"Unknown business day convention: {convention}")  # pragma: no cover


def _following(d: date, calendar: Calendar) -> date:
    while not calendar.is_business_day(d):
        d += timedelta(days=1)
    return d


def _preceding(d: date, calendar: Calendar) -> date:
    while not calendar.is_business_day(d):
        d -= timedelta(days=1)
    return d


def subtract_business_days(d: date, n: int, calendar: Calendar = WEEKEND_ONLY) -> date:
    """Step back ``n`` business days from ``d`` under ``calendar``. ``d`` itself
    is not required to be a business day, and ``n=0`` returns ``d`` unchanged."""
    remaining = n
    current = d
    while remaining > 0:
        current -= timedelta(days=1)
        if calendar.is_business_day(current):
            remaining -= 1
    return current


def add_months(d: date, months: int) -> date:
    """Add ``months`` to ``d``, clamping the day to the target month's length."""
    total_months = d.month - 1 + months
    year = d.year + total_months // 12
    month = total_months % 12 + 1
    day = min(d.day, _stdlib_calendar.monthrange(year, month)[1])
    return date(year, month, day)


@dataclass(frozen=True)
class SchedulePeriod:
    """One accrual period of a coupon schedule.

    ``accrual_start``/``accrual_end`` are unadjusted dates used for day-count
    and coupon-size calculations. ``payment_date`` is ``accrual_end`` rolled
    onto a business day — the date cash actually changes hands.
    """

    period_index: int
    accrual_start: date
    accrual_end: date
    payment_date: date


def generate_schedule_dates(
    issue_date: date,
    maturity_date: date,
    frequency: Frequency,
    first_coupon_date: date | None = None,
) -> list[date]:
    """Generate unadjusted accrual-boundary dates, stepping backward from maturity.

    Returns ``n + 1`` dates for ``n`` periods: the first is always
    ``issue_date`` and the last is always ``maturity_date``. Any stub period
    (when the issue-to-maturity span isn't an exact multiple of the coupon
    step) falls at the front of the schedule.

    ``first_coupon_date`` names the date the first coupon is actually *paid*,
    which real bond terms state explicitly. It must be a quasi-coupon date of
    the maturity-anchored grid. Giving the grid date right after issue changes
    nothing; giving a *later* one drops the grid dates in between, so the
    first period spans more than one nominal step -- a **long first coupon**
    (#19). The dropped dates do not disappear as a concept: they remain
    quasi-coupon dates, which is what sizes the coupon, accrues interest and
    counts street yield exponents (see :func:`quasi_coupon_boundaries`).
    """
    if issue_date >= maturity_date:
        raise ValueError("issue_date must be before maturity_date")

    step = frequency.months_between_payments
    dates = [maturity_date]
    k = 1
    while True:
        # Always offset from maturity, never from the previous date: chaining
        # add_months(current, -step) lets one month-end clamp (31 -> 30) leak
        # into every earlier date (#59).
        current = add_months(maturity_date, -k * step)
        if current <= issue_date:
            break
        dates.append(current)
        k += 1
    dates.append(issue_date)
    all_dates = sorted(set(dates))

    if first_coupon_date is None:
        return all_dates
    if first_coupon_date <= issue_date:
        raise ValueError(f"first_coupon_date {first_coupon_date} must be after issue_date {issue_date}")
    if first_coupon_date > maturity_date:
        raise ValueError(
            f"first_coupon_date {first_coupon_date} must not be after maturity_date {maturity_date}"
        )
    try:
        regular_period_start(first_coupon_date, maturity_date, step)
    except ValueError as exc:
        raise ValueError(
            f"first_coupon_date {first_coupon_date} is not a quasi-coupon date of the "
            f"{step}-month grid anchored at maturity {maturity_date}: a coupon cannot be paid "
            f"off-grid. Grid dates are maturity - k*{step} months."
        ) from exc
    return [d for d in all_dates if d <= issue_date or d >= first_coupon_date]


def regular_period_start(period_end: date, maturity_date: date, months_step: int) -> date:
    """The regular grid date one coupon step before ``period_end``.

    The regular grid is anchored to maturity (``maturity - k * step``, see
    :func:`generate_schedule_dates`), so the date before a grid date must be
    derived from maturity too: ``add_months(period_end, -step)`` is wrong
    whenever ``period_end`` is itself a clamped month-end -- e.g. on a 31 Mar
    maturity grid, the date before 30 Sep is 31 Mar, not 30 Mar.

    Used both to decide whether a period is regular (its start *is* this date)
    and as the reference period a stub is a fragment of (ACT/ACT ICMA).
    """
    months_back = (maturity_date.year - period_end.year) * 12 + (maturity_date.month - period_end.month)
    if months_back < 0 or months_back % months_step:
        raise ValueError(
            f"{period_end} is not on the regular {months_step}-month grid "
            f"anchored at maturity {maturity_date}"
        )
    return add_months(maturity_date, -(months_back + months_step))


def months_between(start: date, end: date) -> int:
    """Whole months from ``start`` to ``end``, by calendar month arithmetic.

    Day-of-month is ignored: both ends of a schedule grid step share it (up to
    a month-end clamp), so the month difference *is* the step length.
    """
    return (end.year - start.year) * 12 + (end.month - start.month)


def quasi_coupon_boundaries(
    accrual_start: date, accrual_end: date, maturity_date: date, months_step: int
) -> list[date]:
    """Partition ``[accrual_start, accrual_end]`` at the quasi-coupon dates inside it.

    Returns the boundary dates in ascending order, always starting with
    ``accrual_start`` and ending with ``accrual_end``. A regular period and a
    short stub both yield exactly ``[accrual_start, accrual_end]`` -- there is
    no grid date strictly inside them. A **long** first period (one that
    skipped a coupon payment, see ``first_coupon_date`` of
    :func:`generate_schedule_dates`) yields the quasi-coupon dates it spans:
    e.g. a 2 Jul 1985 to 15 Feb 1986 first period on a 15 Feb/15 Aug grid
    returns ``[1985-07-02, 1985-08-15, 1986-02-15]``.

    This is the market decomposition every long-coupon calculation runs on:
    ICMA Rule 251 and 31 CFR 356 App. B both size a long coupon, and accrue
    interest inside it, sub-period by sub-period rather than treating the
    whole span as one oversized period.
    """
    boundaries = [accrual_end]
    current = accrual_end
    while True:
        previous = regular_period_start(current, maturity_date, months_step)
        if previous <= accrual_start:
            break
        boundaries.append(previous)
        current = previous
    boundaries.append(accrual_start)
    return sorted(boundaries)


def generate_schedule(
    issue_date: date,
    maturity_date: date,
    frequency: Frequency,
    business_day_convention: BusinessDayConvention = BusinessDayConvention.FOLLOWING,
    calendar: Calendar = WEEKEND_ONLY,
    first_coupon_date: date | None = None,
) -> list[SchedulePeriod]:
    """Generate the full list of accrual/payment periods for a coupon bond.

    See :func:`generate_schedule_dates` for ``first_coupon_date`` (long first
    coupon).
    """
    dates = generate_schedule_dates(issue_date, maturity_date, frequency, first_coupon_date)
    periods = []
    for i in range(len(dates) - 1):
        start, end = dates[i], dates[i + 1]
        periods.append(
            SchedulePeriod(
                period_index=i,
                accrual_start=start,
                accrual_end=end,
                payment_date=adjust_business_day(end, business_day_convention, calendar),
            )
        )
    return periods
