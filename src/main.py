"""
main.py — Entry point for QAOA Green Dispatch.

Run from the project root:
    python -m src.main                       # default 3-slot problem
    python -m src.main --slots 4 --p 2      # 4 slots, QAOA depth 2
    python -m src.main --slots 3 --noise    # with hardware noise model
    python -m src.main --compare            # benchmark vs classical

Or directly:
    python src/main.py --help
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

# Ensure project root is on sys.path when run directly
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.problem import ProblemParams, QuboMatrix, build_default_problem
from src.data_generator import generate_daily_profile
from src.optimizer import run_optimization, compare_solvers
from src.co2_calculator import calculate_metrics


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║          ⚡  QAOA Green Dispatch  🌿                         ║
║   Quantum-Optimized Clean Energy Scheduling via QAOA         ║
║   VTU Qiskit Fall Fest 2026 · Track 6 · Team Intellix Titans ║
╚══════════════════════════════════════════════════════════════╝
"""


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="qaoa-green-dispatch",
        description="QAOA-based clean energy scheduling optimizer.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--slots", type=int, default=3, metavar="N",
        help="Number of time slots (2–8 recommended; each slot = 3 hours).",
    )
    p.add_argument(
        "--p", type=int, default=2, metavar="P",
        help="QAOA circuit depth (number of cost+mixer layers).",
    )
    p.add_argument(
        "--shots", type=int, default=1024,
        help="Measurement shots per circuit evaluation.",
    )
    p.add_argument(
        "--noise", action="store_true",
        help="Enable hardware noise model (depolarizing + readout errors).",
    )
    p.add_argument(
        "--compare", action="store_true",
        help="Also run brute-force and greedy solvers for benchmarking.",
    )
    p.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility.",
    )
    p.add_argument(
        "--output", type=str, default=None, metavar="FILE",
        help="Save results as JSON to this file (e.g. results/run.json).",
    )
    return p


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _print_section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def _print_problem_summary(params: ProblemParams, profile: dict) -> None:
    _print_section("📋 Problem Setup")
    print(f"  Time slots : {params.n_slots}  ×  3h = {params.n_slots * 3}h window")
    print(f"  Qubits     : {params.n_vars}  ({params.n_sources} sources × {params.n_slots} slots)")
    print()
    print(f"  {'Source':<12} {'Capacity':>10} {'Cost ($/kWh)':>14} {'CO₂ (kg/kWh)':>14}")
    print(f"  {'─'*12} {'─'*10} {'─'*14} {'─'*14}")
    icons = ["☀️ ", "🔋", "⚡", "🛢️ "]
    for i, name in enumerate(params.source_names):
        print(
            f"  {icons[i]}{name:<10} {params.capacities[i]:>9.1f}kW"
            f"  {params.costs[i]:>12.3f}   {params.co2_factors[i]:>12.2f}"
        )
    print()
    print(f"  {'Slot':<8} {'Time':>6} {'Demand':>8} {'Solar Avail':>12}")
    print(f"  {'─'*8} {'─'*6} {'─'*8} {'─'*12}")
    for t in range(params.n_slots):
        label = profile["time_labels"][t]
        print(
            f"  {t:<8} {label:>6} {params.demands[t]:>7.1f}kW"
            f"  {params.solar_avail[t]:>11.0%}"
        )


def _print_circuit_info(result: dict) -> None:
    _print_section("🔬 QAOA Circuit")
    print(f"  Qubits      : {result['n_qubits']}")
    print(f"  Circuit depth: {result['circuit_depth']}")
    n_params = len(result['optimal_params'])
    p = n_params // 2
    print(f"  QAOA depth p: {p}")
    gammas = result['optimal_params'][:p]
    betas = result['optimal_params'][p:]
    print(f"  Optimal γ   : {np.round(gammas, 4)}")
    print(f"  Optimal β   : {np.round(betas, 4)}")
    print(f"  Noise model : {'✅ ON' if result.get('noisy') else '❌ OFF'}")


