"""Property-based tests for day-count conventions (#39).

A day-count convention is free to disagree with the calendar — that is what it
is for. 30/360 says a month is thirty days whatever the calendar says; ACT/360
divides real days by a 360-day year, so a 365-day span measures more than one
year. None of that is a defect, and the tests here are careful not to assert
it away.

What a convention is *not* free to do is contradict itself. The laws below hold
for every convention regardless of its rules, and each is a thing that would
produce money out of nowhere if it broke:

- a date with itself measures zero time;
- time does not run backward as the end date moves forward;
- a day count and its year fraction agree on sign.

The first of those is how the missing 30/360 US end-of-February rule was
found: ``day_count(29 Feb, 29 Feb)`` returned -1, which reached
``compute_accrued_interest`` as negative accrued interest.
"""

import calendar as stdlib_calendar
from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fixed_income.conventions.day_count import (
    ActualActualICMA,
    DayCount,
    ScheduleContext,
    get_day_count_convention,
)
from fixed_income.conventions.frequency import Frequency

_CONVENTIONS = [get_day_count_convention(name) for name in DayCount]
# ACT/ACT ICMA refuses to compute a year fraction without a reference period,
# by design (#15) -- its year_fraction is covered separately, with one.
_CONTEXT_FREE = [c for c in _CONVENTIONS if not isinstance(c, ActualActualICMA)]

_YEARS = st.integers(min_value=1950, max_value=2100)


@st.composite
def _month_end_dates(draw):
    """The last day of some month, February included.

    Every special case in the 30/360 family is a month-end rule, and a
    uniform draw over a 150-year span lands on the last day of February about
    once in two thousand examples — which is to say, never within a default
    run. Mixing this in puts those dates where the rules actually are.
    """
    year = draw(_YEARS)
    month = draw(st.integers(min_value=1, max_value=12))
    return date(year, month, stdlib_calendar.monthrange(year, month)[1])


_DATES = st.one_of(
    st.dates(min_value=date(1950, 1, 1), max_value=date(2100, 12, 31)),
    _month_end_dates(),
    # The last day of February specifically, both sides of the leap rule.
    st.builds(lambda y: date(y, 2, stdlib_calendar.monthrange(y, 2)[1]), _YEARS),
)


@given(_DATES, st.sampled_from(_CONVENTIONS))
def test_a_date_with_itself_measures_zero_days(d, convention):
    """No convention may disagree with itself about a zero-length interval."""
    assert convention.day_count(d, d) == 0


@given(_DATES, st.integers(min_value=0, max_value=4000), st.sampled_from(_CONVENTIONS))
def test_day_count_never_runs_backward(d, span, convention):
    assert convention.day_count(d, d + timedelta(days=span)) >= 0


@given(
    _DATES,
    st.integers(min_value=0, max_value=2000),
    st.integers(min_value=0, max_value=2000),
    st.sampled_from(_CONVENTIONS),
)
def test_day_count_is_non_decreasing_as_the_end_date_moves_forward(d, first, second, convention):
    earlier, later = sorted((first, second))
    assert convention.day_count(d, d + timedelta(days=earlier)) <= convention.day_count(
        d, d + timedelta(days=later)
    )


@given(_DATES, st.integers(min_value=0, max_value=4000), st.sampled_from(_CONTEXT_FREE))
def test_year_fraction_agrees_with_day_count_on_sign(d, span, convention):
    """A convention's two views of the same interval cannot disagree about
    whether any time passed: a positive day count must not come back as a
    non-positive year fraction, nor the reverse."""
    end = d + timedelta(days=span)
    days = convention.day_count(d, end)
    fraction = convention.year_fraction(d, end)
    assert (days > 0) == (fraction > 0)
    assert (days == 0) == (fraction == 0)


@settings(deadline=None)
@given(
    st.dates(min_value=date(1990, 1, 1), max_value=date(2060, 1, 1)),
    st.sampled_from([Frequency.ANNUAL, Frequency.SEMI_ANNUAL, Frequency.QUARTERLY]),
    st.floats(min_value=0.0, max_value=1.0),
)
def test_icma_year_fraction_of_a_fragment_never_exceeds_its_reference_period(
    reference_start, frequency, through
):
    """ACT/ACT ICMA's defining property (Rule 251): a fragment of a coupon
    period is that fragment's real days over the *reference* period's real
    days, scaled by the frequency. So a fragment measures at most one period
    and a whole period measures exactly ``1/frequency`` — the equality ICMA
    exists to guarantee and that ACT/360 and ACT/365F deliberately break."""
    from fixed_income.cashflows.schedule import add_months

    reference_end = add_months(reference_start, frequency.months_between_payments)
    context = ScheduleContext(reference_start, reference_end, frequency)
    convention = ActualActualICMA()

    span = (reference_end - reference_start).days
    settlement = reference_start + timedelta(days=int(through * span))

    whole = convention.year_fraction(reference_start, reference_end, context)
    fragment = convention.year_fraction(reference_start, settlement, context)

    assert whole == pytest.approx(1.0 / frequency.periods_per_year, rel=1e-15)
    assert 0.0 <= fragment <= whole + 1e-15
