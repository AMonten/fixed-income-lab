from datetime import date

import pytest

from fixed_income.analytics import SecurityAnalytics
from fixed_income.portfolio.analytics import PortfolioPosition, analyze_portfolio

VALUATION_DATE = date(2024, 1, 1)


def _analytics(
    yield_to_maturity,
    dirty_price,
    clean_price,
    mod_dur,
    dv01,
    convexity,
    settlement_date=VALUATION_DATE,
):
    return SecurityAnalytics(
        settlement_date=settlement_date,
        yield_to_maturity=yield_to_maturity,
        dirty_price=dirty_price,
        clean_price=clean_price,
        accrued_interest=dirty_price - clean_price,
        macaulay_duration=mod_dur,
        modified_duration=mod_dur,
        dv01=dv01,
        convexity=convexity,
    )


def _position(identifier, par_amount, maturity_date, analytics, **kwargs):
    kwargs.setdefault("settlement_date", VALUATION_DATE)
    return PortfolioPosition(
        identifier,
        par_amount=par_amount,
        maturity_date=maturity_date,
        analytics=analytics,
        **kwargs,
    )


def test_portfolio_position_market_value_scales_with_par_amount():
    analytics = _analytics(0.05, 101.0, 100.0, 5.0, 0.05, 30.0)
    pos = _position("A", 1_000_000.0, date(2030, 1, 1), analytics)
    assert pos.market_value == pytest.approx(1_010_000.0)
    assert pos.clean_market_value == pytest.approx(1_000_000.0)
    assert pos.dv01 == pytest.approx(500.0)


def test_portfolio_position_rejects_zero_par_amount():
    analytics = _analytics(0.05, 100.0, 100.0, 5.0, 0.05, 30.0)
    with pytest.raises(ValueError):
        _position("A", 0.0, date(2030, 1, 1), analytics)


def test_portfolio_position_allows_negative_par_amount_for_a_short():
    analytics = _analytics(0.05, 101.0, 100.0, 5.0, 0.05, 30.0)
    pos = _position("SHORT", -1_000_000.0, date(2030, 1, 1), analytics)
    # A short's market value and DV01 carry the sign through.
    assert pos.market_value == pytest.approx(-1_010_000.0)
    assert pos.clean_market_value == pytest.approx(-1_000_000.0)
    assert pos.dv01 == pytest.approx(-500.0)


def test_portfolio_position_rejects_settlement_before_trade_date():
    analytics = _analytics(0.05, 100.0, 100.0, 5.0, 0.05, 30.0)
    with pytest.raises(ValueError):
        _position(
            "A",
            1_000_000.0,
            date(2030, 1, 1),
            analytics,
            trade_date=date(2024, 1, 3),
            settlement_date=date(2024, 1, 1),
        )


def test_analyze_portfolio_weighted_metrics_are_market_value_weighted():
    a1 = _analytics(0.04, 100.0, 99.0, 4.0, 0.04, 20.0)
    a2 = _analytics(0.06, 100.0, 99.0, 8.0, 0.08, 60.0)
    pos1 = _position("A", 1_000_000.0, date(2028, 1, 1), a1)
    pos2 = _position("B", 1_000_000.0, date(2032, 1, 1), a2)

    result = analyze_portfolio([pos1, pos2], valuation_date=VALUATION_DATE)

    assert result.valuation_date == VALUATION_DATE
    assert result.currency == "USD"
    assert result.market_value == pytest.approx(pos1.market_value + pos2.market_value)
    # equal market values -> simple average of yield/duration/convexity
    assert result.weighted_yield == pytest.approx(0.05)
    assert result.weighted_modified_duration == pytest.approx(6.0)
    assert result.weighted_convexity == pytest.approx(40.0)
    assert result.dv01 == pytest.approx(pos1.dv01 + pos2.dv01)


def test_analyze_portfolio_allows_different_settlement_dates_per_position():
    # Positions may settle on different dates as long as they are valued as of
    # the same date.
    a1 = _analytics(0.04, 100.0, 99.0, 4.0, 0.04, 20.0)
    a2 = _analytics(0.06, 100.0, 99.0, 8.0, 0.08, 60.0)
    pos1 = _position("A", 1_000_000.0, date(2028, 1, 1), a1, settlement_date=date(2024, 1, 3))
    pos2 = _position("B", 1_000_000.0, date(2032, 1, 1), a2, settlement_date=date(2024, 1, 5))

    result = analyze_portfolio([pos1, pos2], valuation_date=VALUATION_DATE)

    assert result.market_value == pytest.approx(pos1.market_value + pos2.market_value)


