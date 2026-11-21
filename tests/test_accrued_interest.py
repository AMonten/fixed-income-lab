from datetime import date, timedelta

import pytest

from fixed_income.cashflows.schedule import BusinessDayConvention
from fixed_income.conventions.day_count import Actual365Fixed, ActualActualICMA, Thirty360US
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


def test_accrued_inside_the_leading_fragment_of_a_long_first_coupon():
    """#19 / 31 CFR 356 App. B Sec. II.G: 9 3/4% note issued 15 Oct 1988, due
    15 Dec 1994, first coupon 15 Jun 1989, settling 15 Nov 1988 -- inside the
    long coupon's leading fragment. Published accrued interest: 0.82582 per 100.
    The fragment accrues over the *regular* period it belongs to (15 Jun ->
    15 Dec 1988, 183 days), not over the 8-month coupon span."""
    bond = Bond(
        100.0,
        0.0975,
        date(1988, 10, 15),
        date(1994, 12, 15),
        day_count=ActualActualICMA(),
        business_day_convention=BusinessDayConvention.NONE,
        first_coupon_date=date(1989, 6, 15),
    )
    result = compute_accrued_interest(bond, date(1988, 11, 15))
    assert result.accrued_interest == pytest.approx(0.82582, abs=5e-7)
    assert result.accrued_interest == pytest.approx(4.875 * 31 / 183, abs=1e-12)


def test_accrued_past_the_leading_fragment_of_a_long_first_coupon():
    """#19 / 31 CFR 356 App. B Sec. II.E: 10 3/4% bond issued 2 Jul 1985, due
    15 Aug 2005, first coupon 15 Feb 1986, settling 4 Nov 1985 -- past the
    leading fragment, inside the regular quasi-coupon period. Published accrued
    interest: 3.672798 per 100. The fragment is fully earned (44/181) and the
    regular piece prorates within itself (81/184). Prorating the whole 6.6816
    coupon evenly across its 228-day span would understate it (3.6631), because
    the two pieces are not paid at the same rate."""
    bond = Bond(
        100.0,
        0.1075,
        date(1985, 7, 2),
        date(2005, 8, 15),
        day_count=ActualActualICMA(),
        business_day_convention=BusinessDayConvention.NONE,
        first_coupon_date=date(1986, 2, 15),
    )
    result = compute_accrued_interest(bond, date(1985, 11, 4))
    assert result.accrued_interest == pytest.approx(3.672798, abs=5e-7)
    assert result.accrued_interest == pytest.approx(5.375 * (44 / 181 + 81 / 184), abs=1e-12)
    # accrued_fraction stays coherent with the coupon actually paid
    assert result.accrued_fraction == pytest.approx(
        result.accrued_interest / result.full_period_coupon, abs=1e-15
    )
