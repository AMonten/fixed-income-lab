"""Core analytical invariants (issue #38 / ROADMAP Bloque 5).

Cheap, high-signal checks that must hold for *any* correct implementation,
independent of an external reference case: if one of these fails, a formula
is wrong somewhere. Each invariant is exercised across a grid of instruments
and conventions rather than a single hand-picked bond, so a regression that
only shows up under one day count / frequency / compounding still trips.

Invariants covered (one test function each):

- par -> 100 at a regular coupon date (extends ``test_par_bond_prices_to_exactly_100``
  from #4, which only checks the issue date)
- price strictly decreasing in yield
- convexity >= 0 when every cash flow is positive
- ``sum(principal) == face`` -- only where the structure guarantees it (bullet,
  zero, ``FullyAmortizingPlan``, ``PartialAmortizationPlan`` incl. balloon); not
  for ``FactorAmortizationPlan``, which does not force redemption (see #8)
- ``dirty == clean + accrued``
- ``factor in [0, 1]``
- ``DV01 ~= D_mod * P * 1e-4``
"""

from __future__ import annotations

from datetime import date

import pytest

from fixed_income import analyze_bond, analyze_cash_flows
from fixed_income.conventions import (
    Actual360,
    Actual365Fixed,
    ActualActualICMA,
    ActualActualISDA,
    Frequency,
    Thirty360US,
    ThirtyE360,
)
from fixed_income.instruments.amortizing import (
    AmortizingBond,
    FactorAmortizationPlan,
    FactorHistory,
    FactorObservation,
    PartialAmortizationPlan,
    ProjectedFactorPath,
    ProjectedFactorPoint,
)
from fixed_income.instruments.bond import Bond, ZeroCouponBond
from fixed_income.pricing.yield_convention import CompoundingConvention, YieldConvention
from fixed_income.pricing.yield_solver import price_from_yield
from fixed_income.risk.convexity import convexity

DAY_COUNTS = [
    Actual360(),
    Actual365Fixed(),
    Thirty360US(),
    ThirtyE360(),
    ActualActualICMA(),
    ActualActualISDA(),
]
FREQUENCIES = [Frequency.ANNUAL, Frequency.SEMI_ANNUAL, Frequency.QUARTERLY]
YIELD_CONVENTIONS = {
    "street": YieldConvention.street,
    "true": YieldConvention.true_yield,
    "annual": lambda f: YieldConvention(CompoundingConvention.ANNUAL, f.periods_per_year),
    "continuous": lambda f: YieldConvention(CompoundingConvention.CONTINUOUS, f.periods_per_year),
}
# ACT/ACT ICMA needs a ScheduleContext, which the TRUE-yield branch cannot
# supply (settlement -> payment date spans many periods; see #14/#15), so that
# pairing raises by design -- covered by its own test below, excluded here.
DC_X_YC = [
    (dc, yc)
    for dc in DAY_COUNTS
    for yc in YIELD_CONVENTIONS
    if not (isinstance(dc, ActualActualICMA) and yc == "true")
]
SETTLEMENTS = [date(2024, 1, 16), date(2024, 4, 15), date(2025, 7, 31), date(2029, 12, 1)]


def _id(obj: object) -> str:
    return type(obj).__name__


def _bond(day_count, frequency=Frequency.SEMI_ANNUAL, coupon=0.05) -> Bond:
    return Bond(100.0, coupon, date(2020, 1, 15), date(2030, 1, 15), frequency, day_count)


def _level_amortizer() -> AmortizingBond:
    return AmortizingBond.with_level_principal(100.0, 0.06, date(2022, 3, 1), date(2027, 3, 1))


def _balloon_amortizer() -> AmortizingBond:
    issue, maturity = date(2022, 3, 1), date(2025, 3, 1)
    plan = PartialAmortizationPlan(principal_repayments=(10.0,) * 6, balloon=40.0)
    return AmortizingBond(100.0, 0.06, issue, maturity, plan)


def _historical_factor_amortizer() -> AmortizingBond:
    # Includes an upward vendor revision (legal for FactorHistory, see #9).
    history = FactorHistory(
        100.0,
        (
            FactorObservation(date(2022, 9, 1), 0.92),
            FactorObservation(date(2023, 3, 1), 0.80),
            FactorObservation(date(2023, 3, 1), 0.83, as_of=date(2023, 3, 20)),
            FactorObservation(date(2023, 9, 1), 0.71),
        ),
    )
    return AmortizingBond(100.0, 0.06, date(2022, 3, 1), date(2025, 3, 1), FactorAmortizationPlan(history))


