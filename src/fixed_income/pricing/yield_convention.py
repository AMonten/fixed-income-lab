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
- ``PERIODIC_SIMPLE_FRACTIONAL_PERIOD``: periodic compounding over whole
  coupon periods, but the *fractional* period from settlement to the next
  quasi-coupon date discounted at **simple** interest:
  ``(1 + y/m) ** -n / (1 + w * y / m)``, where ``w`` is that fraction and
  ``n`` the whole periods beyond it. This is the US Treasury's own formula for
  non-indexed notes and bonds — ``1 + (r/s)(i/2)`` in 31 CFR 356 App. B — and
  it applies to *any* settlement between coupon dates, not only to stubs. It
  coincides with ``PERIODIC`` exactly when settlement is on a coupon date
  (``w = 1``), and otherwise prices marginally differently: that difference is
  the whole of issue #61. Reach it through
  :meth:`YieldConvention.treasury_auction`.

Note that this last rule's discount function is **not** an exponential in
``t``, so the textbook ``macaulay / (1 + y/m)`` and the closed-form convexity
do not hold under it. Risk measures therefore ask the convention itself for its
discount sensitivities (:meth:`YieldConvention.discount_sensitivities`) rather
than assuming a shape.

Time convention — street vs. true yield
----------------------------------------

A quoted yield does not discount to the *actual* (business-day-adjusted)
payment date. The market convention (ICMA/street quasi-coupon pricing) counts
whole coupon periods from settlement, using each period's own *unadjusted*
accrual boundaries:

``t_k = (w + k) / m``

