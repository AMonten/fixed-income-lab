"""Property-based tests for schedule generation (#39).

An example-based test says *this* schedule comes out right. The schedule grid
also obeys a handful of structural laws that must hold for *every* bond, and
those are what break on inputs nobody thought to write an example for:
month-end maturities, February in a leap year, a front stub long enough to
swallow a grid date, monthly frequencies where consecutive steps clamp to a
different day of the month.

Each test below is one of those laws, stated over randomly drawn terms. Where
a law generalizes an example in ``test_schedule.py``, the example stays: it
documents the market case it came from, the property defends the general rule.

Scope: schedule generation plus the two calculations that read the grid
directly -- long-coupon sizing (#19) and accrual. Pricing invariants over
randomly generated bonds are ``test_invariants.py``'s job and are deliberately
not duplicated here, where the per-example cost would multiply across hundreds
of draws.
"""

from datetime import date, timedelta
from itertools import pairwise

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from fixed_income.cashflows.generator import quasi_period_coupons
from fixed_income.cashflows.schedule import (
    BusinessDayConvention,
    add_months,
    adjust_business_day,
    generate_schedule,
    generate_schedule_dates,
    months_between,
    quasi_coupon_boundaries,
    regular_period_start,
    subtract_business_days,
)
from fixed_income.conventions.calendar import WEEKEND_ONLY, UnitedStatesFederalCalendar
from fixed_income.conventions.day_count import DayCount, get_day_count_convention
from fixed_income.conventions.frequency import Frequency
from fixed_income.instruments.bond import Bond
from fixed_income.pricing.accrued_interest import compute_accrued_interest

_FREQUENCIES = list(Frequency)
_DAY_COUNTS = [get_day_count_convention(name) for name in DayCount]
_CALENDARS = [WEEKEND_ONLY, UnitedStatesFederalCalendar()]

# Business-day and month arithmetic are calendar-wide laws, so they get a wide
# window; bond terms stay inside it so that any maturity can be stepped back
# the full number of periods without leaving it.
_WIDE_START = date(1950, 1, 1)
_WIDE_END = date(2100, 12, 31)


def _on_grid(d: date, maturity_date: date, months_step: int) -> bool:
    """Whether ``d`` is a quasi-coupon date of the grid anchored at maturity.

    Independent restatement of the grid's definition (``maturity - k*step``,
    day of month clamped by :func:`add_months`) — deliberately not routed
    through :func:`regular_period_start`, which is one of the things under
    test here.
    """
    months_back = months_between(d, maturity_date)
    return (
        months_back >= 0 and months_back % months_step == 0 and d == add_months(maturity_date, -months_back)
    )


@st.composite
def bond_terms(draw, max_steps: int = 8):
    """``(issue_date, maturity_date, frequency)`` spanning the shapes a V1 schedule can take.

    The maturity day of month is drawn across the whole calendar, so month-end
    clamping (29/30/31, February in leap and non-leap years) is exercised
    rather than assumed away. The front period then gets a random number of
    odd days, which covers an exact multiple of the frequency (zero odd days),
    every size of short stub, and a span long enough to push the issue date
    past an earlier grid date.
    """
    maturity_date = draw(st.dates(min_value=date(2000, 1, 1), max_value=date(2050, 12, 31)))
    frequency = draw(st.sampled_from(_FREQUENCIES))
    step = frequency.months_between_payments
    steps = draw(st.integers(min_value=1, max_value=max_steps))
    odd_days = draw(st.integers(min_value=0, max_value=31 * step))
    issue_date = add_months(maturity_date, -steps * step) - timedelta(days=odd_days)
    return issue_date, maturity_date, frequency


@st.composite
def bond_terms_with_first_coupon(draw, max_steps: int = 8):
    """Bond terms plus a ``first_coupon_date`` drawn from that bond's own grid.

    Drawing the first grid date is the no-op case; drawing a later one is a
    long first coupon (#19); drawing maturity makes the whole bond one period.
    """
    issue_date, maturity_date, frequency = draw(bond_terms(max_steps=max_steps))
    grid = generate_schedule_dates(issue_date, maturity_date, frequency)[1:]
    return issue_date, maturity_date, frequency, draw(st.sampled_from(grid))


# ---------------------------------------------------------------------------
# add_months: the primitive the whole grid is built from
# ---------------------------------------------------------------------------


@given(st.dates(min_value=_WIDE_START, max_value=_WIDE_END), st.integers(min_value=-600, max_value=600))
def test_add_months_lands_on_the_target_month_with_the_day_clamped(d, months):
    import calendar as stdlib_calendar

    result = add_months(d, months)
    assert result.year * 12 + result.month == d.year * 12 + d.month + months
    assert result.day == min(d.day, stdlib_calendar.monthrange(result.year, result.month)[1])


