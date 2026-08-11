"""시간대별 EV 링크 비용으로 경로를 탐색한다.

이 모듈은 ``historical_hybrid_link_energy`` 또는 ``link_energy``의 Parquet 한
파일을 입력으로 사용한다. 도로망은 ``F_NODE -> T_NODE`` 방향을 보존하며,
같은 노드 쌍에 여러 링크가 있는 경우에도 모두 보존한다. 따라서 시간 최적과
에너지 최적 탐색에서 서로 다른 병렬 간선을 정확히 선택할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import pandas as pd
from shapely.geometry import mapping


@dataclass(frozen=True)
class Edge:
    """그래프의 방향 링크와 경로 합산에 필요한 비용."""

    link_id: str
    from_node: str
    to_node: str
    length_m: float
    travel_time_sec: float
    energy_wh: float
    speed_kmh: float
    slope_pct: float
    tier: str
    confidence: str
    road_name: str = ""


@dataclass(frozen=True)
class Route:
    """한 비용 기준으로 계산된 경로."""

    route_type: str
    edges: tuple[Edge, ...]

    @property
    def distance_km(self) -> float:
        return sum(edge.length_m for edge in self.edges) / 1000.0

    @property
    def time_min(self) -> float:
        return sum(edge.travel_time_sec for edge in self.edges) / 60.0

    @property
    def energy_wh(self) -> float:
        return sum(edge.energy_wh for edge in self.edges)

    @property
    def link_ids(self) -> list[str]:
        return [edge.link_id for edge in self.edges]

    def summary(self) -> dict[str, float | int | str]:
        return {
            "route_type": self.route_type,
            "distance_km": round(self.distance_km, 3),
            "time_min": round(self.time_min, 2),
            "energy_wh": round(self.energy_wh, 2),
            "n_links": len(self.edges),
        }

    def guidance(self) -> list[dict[str, float | int | str]]:
        """연속된 같은 도로명을 묶어 지도용 구간 안내를 만든다.

        회전 제약·진입 방향 데이터가 없으므로 내비게이션의 회전 문구가 아니라
        현재 도로망에서 신뢰할 수 있는 도로명 기반 안내다.
        """
        groups: list[dict[str, float | int | str]] = []
        for edge in self.edges:
            road_name = edge.road_name.strip() or "도로명 미상 구간"
            if groups and groups[-1]["road_name"] == road_name:
                groups[-1]["distance_km"] = float(groups[-1]["distance_km"]) + edge.length_m / 1000.0
                groups[-1]["time_min"] = float(groups[-1]["time_min"]) + edge.travel_time_sec / 60.0
                groups[-1]["n_links"] = int(groups[-1]["n_links"]) + 1
            else:
                groups.append({"road_name": road_name, "distance_km": edge.length_m / 1000.0, "time_min": edge.travel_time_sec / 60.0, "n_links": 1})
        return [
            {**group, "distance_km": round(float(group["distance_km"]), 2), "time_min": round(float(group["time_min"]), 1)}
            for group in groups
        ]


class RouteNotFoundError(RuntimeError):
    """스냅된 두 노드 사이에 방향 경로가 없을 때 발생한다."""


class EcoRoutingEngine:
    """한 시점의 링크 비용을 메모리에 올린 방향성 에코 라우팅 엔진."""

    REQUIRED_COLUMNS = (
        "LINK_ID", "F_NODE", "T_NODE", "LENGTH", "travel_time_sec", "energy_ev_wh",
        "ROAD_NAME", "speed_kmh", "slope_pct_raw", "tier", "prediction_confidence",
    )

    def __init__(self, edges: Iterable[Edge]) -> None:
        self.adjacency: dict[str, list[Edge]] = {}
        self.edges_by_link: dict[str, Edge] = {}
        self.nodes: set[str] = set()
        for edge in edges:
            self.adjacency.setdefault(edge.from_node, []).append(edge)
            self.edges_by_link[edge.link_id] = edge
            self.nodes.add(edge.from_node)
            self.nodes.add(edge.to_node)
        if not self.edges_by_link:
            raise ValueError("라우팅 그래프에 사용할 링크가 없습니다.")
        self.node_coordinates: dict[str, tuple[float, float]] = {}
        self.geometries: dict[str, object] = {}

    @classmethod
    def from_parquet(cls, path: Path) -> "EcoRoutingEngine":
        """현재 공식 에너지 산출물 한 파일에서 그래프를 만든다."""
        frame = pd.read_parquet(path, columns=list(cls.REQUIRED_COLUMNS))
        numeric_columns = ["LENGTH", "travel_time_sec", "energy_ev_wh", "speed_kmh", "slope_pct_raw"]
        for column in numeric_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        valid = frame.dropna(subset=["LINK_ID", "F_NODE", "T_NODE", *numeric_columns])
        valid = valid[(valid["LENGTH"] > 0) & (valid["travel_time_sec"] > 0) & (valid["energy_ev_wh"] >= 0)]

        edges = (
            Edge(
                link_id=str(row.LINK_ID),
                from_node=str(row.F_NODE),
                to_node=str(row.T_NODE),
                length_m=float(row.LENGTH),
                travel_time_sec=float(row.travel_time_sec),
                energy_wh=float(row.energy_ev_wh),
                speed_kmh=float(row.speed_kmh),
                slope_pct=float(row.slope_pct_raw),
                tier=str(row.tier),
                confidence=str(row.prediction_confidence),
                road_name=str(row.ROAD_NAME) if pd.notna(row.ROAD_NAME) else "",
            )
            for row in valid.itertuples(index=False)
        )
        return cls(edges)

    def load_geometry(self, shapefile_path: Path) -> None:
        """링크 geometry와 노드 좌표를 WGS84로 불러온다.

        geometry는 지도 응답을 만들 때만 필요하므로 그래프 구축과 분리했다.
        """
        links = gpd.read_file(shapefile_path)
        links["LINK_ID"] = links["LINK_ID"].astype(str)
        links["F_NODE"] = links["F_NODE"].astype(str)
        links["T_NODE"] = links["T_NODE"].astype(str)
        links = links[links["LINK_ID"].isin(self.edges_by_link)].to_crs(4326)

        node_points: dict[str, list[tuple[float, float]]] = {}
        for row in links[["LINK_ID", "F_NODE", "T_NODE", "geometry"]].itertuples(index=False):
            geometry = row.geometry
            if geometry is None or geometry.is_empty:
                continue
            if geometry.geom_type == "MultiLineString":
                geometry = max(geometry.geoms, key=lambda segment: segment.length)
            coordinates = list(geometry.coords)
            if len(coordinates) < 2:
                continue
            self.geometries[str(row.LINK_ID)] = geometry
            node_points.setdefault(str(row.F_NODE), []).append(coordinates[0])
            node_points.setdefault(str(row.T_NODE), []).append(coordinates[-1])

        self.node_coordinates = {
            node: (
                sum(point[0] for point in points) / len(points),
                sum(point[1] for point in points) / len(points),
            )
            for node, points in node_points.items()
            if node in self.nodes
        }

    @staticmethod
    def _edge_cost(edge: Edge, weight: str) -> float:
        if weight == "time":
            return edge.travel_time_sec
        if weight == "energy":
            return edge.energy_wh
        if weight == "distance":
            return edge.length_m
        raise ValueError(f"지원하지 않는 가중치입니다: {weight}")

    def shortest_path(self, source: str, target: str, weight: str) -> Route:
        """양의 간선 비용에 대한 Dijkstra 탐색을 수행한다."""
        if source not in self.nodes or target not in self.nodes:
            raise RouteNotFoundError("출발 또는 도착 스냅 노드가 도로망에 없습니다.")

        queue: list[tuple[float, int, str]] = [(0.0, 0, source)]
        distance = {source: 0.0}
        predecessor: dict[str, tuple[str, Edge]] = {}
        counter = 0
        while queue:
            current_cost, _, node = heapq.heappop(queue)
            if current_cost != distance.get(node):
                continue
            if node == target:
                break
            for edge in self.adjacency.get(node, []):
                candidate = current_cost + self._edge_cost(edge, weight)
                if candidate < distance.get(edge.to_node, float("inf")):
                    distance[edge.to_node] = candidate
                    predecessor[edge.to_node] = (node, edge)
                    counter += 1
                    heapq.heappush(queue, (candidate, counter, edge.to_node))

        if target not in predecessor and source != target:
            raise RouteNotFoundError("선택한 출발지와 도착지 사이에 방향 경로가 없습니다.")
        return Route(route_type=weight, edges=tuple(self._reconstruct(source, target, predecessor)))

    @staticmethod
    def _reconstruct(source: str, target: str, predecessor: dict[str, tuple[str, Edge]]) -> list[Edge]:
        path: list[Edge] = []
        node = target
        while node != source:
            previous, edge = predecessor[node]
            path.append(edge)
            node = previous
        path.reverse()
        return path

    def snap(self, longitude: float, latitude: float) -> str:
        """현재는 가장 가까운 그래프 노드에 스냅한다.

        다음 단계에서 링크 스냅과 가상 연결 간선으로 확장할 수 있도록 분리했다.
        """
        if not self.node_coordinates:
            raise RuntimeError("스냅하려면 먼저 load_geometry()를 호출해야 합니다.")
        return min(
            self.node_coordinates,
            key=lambda node: self._haversine_m(
                longitude, latitude, self.node_coordinates[node][0], self.node_coordinates[node][1]
            ),
        )

    @staticmethod
    def _haversine_m(lon_a: float, lat_a: float, lon_b: float, lat_b: float) -> float:
        radius_m = 6_371_000.0
        lat_delta = radians(lat_b - lat_a)
        lon_delta = radians(lon_b - lon_a)
        a = sin(lat_delta / 2) ** 2 + cos(radians(lat_a)) * cos(radians(lat_b)) * sin(lon_delta / 2) ** 2
        return 2 * radius_m * asin(sqrt(a))

    def compare(self, source: str, target: str) -> dict[str, Route]:
        """최단시간·최소에너지·최단거리 경로를 함께 반환한다."""
        return {
            "fastest": self.shortest_path(source, target, "time"),
            "eco": self.shortest_path(source, target, "energy"),
            "shortest": self.shortest_path(source, target, "distance"),
        }

    def energy_route_with_time_limit(
        self,
        source: str,
        target: str,
        max_time_sec: float,
        max_labels_per_node: int = 20,
    ) -> Route:
        """시간 상한 안에서 에너지가 가장 작은 경로를 찾는다.

        한 노드에 도착하는 ``(시간, 에너지)`` 조합 중 다른 조합보다 둘 다 나쁜
        라벨은 버리는 다목적 label-setting 탐색이다. 일반적인 가중합 경로보다
        "최단시간보다 최대 N% 늦게"라는 제품 요구를 직접 만족시킨다.
        """
        if max_time_sec <= 0:
            raise ValueError("허용 통행시간은 0보다 커야 합니다.")
        if source not in self.nodes or target not in self.nodes:
            raise RouteNotFoundError("출발 또는 도착 스냅 노드가 도로망에 없습니다.")

        # (노드, 누적시간, 누적에너지, 이전 라벨 ID, 이전 간선, 활성 여부)
        labels: list[list[object]] = [[source, 0.0, 0.0, None, None, True]]
        active_labels: dict[str, list[int]] = {source: [0]}
        queue: list[tuple[float, float, int, int]] = [(0.0, 0.0, 0, 0)]
        counter = 0

        while queue:
            energy, elapsed, _, label_id = heapq.heappop(queue)
            node, stored_time, stored_energy, _, _, active = labels[label_id]
            if not active or energy != stored_energy or elapsed != stored_time:
                continue
            if node == target:
                return Route("balanced", tuple(self._reconstruct_label_path(labels, label_id)))

            for edge in self.adjacency.get(str(node), []):
                next_time = float(stored_time) + edge.travel_time_sec
                if next_time > max_time_sec:
                    continue
                next_energy = float(stored_energy) + edge.energy_wh
                node_labels = active_labels.setdefault(edge.to_node, [])

                # 기존 라벨이 시간·에너지 모두 더 좋으면 후보를 버린다.
                if any(
                    float(labels[existing][1]) <= next_time and float(labels[existing][2]) <= next_energy
                    for existing in node_labels
                    if bool(labels[existing][5])
                ):
                    continue

                # 후보보다 두 비용 모두 나쁜 기존 라벨은 더 이상 필요 없다.
                survivors = []
                for existing in node_labels:
                    if float(labels[existing][1]) >= next_time and float(labels[existing][2]) >= next_energy:
                        labels[existing][5] = False
                    elif bool(labels[existing][5]):
                        survivors.append(existing)
                node_labels[:] = survivors

                label_id_next = len(labels)
                labels.append([edge.to_node, next_time, next_energy, label_id, edge, True])
                node_labels.append(label_id_next)

                # 비정상적으로 많은 Pareto 라벨이 생기는 경우 탐색을 제한한다.
                if len(node_labels) > max_labels_per_node:
                    node_labels.sort(key=lambda item: (float(labels[item][2]), float(labels[item][1])))
                    for discarded in node_labels[max_labels_per_node:]:
                        labels[discarded][5] = False
                    del node_labels[max_labels_per_node:]

                counter += 1
                heapq.heappush(queue, (next_energy, next_time, counter, label_id_next))

        raise RouteNotFoundError("허용 시간 안에 도착 가능한 에너지 경로가 없습니다.")

    @staticmethod
    def _reconstruct_label_path(labels: list[list[object]], label_id: int) -> list[Edge]:
        path: list[Edge] = []
        current: int | None = label_id
        while current is not None:
            previous = labels[current][3]
            edge = labels[current][4]
            if edge is not None:
                path.append(edge)  # type: ignore[arg-type]
            current = previous if isinstance(previous, int) else None
        path.reverse()
        return path

    def compare_with_balanced(self, source: str, target: str, max_time_increase_pct: float = 15.0) -> dict[str, Route]:
        """최단시간 대비 허용 지연률을 만족하는 균형 에코 경로를 더한다."""
        if max_time_increase_pct < 0:
            raise ValueError("허용 시간 증가율은 0 이상이어야 합니다.")
        routes = self.compare(source, target)
        time_limit = routes["fastest"].time_min * 60 * (1 + max_time_increase_pct / 100)
        try:
            routes["balanced"] = self.energy_route_with_time_limit(source, target, time_limit)
        except RouteNotFoundError:
            # 최단시간 경로는 상한을 만족하므로 이 분기는 데이터 이상 방어용이다.
            routes["balanced"] = Route("balanced", routes["fastest"].edges)
        return routes

    def routes_geojson(self, routes: Iterable[Route]) -> dict:
        """경로별 링크 geometry를 지도용 GeoJSON FeatureCollection으로 반환한다."""
        features = []
        for route in routes:
            geometries = [self.geometries[edge.link_id] for edge in route.edges if edge.link_id in self.geometries]
            if not geometries:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": route.summary(),
                    "geometry": {
                        "type": "MultiLineString",
                        "coordinates": [mapping(geometry)["coordinates"] for geometry in geometries],
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}