def test_analyze_portfolio_maturity_distribution_weights_sum_to_one():
    a1 = _analytics(0.04, 100.0, 99.0, 4.0, 0.04, 20.0)
    a2 = _analytics(0.06, 100.0, 99.0, 8.0, 0.08, 60.0)
    pos1 = _position("A", 3_000_000.0, date(2028, 1, 1), a1)
    pos2 = _position("B", 1_000_000.0, date(2032, 1, 1), a2)

    result = analyze_portfolio([pos1, pos2], valuation_date=VALUATION_DATE)
    weights = [w for _, _, w in result.maturity_distribution]
    assert sum(weights) == pytest.approx(1.0)
    assert weights[0] > weights[1]  # position A has 3x the par amount


def test_analyze_portfolio_requires_at_least_one_position():
    with pytest.raises(ValueError):
        analyze_portfolio([], valuation_date=VALUATION_DATE)


def test_analyze_portfolio_rejects_mixed_currencies():
    a1 = _analytics(0.04, 100.0, 99.0, 4.0, 0.04, 20.0)
    a2 = _analytics(0.06, 100.0, 99.0, 8.0, 0.08, 60.0)
    pos1 = _position("USD-bond", 1_000_000.0, date(2028, 1, 1), a1, currency="USD")
    pos2 = _position("EUR-bond", 1_000_000.0, date(2032, 1, 1), a2, currency="EUR")

    with pytest.raises(ValueError, match="currency"):
        analyze_portfolio([pos1, pos2], valuation_date=VALUATION_DATE)


def test_analyze_portfolio_rejects_analytics_priced_as_of_other_date():
    a1 = _analytics(0.04, 100.0, 99.0, 4.0, 0.04, 20.0)
    # priced as of a different as-of date than the portfolio valuation_date
    a2 = _analytics(0.06, 100.0, 99.0, 8.0, 0.08, 60.0, settlement_date=date(2024, 6, 30))
    pos1 = _position("A", 1_000_000.0, date(2028, 1, 1), a1)
    pos2 = _position("B", 1_000_000.0, date(2032, 1, 1), a2)

    with pytest.raises(ValueError, match="valuation_date"):
        analyze_portfolio([pos1, pos2], valuation_date=VALUATION_DATE)


def test_analyze_portfolio_long_short_hedge_nets_dv01_to_zero():
    """#34 'done when': a long position hedged by an offsetting short nets to
    DV01 ~= 0. The long holds 1mm of a bond with DV01 0.08/100 par; the short
    is sized so its dollar DV01 exactly offsets (DV01 0.04/100 par -> 2mm)."""
    long_bond = _analytics(0.05, 100.0, 99.0, 8.0, 0.08, 50.0)
    hedge = _analytics(0.03, 100.0, 99.5, 2.0, 0.04, 6.0)
    long_pos = _position("LONG", 1_000_000.0, date(2034, 1, 1), long_bond)
    short_pos = _position("HEDGE", -2_000_000.0, date(2026, 1, 1), hedge)

    result = analyze_portfolio([long_pos, short_pos], valuation_date=VALUATION_DATE)

    # long dollar DV01 = 0.08 * 1mm/100 = 800; short = 0.04 * -2mm/100 = -800
    assert result.dv01 == pytest.approx(0.0, abs=1e-9)
    # net market value is also near zero here, but gross weighting still works
    assert result.market_value == pytest.approx(long_pos.market_value + short_pos.market_value)


def test_analyze_portfolio_gross_weighting_handles_dollar_neutral_book():
    """A dollar-neutral long/short book has net market value zero, so net-value
    weighting would divide by zero. Gross (absolute) weighting still yields
    well-defined weights that sum to 1."""
    a_long = _analytics(0.04, 100.0, 99.0, 4.0, 0.04, 20.0)
    a_short = _analytics(0.06, 100.0, 99.0, 8.0, 0.08, 60.0)
    long_pos = _position("L", 1_000_000.0, date(2028, 1, 1), a_long)
    short_pos = _position("S", -1_000_000.0, date(2032, 1, 1), a_short)

    result = analyze_portfolio([long_pos, short_pos], valuation_date=VALUATION_DATE)

    assert result.market_value == pytest.approx(0.0, abs=1e-6)
    # equal gross exposure -> simple average of the two legs' metrics
    assert result.weighted_yield == pytest.approx(0.05)
    assert result.weighted_modified_duration == pytest.approx(6.0)
    assert result.weighted_convexity == pytest.approx(40.0)
    weights = [w for _, _, w in result.maturity_distribution]
    assert sum(weights) == pytest.approx(1.0)
    assert all(w >= 0 for w in weights)
