"""
plots.py — Plotly chart helpers for the QAOA Green Dispatch dashboard.

All functions return a :class:`plotly.graph_objects.Figure` instance that can
be passed directly to :func:`streamlit.plotly_chart`.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any

import numpy as np

try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    _PLOTLY_OK = True
except ImportError:  # pragma: no cover
    _PLOTLY_OK = False


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
SOURCE_COLOURS: Dict[str, str] = {
    "Solar":   "#FFD600",   # golden yellow
    "Battery": "#00B0FF",   # sky blue
    "Grid":    "#66BB6A",   # green
    "Diesel":  "#EF5350",   # red
}

_DEFAULT_COLOUR = "#B0BEC5"


def _source_colour(name: str) -> str:
    """Return the hex colour for a source by name (case-insensitive match)."""
    for key, colour in SOURCE_COLOURS.items():
        if key.lower() in name.lower():
            return colour
    return _DEFAULT_COLOUR


# ---------------------------------------------------------------------------
# 1. Demand profile + solar overlay
# ---------------------------------------------------------------------------

def plot_demand_profile(
    time_labels: List[str],
    demands: List[float],
    solar_avail: List[float],
) -> "go.Figure":
    """Plot the daily demand curve and solar availability as a dual-axis chart.

    Args:
        time_labels:  List of HH:MM strings for the x-axis.
        demands:      Energy demand (kW) per slot.
        solar_avail:  Solar availability factor [0, 1] per slot.

    Returns:
        Plotly :class:`~plotly.graph_objects.Figure`.
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            x=time_labels,
            y=demands,
            name="Demand (kW)",
            marker_color="#1565C0",
            opacity=0.8,
        ),
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=time_labels,
            y=[v * 100 for v in solar_avail],
            name="Solar Availability (%)",
            mode="lines+markers",
            line={"color": "#FFD600", "width": 3},
            marker={"size": 8},
        ),
        secondary_y=True,
    )

    fig.update_layout(
        title="Daily Demand Profile & Solar Availability",
        xaxis_title="Time Slot",
        legend={"orientation": "h", "y": -0.2},
        template="plotly_white",
        height=400,
    )
    fig.update_yaxes(title_text="Demand (kW)", secondary_y=False)
    fig.update_yaxes(title_text="Solar Availability (%)", secondary_y=True,
                     range=[0, 110])
    return fig


# ---------------------------------------------------------------------------
# 2. Energy schedule (stacked bar, one bar per slot)
# ---------------------------------------------------------------------------

def plot_energy_schedule(
    schedule: Dict[str, List[int]],
    time_labels: List[str],
    source_names: List[str],
    capacities: Optional[List[float]] = None,
    solar_avail: Optional[List[float]] = None,
    demands: Optional[List[float]] = None,
) -> "go.Figure":
    """Plot a stacked bar chart showing which sources are active per time slot.

    Args:
        schedule:     Dict {source_name: [on/off per slot]}.
        time_labels:  List of HH:MM x-axis labels.
        source_names: Ordered list of source names.
        capacities:   Optional list of rated capacities; used to scale bars.
        solar_avail:  Optional solar availability factors; used to scale solar bars.
        demands:      Optional demand trace to overlay.

    Returns:
        Plotly :class:`~plotly.graph_objects.Figure`.
    """
    n_slots = len(time_labels)
    fig = go.Figure()

    for i, name in enumerate(source_names):
        on_off = schedule.get(name, [0] * n_slots)
        if capacities:
            cap = capacities[i]
            # Scale solar by availability
            if solar_avail and "solar" in name.lower():
                values = [on_off[t] * cap * solar_avail[t] for t in range(n_slots)]
            else:
                values = [on_off[t] * cap for t in range(n_slots)]
        else:
            values = on_off  # binary

        fig.add_trace(
            go.Bar(
                x=time_labels,
                y=values,
                name=name,
                marker_color=_source_colour(name),
            )
        )

    if demands:
        fig.add_trace(
            go.Scatter(
                x=time_labels,
                y=demands,
                name="Demand",
                mode="lines+markers",
                line={"color": "black", "width": 2, "dash": "dot"},
                marker={"symbol": "diamond", "size": 9},
            )
        )

    fig.update_layout(
        barmode="stack",
        title="Optimised Energy Dispatch Schedule",
        xaxis_title="Time Slot",
        yaxis_title="Power (kW)",
        legend={"orientation": "h", "y": -0.2},
        template="plotly_white",
        height=420,
    )
    return fig


