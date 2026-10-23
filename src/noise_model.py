"""
noise_model.py — Realistic hardware noise model for Qiskit Aer simulation.

Builds a :class:`qiskit_aer.noise.NoiseModel` that approximates the error
rates seen on current NISQ devices:

  - 1-qubit depolarising error: p1 = 0.001  (0.1 %)
  - 2-qubit depolarising error: p2 = 0.01   (1.0 %)
  - Readout (measurement) error: p_meas = 0.02 (2.0 %)

The model is applied to all standard single- and two-qubit gates and to the
``measure`` instruction in the circuit.
"""

from __future__ import annotations

import warnings
from typing import Optional

# Graceful import so the module is importable even without qiskit-aer
try:
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import (
        NoiseModel,
        depolarizing_error,
        ReadoutError,
    )
    _AER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _AER_AVAILABLE = False
    warnings.warn(
        "qiskit-aer is not installed; build_noise_model() will return None. "
        "Install with: pip install qiskit-aer"
    )


# Default error rates
DEFAULT_P1: float = 0.001    # 1-qubit depolarising error probability
DEFAULT_P2: float = 0.01     # 2-qubit depolarising error probability
DEFAULT_P_MEAS: float = 0.02  # Readout / measurement error probability

# Standard single-qubit and two-qubit gate sets targeted by the noise model
_SINGLE_QUBIT_GATES = ["u1", "u2", "u3", "rx", "ry", "rz", "h", "x", "sx", "id"]
_TWO_QUBIT_GATES = ["cx", "cz", "ecr", "rzz"]


def build_noise_model(
    p1: float = DEFAULT_P1,
    p2: float = DEFAULT_P2,
    p_meas: float = DEFAULT_P_MEAS,
) -> Optional["NoiseModel"]:
    """Construct a realistic depolarising + readout noise model.

    This model approximates errors encountered on current superconducting-qubit
    hardware (e.g. IBM Quantum devices at the 100–127-qubit generation).

    Args:
        p1:     Depolarising error probability for single-qubit gates.
                Typical NISQ range: 1e-4 – 5e-3.
        p2:     Depolarising error probability for two-qubit gates.
                Typical NISQ range: 1e-3 – 2e-2.
        p_meas: Symmetric readout error probability (P(1|0) = P(0|1)).
                Typical NISQ range: 5e-3 – 5e-2.

    Returns:
        A :class:`~qiskit_aer.noise.NoiseModel` instance, or ``None`` if
        qiskit-aer is not installed.

    Raises:
        ValueError: If any error probability is outside [0, 1).
    """
    if not _AER_AVAILABLE:
        return None

    for name, val in [("p1", p1), ("p2", p2), ("p_meas", p_meas)]:
        if not (0.0 <= val < 1.0):
            raise ValueError(f"Error probability '{name}' must be in [0, 1), got {val}.")

    noise_model = NoiseModel()

    # ------------------------------------------------------------------ #
    # 1-qubit depolarising error
    # ------------------------------------------------------------------ #
    error_1q = depolarizing_error(p1, num_qubits=1)
    for gate in _SINGLE_QUBIT_GATES:
        noise_model.add_all_qubit_quantum_error(error_1q, [gate])

    # ------------------------------------------------------------------ #
    # 2-qubit depolarising error
    # ------------------------------------------------------------------ #
    error_2q = depolarizing_error(p2, num_qubits=2)
    for gate in _TWO_QUBIT_GATES:
        noise_model.add_all_qubit_quantum_error(error_2q, [gate])

    # ------------------------------------------------------------------ #
    # Readout (measurement) error — symmetric bit-flip channel
    # ------------------------------------------------------------------ #
    # ReadoutError([[P(0|0), P(1|0)], [P(0|1), P(1|1)]])
    readout_matrix = [
        [1.0 - p_meas, p_meas],      # measured 0: correct with prob 1-p, flip with p
        [p_meas, 1.0 - p_meas],      # measured 1: flip with p, correct with 1-p
    ]
    readout_error = ReadoutError(readout_matrix)
    noise_model.add_all_qubit_readout_error(readout_error)

    return noise_model


def get_simulator_with_noise(
    p1: float = DEFAULT_P1,
    p2: float = DEFAULT_P2,
    p_meas: float = DEFAULT_P_MEAS,
) -> Optional["AerSimulator"]:
    """Return an :class:`AerSimulator` pre-configured with the noise model.

    Convenience wrapper around :func:`build_noise_model`.

    Args:
        p1:     1-qubit depolarising error probability.
        p2:     2-qubit depolarising error probability.
        p_meas: Readout error probability.

    Returns:
        Noisy :class:`AerSimulator`, or ``None`` if qiskit-aer is missing.
    """
    if not _AER_AVAILABLE:
        return None
    nm = build_noise_model(p1=p1, p2=p2, p_meas=p_meas)
    return AerSimulator(noise_model=nm)
