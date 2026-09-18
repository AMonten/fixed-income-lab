"""Yield/compounding conventions.

A yield is meaningless without a statement of *how* it compounds, and,
separately, *which dates* its discount exponents are measured against. This
module makes both assumptions explicit so pricing, YTM solving, and duration
all discount consistently.

Compounding
-----------

Given a yield ``y`` (decimal, e.g. ``0.045`` for 4.5%) and a time to a cash
flow ``t`` measured in years, the discount factor is:

- ``PERIODIC`` (street/bond-equivalent convention): ``(1 + y / m) ** -(m * t)``
  where ``m`` is the number of compounding periods per year. This is the
  standard US bond-market convention (semi-annual compounding for most
  bonds).
- ``ANNUAL``: ``(1 + y) ** -t``.
- ``CONTINUOUS``: ``exp(-y * t)``.

Time convention — street vs. true yield
----------------------------------------

A quoted yield does not discount to the *actual* (business-day-adjusted)
payment date. The market convention (ICMA/street quasi-coupon pricing) counts
whole coupon periods from settlement, using each period's own *unadjusted*
accrual boundaries:

``t_k = (w + k) / m``

where ``k = 0, 1, 2, ...`` indexes the remaining cash flows in order, and
``w`` is the fraction of the *current* coupon period (the one containing
settlement) still outstanding: days from settlement to that period's
unadjusted ``accrual_end``, over the period's own length, both measured with
the bond's day-count convention. Every subsequent cash flow simply adds one
full period (``k``), regardless of that period's actual calendar length —
that is the entire point of quasi-coupon counting: a coupon landing on a
weekend, or a short/long stub, never distorts the yield.

``STREET`` is the default and should stay the default: it is what "yield to
maturity" means on a dealer screen. ``TRUE`` discounts to the actual
(adjusted) payment date instead — a deliberate, explicit choice for a
specific reconciliation need, never a silent fallback.

A cash-flow list with a single flow whose ``period_index`` is ``0`` (e.g. a
:class:`~fixed_income.instruments.bond.ZeroCouponBond`, whose one "period"
spans its entire life rather than a real ``1/m``-year coupon period) has no
coupon periodicity to count against; :func:`yield_time_fractions` falls back
to actual elapsed time for it even under ``STREET``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import Enum

from ..cashflows.generator import CashFlow, cash_flows_after
from ..conventions.day_count import DayCountConvention
from ..conventions.frequency import Frequency


class CompoundingConvention(str, Enum):
    PERIODIC = "periodic"
    ANNUAL = "annual"
    CONTINUOUS = "continuous"


class YieldTimeConvention(str, Enum):
    """Which dates a quoted yield's discount exponents are measured against."""

    STREET = "street"
    TRUE = "true"


@dataclass(frozen=True)
class YieldConvention:
    """How a yield-to-maturity compounds and is timed when discounting cash flows.

    Attributes:
        compounding: The compounding rule.
        periods_per_year: Compounding frequency for ``PERIODIC``, and the
            period-counting divisor for ``STREET`` timing regardless of
            compounding. Ignored by the discount formula itself for
            ``ANNUAL``/``CONTINUOUS``. Defaults to semi-annual, the standard
            US bond-market (street) convention.
        time_convention: Whether discount exponents count coupon periods
            (``STREET``, the default) or actual elapsed time to the adjusted
            payment date (``TRUE``, explicit opt-in only).
    """

    compounding: CompoundingConvention = CompoundingConvention.PERIODIC
    periods_per_year: int = Frequency.SEMI_ANNUAL.periods_per_year
    time_convention: YieldTimeConvention = YieldTimeConvention.STREET

    def discount_factor(self, y: float, t_years: float) -> float:
        """Discount factor for time ``t_years`` at yield ``y``."""
        if self.compounding is CompoundingConvention.CONTINUOUS:
            return math.exp(-y * t_years)
        if self.compounding is CompoundingConvention.ANNUAL:
            return (1.0 + y) ** (-t_years)
        m = self.periods_per_year
        return (1.0 + y / m) ** (-m * t_years)

    @classmethod
    def street(cls, frequency: Frequency = Frequency.SEMI_ANNUAL) -> YieldConvention:
        """The standard US bond-market ("street") convention: periodic
        compounding at the bond's own coupon frequency, discounting on
        unadjusted quasi-coupon periods rather than adjusted payment dates."""
        return cls(
            compounding=CompoundingConvention.PERIODIC,
            periods_per_year=frequency.periods_per_year,
            time_convention=YieldTimeConvention.STREET,
        )

    @classmethod
    def true_yield(cls, frequency: Frequency = Frequency.SEMI_ANNUAL) -> YieldConvention:
        """Periodic compounding discounting to the actual (business-day-adjusted)
        payment date, instead of counting unadjusted coupon periods. An explicit,
        named choice for reconciliation against a system that quotes this way —
        never the default."""
        return cls(
            compounding=CompoundingConvention.PERIODIC,
            periods_per_year=frequency.periods_per_year,
            time_convention=YieldTimeConvention.TRUE,
        )


def yield_time_fractions(
    cash_flows: list[CashFlow],
    settlement_date: date,
    day_count: DayCountConvention,
    yield_convention: YieldConvention,
) -> list[float]:
    """Time to each remaining cash flow, in years, per ``yield_convention.time_convention``.

    Returns one fraction per cash flow in ``cash_flows_after(cash_flows, settlement_date)``,
    in the same order.
    """
    remaining = cash_flows_after(cash_flows, settlement_date)
    if not remaining:
        return []

    if yield_convention.time_convention is YieldTimeConvention.TRUE:
        return [day_count.year_fraction(settlement_date, cf.payment_date) for cf in remaining]

    first = remaining[0]
    if len(remaining) == 1 and first.period_index == 0:
        # A single cash flow whose "period" spans the instrument's entire
        # life (e.g. a zero-coupon bond) isn't a real coupon period — there
        # is nothing to count quasi-coupon periods against.
        return [day_count.year_fraction(settlement_date, first.payment_date)]

    period_days = day_count.day_count(first.accrual_start, first.accrual_end)
    if period_days <= 0:
        raise ValueError(
            f"Cannot compute street time fractions: non-positive period length "
            f"({first.accrual_start} to {first.accrual_end})"
        )
    remaining_days = day_count.day_count(settlement_date, first.accrual_end)
    w = remaining_days / period_days
    m = yield_convention.periods_per_year
    return [(w + k) / m for k in range(len(remaining))]
