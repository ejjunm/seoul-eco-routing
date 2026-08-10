"""16. 에너지 최적 경로 탐색 (Stage 3)

15번이 만든 링크별 에너지 비용을 간선 가중치로 써서, 같은 출발–목적지에 대해
세 가지 경로를 뽑고 비교한다.

    shortest  최단거리   비용 = LENGTH
    fastest   최단시간   비용 = travel_time_sec
    eco       에너지최적 비용 = energy_ev_J        <- 우리 산출물

프로젝트의 결론 수치("최단시간 대비 에너지 N% 절감")가 여기서 나온다.

그래프
    표준노드링크의 F_NODE -> T_NODE 방향 간선으로 유향 그래프를 만든다. 같은
    노드쌍에 링크가 여럿이면 비용이 가장 낮은 것만 남긴다(단순 그래프).
    양방향 도로는 원본에 반대 방향 링크가 따로 있으므로 별도 처리하지 않는다.
    경로 탐색은 최대 강연결 컴포넌트(SCC) 안에서만 수행한다.

OD 쌍
    --od-file 로 CSV(name,olat,olon,dlat,dlon)를 주면 그대로 쓰고, 없으면
    서울 주요 지점 목록에서 조합을 만든다. 좌표는 가장 가까운 노드로 스냅한다.

출력
    data/processed/routes_{tm}.geojson   경로 3종의 LineString (EPSG:4326)
    data/processed/route_comparison_{tm}.csv   OD x 경로별 거리/시간/전력/CO2

사용
    python src/routing/16_eco_route.py --tm 202607160800
    python src/routing/16_eco_route.py --tm 202607160800 --max-pairs 30
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import linemerge

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED = PROJECT_ROOT / "data" / "processed"
INTERIM = PROJECT_ROOT / "data" / "interim"
LINK_SHP = INTERIM / "seoul_link.shp"

COSTS = {"shortest": "LENGTH", "fastest": "travel_time_sec", "eco": "energy_ev_J"}
COST_LABEL = {"shortest": "최단거리", "fastest": "최단시간", "eco": "에너지최적"}

# 서울 주요 지점 (위경도). OD 파일을 안 주면 이 목록에서 쌍을 만든다.
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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--tm", required=True, help="시각 YYYYMMDDHHMM (15번과 동일)")
    p.add_argument("--od-file", help="OD CSV 경로 (name,olat,olon,dlat,dlon)")
    p.add_argument("--random-pairs", type=int, default=0,
                   help="주요지점 대신 무작위 OD를 N쌍 뽑는다(대표성 검증용)")
    p.add_argument("--seed", type=int, default=42, help="무작위 OD 시드")
    p.add_argument("--max-pairs", type=int, default=30, help="OD 쌍 최대 개수")
    p.add_argument("--min-km", type=float, default=3.0, help="직선거리 이보다 짧은 쌍은 제외")
    p.add_argument("--max-km", type=float, default=20.0, help="직선거리 이보다 먼 쌍은 제외")
    p.add_argument("--tag", default="", help="출력 파일명 접미사 (예: random200)")
    return p.parse_args()


def sample_random_pairs(nodes: pd.DataFrame, scc: set, n: int, seed: int,
                        min_km: float, max_km: float) -> list:
    """SCC 안의 노드에서 무작위 OD 쌍을 뽑는다. 주요지점 표본의 대표성을 검증하기 위한 것."""
    rng = np.random.default_rng(seed)
    sub = nodes[nodes["NODE_ID"].isin(scc)].reset_index(drop=True)
    pairs, tries = [], 0
    while len(pairs) < n and tries < n * 60:
        tries += 1
        i, j = rng.integers(0, len(sub), 2)
        if i == j:
            continue
        o, d = sub.iloc[int(i)], sub.iloc[int(j)]
        km = np.hypot((o["lat"] - d["lat"]) * 111, (o["lon"] - d["lon"]) * 88)
        if min_km <= km <= max_km:
            pairs.append((f"rand{len(pairs):04d}", (o["lat"], o["lon"]), (d["lat"], d["lon"])))
    return pairs


def build_graph(df: pd.DataFrame) -> nx.DiGraph:
    """F_NODE -> T_NODE 유향 그래프. 중복 간선은 에너지가 낮은 쪽만 남긴다."""
    df = df.sort_values("energy_ev_J").drop_duplicates(["F_NODE", "T_NODE"], keep="first")
    G = nx.DiGraph()
    for r in df.itertuples(index=False):
        G.add_edge(r.F_NODE, r.T_NODE, LINK_ID=r.LINK_ID, LENGTH=float(r.LENGTH),
                   travel_time_sec=float(r.travel_time_sec), energy_ev_J=float(r.energy_ev_J),
                   ev_wh=float(r.ev_wh), co2_ev_g=float(r.co2_ev_g))
    return G


def node_coordinates(link_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """링크 geometry의 시작·끝점에서 노드 좌표를 만든다(WGS84)."""
    g = link_gdf.to_crs(4326)
    rows = []
    for lid, fn, tn, geom in zip(g["LINK_ID"], g["F_NODE"], g["T_NODE"], g.geometry):
        if geom is None or geom.is_empty:
            continue
        coords = list(geom.coords) if geom.geom_type == "LineString" else list(geom.geoms[0].coords)
        rows.append((fn, coords[0][0], coords[0][1]))
        rows.append((tn, coords[-1][0], coords[-1][1]))
    nodes = pd.DataFrame(rows, columns=["NODE_ID", "lon", "lat"])
    return nodes.groupby("NODE_ID", as_index=False)[["lon", "lat"]].mean()


def snap(nodes: pd.DataFrame, lat: float, lon: float, allowed: set) -> str:
    sub = nodes[nodes["NODE_ID"].isin(allowed)]
    d = (sub["lat"] - lat) ** 2 + (sub["lon"] - lon) ** 2
    return sub.iloc[int(d.values.argmin())]["NODE_ID"]


def path_metrics(G: nx.DiGraph, path: list) -> dict:
    edges = list(zip(path[:-1], path[1:]))
    a = {k: sum(G[u][v][k] for u, v in edges)
         for k in ["LENGTH", "travel_time_sec", "energy_ev_J", "ev_wh", "co2_ev_g"]}
    return {"distance_km": a["LENGTH"] / 1000, "time_min": a["travel_time_sec"] / 60,
            "energy_wh": a["ev_wh"], "co2_g": a["co2_ev_g"],
            "link_ids": [G[u][v]["LINK_ID"] for u, v in edges]}


def route_geometry(link_geom: dict, link_ids: list):
    parts = [link_geom[l] for l in link_ids if l in link_geom]
    if not parts:
        return None
    merged = linemerge(parts) if len(parts) > 1 else parts[0]
    if merged.geom_type == "MultiLineString":       # 끊긴 구간이 있으면 좌표를 이어붙인다
        coords = []
        for seg in merged.geoms:
            coords.extend(list(seg.coords))
        merged = LineString(coords)
    return merged


def main() -> None:
    args = parse_args()
    energy_path = PROCESSED / f"seoul_all_link_energy_{args.tm}.csv"
    if not energy_path.exists():
        raise SystemExit(f"15번 에너지 결과가 없습니다: {energy_path}")

    df = pd.read_csv(energy_path, dtype={"LINK_ID": str, "F_NODE": str, "T_NODE": str},
                     encoding="utf-8-sig")
    for c in ["LENGTH", "travel_time_sec", "energy_ev_J", "ev_wh", "co2_ev_g"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["F_NODE", "T_NODE", "LENGTH", "travel_time_sec", "energy_ev_J"])

    print(f"[1/4] 그래프 구성 ({len(df):,} 링크)...")
    G = build_graph(df)
    scc = max(nx.strongly_connected_components(G), key=len)
    print(f"      노드 {G.number_of_nodes():,} 간선 {G.number_of_edges():,} | "
          f"최대 강연결 컴포넌트 노드 {len(scc):,} ({len(scc)/G.number_of_nodes():.1%})")

    print("[2/4] 노드 좌표 준비...")
    link_gdf = gpd.read_file(LINK_SHP)
    link_gdf["LINK_ID"] = link_gdf["LINK_ID"].astype(str)
    link_gdf["F_NODE"] = link_gdf["F_NODE"].astype(str)
    link_gdf["T_NODE"] = link_gdf["T_NODE"].astype(str)
    nodes = node_coordinates(link_gdf)
    link_geom = dict(zip(link_gdf["LINK_ID"], link_gdf.to_crs(4326).geometry))

    # --- OD 쌍 준비 ---
    if args.od_file:
        od = pd.read_csv(args.od_file)
        pairs = [(r["name"], (r["olat"], r["olon"]), (r["dlat"], r["dlon"]))
                 for _, r in od.iterrows()]
        pairs = pairs[: args.max_pairs]
    elif args.random_pairs:
        pairs = sample_random_pairs(nodes, scc, args.random_pairs, args.seed,
                                    args.min_km, args.max_km)
    else:
        pairs = []
        for (n1, p1), (n2, p2) in itertools.combinations(SEOUL_POINTS.items(), 2):
            km = np.hypot((p1[0] - p2[0]) * 111, (p1[1] - p2[1]) * 88)
            if km >= args.min_km:
                pairs.append((f"{n1}→{n2}", p1, p2))
        pairs = pairs[: args.max_pairs]
    print(f"[3/4] 경로 탐색 ({len(pairs)}개 OD x 3경로)...")

    records, features = [], []
    for name, o, d in pairs:
        s, t = snap(nodes, o[0], o[1], scc), snap(nodes, d[0], d[1], scc)
        if s == t:
            continue
        try:
            paths = {k: nx.shortest_path(G, s, t, weight=w) for k, w in COSTS.items()}
        except nx.NetworkXNoPath:
            print(f"      [건너뜀] {name}: 경로 없음")
            continue

        for kind, path in paths.items():
            m = path_metrics(G, path)
            records.append({"od": name, "route_type": kind, "label": COST_LABEL[kind],
                            "distance_km": round(m["distance_km"], 3),
                            "time_min": round(m["time_min"], 2),
                            "energy_wh": round(m["energy_wh"], 1),
                            "co2_g": round(m["co2_g"], 1),
                            "n_links": len(m["link_ids"])})
            geom = route_geometry(link_geom, m["link_ids"])
            if geom is not None:
                features.append({
                    "type": "Feature",
                    "properties": {"od": name, "route_type": kind, "label": COST_LABEL[kind],
                                   "tm": args.tm,
                                   "distance_km": round(m["distance_km"], 3),
                                   "time_min": round(m["time_min"], 2),
                                   "energy_wh": round(m["energy_wh"], 1),
                                   "co2_g": round(m["co2_g"], 1)},
                    "geometry": json.loads(gpd.GeoSeries([geom], crs=4326).to_json())
                                     ["features"][0]["geometry"],
                })

    print("[4/4] 결과 저장...")
    suffix = f"_{args.tag}" if args.tag else ""
    comp = pd.DataFrame(records)
    comp_path = PROCESSED / f"route_comparison_{args.tm}{suffix}.csv"
    comp.to_csv(comp_path, index=False, encoding="utf-8-sig")

    geo_path = PROCESSED / f"routes_{args.tm}{suffix}.geojson"
    geo_path.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                                   ensure_ascii=False), encoding="utf-8")

    # --- 요약: 최단시간 대비 에너지최적의 절감률 ---
    piv = comp.pivot_table(index="od", columns="route_type",
                           values=["energy_wh", "time_min", "distance_km"])
    ok = piv["energy_wh"]["fastest"].notna() & piv["energy_wh"]["eco"].notna()
    piv = piv[ok]
    e_save = (1 - piv["energy_wh"]["eco"] / piv["energy_wh"]["fastest"]) * 100
    t_cost = (piv["time_min"]["eco"] / piv["time_min"]["fastest"] - 1) * 100
    d_cost = (piv["distance_km"]["eco"] / piv["distance_km"]["fastest"] - 1) * 100

    print()
    print("=" * 72)
    print(f"에너지 최적 경로 vs 최단시간 경로  ({len(piv)}개 OD, tm={args.tm})")
    print("=" * 72)
    print(f"  에너지 절감  평균 {e_save.mean():5.1f}%   중앙 {e_save.median():5.1f}%   "
          f"최대 {e_save.max():5.1f}%")
    print(f"  통행시간     평균 {t_cost.mean():+5.1f}%  중앙 {t_cost.median():+5.1f}%")
    print(f"  주행거리     평균 {d_cost.mean():+5.1f}%  중앙 {d_cost.median():+5.1f}%")
    print(f"  경로가 실제로 달라진 OD: {(e_save.abs() > 0.01).sum()}/{len(piv)}")
    print()
    print("저장:", comp_path.name, "|", geo_path.name)


if __name__ == "__main__":
    main()
