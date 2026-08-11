"""
[역할]
15번 스크립트(전체 링크 에너지 In-Memory DataFrame)의 결과를 바탕으로,
MOCT_LINK 도로망 유향 그래프(NetworkX) 상에서 출발지(OD) 간 3가지 경로를 메모리 상에서 탐색 및 비교합니다.
1) 최단거리 경로 (Shortest)
2) 최단시간 경로 (Fastest)
3) 에너지 최적 경로 (Eco)

[주요 기능]
- 다익스트라(Dijkstra) 기반 다중 가중치 최적 경로 탐색
- SEOUL_POINTS 사전 정의 및 좌표 기반 가까운 노드 스내핑(snap_node) 지원
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import linemerge

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INTERIM_DIR = PROJECT_ROOT / "data" / "interim"
LINK_SHP = INTERIM_DIR / "seoul_link.shp"

COSTS = {"shortest": "LENGTH", "fastest": "travel_time_sec", "eco": "energy_ev_J"}
COST_LABEL = {"shortest": "최단거리", "fastest": "최단시간", "eco": "에너지최적"}

# 서울 주요 지점 위경도 좌표 사전 (웹 UI 내 OD 선택 및 테스트용)
SEOUL_POINTS = {
    "강남역": (37.4979, 127.0276),
    "서울시청": (37.5665, 126.9780),
    "여의도": (37.5219, 126.9245),
    "잠실역": (37.5133, 127.1000),
    "홍대입구": (37.5572, 126.9245),
    "청량리": (37.5800, 127.0470),
    "구로디지털단지": (37.4853, 126.9016),
    "서울대입구": (37.4813, 126.9527),
    "북한산우이": (37.6630, 127.0130),   # 북부 구릉지 — 경사 효과 확인용
    "사당": (37.4765, 126.9816),
}


def build_graph(df: pd.DataFrame) -> nx.DiGraph:
    """F_NODE -> T_NODE 유향 그래프 구축 (중복 간선 발생 시 에너지 소비가 적은 쪽 선택)"""
    df_sorted = df.sort_values("energy_ev_J").drop_duplicates(["F_NODE", "T_NODE"], keep="first")
    G = nx.DiGraph()
    for r in df_sorted.itertuples(index=False):
        G.add_edge(
            str(r.F_NODE), str(r.T_NODE),
            LINK_ID=str(r.LINK_ID),
            LENGTH=float(r.LENGTH),
            travel_time_sec=float(r.travel_time_sec),
            energy_ev_J=float(r.energy_ev_J),
            ev_wh=float(getattr(r, "ev_wh", r.energy_ev_J / 3600.0)),
            co2_ev_g=float(getattr(r, "co2_ev_g", 0.0))
        )
    return G


def prepare_spatial_cache(link_shp_path: Path | str = LINK_SHP) -> tuple[gpd.GeoDataFrame, pd.DataFrame, dict]:
    """
    [웹 앱 서버 초기화 시 1회 호출용 캐시 함수]
    Shapefile을 읽어 WGS84(EPSG:4326)로 변환하고 노드 좌표표와 지오메트리 딕셔너리를 미리 구성합니다.
    maps.py 구동 시 1회 실행해 두면 이후 탐색 속도가 0.05초 수준으로 극대화됩니다.
    """
    link_gdf = gpd.read_file(link_shp_path).to_crs(epsg=4326)
    link_gdf["LINK_ID"] = link_gdf["LINK_ID"].astype(str)
    link_gdf["F_NODE"] = link_gdf["F_NODE"].astype(str)
    link_gdf["T_NODE"] = link_gdf["T_NODE"].astype(str)

    # 노드 중심 좌표 추출
    rows = []
    for fn, tn, geom in zip(link_gdf["F_NODE"], link_gdf["T_NODE"], link_gdf.geometry):
        if geom is None or geom.is_empty:
            continue
        coords = list(geom.coords) if geom.geom_type == "LineString" else list(geom.geoms[0].coords)
        rows.append((str(fn), coords[0][0], coords[0][1]))
        rows.append((str(tn), coords[-1][0], coords[-1][1]))
    
    nodes_df = pd.DataFrame(rows, columns=["NODE_ID", "lon", "lat"]).groupby("NODE_ID", as_index=False)[["lon", "lat"]].mean()
    link_geom_dict = dict(zip(link_gdf["LINK_ID"], link_gdf.geometry))

    return link_gdf, nodes_df, link_geom_dict


def snap_node(nodes: pd.DataFrame, lat: float, lon: float, allowed_nodes: set) -> str:
    """위경도 좌표에서 가장 가까운 그래프 노드 ID 탐색"""
    sub = nodes[nodes["NODE_ID"].isin(allowed_nodes)]
    d = (sub["lat"] - lat) ** 2 + (sub["lon"] - lon) ** 2
    return sub.iloc[int(d.values.argmin())]["NODE_ID"]


def route_geometry(link_geom_dict: dict, link_ids: list):
    """링크 ID 리스트를 단일 merged LineString으로 합성"""
    parts = [link_geom_dict[l] for l in link_ids if l in link_geom_dict]
    if not parts:
        return None
    merged = linemerge(parts) if len(parts) > 1 else parts[0]
    if merged.geom_type == "MultiLineString":
        coords = []
        for seg in merged.geoms:
            coords.extend(list(seg.coords))
        merged = LineString(coords)
    return merged


def find_routes_dataframe(
    energy_df: pd.DataFrame,
    start_latlon: tuple[float, float],
    end_latlon: tuple[float, float],
    link_gdf: gpd.GeoDataFrame | None = None,
    nodes_df: pd.DataFrame | None = None,
    link_geom_dict: dict | None = None
) -> tuple[dict, pd.DataFrame]:
    """
    [웹/모듈 전용 인메모리 핵심 라우팅 함수]
    15번 에너지 DataFrame과 출발/목적지 위경도 좌표를 받아
    파일 입출력 없이 메모리 상에서 0.1초 내로 시각화용 GeoJSON 및 요약 DataFrame을 반환합니다.
    """
    # 1. 그래프 구축 및 최대 강연결 컴포넌트(SCC) 추출
    G = build_graph(energy_df)
    scc = max(nx.strongly_connected_components(G), key=len)

    # 2. 캐시 객체가 미전달 시 온디맨드 로드 (Fallback)
    if nodes_df is None or link_geom_dict is None:
        if link_gdf is None:
            if not Path(LINK_SHP).exists():
                raise FileNotFoundError(f"지오메트리 템플릿 파일이 존재하지 않습니다: {LINK_SHP}")
            link_gdf = gpd.read_file(LINK_SHP)
        link_gdf, nodes_df, link_geom_dict = prepare_spatial_cache(LINK_SHP)

    # 3. OD 위경도 -> 가장 가까운 그래프 노드 스내핑
    s_node = snap_node(nodes_df, start_latlon[0], start_latlon[1], scc)
    t_node = snap_node(nodes_df, end_latlon[0], end_latlon[1], scc)

    if s_node == t_node:
        raise ValueError("출발지와 목적지가 동일한 노드로 매핑되었습니다. 위치를 조정해 주세요.")

    features = []
    records = []

    # 4. 3가지 조건 다익스트라 경로 탐색
    for kind, weight_col in COSTS.items():
        try:
            path = nx.shortest_path(G, s_node, t_node, weight=weight_col)
            edges = list(zip(path[:-1], path[1:]))

            dist_m = sum(G[u][v]["LENGTH"] for u, v in edges)
            time_sec = sum(G[u][v]["travel_time_sec"] for u, v in edges)
            energy_j = sum(G[u][v]["energy_ev_J"] for u, v in edges)
            ev_wh = sum(G[u][v]["ev_wh"] for u, v in edges)
            co2_g = sum(G[u][v]["co2_ev_g"] for u, v in edges)
            link_ids = [G[u][v]["LINK_ID"] for u, v in edges]

            rec = {
                "route_type": kind,
                "label": COST_LABEL[kind],
                "distance_km": round(dist_m / 1000.0, 3),
                "time_min": round(time_sec / 60.0, 2),
                "energy_wh": round(ev_wh, 1),
                "co2_g": round(co2_g, 1),
                "n_links": len(link_ids)
            }
            records.append(rec)

            geom = route_geometry(link_geom_dict, link_ids)
            if geom is not None:
                features.append({
                    "type": "Feature",
                    "properties": rec,
                    "geometry": json.loads(gpd.GeoSeries([geom], crs=4326).to_json())["features"][0]["geometry"]
                })
        except nx.NetworkXNoPath:
            continue

    comp_df = pd.DataFrame(records)

    # 5. 에너지 절감률 산출 (Fastest 대비 Eco)
    if "fastest" in comp_df["route_type"].values and "eco" in comp_df["route_type"].values:
        fast_wh = comp_df.loc[comp_df["route_type"] == "fastest", "energy_wh"].values[0]
        eco_wh = comp_df.loc[comp_df["route_type"] == "eco", "energy_wh"].values[0]
        if fast_wh > 0:
            saving_pct = round(((fast_wh - eco_wh) / fast_wh) * 100.0, 1)
            comp_df["energy_saving_pct"] = np.where(comp_df["route_type"] == "eco", saving_pct, 0.0)

    geojson_data = {
        "type": "FeatureCollection",
        "features": features
    }

    return geojson_data, comp_df