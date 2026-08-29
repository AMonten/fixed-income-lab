import pytest

from fixed_income.conventions.frequency import Frequency


@pytest.mark.parametrize(
    "frequency, expected_periods, expected_months",
    [
        (Frequency.ANNUAL, 1, 12),
        (Frequency.SEMI_ANNUAL, 2, 6),
        (Frequency.QUARTERLY, 4, 3),
        (Frequency.MONTHLY, 12, 1),
    ],
)
def test_frequency_properties(frequency, expected_periods, expected_months):
    assert frequency.periods_per_year == expected_periods
    assert frequency.months_between_payments == expected_months


def test_frequency_is_usable_as_plain_int():
    assert Frequency.SEMI_ANNUAL == 2
    assert 100 / Frequency.QUARTERLY == 25.0
