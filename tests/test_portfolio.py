from datetime import date

import pytest

from fixed_income.analytics import SecurityAnalytics
from fixed_income.portfolio.analytics import PortfolioPosition, analyze_portfolio


def _analytics(yield_to_maturity, dirty_price, clean_price, mod_dur, dv01, convexity):
    return SecurityAnalytics(
        settlement_date=date(2024, 1, 1),
        yield_to_maturity=yield_to_maturity,
        dirty_price=dirty_price,
        clean_price=clean_price,
        accrued_interest=dirty_price - clean_price,
        macaulay_duration=mod_dur,
        modified_duration=mod_dur,
        dv01=dv01,
        convexity=convexity,
    )


def test_portfolio_position_market_value_scales_with_par_amount():
    analytics = _analytics(0.05, 101.0, 100.0, 5.0, 0.05, 30.0)
    pos = PortfolioPosition("A", par_amount=1_000_000.0, maturity_date=date(2030, 1, 1), analytics=analytics)
    assert pos.market_value == pytest.approx(1_010_000.0)
    assert pos.clean_market_value == pytest.approx(1_000_000.0)
    assert pos.dv01 == pytest.approx(500.0)


def test_portfolio_position_rejects_non_positive_par_amount():
    analytics = _analytics(0.05, 100.0, 100.0, 5.0, 0.05, 30.0)
    with pytest.raises(ValueError):
        PortfolioPosition("A", par_amount=0.0, maturity_date=date(2030, 1, 1), analytics=analytics)


def test_analyze_portfolio_weighted_metrics_are_market_value_weighted():
    a1 = _analytics(0.04, 100.0, 99.0, 4.0, 0.04, 20.0)
    a2 = _analytics(0.06, 100.0, 99.0, 8.0, 0.08, 60.0)
    pos1 = PortfolioPosition("A", par_amount=1_000_000.0, maturity_date=date(2028, 1, 1), analytics=a1)
    pos2 = PortfolioPosition("B", par_amount=1_000_000.0, maturity_date=date(2032, 1, 1), analytics=a2)

    result = analyze_portfolio([pos1, pos2])

    assert result.market_value == pytest.approx(pos1.market_value + pos2.market_value)
    # equal market values -> simple average of yield/duration/convexity
    assert result.weighted_yield == pytest.approx(0.05)
    assert result.weighted_modified_duration == pytest.approx(6.0)
    assert result.weighted_convexity == pytest.approx(40.0)
    assert result.dv01 == pytest.approx(pos1.dv01 + pos2.dv01)


def test_analyze_portfolio_maturity_distribution_weights_sum_to_one():
    a1 = _analytics(0.04, 100.0, 99.0, 4.0, 0.04, 20.0)
    a2 = _analytics(0.06, 100.0, 99.0, 8.0, 0.08, 60.0)
    pos1 = PortfolioPosition("A", par_amount=3_000_000.0, maturity_date=date(2028, 1, 1), analytics=a1)
    pos2 = PortfolioPosition("B", par_amount=1_000_000.0, maturity_date=date(2032, 1, 1), analytics=a2)

    result = analyze_portfolio([pos1, pos2])
    weights = [w for _, _, w in result.maturity_distribution]
    assert sum(weights) == pytest.approx(1.0)
    assert weights[0] > weights[1]  # position A has 3x the par amount


def test_analyze_portfolio_requires_at_least_one_position():
    with pytest.raises(ValueError):
        analyze_portfolio([])
