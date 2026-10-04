"""#20: every instrument satisfies the shared FixedIncomeInstrument protocol.

The authoritative check is static (`mypy src/` over the TYPE_CHECKING block in
`instruments/instrument.py`). These runtime tests are a backstop: they confirm
each instrument exposes the protocol members at runtime, and that a function
typed against the protocol accepts every concrete instrument.
"""

from datetime import date

import pytest

from fixed_income.conventions.day_count import Actual360, Actual365Fixed
from fixed_income.conventions.frequency import Frequency
from fixed_income.instruments import (
    AmortizingBond,
    Bond,
    FixedIncomeInstrument,
    FloatingRateNote,
    ZeroCouponBond,
)
from fixed_income.instruments.rate_index import RateIndex


def _instruments() -> list[FixedIncomeInstrument]:
    bond = Bond(100.0, 0.05, date(2020, 1, 15), date(2025, 1, 15), day_count=Actual365Fixed())
    zero = ZeroCouponBond(100.0, date(2020, 1, 15), date(2025, 1, 15), day_count=Actual365Fixed())
    index = RateIndex(name="TEST", forward_assumption=0.03)
    frn = FloatingRateNote(
        100.0, 0.0025, date(2023, 1, 15), date(2024, 1, 15), index, Frequency.QUARTERLY, Actual360()
    )
    amortizing = AmortizingBond.with_level_principal(
        1_000_000.0, 0.06, date(2022, 1, 1), date(2027, 1, 1), Frequency.SEMI_ANNUAL
    )
    return [bond, zero, frn, amortizing]


@pytest.mark.parametrize("instrument", _instruments())
def test_instrument_is_runtime_checkable_protocol_instance(instrument):
    assert isinstance(instrument, FixedIncomeInstrument)


@pytest.mark.parametrize("instrument", _instruments())
def test_instrument_exposes_protocol_members(instrument):
    assert isinstance(instrument.face_value, float)
    assert instrument.day_count is not None
    assert isinstance(instrument.cash_flows(), list)
    assert isinstance(instrument.cash_flows_after(date(2020, 1, 1)), list)


def test_function_typed_against_protocol_accepts_every_instrument():
    def face(inst: FixedIncomeInstrument) -> float:
        return inst.face_value

    assert [face(i) for i in _instruments()] == [100.0, 100.0, 100.0, 1_000_000.0]
