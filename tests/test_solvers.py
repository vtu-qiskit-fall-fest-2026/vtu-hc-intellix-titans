"""
test_solvers.py — Unit tests for BruteForceSolver and GreedySolver.
"""

import numpy as np
import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.problem import ProblemParams, QuboMatrix
from src.classical_solvers import BruteForceSolver, GreedySolver


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def small_params():
    """4 binary variables (2 sources × 2 slots) — tiny enough for brute force."""
    return ProblemParams(
        n_slots=2,
        source_names=["Solar", "Diesel"],
        capacities=[4.0, 5.0],
        costs=[0.02, 0.35],
        co2_factors=[0.0, 0.82],
        demands=[3.0, 4.0],
        solar_avail=[1.0, 0.5],
        penalty_weight=10.0,
        co2_weight=0.5,
    )


@pytest.fixture
def small_qubo(small_params):
    return QuboMatrix(small_params).build()


@pytest.fixture
def four_source_params():
    """Standard 4-source, 2-slot problem (8 qubits)."""
    return ProblemParams(
        n_slots=2,
        demands=[5.0, 7.0],
        solar_avail=[0.8, 0.0],
        penalty_weight=10.0,
        co2_weight=0.5,
    )


@pytest.fixture
def four_source_qubo(four_source_params):
    return QuboMatrix(four_source_params).build()


# ---------------------------------------------------------------------------
# BruteForceSolver tests
# ---------------------------------------------------------------------------

class TestBruteForceSolver:
    def test_finds_global_optimum(self, small_qubo, small_params):
        """Brute force must return the true global minimum over all 2^4 states."""
        bf = BruteForceSolver(small_qubo)
        result = bf.solve()

        # Re-evaluate claimed best cost
        n = small_params.n_vars
        bs = result["best_bitstring"]
        bits = np.array([int(b) for b in reversed(bs)], dtype=float)
        recalc = small_qubo.evaluate(bits)
        assert recalc == pytest.approx(result["best_cost"], rel=1e-9)

        # Verify no better solution exists
        for i in range(2 ** n):
            x = np.array([(i >> k) & 1 for k in range(n)], dtype=float)
            cost = small_qubo.evaluate(x)
            assert cost >= result["best_cost"] - 1e-9, (
                f"BF missed optimum: found {result['best_cost']:.6f} but "
                f"x={x} gives {cost:.6f}"
            )

    def test_result_keys(self, small_qubo):
        """Result dict must contain expected keys."""
        bf = BruteForceSolver(small_qubo)
        result = bf.solve()
        for key in ("best_bitstring", "best_cost", "schedule", "n_evaluated", "runtime_s"):
            assert key in result, f"Missing key: {key}"

    def test_n_evaluated(self, small_qubo, small_params):
        """Brute force must evaluate exactly 2^n bitstrings."""
        bf = BruteForceSolver(small_qubo)
        result = bf.solve()
        assert result["n_evaluated"] == 2 ** small_params.n_vars

    def test_bitstring_length(self, small_qubo, small_params):
        """Best bitstring must have length equal to n_vars."""
        bf = BruteForceSolver(small_qubo)
        result = bf.solve()
        assert len(result["best_bitstring"]) == small_params.n_vars

    def test_runtime_positive(self, small_qubo):
        """Runtime should be a positive float."""
        bf = BruteForceSolver(small_qubo)
        result = bf.solve()
        assert result["runtime_s"] >= 0.0

    def test_too_large_raises(self):
        """Problems with > 20 variables must raise ValueError."""
        large_params = ProblemParams(n_slots=6)  # 4*6 = 24 vars
        large_qubo = QuboMatrix(large_params).build()
        with pytest.raises(ValueError, match="capped at"):
            BruteForceSolver(large_qubo)

    def test_schedule_contains_all_sources(self, small_qubo, small_params):
        """Decoded schedule must have an entry for every source."""
        bf = BruteForceSolver(small_qubo)
        result = bf.solve()
        for name in small_params.source_names:
            assert name in result["schedule"], f"Source '{name}' missing from schedule"

    def test_4source_optimum_found(self, four_source_qubo, four_source_params):
        """Brute force must find a solution with finite, consistent cost."""
        bf = BruteForceSolver(four_source_qubo)
        result = bf.solve()
        assert np.isfinite(result["best_cost"])
        # Recalculate
        bs = result["best_bitstring"]
        bits = np.array([int(b) for b in reversed(bs)], dtype=float)
        assert four_source_qubo.evaluate(bits) == pytest.approx(
            result["best_cost"], rel=1e-9
        )


