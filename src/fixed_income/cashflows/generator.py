"""Cash-flow generation from a schedule.

Turns a list of :class:`~fixed_income.cashflows.schedule.SchedulePeriod`
into concrete, per-100-face cash amounts: coupon, principal repayment, and
the resulting remaining principal. Every :class:`CashFlow` is derived
deterministically from its inputs, so the same schedule and rate always
produce the same numbers — this is what makes the schedules testable.

Coupon sizing — regular periods vs. stubs
------------------------------------------

A *regular* fixed-rate coupon (one whose accrual span is exactly one nominal
step of the bond's own frequency, e.g. exactly 6 calendar months for a
semi-annual bond) is a fixed dollar amount, ``face_value * coupon_rate /
frequency`` — real bonds pay that flat amount regardless of how many actual
calendar days a given 6-month span happens to contain (182, 183, or 184).
Day-count conventions size *stub* periods (an irregular first period when
the bond's life isn't an exact multiple of its frequency) and compute
accrued interest between coupon dates — they do not resize a regular
coupon.

Passing ``frequency`` to :func:`generate_variable_rate_cashflows` opts into
this: regular periods get the flat amount, and only genuine stubs fall back
to day-count proration. Without it (the default), every period is
day-count-prorated — correct for money-market floating-rate notes, whose
coupon genuinely is ``rate * actual_days/360`` each period, but wrong for a
fixed-rate bond's regular coupons.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..conventions.calendar import WEEKEND_ONLY as _WEEKEND_ONLY
from ..conventions.calendar import Calendar as _Calendar
from ..conventions.day_count import DayCountConvention, ScheduleContext
from ..conventions.frequency import Frequency
from .schedule import BusinessDayConvention as _BusinessDayConvention
from .schedule import SchedulePeriod, add_months, adjust_business_day


@dataclass(frozen=True)
class CashFlow:
    """A single cash flow paid on ``payment_date``.

    Attributes:
        period_index: Index of the originating accrual period.
        accrual_start: Unadjusted accrual period start.
        accrual_end: Unadjusted accrual period end.
        payment_date: Business-day-adjusted payment date.
        coupon: Interest amount paid, per the bond's face-value basis.
        principal: Principal repaid on this date (0 except redemption/
            amortization/sink events).
        begin_principal: Outstanding principal at the start of the period.
        end_principal: Outstanding principal after this payment.
    """

    period_index: int
    accrual_start: date
    accrual_end: date
    payment_date: date
    coupon: float
    principal: float
    begin_principal: float
    end_principal: float

    @property
    def total(self) -> float:
        return self.coupon + self.principal


def _is_regular_period(period: SchedulePeriod, frequency: Frequency) -> bool:
    """Whether ``period`` spans exactly one nominal step of ``frequency``
    (as opposed to a stub, produced when the schedule's life isn't an exact
    multiple of the frequency's step)."""
    return add_months(period.accrual_start, frequency.months_between_payments) == period.accrual_end


def _coupon_amount(
    face_value: float,
    coupon_rate: float,
    period: SchedulePeriod,
    day_count: DayCountConvention,
    frequency: Frequency | None,
) -> float:
    if frequency is not None and _is_regular_period(period, frequency):
        return face_value * coupon_rate / frequency.periods_per_year
    context = None
    if frequency is not None:
        # The reference period for a stub is the *regular* nominal period it's
        # a fragment of, not the stub's own (shorter) bounds -- see
        # ScheduleContext's docstring. accrual_end is always a regular grid
        # date (schedules step backward from maturity), so it anchors the
        # reference period even when accrual_start is an irregular stub start.
        reference_start = add_months(period.accrual_end, -frequency.months_between_payments)
        context = ScheduleContext(reference_start, period.accrual_end, frequency)
    year_fraction = day_count.year_fraction(period.accrual_start, period.accrual_end, context)
    return face_value * coupon_rate * year_fraction


def generate_variable_rate_cashflows(
    face_value: float,
    coupon_rates: list[float],
    schedule: list[SchedulePeriod],
    day_count: DayCountConvention,
    frequency: Frequency | None = None,
) -> list[CashFlow]:
    """Cash flows for a non-amortizing ("bullet") bond with one coupon rate per period.

    A fixed-rate bond is the special case where every entry in
    ``coupon_rates`` is the same value; a floating-rate note supplies a
    different (reference rate + spread) per period. Principal stays at
    ``face_value`` until the final period, which repays it in full
    alongside the last coupon.

    ``frequency``, when given, sizes each *regular* period's coupon as the
    flat ``face_value * coupon_rate / frequency`` rather than day-count
    proration (see module docstring). Leave it ``None`` for a floating-rate
    note, whose coupon is genuinely day-count-accrued every period.
    """
    if len(coupon_rates) != len(schedule):
        raise ValueError(
            f"coupon_rates has {len(coupon_rates)} entries but schedule has {len(schedule)} periods"
        )

    cash_flows = []
    last_index = len(schedule) - 1
    for period, coupon_rate in zip(schedule, coupon_rates, strict=True):
        coupon = _coupon_amount(face_value, coupon_rate, period, day_count, frequency)
        is_final = period.period_index == last_index
        principal = face_value if is_final else 0.0
        cash_flows.append(
            CashFlow(
                period_index=period.period_index,
                accrual_start=period.accrual_start,
                accrual_end=period.accrual_end,
                payment_date=period.payment_date,
                coupon=coupon,
                principal=principal,
                begin_principal=face_value,
                end_principal=face_value - principal,
            )
        )
    return cash_flows


def generate_bullet_cashflows(
    face_value: float,
    coupon_rate: float,
    schedule: list[SchedulePeriod],
    day_count: DayCountConvention,
    frequency: Frequency | None = None,
) -> list[CashFlow]:
    """Cash flows for a non-amortizing ("bullet") fixed-rate bond.

    Principal stays at ``face_value`` until the final period, which repays
    it in full alongside the last coupon. See
    :func:`generate_variable_rate_cashflows` for ``frequency``.
    """
    return generate_variable_rate_cashflows(
        face_value, [coupon_rate] * len(schedule), schedule, day_count, frequency
    )


def generate_zero_coupon_cashflow(
    face_value: float,
    issue_date: date,
    maturity_date: date,
    business_day_convention: _BusinessDayConvention = _BusinessDayConvention.FOLLOWING,
    calendar: _Calendar = _WEEKEND_ONLY,
) -> list[CashFlow]:
    """A single redemption cash flow at maturity — no periodic coupons."""
    payment_date = adjust_business_day(maturity_date, business_day_convention, calendar)
    return [
        CashFlow(
            period_index=0,
            accrual_start=issue_date,
            accrual_end=maturity_date,
            payment_date=payment_date,
            coupon=0.0,
            principal=face_value,
            begin_principal=face_value,
            end_principal=0.0,
        )
    ]


def cash_flows_after(cash_flows: list[CashFlow], settlement_date: date) -> list[CashFlow]:
    """Cash flows with ``payment_date`` strictly after ``settlement_date``."""
    return [cf for cf in cash_flows if cf.payment_date > settlement_date]
