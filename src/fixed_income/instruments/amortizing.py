"""Amortizing and sinkable securities: instruments whose principal declines over time.

Two ways to describe how principal comes down are supported, both behind
the common :class:`AmortizationPlan` interface so :class:`AmortizingBond`
never needs to know which one it's using:

- An explicit list of principal repayment amounts, one per period. This
  splits into two plan types with different, *enforced* invariants rather
  than one type with an implicit, unchecked one (see issue #7 / ROADMAP
  0.5 for why): :class:`FullyAmortizingPlan` (repayments alone must sum to
  the original face -- "plain" amortizing bonds, e.g. level-principal, and
  sinkable bonds with no balloon) and :class:`PartialAmortizationPlan`
  (repayments plus an explicit ``balloon`` due at the final period sum to
  the original face -- a structure that partially amortizes and repays the
  rest as a lump sum at maturity).
- :class:`FactorAmortizationPlan` — principal paydown derived from a
  :class:`FactorHistory` of ``(date, factor)`` observations, the way
  pass-through pools (and, later, MBS/CMO tranches) report paydown.

Either way, :meth:`AmortizingBond.amortization_schedule` produces the same
shape of output: beginning principal, interest, principal repayment, and
ending principal per period.

Over-amortizing (repayments driving outstanding principal below zero) always
raises rather than silently clamping to zero -- see :func:`_outstanding_after`.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from ..cashflows.generator import CashFlow, cash_flows_after
from ..cashflows.schedule import BusinessDayConvention, SchedulePeriod, generate_schedule
from ..conventions.day_count import Actual365Fixed, DayCountConvention
from ..conventions.frequency import Frequency

# Tolerance for float summation noise, per 100 of face value -- not a fudge
# factor for bad data. A validated repayment schedule (Sigma == face, checked
# below) can still land a few ULPs short of exactly zero outstanding at the
# final period purely from float addition order; that noise is clamped to
# zero. Anything past this tolerance is a real over-amortization and raises.
_TOL = 1e-6


class AmortizationPlan(ABC):
    """Determines outstanding principal after each period of an amortizing bond."""

    @abstractmethod
    def outstanding_after(
        self, period_index: int, schedule: list[SchedulePeriod], original_face: float
    ) -> float:
        """Outstanding principal immediately after ``period_index``'s payment."""


def _validate_repayment_count(
    principal_repayments: tuple[float, ...], schedule: list[SchedulePeriod]
) -> None:
    if len(principal_repayments) != len(schedule):
        raise ValueError(
            f"principal_repayments has {len(principal_repayments)} entries but "
            f"schedule has {len(schedule)} periods"
        )


def _outstanding_after(repaid_so_far: float, period_index: int, original_face: float) -> float:
    outstanding = original_face - repaid_so_far
    if outstanding < -_TOL:
        raise ValueError(
            f"Over-amortized: cumulative principal repayment through period {period_index} "
            f"({repaid_so_far}) exceeds original_face ({original_face})"
        )
    return max(outstanding, 0.0)


@dataclass(frozen=True)
class FullyAmortizingPlan(AmortizationPlan):
    """Principal repayment specified explicitly, one amount per period.
    ``principal_repayments`` alone must sum to ``original_face`` -- enforced,
    not assumed. Use :class:`PartialAmortizationPlan` for a structure with an
    explicit balloon due at maturity instead.
    """

    principal_repayments: tuple[float, ...]

    def outstanding_after(
        self, period_index: int, schedule: list[SchedulePeriod], original_face: float
    ) -> float:
        _validate_repayment_count(self.principal_repayments, schedule)
        total = sum(self.principal_repayments)
        if not math.isclose(total, original_face, rel_tol=1e-9, abs_tol=_TOL):
            raise ValueError(
                f"FullyAmortizingPlan requires principal_repayments to sum to original_face "
                f"({original_face}); got {total}. Use PartialAmortizationPlan for a structure "
                f"with a balloon due at maturity."
            )
        repaid_so_far = sum(self.principal_repayments[: period_index + 1])
        return _outstanding_after(repaid_so_far, period_index, original_face)


