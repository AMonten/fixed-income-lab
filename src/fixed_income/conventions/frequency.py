"""Coupon frequency conventions."""

from __future__ import annotations

from enum import Enum


class Frequency(int, Enum):
    """Number of coupon payments per year.

    Backed by an ``int`` so a :class:`Frequency` can be used directly wherever
    "periods per year" is expected (e.g. ``coupon_rate / frequency``).
    """

    ANNUAL = 1
    SEMI_ANNUAL = 2
    QUARTERLY = 4
    MONTHLY = 12

    @property
    def periods_per_year(self) -> int:
        return int(self.value)

    @property
    def months_between_payments(self) -> int:
        if 12 % self.value != 0:
            raise ValueError(f"Frequency {self.name} does not divide evenly into 12 months")
        return 12 // self.value
