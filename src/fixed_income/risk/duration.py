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
    """Convert a Macaulay duration to modified duration under ``yield_convention``.

    This shortcut exists only because dividing by ``1 + y/m`` *is* the exact
    conversion when the discount function is an exponential in ``t``. It is not
    a universal identity: under
    ``PERIODIC_SIMPLE_FRACTIONAL_PERIOD`` (#61) the two durations are no longer
    related by a single factor, because each cash flow's sensitivity depends on
    how much of the fractional period it sits behind. That case raises rather
    than returning a number off by a small, undisclosed amount; use
    :func:`modified_duration`, which is correct under every convention.
    """
    if yield_convention.compounding is CompoundingConvention.CONTINUOUS:
        return macaulay
    if yield_convention.compounding is CompoundingConvention.ANNUAL:
        return macaulay / (1.0 + y)
    if yield_convention.compounding is CompoundingConvention.PERIODIC_SIMPLE_FRACTIONAL_PERIOD:
        raise ValueError(
            "Macaulay duration does not convert to modified duration by a single factor under "
            "PERIODIC_SIMPLE_FRACTIONAL_PERIOD: its discount function is not an exponential in t. "
            "Use modified_duration(), which asks the convention for its own sensitivities."
        )
    m = yield_convention.periods_per_year
    return macaulay / (1.0 + y / m)


def modified_duration(
    cash_flows: list[CashFlow],
    settlement_date: date,
    y: float,
    yield_convention: YieldConvention,
    day_count: DayCountConvention,
) -> float:
    """Modified duration: percentage price sensitivity to a parallel yield shift.

    The PV-weighted mean of each cash flow's own ``-D'/D``, which the yield
    convention supplies (see ``YieldConvention.discount_sensitivities``). For
    the uniform compounding rules that is identically ``macaulay / (1 + y/m)``;
    stating it this way instead keeps it exact for a convention whose discount
    function has no such closed form (#61).
    """
    remaining = cash_flows_after(cash_flows, settlement_date)
    times = yield_time_fractions(cash_flows, settlement_date, day_count, yield_convention)
    pv_total = 0.0
    weighted = 0.0
    for cf, t in zip(remaining, times, strict=True):
        pv = cf.total * yield_convention.discount_factor(y, t)
        first, _ = yield_convention.discount_sensitivities(y, t)
        pv_total += pv
        weighted += pv * first
    if pv_total == 0:
        raise ValueError("Cannot compute modified duration: present value of cash flows is zero")
    return weighted / pv_total


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
