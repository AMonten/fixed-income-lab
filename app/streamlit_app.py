"""Streamlit demo for fixed-income-lab.

A thin UI over the analytics engine in ``fixed_income``: define a security,
inspect its cash flows, price it, and look at its risk. The engine
(``src/fixed_income``) is the real deliverable; this app exists to make it
tangible, not to be a trading tool.

Run with: streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fixed_income.analytics import analyze_bond, analyze_cash_flows
from fixed_income.conventions import Frequency, get_day_count_convention
from fixed_income.instruments.amortizing import AmortizingBond
from fixed_income.instruments.bond import Bond, ZeroCouponBond
from fixed_income.instruments.floating_rate import FloatingRateNote
from fixed_income.instruments.rate_index import RateIndex
from fixed_income.pricing.accrued_interest import compute_accrued_interest
from fixed_income.pricing.yield_convention import YieldConvention
from fixed_income.risk.scenarios import DEFAULT_SHOCKS_BP, run_rate_shock_scenarios

st.set_page_config(page_title="fixed-income-lab", layout="wide")
st.title("fixed-income-lab")
st.caption(
    "Educational/research fixed-income analytics toolkit. Outputs are not "
    "independently validated for production trading or valuation use."
)

DAY_COUNT_OPTIONS = ["ACT/365", "ACT/360", "30/360"]
FREQUENCY_OPTIONS = ["ANNUAL", "SEMI_ANNUAL", "QUARTERLY", "MONTHLY"]

# ---------------------------------------------------------------------------
# Sidebar: define a security
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Define a security")
    instrument_type = st.selectbox(
        "Instrument type",
        ["Fixed-Rate Bond", "Zero-Coupon Bond", "Floating-Rate Note", "Amortizing Bond"],
    )
    face_value = st.number_input("Face value", value=100.0, min_value=0.01, step=100.0)
    issue_date = st.date_input("Issue date", value=date(2022, 1, 15))
    maturity_date = st.date_input("Maturity date", value=date(2032, 1, 15))
    frequency = Frequency[st.selectbox("Coupon frequency", FREQUENCY_OPTIONS, index=1)]
    day_count = get_day_count_convention(st.selectbox("Day-count convention", DAY_COUNT_OPTIONS, index=0))

    if issue_date >= maturity_date:
        st.error("Issue date must be before maturity date.")
        st.stop()

    security: Bond | ZeroCouponBond | FloatingRateNote | AmortizingBond
    accrued_supported = False

    if instrument_type == "Fixed-Rate Bond":
        coupon_rate = st.number_input("Coupon rate (%)", value=5.0, step=0.125) / 100.0
        security = Bond(face_value, coupon_rate, issue_date, maturity_date, frequency, day_count)
        accrued_supported = True

    elif instrument_type == "Zero-Coupon Bond":
        security = ZeroCouponBond(face_value, 0.0, issue_date, maturity_date, frequency, day_count)
        accrued_supported = True

    elif instrument_type == "Floating-Rate Note":
        spread_bp = st.number_input("Spread over reference rate (bp)", value=25.0, step=5.0)
        forward_assumption = st.number_input(
            "Forward-rate assumption (%)",
            value=4.50,
            step=0.05,
            help="Flat assumed reference rate for every reset date without an observed fixing "
            "(V1 has no market-curve bootstrapping).",
        ) / 100.0
        apply_floor = st.checkbox("Apply a rate floor", value=True)
        floor = st.number_input("Floor (%)", value=0.0, step=0.25) / 100.0 if apply_floor else None
        rate_index = RateIndex(name="Reference Index", forward_assumption=forward_assumption, floor=floor)
        security = FloatingRateNote(
            face_value, spread_bp / 10_000.0, issue_date, maturity_date, rate_index, frequency, day_count
        )
        st.info("Every reset date shows as a forward-rate assumption (no historical fixings entered here).")

    else:  # Amortizing Bond
        coupon_rate = st.number_input("Coupon rate (%)", value=5.0, step=0.125) / 100.0
        security = AmortizingBond.with_level_principal(
            face_value, coupon_rate, issue_date, maturity_date, frequency, day_count
        )
        st.caption("Level-principal amortization: equal principal repayment each period.")

    max_settlement = maturity_date - timedelta(days=1)
    settlement_date = st.date_input(
        "Settlement date", value=issue_date, min_value=issue_date, max_value=max_settlement
    )

    yield_convention = YieldConvention.street(frequency)

cash_flows_after_settlement = security.cash_flows_after(settlement_date)

if not cash_flows_after_settlement:
    st.warning("No cash flows remain after the chosen settlement date.")
    st.stop()


def get_accrued_interest(sec, settlement: date) -> float:
    if accrued_supported:
        return compute_accrued_interest(sec, settlement).accrued_interest
    return 0.0


accrued_interest = get_accrued_interest(security, settlement_date)

tab_cf, tab_price, tab_risk, tab_scenarios, tab_amort = st.tabs(
    ["Cash Flows", "Price & Yield", "Risk", "Scenarios", "Amortization"]
)

# ---------------------------------------------------------------------------
# Cash flows
# ---------------------------------------------------------------------------

with tab_cf:
    st.subheader("Generated cash-flow schedule")
    all_cash_flows = security.cash_flows()
    df = pd.DataFrame(
        [
            {
                "Period": cf.period_index,
                "Accrual Start": cf.accrual_start,
                "Accrual End": cf.accrual_end,
                "Payment Date": cf.payment_date,
                "Coupon": round(cf.coupon, 6),
                "Principal": round(cf.principal, 6),
                "Total": round(cf.total, 6),
                "Begin Principal": round(cf.begin_principal, 6),
                "End Principal": round(cf.end_principal, 6),
            }
            for cf in all_cash_flows
        ]
    )
    st.dataframe(df, width='stretch', hide_index=True)
    st.caption(f"{len(all_cash_flows)} period(s) from {security.issue_date} to {security.maturity_date}.")

# ---------------------------------------------------------------------------
# Price & yield
# ---------------------------------------------------------------------------

with tab_price:
    st.subheader("Price / yield")
    col_input, col_output = st.columns(2)

    with col_input:
        mode = st.radio("Solve for", ["Price given yield", "Yield given clean price"])
        if mode == "Price given yield":
            ytm_input = st.number_input("Yield to maturity (%)", value=5.0, step=0.125) / 100.0
            clean_price_input = None
        else:
            ytm_input = None
            clean_price_input = st.number_input("Clean price (per 100 par)", value=100.0, step=0.25)

    try:
        if isinstance(security, Bond):
            result = analyze_bond(
                security, settlement_date, yield_convention=yield_convention,
                yield_to_maturity=ytm_input, clean_price=clean_price_input,
            )
        else:
            result = analyze_cash_flows(
                cash_flows_after_settlement, security.face_value, settlement_date,
                yield_convention, security.day_count,
                yield_to_maturity=ytm_input, clean_price=clean_price_input,
                accrued_interest=accrued_interest,
            )
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    with col_output:
        st.metric("Yield to maturity", f"{result.yield_to_maturity:.4%}")
        st.metric("Clean price", f"{result.clean_price:.4f}")
        st.metric("Dirty price", f"{result.dirty_price:.4f}")

    st.subheader("Accrued interest")
    if accrued_supported:
        detail = compute_accrued_interest(security, settlement_date)
        c1, c2, c3 = st.columns(3)
        c1.metric("Accrued days", detail.accrued_days)
        c2.metric("Accrued fraction", f"{detail.accrued_fraction:.4f}")
        c3.metric("Accrued interest", f"{detail.accrued_interest:.4f}")
        st.caption(f"Coupon period: {detail.accrual_start} to {detail.accrual_end}")
    else:
        st.info(
            "Accrued-interest calculation in V1 covers fixed-rate and zero-coupon bonds only. "
            f"This {instrument_type} is priced with accrued interest assumed to be 0 "
            "(clean price == dirty price)."
        )

# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

with tab_risk:
    st.subheader("Duration, DV01, and convexity")
    st.caption(f"Evaluated at the yield solved above: {result.yield_to_maturity:.4%}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Macaulay duration (yrs)", f"{result.macaulay_duration:.4f}")
    c2.metric("Modified duration", f"{result.modified_duration:.4f}")
    c3.metric("DV01 (per 100 par)", f"{result.dv01:.6f}")
    c4.metric("Convexity", f"{result.convexity:.4f}")

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

with tab_scenarios:
    st.subheader("Parallel yield-shock scenarios")
    scenarios = run_rate_shock_scenarios(
        cash_flows_after_settlement, security.face_value, settlement_date,
        result.yield_to_maturity, yield_convention, security.day_count, DEFAULT_SHOCKS_BP,
    )
    scenario_df = pd.DataFrame(
        [
            {
                "Shock (bp)": s.shock_bp,
                "Shocked Yield": f"{s.shocked_yield:.4%}",
                "Full Reprice": round(s.full_reprice, 4),
                "Duration Approx.": round(s.duration_approx_price, 4),
                "Convexity Approx.": round(s.convexity_approx_price, 4),
                "% Change (full)": f"{s.percent_change:.3%}",
            }
            for s in scenarios
        ]
    )
    st.dataframe(scenario_df, width='stretch', hide_index=True)

    shock_bps = [s.shock_bp for s in scenarios]
    series = [
        ("Full reprice", [s.full_reprice for s in scenarios]),
        ("Duration approx.", [s.duration_approx_price for s in scenarios]),
        ("Convexity approx.", [s.convexity_approx_price for s in scenarios]),
    ]
    fig = go.Figure()
    for name, values in series:
        fig.add_trace(go.Scatter(x=shock_bps, y=values, name=name, mode="lines+markers"))
    fig.update_layout(
        xaxis_title="Yield shock (bp)", yaxis_title="Price (per 100 par)", legend_title="Method"
    )
    st.plotly_chart(fig, width='stretch')

# ---------------------------------------------------------------------------
# Amortization
# ---------------------------------------------------------------------------

with tab_amort:
    st.subheader("Amortization / factor schedule")
    if isinstance(security, AmortizingBond):
        entries = security.amortization_schedule()
        amort_df = pd.DataFrame(
            [
                {
                    "Period": e.period_index,
                    "Payment Date": e.payment_date,
                    "Begin Principal": round(e.begin_principal, 2),
                    "Interest": round(e.interest, 2),
                    "Principal Repayment": round(e.principal_repayment, 2),
                    "End Principal": round(e.end_principal, 2),
                    "Factor": round(e.end_principal / security.original_face, 6),
                }
                for e in entries
            ]
        )
        st.dataframe(amort_df, width='stretch', hide_index=True)

        fig = go.Figure()
        dates = [security.issue_date] + [e.payment_date for e in entries]
        balances = [security.original_face] + [e.end_principal for e in entries]
        fig.add_trace(go.Scatter(x=dates, y=balances, mode="lines+markers", name="Outstanding principal"))
        fig.update_layout(xaxis_title="Date", yaxis_title="Outstanding principal")
        st.plotly_chart(fig, width='stretch')
    else:
        st.info(f"{instrument_type} does not amortize — principal is repaid in full at maturity.")
