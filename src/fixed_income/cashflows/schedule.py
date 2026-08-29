"""Payment-date schedule generation.

Schedules are generated *backward* from the maturity date in fixed month
steps determined by the coupon frequency — the standard bond-market
convention. Stepping backward (rather than forward from issue date) means
any irregular ("stub") period falls at the *front* of the schedule, next to
issue, which is where real-world bonds put it.

Business-day adjustment here only knows about weekends (Saturday/Sunday) —
there is no holiday calendar in V1. This is a deliberate, documented
simplification: plugging in a holiday calendar later only requires replacing
:func:`is_business_day`.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from ..conventions.frequency import Frequency


class BusinessDayConvention(str, Enum):
    """How an accrual-end date is adjusted onto a business day for payment."""

    NONE = "none"
    FOLLOWING = "following"
    MODIFIED_FOLLOWING = "modified_following"
    PRECEDING = "preceding"


def is_business_day(d: date) -> bool:
    """Weekend-only business-day check (no holiday calendar in V1)."""
    return d.weekday() < 5


def adjust_business_day(d: date, convention: BusinessDayConvention) -> date:
    """Roll ``d`` onto a business day per ``convention``."""
    if convention is BusinessDayConvention.NONE:
        return d
    if convention is BusinessDayConvention.FOLLOWING:
        return _following(d)
    if convention is BusinessDayConvention.PRECEDING:
        return _preceding(d)
    if convention is BusinessDayConvention.MODIFIED_FOLLOWING:
        following = _following(d)
        if following.month != d.month:
            return _preceding(d)
        return following
    raise ValueError(f"Unknown business day convention: {convention}")  # pragma: no cover


def _following(d: date) -> date:
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def _preceding(d: date) -> date:
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def add_months(d: date, months: int) -> date:
    """Add ``months`` to ``d``, clamping the day to the target month's length."""
    total_months = d.month - 1 + months
    year = d.year + total_months // 12
    month = total_months % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
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


def generate_schedule_dates(issue_date: date, maturity_date: date, frequency: Frequency) -> list[date]:
    """Generate unadjusted accrual-boundary dates, stepping backward from maturity.

    Returns ``n + 1`` dates for ``n`` periods: the first is always
    ``issue_date`` and the last is always ``maturity_date``. Any stub period
    (when the issue-to-maturity span isn't an exact multiple of the coupon
    step) falls at the front of the schedule.
    """
    if issue_date >= maturity_date:
        raise ValueError("issue_date must be before maturity_date")

    step = frequency.months_between_payments
    dates = [maturity_date]
    current = maturity_date
    while True:
        current = add_months(current, -step)
        if current <= issue_date:
            break
        dates.append(current)
    dates.append(issue_date)
    return sorted(set(dates))


def generate_schedule(
    issue_date: date,
    maturity_date: date,
    frequency: Frequency,
    business_day_convention: BusinessDayConvention = BusinessDayConvention.FOLLOWING,
) -> list[SchedulePeriod]:
    """Generate the full list of accrual/payment periods for a coupon bond."""
    dates = generate_schedule_dates(issue_date, maturity_date, frequency)
    periods = []
    for i in range(len(dates) - 1):
        start, end = dates[i], dates[i + 1]
        periods.append(
            SchedulePeriod(
                period_index=i,
                accrual_start=start,
                accrual_end=end,
                payment_date=adjust_business_day(end, business_day_convention),
            )
        )
    return periods
