"""
app.py — Streamlit interactive dashboard for QAOA Green Energy Dispatch.

Launch with:
    streamlit run dashboard/app.py

The dashboard exposes four tabs:
  1. Problem Setup       — energy sources table, demand profile chart
  2. QAOA Results        — circuit info, measurement histogram, schedule
  3. Classical Comparison — side-by-side cost/CO₂ table and chart
  4. CO₂ Dashboard       — pie chart, savings metrics
"""

from __future__ import annotations

import sys
import os
import time
import warnings
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Make src/ importable when running from the project root or dashboard/ dir
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import streamlit as st
import pandas as pd
import numpy as np

from src.problem import ProblemParams, QuboMatrix, build_default_problem
from src.data_generator import generate_daily_profile
from src.co2_calculator import calculate_metrics
from dashboard.plots import (
    plot_demand_profile,
    plot_energy_schedule,
    plot_comparison_bar,
    plot_co2_pie,
    plot_counts_histogram,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="QAOA Green Dispatch",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------
if "results" not in st.session_state:
    st.session_state["results"] = None


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("⚡ QAOA Green Energy Dispatch")
st.caption(
    "**VTU Qiskit Fall Fest 2026 — Track 6** | "
    "Quantum-Optimised Clean Energy Scheduling"
)
st.markdown("---")


# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Configuration")

    n_slots = st.slider(
        "Time slots (N)",
        min_value=2,
        max_value=8,
        value=4,
        help="Number of scheduling time slots. Each extra slot adds 4 qubits.",
    )

    p_depth = st.slider(
        "QAOA depth (p)",
        min_value=1,
        max_value=3,
        value=1,
        help="Number of cost+mixer layers. Higher p → better approximation but slower.",
    )

    shots = st.select_slider(
        "Measurement shots",
        options=[256, 512, 1024, 2048],
        value=1024,
    )

    use_noise = st.toggle(
        "🔊 Enable noise model",
        value=False,
        help="Simulate hardware noise (depolarising + readout errors).",
    )

    penalty = st.number_input(
        "Demand penalty λ",
        min_value=1.0,
        max_value=100.0,
        value=10.0,
        step=1.0,
        help="Lagrange multiplier for demand-constraint penalty in the QUBO.",
    )

    co2_weight = st.number_input(
        "CO₂ weight",
        min_value=0.0,
        max_value=5.0,
        value=0.5,
        step=0.1,
        help="Relative weight of the CO₂ term in the objective.",
    )

    st.markdown("---")
    run_button = st.button("🚀 Run Optimisation", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# Generate the problem (always, so tabs can render before a run)
# ---------------------------------------------------------------------------
profile = generate_daily_profile(n_slots=n_slots)
params = ProblemParams(
    n_slots=n_slots,
    demands=profile["demands"],
    solar_avail=profile["solar_availability"],
    penalty_weight=penalty,
    co2_weight=co2_weight,
)
qubo = QuboMatrix(params).build()
time_labels = profile["time_labels"]


# ---------------------------------------------------------------------------
# Run optimisation when button is pressed
# ---------------------------------------------------------------------------
if run_button:
    with st.spinner("Running QAOA optimisation … this may take a minute ⏳"):
        try:
            from src.qaoa_solver import QAOASolver
            from src.classical_solvers import BruteForceSolver, GreedySolver
            from src.co2_calculator import calculate_metrics

            solver = QAOASolver(qubo, p=p_depth, shots=shots)
            solver.build_circuit()

            qaoa_result = solver.solve(use_noise=use_noise)
            qaoa_metrics = calculate_metrics(qaoa_result["schedule"], params)

            # Greedy
            greedy = GreedySolver(qubo)
            greedy_result = greedy.solve()
            greedy_metrics = calculate_metrics(greedy_result["schedule"], params)

            # Brute force (only if feasible)
            bf_result = None
            bf_metrics = None
            if params.n_vars <= 20:
                try:
                    bf = BruteForceSolver(qubo)
                    bf_result = bf.solve()
                    bf_metrics = calculate_metrics(bf_result["schedule"], params)
                except Exception as exc:
                    st.warning(f"Brute force skipped: {exc}")

            st.session_state["results"] = {
                "qaoa": qaoa_result,
                "qaoa_metrics": qaoa_metrics,
                "greedy": greedy_result,
                "greedy_metrics": greedy_metrics,
                "bf": bf_result,
                "bf_metrics": bf_metrics,
                "params": params,
                "profile": profile,
            }
            st.success("Optimisation complete! ✅")

        except ImportError as exc:
            st.error(
                f"Import error: {exc}\n\n"
                "Make sure all dependencies are installed:\n"
                "```\npip install -r requirements.txt\n```"
            )
        except Exception as exc:
            st.error(f"Optimisation failed: {exc}")
            st.exception(exc)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs(
    ["📋 Problem Setup", "⚛️ QAOA Results", "📊 Classical Comparison", "🌿 CO₂ Dashboard"]
)

# ═══════════════════════════════════════════════════════════════════════════
# TAB 1 — Problem Setup
# ═══════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("Energy Sources")
    sources_df = pd.DataFrame(
        {
            "Source": params.source_names,
            "Capacity (kW)": params.capacities,
            "Cost ($/kWh)": params.costs,
            "CO₂ (kg/kWh)": params.co2_factors,
            "Always Available": ["No", "Yes", "Yes", "Yes"],
        }
    )
    st.dataframe(sources_df, use_container_width=True, hide_index=True)

    st.subheader("Problem Dimensions")
    col1, col2, col3 = st.columns(3)
    col1.metric("Sources (K)", params.n_sources)
    col2.metric("Time Slots (N)", params.n_slots)
    col3.metric("Qubits required", params.n_vars)

    st.subheader("Demand Profile")
    fig_demand = plot_demand_profile(time_labels, profile["demands"], profile["solar_availability"])
    st.plotly_chart(fig_demand, use_container_width=True)

    with st.expander("📐 QUBO Matrix Heatmap"):
        try:
            import plotly.express as px
            Q = qubo.Q
            fig_q = px.imshow(
                Q,
                color_continuous_scale="RdBu_r",
                title="QUBO Matrix Q",
                labels={"color": "Q value"},
            )
            st.plotly_chart(fig_q, use_container_width=True)
        except Exception:
            st.info("Install plotly to see the QUBO heatmap.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2 — QAOA Results
# ═══════════════════════════════════════════════════════════════════════════
with tab2:
    results = st.session_state.get("results")
    if results is None:
        st.info("Press **🚀 Run Optimisation** in the sidebar to see results.")
    else:
        qaoa = results["qaoa"]
        qm = results["qaoa_metrics"]

        st.subheader("Key Metrics")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Best QUBO Cost", f"{qaoa['best_cost']:.4f}")
        c2.metric("Circuit Depth", qaoa.get("circuit_depth", "N/A"))
        c3.metric("Qubits", qaoa["n_qubits"])
        c4.metric("Solve Time", f"{qaoa['runtime_s']:.1f}s")

        st.subheader("Optimised Schedule")
        fig_sched = plot_energy_schedule(
            qaoa["schedule"],
            time_labels,
            params.source_names,
            capacities=params.capacities,
            solar_avail=profile["solar_availability"],
            demands=profile["demands"],
        )
        st.plotly_chart(fig_sched, use_container_width=True)

        st.subheader("Measurement Counts")
        fig_hist = plot_counts_histogram(qaoa["all_counts"])
        st.plotly_chart(fig_hist, use_container_width=True)

        st.subheader("Best Bitstring")
        st.code(qaoa["best_bitstring"], language=None)

        with st.expander("Optimal Parameters"):
            opt_params = qaoa.get("optimal_params", [])
            p_depth_used = len(opt_params) // 2
            gamma_vals = opt_params[:p_depth_used]
            beta_vals = opt_params[p_depth_used:]
            pdf = pd.DataFrame({
                "Layer": list(range(1, p_depth_used + 1)),
                "γ (gamma)": gamma_vals,
                "β (beta)": beta_vals,
            })
            st.dataframe(pdf, hide_index=True)

        if qaoa.get("noisy"):
            st.warning("⚠️ These results were obtained with a **noisy** simulator.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 3 — Classical Comparison
# ═══════════════════════════════════════════════════════════════════════════
with tab3:
    results = st.session_state.get("results")
    if results is None:
        st.info("Press **🚀 Run Optimisation** in the sidebar to see results.")
    else:
        qm = results["qaoa_metrics"]
        gm = results["greedy_metrics"]
        bm = results.get("bf_metrics")

        # Build comparison dict for chart
        comparison = {
            "QAOA": qm,
            "Greedy": gm,
        }
        if bm:
            comparison["Brute Force"] = bm

        # Comparison table
        st.subheader("Solver Comparison Table")
        rows = []
        for solver_name, metrics in comparison.items():
            runtime_key = {
                "QAOA": "qaoa",
                "Greedy": "greedy",
                "Brute Force": "bf",
            }.get(solver_name, "qaoa")
            runtime = results.get(runtime_key, {}).get("runtime_s", float("nan"))
            rows.append({
                "Solver": solver_name,
                "Total Cost (USD)": metrics["total_cost_usd"],
                "Total CO₂ (kg)": metrics["total_co2_kg"],
                "Demand Met (%)": metrics["demand_satisfaction_pct"],
                "Cost Saved vs Diesel ($)": metrics["cost_vs_diesel_savings_usd"],
                "CO₂ Saved vs Diesel (kg)": metrics["co2_vs_diesel_savings_kg"],
                "Runtime (s)": round(runtime, 3) if not np.isnan(runtime) else "—",
            })

        cmp_df = pd.DataFrame(rows)
        st.dataframe(cmp_df, use_container_width=True, hide_index=True)

        # Comparison chart
        st.subheader("Cost & CO₂ Comparison")
        fig_cmp = plot_comparison_bar(comparison)
        st.plotly_chart(fig_cmp, use_container_width=True)

        # Quantum advantage flag
        if bm:
            qaoa_cost = qm["total_cost_usd"]
            bf_cost = bm["total_cost_usd"]
            gap = abs(qaoa_cost - bf_cost) / (bf_cost + 1e-9) * 100
            if gap < 10:
                st.success(
                    f"🎯 **Quantum Advantage Indicator**: QAOA is within "
                    f"{gap:.1f}% of the optimal brute-force solution!"
                )
            else:
                st.info(
                    f"QAOA is {gap:.1f}% from the brute-force optimum. "
                    "Try increasing QAOA depth (p) for better results."
                )


# ═══════════════════════════════════════════════════════════════════════════
# TAB 4 — CO₂ Dashboard
# ═══════════════════════════════════════════════════════════════════════════
with tab4:
    results = st.session_state.get("results")
    if results is None:
        st.info("Press **🚀 Run Optimisation** in the sidebar to see results.")
    else:
        qm = results["qaoa_metrics"]

        st.subheader("Emissions Breakdown (QAOA Schedule)")
        fig_pie = plot_co2_pie(qm["co2_by_source"])
        st.plotly_chart(fig_pie, use_container_width=True)

        st.subheader("Savings vs All-Diesel Baseline")
        c1, c2 = st.columns(2)
        c1.metric(
            "💰 Cost Saved",
            f"${qm['cost_vs_diesel_savings_usd']:.4f}",
            delta=f"vs ${qm['diesel_cost_usd']:.4f} diesel baseline",
        )
        c2.metric(
            "🌱 CO₂ Avoided",
            f"{qm['co2_vs_diesel_savings_kg']:.4f} kg",
            delta=f"vs {qm['diesel_co2_kg']:.4f} kg diesel baseline",
        )

        st.subheader("Cost by Source")
        cost_df = pd.DataFrame(
            {
                "Source": list(qm["cost_by_source"].keys()),
                "Cost (USD)": list(qm["cost_by_source"].values()),
                "CO₂ (kg)": list(qm["co2_by_source"].values()),
            }
        )
        st.dataframe(cost_df, hide_index=True, use_container_width=True)

        st.subheader("Supplied Power per Slot")
        supply_df = pd.DataFrame(
            {
                "Time Slot": time_labels,
                "Demand (kW)": profile["demands"],
                "Supplied (kW)": qm["supplied_kw_per_slot"],
            }
        )
        st.dataframe(supply_df, hide_index=True, use_container_width=True)
