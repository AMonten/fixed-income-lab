"""Duration and DV01 (PV01).

All functions here operate on a plain list of
:class:`~fixed_income.cashflows.generator.CashFlow` discounted at a single
flat yield — they make no assumption about *how* those cash flows were
generated, so the same code prices duration/DV01 for bullet, amortizing, and
(under a fixed forward-rate assumption) floating-rate cash flows alike.

Definitions
-----------

Macaulay duration
    The present-value-weighted average time to a security's cash flows:

    ``D_mac = sum(t_i * PV_i) / sum(PV_i)``

    where ``PV_i`` is the present value of cash flow ``i`` and ``t_i`` its
    time to payment in years.

Modified duration
    The percentage price sensitivity to a small parallel yield change:

    ``D_mod = -1/P * dP/dy``

    For periodic compounding with ``m`` periods per year,
    ``D_mod = D_mac / (1 + y/m)``; for annual compounding, ``D_mod = D_mac /
    (1 + y)``; for continuous compounding, ``D_mod = D_mac``.

DV01 / PV01
    The dollar price change for a one-basis-point (0.0001) move in yield,
    computed here by full repricing (central difference) rather than the
    ``D_mod * P * 0.0001`` approximation. Full repricing has its own
    truncation error, ``O(h^2) * P'''``, but it is several orders of
    magnitude smaller than the error the duration-based approximation makes
    at realistic convexity — not exact, just far more accurate — and it
    generalizes to any cash-flow list without needing a closed-form duration.
"""

from __future__ import annotations

from datetime import date

from ..cashflows.generator import CashFlow, cash_flows_after
from ..conventions.day_count import DayCountConvention
from ..pricing.yield_convention import CompoundingConvention, YieldConvention, yield_time_fractions
from ..pricing.yield_solver import price_from_yield

_BUMP = 1e-4  # one basis point


def macaulay_duration(
    cash_flows: list[CashFlow],
    settlement_date: date,
    y: float,
    yield_convention: YieldConvention,
    day_count: DayCountConvention,
) -> float:
    """Macaulay duration, in years.

    Times each cash flow per ``yield_convention.time_convention`` — street
    quasi-coupon counting by default, matching how ``y`` itself is quoted.
    """
    remaining = cash_flows_after(cash_flows, settlement_date)
    times = yield_time_fractions(cash_flows, settlement_date, day_count, yield_convention)
    pv_total = 0.0
    weighted_t = 0.0
    for cf, t in zip(remaining, times, strict=True):
        pv = cf.total * yield_convention.discount_factor(y, t)
        pv_total += pv
        weighted_t += t * pv
    if pv_total == 0:
        raise ValueError("Cannot compute Macaulay duration: present value of cash flows is zero")
    return weighted_t / pv_total


def modified_duration_from_macaulay(macaulay: float, y: float, yield_convention: YieldConvention) -> float:
    """Convert a Macaulay duration to modified duration under ``yield_convention``."""
    if yield_convention.compounding is CompoundingConvention.CONTINUOUS:
        return macaulay
    if yield_convention.compounding is CompoundingConvention.ANNUAL:
        return macaulay / (1.0 + y)
    m = yield_convention.periods_per_year
    return macaulay / (1.0 + y / m)


def modified_duration(
    cash_flows: list[CashFlow],
    settlement_date: date,
    y: float,
    yield_convention: YieldConvention,
    day_count: DayCountConvention,
) -> float:
    """Modified duration: percentage price sensitivity to a parallel yield shift."""
    macaulay = macaulay_duration(cash_flows, settlement_date, y, yield_convention, day_count)
    return modified_duration_from_macaulay(macaulay, y, yield_convention)


def dv01(
    cash_flows: list[CashFlow],
    face_value: float,
    settlement_date: date,
    y: float,
    yield_convention: YieldConvention,
    day_count: DayCountConvention,
    bump: float = _BUMP,
) -> float:
    """Dollar price change (per 100 par) for a 1bp parallel yield move, via full repricing."""
    price_up = price_from_yield(
        cash_flows, face_value, settlement_date, y + bump, yield_convention, day_count
    )
    price_down = price_from_yield(
        cash_flows, face_value, settlement_date, y - bump, yield_convention, day_count
    )
    return (price_down - price_up) / 2.0


__all__ = ["macaulay_duration", "modified_duration_from_macaulay", "modified_duration", "dv01"]
