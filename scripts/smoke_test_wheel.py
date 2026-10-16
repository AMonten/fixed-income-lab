"""Smoke test for an *installed* fixed-income-lab wheel (CI, see #45).

Run from outside the repo root against a clean environment where only the
built wheel is installed, so ``fixed_income`` cannot resolve to ``src/``.
Checks that the package imports from site-packages, ships ``py.typed`` (PEP 561,
#42), and reproduces the README Quickstart numbers.
"""

from __future__ import annotations

import importlib.metadata
import math
import sys
from datetime import date
from pathlib import Path

import fixed_income
from fixed_income import analyze_bond
from fixed_income.conventions import Actual365Fixed, Frequency
from fixed_income.instruments.bond import Bond

package_dir = Path(fixed_income.__file__).resolve().parent
if "site-packages" not in package_dir.parts:
    sys.exit(f"fixed_income imported from {package_dir}, not from the installed wheel")
if not (package_dir / "py.typed").is_file():
    sys.exit("py.typed missing from the installed package")

dist_version = importlib.metadata.version("fixed-income-lab")
if fixed_income.__version__ != dist_version:
    sys.exit(f"__version__ {fixed_income.__version__} != distribution version {dist_version}")

# README Quickstart: keep these numbers in sync with the README output block.
bond = Bond(
    face_value=100.0,
    coupon_rate=0.05,
    issue_date=date(2020, 1, 15),
    maturity_date=date(2030, 1, 15),
    frequency=Frequency.SEMI_ANNUAL,
    day_count=Actual365Fixed(),
)
result = analyze_bond(bond, date(2024, 4, 15), yield_to_maturity=0.045)
expected = {
    "clean_price": 102.5016,
    "dirty_price": 103.7516,
    "accrued_interest": 1.2500,
    "modified_duration": 4.9081,
    "convexity": 28.7150,
}
for field, value in expected.items():
    actual = getattr(result, field)
    if not math.isclose(actual, value, abs_tol=5e-5):
        sys.exit(f"{field}: got {actual:.6f}, README says {value}")
if not math.isclose(result.dv01, 0.050922, abs_tol=5e-7):
    sys.exit(f"dv01: got {result.dv01:.7f}, README says 0.050922")

print(f"OK: fixed-income-lab {dist_version} from {package_dir}")
