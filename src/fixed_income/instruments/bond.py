"""Fixed-rate and zero-coupon bond instruments.

A :class:`Bond` is a pure data + derivation object: given its terms (face
value, coupon, dates, conventions) it derives its own payment schedule and
cash flows on demand. It holds no market data (price, yield) — that lives in
the ``pricing``/``risk`` layers, which consume a bond's cash flows rather
than reaching into its internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..cashflows.generator import (
    CashFlow,
    cash_flows_after,
    generate_bullet_cashflows,
    generate_zero_coupon_cashflow,
)
from ..cashflows.schedule import (
    BusinessDayConvention,
    SchedulePeriod,
    adjust_business_day,
    generate_schedule,
    generate_schedule_dates,
)
from ..conventions.calendar import WEEKEND_ONLY, Calendar
from ..conventions.day_count import Actual365Fixed, DayCountConvention
from ..conventions.frequency import Frequency


@dataclass
class Bond:
    """A standard fixed-rate, non-amortizing ("bullet") coupon bond.

    Attributes:
        face_value: Redemption value, per 100 par by convention.
        coupon_rate: Annual coupon rate as a decimal (e.g. ``0.05`` for 5%).
        issue_date: Date from which the first accrual period runs.
        maturity_date: Final redemption date.
        frequency: Coupon payments per year.
        day_count: Day-count convention used to size each coupon.
        business_day_convention: How payment dates are rolled onto business days.
        calendar: Which dates count as business days for that roll (weekend-only by default).
        first_coupon_date: When the first coupon is actually paid, for a bond
            whose terms say so explicitly. Must be a quasi-coupon date of the
            maturity-anchored grid. ``None`` (the default) pays the odd days
            between issue and the first grid date on that date — a short front
            stub. Naming a *later* grid date folds them into that coupon
            instead: a **long first coupon** (#19), which real issuance uses
            when a bond is sold too close to a coupon date for a stub payment
            to be practical.
    """

    face_value: float
    coupon_rate: float
    issue_date: date
    maturity_date: date
    frequency: Frequency = Frequency.SEMI_ANNUAL
    day_count: DayCountConvention = field(default_factory=Actual365Fixed)
    business_day_convention: BusinessDayConvention = BusinessDayConvention.FOLLOWING
    calendar: Calendar = WEEKEND_ONLY
    first_coupon_date: date | None = None

    def __post_init__(self) -> None:
        if self.face_value <= 0:
            raise ValueError("face_value must be positive")
        if self.issue_date >= self.maturity_date:
            raise ValueError("issue_date must be before maturity_date")
        if self.first_coupon_date is not None:
            # Validate eagerly: a first_coupon_date off the quasi-coupon grid is
            # a terms error, and finding out at the first cash_flows() call puts
            # the traceback far from the mistake. Only when one was given, so a
            # bond that doesn't use the feature builds no schedule here.
            generate_schedule_dates(
                self.issue_date, self.maturity_date, self.frequency, self.first_coupon_date
            )

    def schedule(self) -> list[SchedulePeriod]:
        return generate_schedule(
            self.issue_date,
            self.maturity_date,
            self.frequency,
            self.business_day_convention,
            self.calendar,
            self.first_coupon_date,
        )

    def cash_flows(self) -> list[CashFlow]:
        """Full cash-flow list from issue to maturity."""
        return generate_bullet_cashflows(
            self.face_value, self.coupon_rate, self.schedule(), self.day_count, self.frequency
        )

    def cash_flows_after(self, settlement_date: date) -> list[CashFlow]:
        """Cash flows still owed as of ``settlement_date`` (payment date strictly after it)."""
        return cash_flows_after(self.cash_flows(), settlement_date)

    def previous_coupon_date(self, settlement_date: date) -> date:
        """Accrual start of the period containing ``settlement_date``
        (or issue date if before the first period)."""
        for period in self.schedule():
            if period.accrual_start <= settlement_date < period.accrual_end:
                return period.accrual_start
        if settlement_date < self.issue_date:
            return self.issue_date
        return self.maturity_date

    def next_coupon_date(self, settlement_date: date) -> date:
        """Accrual end (unadjusted) of the period containing ``settlement_date``."""
        for period in self.schedule():
            if period.accrual_start <= settlement_date < period.accrual_end:
                return period.accrual_end
        return self.maturity_date


@dataclass
class ZeroCouponBond:
    """A zero-coupon bond: a single redemption payment at maturity, no periodic coupons.

    Deliberately *not* a :class:`Bond` subclass: a zero-coupon bond has no
    coupon rate to configure, and inheriting from ``Bond`` used to mean
    accepting a ``coupon_rate`` constructor argument and silently discarding
    it — a Liskov substitution violation (issue #7). This is a sibling class
    under the same informal contract (``schedule()``, ``cash_flows()``,
    ``cash_flows_after()``, ``previous_coupon_date()``, ``next_coupon_date()``,
    plus the ``face_value``/``issue_date``/``maturity_date``/``day_count``
    attributes) that code consuming either type relies on structurally;
    formalizing that contract as a ``typing.Protocol`` is tracked separately
    in #20.

    ``coupon_rate`` is exposed as a fixed ``0.0`` attribute (not a
    constructor parameter) for code that reads it generically alongside
    :class:`Bond`. ``frequency`` is retained only as the compounding-frequency
    assumption used when quoting a yield to maturity on a street/periodic
    basis (see :mod:`fixed_income.pricing.yield_convention`).
    """

    face_value: float
    issue_date: date
    maturity_date: date
    frequency: Frequency = Frequency.SEMI_ANNUAL
    day_count: DayCountConvention = field(default_factory=Actual365Fixed)
    business_day_convention: BusinessDayConvention = BusinessDayConvention.FOLLOWING
    calendar: Calendar = WEEKEND_ONLY
    coupon_rate: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        if self.face_value <= 0:
            raise ValueError("face_value must be positive")
        if self.issue_date >= self.maturity_date:
            raise ValueError("issue_date must be before maturity_date")

    def schedule(self) -> list[SchedulePeriod]:
        return [
            SchedulePeriod(
                period_index=0,
                accrual_start=self.issue_date,
                accrual_end=self.maturity_date,
                payment_date=adjust_business_day(
                    self.maturity_date, self.business_day_convention, self.calendar
                ),
            )
        ]

    def cash_flows(self) -> list[CashFlow]:
        return generate_zero_coupon_cashflow(
            self.face_value,
            self.issue_date,
            self.maturity_date,
            self.business_day_convention,
            self.calendar,
        )

    def cash_flows_after(self, settlement_date: date) -> list[CashFlow]:
        """Cash flows still owed as of ``settlement_date`` (payment date strictly after it)."""
        return cash_flows_after(self.cash_flows(), settlement_date)

    def previous_coupon_date(self, settlement_date: date) -> date:
        """Issue date: a zero-coupon bond's single period never resets."""
        return self.issue_date

    def next_coupon_date(self, settlement_date: date) -> date:
        """Maturity date: a zero-coupon bond's single period ends at redemption."""
        return self.maturity_date
