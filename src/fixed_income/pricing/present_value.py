"""Present-value / pricing core.

Every valuation in this library reduces to the same operation: discount each
future cash flow back to settlement and sum. :func:`present_value` is the one
place that happens; everything else (yield-based pricing, curve-based
pricing) supplies a different discount-factor function to it.

Prices are computed in the cash flows' native units (i.e. scaled to the
bond's actual ``face_value``). Per the "per 100 par" quoting convention used
throughout fixed income, use :func:`price_per_100` to rescale.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from ..cashflows.generator import CashFlow, cash_flows_after
from ..conventions.day_count import DayCountConvention
from .yield_convention import YieldConvention

DiscountFactorFn = Callable[[float], float]


def present_value(
    cash_flows: list[CashFlow],
    settlement_date: date,
    discount_factor: DiscountFactorFn,
    day_count: DayCountConvention,
) -> float:
    """PV, as of ``settlement_date``, of all cash flows paid strictly after it.

    ``discount_factor(t)`` returns the discount factor for a cash flow
    ``t`` years away, where ``t`` is measured using ``day_count``.
    """
    total = 0.0
    for cf in cash_flows_after(cash_flows, settlement_date):
        t = day_count.year_fraction(settlement_date, cf.payment_date)
        total += cf.total * discount_factor(t)
    return total


def present_value_from_yield(
    cash_flows: list[CashFlow],
    settlement_date: date,
    y: float,
    yield_convention: YieldConvention,
    day_count: DayCountConvention,
) -> float:
    """PV discounting every cash flow at a single flat yield ``y``."""
    return present_value(cash_flows, settlement_date, lambda t: yield_convention.discount_factor(y, t), day_count)


def price_per_100(present_value_amount: float, face_value: float) -> float:
    """Rescale a present value to the standard "per 100 par" quoting convention."""
    return present_value_amount * 100.0 / face_value


def dirty_price(clean_price: float, accrued_interest: float) -> float:
    """Dirty (full) price = clean price + accrued interest, both per 100 par."""
    return clean_price + accrued_interest


def clean_price(dirty_price_value: float, accrued_interest: float) -> float:
    """Clean price = dirty (full) price - accrued interest, both per 100 par."""
    return dirty_price_value - accrued_interest
