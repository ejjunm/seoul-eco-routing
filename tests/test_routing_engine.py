import unittest

from src.routing.engine import EcoRoutingEngine, Edge


def edge(link_id: str, start: str, end: str, length: float, time: float, energy: float) -> Edge:
    return Edge(link_id, start, end, length, time, energy, 30.0, 0.0, "A_lookup", "high")


class EcoRoutingEngineTests(unittest.TestCase):
    def test_parallel_links_keep_cost_specific_choice(self) -> None:
        engine = EcoRoutingEngine(
            [
                edge("slow_low_energy", "A", "B", 1000, 120, 50),
                edge("fast_high_energy", "A", "B", 1000, 60, 90),
                edge("finish", "B", "C", 1000, 60, 50),
            ]
        )

        fastest = engine.shortest_path("A", "C", "time")
        eco = engine.shortest_path("A", "C", "energy")

        self.assertEqual(fastest.link_ids, ["fast_high_energy", "finish"])
        self.assertEqual(eco.link_ids, ["slow_low_energy", "finish"])

    def test_route_metrics_are_link_sums(self) -> None:
        engine = EcoRoutingEngine([edge("ab", "A", "B", 1500, 90, 80), edge("bc", "B", "C", 500, 30, 20)])
        route = engine.shortest_path("A", "C", "energy")

        self.assertEqual(route.distance_km, 2.0)
        self.assertEqual(route.time_min, 2.0)
        self.assertEqual(route.energy_wh, 100.0)

    def test_balanced_route_respects_time_limit(self) -> None:
        engine = EcoRoutingEngine(
            [
                edge("fast_ab", "A", "B", 1000, 60, 100),
                edge("fast_bc", "B", "D", 1000, 60, 100),
                edge("balanced_ac", "A", "C", 1000, 70, 65),
                edge("balanced_cd", "C", "D", 1000, 60, 65),
                edge("slow_ae", "A", "E", 1000, 100, 20),
                edge("slow_ed", "E", "D", 1000, 100, 20),
            ]
        )

        route = engine.energy_route_with_time_limit("A", "D", max_time_sec=140)

        self.assertEqual(route.link_ids, ["balanced_ac", "balanced_cd"])
        self.assertLessEqual(route.time_min * 60, 140)
