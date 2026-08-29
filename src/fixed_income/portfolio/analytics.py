"""Portfolio-level analytics: a market-value-weighted roll-up of security analytics.

Security-level analytics (:mod:`fixed_income.analytics`) is the primary
product of this library; portfolio analytics is a thin, secondary layer on
top of it. A :class:`PortfolioPosition` pairs a par (notional) amount with a
:class:`~fixed_income.analytics.SecurityAnalytics` snapshot computed per 100
par — nothing here re-derives pricing or risk, it only weights and sums.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..analytics import SecurityAnalytics


@dataclass(frozen=True)
class PortfolioPosition:
    """One holding in a portfolio.

    Attributes:
        identifier: A label for the position (e.g. CUSIP, ticker, name).
        par_amount: The actual notional held (not per-100 par).
        maturity_date: The security's maturity date.
        analytics: Per-100-par price/yield/risk snapshot for this security.
    """

    identifier: str
    par_amount: float
    maturity_date: date
    analytics: SecurityAnalytics

    def __post_init__(self) -> None:
        if self.par_amount <= 0:
            raise ValueError("par_amount must be positive")

    @property
    def market_value(self) -> float:
        """Dirty (full) market value of the position."""
        return self.analytics.dirty_price * self.par_amount / 100.0

    @property
    def clean_market_value(self) -> float:
        return self.analytics.clean_price * self.par_amount / 100.0

    @property
    def dv01(self) -> float:
        """Dollar DV01 of the position (scaled from the per-100-par DV01)."""
        return self.analytics.dv01 * self.par_amount / 100.0


@dataclass(frozen=True)
class PortfolioAnalytics:
    """Market-value-weighted analytics across a set of positions."""

    market_value: float
    clean_market_value: float
    weighted_yield: float
    weighted_modified_duration: float
    dv01: float
    weighted_convexity: float
    maturity_distribution: tuple[tuple[str, date, float], ...]
    """``(identifier, maturity_date, weight)`` by dirty market-value share."""


def analyze_portfolio(positions: list[PortfolioPosition]) -> PortfolioAnalytics:
    """Roll up a list of positions into portfolio-level analytics.

    Weighting is by dirty market value throughout (weighted yield, weighted
    modified duration, weighted convexity); DV01 is additive across positions.
    """
    if not positions:
        raise ValueError("Portfolio must contain at least one position")

    total_market_value = sum(p.market_value for p in positions)
    if total_market_value == 0:
        raise ValueError("Total portfolio market value is zero; cannot compute weighted analytics")

    def weighted(metric_fn) -> float:
        return sum(p.market_value * metric_fn(p.analytics) for p in positions) / total_market_value

    weighted_yield = weighted(lambda a: a.yield_to_maturity)
    weighted_modified_duration = weighted(lambda a: a.modified_duration)
    weighted_convexity = weighted(lambda a: a.convexity)
    total_dv01 = sum(p.dv01 for p in positions)
    total_clean_market_value = sum(p.clean_market_value for p in positions)

    maturity_distribution = tuple(
        (p.identifier, p.maturity_date, p.market_value / total_market_value) for p in positions
    )

    return PortfolioAnalytics(
        market_value=total_market_value,
        clean_market_value=total_clean_market_value,
        weighted_yield=weighted_yield,
        weighted_modified_duration=weighted_modified_duration,
        dv01=total_dv01,
        weighted_convexity=weighted_convexity,
        maturity_distribution=maturity_distribution,
    )


__all__ = ["PortfolioPosition", "PortfolioAnalytics", "analyze_portfolio"]