def _projected_factor_amortizer() -> AmortizingBond:
    path = ProjectedFactorPath(
        100.0,
        tuple(
            ProjectedFactorPoint(date(2022 + (i + 1) // 2, 9 if i % 2 == 0 else 3, 1), f)
            for i, f in enumerate((0.9, 0.75, 0.6, 0.4, 0.2, 0.0))
        ),
    )
    return AmortizingBond(100.0, 0.06, date(2022, 3, 1), date(2025, 3, 1), FactorAmortizationPlan(path))


# --- par -> 100 at a regular coupon date -------------------------------------


@pytest.mark.parametrize("frequency", FREQUENCIES, ids=lambda f: f.name)
@pytest.mark.parametrize("day_count", DAY_COUNTS, ids=_id)
def test_par_bond_prices_to_100_at_a_mid_life_coupon_date(day_count, frequency):
    """Yield == coupon on a coupon date => clean == dirty == 100, accrued == 0.

    Holds under every day count: regular periods pay a flat ``coupon / m``
    (#13) and street timing counts whole periods, so the day count never
    enters either side at a coupon date.
    """
    bond = _bond(day_count, frequency)
    coupon_date = date(2025, 1, 15)  # regular coupon date for every frequency above
    result = analyze_bond(bond, coupon_date, yield_to_maturity=bond.coupon_rate)
    assert result.accrued_interest == pytest.approx(0.0, abs=1e-12)
    assert result.dirty_price == pytest.approx(100.0, abs=1e-9)
    assert result.clean_price == pytest.approx(100.0, abs=1e-9)


# --- price monotone decreasing in yield ---------------------------------------


_YIELD_GRID = [-0.005, 0.0, 0.01, 0.03, 0.05, 0.08, 0.12, 0.20, 0.35]


@pytest.mark.parametrize(("day_count", "yc_name"), DC_X_YC, ids=lambda v: v if isinstance(v, str) else _id(v))
def test_bond_price_is_strictly_decreasing_in_yield(day_count, yc_name):
    bond = _bond(day_count)
    yc = YIELD_CONVENTIONS[yc_name](bond.frequency)
    settlement = date(2024, 4, 15)
    cfs = bond.cash_flows_after(settlement)
    prices = [price_from_yield(cfs, bond.face_value, settlement, y, yc, bond.day_count) for y in _YIELD_GRID]
    assert all(p_lo > p_hi for p_lo, p_hi in zip(prices, prices[1:], strict=False))


@pytest.mark.parametrize(
    "instrument",
    [
        ZeroCouponBond(100.0, date(2020, 1, 15), date(2030, 1, 15)),
        _level_amortizer(),
        _balloon_amortizer(),
        _historical_factor_amortizer(),
        _projected_factor_amortizer(),
    ],
    ids=["zero", "level", "balloon", "factor_history", "factor_projected"],
)
def test_non_bullet_price_is_strictly_decreasing_in_yield(instrument):
    settlement = date(2023, 1, 10)
    cfs = instrument.cash_flows_after(settlement)
    yc = YieldConvention.street(instrument.frequency)
    prices = [
        price_from_yield(cfs, instrument.face_value, settlement, y, yc, instrument.day_count)
        for y in _YIELD_GRID
    ]
    assert all(p_lo > p_hi for p_lo, p_hi in zip(prices, prices[1:], strict=False))


def test_icma_under_true_yield_fails_loudly_rather_than_pricing():
    bond = _bond(ActualActualICMA())
    settlement = date(2024, 4, 15)
    yc = YieldConvention.true_yield(bond.frequency)
    with pytest.raises(ValueError, match="ScheduleContext"):
        price_from_yield(
            bond.cash_flows_after(settlement), bond.face_value, settlement, 0.05, yc, bond.day_count
        )


# --- convexity >= 0 with positive cash flows ----------------------------------


@pytest.mark.parametrize("y", [0.0, 0.02, 0.05, 0.15])
@pytest.mark.parametrize("yc_name", YIELD_CONVENTIONS)
@pytest.mark.parametrize(
    "instrument",
    [
        _bond(Actual365Fixed()),
        _bond(Thirty360US(), Frequency.ANNUAL, coupon=0.0),
        ZeroCouponBond(100.0, date(2020, 1, 15), date(2030, 1, 15)),
        _level_amortizer(),
        _balloon_amortizer(),
        _historical_factor_amortizer(),
    ],
    ids=["bullet", "zero_coupon_bullet", "zero", "level", "balloon", "factor_history"],
)
def test_convexity_is_non_negative_for_positive_cash_flows(instrument, yc_name, y):
    settlement = date(2023, 1, 10)
    cfs = instrument.cash_flows_after(settlement)
    assert cfs and all(cf.total >= 0 for cf in cfs)
    yc = YIELD_CONVENTIONS[yc_name](instrument.frequency)
    assert convexity(cfs, settlement, y, yc, instrument.day_count) >= 0.0


# --- sum(principal) == face, where the structure guarantees it ----------------


@pytest.mark.parametrize(
    "instrument",
    [
        *[_bond(dc, f) for dc in DAY_COUNTS for f in FREQUENCIES],
        ZeroCouponBond(100.0, date(2020, 1, 15), date(2030, 1, 15)),
        _level_amortizer(),
        _balloon_amortizer(),
    ],
)
def test_principal_repaid_sums_to_face(instrument):
    cfs = instrument.cash_flows()
    assert sum(cf.principal for cf in cfs) == pytest.approx(instrument.face_value, abs=1e-9)
    assert cfs[-1].end_principal == pytest.approx(0.0, abs=1e-9)


def test_factor_plan_principal_is_not_forced_to_face():
    """Counter-case documenting *why* the invariant above is scoped: a factor
    plan whose last observation is above zero leaves principal outstanding
    at maturity (README "Assumptions & Limitations"; issue #8)."""
    bond = _historical_factor_amortizer()
    assert sum(cf.principal for cf in bond.cash_flows()) < bond.face_value


# --- dirty == clean + accrued ------------------------------------------------


@pytest.mark.parametrize("settlement", SETTLEMENTS, ids=str)
@pytest.mark.parametrize("frequency", FREQUENCIES, ids=lambda f: f.name)
@pytest.mark.parametrize("day_count", DAY_COUNTS, ids=_id)
def test_dirty_equals_clean_plus_accrued(day_count, frequency, settlement):
    bond = _bond(day_count, frequency)
    result = analyze_bond(bond, settlement, yield_to_maturity=0.047)
    assert result.dirty_price == pytest.approx(result.clean_price + result.accrued_interest, abs=1e-12)
    # And the reverse direction: quoting the clean price must round-trip.
    from_clean = analyze_bond(bond, settlement, clean_price=result.clean_price)
    assert from_clean.dirty_price == pytest.approx(result.dirty_price, abs=1e-8)
    assert from_clean.accrued_interest == result.accrued_interest


# --- factor in [0, 1] --------------------------------------------------------


@pytest.mark.parametrize(
    "instrument",
    [_level_amortizer(), _balloon_amortizer(), _historical_factor_amortizer(), _projected_factor_amortizer()],
    ids=["level", "balloon", "factor_history", "factor_projected"],
)
def test_current_factor_stays_within_unit_interval(instrument):
    probe_dates = (
        [date(2021, 1, 1)] + [cf.payment_date for cf in instrument.cash_flows()] + [date(2031, 1, 1)]
    )
    for d in probe_dates:
        assert 0.0 <= instrument.current_factor(d) <= 1.0, d


@pytest.mark.parametrize("bad_factor", [-1e-9, 1.0 + 1e-9, -0.5, 2.0])
def test_factor_outside_unit_interval_is_rejected_at_construction(bad_factor):
    with pytest.raises(ValueError):
        FactorObservation(date(2023, 1, 1), bad_factor)
    with pytest.raises(ValueError):
        ProjectedFactorPoint(date(2023, 1, 1), bad_factor)


# --- DV01 ~= D_mod * P * 1e-4 ------------------------------------------------

# DV01 is a central difference ((P(y-h) - P(y+h)) / 2, h = 1bp), whose error
# vs. the analytic -P'(y)*h is -P'''(y)*h^3/6: relative to DV01 that's
# ~(P'''/P')*h^2/6 -- order 1e-7 for a 10y bond at h = 1e-4. D_mod here is the
# closed form (D_mac / (1 + y/m), exact for every compounding we support), so
# the two must agree to well within this documented tolerance.
_DV01_REL_TOL = 1e-6


@pytest.mark.parametrize("y", [0.001, 0.03, 0.08, 0.2])
@pytest.mark.parametrize(("day_count", "yc_name"), DC_X_YC, ids=lambda v: v if isinstance(v, str) else _id(v))
def test_dv01_matches_modified_duration_times_dirty_price(day_count, yc_name, y):
    bond = _bond(day_count)
    yc = YIELD_CONVENTIONS[yc_name](bond.frequency)
    settlement = date(2024, 4, 15)
    r = analyze_cash_flows(
        bond.cash_flows_after(settlement),
        bond.face_value,
        settlement,
        yc,
        bond.day_count,
        yield_to_maturity=y,
    )
    assert r.dv01 == pytest.approx(r.modified_duration * r.dirty_price * 1e-4, rel=_DV01_REL_TOL)


@pytest.mark.parametrize(
    "instrument",
    [ZeroCouponBond(100.0, date(2020, 1, 15), date(2030, 1, 15)), _level_amortizer(), _balloon_amortizer()],
    ids=["zero", "level", "balloon"],
)
def test_dv01_matches_modified_duration_for_non_bullet_instruments(instrument):
    settlement = date(2023, 1, 10)
    yc = YieldConvention.street(instrument.frequency)
    r = analyze_cash_flows(
        instrument.cash_flows_after(settlement),
        instrument.face_value,
        settlement,
        yc,
        instrument.day_count,
        yield_to_maturity=0.055,
    )
    assert r.dv01 == pytest.approx(r.modified_duration * r.dirty_price * 1e-4, rel=_DV01_REL_TOL)
