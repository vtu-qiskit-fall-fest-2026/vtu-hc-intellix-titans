"""
qaoa_solver.py — QAOA-based solver for the Green Energy Dispatch QUBO.

Uses Qiskit 1.x APIs:
  - qiskit.quantum_info.SparsePauliOp  for Hamiltonian construction
  - qiskit.circuit.library.QAOAAnsatz (falls back to manual build if unavailable)
  - qiskit_aer simulators (StatevectorSimulator / AerSimulator)
  - COBYLA optimizer via scipy (with optional qiskit_algorithms wrapper)

The solver converts the QUBO to an Ising (J, h) model, builds the cost
Hamiltonian H_C = sum_ij J_ij Z_i Z_j + sum_i h_i Z_i, and runs QAOA with p
layers of (cost + mixer) unitaries.
"""

from __future__ import annotations

import time
import warnings
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Qiskit 1.x core imports
# ---------------------------------------------------------------------------
try:
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import SparsePauliOp, Statevector
    from qiskit.circuit import Parameter, ParameterVector
    from qiskit.circuit.library import QAOAAnsatz
    _QISKIT_OK = True
except ImportError as exc:  # pragma: no cover
    warnings.warn(f"Qiskit not available: {exc}. QAOASolver will be non-functional.")
    _QISKIT_OK = False

# ---------------------------------------------------------------------------
# Aer simulator imports
# ---------------------------------------------------------------------------
try:
    from qiskit_aer import AerSimulator
    from qiskit_aer.primitives import Sampler as AerSampler
    _AER_OK = True
except ImportError:  # pragma: no cover
    _AER_OK = False
    warnings.warn("qiskit-aer not available; noisy simulation disabled.")

# ---------------------------------------------------------------------------
# Classical optimiser — prefer scipy COBYLA, fall back gracefully
# ---------------------------------------------------------------------------
try:
    from scipy.optimize import minimize as scipy_minimize
    _SCIPY_OK = True
except ImportError:  # pragma: no cover
    _SCIPY_OK = False
    warnings.warn("scipy not available; optimisation will use random parameters.")

from src.problem import ProblemParams, QuboMatrix


# ---------------------------------------------------------------------------
# Helper: build cost Hamiltonian from Ising (J, h)
# ---------------------------------------------------------------------------

def _build_cost_hamiltonian(J: np.ndarray, h: np.ndarray) -> "SparsePauliOp":
    """Construct the Ising cost Hamiltonian as a :class:`SparsePauliOp`.

    H_C = sum_{i<j} J_ij Z_i Z_j + sum_i h_i Z_i

    Pauli string convention for *n* qubits: the *rightmost* character of the
    string acts on qubit 0, so a Z on qubit *k* in an *n*-qubit register is
    placed at position ``n - 1 - k`` in the string.

    Args:
        J: (n × n) coupling matrix (upper triangle used).
        h: (n,) local field vector.

    Returns:
        SparsePauliOp representing H_C.
    """
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
        # Trivial all-identity Hamiltonian
        paulis = [("I" * n, 0.0 + 0j)]

    return SparsePauliOp.from_list(paulis)


# ---------------------------------------------------------------------------
# Helper: build QAOA circuit manually (fallback / explicit)
# ---------------------------------------------------------------------------

