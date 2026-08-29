from datetime import date

import pytest

from fixed_income.conventions.day_count import Actual365Fixed
from fixed_income.conventions.frequency import Frequency
from fixed_income.instruments.bond import Bond
from fixed_income.pricing.yield_convention import YieldConvention
from fixed_income.pricing.yield_solver import price_from_yield
from fixed_income.risk.scenarios import DEFAULT_SHOCKS_BP, run_rate_shock_scenarios


@pytest.fixture
def setup():
    bond = Bond(100.0, 0.05, date(2020, 1, 15), date(2030, 1, 15), Frequency.SEMI_ANNUAL, Actual365Fixed())
    settlement = date(2024, 1, 16)
    cfs = bond.cash_flows_after(settlement)
    yc = YieldConvention.street(bond.frequency)
    return bond, settlement, cfs, yc


def test_scenario_zero_shock_matches_base_price(setup):
    bond, settlement, cfs, yc = setup
    base_yield = 0.05
    base_price = price_from_yield(cfs, bond.face_value, settlement, base_yield, yc, bond.day_count)
    results = run_rate_shock_scenarios(cfs, bond.face_value, settlement, base_yield, yc, bond.day_count)
    zero_shock = next(r for r in results if r.shock_bp == 0.0)
    assert zero_shock.full_reprice == pytest.approx(base_price)
    assert zero_shock.price_change == pytest.approx(0.0)
    assert zero_shock.duration_approx_price == pytest.approx(base_price)
    assert zero_shock.convexity_approx_price == pytest.approx(base_price)


def test_scenario_prices_move_opposite_to_shock_direction(setup):
    bond, settlement, cfs, yc = setup
    results = run_rate_shock_scenarios(cfs, bond.face_value, settlement, 0.05, yc, bond.day_count)
    by_shock = {r.shock_bp: r for r in results}
    assert by_shock[-100.0].full_reprice > by_shock[0.0].full_reprice
    assert by_shock[100.0].full_reprice < by_shock[0.0].full_reprice


def test_scenario_default_shocks_are_the_standard_set():
    assert DEFAULT_SHOCKS_BP == (-100.0, -50.0, 0.0, 50.0, 100.0)


def test_convexity_approximation_closer_than_duration_at_large_shock(setup):
    bond, settlement, cfs, yc = setup
    results = run_rate_shock_scenarios(cfs, bond.face_value, settlement, 0.05, yc, bond.day_count, shocks_bp=(100.0,))
    r = results[0]
    duration_error = abs(r.full_reprice - r.duration_approx_price)
    convexity_error = abs(r.full_reprice - r.convexity_approx_price)
    assert convexity_error < duration_error


def test_custom_shock_set_is_respected(setup):
    bond, settlement, cfs, yc = setup
    results = run_rate_shock_scenarios(cfs, bond.face_value, settlement, 0.05, yc, bond.day_count, shocks_bp=(-25.0, 25.0))
    assert [r.shock_bp for r in results] == [-25.0, 25.0]