# ---------------------------------------------------------------------------
# GreedySolver tests
# ---------------------------------------------------------------------------

class TestGreedySolver:
    def test_always_satisfies_demand_when_possible(self, four_source_qubo, four_source_params):
        """Greedy solver should meet demand in each slot when total capacity allows."""
        gs = GreedySolver(four_source_qubo)
        result = gs.solve()

        p = four_source_params
        for t in range(p.n_slots):
            total_cap = sum(p.capacities)  # all sources summed ignoring solar limit
            if p.demands[t] <= total_cap:
                assert result["supplied_kw"][t] >= p.demands[t] - 1e-6, (
                    f"Demand not met at slot {t}: "
                    f"supplied={result['supplied_kw'][t]:.3f}, "
                    f"demand={p.demands[t]:.3f}"
                )

    def test_result_keys(self, four_source_qubo):
        """Result dict must contain expected keys."""
        gs = GreedySolver(four_source_qubo)
        result = gs.solve()
        for key in ("best_bitstring", "best_cost", "schedule",
                    "demand_met", "supplied_kw", "runtime_s"):
            assert key in result, f"Missing key: {key}"

    def test_cost_finite(self, four_source_qubo):
        """Greedy solution cost must be finite."""
        gs = GreedySolver(four_source_qubo)
        result = gs.solve()
        assert np.isfinite(result["best_cost"])

    def test_prefers_cheap_sources(self, four_source_params, four_source_qubo):
        """When solar is available, it should be selected before diesel."""
        gs = GreedySolver(four_source_qubo)
        result = gs.solve()
        schedule = result["schedule"]

        # Slot 0: solar_avail = 0.8 → solar effective cap = 4 * 0.8 = 3.2 kW
        # Solar cost < Diesel cost, so solar must be ON in slot 0 if solar is available
        if four_source_params.solar_avail[0] > 0:
            assert schedule["Solar"][0] == 1, (
                "Greedy should prefer solar (cheapest) when available."
            )

    def test_diesel_used_only_as_last_resort(self, four_source_params, four_source_qubo):
        """Diesel (most expensive) should only be active when needed."""
        gs = GreedySolver(four_source_qubo)
        result = gs.solve()
        schedule = result["schedule"]

        # For each slot where diesel is ON, check that removing it would
        # violate the demand constraint
        p = four_source_params
        for t in range(p.n_slots):
            if not schedule["Diesel"][t]:
                continue
            supplied_without_diesel = result["supplied_kw"][t] - p.capacities[3]
            # Diesel should only activate if demand isn't otherwise met
            assert supplied_without_diesel < p.demands[t] + 1e-3, (
                f"Diesel active at slot {t} unnecessarily: "
                f"supply without diesel = {supplied_without_diesel:.2f}, "
                f"demand = {p.demands[t]:.2f}"
            )

    def test_schedule_length(self, four_source_qubo, four_source_params):
        """Each source's schedule list must have length n_slots."""
        gs = GreedySolver(four_source_qubo)
        result = gs.solve()
        for name in four_source_params.source_names:
            assert len(result["schedule"][name]) == four_source_params.n_slots

    def test_greedy_small(self, small_qubo):
        """Greedy must run on a tiny 2-source, 2-slot problem."""
        gs = GreedySolver(small_qubo)
        result = gs.solve()
        assert np.isfinite(result["best_cost"])

    def test_runtime_positive(self, four_source_qubo):
        """Greedy runtime should be a non-negative float."""
        gs = GreedySolver(four_source_qubo)
        result = gs.solve()
        assert result["runtime_s"] >= 0.0
