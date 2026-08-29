"""Convexity: the second-order price sensitivity to yield.

``Convexity = (1/P) * d^2P/dy^2``

For a flat yield ``y`` with ``m`` compounding periods per year (``m = 1``
under annual compounding), discounting each cash flow with
``(1 + y/m)^(-m*t)`` gives the closed form:

``Convexity = sum(PV_i * t_i * (t_i + 1/m)) / (P * (1 + y/m)^2)``

and under continuous compounding (``exp(-y*t)``) it simplifies to:

``Convexity = sum(PV_i * t_i^2) / P``

Both are implemented directly (no finite-difference approximation), so
convexity is exact for any deterministic cash-flow list discounted at a
flat yield.
"""

from __future__ import annotations

from datetime import date

from ..cashflows.generator import CashFlow, cash_flows_after
from ..conventions.day_count import DayCountConvention
from ..pricing.yield_convention import CompoundingConvention, YieldConvention


def convexity(
    cash_flows: list[CashFlow],
    settlement_date: date,
    y: float,
    yield_convention: YieldConvention,
    day_count: DayCountConvention,
) -> float:
    """Convexity of ``cash_flows`` discounted at flat yield ``y``, in years^2."""
    is_continuous = yield_convention.compounding is CompoundingConvention.CONTINUOUS
    m = 1 if yield_convention.compounding is CompoundingConvention.ANNUAL else yield_convention.periods_per_year

    pv_total = 0.0
    weighted = 0.0
    for cf in cash_flows_after(cash_flows, settlement_date):
        t = day_count.year_fraction(settlement_date, cf.payment_date)
        pv = cf.total * yield_convention.discount_factor(y, t)
        pv_total += pv
        weighted += pv * (t * t if is_continuous else t * (t + 1.0 / m))

    if pv_total == 0:
        raise ValueError("Cannot compute convexity: present value of cash flows is zero")

    if is_continuous:
        return weighted / pv_total
    return weighted / (pv_total * (1.0 + y / m) ** 2)


__all__ = ["convexity"]
