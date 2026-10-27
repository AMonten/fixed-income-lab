"""Independent reference validation (issue #37 / ROADMAP Bloque 5).

Every ``fixtures/*.json`` file is one reference case: instrument inputs, a
settlement date and quote, the *expected* outputs, and where those expected
numbers come from (``reference.engine`` / ``version`` / ``convention`` /
``source``) with the tolerance they're checked to. Sources are external to
this library by construction -- a published US Treasury worked example, a
frozen QuantLib run (see ``scripts/generate_reference_fixtures.py``), or a
hand derivation written out in the fixture -- so a test here failing means
the library disagrees with something it didn't compute itself.

Each ``(fixture, field)`` pair is its own test. A field listed under a
fixture's ``known_deviations`` is a *documented* disagreement with the
reference (reason + tracking issue in the JSON) and runs as a strict xfail:
it must keep failing, so the day a fix lands the xfail turns into an XPASS
and forces the deviation entry to be removed rather than silently going stale.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixed_income import analyze_bond, analyze_cash_flows
from fixed_income.cashflows.schedule import BusinessDayConvention
from fixed_income.conventions import Frequency, get_day_count_convention
from fixed_income.instruments.amortizing import AmortizingBond
from fixed_income.instruments.bond import Bond, ZeroCouponBond
from fixed_income.instruments.floating_rate import FloatingRateNote
from fixed_income.instruments.rate_index import RateIndex, RateObservation
from fixed_income.pricing.yield_convention import YieldConvention

FIXTURE_DIR = Path(__file__).parent / "fixtures"
REQUIRED_REFERENCE_KEYS = {"engine", "version", "convention", "source"}

_PRICE_FIELDS = {"clean_price", "dirty_price", "accrued_interest", "first_coupon"}
_RISK_FIELDS = {"modified_duration", "convexity"}


def _load() -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(FIXTURE_DIR.glob("*.json"))]


FIXTURES = _load()


def _build(spec: dict[str, Any]) -> Any:
    common = {
        "issue_date": date.fromisoformat(spec["issue_date"]),
        "maturity_date": date.fromisoformat(spec["maturity_date"]),
        "frequency": Frequency[spec["frequency"]],
        "day_count": get_day_count_convention(spec["day_count"]),
        "business_day_convention": BusinessDayConvention(spec["business_day_convention"]),
    }
    kind = spec["type"]
    if kind == "Bond":
        return Bond(spec["face_value"], spec["coupon_rate"], **common)
    if kind == "ZeroCouponBond":
        return ZeroCouponBond(spec["face_value"], **common)
    if kind == "AmortizingBond.with_level_principal":
        return AmortizingBond.with_level_principal(spec["original_face"], spec["coupon_rate"], **common)
    if kind == "FloatingRateNote":
        idx = spec["rate_index"]
        index = RateIndex(
            idx["name"],
            tuple(RateObservation(date.fromisoformat(d), r) for d, r in idx["observations"]),
            forward_assumption=idx["forward_assumption"],
        )
        return FloatingRateNote(spec["face_value"], spec["spread"], rate_index=index, **common)
    raise ValueError(f"Unknown instrument type in fixture: {kind}")


def _actual(fixture: dict[str, Any], field: str) -> Any:
    """The library's own value for ``field``, computed from the fixture's inputs only."""
    inst = _build(fixture["instrument"])
    settlement = date.fromisoformat(fixture["settlement_date"])
    ytm = fixture["quote"].get("ytm")
    yc = YieldConvention.street(inst.frequency)

    if field == "cash_flows":
        return [
            {"payment_date": cf.payment_date.isoformat(), "coupon": cf.coupon, "principal": cf.principal}
            for cf in inst.cash_flows()
        ]
    if field == "first_coupon":
        return inst.cash_flows()[0].coupon
    if isinstance(inst, (Bond, ZeroCouponBond)):
        if field == "ytm_from_clean":
            clean = fixture["expected"]["clean_price"]
            return analyze_bond(inst, settlement, yield_convention=yc, clean_price=clean).yield_to_maturity
        if field == "accrued_interest" and ytm is None:
            return analyze_bond(
                inst, settlement, yield_convention=yc, yield_to_maturity=0.05
            ).accrued_interest
        return getattr(analyze_bond(inst, settlement, yield_convention=yc, yield_to_maturity=ytm), field)
    result = analyze_cash_flows(
        inst.cash_flows_after(settlement),
        inst.face_value,
        settlement,
        yc,
        inst.day_count,
        yield_to_maturity=ytm,
    )
    return getattr(result, field)


def _matches(field: str, actual: Any, expected: Any, tol: dict[str, Any]) -> bool:
    if field == "cash_flows":
        if len(actual) != len(expected):
            return False
        return all(
            a["payment_date"] == e["payment_date"]
            and math.isclose(a["coupon"], e["coupon"], rel_tol=0, abs_tol=tol["price"])
            and math.isclose(a["principal"], e["principal"], rel_tol=0, abs_tol=tol["price"])
            for a, e in zip(actual, expected, strict=True)
        )
    if field == "first_coupon":
        return math.isclose(actual, expected, rel_tol=0, abs_tol=tol.get("coupon", tol["price"]))
    if field in _PRICE_FIELDS:
        return math.isclose(actual, expected, rel_tol=0, abs_tol=tol["price"])
    if field == "ytm_from_clean":
        return math.isclose(actual, expected, rel_tol=0, abs_tol=tol["yield"])
    if field in _RISK_FIELDS:
        return math.isclose(actual, expected, rel_tol=tol["risk_rel"], abs_tol=0)
    raise ValueError(f"No comparison rule for field {field!r}")


def _cases() -> list[Any]:
    cases = []
    for fx in FIXTURES:
        deviations: dict[str, list[str]] = {}
        for dev in fx.get("known_deviations", {}).values():
            for field in dev["fields"]:
                deviations.setdefault(field, []).append(f"#{dev['issue']}: {dev['reason']}")
        for field in fx["expected"]:
            marks = []
            if field in deviations:
                reason = "known deviation -- " + " | ".join(deviations[field])
                marks.append(pytest.mark.xfail(strict=True, reason=reason))
            cases.append(pytest.param(fx, field, id=f"{fx['id']}::{field}", marks=marks))
    return cases


@pytest.mark.parametrize(("fixture", "field"), _cases())
def test_matches_reference(fixture, field):
    expected = fixture["expected"][field]
    actual = _actual(fixture, field)
    assert _matches(field, actual, expected, fixture["tolerance"]), (
        f"{fixture['id']}::{field} vs {fixture['reference']['engine']} "
        f"({fixture['reference']['source']}): expected {expected!r}, got {actual!r}"
    )


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f["id"])
def test_fixture_declares_its_source_and_tolerance(fixture):
    assert REQUIRED_REFERENCE_KEYS <= fixture["reference"].keys()
    assert all(fixture["reference"][k] for k in REQUIRED_REFERENCE_KEYS)
    assert "price" in fixture["tolerance"] and "yield" in fixture["tolerance"]
    for dev in fixture.get("known_deviations", {}).values():
        assert dev["reason"] and dev["issue"] and dev["fields"]
        assert set(dev["fields"]) <= fixture["expected"].keys()


def test_every_supported_instrument_type_has_a_reference_case():
    covered = {fx["instrument"]["type"] for fx in FIXTURES}
    assert {"Bond", "ZeroCouponBond", "AmortizingBond.with_level_principal", "FloatingRateNote"} <= covered
