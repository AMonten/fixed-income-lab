"""Regenerate the QuantLib-sourced fixtures in ``tests/reference/fixtures/``.

QuantLib is a *reference engine*, never a runtime or CI dependency (see
CLAUDE.md / ROADMAP Bloque 5): this script runs it once, offline, and freezes
its numbers into JSON alongside ``reference.version``, so CI validates against
a declared, reproducible value without installing QuantLib. Re-run after a
QuantLib upgrade and review the diff -- a changed number is a finding, not
noise::

    pip install -e ".[reference]"
    python scripts/generate_reference_fixtures.py

Every case is set up so the QuantLib convention is *the same convention* the
library computes, not merely a similar one: ``NullCalendar`` + ``Unadjusted``
payment dates (street yield discounts on unadjusted dates), backward schedule
generation from maturity without EOM (V1 schedules only produce short front
stubs), ``Compounded`` at the coupon frequency, and ``ActualActual.ISMA``
built with the schedule so stubs get their regular reference period. Under
those settings QuantLib's yield time for each flow -- ``dc.yearFraction``
accumulated period by period with reference periods -- is exactly street
quasi-coupon counting.

The Treasury (31 CFR 356 App. B) and hand-derived fixtures are *not*
generated here: their source is a published/derived number, written by hand.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import QuantLib as ql

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "reference" / "fixtures"

_FREQ = {"ANNUAL": ql.Annual, "SEMI_ANNUAL": ql.Semiannual, "QUARTERLY": ql.Quarterly}


def _qd(d: date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def _schedule(issue: date, maturity: date, frequency: str) -> ql.Schedule:
    return ql.Schedule(
        _qd(issue),
        _qd(maturity),
        ql.Period(_FREQ[frequency]),
        ql.NullCalendar(),
        ql.Unadjusted,
        ql.Unadjusted,
        ql.DateGeneration.Backward,
        False,
    )


def _day_counter(name: str, schedule: ql.Schedule) -> ql.DayCounter:
    if name == "ACT/ACT-ICMA":
        return ql.ActualActual(ql.ActualActual.ISMA, schedule)
    return {
        "ACT/365": ql.Actual365Fixed(),
        "30/360": ql.Thirty360(ql.Thirty360.BondBasis),
        "30E/360": ql.Thirty360(ql.Thirty360.European),
    }[name]


def _analytics(bond: ql.Bond, dc: ql.DayCounter, frequency: str, settlement: date, y: float) -> dict:
    ql.Settings.instance().evaluationDate = _qd(settlement)
    s, f = _qd(settlement), _FREQ[frequency]
    rate = ql.InterestRate(y, dc, ql.Compounded, f)
    clean = ql.BondFunctions.cleanPrice(bond, rate, s)
    accrued = ql.BondFunctions.accruedAmount(bond, s)
    flows: dict[str, dict[str, float]] = {}
    for cf in bond.cashflows():
        key = cf.date().ISO()
        entry = flows.setdefault(key, {"coupon": 0.0, "principal": 0.0})
        if ql.as_coupon(cf) is not None:
            entry["coupon"] += cf.amount()
        else:
            entry["principal"] += cf.amount()
    return {
        "clean_price": clean,
        "dirty_price": clean + accrued,
        "accrued_interest": accrued,
        "modified_duration": ql.BondFunctions.duration(bond, rate, ql.Duration.Modified, s),
        "convexity": ql.BondFunctions.convexity(bond, rate, s),
        "cash_flows": [{"payment_date": d, **v} for d, v in sorted(flows.items())],
    }


def _fixed_case(case: dict) -> dict:
    inst = case["instrument"]
    issue, maturity = date.fromisoformat(inst["issue_date"]), date.fromisoformat(inst["maturity_date"])
    sched = _schedule(issue, maturity, inst["frequency"])
    dc = _day_counter(inst["day_count"], sched)
    if inst["type"] == "Bond":
        bond = ql.FixedRateBond(0, inst["face_value"], sched, [inst["coupon_rate"]], dc, ql.Unadjusted)
    elif inst["type"] == "ZeroCouponBond":
        bond = ql.ZeroCouponBond(
            0, ql.NullCalendar(), inst["face_value"], _qd(maturity), ql.Unadjusted, 100.0, _qd(issue)
        )
    elif inst["type"] == "AmortizingBond.with_level_principal":
        n = len(sched) - 1
        face = inst["original_face"]
        notionals = [face - face * k / n for k in range(n)]
        bond = ql.AmortizingFixedRateBond(0, notionals, sched, [inst["coupon_rate"]], dc, ql.Unadjusted)
    else:
        raise ValueError(inst["type"])
    expected = _analytics(
        bond, dc, inst["frequency"], date.fromisoformat(case["settlement_date"]), case["ytm"]
    )
    if inst["type"] == "AmortizingBond.with_level_principal":
        # QuantLib quotes an amortizer per 100 of *current* notional; the library
        # quotes every price per 100 of original face (README "Assumptions").
        # Rescale explicitly -- durations/convexity are ratios, basis-invariant.
        factor = bond.notional(_qd(date.fromisoformat(case["settlement_date"]))) / inst["original_face"]
        for name in ("clean_price", "dirty_price", "accrued_interest"):
            expected[name] *= factor
    else:
        expected["ytm_from_clean"] = case["ytm"]
    for name in case.get("omit", ()):
        del expected[name]
    return {
        "id": case["id"],
        "description": case["description"],
        "reference": {
            "engine": "QuantLib",
            "version": ql.__version__,
            "convention": case["convention"],
            "source": "scripts/generate_reference_fixtures.py",
        },
        "tolerance": {"price": 1e-8, "yield": 1e-10, "risk_rel": 1e-8},
        "instrument": inst,
        "settlement_date": case["settlement_date"],
        "quote": {"ytm": case["ytm"]},
        "expected": expected,
        "known_deviations": case.get("known_deviations", {}),
    }


_ICMA_STREET = (
    "ACT/ACT ICMA accrual, street yield (unadjusted quasi-coupon periods), compounded at coupon frequency"
)

CASES = [
    {
        "id": "quantlib_eur_icma_annual_leap_reference_period",
        "description": (
            "EUR-style annual 4% bond under ACT/ACT ICMA, settled 2024-03-01 inside a coupon period "
            "(2023-06-15 -> 2024-06-15) that contains 29 Feb 2024: accrued and the street fraction "
            "must divide by the 366-day reference period."
        ),
        "convention": _ICMA_STREET,
        "instrument": {
            "type": "Bond",
            "face_value": 100.0,
            "coupon_rate": 0.04,
            "issue_date": "2020-06-15",
            "maturity_date": "2030-06-15",
            "frequency": "ANNUAL",
            "day_count": "ACT/ACT-ICMA",
            "business_day_convention": "none",
        },
        "settlement_date": "2024-03-01",
        "ytm": 0.035,
    },
    {
        "id": "quantlib_eur_icma_semiannual_short_first_coupon",
        "description": (
            "Semi-annual 5% bond under ACT/ACT ICMA issued 2020-03-01 into a 15 Jan/15 Jul grid: short "
            "first (stub) coupon prorated over the regular 2020-01-15 -> 2020-07-15 reference period. "
            "Settled after the stub, in a regular period."
        ),
        "convention": _ICMA_STREET,
        "instrument": {
            "type": "Bond",
            "face_value": 100.0,
            "coupon_rate": 0.05,
            "issue_date": "2020-03-01",
            "maturity_date": "2025-01-15",
            "frequency": "SEMI_ANNUAL",
            "day_count": "ACT/ACT-ICMA",
            "business_day_convention": "none",
        },
        "settlement_date": "2021-03-10",
        "ytm": 0.042,
    },
    {
        "id": "quantlib_eur_icma_semiannual_settled_inside_short_first_coupon",
        "description": (
            "Same bond as the short-first-coupon case, but settled *inside* the stub (2020-05-01): "
            "exercises the street fraction of an irregular first period."
        ),
        "convention": _ICMA_STREET,
        "instrument": {
            "type": "Bond",
            "face_value": 100.0,
            "coupon_rate": 0.05,
            "issue_date": "2020-03-01",
            "maturity_date": "2025-01-15",
            "frequency": "SEMI_ANNUAL",
            "day_count": "ACT/ACT-ICMA",
            "business_day_convention": "none",
        },
        "settlement_date": "2020-05-01",
        "ytm": 0.042,
    },
    {
        "id": "quantlib_us_corporate_30_360_mid_period",
        "description": "US corporate-style semi-annual 6% bond, 30/360 bond basis, settled mid-period.",
        "convention": "30/360 US (bond basis) accrual, street yield, semi-annual compounding",
        "instrument": {
            "type": "Bond",
            "face_value": 100.0,
            "coupon_rate": 0.06,
            "issue_date": "2021-02-15",
            "maturity_date": "2031-02-15",
            "frequency": "SEMI_ANNUAL",
            "day_count": "30/360",
            "business_day_convention": "none",
        },
        "settlement_date": "2024-05-20",
        "ytm": 0.0525,
    },
    {
        "id": "quantlib_eurobond_30e_360_mid_period",
        "description": "Annual 3.25% Eurobond under 30E/360, settled on a 31st (exercises the 31 -> 30 cap).",
        "convention": "30E/360 accrual, street yield, annual compounding",
        "instrument": {
            "type": "Bond",
            "face_value": 100.0,
            "coupon_rate": 0.0325,
            "issue_date": "2021-09-30",
            "maturity_date": "2031-09-30",
            "frequency": "ANNUAL",
            "day_count": "30E/360",
            "business_day_convention": "none",
        },
        "settlement_date": "2024-01-31",
        "ytm": 0.029,
    },
    {
        "id": "quantlib_zero_coupon_act365",
        "description": "10-year zero-coupon bond, ACT/365F, semi-annual compounding, mid-life settlement.",
        "convention": "ACT/365F time to maturity, semi-annual compounding",
        "instrument": {
            "type": "ZeroCouponBond",
            "face_value": 100.0,
            "issue_date": "2020-01-15",
            "maturity_date": "2030-01-15",
            "frequency": "SEMI_ANNUAL",
            "day_count": "ACT/365",
            "business_day_convention": "none",
        },
        "settlement_date": "2024-04-15",
        "ytm": 0.045,
    },
    {
        "id": "quantlib_level_principal_amortizer_30_360",
        "description": (
            "5-year semi-annual 6% level-principal amortizer (10 x 10.0), 30/360 bond basis: interest on "
            "beginning-of-period outstanding. Clean price / accrued omitted: the library has no "
            "accrued-interest API for AmortizingBond yet, so dirty price is what it validates."
        ),
        "omit": ("clean_price", "accrued_interest"),
        "convention": (
            "30/360 US accrual on outstanding principal, street yield, semi-annual compounding; QuantLib's "
            "per-100-of-current-notional price rescaled to per 100 of original face (the library's basis)"
        ),
        "instrument": {
            "type": "AmortizingBond.with_level_principal",
            "original_face": 100.0,
            "coupon_rate": 0.06,
            "issue_date": "2022-03-01",
            "maturity_date": "2027-03-01",
            "frequency": "SEMI_ANNUAL",
            "day_count": "30/360",
            "business_day_convention": "none",
        },
        "settlement_date": "2023-01-10",
        "ytm": 0.055,
    },
]


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        fixture = _fixed_case(case)
        path = FIXTURES / f"{case['id']}.json"
        path.write_text(json.dumps(fixture, indent=2) + "\n")
        print(f"wrote {path.relative_to(FIXTURES.parents[2])}")


if __name__ == "__main__":
    main()
