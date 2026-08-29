from datetime import date

import pytest

from fixed_income.analytics import analyze_bond, analyze_cash_flows
from fixed_income.conventions.day_count import Actual365Fixed
from fixed_income.conventions.frequency import Frequency
from fixed_income.instruments.bond import Bond
from fixed_income.pricing.yield_convention import YieldConvention


@pytest.fixture
def bond():
    return Bond(100.0, 0.05, date(2020, 1, 15), date(2030, 1, 15), Frequency.SEMI_ANNUAL, Actual365Fixed())


def test_analyze_bond_from_yield_computes_full_snapshot(bond):
    settlement = date(2024, 4, 15)
    result = analyze_bond(bond, settlement, yield_to_maturity=0.045)
    assert result.yield_to_maturity == pytest.approx(0.045)
    assert result.dirty_price == pytest.approx(result.clean_price + result.accrued_interest)
    assert result.macaulay_duration > 0
    assert result.modified_duration > 0
    assert result.convexity > 0
    assert result.accrued_interest > 0


def test_analyze_bond_clean_price_round_trips_to_same_yield(bond):
    settlement = date(2024, 4, 15)
    forward = analyze_bond(bond, settlement, yield_to_maturity=0.045)
    backward = analyze_bond(bond, settlement, clean_price=forward.clean_price)
    assert backward.yield_to_maturity == pytest.approx(forward.yield_to_maturity, abs=1e-8)
    assert backward.clean_price == pytest.approx(forward.clean_price, abs=1e-6)


def test_analyze_bond_dirty_price_round_trips_to_same_yield(bond):
    settlement = date(2024, 4, 15)
    forward = analyze_bond(bond, settlement, yield_to_maturity=0.045)
    backward = analyze_bond(bond, settlement, dirty_price=forward.dirty_price)
    assert backward.yield_to_maturity == pytest.approx(forward.yield_to_maturity, abs=1e-8)


def test_analyze_cash_flows_requires_exactly_one_input(bond):
    settlement = date(2024, 4, 15)
    yc = YieldConvention.street(bond.frequency)
    cfs = bond.cash_flows_after(settlement)
    with pytest.raises(ValueError):
        analyze_cash_flows(cfs, bond.face_value, settlement, yc, bond.day_count)
    with pytest.raises(ValueError):
        analyze_cash_flows(
            cfs, bond.face_value, settlement, yc, bond.day_count,
            yield_to_maturity=0.05, clean_price=100.0,
        )


def test_analyze_cash_flows_default_accrued_interest_is_zero(bond):
    settlement = date(2024, 4, 15)
    yc = YieldConvention.street(bond.frequency)
    cfs = bond.cash_flows_after(settlement)
    result = analyze_cash_flows(cfs, bond.face_value, settlement, yc, bond.day_count, yield_to_maturity=0.045)
    assert result.accrued_interest == 0.0
    assert result.clean_price == pytest.approx(result.dirty_price)