def _print_qaoa_result(result: dict, params: ProblemParams) -> None:
    _print_section("🎯 QAOA Result")
    print(f"  Best bitstring : {result['best_bitstring']}")
    print(f"  Best QUBO cost : {result['best_cost']:.4f}")
    print(f"  Runtime        : {result['runtime_s']:.2f}s")
    print()

    schedule = result["schedule"]
    print(f"  {'Source':<12}", end="")
    for t in range(params.n_slots):
        print(f"  t={t}", end="")
    print()
    print(f"  {'─'*12}", end="")
    for _ in range(params.n_slots):
        print(f"  {'─'*4}", end="")
    print()
    icons = ["☀️ ", "🔋", "⚡", "🛢️ "]
    for i, (src, slots) in enumerate(schedule.items()):
        icon = icons[i] if i < len(icons) else "  "
        print(f"  {icon}{src:<10}", end="")
        for val in slots:
            cell = " ON " if val else " -- "
            print(f"  {cell}", end="")
        print()

    metrics = calculate_metrics(schedule, params)
    print()
    print(f"  💰 Total cost   : ${metrics['total_cost_usd']:.4f}")
    print(f"  🌫️  Total CO₂    : {metrics['total_co2_kg']:.4f} kg")
    print(f"  ✅ Demand met   : {metrics['demand_satisfaction_pct']:.1f}%")
    print(f"  💚 Cost saved   : ${metrics['cost_vs_diesel_savings_usd']:.4f} vs all-diesel")
    print(f"  🌱 CO₂ saved    : {metrics['co2_vs_diesel_savings_kg']:.4f} kg vs all-diesel")


def _print_comparison(results: dict, params: ProblemParams) -> None:
    _print_section("📊 Solver Comparison")
    solvers = ["qaoa", "brute_force", "greedy"]
    labels  = ["QAOA (quantum)", "Brute Force", "Greedy"]

    print(f"  {'Solver':<20} {'QUBO Cost':>10} {'$/kWh cost':>12} "
          f"{'CO₂ (kg)':>10} {'Runtime':>10}")
    print(f"  {'─'*20} {'─'*10} {'─'*12} {'─'*10} {'─'*10}")

    for solver, label in zip(solvers, labels):
        r = results.get(solver, {})
        if "error" in r:
            print(f"  {label:<20}  ERROR: {r['error']}")
            continue
        m = r.get("metrics", {})
        print(
            f"  {label:<20} {r.get('best_cost', 0.0):>10.4f}"
            f"  {m.get('total_cost_usd', 0.0):>10.4f}"
            f"  {m.get('total_co2_kg', 0.0):>10.4f}"
            f"  {r.get('runtime_s', 0.0):>8.2f}s"
        )

    # Quantum advantage check
    qaoa_cost = results.get("qaoa", {}).get("best_cost", np.inf)
    bf_cost   = results.get("brute_force", {}).get("best_cost", np.inf)
    gap = abs(qaoa_cost - bf_cost) / max(abs(bf_cost), 1e-9) * 100
    print()
    if gap < 5.0:
        print(f"  🏆 Quantum Advantage: QAOA within {gap:.1f}% of optimal (≤5% threshold ✅)")
    else:
        print(f"  ⚠️  QAOA gap from optimal: {gap:.1f}% — consider increasing p or shots.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> None:  # noqa: F821
    print(BANNER)

    parser = _build_parser()
    args = parser.parse_args(argv)

    # Build problem
    print(f"Building problem: {args.slots} slots, QAOA p={args.p} ...")
    profile = generate_daily_profile(n_slots=args.slots)
    params = ProblemParams(
        n_slots=args.slots,
        demands=profile["demands"],
        solar_avail=profile["solar_availability"],
    )
    qubo = QuboMatrix(params).build()

    _print_problem_summary(params, profile)

    # Run QAOA
    print(f"\n⚙️  Running QAOA (p={args.p}, shots={args.shots}"
          + (", 🔊 noisy" if args.noise else "") + ") ...")
    qaoa_result = run_optimization(
        params, qubo,
        p=args.p,
        shots=args.shots,
        use_noise=args.noise,
        seed=args.seed,
    )

    _print_circuit_info(qaoa_result)
    _print_qaoa_result(qaoa_result, params)

    all_results = {"qaoa": qaoa_result}

    # Optional comparison
    if args.compare:
        print("\n⚙️  Running classical solvers for comparison ...")
        comparison = compare_solvers(params, qubo, p=args.p, shots=args.shots)
        all_results.update(comparison)
        _print_comparison(all_results, params)

    # Save output
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        def _make_serializable(obj):
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, (np.integer, np.floating)):
                return obj.item()
            if isinstance(obj, dict):
                return {k: _make_serializable(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_make_serializable(i) for i in obj]
            return obj

        with open(out_path, "w") as f:
            json.dump(_make_serializable(all_results), f, indent=2)
        print(f"\n💾 Results saved to {out_path}")

    _print_section("✅ Done")
    print(f"  Run the dashboard: streamlit run dashboard/app.py")
    print(f"  Run tests        : pytest tests/ -v")
    print()


if __name__ == "__main__":
    main()
