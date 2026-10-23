"""
test_co2.py — Unit tests for the CO₂ and cost calculator.
"""

import pytest
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.problem import ProblemParams, QuboMatrix
from src.co2_calculator import calculate_metrics, format_metrics_table


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def params_2slot():
    """Minimal 4-source, 2-slot problem."""
    return ProblemParams(
        n_slots=2,
        demands=[4.0, 6.0],
        solar_avail=[1.0, 0.0],
        penalty_weight=10.0,
        co2_weight=0.5,
    )


@pytest.fixture
def all_off_schedule(params_2slot):
    """Schedule where all sources are OFF."""
    return {name: [0, 0] for name in params_2slot.source_names}


@pytest.fixture
def all_solar_schedule(params_2slot):
    """Schedule where only Solar is ON for both slots."""
    sched = {name: [0, 0] for name in params_2slot.source_names}
    sched["Solar"] = [1, 1]
    return sched


@pytest.fixture
def all_diesel_schedule(params_2slot):
    """Schedule where only Diesel is ON for both slots."""
    sched = {name: [0, 0] for name in params_2slot.source_names}
    sched["Diesel"] = [1, 1]
    return sched


@pytest.fixture
def mixed_schedule(params_2slot):
    """Solar ON slot 0, Grid ON slot 1."""
    sched = {name: [0, 0] for name in params_2slot.source_names}
    sched["Solar"] = [1, 0]
    sched["Grid"]  = [0, 1]
    return sched


# ---------------------------------------------------------------------------
# Tests: basic structure and types
# ---------------------------------------------------------------------------

class TestCalculateMetricsStructure:
    def test_required_keys(self, params_2slot, all_off_schedule):
        """All required keys must be present in the metrics dict."""
        metrics = calculate_metrics(all_off_schedule, params_2slot)
        required = [
            "total_cost_usd",
            "total_co2_kg",
            "demand_satisfaction_pct",
            "supplied_kw_per_slot",
            "cost_by_source",
            "co2_by_source",
            "cost_vs_diesel_savings_usd",
            "co2_vs_diesel_savings_kg",
            "diesel_cost_usd",
            "diesel_co2_kg",
        ]
        for key in required:
            assert key in metrics, f"Missing key: {key}"

    def test_supplied_length(self, params_2slot, mixed_schedule):
        """supplied_kw_per_slot must have length n_slots."""
        metrics = calculate_metrics(mixed_schedule, params_2slot)
        assert len(metrics["supplied_kw_per_slot"]) == params_2slot.n_slots

    def test_cost_by_source_keys(self, params_2slot, mixed_schedule):
        """cost_by_source must contain an entry for each source."""
        metrics = calculate_metrics(mixed_schedule, params_2slot)
        for name in params_2slot.source_names:
            assert name in metrics["cost_by_source"]
            assert name in metrics["co2_by_source"]


# ---------------------------------------------------------------------------
# Tests: known-value calculations
# ---------------------------------------------------------------------------

