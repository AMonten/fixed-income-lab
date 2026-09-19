from datetime import date

import pytest

from fixed_income.conventions.frequency import Frequency
from fixed_income.instruments.amortizing import (
    AmortizingBond,
    FactorAmortizationPlan,
    FactorHistory,
    FactorObservation,
    FullyAmortizingPlan,
    PartialAmortizationPlan,
)


def test_level_principal_fully_amortizes_to_zero():
    bond = AmortizingBond.with_level_principal(1_000_000.0, 0.06, date(2022, 1, 1), date(2027, 1, 1), Frequency.SEMI_ANNUAL)
    entries = bond.amortization_schedule()
    assert entries[-1].end_principal == pytest.approx(0.0, abs=1e-6)
    assert sum(e.principal_repayment for e in entries) == pytest.approx(1_000_000.0)


def test_level_principal_repays_equal_installments():
    bond = AmortizingBond.with_level_principal(1_000_000.0, 0.06, date(2022, 1, 1), date(2027, 1, 1), Frequency.SEMI_ANNUAL)
    entries = bond.amortization_schedule()
    installments = [e.principal_repayment for e in entries]
    # all but possibly the last are identical
    assert all(x == pytest.approx(installments[0]) for x in installments[:-1])


def test_interest_computed_on_declining_balance():
    bond = AmortizingBond.with_level_principal(1_000_000.0, 0.06, date(2022, 1, 1), date(2027, 1, 1), Frequency.SEMI_ANNUAL)
    entries = bond.amortization_schedule()
    for prev, curr in zip(entries, entries[1:]):  # noqa: B905 - intentionally mismatched lengths (pairwise)
        assert curr.begin_principal == pytest.approx(prev.end_principal)
        assert curr.begin_principal < prev.begin_principal
    # interest should decline period over period as balance declines
    interests = [e.interest for e in entries]
    assert interests == sorted(interests, reverse=True)


def test_current_factor_and_face_over_time():
    bond = AmortizingBond.with_level_principal(1_000_000.0, 0.06, date(2022, 1, 1), date(2027, 1, 1), Frequency.SEMI_ANNUAL)
    assert bond.current_factor(bond.issue_date) == pytest.approx(1.0)
    assert bond.current_factor(bond.maturity_date) == pytest.approx(0.0, abs=1e-6)
    assert bond.percent_amortized(bond.issue_date) == pytest.approx(0.0)


def test_sinkable_bond_explicit_schedule():
    plan = FullyAmortizingPlan((200_000.0, 300_000.0, 500_000.0))
    bond = AmortizingBond(1_000_000.0, 0.05, date(2023, 1, 1), date(2024, 7, 1), plan, Frequency.SEMI_ANNUAL)
    entries = bond.amortization_schedule()
    assert [e.principal_repayment for e in entries] == pytest.approx([200_000.0, 300_000.0, 500_000.0])
    assert entries[-1].end_principal == pytest.approx(0.0)


def test_sinkable_plan_length_mismatch_raises():
    plan = FullyAmortizingPlan((200_000.0, 300_000.0))  # only 2 entries
    bond = AmortizingBond(1_000_000.0, 0.05, date(2023, 1, 1), date(2024, 7, 1), plan, Frequency.SEMI_ANNUAL)
    with pytest.raises(ValueError):
        bond.amortization_schedule()


def test_fully_amortizing_plan_rejects_over_amortization_instead_of_clamping():
    """Regression for #8: repayments summing to more than original_face used to
    silently clamp outstanding to zero via max(..., 0.0) instead of raising."""
    plan = FullyAmortizingPlan((200_000.0, 300_000.0, 600_000.0))  # sums to 1,100,000 > face
    bond = AmortizingBond(1_000_000.0, 0.05, date(2023, 1, 1), date(2024, 7, 1), plan, Frequency.SEMI_ANNUAL)
    with pytest.raises(ValueError):
        bond.amortization_schedule()


def test_fully_amortizing_plan_rejects_under_amortization():
    """A FullyAmortizingPlan whose repayments don't sum to face is exactly the
    ambiguous case #8 flags -- it must raise, not leave a silent leftover."""
    plan = FullyAmortizingPlan((200_000.0, 300_000.0, 400_000.0))  # sums to 900,000 < face
    bond = AmortizingBond(1_000_000.0, 0.05, date(2023, 1, 1), date(2024, 7, 1), plan, Frequency.SEMI_ANNUAL)
    with pytest.raises(ValueError):
        bond.amortization_schedule()


