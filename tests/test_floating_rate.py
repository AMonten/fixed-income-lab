from datetime import date, timedelta

import pytest

from fixed_income.conventions.day_count import Actual360
from fixed_income.conventions.frequency import Frequency
from fixed_income.instruments.floating_rate import FloatingRateNote
from fixed_income.instruments.rate_index import RateIndex, RateObservation


@pytest.fixture
def index():
    return RateIndex(
        name="SOFR-3M",
        observations=(
            RateObservation(date(2023, 1, 15), 0.0530),
            RateObservation(date(2023, 4, 15), 0.0500),
        ),
        forward_assumption=0.045,
    )


@pytest.fixture
def frn(index):
    return FloatingRateNote(
        face_value=100.0,
        spread=0.0025,
        issue_date=date(2023, 1, 15),
        maturity_date=date(2024, 1, 15),
        rate_index=index,
        frequency=Frequency.QUARTERLY,
        day_count=Actual360(),
    )


def test_coupon_rate_uses_observed_fixing_plus_spread(frn):
    schedule = frn.schedule()
    rate = frn.coupon_rate_for_period(schedule[0])
    assert rate == pytest.approx(0.0530 + 0.0025)


def test_coupon_rate_falls_back_to_forward_assumption(frn):
    schedule = frn.schedule()
    # third period's reset date has no observed fixing
    rate = frn.coupon_rate_for_period(schedule[2])
    assert rate == pytest.approx(0.045 + 0.0025)


def test_rate_provenance_flags_observed_vs_assumed(frn):
    provenance = frn.rate_provenance()
    observed_flags = [is_observed for _, is_observed in provenance]
    assert observed_flags[0] is True
    assert observed_flags[1] is True
    assert all(flag is False for flag in observed_flags[2:])


def test_final_period_repays_principal(frn):
    cfs = frn.cash_flows()
    assert cfs[-1].principal == pytest.approx(100.0)
    assert all(cf.principal == 0.0 for cf in cfs[:-1])


def test_rate_floor_is_applied():
    index = RateIndex(name="TEST", forward_assumption=-0.01, floor=0.0)
    frn = FloatingRateNote(100.0, 0.001, date(2023, 1, 15), date(2024, 1, 15), index, Frequency.QUARTERLY, Actual360())
    for period in frn.schedule():
        rate = frn.coupon_rate_for_period(period)
        assert rate == pytest.approx(0.0 + 0.001)  # floored reference rate (0) + spread


def test_reset_lag_shifts_reset_date_before_accrual_start(index):
    frn = FloatingRateNote(
        100.0, 0.0025, date(2023, 1, 15), date(2024, 1, 15), index, Frequency.QUARTERLY, Actual360(),
        reset_lag_days=2,
    )
    schedule = frn.schedule()
    assert frn.reset_date_for(schedule[0]) == schedule[0].accrual_start - timedelta(days=2)


def test_negative_reset_lag_rejected(index):
    with pytest.raises(ValueError):
        FloatingRateNote(
            100.0, 0.0025, date(2023, 1, 15), date(2024, 1, 15), index,
            Frequency.QUARTERLY, Actual360(), reset_lag_days=-1,
        )


def test_rate_index_raises_without_observation_or_assumption():
    index = RateIndex(name="NO-DATA")
    with pytest.raises(ValueError):
        index.rate_on(date(2023, 1, 1))
