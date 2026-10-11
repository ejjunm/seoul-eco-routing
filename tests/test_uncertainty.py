import importlib.util
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


speed_uncertainty = load_module("speed_uncertainty", "src/models/05_build_speed_uncertainty.py")
route_uncertainty = load_module("route_uncertainty", "src/transit/12_route_carbon_uncertainty.py")


class ConformalTests(unittest.TestCase):
    def test_finite_sample_quantile_is_conservative(self):
        scores = np.arange(1.0, 11.0)
        # ceil((10+1)*0.9)/10 = 1.0, so the finite-sample correction takes the maximum.
        self.assertEqual(speed_uncertainty.conformal_quantile(scores, 0.1), 10.0)

    def test_conformal_expands_and_orders_interval(self):
        raw = np.array([[1.0, 5.0, 8.0], [4.0, 6.0, 9.0]])
        calibrated = speed_uncertainty.apply_conformal(
            raw, np.array([True, False]),
            {"B_neighbor_model": 2.0, "C_static_model": 1.0},
        )
        self.assertTrue(np.all(calibrated[:, 0] <= calibrated[:, 1]))
        self.assertTrue(np.all(calibrated[:, 1] <= calibrated[:, 2]))
        self.assertEqual(calibrated[0, 0], 3.0)  # physical minimum speed clip
        self.assertEqual(calibrated[0, 2], 10.0)

    def test_class_endpoints_follow_dependence_side(self):
        high = np.array([True, True, False, False])
        efficient = np.array([True, False, True, False])
        np.testing.assert_array_equal(route_uncertainty.class_for(high, efficient), [1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
