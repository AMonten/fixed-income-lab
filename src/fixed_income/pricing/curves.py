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
        tenors: Tenors in years, strictly increasing.
        zero_rates: Zero (spot) rates as decimals, one per tenor.
        compounding: Compounding convention the zero rates are quoted under.
        interpolation: Interpolation rule between pillar points. Outside the
            pillar range, the curve extrapolates flat (holds the nearest
            endpoint rate constant). ``LOG_LINEAR`` requires every pillar
            rate bracketing a query to be strictly positive, since it
            interpolates in log-rate space; it raises :class:`ValueError`
            for a zero or negative bracketing rate.
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
        if list(self.tenors) != sorted(self.tenors):
            raise ValueError("tenors must be strictly increasing")
        object.__setattr__(self, "_yield_convention", YieldConvention(compounding=self.compounding))

    def zero_rate(self, t: float) -> float:
        """Interpolated (or flat-extrapolated) zero rate at tenor ``t`` years."""
        tenors, rates = self.tenors, self.zero_rates
        if t <= tenors[0]:
            return rates[0]
        if t >= tenors[-1]:
            return rates[-1]

        for i in range(len(tenors) - 1):
            t0, t1 = tenors[i], tenors[i + 1]
            if t0 <= t <= t1:
                r0, r1 = rates[i], rates[i + 1]
                weight = (t - t0) / (t1 - t0)
                if self.interpolation is Interpolation.FLAT:
                    return r0
                if self.interpolation is Interpolation.LOG_LINEAR:
                    if r0 <= 0 or r1 <= 0:
                        raise ValueError(
                            "LOG_LINEAR interpolation requires strictly positive zero rates; "
                            f"got {r0!r} at tenor {t0} and {r1!r} at tenor {t1}"
                        )
                    return math.exp(math.log(r0) * (1 - weight) + math.log(r1) * weight)
                return r0 + weight * (r1 - r0)
        raise AssertionError("unreachable")  # pragma: no cover

    def discount_factor(self, t: float) -> float:
        r = self.zero_rate(t)
        return self._yield_convention.discount_factor(r, t)


def present_value_from_curve(
    cash_flows: list[CashFlow],
    settlement_date: date,
    curve: YieldCurve,
    day_count: DayCountConvention,
) -> float:
    """PV discounting each cash flow off the curve's zero rate for its own maturity."""
    return present_value(cash_flows, settlement_date, curve.discount_factor, day_count)
