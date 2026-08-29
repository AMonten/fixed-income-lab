"""The security-level analytics facade.

Every instrument in this library (bullet bonds, zero-coupon bonds, floating
rate notes, amortizing bonds) reduces, for valuation purposes, to the same
thing: a list of :class:`~fixed_income.cashflows.generator.CashFlow` plus a
face value. :func:`analyze_cash_flows` is the one place that turns that
generic representation, plus a price-or-yield input, into a complete
:class:`SecurityAnalytics` bundle — so scenario analysis and portfolio
analytics (which need the same numbers for every instrument type) consume
one function instead of re-deriving price/yield/risk logic per instrument.

:func:`analyze_bond` is a convenience wrapper for the common case of a plain
:class:`~fixed_income.instruments.bond.Bond` (fixed-rate or zero-coupon),
which also fills in accrued interest automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .cashflows.generator import CashFlow
from .conventions.day_count import DayCountConvention
from .instruments.bond import Bond
from .pricing.accrued_interest import compute_accrued_interest
from .pricing.yield_convention import YieldConvention
from .pricing.yield_solver import price_from_yield, solve_yield_to_maturity
from .risk.convexity import convexity as _convexity
from .risk.duration import dv01 as _dv01
from .risk.duration import macaulay_duration as _macaulay_duration
from .risk.duration import modified_duration_from_macaulay


@dataclass(frozen=True)
class SecurityAnalytics:
    """A complete price/yield/risk snapshot for a security as of one settlement date.

    All price fields are per 100 par.
    """

    settlement_date: date
    yield_to_maturity: float
    dirty_price: float
    clean_price: float
    accrued_interest: float
    macaulay_duration: float
    modified_duration: float
    dv01: float
    convexity: float


def analyze_cash_flows(
    cash_flows: list[CashFlow],
    face_value: float,
    settlement_date: date,
    yield_convention: YieldConvention,
    day_count: DayCountConvention,
    *,
    yield_to_maturity: float | None = None,
    dirty_price: float | None = None,
    clean_price: float | None = None,
    accrued_interest: float = 0.0,
) -> SecurityAnalytics:
    """Build a :class:`SecurityAnalytics` from a generic cash-flow list.

    Exactly one of ``yield_to_maturity``, ``dirty_price``, or ``clean_price``
    must be supplied; the other price/yield values are derived from it.
    ``accrued_interest`` (per 100 par) defaults to 0 — pass it explicitly for
    coupon-bearing instruments (see :func:`analyze_bond` for the common case
    where it is computed automatically).
    """
    provided = [v is not None for v in (yield_to_maturity, dirty_price, clean_price)]
    if sum(provided) != 1:
        raise ValueError(
            "Provide exactly one of yield_to_maturity, dirty_price, or clean_price "
            f"(got {sum(provided)})"
        )

    if clean_price is not None:
        dirty_price = clean_price + accrued_interest

    if dirty_price is not None:
        yield_to_maturity = solve_yield_to_maturity(
            cash_flows, face_value, settlement_date, dirty_price, yield_convention, day_count
        )
    else:
        assert yield_to_maturity is not None
        dirty_price = price_from_yield(
            cash_flows, face_value, settlement_date, yield_to_maturity, yield_convention, day_count
        )

    clean = dirty_price - accrued_interest
    macaulay = _macaulay_duration(cash_flows, settlement_date, yield_to_maturity, yield_convention, day_count)
    modified = modified_duration_from_macaulay(macaulay, yield_to_maturity, yield_convention)
    dollar_dv01 = _dv01(cash_flows, face_value, settlement_date, yield_to_maturity, yield_convention, day_count)
    convexity_value = _convexity(cash_flows, settlement_date, yield_to_maturity, yield_convention, day_count)

    return SecurityAnalytics(
        settlement_date=settlement_date,
        yield_to_maturity=yield_to_maturity,
        dirty_price=dirty_price,
        clean_price=clean,
        accrued_interest=accrued_interest,
        macaulay_duration=macaulay,
        modified_duration=modified,
        dv01=dollar_dv01,
        convexity=convexity_value,
    )


def analyze_bond(
    bond: Bond,
    settlement_date: date,
    *,
    yield_convention: YieldConvention | None = None,
    yield_to_maturity: float | None = None,
    dirty_price: float | None = None,
    clean_price: float | None = None,
) -> SecurityAnalytics:
    """Convenience wrapper for a plain :class:`Bond`/``ZeroCouponBond``: computes
    accrued interest automatically from the bond's own schedule and day count.
    """
    yc = yield_convention or YieldConvention.street(bond.frequency)
    accrued = compute_accrued_interest(bond, settlement_date).accrued_interest
    return analyze_cash_flows(
        bond.cash_flows_after(settlement_date),
        bond.face_value,
        settlement_date,
        yc,
        bond.day_count,
        yield_to_maturity=yield_to_maturity,
        dirty_price=dirty_price,
        clean_price=clean_price,
        accrued_interest=accrued,
    )
