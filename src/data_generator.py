"""
data_generator.py — Synthetic daily energy-demand and solar-availability profiles.

Generates realistic 24-hour energy data at configurable temporal resolution.
The demand curve follows a typical residential/commercial pattern:
  - Low demand overnight (00:00–06:00)
  - Morning ramp (06:00–09:00)
  - Peak at noon / early afternoon (09:00–15:00)
  - Evening secondary peak (17:00–20:00)
  - Decline overnight

Solar availability is zero before 06:00 and after 20:00, with a bell-shaped
curve peaking at solar noon (12:00–13:00).
"""

from __future__ import annotations

import math
from typing import Dict, List, Any


def _demand_at_hour(hour: float) -> float:
    """Return a normalised demand value in [0, 1] at a fractional hour of the day."""
    if hour < 6.0:
        return 0.30 + 0.05 * math.sin(math.pi * hour / 6.0)
    if hour < 9.0:
        t = (hour - 6.0) / 3.0
        return 0.30 + 0.55 * t
    if hour < 17.0:
        return 0.80 + 0.10 * math.sin(math.pi * (hour - 9.0) / 8.0)
    if hour < 20.0:
        t = (hour - 17.0) / 3.0
        return 0.85 + 0.15 * math.sin(math.pi * t)
    t = (hour - 20.0) / 4.0
    return 1.00 - 0.70 * t


def _solar_at_hour(hour: float) -> float:
    """Return normalised solar irradiance in [0, 1] at a fractional hour."""
    if hour < 6.0 or hour > 20.0:
        return 0.0
    return max(0.0, math.exp(-0.5 * ((hour - 13.0) / 3.0) ** 2))


def generate_daily_profile(n_slots: int = 8) -> Dict[str, list]:
    """Generate a synthetic daily energy profile split into *n_slots* intervals."""
    if n_slots < 2:
        raise ValueError(f"n_slots must be >= 2, got {n_slots}")

    slot_hours = 24.0 / n_slots
    demands: List[float] = []
    solar_avail: List[float] = []
    time_labels: List[str] = []

    for s in range(n_slots):
        hour_start = s * slot_hours
        hour_mid = hour_start + slot_hours / 2.0

        raw = _demand_at_hour(hour_mid)
        kw = 2.0 + 8.0 * raw
        demands.append(round(kw, 2))
        solar_avail.append(round(_solar_at_hour(hour_mid), 3))

        h = int(hour_start) % 24
        m = int((hour_start - int(hour_start)) * 60)
        time_labels.append(f"{h:02d}:{m:02d}")

    return {
        "demands": demands,
        "solar_availability": solar_avail,
        "time_labels": time_labels,
    }


def generate_random_profile(
    n_slots: int = 8,
    seed: int = 42,
    min_demand: float = 2.0,
    max_demand: float = 10.0,
) -> Dict[str, list]:
    """Generate a random (non-physically-motivated) energy profile."""
    import random

    rng = random.Random(seed)
    slot_hours = 24.0 / n_slots
    demands = [round(rng.uniform(min_demand, max_demand), 2) for _ in range(n_slots)]
    solar_avail = [round(rng.uniform(0.0, 1.0), 3) for _ in range(n_slots)]
    time_labels = []
    for s in range(n_slots):
        h = int(s * slot_hours) % 24
        m = int((s * slot_hours - int(s * slot_hours)) * 60)
        time_labels.append(f"{h:02d}:{m:02d}")

    return {
        "demands": demands,
        "solar_availability": solar_avail,
        "time_labels": time_labels,
    }


# ---------------------------------------------------------------------------
# Realistic Benchmarking Scenarios
# ---------------------------------------------------------------------------

SCENARIOS: Dict[str, Dict[str, Any]] = {
    "standard": {
        "title": "☀️ Standard 24h Mixed Cycle",
        "description": "Typical commercial/residential load profile with moderate solar peak at noon.",
        "demand_multiplier": 1.0,
        "solar_multiplier": 1.0,
        "co2_weight": 0.5,
        "penalty_weight": 10.0,
        "grid_available": True,
    },
    "summer_peak": {
        "title": "🌞 Summer Cooling & Solar Surge",
        "description": "Intense air-conditioning load during midday aligned with high solar irradiance.",
        "demand_multiplier": 1.35,
        "solar_multiplier": 1.2,
        "co2_weight": 0.6,
        "penalty_weight": 12.0,
        "grid_available": True,
    },
    "winter_evening": {
        "title": "🌙 Winter Evening Heating Deficit",
        "description": "Zero daytime solar with heavy heating demand. Tests battery dispatch to prevent diesel use.",
        "demand_multiplier": 1.25,
        "solar_multiplier": 0.15,
        "co2_weight": 0.8,
        "penalty_weight": 12.0,
        "grid_available": True,
    },
    "grid_outage": {
        "title": "🚨 Grid Blackout & Microgrid Resilience",
        "description": "Utility grid is completely offline. Microgrid must self-balance on solar + battery.",
        "demand_multiplier": 0.85,
        "solar_multiplier": 1.0,
        "co2_weight": 1.0,
        "penalty_weight": 15.0,
        "grid_available": False,
    },
    "net_zero": {
        "title": "🌿 Strict Net-Zero Campus Directive",
        "description": "Extreme penalty weight placed on carbon emissions to force clean energy prioritization.",
        "demand_multiplier": 1.0,
        "solar_multiplier": 1.0,
        "co2_weight": 2.5,
        "penalty_weight": 15.0,
        "grid_available": True,
    },
}


def generate_scenario_profile(
    scenario_key: str = "standard",
    n_slots: int = 4,
) -> Dict[str, Any]:
    """Generate energy profile and configuration parameters for a preset scenario.

    Args:
        scenario_key: One of ``'standard'``, ``'summer_peak'``, ``'winter_evening'``,
                      ``'grid_outage'``, ``'net_zero'``.
        n_slots:      Number of time slots.

    Returns:
        Dict containing ``demands``, ``solar_availability``, ``time_labels``,
        and scenario metadata (``co2_weight``, ``penalty_weight``, ``grid_available``).
    """
    spec = SCENARIOS.get(scenario_key, SCENARIOS["standard"])
    base = generate_daily_profile(n_slots=n_slots)

    d_mult = spec.get("demand_multiplier", 1.0)
    s_mult = spec.get("solar_multiplier", 1.0)

    scaled_demands = [round(d * d_mult, 2) for d in base["demands"]]
    scaled_solar = [round(min(1.0, max(0.0, s * s_mult)), 3) for s in base["solar_availability"]]

    return {
        "demands": scaled_demands,
        "solar_availability": scaled_solar,
        "time_labels": base["time_labels"],
        "co2_weight": spec["co2_weight"],
        "penalty_weight": spec["penalty_weight"],
        "grid_available": spec["grid_available"],
        "title": spec["title"],
        "description": spec["description"],
    }
