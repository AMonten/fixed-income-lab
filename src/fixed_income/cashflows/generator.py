"""Cash-flow generation from a schedule.

Turns a list of :class:`~fixed_income.cashflows.schedule.SchedulePeriod`
into concrete, per-100-face cash amounts: coupon, principal repayment, and
the resulting remaining principal. Every :class:`CashFlow` is derived
deterministically from its inputs, so the same schedule and rate always
produce the same numbers — this is what makes the schedules testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..conventions.day_count import DayCountConvention
from .schedule import SchedulePeriod, adjust_business_day
from .schedule import BusinessDayConvention as _BusinessDayConvention


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


def generate_variable_rate_cashflows(
    face_value: float,
    coupon_rates: list[float],
    schedule: list[SchedulePeriod],
    day_count: DayCountConvention,
) -> list[CashFlow]:
    """Cash flows for a non-amortizing ("bullet") bond with one coupon rate per period.

    A fixed-rate bond is the special case where every entry in
    ``coupon_rates`` is the same value; a floating-rate note supplies a
    different (reference rate + spread) per period. Principal stays at
    ``face_value`` until the final period, which repays it in full
    alongside the last coupon.
    """
    if len(coupon_rates) != len(schedule):
        raise ValueError(
            f"coupon_rates has {len(coupon_rates)} entries but schedule has {len(schedule)} periods"
        )

    cash_flows = []
    last_index = len(schedule) - 1
    for period, coupon_rate in zip(schedule, coupon_rates):
        year_fraction = day_count.year_fraction(period.accrual_start, period.accrual_end)
        coupon = face_value * coupon_rate * year_fraction
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
) -> list[CashFlow]:
    """Cash flows for a non-amortizing ("bullet") fixed-rate bond.

    Principal stays at ``face_value`` until the final period, which repays
    it in full alongside the last coupon.
    """
    return generate_variable_rate_cashflows(face_value, [coupon_rate] * len(schedule), schedule, day_count)


def generate_zero_coupon_cashflow(
    face_value: float,
    issue_date: date,
    maturity_date: date,
    business_day_convention: _BusinessDayConvention = _BusinessDayConvention.FOLLOWING,
) -> list[CashFlow]:
    """A single redemption cash flow at maturity — no periodic coupons."""
    payment_date = adjust_business_day(maturity_date, business_day_convention)
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