@dataclass(frozen=True)
class PartialAmortizationPlan(AmortizationPlan):
    """Principal repayment specified explicitly per period, plus an explicit
    ``balloon`` repaid in full at the final period -- e.g. ``principal_repayments
    = (20.0, 20.0, 20.0)`` with ``balloon=40.0`` on a face of 100: each period
    repays its level 20, and the final period repays an additional 40 on top.

    Unlike :class:`FullyAmortizingPlan`, ``principal_repayments`` alone need
    not sum to ``original_face`` -- the terminal balance is this plan's
    explicit ``balloon``, not an implicit leftover the caller has to
    remember to zero out. ``principal_repayments`` plus ``balloon`` together
    must still sum to ``original_face``: this is a partial-amortization-then-
    balloon structure, not a way to under- or over-redeem a bond.
    """

    principal_repayments: tuple[float, ...]
    balloon: float

    def outstanding_after(
        self, period_index: int, schedule: list[SchedulePeriod], original_face: float
    ) -> float:
        _validate_repayment_count(self.principal_repayments, schedule)
        total = sum(self.principal_repayments) + self.balloon
        if not math.isclose(total, original_face, rel_tol=1e-9, abs_tol=_TOL):
            raise ValueError(
                f"PartialAmortizationPlan requires principal_repayments plus balloon to sum "
                f"to original_face ({original_face}); got {total}"
            )
        repaid_so_far = sum(self.principal_repayments[: period_index + 1])
        if period_index == len(schedule) - 1:
            repaid_so_far += self.balloon
        return _outstanding_after(repaid_so_far, period_index, original_face)


@dataclass(frozen=True)
class FactorObservation:
    """A single observed paydown factor. ``factor`` is in ``[0, 1]``: 1.0 means fully outstanding."""

    date: date
    factor: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.factor <= 1.0):
            raise ValueError(f"factor must be in [0, 1], got {self.factor}")