# ---------------------------------------------------------------------------
# 3. Side-by-side comparison bar chart
# ---------------------------------------------------------------------------

def plot_comparison_bar(results_dict: Dict[str, Dict[str, float]]) -> "go.Figure":
    """Plot a grouped bar chart comparing solvers on cost and CO₂.

    Args:
        results_dict: Nested dict of the form::

            {
                "QAOA":        {"total_cost_usd": ..., "total_co2_kg": ...},
                "Greedy":      {"total_cost_usd": ..., "total_co2_kg": ...},
                "Brute Force": {"total_cost_usd": ..., "total_co2_kg": ...},
            }

    Returns:
        Plotly :class:`~plotly.graph_objects.Figure` with two subplots.
    """
    solvers = list(results_dict.keys())
    costs = [results_dict[s].get("total_cost_usd", 0) for s in solvers]
    co2s = [results_dict[s].get("total_co2_kg", 0) for s in solvers]

    colours = ["#1565C0", "#43A047", "#FB8C00"]

    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=["Total Cost (USD)", "Total CO₂ (kg)"],
    )

    for idx, (solver, cost, co2) in enumerate(zip(solvers, costs, co2s)):
        colour = colours[idx % len(colours)]
        fig.add_trace(
            go.Bar(name=solver, x=[solver], y=[cost], marker_color=colour,
                   showlegend=(idx == 0)),
            row=1, col=1,
        )
        fig.add_trace(
            go.Bar(name=solver, x=[solver], y=[co2], marker_color=colour,
                   showlegend=False),
            row=1, col=2,
        )

    fig.update_layout(
        title="Solver Comparison: QAOA vs Classical",
        barmode="group",
        template="plotly_white",
        height=420,
        showlegend=True,
    )
    return fig


# ---------------------------------------------------------------------------
# 4. CO₂ pie chart by source
# ---------------------------------------------------------------------------

def plot_co2_pie(co2_by_source: Dict[str, float]) -> "go.Figure":
    """Pie chart of CO₂ emissions broken down by energy source.

    Args:
        co2_by_source: Dict {source_name: co2_kg}.

    Returns:
        Plotly :class:`~plotly.graph_objects.Figure`.
    """
    labels = list(co2_by_source.keys())
    values = [max(0.0, v) for v in co2_by_source.values()]

    colours = [_source_colour(name) for name in labels]

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            marker={"colors": colours},
            hole=0.4,
            textinfo="label+percent",
        )
    )
    fig.update_layout(
        title="CO₂ Emissions by Energy Source",
        template="plotly_white",
        height=380,
    )
    return fig


# ---------------------------------------------------------------------------
# 5. Measurement counts histogram
# ---------------------------------------------------------------------------

def plot_counts_histogram(counts_dict: Dict[str, int], top_n: int = 20) -> "go.Figure":
    """Bar chart of the top-N most-sampled bitstrings from QAOA measurement.

    Args:
        counts_dict: Dict {bitstring: count} as returned by the QAOA solver.
        top_n:       Number of highest-count bitstrings to display.

    Returns:
        Plotly :class:`~plotly.graph_objects.Figure`.
    """
    sorted_counts = sorted(counts_dict.items(), key=lambda kv: kv[1], reverse=True)
    top = sorted_counts[:top_n]
    if not top:
        fig = go.Figure()
        fig.update_layout(title="No measurement data available.")
        return fig

    bitstrings, counts = zip(*top)

    fig = go.Figure(
        go.Bar(
            x=list(bitstrings),
            y=list(counts),
            marker_color="#7B1FA2",
        )
    )
    fig.update_layout(
        title=f"QAOA Measurement Counts (top {min(top_n, len(top))} bitstrings)",
        xaxis_title="Bitstring",
        yaxis_title="Count",
        xaxis={"tickangle": -45},
        template="plotly_white",
        height=400,
    )
    return fig
