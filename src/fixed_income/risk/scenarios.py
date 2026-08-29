"""Parallel rate-shock scenario analysis.

For a set of yield shocks (in basis points), computes the fully repriced
value alongside two Taylor-series approximations built from the base-case
duration and convexity:

``duration_approx  = P0 * (1 - D_mod * dy)``
``convexity_approx = P0 * (1 - D_mod * dy + 0.5 * C * dy^2)``

Comparing these to the full reprice shows the approximation error the
duration-only and duration+convexity models carry at each shock size — the
error should be visibly smaller for the convexity-adjusted estimate,
especially at the +-100bp shocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..cashflows.generator import CashFlow
from ..conventions.day_count import DayCountConvention
from ..pricing.yield_convention import YieldConvention
from ..pricing.yield_solver import price_from_yield
from .convexity import convexity as _convexity
from .duration import macaulay_duration, modified_duration_from_macaulay

DEFAULT_SHOCKS_BP: tuple[float, ...] = (-100.0, -50.0, 0.0, 50.0, 100.0)


@dataclass(frozen=True)
class ScenarioResult:
    """Outcome of one rate-shock scenario, prices per 100 par.

    Attributes:
        shock_bp: The applied parallel yield shock, in basis points.
        shocked_yield: Base yield plus the shock.
        full_reprice: Dirty price from fully repricing at ``shocked_yield``.
        price_change: ``full_reprice - base_price``.
        percent_change: ``price_change / base_price``.
        duration_approx_price: First-order (duration-only) price estimate.
        convexity_approx_price: Second-order (duration + convexity) price estimate.
    """

    shock_bp: float
    shocked_yield: float
    full_reprice: float
    price_change: float
    percent_change: float
    duration_approx_price: float
    convexity_approx_price: float


def run_rate_shock_scenarios(
    cash_flows: list[CashFlow],
    face_value: float,
    settlement_date: date,
    base_yield: float,
    yield_convention: YieldConvention,
    day_count: DayCountConvention,
    shocks_bp: tuple[float, ...] = DEFAULT_SHOCKS_BP,
) -> list[ScenarioResult]:
    """Run parallel yield-shock scenarios and compare full repricing to Taylor approximations."""
    base_price = price_from_yield(cash_flows, face_value, settlement_date, base_yield, yield_convention, day_count)
    macaulay = macaulay_duration(cash_flows, settlement_date, base_yield, yield_convention, day_count)
    modified = modified_duration_from_macaulay(macaulay, base_yield, yield_convention)
    conv = _convexity(cash_flows, settlement_date, base_yield, yield_convention, day_count)

    results = []
    for shock_bp in shocks_bp:
        dy = shock_bp / 10_000.0
        shocked_yield = base_yield + dy
        full_reprice = price_from_yield(
            cash_flows, face_value, settlement_date, shocked_yield, yield_convention, day_count
        )
        duration_approx = base_price * (1.0 - modified * dy)
        convexity_approx = base_price * (1.0 - modified * dy + 0.5 * conv * dy * dy)

        results.append(
            ScenarioResult(
                shock_bp=shock_bp,
                shocked_yield=shocked_yield,
                full_reprice=full_reprice,
                price_change=full_reprice - base_price,
                percent_change=(full_reprice - base_price) / base_price,
                duration_approx_price=duration_approx,
                convexity_approx_price=convexity_approx,
            )
        )
    return results


__all__ = ["DEFAULT_SHOCKS_BP", "ScenarioResult", "run_rate_shock_scenarios"]
