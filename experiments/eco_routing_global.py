"""
전역 에코라우팅 — 서울 전 도로(100% 속도 완비)에서 에너지 최소 경로.

experiments/eco_routing.py는 센서 없는 도로를 '도로등급 평균'으로 대충 메웠다.
이 버전은 fill_all_speeds.py가 만든 all_link_speeds.csv(구조피처 예측으로 채운
시간대별 속도)를 써서, 특정 시간대(--hour)·요일(--weekend) 기준으로 라우팅한다.

사용:  python experiments/eco_routing_global.py --hour 8 --pairs 6      # 출근 8시
       python experiments/eco_routing_global.py --hour 3 --pairs 6      # 새벽 3시
"""
from __future__ import annotations

import argparse
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = PROJECT_ROOT / "data" / "processed"

# 에너지 계수 (eco_routing.py와 동일: 대표 승용차 도로하중)
VEH = dict(m=1500.0, g=9.81, Cr=0.011, rho=1.225, Cd=0.30, A=2.2, P_idle=3000.0, eta=0.30)
FUEL_MJ_PER_L = 34.2
V_FLOOR_KMH = 3.0


def link_energy_J(L_m, v_kmh, slope_pct, veh=VEH):
    v = np.maximum(v_kmh, V_FLOOR_KMH) / 3.6
    tan = slope_pct / 100.0
    sin_pos = np.maximum(tan / np.sqrt(1 + tan * tan), 0.0)
    F = veh["m"] * veh["g"] * veh["Cr"] + 0.5 * veh["rho"] * veh["Cd"] * veh["A"] * v * v + veh["m"] * veh["g"] * sin_pos
    return L_m * F / veh["eta"] + veh["P_idle"] * (L_m / v)


def build_link_table(hour: int, weekend: bool):
    attr = pd.read_csv(PROCESSED / "seoul_link_attr.csv", dtype={"LINK_ID": str, "F_NODE": str, "T_NODE": str},
                       usecols=["LINK_ID", "F_NODE", "T_NODE", "LENGTH"])
    attr["LENGTH"] = pd.to_numeric(attr["LENGTH"], errors="coerce")
    dem = pd.read_csv(PROCESSED / "seoul_link_dem_features.csv", dtype={"LINK_ID": str}, usecols=["LINK_ID", "slope_pct"])

    sp = pd.read_csv(PROCESSED / "all_link_speeds.csv", dtype={"LINK_ID": str, "dow_group": str})
    dg = "02" if weekend else "01"
    sp = sp[(sp["시간코드"] == hour) & (sp["dow_group"] == dg)][["LINK_ID", "v_kmh", "source"]]

    df = attr.merge(dem, on="LINK_ID", how="left").merge(sp, on="LINK_ID", how="left")
    df["slope_pct"] = df["slope_pct"].fillna(0.0)
    df["v_kmh"] = df["v_kmh"].fillna(df["v_kmh"].median())
    df["source"] = df["source"].fillna("median")
    df["time_s"] = df["LENGTH"] / (df["v_kmh"] / 3.6)
    df["energy_J"] = link_energy_J(df["LENGTH"].values, df["v_kmh"].values, df["slope_pct"].values)
    return df


def build_graph(df):
    G = nx.DiGraph()
    for r in df.itertuples(index=False):
        G.add_edge(r.F_NODE, r.T_NODE, length=r.LENGTH, time=r.time_s, energy=r.energy_J)
    return G


def path_tot(G, p):
    d = t = e = 0.0
    for u, w in zip(p[:-1], p[1:]):
        ed = G[u][w]; d += ed["length"]; t += ed["time"]; e += ed["energy"]
    return dict(dist_km=d / 1000, time_min=t / 60, energy_MJ=e / 1e6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hour", type=int, default=8, help="시간코드 1~24")
    ap.add_argument("--weekend", action="store_true")
    ap.add_argument("--pairs", type=int, default=6)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print(f"[1/3] 링크 속도 테이블 ({args.hour}시, {'주말' if args.weekend else '주중'})...")
    df = build_link_table(args.hour, args.weekend)
    src = df["source"].value_counts()
    print(f"  링크 {len(df):,} | 속도출처 {src.to_dict()} | 평균 {df['v_kmh'].mean():.1f}km/h")

    print("[2/3] 그래프 구성...")
    G = build_graph(df)
    scc = sorted(max(nx.strongly_connected_components(G), key=len))
    print(f"  노드 {G.number_of_nodes():,} | 엣지 {G.number_of_edges():,} | 최대 강연결 {len(scc):,}")

    print(f"[3/3] OD {args.pairs}쌍 에너지 vs 최속 경로 비교...\n")
    rng = np.random.default_rng(args.seed)
    saves, pens, done = [], [], 0
    while done < args.pairs:
        s, t = scc[rng.integers(len(scc))], scc[rng.integers(len(scc))]
        if s == t or not nx.has_path(G, s, t):
            continue
        fast = path_tot(G, nx.shortest_path(G, s, t, weight="time"))
        eco = path_tot(G, nx.shortest_path(G, s, t, weight="energy"))
        es = (fast["energy_MJ"] - eco["energy_MJ"]) / fast["energy_MJ"] * 100
        tp = (eco["time_min"] - fast["time_min"]) / fast["time_min"] * 100
        saves.append(es); pens.append(tp); done += 1
        print(f"  OD{done}: 최속 {fast['energy_MJ']:.1f}MJ/{fast['time_min']:.0f}분 vs "
              f"에코 {eco['energy_MJ']:.1f}MJ/{eco['time_min']:.0f}분 → 에너지 {es:+.1f}% (시간 {tp:+.1f}%)")

    print(f"\n=== 요약 ({args.hour}시 · OD {done}쌍) ===")
    print(f"  에너지 절감 평균 {np.mean(saves):+.1f}% | 시간 증가 평균 {np.mean(pens):+.1f}%")


if __name__ == "__main__":
    main()
