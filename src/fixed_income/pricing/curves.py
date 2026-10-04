"""A minimal yield-curve representation.

V1 deliberately avoids bootstrapping machinery: a :class:`YieldCurve` is just
a set of ``(tenor, zero rate)`` points with an interpolation rule. It is
enough to discount a bond's cash flows off more than one point on the curve
without pretending to be a full curve-construction framework.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from ..cashflows.generator import CashFlow
from ..conventions.day_count import DayCountConvention
from .present_value import present_value
from .yield_convention import CompoundingConvention, YieldConvention


class Interpolation(str, Enum):
    LINEAR = "linear"
    LOG_LINEAR = "log_linear"
    FLAT = "flat"


@dataclass(frozen=True)
class YieldCurve:
    """A zero-rate curve.

    Attributes:
        tenors: Tenors in years, strictly increasing (no duplicates) and
            non-negative — a negative tenor has no market meaning, and a
            repeated tenor makes interpolation between it and itself ambiguous.
        zero_rates: Zero (spot) rates as decimals, one per tenor.
        compounding: Compounding convention the zero rates are quoted under.
        interpolation: Interpolation rule between pillar points. Outside the
            pillar range, the curve extrapolates flat (holds the nearest
            endpoint rate constant). ``LOG_LINEAR`` interpolates the natural
            log of the *discount factor* linearly between the bracketing
            pillars (standard curve practice), and reports :meth:`zero_rate`
            as the rate implied by that interpolated discount factor. Because
            a discount factor is positive by construction, this places no
            positivity requirement on the zero rate itself — negative rates
            (EUR/JPY-style regimes) interpolate fine.
    """

    tenors: tuple[float, ...]
    zero_rates: tuple[float, ...]
    compounding: CompoundingConvention = CompoundingConvention.ANNUAL
    interpolation: Interpolation = Interpolation.LINEAR
    _yield_convention: YieldConvention = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if len(self.tenors) != len(self.zero_rates):
            raise ValueError("tenors and zero_rates must have the same length")
        if len(self.tenors) == 0:
            raise ValueError("YieldCurve requires at least one pillar point")
        if any(t1 <= t0 for t0, t1 in zip(self.tenors, self.tenors[1:], strict=False)):
            raise ValueError("tenors must be strictly increasing, with no duplicates")
        if self.tenors[0] < 0:
            raise ValueError("tenors must be non-negative")
        object.__setattr__(self, "_yield_convention", YieldConvention(compounding=self.compounding))

    def zero_rate(self, t: float) -> float:
        """Interpolated (or flat-extrapolated) zero rate at tenor ``t`` years.

        For ``LOG_LINEAR`` this is the rate *implied* by the discount factor
        obtained from interpolating ``ln(DF)`` linearly between the bracketing
        pillars — not a log-space interpolation of the rate itself.
        """
        tenors, rates = self.tenors, self.zero_rates
        if t <= tenors[0]:
            return rates[0]
        if t >= tenors[-1]:
            return rates[-1]

        t0, t1, r0, r1, weight = self._bracket(t)
        if self.interpolation is Interpolation.FLAT:
            return r0
        if self.interpolation is Interpolation.LOG_LINEAR:
            df = self._log_linear_discount_factor(t0, t1, r0, r1, weight)
            return self._rate_from_discount_factor(df, t)
        return r0 + weight * (r1 - r0)

    def discount_factor(self, t: float) -> float:
        """Discount factor at tenor ``t`` years.

        For ``LOG_LINEAR`` the discount factor is the primary interpolated
        quantity (``ln(DF)`` linear between pillars); for every other mode it
        is derived from the interpolated :meth:`zero_rate`. Outside the pillar
        range the curve extrapolates flat in the rate, so the discount factor
        there is ``convention.discount_factor(endpoint_rate, t)``.
        """
        tenors = self.tenors
        if self.interpolation is Interpolation.LOG_LINEAR and tenors[0] < t < tenors[-1]:
            t0, t1, r0, r1, weight = self._bracket(t)
            return self._log_linear_discount_factor(t0, t1, r0, r1, weight)
        r = self.zero_rate(t)
        return self._yield_convention.discount_factor(r, t)

    def _bracket(self, t: float) -> tuple[float, float, float, float, float]:
        """The pillars bracketing an interior ``t`` and its interpolation weight."""
        tenors, rates = self.tenors, self.zero_rates
        for i in range(len(tenors) - 1):
            t0, t1 = tenors[i], tenors[i + 1]
            if t0 <= t <= t1:
                return t0, t1, rates[i], rates[i + 1], (t - t0) / (t1 - t0)
        raise AssertionError("unreachable")  # pragma: no cover

    def _log_linear_discount_factor(
        self, t0: float, t1: float, r0: float, r1: float, weight: float
    ) -> float:
        """Discount factor from linearly interpolating ``ln(DF)`` between pillars.

        The pillar discount factors are always positive (a discount factor is
        positive by construction), so ``ln`` is always defined — the zero rates
        themselves may be negative.
        """
        conv = self._yield_convention
        ln_df0 = math.log(conv.discount_factor(r0, t0))
        ln_df1 = math.log(conv.discount_factor(r1, t1))
        return math.exp((1.0 - weight) * ln_df0 + weight * ln_df1)

    def _rate_from_discount_factor(self, df: float, t: float) -> float:
        """Invert :meth:`YieldConvention.discount_factor`: the zero rate that,
        under this curve's compounding, produces discount factor ``df`` at
        tenor ``t``. Interior ``t`` is always strictly positive here."""
        compounding = self.compounding
        if compounding is CompoundingConvention.CONTINUOUS:
            return -math.log(df) / t
        if compounding is CompoundingConvention.ANNUAL:
            return df ** (-1.0 / t) - 1.0
        m = self._yield_convention.periods_per_year
        return m * (df ** (-1.0 / (m * t)) - 1.0)


def present_value_from_curve(
    cash_flows: list[CashFlow],
    settlement_date: date,
    curve: YieldCurve,
    day_count: DayCountConvention,
) -> float:
    """PV discounting each cash flow off the curve's zero rate for its own maturity."""
    return present_value(cash_flows, settlement_date, curve.discount_factor, day_count)