def _build_qaoa_circuit_manual(
    cost_op: "SparsePauliOp",
    p: int,
) -> Tuple["QuantumCircuit", "ParameterVector", "ParameterVector"]:
    """Build a QAOA circuit with *p* layers without using QAOAAnsatz.

    Layers alternate between:
      - Cost unitary: exp(-i γ H_C)
      - Mixer unitary: exp(-i β H_B), where H_B = sum_i X_i

    The cost unitary is decomposed using the Pauli exponential method:
    for ZZ: CNOT + Rz(2γ J) + CNOT; for Z: Rz(2γ h).

    Args:
        cost_op: The cost Hamiltonian as a SparsePauliOp.
        p:       Number of QAOA layers.

    Returns:
        (circuit, gammas, betas) — the parameterised QuantumCircuit and the
        two ParameterVectors of length p.
    """
    n = cost_op.num_qubits
    gammas = ParameterVector("γ", length=p)
    betas = ParameterVector("β", length=p)

    qc = QuantumCircuit(n)

    # Initial state: uniform superposition
    qc.h(range(n))

    for layer in range(p):
        # --- Cost layer ---
        for pauli_term, coeff in cost_op.to_list():
            angle = 2.0 * float(np.real(coeff)) * gammas[layer]
            z_qubits = [
                n - 1 - k
                for k, char in enumerate(pauli_term)
                if char == "Z"
            ]
            if len(z_qubits) == 1:
                qc.rz(angle, z_qubits[0])
            elif len(z_qubits) == 2:
                qi, qj = z_qubits
                qc.cx(qi, qj)
                qc.rz(angle, qj)
                qc.cx(qi, qj)
            # Higher-weight Paulis ignored (not present in Ising model)

        # --- Mixer layer ---
        for qubit in range(n):
            qc.rx(2.0 * betas[layer], qubit)

    return qc, gammas, betas


# ---------------------------------------------------------------------------
# Main solver class
# ---------------------------------------------------------------------------

