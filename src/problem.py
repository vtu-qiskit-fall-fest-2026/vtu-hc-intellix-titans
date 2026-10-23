"""
problem.py — QUBO formulation for the Green Energy Dispatch problem.

For N time slots and K energy sources we define binary variables
x_{i,t} = 1 if source i is ON at time slot t.

The QUBO cost encodes:
  1. Demand-satisfaction penalty: for each t, (sum_i cap_i*x_{i,t} - demand_t)^2 * penalty
  2. Operational cost objective: sum_{i,t} cost_i * x_{i,t}
  3. CO2 emission objective:     sum_{i,t} co2_i  * x_{i,t} * co2_weight
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Default energy-source parameters (4 sources)
# ---------------------------------------------------------------------------
DEFAULT_SOURCE_NAMES: List[str] = ["Solar", "Battery", "Grid", "Diesel"]

# Capacity in kW for each source
DEFAULT_CAPACITIES: List[float] = [4.0, 3.0, 6.0, 5.0]

# Operational cost in $/kWh
DEFAULT_COSTS: List[float] = [0.02, 0.05, 0.12, 0.35]

# CO₂ emission factor in kg CO₂ / kWh
DEFAULT_CO2: List[float] = [0.0, 0.0, 0.45, 0.82]


@dataclass
class ProblemParams:
    """Container for all problem parameters.

    Attributes:
        n_slots:        Number of time slots.
        source_names:   Human-readable name for each energy source.
        capacities:     Rated power (kW) that source i delivers when ON.
        costs:          Operational cost ($/kWh) for source i.
        co2_factors:    CO₂ emission rate (kg/kWh) for source i.
        demands:        Energy demand (kW) at each time slot.
        solar_avail:    Per-slot availability multiplier for solar [0, 1].
        penalty_weight: Lagrange multiplier for demand-constraint penalty.
        co2_weight:     Relative weight given to CO₂ in the objective.
    """

    n_slots: int = 4
    source_names: List[str] = field(default_factory=lambda: list(DEFAULT_SOURCE_NAMES))
    capacities: List[float] = field(default_factory=lambda: list(DEFAULT_CAPACITIES))
    costs: List[float] = field(default_factory=lambda: list(DEFAULT_COSTS))
    co2_factors: List[float] = field(default_factory=lambda: list(DEFAULT_CO2))
    demands: List[float] = field(default_factory=lambda: [5.0, 7.0, 6.0, 4.0])
    solar_avail: List[float] = field(default_factory=lambda: [0.0, 0.8, 1.0, 0.3])
    penalty_weight: float = 10.0
    co2_weight: float = 0.5

    def __post_init__(self) -> None:
        """Validate shapes are consistent."""
        k = len(self.source_names)
        assert len(self.capacities) == k, "capacities length mismatch"
        assert len(self.costs) == k, "costs length mismatch"
        assert len(self.co2_factors) == k, "co2_factors length mismatch"
        assert len(self.demands) == self.n_slots, "demands length mismatch"
        assert len(self.solar_avail) == self.n_slots, "solar_avail length mismatch"

    @property
    def n_sources(self) -> int:
        """Number of energy sources (K)."""
        return len(self.source_names)

    @property
    def n_vars(self) -> int:
        """Total binary variables = K * N."""
        return self.n_sources * self.n_slots

    def effective_capacity(self, source_idx: int, slot_idx: int) -> float:
        """Return the effective capacity of *source_idx* at *slot_idx* (kW).

        Solar capacity is scaled by the slot's availability factor.
        """
        cap = self.capacities[source_idx]
        if self.source_names[source_idx].lower() == "solar":
            cap *= self.solar_avail[slot_idx]
        return cap

    def var_index(self, source_idx: int, slot_idx: int) -> int:
        """Map (source_idx, slot_idx) → flat variable index."""
        return source_idx * self.n_slots + slot_idx


class QuboMatrix:
    """Build and store the QUBO matrix for the energy dispatch problem.

    The variable ordering is: x_{0,0}, x_{0,1}, …, x_{0,T-1},
                               x_{1,0}, …, x_{K-1,T-1}.

    So variable index = source_idx * n_slots + slot_idx.
    """

    def __init__(self, params: ProblemParams) -> None:
        """Initialise the QUBO builder.

        Args:
            params: A fully populated :class:`ProblemParams` instance.
        """
        self.params = params
        n = params.n_vars
        self._Q: np.ndarray = np.zeros((n, n), dtype=float)
        self._offset: float = 0.0  # constant term accumulated during build
        self._built: bool = False

    # ------------------------------------------------------------------
    # Builder methods
    # ------------------------------------------------------------------

    def _add_demand_penalty(self) -> None:
        """Add squared-penalty term for demand satisfaction at each slot.

        For slot t: penalty * (sum_i cap_{i,t} * x_{i,t} - demand_t)^2

        Expanding:  penalty * [ sum_i cap_{i,t}^2 * x_{i,t}
                               + 2 * sum_{i<j} cap_{i,t}*cap_{j,t} * x_{i,t}*x_{j,t}
                               - 2 * demand_t * sum_i cap_{i,t} * x_{i,t}
                               + demand_t^2 ]
        """
        p = self.params
        lam = p.penalty_weight

        for t in range(p.n_slots):
            d = p.demands[t]
            self._offset += lam * d * d  # constant term

            for i in range(p.n_sources):
                cap_i = p.effective_capacity(i, t)
                vi = p.var_index(i, t)
                # Diagonal: cap_i^2 - 2*demand*cap_i  (using x^2 = x for binary)
                self._Q[vi, vi] += lam * (cap_i * cap_i - 2.0 * d * cap_i)

                for j in range(i + 1, p.n_sources):
                    cap_j = p.effective_capacity(j, t)
                    vj = p.var_index(j, t)
                    # Off-diagonal coupling: 2 * cap_i * cap_j (symmetrised below)
                    self._Q[vi, vj] += lam * 2.0 * cap_i * cap_j

    def _add_cost_objective(self) -> None:
        """Add linear cost objective: sum_{i,t} cost_i * x_{i,t}."""
        p = self.params
        for i in range(p.n_sources):
            for t in range(p.n_slots):
                vi = p.var_index(i, t)
                self._Q[vi, vi] += p.costs[i]

    def _add_co2_objective(self) -> None:
        """Add linear CO₂ objective: co2_weight * sum_{i,t} co2_i * x_{i,t}."""
        p = self.params
        for i in range(p.n_sources):
            for t in range(p.n_slots):
                vi = p.var_index(i, t)
                self._Q[vi, vi] += p.co2_weight * p.co2_factors[i]

    def build(self) -> "QuboMatrix":
        """Assemble all QUBO terms and symmetrise the matrix.

        Returns:
            self, for chaining.
        """
        self._add_demand_penalty()
        self._add_cost_objective()
        self._add_co2_objective()

        # Symmetrise: Q_sym = (Q + Q^T) / 2
        # (upper-triangle already filled; lower stays zero until symmetrised)
        self._Q = (self._Q + self._Q.T) / 2.0
        self._built = True
        return self

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def Q(self) -> np.ndarray:
        """The (n_vars × n_vars) QUBO matrix Q (symmetrised)."""
        if not self._built:
            raise RuntimeError("Call .build() before accessing Q.")
        return self._Q

    @property
    def offset(self) -> float:
        """Constant energy offset accumulated during build."""
        return self._offset

    def evaluate(self, x: np.ndarray) -> float:
        """Compute the QUBO energy for a binary vector *x*.

        Args:
            x: 1-D binary array of length n_vars.

        Returns:
            Scalar energy value x^T Q x + offset.
        """
        if not self._built:
            raise RuntimeError("Call .build() first.")
        x = np.asarray(x, dtype=float)
        return float(x @ self._Q @ x) + self._offset

    def to_ising(self) -> Tuple[np.ndarray, np.ndarray, float]:
        """Convert QUBO to Ising (J, h) form.

        Variable substitution: x_i = (1 - s_i) / 2,  s_i ∈ {-1, +1}.

        Returns:
            J:      (n_vars × n_vars) coupling matrix (upper triangle).
            h:      (n_vars,) local field vector.
            offset: Constant energy offset.
        """
        if not self._built:
            raise RuntimeError("Call .build() first.")

        n = self.params.n_vars
        Q = self._Q.copy()

        # Linear contribution to h
        h = np.zeros(n)
        J = np.zeros((n, n))
        offset = self._offset

        # x_i = (1 - s_i)/2  →  x_i^2 = x_i  (binary)
        # x_i x_j = (1-s_i)(1-s_j)/4
        for i in range(n):
            # Diagonal Q_{ii} x_i:   Q_{ii}/4 * (1 - s_i)(treated as linear+const)
            h[i] -= Q[i, i] / 4.0
            offset += Q[i, i] / 4.0

        for i in range(n):
            for j in range(i + 1, n):
                if Q[i, j] == 0.0:
                    continue
                q = Q[i, j]
                J[i, j] += q / 4.0
                h[i] -= q / 4.0
                h[j] -= q / 4.0
                offset += q / 4.0

        return J, h, offset

    def decode_bitstring(self, bitstring: str) -> Dict[str, List[int]]:
        """Decode a bitstring into the (source × slot) schedule.

        Args:
            bitstring: Binary string of length n_vars. The convention used
                       by Qiskit is that the *rightmost* character is qubit 0,
                       so we reverse before indexing.

        Returns:
            Dict mapping source name → list of on/off values per slot.
        """
        p = self.params
        # Qiskit counts string right-to-left; reverse so index 0 = leftmost qubit
        bits = list(reversed(bitstring))
        schedule: Dict[str, List[int]] = {name: [] for name in p.source_names}
        for i, name in enumerate(p.source_names):
            for t in range(p.n_slots):
                vi = p.var_index(i, t)
                val = int(bits[vi]) if vi < len(bits) else 0
                schedule[name].append(val)
        return schedule


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def build_default_problem(n_slots: int = 4, penalty: float = 10.0,
                           co2_weight: float = 0.5) -> Tuple[ProblemParams, QuboMatrix]:
    """Return a :class:`ProblemParams` and a built :class:`QuboMatrix`.

    Uses the data_generator module to create a realistic daily profile.

    Args:
        n_slots:    Number of time slots (2–8 recommended).
        penalty:    Demand-constraint Lagrange multiplier.
        co2_weight: Weight given to CO₂ in the objective.

    Returns:
        (params, qubo) ready for use by solvers.
    """
    from src.data_generator import generate_daily_profile  # lazy import

    profile = generate_daily_profile(n_slots=n_slots)
    params = ProblemParams(
        n_slots=n_slots,
        demands=profile["demands"],
        solar_avail=profile["solar_availability"],
        penalty_weight=penalty,
        co2_weight=co2_weight,
    )
    qubo = QuboMatrix(params).build()
    return params, qubo
