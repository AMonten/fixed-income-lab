"""Reference-rate representation for floating-rate instruments.

V1 does not implement market-curve bootstrapping infrastructure. Instead, a
:class:`RateIndex` holds a set of *observed* historical fixings plus an
optional flat *forward-rate assumption* used for any reset date that has not
yet been observed. Callers must be able to tell which is which, so
:meth:`RateIndex.is_observed` and :meth:`RateIndex.rate_on` never blend the
two silently: a reset date is resolved from observations first, and only
falls back to the assumption when explicitly allowed to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class RateObservation:
    """A single observed fixing of a reference rate.

    Attributes:
        fixing_date: The date the rate was observed/published.
        rate: The observed rate, as a decimal (e.g. ``0.0525`` for 5.25%).
    """

    fixing_date: date
    rate: float


@dataclass
class RateIndex:
    """A reference rate index (e.g. SOFR, EURIBOR-3M) with a fixing history.

    Attributes:
        name: Human-readable index name.
        observations: Known historical fixings, in any order.
        forward_assumption: A single flat rate (decimal) assumed to prevail
            for any reset date without an observed fixing. This is an
            explicit modelling assumption, not a market-implied forward
            curve — V1 intentionally avoids curve-bootstrapping machinery.
        floor: Optional rate floor (decimal) applied to the coupon
            reference rate, e.g. ``0.0`` for a "floored at zero" note.
    """

    name: str
    observations: tuple[RateObservation, ...] = field(default_factory=tuple)
    forward_assumption: float | None = None
    floor: float | None = None

    def __post_init__(self) -> None:
        self.observations = tuple(sorted(self.observations, key=lambda o: o.fixing_date))

    def is_observed(self, fixing_date: date) -> bool:
        return any(o.fixing_date == fixing_date for o in self.observations)

    def observed_rate(self, fixing_date: date) -> float | None:
        for o in self.observations:
            if o.fixing_date == fixing_date:
                return o.rate
        return None

    def rate_on(self, fixing_date: date) -> float:
        """Resolve the reference rate for ``fixing_date``.

        Uses an observed fixing when available, otherwise falls back to
        ``forward_assumption``. Raises if neither is available, so a missing
        assumption fails loudly rather than silently pricing off ``None``.
        """
        observed = self.observed_rate(fixing_date)
        if observed is not None:
            return observed
        if self.forward_assumption is not None:
            return self.forward_assumption
        raise ValueError(
            f"No observed fixing for {self.name} on {fixing_date} and no "
            "forward_assumption was provided."
        )

    def apply_floor(self, rate: float) -> float:
        if self.floor is not None:
            return max(rate, self.floor)
        return rate
