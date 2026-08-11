from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.energy.link_energy import DEFAULT_PARAMETERS, calculate_link_energy, rolling_resistance_coefficient


class LinkEnergyTests(unittest.TestCase):
    def test_flat_link_matches_pdf_formula(self):
        # 1 km, 36 km/h(=10 m/s), 평지의 손계산 가능한 기준 사례.
        frame = pd.DataFrame({"LINK_ID": ["flat"], "LENGTH": [1000.0], "speed_kmh": [36.0], "slope_pct": [0.0]})
        row = calculate_link_energy(frame).iloc[0]
        p = DEFAULT_PARAMETERS
        u = 10.0
        crr = rolling_resistance_coefficient(np.array([u]))[0]
        force = p.mass_kg * p.gravity_m_s2 * crr + 0.5 * p.air_density_kg_m3 * p.drag_coefficient * p.frontal_area_m2 * u**2
        expected_j = (force * u / p.total_efficiency + p.auxiliary_power_w) * 100.0
        self.assertAlmostEqual(row["travel_time_sec"], 100.0, places=9)
        self.assertAlmostEqual(row["energy_ev_j"], expected_j, places=6)

    def test_uphill_cost_exceeds_flat_and_downhill_keeps_auxiliary_cost(self):
        frame = pd.DataFrame({
            "LINK_ID": ["down", "flat", "up"],
            "LENGTH": [1000.0, 1000.0, 1000.0],
            "speed_kmh": [36.0, 36.0, 36.0],
            "slope_pct": [-5.0, 0.0, 5.0],
        })
        result = calculate_link_energy(frame).set_index("LINK_ID")
        self.assertGreater(result.loc["up", "energy_ev_j"], result.loc["flat", "energy_ev_j"])
        self.assertGreaterEqual(result.loc["down", "energy_ev_j"], 700.0 * result.loc["down", "travel_time_sec"])
        self.assertGreater(result.loc["down", "energy_ev_j"], 0.0)

    def test_extreme_slope_is_clipped(self):
        frame = pd.DataFrame({"LINK_ID": ["extreme"], "LENGTH": [100.0], "speed_kmh": [20.0], "slope_pct": [310.0]})
        row = calculate_link_energy(frame).iloc[0]
        self.assertEqual(row["slope_pct_used"], 12.0)
        self.assertEqual(row["slope_outlier_flag"], 1)


if __name__ == "__main__":
    unittest.main()