def test_partial_amortization_plan_repays_balloon_at_final_period():
    """The ROADMAP's own example: 100 = 20 + 20 + 20 in level repayments,
    with a 40 balloon due in full at the final period."""
    plan = PartialAmortizationPlan((20.0, 20.0, 20.0), balloon=40.0)
    bond = AmortizingBond(100.0, 0.05, date(2023, 1, 1), date(2024, 7, 1), plan, Frequency.SEMI_ANNUAL)
    entries = bond.amortization_schedule()
    assert [e.principal_repayment for e in entries] == pytest.approx([20.0, 20.0, 60.0])
    assert entries[-1].end_principal == pytest.approx(0.0)


def test_partial_amortization_plan_requires_repayments_plus_balloon_to_equal_face():
    plan = PartialAmortizationPlan((20.0, 20.0, 20.0), balloon=100.0)  # 60 + 100 != 100
    bond = AmortizingBond(100.0, 0.05, date(2023, 1, 1), date(2024, 7, 1), plan, Frequency.SEMI_ANNUAL)
    with pytest.raises(ValueError):
        bond.amortization_schedule()


def test_partial_amortization_plan_rejects_over_amortization_before_the_balloon():
    """A too-large intermediate repayment must raise even though the total
    across all periods still adds up to face -- issue #8's "single period
    driving outstanding below zero" case, not just a bad grand total."""
    plan = PartialAmortizationPlan((90.0, 20.0, -10.0), balloon=0.0)  # sums to 100, but period 1 over-repays
    bond = AmortizingBond(100.0, 0.05, date(2023, 1, 1), date(2024, 7, 1), plan, Frequency.SEMI_ANNUAL)
    with pytest.raises(ValueError):
        bond.amortization_schedule()


def test_factor_history_current_face_matches_spec_example():
    history = FactorHistory(original_face=10_000_000.0, observations=(FactorObservation(date(2023, 7, 1), 0.734512),))
    assert history.current_face_on(date(2023, 8, 1)) == pytest.approx(7_345_120.0)


def test_factor_history_defaults_to_full_factor_before_first_observation():
    history = FactorHistory(original_face=10_000_000.0, observations=(FactorObservation(date(2023, 7, 1), 0.5),))
    assert history.factor_on(date(2023, 1, 1)) == pytest.approx(1.0)


def test_factor_history_percent_amortized_and_paydown():
    history = FactorHistory(original_face=10_000_000.0, observations=(FactorObservation(date(2023, 7, 1), 0.8),))
    assert history.percent_amortized_on(date(2023, 8, 1)) == pytest.approx(0.2)
    assert history.paydown_on(date(2023, 8, 1)) == pytest.approx(2_000_000.0)


def test_factor_observation_rejects_out_of_range_factor():
    with pytest.raises(ValueError):
        FactorObservation(date(2023, 1, 1), 1.5)


def test_factor_amortization_plan_drives_bond_paydown():
    history = FactorHistory(
        original_face=10_000_000.0,
        observations=(FactorObservation(date(2022, 7, 1), 0.9), FactorObservation(date(2023, 1, 1), 0.8)),
    )
    plan = FactorAmortizationPlan(history)
    bond = AmortizingBond(10_000_000.0, 0.045, date(2022, 1, 1), date(2023, 7, 1), plan, Frequency.SEMI_ANNUAL)
    entries = bond.amortization_schedule()
    assert entries[0].end_principal == pytest.approx(9_000_000.0)
    assert entries[1].end_principal == pytest.approx(8_000_000.0)


def test_amortizing_bond_face_value_alias_matches_original_face():
    bond = AmortizingBond.with_level_principal(1_000_000.0, 0.06, date(2022, 1, 1), date(2027, 1, 1))
    assert bond.face_value == bond.original_face


def test_amortizing_bond_cash_flows_track_amortization_schedule():
    bond = AmortizingBond.with_level_principal(1_000_000.0, 0.06, date(2022, 1, 1), date(2027, 1, 1), Frequency.SEMI_ANNUAL)
    cfs = bond.cash_flows()
    entries = bond.amortization_schedule()
    for cf, entry in zip(cfs, entries, strict=True):
        assert cf.coupon == pytest.approx(entry.interest)
        assert cf.principal == pytest.approx(entry.principal_repayment)
        assert cf.end_principal == pytest.approx(entry.end_principal)
