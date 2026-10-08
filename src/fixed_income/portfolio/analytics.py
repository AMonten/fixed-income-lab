"""Portfolio-level analytics: a market-value-weighted roll-up of security analytics.

Security-level analytics (:mod:`fixed_income.analytics`) is the primary
product of this library; portfolio analytics is a thin, secondary layer on
top of it. A :class:`PortfolioPosition` pairs a par (notional) amount with a
:class:`~fixed_income.analytics.SecurityAnalytics` snapshot computed per 100
par — nothing here re-derives pricing or risk, it only weights and sums.

A portfolio roll-up is only coherent when every position is measured on the
same footing:

* **One valuation date.** Every position's analytics snapshot must be computed
  *as of* the portfolio's ``valuation_date`` (the "as of" date the roll-up is
  reported for). Individual positions may still *settle* on different dates —
  a real book holds trades settling on different days — so the per-position
  ``settlement_date`` is deliberately *not* forced to be common; only the
  valuation date is.
* **One currency.** Market value and DV01 are additive only within a single
  currency. Summing across currencies is meaningless without an FX conversion
  this layer does not perform, so mixed currencies are rejected rather than
  silently summed.
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
            Its ``settlement_date`` is the *as-of* (valuation) date the
            snapshot was priced for, and must match the portfolio's
            ``valuation_date`` when rolled up (see :func:`analyze_portfolio`).
        settlement_date: The date this trade settles (delivery vs. payment).
            Positions in one portfolio may settle on different dates.
        currency: ISO-like currency code the position is denominated in. All
            positions in a portfolio must share one currency.
        trade_date: The date this trade was executed, if known. Must not be
            after ``settlement_date``.
    """

    identifier: str
    par_amount: float
    maturity_date: date
    analytics: SecurityAnalytics
    settlement_date: date
    currency: str = "USD"
    trade_date: date | None = None

    def __post_init__(self) -> None:
        if self.par_amount <= 0:
            raise ValueError("par_amount must be positive")
        if not self.currency:
            raise ValueError("currency must be a non-empty currency code")
        if self.trade_date is not None and self.settlement_date < self.trade_date:
            raise ValueError(
                f"settlement_date ({self.settlement_date}) cannot be before "
                f"trade_date ({self.trade_date}) for position {self.identifier!r}"
            )

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

    valuation_date: date
    """The common "as of" date every position's analytics were priced for."""
    currency: str
    """The single currency every position in the portfolio is denominated in."""
    market_value: float
    clean_market_value: float
    weighted_yield: float
    weighted_modified_duration: float
    dv01: float
    weighted_convexity: float
    maturity_distribution: tuple[tuple[str, date, float], ...]
    """``(identifier, maturity_date, weight)`` by dirty market-value share."""


def analyze_portfolio(
    positions: list[PortfolioPosition],
    valuation_date: date,
) -> PortfolioAnalytics:
    """Roll up a list of positions into portfolio-level analytics.

    Weighting is by dirty market value throughout (weighted yield, weighted
    modified duration, weighted convexity); DV01 is additive across positions.

    Args:
        positions: The holdings to aggregate. Must be non-empty, share a single
            ``currency``, and each carry an analytics snapshot priced as of
            ``valuation_date``.
        valuation_date: The "as of" date the roll-up is reported for. Every
            position's ``analytics.settlement_date`` (its pricing/as-of date)
            must equal this; positions priced as of a different date are
            rejected rather than summed as if they shared one date.

    Raises:
        ValueError: If ``positions`` is empty, the positions span more than one
            currency, any position's analytics were priced as of a date other
            than ``valuation_date``, or total market value is zero.
    """
    if not positions:
        raise ValueError("Portfolio must contain at least one position")

    currencies = {p.currency for p in positions}
    if len(currencies) > 1:
        raise ValueError(
            "All positions must share one currency to be aggregated; got "
            f"{sorted(currencies)}. Convert to a common base currency first."
        )

    mismatched = {
        p.identifier: p.analytics.settlement_date
        for p in positions
        if p.analytics.settlement_date != valuation_date
    }
    if mismatched:
        raise ValueError(
            f"Every position's analytics must be priced as of the portfolio "
            f"valuation_date ({valuation_date}); these were priced as of a "
            f"different date: {mismatched}"
        )

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
        valuation_date=valuation_date,
        currency=currencies.pop(),
        market_value=total_market_value,
        clean_market_value=total_clean_market_value,
        weighted_yield=weighted_yield,
        weighted_modified_duration=weighted_modified_duration,
        dv01=total_dv01,
        weighted_convexity=weighted_convexity,
        maturity_distribution=maturity_distribution,
    )


__all__ = ["PortfolioPosition", "PortfolioAnalytics", "analyze_portfolio"]