@given(st.dates(min_value=_WIDE_START, max_value=_WIDE_END), st.integers(min_value=1, max_value=600))
def test_add_months_is_strictly_monotone_in_the_month_offset(d, months):
    assert add_months(d, 0) == d
    assert add_months(d, months) > d
    assert add_months(d, -months) < d


@given(
    st.builds(
        date,
        st.integers(min_value=1950, max_value=2100),
        st.integers(min_value=1, max_value=12),
        st.integers(min_value=1, max_value=28),
    ),
    st.integers(min_value=-600, max_value=600),
)
def test_add_months_round_trips_when_the_day_cannot_clamp(d, months):
    """Clamping is the only thing that loses information, and a day in 1..28
    exists in every month — so on those days the offset is invertible. Days
    29..31 are intentionally excluded: there the clamp is *meant* to lose
    information, which is why the grid is anchored to maturity (#59) instead
    of chained."""
    assert add_months(add_months(d, months), -months) == d


# ---------------------------------------------------------------------------
# generate_schedule_dates: the grid itself
# ---------------------------------------------------------------------------


@given(bond_terms())
def test_schedule_dates_run_from_issue_to_maturity_strictly_increasing(terms):
    issue_date, maturity_date, frequency = terms
    dates = generate_schedule_dates(issue_date, maturity_date, frequency)
    assert dates[0] == issue_date
    assert dates[-1] == maturity_date
    assert len(dates) >= 2
    # Strictly increasing: a repeated date would be a zero-length accrual
    # period, which would silently divide by zero downstream.
    assert all(earlier < later for earlier, later in pairwise(dates))


@given(bond_terms())
def test_every_date_after_the_issue_date_sits_on_the_maturity_anchored_grid(terms):
    """#59 as a law rather than three examples: no month-end drift anywhere in
    the schedule, at any frequency, for any maturity day of month."""
    issue_date, maturity_date, frequency = terms
    step = frequency.months_between_payments
    dates = generate_schedule_dates(issue_date, maturity_date, frequency)
    for d in dates[1:]:
        assert _on_grid(d, maturity_date, step)


@given(bond_terms())
def test_only_the_front_period_can_be_irregular(terms):
    issue_date, maturity_date, frequency = terms
    step = frequency.months_between_payments
    dates = generate_schedule_dates(issue_date, maturity_date, frequency)
    for start, end in pairwise(dates[1:]):
        assert months_between(start, end) == step
        assert regular_period_start(end, maturity_date, step) == start


@given(bond_terms())
def test_the_front_stub_fits_inside_its_own_reference_period(terms):
    """Short-stub-only is a load-bearing assumption, not a cosmetic one: stub
    coupon sizing prorates over the nominal period the stub is a fragment of
    (#15), and ``quasi_coupon_boundaries`` derives that reference period the
    same way. A front period longer than one nominal step would break both
    quietly — which is exactly why a long first coupon has to be asked for
    explicitly (#19) instead of arising from the issue date."""
    issue_date, maturity_date, frequency = terms
    step = frequency.months_between_payments
    dates = generate_schedule_dates(issue_date, maturity_date, frequency)
    assert regular_period_start(dates[1], maturity_date, step) <= dates[0] < dates[1]


@given(bond_terms())
def test_generate_schedule_rejects_a_maturity_at_or_before_issue(terms):
    issue_date, _maturity_date, frequency = terms
    with pytest.raises(ValueError, match="issue_date must be before maturity_date"):
        generate_schedule_dates(issue_date, issue_date, frequency)


# ---------------------------------------------------------------------------
# first_coupon_date: the long first coupon (#19)
# ---------------------------------------------------------------------------


@given(bond_terms())
def test_naming_the_first_grid_date_as_first_coupon_date_changes_nothing(terms):
    issue_date, maturity_date, frequency = terms
    plain = generate_schedule_dates(issue_date, maturity_date, frequency)
    assert generate_schedule_dates(issue_date, maturity_date, frequency, plain[1]) == plain


@given(bond_terms_with_first_coupon())
def test_a_first_coupon_date_drops_exactly_the_grid_dates_before_it(terms):
    issue_date, maturity_date, frequency, first_coupon_date = terms
    plain = generate_schedule_dates(issue_date, maturity_date, frequency)
    dates = generate_schedule_dates(issue_date, maturity_date, frequency, first_coupon_date)

    assert dates[0] == issue_date
    assert dates[-1] == maturity_date
    assert dates[1] == first_coupon_date
    assert all(earlier < later for earlier, later in pairwise(dates))
    # Dropping dates is all it does: no date is invented, and the ones that go
    # are exactly the grid dates the first coupon now spans.
    assert set(plain) - set(dates) == {d for d in plain[1:] if d < first_coupon_date}


