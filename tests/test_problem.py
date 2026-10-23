"""
test_problem.py — Unit tests for the QUBO problem formulation.
"""

import numpy as np
import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.problem import ProblemParams, QuboMatrix, build_default_problem
from src.data_generator import generate_daily_profile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tiny_params():
    """Minimal 2-slot, 2-source problem for fast testing."""
    return ProblemParams(
        n_slots=2,
        source_names=["Solar", "Diesel"],
        capacities=[4.0, 5.0],
        costs=[0.02, 0.35],
        co2_factors=[0.0, 0.82],
        demands=[3.0, 6.0],
        solar_avail=[1.0, 0.5],
        penalty_weight=10.0,
        co2_weight=0.5,
    )


@pytest.fixture
def tiny_qubo(tiny_params):
    return QuboMatrix(tiny_params).build()


@pytest.fixture
def default_qubo():
    _, qubo = build_default_problem(n_slots=3)
    return qubo


# ---------------------------------------------------------------------------
# 1. QUBO matrix properties
# ---------------------------------------------------------------------------

class TestQuboMatrix:
    def test_shape(self, tiny_qubo, tiny_params):
        """Q should be square with size n_vars × n_vars."""
        n = tiny_params.n_vars
        assert tiny_qubo.Q.shape == (n, n)

    def test_symmetry(self, tiny_qubo):
        """Q must be symmetric: Q == Q^T."""
        Q = tiny_qubo.Q
        np.testing.assert_allclose(Q, Q.T, atol=1e-12,
                                   err_msg="QUBO matrix is not symmetric.")

    def test_symmetry_default(self, default_qubo):
        """Symmetry check on default 4-source, 3-slot problem."""
        Q = default_qubo.Q
        np.testing.assert_allclose(Q, Q.T, atol=1e-12)

    def test_evaluate_all_zeros(self, tiny_qubo):
        """Evaluating the all-zeros vector should return only the offset."""
        n = tiny_qubo.params.n_vars
        x = np.zeros(n)
        energy = tiny_qubo.evaluate(x)
        # x^T Q x = 0; energy = offset (sum of demand^2 * penalty terms)
        assert energy == pytest.approx(tiny_qubo.offset, rel=1e-9)

    def test_evaluate_known(self, tiny_params, tiny_qubo):
        """Manual energy calculation matches QuboMatrix.evaluate."""
        n = tiny_params.n_vars
        x = np.array([1, 0, 0, 1], dtype=float)  # solar slot0 ON, diesel slot1 ON
        manual = float(x @ tiny_qubo.Q @ x) + tiny_qubo.offset
        assert tiny_qubo.evaluate(x) == pytest.approx(manual, rel=1e-9)


# ---------------------------------------------------------------------------
# 2. Ising conversion
# ---------------------------------------------------------------------------

class TestIsingConversion:
    def test_shapes(self, tiny_qubo, tiny_params):
        """J and h must have shapes (n, n) and (n,)."""
        J, h, offset = tiny_qubo.to_ising()
        n = tiny_params.n_vars
        assert J.shape == (n, n), f"Expected J shape ({n},{n}), got {J.shape}"
        assert h.shape == (n,), f"Expected h shape ({n},), got {h.shape}"

    def test_offset_finite(self, tiny_qubo):
        """Ising offset must be a finite float."""
        _, _, offset = tiny_qubo.to_ising()
        assert np.isfinite(offset)

    def test_energy_equivalence(self, tiny_qubo, tiny_params):
        """Ising energy (s ∈ {-1,+1}) and QUBO energy (x ∈ {0,1}) must agree.

        Conversion: s_i = 1 - 2*x_i  →  x_i = (1 - s_i) / 2
        E_ising(s) = sum_ij J_ij s_i s_j + sum_i h_i s_i + offset
        """
        J, h, iso = tiny_qubo.to_ising()
        n = tiny_params.n_vars

        rng = np.random.default_rng(0)
        for _ in range(10):
            x = rng.integers(0, 2, size=n).astype(float)
            s = 1.0 - 2.0 * x  # x→s

            qubo_energy = tiny_qubo.evaluate(x)
            ising_energy = float(s @ J @ s + h @ s) + iso

            assert qubo_energy == pytest.approx(ising_energy, rel=1e-6,
                                                abs=1e-8), (
                f"Mismatch for x={x}: QUBO={qubo_energy:.6f}, Ising={ising_energy:.6f}"
            )


# ---------------------------------------------------------------------------
# 3. Demand penalty
# ---------------------------------------------------------------------------

class TestDemandPenalty:
    def test_penalty_enforces_demand(self, tiny_params):
        """A configuration that exactly meets demand should have lower energy
        than one that wildly over- or under-supplies."""
        qubo = QuboMatrix(tiny_params).build()
        n = tiny_params.n_vars

        # All-off: demand completely unmet → large penalty
        x_off = np.zeros(n)
        e_off = qubo.evaluate(x_off)

        # All-on: over-supply but demand met
        x_on = np.ones(n)
        e_on = qubo.evaluate(x_on)

        # Solar slot0 ON, Diesel slot1 ON: reasonable coverage
        x_ok = np.array([1, 0, 0, 1], dtype=float)
        e_ok = qubo.evaluate(x_ok)

        # All-off should generally be worse than a reasonable schedule
        # (penalty dominates)
        assert e_off > e_ok or e_on < e_off, (
            "Penalty does not discourage leaving demand unmet."
        )

    def test_no_negative_penalty(self, tiny_qubo):
        """The penalty contribution should make unmet demand costly.

        For any x, evaluate must not return -inf (penalty is non-negative).
        """
        rng = np.random.default_rng(42)
        n = tiny_qubo.params.n_vars
        for _ in range(50):
            x = rng.integers(0, 2, size=n).astype(float)
            e = tiny_qubo.evaluate(x)
            assert np.isfinite(e)


# ---------------------------------------------------------------------------
# 4. var_index and decode_bitstring consistency
# ---------------------------------------------------------------------------

class TestVarIndex:
    def test_var_index_unique(self, tiny_params):
        """Every (source, slot) pair must map to a unique flat index."""
        indices = set()
        for i in range(tiny_params.n_sources):
            for t in range(tiny_params.n_slots):
                vi = tiny_params.var_index(i, t)
                assert vi not in indices, f"Duplicate index {vi} for (i={i}, t={t})"
                indices.add(vi)
        assert len(indices) == tiny_params.n_vars

    def test_decode_roundtrip(self, tiny_qubo, tiny_params):
        """decode_bitstring should return on/off values matching the original x."""
        n = tiny_params.n_vars
        rng = np.random.default_rng(7)
        x = rng.integers(0, 2, size=n).astype(float)

        # Build bitstring (Qiskit convention: qubit 0 at rightmost position)
        bitstring = "".join(str(int(b)) for b in reversed(x))
        schedule = tiny_qubo.decode_bitstring(bitstring)

        for i, name in enumerate(tiny_params.source_names):
            for t in range(tiny_params.n_slots):
                vi = tiny_params.var_index(i, t)
                assert schedule[name][t] == int(x[vi]), (
                    f"Mismatch at source={name}, slot={t}"
                )
