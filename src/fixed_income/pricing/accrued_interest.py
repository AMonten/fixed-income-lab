"""Accrued interest as of a settlement date.

Accrued interest is the portion of the *current* coupon period's interest
that belongs to the seller because it built up before ``settlement_date``.
It is computed from the coupon period containing settlement, not from the
bond's yield or price:

``accrued_interest = full_period_coupon * (accrued_days / period_days)``

``full_period_coupon`` is read directly off the bond's own cash flows
(:mod:`fixed_income.cashflows.generator`) rather than recomputed here, so
accrued interest always agrees with the coupon that actually gets paid —
whether that period is a flat regular coupon or a day-count-prorated stub.
``accrued_days``/``period_days`` use the bond's own day-count convention.

All values are expressed per 100 par, matching clean/dirty price quoting.

Assumptions (V1):
    - No ex-coupon period is modelled: accrued interest is always computed
      against the *buyer* of record as of settlement, i.e. cum-coupon.
      Ex-dividend/ex-coupon trading conventions are out of scope until a
      concrete markets requirement defines the ex-date rule.
    - On the coupon date itself, accrued interest is zero: the coupon has
      just reset and settlement belongs to the *next* accrual period.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..instruments.bond import Bond


@dataclass(frozen=True)
class AccruedInterestResult:
    """Breakdown of an accrued-interest calculation, per 100 par.

    Attributes:
        accrual_start: Start of the coupon period containing settlement.
        settlement_date: The settlement date accrued interest is computed for.
        accrual_end: End of the coupon period containing settlement (next coupon date).
        accrued_days: Days elapsed since ``accrual_start``, per the bond's day-count convention.
        period_days: Total days in the coupon period, per the same convention.
        accrued_fraction: ``accrued_days / period_days``.
        full_period_coupon: The full coupon amount for this period, per 100 par.
        accrued_interest: The accrued interest, per 100 par.
    """

    accrual_start: date
    settlement_date: date
    accrual_end: date
    accrued_days: int
    period_days: int
    accrued_fraction: float
    full_period_coupon: float
    accrued_interest: float


def compute_accrued_interest(bond: Bond, settlement_date: date) -> AccruedInterestResult:
    """Compute accrued interest for ``bond`` as of ``settlement_date``, per 100 par."""
    if settlement_date < bond.issue_date:
        raise ValueError(f"settlement_date {settlement_date} is before issue_date {bond.issue_date}")
    if settlement_date >= bond.maturity_date:
        raise ValueError(
            f"settlement_date {settlement_date} is on or after maturity_date {bond.maturity_date}; "
            "no coupon period is active"
        )

    cash_flow = next(
        cf for cf in bond.cash_flows() if cf.accrual_start <= settlement_date < cf.accrual_end
    )
    day_count = bond.day_count

    accrued_days = day_count.day_count(cash_flow.accrual_start, settlement_date)
    period_days = day_count.day_count(cash_flow.accrual_start, cash_flow.accrual_end)
    accrued_fraction = accrued_days / period_days if period_days else 0.0

    full_period_coupon = cash_flow.coupon
    accrued = full_period_coupon * accrued_fraction

    return AccruedInterestResult(
        accrual_start=cash_flow.accrual_start,
        settlement_date=settlement_date,
        accrual_end=cash_flow.accrual_end,
        accrued_days=accrued_days,
        period_days=period_days,
        accrued_fraction=accrued_fraction,
        full_period_coupon=full_period_coupon,
        accrued_interest=accrued,
    )