@given(bond_terms_with_first_coupon())
def test_the_schedule_after_a_long_first_coupon_is_still_regular(terms):
    issue_date, maturity_date, frequency, first_coupon_date = terms
    step = frequency.months_between_payments
    dates = generate_schedule_dates(issue_date, maturity_date, frequency, first_coupon_date)
    for start, end in pairwise(dates[1:]):
        assert months_between(start, end) == step
        assert regular_period_start(end, maturity_date, step) == start


@given(bond_terms_with_first_coupon(), st.integers(min_value=1, max_value=120))
def test_a_first_coupon_date_off_the_quasi_coupon_grid_is_rejected(terms, days_before):
    """A coupon cannot be paid off-grid. Accepting such a date would not just
    be lax: the schedule would drop the real grid date and pay the first
    coupon on the *next* one, silently answering a question nobody asked."""
    issue_date, maturity_date, frequency, first_coupon_date = terms
    step = frequency.months_between_payments
    candidate = first_coupon_date - timedelta(days=days_before)
    assume(issue_date < candidate <= maturity_date)
    assume(not _on_grid(candidate, maturity_date, step))

    with pytest.raises(ValueError, match="not a quasi-coupon date"):
        generate_schedule_dates(issue_date, maturity_date, frequency, candidate)


@given(bond_terms(), st.integers(min_value=0, max_value=400))
def test_a_first_coupon_date_outside_the_bond_life_is_rejected(terms, days_outside):
    issue_date, maturity_date, frequency = terms
    with pytest.raises(ValueError, match="must be after issue_date"):
        generate_schedule_dates(
            issue_date, maturity_date, frequency, issue_date - timedelta(days=days_outside)
        )
    with pytest.raises(ValueError, match="must not be after maturity_date"):
        generate_schedule_dates(
            issue_date, maturity_date, frequency, maturity_date + timedelta(days=days_outside + 1)
        )


# ---------------------------------------------------------------------------
# quasi_coupon_boundaries: the partition every long-coupon calculation runs on
# ---------------------------------------------------------------------------


@given(bond_terms_with_first_coupon())
def test_quasi_coupon_boundaries_recover_the_dates_a_long_coupon_skipped(terms):
    """The boundaries of a period are its own two ends plus every date of the
    *undropped* schedule that falls inside it. That ties the two halves of #19
    together: ``first_coupon_date`` stops those dates being **payment** dates,
    and this is the statement that they survive as **quasi-coupon** dates —
    which is what sizes the coupon, accrues interest and counts street yield
    exponents. Checked against the plain schedule rather than against the
    grid formula, so it is independent of how either one is computed."""
    issue_date, maturity_date, frequency, first_coupon_date = terms
    step = frequency.months_between_payments
    plain = set(generate_schedule_dates(issue_date, maturity_date, frequency))
    periods = generate_schedule(issue_date, maturity_date, frequency, first_coupon_date=first_coupon_date)
    for period in periods:
        boundaries = quasi_coupon_boundaries(period.accrual_start, period.accrual_end, maturity_date, step)
        inside = {d for d in plain if period.accrual_start < d < period.accrual_end}
        assert boundaries == sorted({period.accrual_start, period.accrual_end} | inside)
        # The period's own start may be an off-grid stub start; everything else is
        # a genuine quasi-coupon date.
        assert all(_on_grid(d, maturity_date, step) for d in boundaries[1:])


@given(bond_terms_with_first_coupon())
def test_only_the_first_period_is_ever_long(terms):
    issue_date, maturity_date, frequency, first_coupon_date = terms
    step = frequency.months_between_payments
    periods = generate_schedule(issue_date, maturity_date, frequency, first_coupon_date=first_coupon_date)
    for period in periods[1:]:
        boundaries = quasi_coupon_boundaries(period.accrual_start, period.accrual_end, maturity_date, step)
        assert boundaries == [period.accrual_start, period.accrual_end]


# ---------------------------------------------------------------------------
# Business-day adjustment
# ---------------------------------------------------------------------------


@given(
    st.dates(min_value=_WIDE_START, max_value=_WIDE_END),
    st.sampled_from(_CALENDARS),
)
def test_following_is_the_earliest_business_day_not_before_the_date(d, calendar):
    rolled = adjust_business_day(d, BusinessDayConvention.FOLLOWING, calendar)
    assert rolled >= d
    assert calendar.is_business_day(rolled)
    assert not any(calendar.is_business_day(d + timedelta(days=i)) for i in range((rolled - d).days))


