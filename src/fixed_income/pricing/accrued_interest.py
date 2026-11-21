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

Long coupon periods (#19)
-------------------------

The formula above assumes interest builds up evenly across the period, which
holds only while the period is one quasi-coupon period long. A **long** first
coupon spans more than one, and its pieces are *not* equally paid: a full
nominal step pays the flat coupon, the leading fragment pays a prorated
share. Accruing such a period therefore walks its pieces
(:func:`fixed_income.cashflows.generator.quasi_period_coupons`): pieces
already past pay in full, the piece holding settlement prorates inside
itself, and ``accrued_fraction`` is reported as ``accrued /
full_period_coupon`` rather than a ratio of days — days no longer map
linearly onto interest. This reproduces 31 CFR 356 App. B §II.E to the
published sixth decimal.

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

from ..cashflows.generator import CashFlow, quasi_period_coupons
from ..cashflows.schedule import SchedulePeriod
from ..instruments.bond import Bond, ZeroCouponBond


def _quasi_pieces(bond: Bond | ZeroCouponBond, cash_flow: CashFlow) -> list[tuple[date, date, float]]:
    """``(start, end, coupon)`` for each quasi-coupon period inside ``cash_flow``'s
    accrual span — a single entry unless that period is long (#19)."""
    period = SchedulePeriod(
        period_index=cash_flow.period_index,
        accrual_start=cash_flow.accrual_start,
        accrual_end=cash_flow.accrual_end,
        payment_date=cash_flow.payment_date,
    )
    return quasi_period_coupons(
        bond.face_value,
        bond.coupon_rate,
        period,
        bond.day_count,
        bond.frequency,
        bond.maturity_date,
    )


@dataclass(frozen=True)
class AccruedInterestResult:
    """Breakdown of an accrued-interest calculation, per 100 par.

    Attributes:
        accrual_start: Start of the coupon period containing settlement.
        settlement_date: The settlement date accrued interest is computed for.
        accrual_end: End of the coupon period containing settlement (next coupon date).
        accrued_days: Days elapsed since ``accrual_start``, per the bond's day-count convention.
        period_days: Total days in the coupon period, per the same convention.
        accrued_fraction: ``accrued_days / period_days`` — or, for a long
            coupon period (#19), ``accrued_interest / full_period_coupon``,
            since the period's quasi-coupon pieces are not equally paid.
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


def compute_accrued_interest(bond: Bond | ZeroCouponBond, settlement_date: date) -> AccruedInterestResult:
    """Compute accrued interest for ``bond`` as of ``settlement_date``, per 100 par."""
    if settlement_date < bond.issue_date:
        raise ValueError(f"settlement_date {settlement_date} is before issue_date {bond.issue_date}")
    if settlement_date >= bond.maturity_date:
        raise ValueError(
            f"settlement_date {settlement_date} is on or after maturity_date {bond.maturity_date}; "
            "no coupon period is active"
        )

    cash_flow = next(cf for cf in bond.cash_flows() if cf.accrual_start <= settlement_date < cf.accrual_end)
    day_count = bond.day_count

    accrued_days = day_count.day_count(cash_flow.accrual_start, settlement_date)
    period_days = day_count.day_count(cash_flow.accrual_start, cash_flow.accrual_end)
    accrued_fraction = accrued_days / period_days if period_days else 0.0

    full_period_coupon = cash_flow.coupon
    pieces = _quasi_pieces(bond, cash_flow)
    if len(pieces) > 1 and full_period_coupon:
        # Long coupon period (#19): the span covers more than one quasi-coupon
        # period, so prorating the whole coupon over the whole span is wrong --
        # the pieces are not equally paid. Accrue piece by piece: every piece
        # already past pays in full, the one holding settlement prorates
        # within itself. Equals the formula above whenever there is one piece.
        accrued = 0.0
        for start, end, piece_coupon in pieces:
            if end <= settlement_date:
                accrued += piece_coupon
            elif start < settlement_date:
                piece_days = day_count.day_count(start, end)
                if piece_days:
                    accrued += piece_coupon * (day_count.day_count(start, settlement_date) / piece_days)
        accrued_fraction = accrued / full_period_coupon
    else:
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
