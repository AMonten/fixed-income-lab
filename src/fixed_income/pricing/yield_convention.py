"""Yield/compounding conventions.

A yield is meaningless without a statement of *how* it compounds. This module
makes that assumption explicit so pricing, YTM solving, and duration all
discount consistently.

Given a yield ``y`` (decimal, e.g. ``0.045`` for 4.5%) and a time to a cash
flow ``t`` measured in years, the discount factor is:

- ``PERIODIC`` (street/bond-equivalent convention): ``(1 + y / m) ** -(m * t)``
  where ``m`` is the number of compounding periods per year. This is the
  standard US bond-market convention (semi-annual compounding for most
  bonds).
- ``ANNUAL``: ``(1 + y) ** -t``.
- ``CONTINUOUS``: ``exp(-y * t)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from ..conventions.frequency import Frequency


class CompoundingConvention(str, Enum):
    PERIODIC = "periodic"
    ANNUAL = "annual"
    CONTINUOUS = "continuous"


@dataclass(frozen=True)
class YieldConvention:
    """How a yield-to-maturity compounds when used to discount cash flows.

    Attributes:
        compounding: The compounding rule.
        periods_per_year: Compounding frequency for ``PERIODIC``. Ignored for
            ``ANNUAL`` and ``CONTINUOUS``. Defaults to semi-annual, the
            standard US bond-market (street) convention.
    """

    compounding: CompoundingConvention = CompoundingConvention.PERIODIC
    periods_per_year: int = Frequency.SEMI_ANNUAL.periods_per_year

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
        compounding at the bond's own coupon frequency."""
        return cls(compounding=CompoundingConvention.PERIODIC, periods_per_year=frequency.periods_per_year)
