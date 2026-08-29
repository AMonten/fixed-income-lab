from datetime import date, timedelta

import pytest

from fixed_income.conventions.day_count import Actual365Fixed, Thirty360US
from fixed_income.instruments.bond import Bond
from fixed_income.pricing.accrued_interest import compute_accrued_interest
from fixed_income.pricing.present_value import clean_price, dirty_price


@pytest.fixture
def bond():
    return Bond(100.0, 0.05, date(2020, 1, 15), date(2030, 1, 15), day_count=Thirty360US())


def test_accrued_interest_midway_through_period(bond):
    result = compute_accrued_interest(bond, date(2024, 4, 15))
    assert result.accrual_start == date(2024, 1, 15)
    assert result.accrual_end == date(2024, 7, 15)
    assert result.accrued_days == 90
    assert result.period_days == 180
    assert result.accrued_fraction == pytest.approx(0.5)
    assert result.accrued_interest == pytest.approx(1.25)  # half of a 2.5 semi-annual coupon


def test_accrued_interest_is_zero_on_coupon_date(bond):
    result = compute_accrued_interest(bond, date(2024, 1, 15))
    assert result.accrued_interest == 0.0
    assert result.accrual_start == date(2024, 1, 15)


def test_accrued_interest_on_issue_date_is_zero(bond):
    result = compute_accrued_interest(bond, bond.issue_date)
    assert result.accrued_interest == 0.0


def test_accrued_interest_before_issue_date_raises(bond):
    with pytest.raises(ValueError):
        compute_accrued_interest(bond, date(2019, 1, 1))


def test_accrued_interest_on_or_after_maturity_raises(bond):
    with pytest.raises(ValueError):
        compute_accrued_interest(bond, bond.maturity_date)
    with pytest.raises(ValueError):
        compute_accrued_interest(bond, date(2031, 1, 1))


def test_accrued_interest_day_before_maturity_still_valid(bond):
    result = compute_accrued_interest(bond, bond.maturity_date - timedelta(days=1))
    assert result.accrual_end == bond.maturity_date
    assert result.accrued_interest > 0


def test_zero_coupon_bond_never_accrues():
    zcb = Bond(100.0, 0.0, date(2020, 1, 15), date(2030, 1, 15), day_count=Actual365Fixed())
    result = compute_accrued_interest(zcb, date(2024, 4, 15))
    assert result.accrued_interest == 0.0


def test_clean_dirty_price_round_trip():
    clean = 98.5
    accrued = 1.25
    dirty = dirty_price(clean, accrued)
    assert dirty == pytest.approx(clean + accrued)
    assert clean_price(dirty, accrued) == pytest.approx(clean)
