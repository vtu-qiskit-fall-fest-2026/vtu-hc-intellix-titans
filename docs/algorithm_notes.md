# QAOA Green Dispatch — Algorithm Notes
# VTU Qiskit Fall Fest 2026 · Track 6

## Problem: Unit Commitment as QUBO

Binary variable x_{i,t} = 1 if energy source i is ON at time slot t.

Minimize:  x^T Q x
where Q encodes:
  (1) Demand penalty:  λ Σ_t (Σ_i cap_i·x_{i,t} − d_t)²
  (2) Cost:            Σ_{i,t} cost_i · x_{i,t}
  (3) CO₂:            α Σ_{i,t} co2_i · x_{i,t}

## QAOA Circuit Structure

Initial state:   |+⟩^⊗n  (Hadamard on all qubits)

For layer k = 1..p:
  Cost unitary:    U_C(γ_k) = exp(−iγ_k H_C)
    → ZZ pairs:  CNOT + Rz(2γJ_{ij}) + CNOT
    → Z terms:   Rz(2γh_i)

  Mixer unitary:   U_M(β_k) = exp(−iβ_k Σ X_i)
    → Rx(2β) on all qubits

Measure all qubits → decode → pick lowest QUBO energy bitstring

## Parameters

| Source  | Cap (kW) | Cost ($/kWh) | CO₂ (kg/kWh) |
|---------|----------|-------------|---------------|
| Solar   | 4.0      | 0.02        | 0.00          |
| Battery | 3.0      | 0.05        | 0.00          |
| Grid    | 6.0      | 0.12        | 0.45          |
| Diesel  | 5.0      | 0.35        | 0.82          |

## References

- Farhi et al. (2014): "A Quantum Approximate Optimization Algorithm" arXiv:1411.4028
- Glover et al. (2019): "Quantum Bridge Analytics I: A Tutorial on QUBO Formulations"
- Qiskit Documentation: https://docs.quantum.ibm.com/
- Qiskit Aer: https://qiskit.github.io/qiskit-aer/
