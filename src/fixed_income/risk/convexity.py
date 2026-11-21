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

Rather than reproduce those closed forms here and branch on the compounding
rule, this module asks the yield convention for each cash flow's own
``D''/D`` (:meth:`~fixed_income.pricing.yield_convention.YieldConvention.discount_sensitivities`)
and takes the PV-weighted mean. That is the same number for the uniform rules
above, and it stays exact under
``PERIODIC_SIMPLE_FRACTIONAL_PERIOD`` (#61), whose discount function is not an
exponential in ``t`` and therefore satisfies neither closed form.
"""

from __future__ import annotations

from datetime import date

from ..cashflows.generator import CashFlow, cash_flows_after
from ..conventions.day_count import DayCountConvention
from ..pricing.yield_convention import YieldConvention, yield_time_fractions


def convexity(
    cash_flows: list[CashFlow],
    settlement_date: date,
    y: float,
    yield_convention: YieldConvention,
    day_count: DayCountConvention,
) -> float:
    """Convexity of ``cash_flows`` discounted at flat yield ``y``, in years^2.

    Times each cash flow per ``yield_convention.time_convention`` — street
    quasi-coupon counting by default, matching how ``y`` itself is quoted.
    """
    remaining = cash_flows_after(cash_flows, settlement_date)
    times = yield_time_fractions(cash_flows, settlement_date, day_count, yield_convention)
    pv_total = 0.0
    weighted = 0.0
    for cf, t in zip(remaining, times, strict=True):
        pv = cf.total * yield_convention.discount_factor(y, t)
        _, second = yield_convention.discount_sensitivities(y, t)
        pv_total += pv
        weighted += pv * second

    if pv_total == 0:
        raise ValueError("Cannot compute convexity: present value of cash flows is zero")

    return weighted / pv_total


__all__ = ["convexity"]
