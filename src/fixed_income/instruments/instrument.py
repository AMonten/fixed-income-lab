"""The shared instrument interface.

`Bond`, `ZeroCouponBond`, `FloatingRateNote`, and `AmortizingBond` already
expose the same handful of members that every pricing and risk function needs —
a face value, a day-count convention, and the instrument's cash flows — but
only *by convention*, not by any shared type. (``AmortizingBond.face_value`` is
a hand-added alias for ``original_face`` precisely to make this informal
contract hold.)

:class:`FixedIncomeInstrument` formalizes that contract as a
:class:`typing.Protocol`, so it can be used as a parameter type and, more
usefully, so ``mypy`` *verifies* that each instrument still satisfies it. The
protocol is structural: instruments conform by shape, without inheriting from
it.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..cashflows.generator import CashFlow
from ..conventions.day_count import DayCountConvention


@runtime_checkable
class FixedIncomeInstrument(Protocol):
    """The interface shared by every instrument the analytics layer can price.

    Any object exposing a ``face_value``, a ``day_count``, and the two
    cash-flow accessors is a valid instrument as far as
    :mod:`fixed_income.analytics`, pricing, and risk are concerned — none of
    those ever branch on the concrete instrument type.
    """

    @property
    def face_value(self) -> float:
        """Redemption/face value. A read-only member so that an instrument whose
        ``face_value`` is a computed property (``AmortizingBond``, where it
        aliases ``original_face``) conforms just as a plain attribute does."""
        ...

    day_count: DayCountConvention

    def cash_flows(self) -> list[CashFlow]:
        """All of the instrument's cash flows, earliest first."""
        ...

    def cash_flows_after(self, settlement_date: date) -> list[CashFlow]:
        """The instrument's cash flows strictly after ``settlement_date``."""
        ...


if TYPE_CHECKING:
    # Static conformance checks. These run under `mypy src/` (never at runtime)
    # and fail type-checking if any instrument drifts from the protocol — e.g.
    # if AmortizingBond lost its `face_value` alias. Import here, guarded, to
    # avoid a runtime import cycle (the instrument modules don't import this one).
    from .amortizing import AmortizingBond
    from .bond import Bond, ZeroCouponBond
    from .floating_rate import FloatingRateNote

    def _assert_protocol_conformance(
        bond: Bond,
        zero_coupon_bond: ZeroCouponBond,
        floating_rate_note: FloatingRateNote,
        amortizing_bond: AmortizingBond,
    ) -> None:
        _instruments: list[FixedIncomeInstrument] = [
            bond,
            zero_coupon_bond,
            floating_rate_note,
            amortizing_bond,
        ]


__all__ = ["FixedIncomeInstrument"]