@given(
    st.dates(min_value=_WIDE_START, max_value=_WIDE_END),
    st.sampled_from(_CALENDARS),
)
def test_preceding_is_the_latest_business_day_not_after_the_date(d, calendar):
    rolled = adjust_business_day(d, BusinessDayConvention.PRECEDING, calendar)
    assert rolled <= d
    assert calendar.is_business_day(rolled)
    assert not any(calendar.is_business_day(d - timedelta(days=i)) for i in range((d - rolled).days))


@given(
    st.dates(min_value=_WIDE_START, max_value=_WIDE_END),
    st.sampled_from(_CALENDARS),
)
def test_modified_following_never_leaves_the_month(d, calendar):
    """The whole point of the modified variant: a payment date never slips into
    the next month, which is what would make a monthly schedule skip a month."""
    rolled = adjust_business_day(d, BusinessDayConvention.MODIFIED_FOLLOWING, calendar)
    assert (rolled.year, rolled.month) == (d.year, d.month)
    assert calendar.is_business_day(rolled)


@given(
    st.dates(min_value=_WIDE_START, max_value=_WIDE_END),
    st.sampled_from(list(BusinessDayConvention)),
    st.sampled_from(_CALENDARS),
)
def test_business_day_adjustment_is_idempotent(d, convention, calendar):
    once = adjust_business_day(d, convention, calendar)
    assert adjust_business_day(once, convention, calendar) == once


@given(
    st.dates(min_value=_WIDE_START, max_value=_WIDE_END),
    st.integers(min_value=0, max_value=40),
    st.sampled_from(_CALENDARS),
)
def test_subtract_business_days_equals_repeating_a_single_step(d, n, calendar):
    stepwise = d
    for _ in range(n):
        stepwise = subtract_business_days(stepwise, 1, calendar)
    assert subtract_business_days(d, n, calendar) == stepwise
    if n:
        assert stepwise < d
        assert calendar.is_business_day(stepwise)
    else:
        assert stepwise == d


# ---------------------------------------------------------------------------
# generate_schedule: periods, not just dates
# ---------------------------------------------------------------------------


@given(bond_terms_with_first_coupon(), st.sampled_from(_CALENDARS))
def test_schedule_periods_are_contiguous_and_land_on_business_days(terms, calendar):
    issue_date, maturity_date, frequency, first_coupon_date = terms
    periods = generate_schedule(
        issue_date,
        maturity_date,
        frequency,
        BusinessDayConvention.FOLLOWING,
        calendar,
        first_coupon_date,
    )
    assert [p.period_index for p in periods] == list(range(len(periods)))
    assert periods[0].accrual_start == issue_date
    assert periods[-1].accrual_end == maturity_date
    for period in periods:
        assert period.accrual_start < period.accrual_end
        assert period.payment_date >= period.accrual_end
        assert calendar.is_business_day(period.payment_date)
    for earlier, later in pairwise(periods):
        assert earlier.accrual_end == later.accrual_start


# ---------------------------------------------------------------------------
# What the grid is for: long-coupon sizing (#19) and accrual
# ---------------------------------------------------------------------------


@st.composite
def long_first_coupon_bond(draw):
    """A bond whose first coupon may be short, regular, or long, under any day count."""
    issue_date, maturity_date, frequency, first_coupon_date = draw(bond_terms_with_first_coupon(max_steps=5))
    return Bond(
        face_value=100.0,
        coupon_rate=draw(st.floats(min_value=0.001, max_value=0.25)),
        issue_date=issue_date,
        maturity_date=maturity_date,
        frequency=frequency,
        day_count=draw(st.sampled_from(_DAY_COUNTS)),
        first_coupon_date=first_coupon_date,
    )