where ``k = 0, 1, 2, ...`` indexes the remaining cash flows in order, and
``w`` is the fraction of the *current* quasi-coupon period still
outstanding: days from settlement to the current period's unadjusted
``accrual_end``, over the days in the *regular* coupon period ending on that
date, both measured with the bond's day-count convention. For a regular
period that is simply its own length; for a short front stub it is the full
regular period the stub is a fragment of (SIFMA's ``DSC/E``, the ``r/s`` of
31 CFR 356 App. B, QuantLib's ISMA reference period) — never the stub's own
length, which would overstate how much of a period is left (#60). Every
subsequent cash flow simply adds one full period (``k``), regardless of that
period's actual calendar length — that is the entire point of quasi-coupon
counting: a coupon landing on a weekend, or a stub, never distorts the yield.

``k`` counts *quasi-coupon periods*, not cash flows. The two coincide for
every V1 schedule — one coupon per period — but not for a long first coupon
(#19), which skips a quasi-coupon date: its single payment sits ``w + 1``
periods out, not ``w``, and each later flow follows from there. Counting
flows instead would silently shorten the whole schedule by a period.

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
from ..cashflows.schedule import months_between, regular_period_start
from ..conventions.day_count import DayCountConvention
from ..conventions.frequency import Frequency


class CompoundingConvention(str, Enum):
    PERIODIC = "periodic"
    ANNUAL = "annual"
    CONTINUOUS = "continuous"
    PERIODIC_SIMPLE_FRACTIONAL_PERIOD = "periodic_simple_fractional_period"


def _split_fractional_period(t_years: float, m: int) -> tuple[int, float]:
    """Split ``m * t_years`` into ``(whole periods beyond the fractional one, w)``.

    ``w`` lands in ``(0, 1]``: a time of exactly ``k`` periods is read as
    ``k - 1`` whole periods plus a *full* fractional period, not as ``k`` whole
    periods plus nothing. That is the reading the convention needs — simple
    interest over one full period is ``1 + i/m``, which is also what compounding
    gives, so the two agree exactly on coupon dates and differ only in between.
    """
    periods = m * t_years
    whole = math.ceil(periods) - 1
    return whole, periods - whole


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
        if self.compounding is CompoundingConvention.PERIODIC_SIMPLE_FRACTIONAL_PERIOD:
            whole, w = _split_fractional_period(t_years, m)
            return (1.0 + y / m) ** (-whole) / (1.0 + w * y / m)
        return (1.0 + y / m) ** (-m * t_years)

    def discount_sensitivities(self, y: float, t_years: float) -> tuple[float, float]:
        """``(-D'/D, D''/D)`` for this convention's own discount factor ``D(y, t)``.

        Risk measures are weighted averages of these: modified duration is the
        PV-weighted mean of the first, convexity the PV-weighted mean of the
        second. Asking the convention for them — rather than letting ``risk/``
        branch on the compounding rule — is what keeps a convention whose
        discount function is *not* a clean exponential from being handed the
        closed form of one. For the three uniform rules these reduce exactly to
        the textbook expressions (``t / (1 + y/m)`` and ``t(t + 1/m) / (1 +
        y/m)**2`` for periodic, ``t`` and ``t**2`` for continuous).
        """
        if self.compounding is CompoundingConvention.CONTINUOUS:
            return t_years, t_years * t_years
        if self.compounding is CompoundingConvention.ANNUAL:
            u = 1.0 + y
            return t_years / u, t_years * (t_years + 1.0) / (u * u)
        m = self.periods_per_year
        u = 1.0 + y / m
        if self.compounding is CompoundingConvention.PERIODIC_SIMPLE_FRACTIONAL_PERIOD:
            # D = (1 + w*y/m)^-1 * (1 + y/m)^-n, so the log-derivatives add:
            # the simple-interest factor contributes (w/m)/(1 + w*y/m) and the
            # compounded tail (n/m)/(1 + y/m).
            n, w = _split_fractional_period(t_years, m)
            v = 1.0 + w * y / m
            first = (w / m) / v + (n / m) / u
            second = (
                2.0 * (w / m) ** 2 / (v * v)
                + 2.0 * (w / m) * (n / m) / (v * u)
                + n * (n + 1.0) / (m * m) / (u * u)
            )
            return first, second
        return t_years / u, t_years * (t_years + 1.0 / m) / (u * u)

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

    @classmethod
    def treasury_auction(cls, frequency: Frequency = Frequency.SEMI_ANNUAL) -> YieldConvention:
        """The US Treasury's own auction/settlement formula for non-indexed
        notes and bonds (31 CFR 356 App. B): street quasi-coupon timing, but the
        fractional period to the next coupon discounted at **simple** interest,
        ``1 + (r/s)(i/2)``, instead of compounded, ``(1 + i/2)**(r/s)``.

        An explicit, named choice for reconciling against Treasury-published
        prices — never the default. The street convention remains what "yield to
        maturity" means on a dealer screen, and the two agree exactly whenever
        settlement falls on a coupon date (issue #61).
        """
        return cls(
            compounding=CompoundingConvention.PERIODIC_SIMPLE_FRACTIONAL_PERIOD,
            periods_per_year=frequency.periods_per_year,
            time_convention=YieldTimeConvention.STREET,
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
        # No ScheduleContext: settlement to an arbitrary future payment date
        # can span many coupon periods, same reasoning as present_value().
        return [day_count.year_fraction(settlement_date, cf.payment_date) for cf in remaining]

    first = remaining[0]
    if len(remaining) == 1 and first.period_index == 0:
        # A single cash flow whose "period" spans the instrument's entire
        # life (e.g. a zero-coupon bond) isn't a real coupon period — there
        # is nothing to count quasi-coupon periods against.
        return [day_count.year_fraction(settlement_date, first.payment_date)]

    period_start = first.accrual_start
    next_quasi = first.accrual_end
    whole_periods = list(range(len(remaining)))
    if len(remaining) > 1:
        # Only the first period of a V1 schedule can be irregular (front stub
        # or long coupon), so the next one spans exactly one regular step.
        nxt = remaining[1]
        maturity = remaining[-1].accrual_end
        step = months_between(nxt.accrual_start, nxt.accrual_end)
        # The quasi-coupon date the *settlement* period runs to. Normally
        # that is the next cash flow's own accrual_end, but a long first
        # coupon (#19) skipped one or more quasi-coupon dates: those still
        # count as whole periods in the exponent, so step back to the first
        # grid date after settlement instead of assuming one flow per period.
        while True:
            previous = regular_period_start(next_quasi, maturity, step)
            if previous <= settlement_date:
                break
            next_quasi = previous
        period_start = regular_period_start(next_quasi, maturity, step)
        whole_periods = [months_between(next_quasi, cf.accrual_end) // step for cf in remaining]
    period_days = day_count.day_count(period_start, next_quasi)
    if period_days <= 0:
        raise ValueError(
            f"Cannot compute street time fractions: non-positive period length "
            f"({period_start} to {next_quasi})"
        )
    remaining_days = day_count.day_count(settlement_date, next_quasi)
    w = remaining_days / period_days
    m = yield_convention.periods_per_year
    return [(w + k) / m for k in whole_periods]
