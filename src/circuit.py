"""
circuit.py — Quantum circuit construction for QAOA Green Dispatch.

Builds the QAOA ansatz circuit for the green energy unit-commitment QUBO.
The cost Hamiltonian is derived from the Ising (J, h) representation of the
QUBO, and the mixer Hamiltonian is the standard transverse-field X mixer.

Public API
----------
build_cost_hamiltonian(J, h)  -> SparsePauliOp
build_qaoa_circuit(cost_op, p) -> (QuantumCircuit, gammas, betas)
draw_circuit(circuit, params)  -> str  (ASCII or matplotlib)
"""

from __future__ import annotations

import warnings
from typing import List, Optional, Tuple

import numpy as np

try:
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import SparsePauliOp
    from qiskit.circuit import Parameter, ParameterVector
    from qiskit.circuit.library import QAOAAnsatz
    _QISKIT_OK = True
except ImportError as exc:  # pragma: no cover
    warnings.warn(f"Qiskit not available: {exc}")
    _QISKIT_OK = False


# ---------------------------------------------------------------------------
# Cost Hamiltonian
# ---------------------------------------------------------------------------

def build_cost_hamiltonian(J: np.ndarray, h: np.ndarray) -> "SparsePauliOp":
    """Construct the Ising cost Hamiltonian as a SparsePauliOp.

    H_C = Σ_{i<j} J_ij Z_i Z_j  +  Σ_i h_i Z_i

    The Pauli-string convention: the *rightmost* character acts on qubit 0,
    so a Z on qubit k in an n-qubit register sits at index ``n - 1 - k``.

    Args:
        J: (n × n) symmetric coupling matrix (upper triangle used).
        h: (n,) local field vector.

    Returns:
        SparsePauliOp representing H_C.
    """
    if not _QISKIT_OK:
        raise ImportError("Qiskit is required to build the cost Hamiltonian.")

    n = len(h)
    paulis: List[Tuple[str, complex]] = []

    # Single-qubit Z terms
    for i in range(n):
        if abs(h[i]) < 1e-12:
            continue
        pauli_str = ["I"] * n
        pauli_str[n - 1 - i] = "Z"
        paulis.append(("".join(pauli_str), complex(h[i])))

    # Two-qubit ZZ terms
    for i in range(n):
        for j in range(i + 1, n):
            if abs(J[i, j]) < 1e-12:
                continue
            pauli_str = ["I"] * n
            pauli_str[n - 1 - i] = "Z"
            pauli_str[n - 1 - j] = "Z"
            paulis.append(("".join(pauli_str), complex(J[i, j])))

    if not paulis:
        paulis = [("I" * n, 0.0 + 0j)]

    return SparsePauliOp.from_list(paulis)


# ---------------------------------------------------------------------------
# QAOA Circuit — primary builder
# ---------------------------------------------------------------------------

def build_qaoa_circuit(
    cost_op: "SparsePauliOp",
    p: int = 1,
    use_library_ansatz: bool = True,
) -> Tuple["QuantumCircuit", "ParameterVector", "ParameterVector"]:
    """Build a parameterised QAOA circuit with p cost+mixer layers.

    Attempts to use ``QAOAAnsatz`` from qiskit.circuit.library (Qiskit 1.x).
    Falls back to a manually constructed circuit if the library class is
    unavailable or if ``use_library_ansatz=False``.

    Args:
        cost_op:            SparsePauliOp cost Hamiltonian.
        p:                  Number of QAOA layers (circuit depth parameter).
        use_library_ansatz: If True (default), prefer QAOAAnsatz.

    Returns:
        (circuit, gammas, betas):
            circuit — the parameterised QuantumCircuit.
            gammas  — ParameterVector of length p (cost angles).
            betas   — ParameterVector of length p (mixer angles).
    """
    if not _QISKIT_OK:
        raise ImportError("Qiskit is required.")

    gammas = ParameterVector("γ", p)
    betas = ParameterVector("β", p)

    # --- Try QAOAAnsatz ---
    if use_library_ansatz:
        try:
            ansatz = QAOAAnsatz(cost_op, reps=p)
            ansatz = ansatz.decompose()
            # Re-bind our named parameters to the ansatz parameters
            # QAOAAnsatz names them theta_0..theta_{2p-1}
            params = list(ansatz.parameters)
            # First p are cost (gamma), last p are mixer (beta)
            param_map = {}
            for k in range(p):
                param_map[params[k]] = gammas[k]
            for k in range(p):
                param_map[params[p + k]] = betas[k]
            circuit = ansatz.assign_parameters(param_map)
            circuit.measure_all()
            return circuit, gammas, betas
        except Exception:
            pass  # fall through to manual build

    # --- Manual QAOA circuit ---
    return _build_manual_qaoa(cost_op, p, gammas, betas)


def _build_manual_qaoa(
    cost_op: "SparsePauliOp",
    p: int,
    gammas: "ParameterVector",
    betas: "ParameterVector",
) -> Tuple["QuantumCircuit", "ParameterVector", "ParameterVector"]:
    """Hand-crafted QAOA circuit: alternating cost and mixer unitaries.

    Cost unitary U_C(γ) = exp(-iγ H_C):
      - For Z terms:  Rz(2γ h_i) on qubit i
      - For ZZ terms: CNOT + Rz(2γ J_ij) + CNOT

    Mixer unitary U_M(β) = exp(-iβ H_B), H_B = Σ X_i:
      - Rx(2β) on every qubit

    Args:
        cost_op: SparsePauliOp Hamiltonian.
        p:       Number of layers.
        gammas:  ParameterVector of length p.
        betas:   ParameterVector of length p.

    Returns:
        (circuit, gammas, betas)
    """
    n = cost_op.num_qubits
    qc = QuantumCircuit(n, n)

    # Initial state: uniform superposition
    qc.h(range(n))

    for layer in range(p):
        gamma = gammas[layer]
        beta = betas[layer]

        # --- Cost unitary ---
        for term, coeff in zip(cost_op.paulis, cost_op.coeffs):
            pauli_str = term.to_label()  # e.g. "IZZI"
            coeff_r = float(np.real(coeff))
            if abs(coeff_r) < 1e-12:
                continue

            active = [(n - 1 - k) for k, ch in enumerate(pauli_str) if ch == "Z"]

            if len(active) == 1:
                qc.rz(2 * gamma * coeff_r, active[0])
            elif len(active) == 2:
                i, j = active[0], active[1]
                qc.cx(i, j)
                qc.rz(2 * gamma * coeff_r, j)
                qc.cx(i, j)
            # Higher-order terms: skip (QUBO → at most 2-local)

        qc.barrier()

        # --- Mixer unitary ---
        for q in range(n):
            qc.rx(2 * beta, q)

        qc.barrier()

    # Measure all
    qc.measure(range(n), range(n))

    return qc, gammas, betas


# ---------------------------------------------------------------------------
# Drawing helper
# ---------------------------------------------------------------------------

def draw_circuit(
    circuit: "QuantumCircuit",
    output: str = "text",
    fold: int = 80,
) -> str:
    """Return a text or matplotlib drawing of the circuit.

    Args:
        circuit: The (possibly bound) QuantumCircuit.
        output:  ``"text"`` for ASCII, ``"mpl"`` for matplotlib figure.
        fold:    Line-wrap column for text output.

    Returns:
        String representation (text mode) or saves/shows mpl figure.
    """
    if not _QISKIT_OK:
        return "Qiskit not available."
    drawing = circuit.draw(output=output, fold=fold)
    return str(drawing)
