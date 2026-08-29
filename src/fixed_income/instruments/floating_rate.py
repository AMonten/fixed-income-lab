"""Floating-rate notes (FRNs).

A floating-rate note pays a coupon that resets each period to a reference
rate plus a fixed spread:

``Coupon Rate = Reference Rate + Spread``

V1 does not implement a market-curve / forward-curve bootstrapping
framework. Instead, each period's reference rate is resolved from a
:class:`~fixed_income.instruments.rate_index.RateIndex`, which returns an
*observed* historical fixing when one exists and otherwise falls back to an
explicit *forward-rate assumption*. :meth:`FloatingRateNote.rate_provenance`
reports, per reset date, which of the two was used — so a caller never
mistakes an assumption for a market-observed rate.

Cash flows are generated with the same :func:`generate_variable_rate_cashflows`
engine used for fixed-rate bonds; a fixed-rate coupon is just the special
case where every period gets the same rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..cashflows.generator import CashFlow, cash_flows_after, generate_variable_rate_cashflows
from ..cashflows.schedule import BusinessDayConvention, SchedulePeriod, generate_schedule
from ..conventions.day_count import Actual360, DayCountConvention
from ..conventions.frequency import Frequency
from .rate_index import RateIndex


@dataclass
class FloatingRateNote:
    """A floating-rate note referencing a single :class:`RateIndex`.

    Attributes:
        face_value: Redemption value, per 100 par by convention.
        spread: Fixed spread over the reference rate, as a decimal (e.g. ``0.0025`` for 25bp).
        issue_date: Date from which the first accrual period runs.
        maturity_date: Final redemption date.
        rate_index: The reference rate (e.g. SOFR) driving each period's coupon.
        frequency: Coupon/reset payments per year. Quarterly is the common
            money-market convention.
        day_count: Day-count convention used to size each coupon. ACT/360
            is the common convention for FRNs referencing money-market rates.
        business_day_convention: How payment dates are rolled onto business days.
        reset_lag_days: Days before each period's accrual start that the
            reference rate is observed (a "lookback"). ``0`` means the
            reset is observed exactly on the accrual start date.
    """

    face_value: float
    spread: float
    issue_date: date
    maturity_date: date
    rate_index: RateIndex
    frequency: Frequency = Frequency.QUARTERLY
    day_count: DayCountConvention = field(default_factory=Actual360)
    business_day_convention: BusinessDayConvention = BusinessDayConvention.FOLLOWING
    reset_lag_days: int = 0

    def __post_init__(self) -> None:
        if self.face_value <= 0:
            raise ValueError("face_value must be positive")
        if self.issue_date >= self.maturity_date:
            raise ValueError("issue_date must be before maturity_date")
        if self.reset_lag_days < 0:
            raise ValueError("reset_lag_days must be non-negative")

    def schedule(self) -> list[SchedulePeriod]:
        return generate_schedule(
            self.issue_date, self.maturity_date, self.frequency, self.business_day_convention
        )

    def reset_date_for(self, period: SchedulePeriod) -> date:
        """The date the reference rate is observed for ``period``."""
        return period.accrual_start - timedelta(days=self.reset_lag_days)

    def reset_dates(self) -> list[date]:
        return [self.reset_date_for(p) for p in self.schedule()]

    def coupon_rate_for_period(self, period: SchedulePeriod) -> float:
        """Resolve this period's all-in coupon rate: floored reference rate + spread."""
        reference_rate = self.rate_index.rate_on(self.reset_date_for(period))
        reference_rate = self.rate_index.apply_floor(reference_rate)
        return reference_rate + self.spread

    def coupon_rates(self) -> list[float]:
        return [self.coupon_rate_for_period(p) for p in self.schedule()]

    def rate_provenance(self) -> list[tuple[date, bool]]:
        """Per reset date, whether the reference rate is an observed fixing (``True``)
        or a forward-rate assumption (``False``)."""
        return [(d, self.rate_index.is_observed(d)) for d in self.reset_dates()]

    def cash_flows(self) -> list[CashFlow]:
        schedule = self.schedule()
        rates = [self.coupon_rate_for_period(p) for p in schedule]
        return generate_variable_rate_cashflows(self.face_value, rates, schedule, self.day_count)

    def cash_flows_after(self, settlement_date: date) -> list[CashFlow]:
        return cash_flows_after(self.cash_flows(), settlement_date)
