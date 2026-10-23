"""
optimizer.py — QAOA optimization loop for QAOA Green Dispatch.

Ties together circuit construction (circuit.py), QUBO evaluation (problem.py),
and the COBYLA classical optimizer into a single ``run_optimization`` function
that returns a structured result dictionary.

Public API
----------
run_optimization(params, qubo, p, shots, use_noise) -> dict
compare_solvers(params, qubo, p)                    -> dict
"""

from __future__ import annotations

import time
import warnings
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Qiskit Aer
try:
    from qiskit_aer import AerSimulator
    _AER_OK = True
except ImportError:
    _AER_OK = False
    warnings.warn("qiskit-aer not installed; simulation unavailable.")

# SciPy COBYLA
try:
    from scipy.optimize import minimize as scipy_minimize
    _SCIPY_OK = True
except ImportError:
    _SCIPY_OK = False
    warnings.warn("scipy not installed; falling back to random search.")

from src.problem import ProblemParams, QuboMatrix
from src.circuit import build_cost_hamiltonian, build_qaoa_circuit
from src.noise_model import build_noise_model


# ---------------------------------------------------------------------------
# Core optimization runner
# ---------------------------------------------------------------------------

def run_optimization(
    params: ProblemParams,
    qubo: QuboMatrix,
    p: int = 2,
    shots: int = 1024,
    use_noise: bool = False,
    max_iter: int = 500,
    seed: int = 42,
) -> Dict[str, Any]:
    """Run the full QAOA optimization pipeline.

    Steps
    -----
    1. Convert QUBO → Ising (J, h).
    2. Build cost Hamiltonian H_C via ``build_cost_hamiltonian``.
    3. Build QAOA ansatz circuit via ``build_qaoa_circuit``.
    4. Classically optimize circuit parameters (COBYLA) by minimizing
       the expected QUBO energy estimated from measurement counts.
    5. Sample the optimized circuit and decode the best bitstring.

    Args:
        params:    Problem parameters (sources, demands, etc.).
        qubo:      Pre-built :class:`~src.problem.QuboMatrix`.
        p:         QAOA depth (number of cost+mixer layers).
        shots:     Number of measurement shots per evaluation.
        use_noise: If True, add a hardware noise model to the Aer simulator.
        max_iter:  Maximum COBYLA iterations.
        seed:      RNG seed for reproducibility.

    Returns:
        A dict with keys:
          best_bitstring   – binary string of the optimal solution.
          best_cost        – QUBO energy of the best solution.
          all_counts       – {bitstring: count} from final sampling.
          optimal_params   – optimized γ and β angles (numpy array).
          circuit_depth    – compiled circuit depth.
          schedule         – decoded {source: [on/off per slot]} dict.
          n_qubits         – total number of qubits used.
          runtime_s        – wall-clock time in seconds.
          noisy            – whether noise model was applied.
    """
    if not _AER_OK:
        raise RuntimeError(
            "qiskit-aer is required. Install with: pip install qiskit-aer"
        )

    t0 = time.time()
    rng = np.random.default_rng(seed)

    # 1. QUBO → Ising
    J, h, _offset = qubo.to_ising()
    n_qubits = params.n_vars

    # 2. Cost Hamiltonian
    cost_op = build_cost_hamiltonian(J, h)

    # 3. QAOA Circuit
    circuit, gammas, betas = build_qaoa_circuit(cost_op, p=p)

    # 4. Set up simulator
    if use_noise:
        noise_model = build_noise_model()
        simulator = AerSimulator(noise_model=noise_model)
    else:
        simulator = AerSimulator(method="statevector")

    # 5. Optimization loop
    n_params = 2 * p  # p gammas + p betas
    x0 = rng.uniform(0, np.pi, size=n_params)

    best_energy = np.inf
    best_params = x0.copy()

    def objective(theta: np.ndarray) -> float:
        """Evaluate expected QUBO energy for parameter vector theta."""
        nonlocal best_energy, best_params
        energy = _evaluate_energy(theta, circuit, gammas, betas,
                                  qubo, simulator, shots)
        if energy < best_energy:
            best_energy = energy
            best_params = theta.copy()
        return energy

    if _SCIPY_OK:
        result = scipy_minimize(
            objective,
            x0,
            method="COBYLA",
            options={"maxiter": max_iter, "rhobeg": 0.5},
        )
        optimal_params = result.x
    else:
        # Random-search fallback
        for _ in range(200):
            theta = rng.uniform(0, np.pi, size=n_params)
            objective(theta)
        optimal_params = best_params

    # 6. Final sampling at optimal parameters
    counts = _sample_counts(optimal_params, circuit, gammas, betas,
                            simulator, shots)

    # 7. Decode best solution
    best_bitstring, best_cost = _best_from_counts(counts, qubo, n_qubits)
    schedule = qubo.decode_bitstring(best_bitstring)

    return {
        "best_bitstring": best_bitstring,
        "best_cost": best_cost,
        "all_counts": counts,
        "optimal_params": optimal_params,
        "circuit_depth": circuit.depth(),
        "schedule": schedule,
        "n_qubits": n_qubits,
        "runtime_s": time.time() - t0,
        "noisy": use_noise,
    }


# ---------------------------------------------------------------------------
# Benchmark helper: compare QAOA vs classical solvers
# ---------------------------------------------------------------------------

