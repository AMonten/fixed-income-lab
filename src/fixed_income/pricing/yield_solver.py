"""Yield-to-maturity solving: price <-> yield inversion.

Price is a smooth, strictly decreasing function of yield for any bond with
non-negative cash flows, so root-finding is well posed. We use Brent's
method (:func:`scipy.optimize.brentq`), which is derivative-free and
guaranteed to converge once a sign-changing bracket is found — more robust
for this problem than Newton's method, which can diverge from a poor
starting guess on long-dated or deep-discount bonds.
"""

from __future__ import annotations

from datetime import date

from scipy.optimize import brentq

from ..cashflows.generator import CashFlow
from ..conventions.day_count import DayCountConvention
from .present_value import present_value_from_yield, price_per_100
from .yield_convention import YieldConvention


class YieldSolverError(ValueError):
    """Raised when a yield to maturity cannot be solved for the given inputs."""


def price_from_yield(
    cash_flows: list[CashFlow],
    face_value: float,
    settlement_date: date,
    y: float,
    yield_convention: YieldConvention,
    day_count: DayCountConvention,
) -> float:
    """Dirty price (per 100 par) implied by yield ``y``."""
    pv = present_value_from_yield(cash_flows, settlement_date, y, yield_convention, day_count)
    return price_per_100(pv, face_value)


def solve_yield_to_maturity(
    cash_flows: list[CashFlow],
    face_value: float,
    settlement_date: date,
    target_dirty_price: float,
    yield_convention: YieldConvention,
    day_count: DayCountConvention,
    *,
    bracket: tuple[float, float] = (-0.99, 3.0),
    tol: float = 1e-10,
    max_iter: int = 200,
) -> float:
    """Solve for the flat yield that reprices ``cash_flows`` to ``target_dirty_price``.

    Args:
        target_dirty_price: Full (dirty) price per 100 par to match.
        bracket: ``(low, high)`` yield bracket searched for a sign change.
            Defaults are wide enough for essentially any realistic bond;
            narrow it if a security has multiple valid roots.
        tol: Absolute tolerance on the solved yield (Brent's ``xtol``).
        max_iter: Maximum Brent iterations.

    Raises:
        YieldSolverError: If no cash flows remain after settlement, or if
            the bracket does not contain a sign change (e.g. the target
            price is unreachable at any yield in ``bracket``).
    """
    if not cash_flows:
        raise YieldSolverError("Cannot solve for yield with an empty cash-flow list")

    def objective(y: float) -> float:
        return price_from_yield(cash_flows, face_value, settlement_date, y, yield_convention, day_count) - (
            target_dirty_price
        )

    lo, hi = bracket
    try:
        f_lo, f_hi = objective(lo), objective(hi)
    except (ZeroDivisionError, OverflowError, ValueError) as exc:
        raise YieldSolverError(
            f"Failed to evaluate price at bracket endpoints {bracket} for target price "
            f"{target_dirty_price}: {exc}"
        ) from exc

    if f_lo * f_hi > 0:
        raise YieldSolverError(
            f"No sign change in price-yield objective over bracket {bracket} "
            f"(price at {lo:.4%} = {f_lo + target_dirty_price:.6f}, "
            f"price at {hi:.4%} = {f_hi + target_dirty_price:.6f}); "
            f"target price {target_dirty_price} is likely unreachable, or the bracket needs widening."
        )

    try:
        return brentq(objective, lo, hi, xtol=tol, maxiter=max_iter)
    except RuntimeError as exc:  # pragma: no cover - brentq convergence failure
        raise YieldSolverError(
            f"Yield solver failed to converge within {max_iter} iterations: {exc}"
        ) from exc