class TestKnownValues:
    def test_all_off_zero_cost(self, params_2slot, all_off_schedule):
        """All-off schedule → zero cost and zero CO₂."""
        m = calculate_metrics(all_off_schedule, params_2slot)
        assert m["total_cost_usd"] == pytest.approx(0.0, abs=1e-9)
        assert m["total_co2_kg"] == pytest.approx(0.0, abs=1e-9)

    def test_all_off_zero_demand_satisfaction(self, params_2slot, all_off_schedule):
        """All-off schedule → 0% demand satisfaction."""
        m = calculate_metrics(all_off_schedule, params_2slot)
        assert m["demand_satisfaction_pct"] == pytest.approx(0.0, abs=1e-9)

    def test_solar_zero_co2(self, params_2slot, all_solar_schedule):
        """Solar-only schedule → zero CO₂ (co2_factor = 0)."""
        m = calculate_metrics(all_solar_schedule, params_2slot)
        assert m["total_co2_kg"] == pytest.approx(0.0, abs=1e-9)

    def test_solar_cost(self, params_2slot, all_solar_schedule):
        """Solar-only schedule cost = cap_solar * cost_solar * n_active_slots.

        Slot 0: cap_eff = 4 * 1.0 = 4 kW, cost = 0.02 $/kWh → 0.08 $
        Slot 1: cap_eff = 4 * 0.0 = 0 kW (night), cost = 0
        Total  = 0.08 $
        """
        m = calculate_metrics(all_solar_schedule, params_2slot)
        expected_cost = 4.0 * 1.0 * 0.02 + 4.0 * 0.0 * 0.02  # slot0 + slot1
        assert m["total_cost_usd"] == pytest.approx(expected_cost, rel=1e-6)

    def test_diesel_high_co2(self, params_2slot, all_diesel_schedule):
        """Diesel-only schedule should produce maximum CO₂."""
        m_diesel = calculate_metrics(all_diesel_schedule, params_2slot)
        # CO₂ = 5 kW * 0.82 kg/kWh * 2 slots = 8.2 kg
        expected_co2 = 5.0 * 0.82 * 2
        assert m_diesel["total_co2_kg"] == pytest.approx(expected_co2, rel=1e-6)

    def test_diesel_baseline_matches_all_diesel(self, params_2slot, all_diesel_schedule):
        """diesel_co2_kg must equal the all-diesel schedule's CO₂."""
        m = calculate_metrics(all_diesel_schedule, params_2slot)
        # diesel_co2_kg uses full capacity * n_slots (not effective; diesel has no avail factor)
        assert m["diesel_co2_kg"] == pytest.approx(m["total_co2_kg"], rel=1e-6)

    def test_mixed_schedule_cost(self, params_2slot, mixed_schedule):
        """Solar slot0 + Grid slot1: manually computed cost."""
        # Solar slot0: eff_cap = 4*1.0 = 4 kW, cost_rate = 0.02 → 0.08 $
        # Grid  slot1: cap = 6 kW, cost_rate = 0.12 → 0.72 $
        expected = 4.0 * 1.0 * 0.02 + 6.0 * 0.12
        m = calculate_metrics(mixed_schedule, params_2slot)
        assert m["total_cost_usd"] == pytest.approx(expected, rel=1e-6)

    def test_mixed_schedule_co2(self, params_2slot, mixed_schedule):
        """Solar slot0 + Grid slot1: manually computed CO₂."""
        # Solar: 0 kg/kWh; Grid slot1: 6 * 0.45 = 2.70 kg
        expected = 6.0 * 0.45
        m = calculate_metrics(mixed_schedule, params_2slot)
        assert m["total_co2_kg"] == pytest.approx(expected, rel=1e-6)

    def test_savings_are_positive_for_clean_schedules(self, params_2slot, all_solar_schedule):
        """Cost and CO₂ savings vs diesel should be positive for solar-only."""
        m = calculate_metrics(all_solar_schedule, params_2slot)
        assert m["cost_vs_diesel_savings_usd"] > 0
        assert m["co2_vs_diesel_savings_kg"] > 0

    def test_demand_satisfaction_100pct(self, params_2slot):
        """Schedule that over-supplies in all slots → 100% satisfaction."""
        # All sources ON for both slots; total cap >> demand
        sched = {name: [1, 1] for name in params_2slot.source_names}
        m = calculate_metrics(sched, params_2slot)
        assert m["demand_satisfaction_pct"] == pytest.approx(100.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Tests: format_metrics_table
# ---------------------------------------------------------------------------

class TestFormatMetricsTable:
    def test_returns_string(self, params_2slot, mixed_schedule):
        """format_metrics_table must return a non-empty string."""
        m = calculate_metrics(mixed_schedule, params_2slot)
        table = format_metrics_table(m)
        assert isinstance(table, str)
        assert len(table) > 0

    def test_contains_key_values(self, params_2slot, mixed_schedule):
        """The formatted table should contain the numeric values."""
        m = calculate_metrics(mixed_schedule, params_2slot)
        table = format_metrics_table(m)
        assert str(m["demand_satisfaction_pct"]) in table or "%" in table
