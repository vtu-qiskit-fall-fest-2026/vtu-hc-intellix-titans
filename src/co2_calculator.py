"""
co2_calculator.py — Cost and CO₂ metric computation for energy schedules.

Converts a binary source-on/off schedule into human-readable financial and
environmental KPIs, referenced against an all-diesel baseline (worst case).
"""

from __future__ import annotations

from typing import Dict, List, Any

from src.problem import ProblemParams


def calculate_metrics(
    schedule: Dict[str, List[int]],
    params: ProblemParams,
) -> Dict[str, Any]:
    """Compute cost and CO₂ metrics for a dispatch schedule.

    The schedule is compared to an *all-diesel baseline* where diesel is ON
    for every time slot and all other sources are OFF.

    Args:
        schedule: Dict mapping source name → list of on/off integers per slot.
                  Produced by :meth:`~src.problem.QuboMatrix.decode_bitstring`.
        params:   The :class:`~src.problem.ProblemParams` for this problem.

    Returns:
        Dictionary with the following keys:

        - ``total_cost_usd``             – float, total operational cost in USD.
        - ``total_co2_kg``               – float, total CO₂ emitted in kg.
        - ``demand_satisfaction_pct``    – float in [0, 100], % of slots where
                                           demand is fully met.
        - ``supplied_kw_per_slot``       – list[float], kW supplied per slot.
        - ``cost_by_source``             – dict {source_name: cost_usd}.
        - ``co2_by_source``              – dict {source_name: co2_kg}.
        - ``cost_vs_diesel_savings_usd`` – float, cost saved vs all-diesel.
        - ``co2_vs_diesel_savings_kg``   – float, CO₂ saved vs all-diesel.
        - ``diesel_cost_usd``            – float, baseline all-diesel cost.
        - ``diesel_co2_kg``              – float, baseline all-diesel CO₂.
    """
    total_cost = 0.0
    total_co2 = 0.0
    cost_by_source: Dict[str, float] = {}
    co2_by_source: Dict[str, float] = {}
    supplied_kw_per_slot: List[float] = [0.0] * params.n_slots
    slots_met = 0

    for name in params.source_names:
        cost_by_source[name] = 0.0
        co2_by_source[name] = 0.0

    for i, name in enumerate(params.source_names):
        cost_rate = params.costs[i]          # $/kWh
        co2_rate = params.co2_factors[i]     # kg/kWh
        on_off = schedule.get(name, [0] * params.n_slots)

        for t, active in enumerate(on_off):
            if not active:
                continue
            eff_cap = params.effective_capacity(i, t)
            cost_by_source[name] += eff_cap * cost_rate
            co2_by_source[name] += eff_cap * co2_rate
            supplied_kw_per_slot[t] += eff_cap

    total_cost = sum(cost_by_source.values())
    total_co2 = sum(co2_by_source.values())

    for t in range(params.n_slots):
        if supplied_kw_per_slot[t] >= params.demands[t] - 1e-6:
            slots_met += 1

    demand_satisfaction_pct = 100.0 * slots_met / params.n_slots if params.n_slots else 0.0

    # ------------------------------------------------------------------ #
    # All-diesel baseline (diesel always ON at full capacity)
    # ------------------------------------------------------------------ #
    diesel_idx = next(
        (i for i, n in enumerate(params.source_names) if "diesel" in n.lower()),
        len(params.source_names) - 1,  # fallback: last source
    )
    diesel_cost_rate = params.costs[diesel_idx]
    diesel_co2_rate = params.co2_factors[diesel_idx]
    diesel_cap = params.capacities[diesel_idx]

    diesel_cost = diesel_cap * diesel_cost_rate * params.n_slots
    diesel_co2 = diesel_cap * diesel_co2_rate * params.n_slots

    return {
        "total_cost_usd": round(total_cost, 4),
        "total_co2_kg": round(total_co2, 4),
        "demand_satisfaction_pct": round(demand_satisfaction_pct, 1),
        "supplied_kw_per_slot": [round(v, 3) for v in supplied_kw_per_slot],
        "cost_by_source": {k: round(v, 4) for k, v in cost_by_source.items()},
        "co2_by_source": {k: round(v, 4) for k, v in co2_by_source.items()},
        "cost_vs_diesel_savings_usd": round(diesel_cost - total_cost, 4),
        "co2_vs_diesel_savings_kg": round(diesel_co2 - total_co2, 4),
        "diesel_cost_usd": round(diesel_cost, 4),
        "diesel_co2_kg": round(diesel_co2, 4),
    }


def format_metrics_table(metrics: Dict[str, Any]) -> str:
    """Format a metrics dict as a human-readable ASCII table.

    Args:
        metrics: Dictionary as returned by :func:`calculate_metrics`.

    Returns:
        Multi-line string suitable for printing to a terminal.
    """
    lines = [
        "┌─────────────────────────────────────────────────┐",
        "│            CO₂ & Cost Metrics Summary            │",
        "├─────────────────────────────────────────────────┤",
        f"│  Total Cost            : ${metrics['total_cost_usd']:>10.4f}           │",
        f"│  Total CO₂             : {metrics['total_co2_kg']:>10.4f} kg          │",
        f"│  Demand Satisfaction   : {metrics['demand_satisfaction_pct']:>10.1f} %           │",
        f"│  Cost Saved vs Diesel  : ${metrics['cost_vs_diesel_savings_usd']:>10.4f}           │",
        f"│  CO₂ Saved vs Diesel   : {metrics['co2_vs_diesel_savings_kg']:>10.4f} kg          │",
        "└─────────────────────────────────────────────────┘",
    ]
    return "\n".join(lines)