# Deadline off: an example here builds a whole cash-flow schedule (up to 60
# monthly periods) under a drawn day count. That is well within a test's
# budget but not within hypothesis's 200ms default on a loaded CI runner.
@settings(deadline=None)
@given(long_first_coupon_bond())
def test_a_long_first_coupon_is_the_short_stub_plus_the_coupons_it_absorbed(bond):
    """A long first coupon decomposes exactly: it is what the *same* bond would
    have paid as a short front stub, plus one flat regular coupon for each
    quasi-coupon date the long period swallowed. That cross-checks #19's new
    piecewise path against the short-stub path that predates it, independently
    of either one's formula — the long coupon is not allowed to be its own
    calculation.

    Also pins the lower bound ICMA Rule 251 and 31 CFR 356 App. B exist to
    enforce: a long coupon pays *at least* a regular one. One proration over
    the oversized span, the obvious wrong formula, lands below it.

    Neither side of the obvious bracket ``0 < coupon <= n * regular`` is
    asserted, and both omissions are deliberate — each one is a day-count
    convention doing its job, not a defect:

    - The upper bound fails because a stub's day-count fraction can exceed
      ``1/frequency`` whenever the basis year is shorter than the calendar
      one. A 361-day stub under ACT/360 pays ``361/360`` of the annual
      coupon; ACT/365F does the same in a leap year.
    - The lower bound fails because 30/360 measures zero days from the 30th
      to the 31st of the same month — the 31st does not exist in a 30-day
      month model — so a bond issued on 30 Jan against a 31 Jan grid has a
      one-day front stub that correctly pays nothing at all."""
    first = bond.cash_flows()[0]
    pieces = quasi_period_coupons(
        bond.face_value,
        bond.coupon_rate,
        bond.schedule()[0],
        bond.day_count,
        bond.frequency,
        bond.maturity_date,
    )
    regular = bond.face_value * bond.coupon_rate / bond.frequency.periods_per_year

    assert first.coupon == pytest.approx(sum(amount for _, _, amount in pieces), rel=1e-15)
    assert first.coupon >= 0.0

    # The same bond with no first_coupon_date: a short front stub, the V1 shape.
    as_short_stub = Bond(
        face_value=bond.face_value,
        coupon_rate=bond.coupon_rate,
        issue_date=bond.issue_date,
        maturity_date=bond.maturity_date,
        frequency=bond.frequency,
        day_count=bond.day_count,
    )
    absorbed = len(pieces) - 1
    expected = as_short_stub.cash_flows()[0].coupon + absorbed * regular
    assert first.coupon == pytest.approx(expected, rel=1e-12)
    if absorbed:
        assert first.coupon >= regular


@st.composite
def bond_and_two_settlements(draw):
    """A bond plus two settlement dates inside its first period, in order."""
    bond = draw(long_first_coupon_bond())
    first = bond.cash_flows()[0]
    span = (first.accrual_end - first.accrual_start).days
    earlier = draw(st.integers(min_value=0, max_value=span - 1))
    later = draw(st.integers(min_value=earlier, max_value=span - 1))
    return (
        bond,
        first.accrual_start + timedelta(days=earlier),
        first.accrual_start + timedelta(days=later),
    )


@settings(deadline=None)
@given(bond_and_two_settlements())
def test_accrued_interest_is_bounded_and_non_decreasing_within_a_period(terms):
    """Interest never un-accrues. Inside a *long* period the pieces are not
    equally paid (#19), so accrual is piecewise linear rather than linear —
    monotonicity is the property that survives, and it is what would break if
    a boundary were double-counted or skipped."""
    bond, earlier, later = terms
    first = compute_accrued_interest(bond, earlier)
    second = compute_accrued_interest(bond, later)

    assert first.accrued_interest <= second.accrued_interest + 1e-12
    for result in (first, second):
        assert 0.0 <= result.accrued_interest <= result.full_period_coupon + 1e-12
        assert 0.0 <= result.accrued_fraction <= 1.0 + 1e-12
        assert result.accrual_start <= result.settlement_date < result.accrual_end


@settings(deadline=None)
@given(long_first_coupon_bond())
def test_accrued_interest_accrues_exactly_when_day_count_time_has_elapsed(bond):
    """Nothing has accrued on the accrual start, nothing beyond the coupon has
    accrued by the day before the period ends, and in between accrual is
    positive on exactly the days the bond's own convention says have elapsed.

    That last clause is a biconditional on purpose. The tempting version —
    "by the day before the period ends, some interest has accrued" — is false,
    and 30/360 is why: it measures zero days from the 30th of a month to the
    31st, so a bond issued 30 Dec against a 1 Jan coupon date accrues nothing
    on 31 Dec. Tying accrual to ``accrued_days`` instead of to the calendar
    keeps the test honest about which clock the convention runs on."""
    first = bond.cash_flows()[0]
    at_start = compute_accrued_interest(bond, first.accrual_start)
    assert at_start.accrued_interest == pytest.approx(0.0, abs=1e-12)
    assert at_start.accrued_days == 0

    day_before_end = first.accrual_end - timedelta(days=1)
    assume(day_before_end > first.accrual_start)
    at_end = compute_accrued_interest(bond, day_before_end)
    assert at_end.accrued_interest <= first.coupon + 1e-12
    assert (at_end.accrued_interest > 0.0) == (at_end.accrued_days > 0 and first.coupon > 0.0)
