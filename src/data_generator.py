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
from typing import Dict, List


def _demand_at_hour(hour: float) -> float:
    """Return a normalised demand value in [0, 1] at a fractional hour of the day.

    Uses a piecewise sinusoidal model calibrated to typical UK residential load.

    Args:
        hour: Time of day as a float in [0, 24).

    Returns:
        Demand level in [0.25, 1.0].
    """
    # Overnight trough
    if hour < 6.0:
        return 0.30 + 0.05 * math.sin(math.pi * hour / 6.0)
    # Morning ramp-up
    if hour < 9.0:
        t = (hour - 6.0) / 3.0
        return 0.30 + 0.55 * t
    # Daytime plateau with slight midday dip
    if hour < 17.0:
        return 0.80 + 0.10 * math.sin(math.pi * (hour - 9.0) / 8.0)
    # Evening peak
    if hour < 20.0:
        t = (hour - 17.0) / 3.0
        return 0.85 + 0.15 * math.sin(math.pi * t)
    # Evening decline
    t = (hour - 20.0) / 4.0
    return 1.00 - 0.70 * t


def _solar_at_hour(hour: float) -> float:
    """Return normalised solar irradiance in [0, 1] at a fractional hour.

    Follows a raised-cosine (Gaussian-like) curve centred on 12:30.

    Args:
        hour: Time of day as a float in [0, 24).

    Returns:
        Solar availability in [0, 1]; 0 outside daylight hours.
    """
    if hour < 6.0 or hour > 20.0:
        return 0.0
    # Bell centred at 13.0, spread σ ≈ 3 hours
    return max(0.0, math.exp(-0.5 * ((hour - 13.0) / 3.0) ** 2))


def generate_daily_profile(n_slots: int = 8) -> Dict[str, list]:
    """Generate a synthetic daily energy profile split into *n_slots* intervals.

    The 24-hour day is divided into *n_slots* equal windows. Each window's
    demand and solar availability are computed at its midpoint.

    Args:
        n_slots: Number of equal-width time slots.  Typical values: 4, 8, 12.
                 Must be ≥ 2.

    Returns:
        A dictionary with keys:

        - ``"demands"`` – list of float, peak demand in kW per slot.
          Scaled so that the average demand ≈ 6 kW (a typical small business).
        - ``"solar_availability"`` – list of float in [0, 1] per slot.
        - ``"time_labels"`` – list of str, e.g. ``"09:00"`` at the slot start.

    Raises:
        ValueError: If *n_slots* < 2.
    """
    if n_slots < 2:
        raise ValueError(f"n_slots must be >= 2, got {n_slots}")

    slot_hours = 24.0 / n_slots
    demands: List[float] = []
    solar_avail: List[float] = []
    time_labels: List[str] = []

    for s in range(n_slots):
        hour_start = s * slot_hours
        hour_mid = hour_start + slot_hours / 2.0

        # Demand: scale [0.30, 1.00] → realistic kW range ~[2, 10] kW
        raw = _demand_at_hour(hour_mid)
        kw = 2.0 + 8.0 * raw  # 2 kW base, up to 10 kW peak
        demands.append(round(kw, 2))

        solar_avail.append(round(_solar_at_hour(hour_mid), 3))

        # Label: HH:MM at slot start
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
    """Generate a random (non-physically-motivated) energy profile.

    Useful for stress-testing solvers with arbitrary inputs.

    Args:
        n_slots:    Number of time slots.
        seed:       Random seed for reproducibility.
        min_demand: Minimum demand per slot (kW).
        max_demand: Maximum demand per slot (kW).

    Returns:
        Same dictionary structure as :func:`generate_daily_profile`.
    """
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
