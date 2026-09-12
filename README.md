# fixed-income-lab

[![CI](https://github.com/AMonten/fixed-income-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/AMonten/fixed-income-lab/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A fixed-income analytics toolkit for pricing, cash-flow modelling, risk metrics, and
amortizing securities — built to answer one question consistently across very
different instruments:

> **How can fixed-income securities be represented, valued, and analyzed
> consistently across different structures?**

A fixed-rate bullet bond, a zero-coupon bond, a floating-rate note, and an
amortizing/sinkable bond look unrelated on the surface. This library treats them
as one thing underneath: a list of dated cash flows plus a face value. Every
pricing, yield, and risk function is written once against that shared
representation — not once per instrument type.

> **This is not a trading application, market-data platform, or valuation system.**
> It is an educational/research toolkit. See [Assumptions & limitations](#assumptions--limitations).

## Contents

- [Why this project exists](#why-this-project-exists)
- [Supported instruments](#supported-instruments)
- [Architecture](#architecture)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Methodology](#methodology)
- [Streamlit app](#streamlit-app)
- [Testing](#testing)
- [Assumptions & limitations](#assumptions--limitations)
- [Roadmap](#roadmap)

## Why this project exists

Most finance-adjacent code samples are either a single price/yield calculator or a
stock-market dashboard. Neither shows how real fixed-income analytics libraries are
put together: a shared cash-flow engine, pluggable day-count and yield conventions,
and risk metrics that consume *any* instrument's cash flows the same way.
`fixed-income-lab` is built the way that layer actually looks — small, typed
domain objects; a cash-flow engine that both a bullet bond and a factor-amortizing
pool call into; and pricing/risk functions that only ever see cash flows and a
face value, never instrument-specific branching.

## Supported instruments

| Instrument | Module | Notes |
|---|---|---|
| Fixed-rate (bullet) bond | `instruments.bond.Bond` | Any day-count/frequency combination |
| Zero-coupon bond | `instruments.bond.ZeroCouponBond` | Single redemption cash flow |
| Floating-rate note | `instruments.floating_rate.FloatingRateNote` | Reference rate + spread, explicit forward assumption, optional floor |
| Amortizing bond | `instruments.amortizing.AmortizingBond` | Level-principal, explicit sinking-fund schedule, or factor-history-driven |

Callable bonds, MBS, CMO tranches, and other structured notes are explicitly out of
scope for V1 (see [Roadmap](#roadmap)) — the architecture (a pluggable
`AmortizationPlan`, a generic cash-flow/analytics pipeline) is built so they can be
added without a rewrite, not so they ship half-finished today.

## Architecture

```
src/fixed_income/
├── instruments/        # Bond, ZeroCouponBond, FloatingRateNote, AmortizingBond, RateIndex
├── cashflows/           # schedule generation + cash-flow generation engine
├── conventions/         # day-count (ACT/360, ACT/365, 30/360) and frequency
├── pricing/             # present value, yield convention, YTM solver, accrued interest, curves
├── risk/                # duration, convexity, DV01, rate-shock scenarios
├── portfolio/           # market-value-weighted roll-up across positions
└── analytics.py         # SecurityAnalytics facade tying pricing + risk together
```

The dependency direction is one-way: `instruments` depend on `cashflows` and
`conventions`; `pricing` and `risk` depend on `cashflows` and `conventions` but
never on a specific instrument; `analytics.py` and `portfolio` sit on top of
everything else. This is what lets `risk.duration.dv01`, say, price a bullet
bond, a floating-rate note (under a fixed forward assumption), and an amortizing
bond with the exact same code path — it only ever sees `CashFlow` objects.

## Installation

```bash
git clone https://github.com/AMonten/fixed-income-lab.git
cd fixed-income-lab
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,app]"
```

Requires Python 3.10+. Core dependencies are `numpy` and `scipy`; the `app` extra
adds `streamlit`, `pandas`, and `plotly` for the demo UI; `dev` adds `pytest`,
`ruff`, and `mypy`.

## Quickstart

```python
from datetime import date
from fixed_income.instruments.bond import Bond
from fixed_income.conventions import Frequency, Actual365Fixed
from fixed_income import analyze_bond

bond = Bond(
    face_value=100.0,
    coupon_rate=0.05,
    issue_date=date(2020, 1, 15),
    maturity_date=date(2030, 1, 15),
    frequency=Frequency.SEMI_ANNUAL,
    day_count=Actual365Fixed(),
)

settlement = date(2024, 4, 15)
result = analyze_bond(bond, settlement, yield_to_maturity=0.045)

print(f"Clean price:        {result.clean_price:.4f}")
print(f"Dirty price:         {result.dirty_price:.4f}")
print(f"Accrued interest:    {result.accrued_interest:.4f}")
print(f"Modified duration:   {result.modified_duration:.4f}")
print(f"DV01 (per 100 par):  {result.dv01:.6f}")
print(f"Convexity:           {result.convexity:.4f}")
```

```
Clean price:        102.5024
Dirty price:         103.7490
Accrued interest:    1.2466
Modified duration:   4.9132
DV01 (per 100 par):  0.050974
Convexity:           28.7726
```

More worked examples — zero-coupon bonds, floating-rate notes, amortizing/sinkable
bonds, scenario analysis, and portfolio roll-ups — are in
[`notebooks/examples/`](notebooks/examples/).

## Methodology

All prices are quoted **per 100 par**. All rates (coupon, yield, spread, floor) are
decimals (5% = `0.05`).

### Day-count conventions

A day-count convention turns a period `[start, end)` into a year fraction. Three are
implemented; more can be added by writing one class and registering it
(`conventions.day_count.register_day_count_convention`):

| Convention | Formula |
|---|---|
| ACT/360 | `year_fraction = (end - start).days / 360` |
| ACT/365 (Fixed) | `year_fraction = (end - start).days / 365` |
| 30/360 (Bond Basis) | `days = (Y2-Y1)*360 + (M2-M1)*30 + (D2-D1)`, with `D1 -> 30` if `D1` is the 31st or last day of February, and `D2 -> 30` if `D2` is 31 and `D1` was already adjusted; `year_fraction = days / 360` |

### Cash-flow generation

Payment schedules are generated **backward from maturity** in fixed steps
determined by coupon frequency — the standard bond-market convention. This puts
any irregular ("stub") period at the front of the schedule, next to issue, matching
how real bonds are structured. Business-day adjustment (`FOLLOWING`,
`MODIFIED_FOLLOWING`, `PRECEDING`, or `NONE`) rolls the *payment* date onto a
business day while the *accrual* dates stay unadjusted for day-count purposes.
V1's business-day check is weekend-only (no holiday calendar — see
[Limitations](#assumptions--limitations)).

A single `generate_variable_rate_cashflows` function produces coupon + principal
cash flows for **any** per-period rate list — a fixed-rate bond is the special case
where every period gets the same rate, and a floating-rate note is the case where
each period's rate is that period's reference rate plus spread.

### Accrued interest

For a settlement date falling inside coupon period `[accrual_start, accrual_end)`:

```
accrued_days     = day_count.day_count(accrual_start, settlement)
period_days      = day_count.day_count(accrual_start, accrual_end)
accrued_fraction = accrued_days / period_days
accrued_interest = full_period_coupon * accrued_fraction
```

Accrued interest is zero exactly on a coupon date (settlement belongs to the next
period) and V1 always prices cum-coupon (no ex-dividend/ex-coupon date modelling).

### Clean and dirty price

```
Dirty Price = Clean Price + Accrued Interest
```

"Dirty" (full) price is the present value of a bond's remaining cash flows as of
settlement; "clean" price is dirty price with the accrued-interest sliver removed,
which is what is actually quoted in the market.

### Yield to maturity

Given a flat yield `y` and a **yield convention** (periodic/street, annual, or
continuous compounding — see `pricing.yield_convention`), price is:

```
Price = sum_i( CF_i * DF(y, t_i) )
```

where `DF` is the yield convention's discount factor and `t_i` is the year
fraction from settlement to cash flow `i`'s payment date. Given a target price,
`pricing.yield_solver.solve_yield_to_maturity` inverts this with **Brent's
method** (`scipy.optimize.brentq`) — derivative-free and guaranteed to converge
once a sign-changing bracket is found, which is more robust across long-dated and
deep-discount bonds than Newton's method from an arbitrary starting guess.

### Duration, DV01, and convexity

**Macaulay duration** — the present-value-weighted average time to cash flow:

```
D_mac = sum_i(t_i * PV_i) / sum_i(PV_i)
```

**Modified duration** — percentage price sensitivity to a small parallel yield
change, `D_mod = -1/P * dP/dy`:

- periodic compounding (`m` periods/year): `D_mod = D_mac / (1 + y/m)`
- annual compounding: `D_mod = D_mac / (1 + y)`
- continuous compounding: `D_mod = D_mac`

**DV01 / PV01** — dollar price change (per 100 par) for a 1bp parallel yield move,
computed here by **full repricing** (central difference at `y ± 1bp`) rather than
the `D_mod * P * 0.0001` approximation, so it stays exact regardless of convexity.

**Convexity** — the second-order term, `Convexity = (1/P) * d^2P/dy^2`, in closed
form for a flat yield with `m` compounding periods per year (`m = 1` for annual):

```
Convexity = sum_i( PV_i * t_i * (t_i + 1/m) ) / ( P * (1 + y/m)^2 )
```

(continuous compounding simplifies to `sum_i(PV_i * t_i^2) / P`).

### Floating-rate notes

```
Coupon Rate = Reference Rate + Spread
```

V1 does not implement forward-curve bootstrapping. Each period's reference rate
comes from a `RateIndex`: an **observed** historical fixing when one exists,
otherwise an explicit **forward-rate assumption**. `FloatingRateNote.rate_provenance()`
reports, per reset date, which of the two was used, so a caller never mistakes an
assumption for a market-observed rate. An optional floor is applied to the
reference rate before adding the spread.

### Amortizing / sinkable securities and factor analytics

```
Current Face = Original Face x Current Factor
```

Principal paydown is described by a pluggable `AmortizationPlan`:

- **`ExplicitAmortizationPlan`** — an explicit list of principal repayments, one
  per period. Covers both level-principal amortizing bonds
  (`AmortizingBond.with_level_principal`) and custom sinking-fund tables.
- **`FactorAmortizationPlan`** — principal derived from a `FactorHistory` of
  `(date, factor)` observations, the way pass-through pools report paydown. This
  is the shape future MBS/CMO support would build on.

Either plan produces the same amortization table: `Period / Beginning Principal /
Interest / Principal Repayment / Ending Principal`, with interest computed on the
*beginning* (outstanding) balance each period.

### Yield curve and scenario analysis

`pricing.curves.YieldCurve` is a set of `(tenor, zero rate)` pillar points with
linear (or log-linear, or flat) interpolation and flat extrapolation beyond the
ends — deliberately not a bootstrapping framework. `risk.scenarios.run_rate_shock_scenarios`
applies parallel yield shocks (default: -100bp, -50bp, 0, +50bp, +100bp) and
reports, at each shock, the fully repriced value alongside the duration-only and
duration+convexity Taylor-series estimates — making the approximation error
visible rather than assumed away.

### Portfolio analytics

A thin, market-value-weighted roll-up (`portfolio.analytics.analyze_portfolio`)
over a list of positions, each an actual par amount paired with a per-100-par
`SecurityAnalytics` snapshot: total market value, weighted yield, weighted
modified duration, weighted convexity, additive DV01, and maturity distribution.
Portfolio analytics is secondary to security-level analytics — it re-derives
nothing, only weights and sums.

## Streamlit app

```bash
streamlit run app/streamlit_app.py
```

Define any of the four V1 instrument types in the sidebar, then inspect the
generated cash-flow schedule, solve price <-> yield, view accrued interest (for
fixed-rate/zero-coupon bonds), duration/DV01/convexity, rate-shock scenarios, and
an amortization schedule/chart. The UI is a thin demonstration layer — the
reusable Python analytics engine in `src/fixed_income/` is the actual product.

## Testing

```bash
pytest                                          # run the suite
pytest --cov=fixed_income --cov-report=term-missing   # with coverage
ruff check src/ tests/ app/                     # lint
```

118 tests cover day-count conventions, schedule generation (including stub
periods, month-end clamping, business-day rolls), accrued-interest edge cases
(on the issue date, on a coupon date, before issue, on/after maturity), price/
yield round-tripping, duration/convexity accuracy (verified against a Taylor
expansion), floating-rate reset provenance, amortizing/sinkable/factor paydown,
scenario analysis, and portfolio roll-ups, at 97% line coverage.

## Assumptions & limitations

`fixed-income-lab` is an educational/research toolkit. Its outputs are **not
independently validated for production trading, risk management, or valuation
use**. Specific, deliberate V1 simplifications:

- **No holiday calendar.** Business-day adjustment only knows about weekends.
  Plugging in a real calendar only requires replacing `cashflows.schedule.is_business_day`.
- **No ex-coupon/ex-dividend modelling.** Accrued interest is always computed
  cum-coupon.
- **No market-curve bootstrapping.** `YieldCurve` interpolates a hand-specified
  set of zero rates; it does not construct a curve from instrument quotes.
- **`LOG_LINEAR` curve interpolation requires strictly positive zero rates.**
  It interpolates in log-rate space, so it raises `ValueError` if either
  pillar rate bracketing a query is zero or negative (e.g. a negative-rate
  curve) — use `LINEAR` or `FLAT` interpolation for those.
- **Floating-rate note duration is a known simplification.** Because the forward
  assumption used to fix an FRN's cash flows isn't linked to the yield being
  shocked, discounting those (now-fixed) cash flows at a different yield
  overstates rate sensitivity relative to a real FRN, whose coupon actually
  resets with the market. Treat FRN duration/DV01 figures here as illustrative,
  not as a substitute for a proper reset-aware model.
- **Factor-based (pool-style) securities don't force full repayment at
  maturity.** If a `FactorHistory` has no observation bringing the factor to
  zero by the maturity date, the last period simply reflects the last known
  factor — mirroring how a real servicer/data feed would report it, but worth
  knowing if you build a `FactorHistory` by hand.
- **Explicit amortization schedules are exactly as accurate as their input.**
  `ExplicitAmortizationPlan` trusts whatever repayment list it's given; it
  doesn't validate against an annuity/mortgage formula.

## Roadmap

V1 is feature-complete per the instruments listed above. Future versions may add:

- Callable bonds (embedded call optionality)
- MBS pass-throughs (prepayment-model-driven factor paydown)
- CMO tranches (waterfall/structuring on top of a pool)
- Structured notes

...but only once each represents a genuinely new modelling challenge, not as an
open-ended feature list. Past v1.0 this project moves into maintenance mode.

## License

[MIT](LICENSE)