@dataclass
class FactorHistory:
    """A time series of paydown factors for a factor-based (pool) security.

    Attributes:
        original_face: Original face amount at issuance (factor == 1.0).
        observations: Known factor observations, in any order.
    """

    original_face: float
    observations: tuple[FactorObservation, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        self.observations = tuple(sorted(self.observations, key=lambda o: o.date))

    def factor_on(self, as_of: date) -> float:
        """Most recently observed factor on or before ``as_of``; ``1.0`` if none exists yet."""
        applicable = [o.factor for o in self.observations if o.date <= as_of]
        return applicable[-1] if applicable else 1.0

    def current_face_on(self, as_of: date) -> float:
        """Current Face = Original Face x Current Factor."""
        return self.original_face * self.factor_on(as_of)

    def paydown_on(self, as_of: date) -> float:
        return self.original_face - self.current_face_on(as_of)

    def percent_amortized_on(self, as_of: date) -> float:
        return 1.0 - self.factor_on(as_of)


@dataclass(frozen=True)
class FactorAmortizationPlan(AmortizationPlan):
    """Principal paydown derived from a :class:`FactorHistory`."""

    factor_history: FactorHistory

    def outstanding_after(
        self, period_index: int, schedule: list[SchedulePeriod], original_face: float
    ) -> float:
        period_end = schedule[period_index].accrual_end
        return self.factor_history.current_face_on(period_end)


@dataclass(frozen=True)
class AmortizationScheduleEntry:
    """One row of an amortization table."""

    period_index: int
    payment_date: date
    begin_principal: float
    interest: float
    principal_repayment: float
    end_principal: float

    @property
    def total_payment(self) -> float:
        return self.interest + self.principal_repayment


@dataclass
class AmortizingBond:
    """A bond whose principal amortizes over time per a pluggable :class:`AmortizationPlan`.

    Attributes:
        original_face: Face amount at issuance.
        coupon_rate: Annual coupon rate (decimal), applied to the
            *outstanding* (beginning-of-period) principal each period.
        issue_date: Date from which the first accrual period runs.
        maturity_date: Final scheduled date; the amortization plan should
            fully repay principal by this date.
        amortization: How principal comes down period by period.
        frequency: Coupon/amortization payments per year.
        day_count: Day-count convention used to size each period's interest.
        business_day_convention: How payment dates are rolled onto business days.
    """

    original_face: float
    coupon_rate: float
    issue_date: date
    maturity_date: date
    amortization: AmortizationPlan
    frequency: Frequency = Frequency.SEMI_ANNUAL
    day_count: DayCountConvention = field(default_factory=Actual365Fixed)
    business_day_convention: BusinessDayConvention = BusinessDayConvention.FOLLOWING

    def __post_init__(self) -> None:
        if self.original_face <= 0:
            raise ValueError("original_face must be positive")
        if self.issue_date >= self.maturity_date:
            raise ValueError("issue_date must be before maturity_date")

    @classmethod
    def with_level_principal(
        cls,
        original_face: float,
        coupon_rate: float,
        issue_date: date,
        maturity_date: date,
        frequency: Frequency = Frequency.SEMI_ANNUAL,
        day_count: DayCountConvention | None = None,
        business_day_convention: BusinessDayConvention = BusinessDayConvention.FOLLOWING,
    ) -> AmortizingBond:
        """Construct a bond that repays equal principal installments each period.

        The last installment absorbs any rounding remainder so principal
        reaches exactly zero at maturity.
        """
        dc = day_count or Actual365Fixed()
        schedule = generate_schedule(issue_date, maturity_date, frequency, business_day_convention)
        n = len(schedule)
        installment = original_face / n
        repayments = [installment] * n
        repayments[-1] = original_face - sum(repayments[:-1])
        plan = FullyAmortizingPlan(tuple(repayments))
        return cls(
            original_face, coupon_rate, issue_date, maturity_date, plan,
            frequency, dc, business_day_convention,
        )

    def schedule(self) -> list[SchedulePeriod]:
        return generate_schedule(
            self.issue_date, self.maturity_date, self.frequency, self.business_day_convention
        )

    def amortization_schedule(self) -> list[AmortizationScheduleEntry]:
        """The full Period / Beginning Principal / Interest / Principal Repayment / Ending Principal table."""
        schedule = self.schedule()
        entries = []
        begin = self.original_face
        for period in schedule:
            end = self.amortization.outstanding_after(period.period_index, schedule, self.original_face)
            principal_repayment = begin - end
            year_fraction = self.day_count.year_fraction(period.accrual_start, period.accrual_end)
            interest = begin * self.coupon_rate * year_fraction
            entries.append(
                AmortizationScheduleEntry(
                    period_index=period.period_index,
                    payment_date=period.payment_date,
                    begin_principal=begin,
                    interest=interest,
                    principal_repayment=principal_repayment,
                    end_principal=end,
                )
            )
            begin = end
        return entries

    def cash_flows(self) -> list[CashFlow]:
        schedule = self.schedule()
        entries = self.amortization_schedule()
        return [
            CashFlow(
                period_index=period.period_index,
                accrual_start=period.accrual_start,
                accrual_end=period.accrual_end,
                payment_date=period.payment_date,
                coupon=entry.interest,
                principal=entry.principal_repayment,
                begin_principal=entry.begin_principal,
                end_principal=entry.end_principal,
            )
            for period, entry in zip(schedule, entries, strict=True)
        ]

    def cash_flows_after(self, settlement_date: date) -> list[CashFlow]:
        return cash_flows_after(self.cash_flows(), settlement_date)

    @property
    def face_value(self) -> float:
        """Alias for ``original_face``, so amortizing bonds share a ``face_value``
        attribute with the other instrument types."""
        return self.original_face

    def outstanding_principal_on(self, as_of: date) -> float:
        """Outstanding principal as of ``as_of``, from the most recent payment on or before it."""
        entries = self.amortization_schedule()
        applicable = [e for e in entries if e.payment_date <= as_of]
        if not applicable:
            return self.original_face
        return applicable[-1].end_principal

    def current_factor(self, as_of: date) -> float:
        """Current Factor = outstanding principal / original face."""
        return self.outstanding_principal_on(as_of) / self.original_face

    def current_face(self, as_of: date) -> float:
        """Current Face = Original Face x Current Factor."""
        return self.outstanding_principal_on(as_of)

    def percent_amortized(self, as_of: date) -> float:
        return 1.0 - self.current_factor(as_of)