class QAOASolver:
    """QAOA solver for the unit-commitment / green dispatch QUBO.

    Attributes:
        qubo:   The built :class:`QuboMatrix` instance.
        p:      QAOA circuit depth (number of (cost + mixer) layers).
        shots:  Number of measurement shots for sampling.
    """

    def __init__(
        self,
        qubo_problem: QuboMatrix,
        p: int = 2,
        shots: int = 1024,
    ) -> None:
        """Initialise the solver.

        Args:
            qubo_problem: A **built** :class:`QuboMatrix` (call `.build()` first).
            p:            QAOA depth (number of alternating layers).
            shots:        Number of measurement shots.

        Raises:
            RuntimeError: If Qiskit is not installed.
        """
        if not _QISKIT_OK:
            raise RuntimeError("Qiskit is required. Install with: pip install qiskit qiskit-aer")

        self.qubo = qubo_problem
        self.p = p
        self.shots = shots
        self.params = qubo_problem.params

        # Derived Ising representation
        J, h, self._ising_offset = qubo_problem.to_ising()
        self.J = J
        self.h = h
        self.n_qubits = qubo_problem.params.n_vars

        # Build cost Hamiltonian
        self.cost_op: SparsePauliOp = _build_cost_hamiltonian(J, h)

        # Circuit and parameters cached after build_circuit()
        self._circuit: Optional[QuantumCircuit] = None
        self._gammas: Optional[ParameterVector] = None
        self._betas: Optional[ParameterVector] = None

    # ------------------------------------------------------------------
    # Circuit construction
    # ------------------------------------------------------------------

    def build_circuit(self) -> QuantumCircuit:
        """Build and return the parameterised QAOA QuantumCircuit.

        Tries to use Qiskit's :class:`~qiskit.circuit.library.QAOAAnsatz`
        first; falls back to a manually constructed circuit if not available.

        Returns:
            The parameterised :class:`~qiskit.QuantumCircuit`.
        """
        try:
            # QAOAAnsatz expects a cost operator and mixer
            ansatz = QAOAAnsatz(cost_operator=self.cost_op, reps=self.p)
            ansatz_bound = ansatz.decompose()
            self._circuit = ansatz_bound
            # Extract parameter vectors
            params = sorted(ansatz.parameters, key=lambda p: p.name)
            self._gammas = [p for p in params if "gamma" in p.name.lower() or "γ" in p.name]
            self._betas = [p for p in params if "beta" in p.name.lower() or "β" in p.name]
            # Fallback if naming differs
            if not self._gammas or not self._betas:
                mid = len(params) // 2
                self._gammas = params[:mid]
                self._betas = params[mid:]
        except Exception:  # pragma: no cover — use manual fallback
            circuit, gammas, betas = _build_qaoa_circuit_manual(self.cost_op, self.p)
            self._circuit = circuit
            self._gammas = list(gammas)
            self._betas = list(betas)

        return self._circuit

    # ------------------------------------------------------------------
    # Energy evaluation
    # ------------------------------------------------------------------

    def _evaluate_energy(
        self,
        params_vec: np.ndarray,
        simulator: Any,
    ) -> float:
        """Evaluate the expectation value ⟨H_C⟩ for given parameters.

        Uses statevector arithmetic for noiseless runs (fast) and shot-based
        sampling for noisy runs.

        Args:
            params_vec: Flattened [γ_1, …, γ_p, β_1, …, β_p] parameter array.
            simulator:  An Aer simulator instance or ``"statevector"``.

        Returns:
            Expectation value (float); lower is better.
        """
        if self._circuit is None:
            self.build_circuit()

        # Bind parameters
        all_params = list(self._gammas) + list(self._betas)
        binding = dict(zip(all_params, params_vec))
        bound_qc = self._circuit.assign_parameters(binding)

        if simulator == "statevector":
            # Exact statevector evaluation
            bound_qc_sv = bound_qc.copy()
            sv = Statevector(bound_qc_sv)
            # E = <ψ|H_C|ψ>  via SparsePauliOp
            expectation = sv.expectation_value(self.cost_op).real
            return float(expectation)
        else:
            # Shot-based: sample, then compute weighted average from counts
            meas_qc = bound_qc.copy()
            meas_qc.measure_all()
            job = simulator.run(meas_qc, shots=self.shots)
            counts = job.result().get_counts()
            energy = 0.0
            total = sum(counts.values())
            for bitstring, count in counts.items():
                bits = np.array([int(b) for b in reversed(bitstring)], dtype=float)
                energy += (count / total) * self.qubo.evaluate(bits)
            return energy

    # ------------------------------------------------------------------
    # Sampling / decoding
    # ------------------------------------------------------------------

    def _sample_counts(
        self,
        params_vec: np.ndarray,
        simulator: Any,
    ) -> Dict[str, int]:
        """Run the circuit with fixed parameters and return measurement counts.

        Args:
            params_vec: Bound parameter values.
            simulator:  Aer simulator instance or ``"statevector"``.

        Returns:
            Dictionary of {bitstring: count}.
        """
        all_params = list(self._gammas) + list(self._betas)
        binding = dict(zip(all_params, params_vec))
        bound_qc = self._circuit.assign_parameters(binding)

        if simulator == "statevector":
            # For statevector, sample probabilities
            bound_qc_sv = bound_qc.copy()
            sv = Statevector(bound_qc_sv)
            probs = sv.probabilities_dict()
            # Convert probabilities → pseudo-counts
            counts = {k: max(1, round(v * self.shots)) for k, v in probs.items()}
        else:
            meas_qc = bound_qc.copy()
            meas_qc.measure_all()
            job = simulator.run(meas_qc, shots=self.shots)
            counts = job.result().get_counts()

        return counts

    # ------------------------------------------------------------------
    # Public solve interface
    # ------------------------------------------------------------------

    def solve(self, use_noise: bool = False) -> Dict[str, Any]:
        """Run QAOA optimisation and return the best schedule found.

        Args:
            use_noise: If True and qiskit-aer is available, runs on a noisy
                       simulator using the default noise model.

        Returns:
            Dictionary with keys:

            - ``best_bitstring``   – str, the bitstring with lowest QUBO cost.
            - ``best_cost``        – float, QUBO energy of that bitstring.
            - ``all_counts``       – dict {bitstring: count}.
            - ``optimal_params``   – np.ndarray of optimised [γ…, β…] values.
            - ``circuit_depth``    – int, transpiled circuit depth.
            - ``schedule``         – dict {source_name: [on/off per slot]}.
            - ``n_qubits``         – int.
            - ``runtime_s``        – float, wall-clock solve time.
        """
        if use_noise:
            return self.solve_with_noise()

        t0 = time.time()
        if self._circuit is None:
            self.build_circuit()

        simulator = "statevector"

        # Optimise with COBYLA via scipy
        n_params = self.p * 2  # p gammas + p betas
        x0 = np.random.uniform(0, np.pi, size=n_params)

        best_energy = np.inf
        optimal_params = x0.copy()

        def objective(params: np.ndarray) -> float:
            nonlocal best_energy, optimal_params
            e = self._evaluate_energy(params, simulator)
            if e < best_energy:
                best_energy = e
                optimal_params = params.copy()
            return e

        if _SCIPY_OK:
            result = scipy_minimize(
                objective,
                x0,
                method="COBYLA",
                options={"maxiter": 500, "rhobeg": 0.5},
            )
            optimal_params = result.x
        else:
            # Fallback: random search with 200 trials
            for _ in range(200):
                params = np.random.uniform(0, np.pi, size=n_params)
                objective(params)

        # Sample final distribution
        counts = self._sample_counts(optimal_params, simulator)

        # Find best bitstring by minimum QUBO cost
        best_bitstring, best_cost = self._best_from_counts(counts)
        schedule = self.qubo.decode_bitstring(best_bitstring)
        depth = self._circuit.depth()

        return {
            "best_bitstring": best_bitstring,
            "best_cost": best_cost,
            "all_counts": counts,
            "optimal_params": optimal_params,
            "circuit_depth": depth,
            "schedule": schedule,
            "n_qubits": self.n_qubits,
            "runtime_s": time.time() - t0,
        }

    def solve_with_noise(self, noise_model: Optional[Any] = None) -> Dict[str, Any]:
        """Run QAOA on a noisy Aer simulator.

        Args:
            noise_model: A :class:`qiskit_aer.noise.NoiseModel` instance.
                         If None, the default model from :mod:`src.noise_model`
                         is used.

        Returns:
            Same dictionary as :meth:`solve`.

        Raises:
            RuntimeError: If qiskit-aer is not installed.
        """
        if not _AER_OK:
            raise RuntimeError("qiskit-aer is required for noisy simulation.")

        t0 = time.time()
        if self._circuit is None:
            self.build_circuit()

        if noise_model is None:
            from src.noise_model import build_noise_model
            noise_model = build_noise_model()

        simulator = AerSimulator(noise_model=noise_model)

        n_params = self.p * 2
        x0 = np.random.uniform(0, np.pi, size=n_params)
        best_energy = np.inf
        optimal_params = x0.copy()

        def objective(params: np.ndarray) -> float:
            nonlocal best_energy, optimal_params
            e = self._evaluate_energy(params, simulator)
            if e < best_energy:
                best_energy = e
                optimal_params = params.copy()
            return e

        if _SCIPY_OK:
            scipy_minimize(
                objective,
                x0,
                method="COBYLA",
                options={"maxiter": 300, "rhobeg": 0.5},
            )
        else:
            for _ in range(100):
                params = np.random.uniform(0, np.pi, size=n_params)
                objective(params)

        counts = self._sample_counts(optimal_params, simulator)
        best_bitstring, best_cost = self._best_from_counts(counts)
        schedule = self.qubo.decode_bitstring(best_bitstring)

        return {
            "best_bitstring": best_bitstring,
            "best_cost": best_cost,
            "all_counts": counts,
            "optimal_params": optimal_params,
            "circuit_depth": self._circuit.depth(),
            "schedule": schedule,
            "n_qubits": self.n_qubits,
            "runtime_s": time.time() - t0,
            "noisy": True,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _best_from_counts(
        self, counts: Dict[str, int]
    ) -> Tuple[str, float]:
        """Select the bitstring with the minimum QUBO energy from counts.

        Args:
            counts: {bitstring: count} dictionary.

        Returns:
            (best_bitstring, best_cost) tuple.
        """
        best_cost = np.inf
        best_bitstring = "0" * self.n_qubits
        for bitstring in counts:
            # Pad or trim to n_qubits
            bs = bitstring.zfill(self.n_qubits)[-self.n_qubits:]
            bits = np.array([int(b) for b in reversed(bs)], dtype=float)
            cost = self.qubo.evaluate(bits)
            if cost < best_cost:
                best_cost = cost
                best_bitstring = bs
        return best_bitstring, best_cost
