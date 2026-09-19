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

from collections.abc import Callable
from datetime import date

from ..cashflows.generator import CashFlow, cash_flows_after
from ..conventions.day_count import DayCountConvention
from .yield_convention import YieldConvention, yield_time_fractions

DiscountFactorFn = Callable[[float], float]


def present_value(
    cash_flows: list[CashFlow],
    settlement_date: date,
    discount_factor: DiscountFactorFn,
    day_count: DayCountConvention,
) -> float:
    """PV, as of ``settlement_date``, of all cash flows paid strictly after it.

    ``discount_factor(t)`` returns the discount factor for a cash flow
    ``t`` years away, where ``t`` is measured using ``day_count`` against the
    cash flow's actual (adjusted) ``payment_date``. This is the right notion
    of time for curve-based discounting — money received on a real date is
    discounted from now to that real date. It is deliberately *not* used for
    yield-based pricing (see :func:`present_value_from_yield`), whose quoted
    convention counts coupon periods rather than calendar time to the
    adjusted payment date.

    No :class:`~fixed_income.conventions.day_count.ScheduleContext` is passed
    here: ``settlement_date`` to ``cf.payment_date`` can span many coupon
    periods (any cash flow beyond the very next one), so there's no single
    reference period to hand a period-based convention like ACT/ACT ICMA —
    see :class:`~fixed_income.conventions.day_count.ScheduleContext`'s
    docstring.
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
    """PV discounting every cash flow at a single flat yield ``y``.

    Unlike :func:`present_value`, this does not discount to the actual
    payment date: it times each cash flow per ``yield_convention.time_convention``
    (street quasi-coupon counting by default; see
    :mod:`fixed_income.pricing.yield_convention`).
    """
    remaining = cash_flows_after(cash_flows, settlement_date)
    times = yield_time_fractions(cash_flows, settlement_date, day_count, yield_convention)
    return sum(
        cf.total * yield_convention.discount_factor(y, t) for cf, t in zip(remaining, times, strict=True)
    )


def price_per_100(present_value_amount: float, face_value: float) -> float:
    """Rescale a present value to the standard "per 100 par" quoting convention."""
    return present_value_amount * 100.0 / face_value


def dirty_price(clean_price: float, accrued_interest: float) -> float:
    """Dirty (full) price = clean price + accrued interest, both per 100 par."""
    return clean_price + accrued_interest


def clean_price(dirty_price_value: float, accrued_interest: float) -> float:
    """Clean price = dirty (full) price - accrued interest, both per 100 par."""
    return dirty_price_value - accrued_interest