def compare_solvers(
    params: ProblemParams,
    qubo: QuboMatrix,
    p: int = 2,
    shots: int = 1024,
) -> Dict[str, Any]:
    """Run QAOA, brute-force, and greedy solvers and return a comparison dict.

    Args:
        params: Problem parameters.
        qubo:   Pre-built QuboMatrix.
        p:      QAOA circuit depth.
        shots:  Measurement shots for QAOA.

    Returns:
        Dict with keys ``"qaoa"``, ``"brute_force"``, ``"greedy"``, each
        containing solver result dicts with at least ``best_cost`` and
        ``runtime_s``.
    """
    from src.classical_solvers import BruteForceSolver, GreedySolver
    from src.co2_calculator import calculate_metrics

    results: Dict[str, Any] = {}

    # QAOA
    try:
        qaoa_res = run_optimization(params, qubo, p=p, shots=shots)
        qaoa_res["metrics"] = calculate_metrics(qaoa_res["schedule"], params)
        results["qaoa"] = qaoa_res
    except Exception as exc:
        results["qaoa"] = {"error": str(exc), "best_cost": float("inf"), "runtime_s": 0}

    # Brute force
    try:
        bf = BruteForceSolver(qubo, params)
        results["brute_force"] = bf.solve()
        results["brute_force"]["metrics"] = calculate_metrics(
            results["brute_force"]["schedule"], params
        )
    except Exception as exc:
        results["brute_force"] = {"error": str(exc), "best_cost": float("inf"), "runtime_s": 0}

    # Greedy
    try:
        gs = GreedySolver(params)
        results["greedy"] = gs.solve()
        results["greedy"]["metrics"] = calculate_metrics(
            results["greedy"]["schedule"], params
        )
    except Exception as exc:
        results["greedy"] = {"error": str(exc), "best_cost": float("inf"), "runtime_s": 0}

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bind_and_run(
    theta: np.ndarray,
    circuit: "QuantumCircuit",
    gammas: "ParameterVector",
    betas: "ParameterVector",
    simulator: "AerSimulator",
    shots: int,
) -> Dict[str, int]:
    """Bind parameters, transpile, and run on the simulator.

    Args:
        theta:     1-D array [γ_0,...,γ_{p-1}, β_0,...,β_{p-1}].
        circuit:   Parameterised QuantumCircuit.
        gammas:    ParameterVector for cost angles.
        betas:     ParameterVector for mixer angles.
        simulator: AerSimulator instance.
        shots:     Number of measurement shots.

    Returns:
        {bitstring: count} dictionary.
    """
    from qiskit import transpile

    p = len(gammas)
    param_map = {}
    for k in range(p):
        param_map[gammas[k]] = float(theta[k])
        param_map[betas[k]] = float(theta[p + k])

    bound = circuit.assign_parameters(param_map)
    tqc = transpile(bound, simulator)
    job = simulator.run(tqc, shots=shots)
    result = job.result()
    return result.get_counts()


def _sample_counts(
    theta: np.ndarray,
    circuit: "QuantumCircuit",
    gammas: "ParameterVector",
    betas: "ParameterVector",
    simulator: "AerSimulator",
    shots: int,
) -> Dict[str, int]:
    """Wrapper around _bind_and_run with error handling."""
    try:
        return _bind_and_run(theta, circuit, gammas, betas, simulator, shots)
    except Exception as exc:
        warnings.warn(f"Circuit execution failed: {exc}")
        return {"0" * circuit.num_qubits: shots}


def _evaluate_energy(
    theta: np.ndarray,
    circuit: "QuantumCircuit",
    gammas: "ParameterVector",
    betas: "ParameterVector",
    qubo: QuboMatrix,
    simulator: "AerSimulator",
    shots: int,
) -> float:
    """Estimate expected QUBO energy from measurement counts.

    Args:
        theta:     Current parameter vector.
        circuit:   Parameterised QAOA circuit.
        gammas:    ParameterVector for cost angles.
        betas:     ParameterVector for mixer angles.
        qubo:      QuboMatrix for energy evaluation.
        simulator: AerSimulator instance.
        shots:     Measurement shots.

    Returns:
        Scalar expected energy (lower is better).
    """
    counts = _sample_counts(theta, circuit, gammas, betas, simulator, shots)
    n = qubo.params.n_vars
    total_energy = 0.0
    total_shots = sum(counts.values())

    for bitstring, count in counts.items():
        bs = bitstring.zfill(n)[-n:]
        bits = np.array([int(b) for b in reversed(bs)], dtype=float)
        energy = qubo.evaluate(bits)
        total_energy += energy * count

    return total_energy / max(total_shots, 1)


def _best_from_counts(
    counts: Dict[str, int],
    qubo: QuboMatrix,
    n_qubits: int,
) -> Tuple[str, float]:
    """Find the lowest-energy bitstring from measurement counts.

    Args:
        counts:   {bitstring: count} dictionary.
        qubo:     QuboMatrix for energy evaluation.
        n_qubits: Expected bitstring length.

    Returns:
        (best_bitstring, best_cost)
    """
    best_cost = np.inf
    best_bitstring = "0" * n_qubits

    for bitstring in counts:
        bs = bitstring.zfill(n_qubits)[-n_qubits:]
        bits = np.array([int(b) for b in reversed(bs)], dtype=float)
        cost = qubo.evaluate(bits)
        if cost < best_cost:
            best_cost = cost
            best_bitstring = bs

    return best_bitstring, best_cost
