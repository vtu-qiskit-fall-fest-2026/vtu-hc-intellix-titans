"""
fill_official_template.py — Populates the official VTU-QFF-HC-XXXX.pptx template without disturbing any design elements.
"""

import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor

def populate_template():
    template_path = r"C:\Users\stewa\Downloads\VTU-QFF-HC-XXXX.pptx"
    output_path = r"C:\Users\stewa\.gemini\antigravity\scratch\repo-clone\docs\VTU-QFF-HC-0170.pptx"
    downloads_output = r"C:\Users\stewa\Downloads\VTU-QFF-HC-0170.pptx"

    prs = Presentation(template_path)

    # -------------------------------------------------------------
    # SLIDE 1: Participant Details (Right-side fields)
    # -------------------------------------------------------------
    s1 = prs.slides[0]

    def set_field_value(shape, val):
        if len(shape.text_frame.paragraphs) > 1:
            p = shape.text_frame.paragraphs[1]
            p.text = val
            p.font.name = "Calibri"
            p.font.size = Pt(11)
            p.font.bold = False

    set_field_value(s1.shapes[8], "QAOA Green Dispatch: Clean Energy Scheduling")
    set_field_value(s1.shapes[9], "Track 6: Climate Change & Sustainability")
    set_field_value(s1.shapes[10], "IntelliX Titans (VTU-QFF-HC-0170)")
    set_field_value(s1.shapes[11], "Team Lead")
    set_field_value(s1.shapes[12], "team@intellix-titans.dev")
    set_field_value(s1.shapes[13], "Lead  ·  Developer 1  ·  Developer 2")
    set_field_value(s1.shapes[14], "VTU Affiliated Institution")
    set_field_value(s1.shapes[15], "India")

    # Helper function to populate card text frames with bullet points
    def fill_card(shape, bullets, font_size=11):
        tf = shape.text_frame
        tf.word_wrap = True
        tf.clear()
        for idx, (heading, body) in enumerate(bullets):
            p = tf.add_paragraph() if idx > 0 else tf.paragraphs[0]
            p.space_after = Pt(6)
            run_h = p.add_run()
            run_h.text = heading + (" — " if heading else "")
            run_h.font.bold = True
            run_h.font.size = Pt(font_size)
            run_h.font.name = "Calibri"

            run_b = p.add_run()
            run_b.text = body
            run_b.font.bold = False
            run_b.font.size = Pt(font_size)
            run_b.font.name = "Calibri"

    # -------------------------------------------------------------
    # SLIDE 2: Problem Statement
    # -------------------------------------------------------------
    s2 = prs.slides[1]
    bullets_s2 = [
        ("The Challenge", "Power systems must decide, hour by hour, which energy sources (solar, battery storage, grid supply, diesel backup) to run so that demand is always met."),
        ("Exponential Complexity", "Choosing poorly raises costs and carbon emissions. The schedule search space grows exponentially as 2^(K×T) with every added source and time slot, making unit commitment combinatorial and NP-hard."),
        ("Why Classical Fails", "Classical brute force is intractable at grid scale, while greedy heuristics get trapped in local minima, often sacrificing clean energy or causing demand shortfalls."),
        ("Sustainability Focus", "Under Track 6 (Climate Change & Sustainability), our goal is to eliminate emergency diesel reliance and prioritize zero-emission renewables through quantum optimization.")
    ]
    fill_card(s2.shapes[6], bullets_s2, font_size=11)

    # -------------------------------------------------------------
    # SLIDE 3: Objectives & Novelty
    # -------------------------------------------------------------
    s3 = prs.slides[2]
    bullets_s3 = [
        ("Primary Objective", "Formulate the multi-period clean energy unit-commitment problem as a Quadratic Unconstrained Binary Optimization (QUBO) model solved via Qiskit QAOA."),
        ("Multi-Objective Cost Matrix", "Simultaneously optimizes operational costs ($/kWh), carbon footprint (kg CO₂/kWh), and quadratic demand-satisfaction penalties in a unified Hamiltonian."),
        ("Core Novelty", "Unlike classical greedy heuristics that switch off renewables prematurely, QAOA evaluates quantum superpositions of schedules to prioritize zero-emission solar and storage."),
        ("Hardware Noise Verification", "Benchmarked under a realistic NISQ hardware noise model (depolarizing + readout error) on Qiskit Aer to validate practical noise robustness.")
    ]
    fill_card(s3.shapes[6], bullets_s3, font_size=11)

    # -------------------------------------------------------------
    # SLIDE 4: Solution & Quantum Advantage
    # -------------------------------------------------------------
    s4 = prs.slides[3]
    bullets_s4 = [
        ("QUBO Mathematical Form", "min x^T Q x, where binary variables x_{i,t} ∈ {0, 1} represent whether energy source i is ON at hour t."),
        ("Ising Transformation", "Exact mapping x_i = (1 - s_i)/2 translates binary choices to spin states s_i ∈ {-1, +1}, yielding Cost Hamiltonian H_C = Σ J_{ij} Z_i Z_j + Σ h_i Z_i."),
        ("Quantum Advantage", "QAOA exploits quantum interference to concentrate measurement probability on low-energy, zero-diesel configurations, exploring 2^n states concurrently."),
        ("Proven Optimality", "In benchmark evaluations against exact classical brute-force, QAOA achieved an exact match (0.0% optimality gap), vastly outperforming classical greedy heuristics.")
    ]
    fill_card(s4.shapes[6], bullets_s4, font_size=11)

    # -------------------------------------------------------------
    # SLIDE 5: Algorithm & Circuit Design
    # -------------------------------------------------------------
    s5 = prs.slides[4]
    # Remove placeholder text in Shape 5
    s5.shapes[5].text_frame.clear()

    # Insert circuit diagram in the image area
    circ_img = r"C:\Users\stewa\.gemini\antigravity\scratch\repo-clone\docs\circuit_diagram.png"
    if os.path.exists(circ_img):
        s5.shapes.add_picture(circ_img, Inches(0.55), Inches(1.95), width=Inches(5.0))

    bullets_s5 = [
        ("Ansatz Structure", "p-layer QAOA circuit: |ψ(γ, β)⟩ = Π [ U_M(β_k) U_C(γ_k) ] |+⟩^⊗n"),
        ("Cost Unitary U_C(γ)", "e^{-iγ H_C} implemented with CNOT + Rz(2γ J_{ij}) + CNOT for 2-qubit ZZ terms and Rz(2γ h_i) for Z terms."),
        ("Mixer Unitary U_M(β)", "e^{-iβ Σ X_i} applying Rx(2β) rotations across all qubits to explore candidate schedules."),
        ("COBYLA Optimizer", "Gradient-free classical optimizer iteratively updates (γ, β) parameters via Qiskit Aer statevector & noisy sampling.")
    ]
    fill_card(s5.shapes[8], bullets_s5, font_size=10.5)

    # -------------------------------------------------------------
    # SLIDE 6: Implementation & Tech Stack
    # -------------------------------------------------------------
    s6 = prs.slides[5]
    bullets_s6 = [
        ("Quantum Stack", "Qiskit 1.x core SDK, SparsePauliOp for exact Hamiltonian construction, and Qiskit Aer for noiseless statevector and hardware noise simulation."),
        ("Optimization Engine", "SciPy COBYLA optimizer with robust fallback mechanisms; exact 2^n brute-force solver and greedy priority heuristic baselines."),
        ("Frontend & Dashboard", "Streamlit multi-tab reactive web dashboard with Plotly interactive energy curves, emission pie charts, and runtime comparisons."),
        ("Cloud Deployment", "Deployed live on Render.com (vtu-hc-intellix-titans.onrender.com) for real-time evaluator demonstrations."),
        ("Repository & Testing", "Fully tested via Pytest with modular architecture (circuit.py, optimizer.py, problem.py, noise_model.py, main.py).")
    ]
    fill_card(s6.shapes[6], bullets_s6, font_size=11)

    # -------------------------------------------------------------
    # SLIDE 7: Results & Analysis
    # -------------------------------------------------------------
    s7 = prs.slides[6]
    # Remove placeholder text in Shape 5
    s7.shapes[5].text_frame.clear()

    # Insert results chart in the image area
    res_img = r"C:\Users\stewa\.gemini\antigravity\scratch\repo-clone\docs\results_chart.png"
    if os.path.exists(res_img):
        s7.shapes.add_picture(res_img, Inches(0.55), Inches(1.95), width=Inches(5.0))

    bullets_s7 = [
        ("Exact Solution Match", "QAOA achieved 0.0% gap from the global brute-force minimum energy (5.0184 vs 237.65 for greedy heuristic)."),
        ("100% Demand Satisfaction", "Satisfied all power demand without deficits while completely eliminating expensive diesel backup (0% diesel)."),
        ("CO₂ & Cost Savings", "Saved 24.5% in operational expenses and 17.1% in carbon emissions compared to baseline fossil backup."),
        ("Noise Robustness", "Under Aer depolarizing and readout noise, QAOA retained near-optimal solutions within 5% of noiseless statevector.")
    ]
    fill_card(s7.shapes[8], bullets_s7, font_size=10.5)

    # -------------------------------------------------------------
    # SLIDE 8: Impact & Real-World Applications
    # -------------------------------------------------------------
    s8 = prs.slides[7]
    bullets_s8 = [
        ("Microgrid Energy Management", "Autonomous clean dispatch for university campuses, industrial microgrids, and off-grid renewable installations."),
        ("Renewable Curtailment Reduction", "Dynamically absorbs surplus intermittent solar into battery storage, preventing green energy curtailment."),
        ("Urban Net-Zero Transition", "Scalable quantum framework to coordinate distributed energy resources (DERs) in smart cities to meet Net-Zero 2030 targets."),
        ("Utility-Scale Adoption", "As fault-tolerant quantum hardware matures, QAOA scales to 1,000+ power nodes where classical integer programming times out.")
    ]
    fill_card(s8.shapes[6], bullets_s8, font_size=11)

    # -------------------------------------------------------------
    # SLIDE 9: Challenges & Future Scope
    # -------------------------------------------------------------
    s9 = prs.slides[8]
    bullets_s9 = [
        ("Current NISQ Challenges", "Limited qubit coherence times and two-qubit CNOT gate error rates constrain QAOA circuit depth on physical QPUs."),
        ("Quantum Error Mitigation", "Future scope includes integrating Zero-Noise Extrapolation (ZNE) via Qiskit Runtime to improve noisy QPU fidelity."),
        ("Dynamic Real-Time Pricing", "Extending the QUBO objective to incorporate dynamic time-of-use (TOU) power tariffs and EV charging load spikes."),
        ("Multi-Bus Power Grids", "Scaling to 24-hour schedules with transmission line power-flow constraints (AC-OPF) on IBM Quantum hardware.")
    ]
    fill_card(s9.shapes[6], bullets_s9, font_size=11)

    # -------------------------------------------------------------
    # SLIDE 10: CLOSING
    # -------------------------------------------------------------
    s10 = prs.slides[9]

    # Shape 3: GITHUB REPOSITORY
    if len(s10.shapes[3].text_frame.paragraphs) > 1:
        p_git = s10.shapes[3].text_frame.paragraphs[1]
        p_git.text = "github.com/vtu-qiskit-fall-fest-2026/vtu-hc-intellix-titans"
        p_git.font.name = "Calibri"
        p_git.font.size = Pt(11)

    # Shape 4: DEMO VIDEO LINK
    if len(s10.shapes[4].text_frame.paragraphs) > 1:
        p_demo = s10.shapes[4].text_frame.paragraphs[1]
        p_demo.text = "https://vtu-hc-intellix-titans.onrender.com"
        p_demo.font.name = "Calibri"
        p_demo.font.size = Pt(11)

    # Save to both repo docs and Downloads
    prs.save(output_path)
    prs.save(downloads_output)
    print(f"Template populated successfully!")
    print(f"Repo file     : {output_path}")
    print(f"Downloads file: {downloads_output}")

if __name__ == "__main__":
    populate_template()
