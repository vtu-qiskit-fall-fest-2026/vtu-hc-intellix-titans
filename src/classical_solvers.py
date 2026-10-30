"""
classical_solvers.py — Brute-force and greedy baselines for QUBO comparison.

Two classical solvers are provided:

1. :class:`BruteForceSolver` — Evaluates every binary assignment x ∈ {0,1}^n
   and returns the one with the lowest QUBO energy.  Exact but exponential in n;
   capped at n ≤ 20 to prevent runaway memory usage.

2. :class:`GreedySolver` — Constructs a feasible schedule by iterating over
   time slots and greedily activating the cheapest energy sources until the
   demand for that slot is met.  Runs in O(n_slots × n_sources log n_sources)
   time.
"""

from __future__ import annotations

import time
import warnings
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.problem import ProblemParams, QuboMatrix

# Maximum number of binary variables before brute force is blocked
_BRUTE_FORCE_MAX_BITS = 20


class BruteForceSolver:
    """Exact solver that exhaustively searches all 2^n binary assignments.

    For large problems (n_vars > 20) this becomes intractable. A
    :exc:`RuntimeWarning` is issued if n_vars > 20 and the solver raises a
    :exc:`ValueError`.

    Attributes:
        qubo: The built :class:`QuboMatrix` instance to optimise.
    """

    def __init__(self, qubo_problem: QuboMatrix) -> None:
        """Initialise the brute-force solver.

        Args:
            qubo_problem: A **built** :class:`QuboMatrix`.

        Raises:
            ValueError: If the problem has more than 20 binary variables.
        """
        self.qubo = qubo_problem
        n = qubo_problem.params.n_vars
        if n > _BRUTE_FORCE_MAX_BITS:
            raise ValueError(
                f"BruteForceSolver is capped at {_BRUTE_FORCE_MAX_BITS} bits "
                f"(problem has {n} bits). Use GreedySolver for larger instances."
            )

    def solve(self) -> Dict[str, Any]:
        """Enumerate all 2^n bitstrings and return the global optimum.

        Returns:
            Dictionary with keys:

            - ``best_bitstring``   – str.
            - ``best_cost``        – float, minimum QUBO energy found.
            - ``schedule``         – dict {source_name: [on/off per slot]}.
            - ``n_evaluated``      – int, total bitstrings evaluated.
            - ``runtime_s``        – float, wall-clock time in seconds.
        """
        t0 = time.time()
        n = self.qubo.params.n_vars

        if n <= 18:
            # High-performance vectorized evaluation via NumPy
            ints = np.arange(2 ** n, dtype=np.uint32)
            X = ((ints[:, None] >> np.arange(n)) & 1).astype(np.float64)
            costs = np.sum((X @ self.qubo.Q) * X, axis=1) + self.qubo.offset
            best_idx = int(np.argmin(costs))
            best_cost = float(costs[best_idx])
            best_bits = X[best_idx]
        else:
            best_cost = np.inf
            best_bits = np.zeros(n, dtype=float)
            for i in range(2 ** n):
                bits = np.array([(i >> k) & 1 for k in range(n)], dtype=float)
                cost = self.qubo.evaluate(bits)
                if cost < best_cost:
                    best_cost = cost
                    best_bits = bits.copy()

        # Convert to bitstring (Qiskit big-endian: qubit 0 at right)
        best_bitstring = "".join(str(int(b)) for b in reversed(best_bits))
        schedule = self.qubo.decode_bitstring(best_bitstring)

        return {
            "best_bitstring": best_bitstring,
            "best_cost": best_cost,
            "schedule": schedule,
            "n_evaluated": 2 ** n,
            "runtime_s": time.time() - t0,
        }


class GreedySolver:
    """Greedy heuristic solver for the energy dispatch problem.

    For each time slot, sources are sorted by a composite priority score
    (lower cost + lower CO₂ contribution) and switched ON in priority order
    until the demand is met or all sources are exhausted.

    If demand cannot be fully met by available capacity, the solver falls
    back to diesel backup (highest CO₂ / cost source) to guarantee feasibility.

    Attributes:
        qubo:   The :class:`QuboMatrix` instance (used only to evaluate cost).
        params: The :class:`ProblemParams` extracted from the qubo.
    """

    def __init__(self, qubo_problem: QuboMatrix) -> None:
        """Initialise the greedy solver.

        Args:
            qubo_problem: A **built** :class:`QuboMatrix`.
        """
        self.qubo = qubo_problem
        self.params = qubo_problem.params

    def _priority_order(self, slot: int) -> List[int]:
        """Return source indices sorted by cheapest-first composite score.

        The composite score is:
            score_i = cost_i + co2_weight * co2_i

        Solar is additionally de-prioritised when its effective capacity at the
        current slot is zero (night-time).

        Args:
            slot: Time-slot index.

        Returns:
            List of source indices, cheapest first.
        """
        p = self.params
        scores = []
        for i in range(p.n_sources):
            eff_cap = p.effective_capacity(i, slot)
            if eff_cap < 1e-6:
                # Source unavailable at this slot — rank last
                score = 1e9
            else:
                score = p.costs[i] + p.co2_weight * p.co2_factors[i]
            scores.append((score, i))
        scores.sort()
        return [idx for _, idx in scores]

    def solve(self) -> Dict[str, Any]:
        """Run the greedy dispatch algorithm.

        Returns:
            Dictionary with keys:

            - ``best_bitstring``     – str, the greedy assignment.
            - ``best_cost``          – float, QUBO energy of that assignment.
            - ``schedule``           – dict {source_name: [on/off per slot]}.
            - ``demand_met``         – list[bool], whether demand was fully met
                                       at each slot.
            - ``supplied_kw``        – list[float], kW supplied per slot.
            - ``runtime_s``          – float, wall-clock time.
        """
        t0 = time.time()
        p = self.params
        n = p.n_vars

        # on_off[source_idx][slot_idx] ∈ {0, 1}
        on_off: List[List[int]] = [[0] * p.n_slots for _ in range(p.n_sources)]
        demand_met: List[bool] = []
        supplied_kw: List[float] = []

        for t in range(p.n_slots):
            remaining = p.demands[t]
            order = self._priority_order(t)
            for i in order:
                eff_cap = p.effective_capacity(i, t)
                if eff_cap <= 0:
                    continue
                if remaining > 0:
                    on_off[i][t] = 1
                    remaining -= eff_cap

            supplied = sum(
                p.effective_capacity(i, t) * on_off[i][t]
                for i in range(p.n_sources)
            )
            demand_met.append(remaining <= 0)
            supplied_kw.append(supplied)

        # Flatten to variable vector (same ordering as QuboMatrix)
        bits = np.zeros(n, dtype=float)
        for i in range(p.n_sources):
            for t in range(p.n_slots):
                vi = p.var_index(i, t)
                bits[vi] = on_off[i][t]

        cost = self.qubo.evaluate(bits)
        # Build bitstring (Qiskit big-endian)
        best_bitstring = "".join(str(int(b)) for b in reversed(bits))
        schedule = self.qubo.decode_bitstring(best_bitstring)

        return {
            "best_bitstring": best_bitstring,
            "best_cost": cost,
            "schedule": schedule,
            "demand_met": demand_met,
            "supplied_kw": supplied_kw,
            "runtime_s": time.time() - t0,
        }
