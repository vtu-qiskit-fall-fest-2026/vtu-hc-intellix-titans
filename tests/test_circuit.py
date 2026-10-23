"""
test_circuit.py — Unit tests for src/circuit.py (quantum circuit construction).
"""

from __future__ import annotations

import numpy as np
import pytest

# Skip entire module if Qiskit is not installed
qiskit = pytest.importorskip("qiskit", reason="Qiskit not installed")

from src.problem import ProblemParams, QuboMatrix
from src.circuit import build_cost_hamiltonian, build_qaoa_circuit, draw_circuit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tiny_problem():
    """2-slot problem → 8 binary variables (8 qubits)."""
    params = ProblemParams(
        n_slots=2,
        demands=[4.0, 6.0],
        solar_avail=[0.5, 1.0],
    )
    qubo = QuboMatrix(params).build()
    return params, qubo


@pytest.fixture
def tiny_ising(tiny_problem):
    _, qubo = tiny_problem
    J, h, offset = qubo.to_ising()
    return J, h, offset


# ---------------------------------------------------------------------------
# Test: build_cost_hamiltonian
# ---------------------------------------------------------------------------

class TestBuildCostHamiltonian:
    def test_returns_sparse_pauli_op(self, tiny_ising):
        from qiskit.quantum_info import SparsePauliOp
        J, h, _ = tiny_ising
        cost_op = build_cost_hamiltonian(J, h)
        assert isinstance(cost_op, SparsePauliOp)

    def test_num_qubits_matches_problem_size(self, tiny_ising, tiny_problem):
        params, _ = tiny_problem
        J, h, _ = tiny_ising
        cost_op = build_cost_hamiltonian(J, h)
        assert cost_op.num_qubits == params.n_vars

    def test_hamiltonian_is_hermitian(self, tiny_ising):
        """SparsePauliOp built from real Z/ZZ terms must be Hermitian."""
        J, h, _ = tiny_ising
        cost_op = build_cost_hamiltonian(J, h)
        mat = cost_op.to_matrix()
        assert np.allclose(mat, mat.conj().T, atol=1e-8), \
            "Cost Hamiltonian must be Hermitian."

    def test_identity_fallback_for_zero_hamiltonian(self):
        """All-zero J and h should produce a valid (identity) Hamiltonian."""
        n = 4
        J = np.zeros((n, n))
        h = np.zeros(n)
        cost_op = build_cost_hamiltonian(J, h)
        assert cost_op.num_qubits == n

    def test_pauli_strings_contain_only_z_and_i(self, tiny_ising):
        """QUBO → Ising gives only Z/ZZ terms; no X or Y Paulis."""
        J, h, _ = tiny_ising
        cost_op = build_cost_hamiltonian(J, h)
        for pauli in cost_op.paulis:
            label = pauli.to_label()
            assert set(label).issubset({"I", "Z"}), \
                f"Unexpected Pauli character in: {label}"


# ---------------------------------------------------------------------------
# Test: build_qaoa_circuit
# ---------------------------------------------------------------------------

class TestBuildQAOACircuit:
    def test_returns_quantum_circuit(self, tiny_ising, tiny_problem):
        from qiskit import QuantumCircuit
        params, _ = tiny_problem
        J, h, _ = tiny_ising
        cost_op = build_cost_hamiltonian(J, h)
        circuit, gammas, betas = build_qaoa_circuit(cost_op, p=1)
        assert isinstance(circuit, QuantumCircuit)

    def test_circuit_has_correct_qubit_count(self, tiny_ising, tiny_problem):
        params, _ = tiny_problem
        J, h, _ = tiny_ising
        cost_op = build_cost_hamiltonian(J, h)
        circuit, _, _ = build_qaoa_circuit(cost_op, p=1)
        assert circuit.num_qubits == params.n_vars

    def test_parameter_counts_match_depth_p(self, tiny_ising):
        J, h, _ = tiny_ising
        cost_op = build_cost_hamiltonian(J, h)
        for p in [1, 2, 3]:
            circuit, gammas, betas = build_qaoa_circuit(cost_op, p=p)
            assert len(gammas) == p, f"Expected {p} gammas for p={p}"
            assert len(betas) == p,  f"Expected {p} betas for p={p}"

    def test_circuit_has_parameters(self, tiny_ising):
        J, h, _ = tiny_ising
        cost_op = build_cost_hamiltonian(J, h)
        circuit, gammas, betas = build_qaoa_circuit(cost_op, p=2)
        assert len(circuit.parameters) > 0, "Circuit must have free parameters."

    def test_circuit_can_be_bound(self, tiny_ising):
        """Binding all parameters should produce a circuit with no free params."""
        J, h, _ = tiny_ising
        cost_op = build_cost_hamiltonian(J, h)
        circuit, gammas, betas = build_qaoa_circuit(cost_op, p=1)
        param_map = {g: 0.5 for g in gammas}
        param_map.update({b: 0.3 for b in betas})
        bound = circuit.assign_parameters(param_map)
        assert len(bound.parameters) == 0, "Bound circuit must have no free params."

    def test_circuit_depth_increases_with_p(self, tiny_ising):
        J, h, _ = tiny_ising
        cost_op = build_cost_hamiltonian(J, h)
        _, c1, _ = build_qaoa_circuit(cost_op, p=1), *build_qaoa_circuit(cost_op, p=1)[1:]
        circ1, _, _ = build_qaoa_circuit(cost_op, p=1)
        circ2, _, _ = build_qaoa_circuit(cost_op, p=2)
        assert circ2.depth() >= circ1.depth(), \
            "Deeper p should produce deeper circuit."

    def test_manual_fallback_circuit(self, tiny_ising):
        """Force manual circuit construction and verify it works."""
        J, h, _ = tiny_ising
        cost_op = build_cost_hamiltonian(J, h)
        circuit, gammas, betas = build_qaoa_circuit(
            cost_op, p=1, use_library_ansatz=False
        )
        assert circuit.num_qubits == cost_op.num_qubits
        assert len(circuit.parameters) > 0


# ---------------------------------------------------------------------------
# Test: draw_circuit
# ---------------------------------------------------------------------------

class TestDrawCircuit:
    def test_draw_returns_string(self, tiny_ising):
        J, h, _ = tiny_ising
        cost_op = build_cost_hamiltonian(J, h)
        circuit, gammas, betas = build_qaoa_circuit(cost_op, p=1)
        # Bind parameters so drawing is deterministic
        bound = circuit.assign_parameters(
            {g: 0.5 for g in gammas} | {b: 0.3 for b in betas}
        )
        drawing = draw_circuit(bound, output="text")
        assert isinstance(drawing, str)
        assert len(drawing) > 0
