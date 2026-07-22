"""
Stage2 (CMEM 에너지) + Stage3 (경로최적화) 프로토타입.

파이프라인:
  Stage1 산출(링크별 속도) + DEM 경사 + 링크 길이
    -> Stage2: 링크별 '통과 에너지' 계산 (거리기반 도로하중 모델)
    -> Stage3: 도로 그래프(F_NODE->T_NODE)에서 에너지최소 / 시간최소 / 거리최소 경로 비교

에너지 모델 (거리기반, 내연 승용차 도로하중 — 순간파워형 아님):
  E[J] = L * ( a/v + b + c*v^2 + d*max(0,sinθ) )
    a = 공회전+보조장치 전력 / 효율            (시간에 비례 -> 거리로는 /v)
    b = 구름저항  m*g*Cr / 효율
    c = 공기저항  0.5*ρ*Cd*A / 효율
    d = 중력경사  m*g / 효율                    (내리막 회생 없음: ICE 가정)
  * v는 m/s. 팀 초안의 순간파워형 Y=L*(a+bv+cv^3+dv*sinθ)은 링크길이 곱 시 v배 과대 -> 거리기반형 사용.

속도 소스:
  - 매칭 링크(25,151): T-data 관측 일평균 속도
  - 미매칭 링크(38,397): ROAD_RANK 평균으로 대체(fallback) — 서울 전역 그래프 확보용

사용:  python experiments/eco_routing.py [--pairs N] [--hour H]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = PROJECT_ROOT / "data" / "processed"
ATTR_PATH = PROCESSED / "seoul_link_attr.csv"
DEM_PATH = PROCESSED / "seoul_link_dem_features.csv"
CACHE_PATH = PROCESSED / "speed_model_cache.parquet"   # Stage1 harness가 만든 캐시(관측 속도 포함)
OUT_ROUTES = PROJECT_ROOT / "experiments" / "eco_routes.csv"

# 대표 승용차(내연) 도로하중 계수 — 물리 기반, 팀 논의로 조정 가능
VEH = dict(
    m=1500.0,       # 총질량 kg (공차+승객)
    g=9.81,
    Cr=0.011,       # 구름저항계수
    rho=1.225,      # 공기밀도 kg/m^3
    Cd=0.30,        # 항력계수
    A=2.2,          # 전면투영면적 m^2
    P_idle=3000.0,  # 공회전+보조장치 전력 W
    eta=0.30,       # tank-to-wheel 효율(내연)
)
FUEL_MJ_PER_L = 34.2      # 가솔린 에너지밀도 MJ/L
CO2_G_PER_L = 2310.0      # 가솔린 연소 CO2 g/L
V_FLOOR_KMH = 3.0         # 속도 하한(정체/결측 보호)


def link_energy_J(L_m, v_kmh, slope_pct, veh=VEH):
    """링크 통과 에너지(J). L_m[m], v_kmh[km/h], slope_pct[%]."""
    v = np.maximum(v_kmh, V_FLOOR_KMH) / 3.6                 # m/s
    tan = slope_pct / 100.0
    sin_pos = np.maximum(tan / np.sqrt(1 + tan * tan), 0.0)  # 오르막만(내리막 회생 없음)
    F_roll = veh["m"] * veh["g"] * veh["Cr"]
    F_aero = 0.5 * veh["rho"] * veh["Cd"] * veh["A"] * v * v
    F_grade = veh["m"] * veh["g"] * sin_pos
    E_tractive = L_m * (F_roll + F_aero + F_grade) / veh["eta"]
    E_idle = veh["P_idle"] * (L_m / v)                       # 공회전 시간에너지
    return E_tractive + E_idle


def build_link_table():
    """LINK_ID, F_NODE, T_NODE, LENGTH, ROAD_RANK, MAX_SPD, slope_pct, v_kmh, speed_source."""
    attr = pd.read_csv(ATTR_PATH, dtype={"LINK_ID": str, "F_NODE": str, "T_NODE": str},
                       usecols=["LINK_ID", "F_NODE", "T_NODE", "LENGTH", "ROAD_RANK", "MAX_SPD"])
    dem = pd.read_csv(DEM_PATH, dtype={"LINK_ID": str}, usecols=["LINK_ID", "slope_pct"])

    # 관측 속도: Stage1 캐시(매칭 링크)에서 링크별 일평균
    cache = pd.read_parquet(CACHE_PATH, columns=["LINK_ID", "평균속도"])
    v_obs = cache.groupby("LINK_ID")["평균속도"].mean().rename("v_obs")

    df = attr.merge(dem, on="LINK_ID", how="left").merge(v_obs, on="LINK_ID", how="left")
    df["slope_pct"] = df["slope_pct"].fillna(0.0)

    # 미매칭 링크 속도 = ROAD_RANK 평균(관측 기반) -> 전역 평균 fallback
    rank_mean = df.groupby("ROAD_RANK")["v_obs"].transform("mean")
    gmean = df["v_obs"].mean()
    df["v_kmh"] = df["v_obs"].fillna(rank_mean).fillna(gmean)
    df["v_kmh"] = np.minimum(df["v_kmh"], df["MAX_SPD"].clip(lower=V_FLOOR_KMH))  # 제한속도 상한
    df["speed_source"] = np.where(df["v_obs"].notna(), "observed", "rank_fallback")

    # Stage2: 링크별 에너지/시간
    df["time_s"] = df["LENGTH"] / (df["v_kmh"] / 3.6)
    df["energy_J"] = link_energy_J(df["LENGTH"].values, df["v_kmh"].values, df["slope_pct"].values)
    return df


def build_graph(df):
    G = nx.DiGraph()
    for r in df.itertuples(index=False):
        G.add_edge(r.F_NODE, r.T_NODE, length=r.LENGTH, time=r.time_s, energy=r.energy_J,
                   link_id=r.LINK_ID, v=r.v_kmh, slope=r.slope_pct)
    return G


def path_totals(G, path):
    d = t = e = 0.0
    for u, w in zip(path[:-1], path[1:]):
        ed = G[u][w]
        d += ed["length"]; t += ed["time"]; e += ed["energy"]
    return dict(dist_km=d / 1000, time_min=t / 60, energy_MJ=e / 1e6,
                fuel_L=e / 1e6 / FUEL_MJ_PER_L, co2_g=e / 1e6 / FUEL_MJ_PER_L * CO2_G_PER_L, n_links=len(path) - 1)


def route(G, s, t):
    """세 목적함수로 각각 최적경로 산출."""
    out = {}
    for key, w in [("shortest", "length"), ("fastest", "time"), ("eco", "energy")]:
        p = nx.shortest_path(G, s, t, weight=w)
        out[key] = path_totals(G, p)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=6)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print("[1/3] 링크 테이블 구성 중...")
    df = build_link_table()
    n_obs = (df["speed_source"] == "observed").sum()
    print(f"  링크 {len(df):,} | 관측속도 {n_obs:,} / fallback {len(df)-n_obs:,}"
          f" | 평균속도 {df['v_kmh'].mean():.1f}km/h | 평균경사 {df['slope_pct'].abs().mean():.2f}%")

    print("[2/3] 도로 그래프 구성 중...")
    G = build_graph(df)
    scc = max(nx.strongly_connected_components(G), key=len)
    print(f"  노드 {G.number_of_nodes():,} | 엣지 {G.number_of_edges():,} | 최대 강연결성분 노드 {len(scc):,}")

    print(f"[3/3] OD {args.pairs}쌍 경로 비교 (에너지 vs 시간 vs 거리)...\n")
    scc = sorted(scc)  # 결정적
    rng = np.random.default_rng(args.seed)
    rows, done = [], 0
    while done < args.pairs and len(scc) > 1:
        s, t = scc[rng.integers(len(scc))], scc[rng.integers(len(scc))]
        if s == t or not nx.has_path(G, s, t):
            continue
        r = route(G, s, t)
        eco, fast = r["eco"], r["fastest"]
        e_save = (fast["energy_MJ"] - eco["energy_MJ"]) / fast["energy_MJ"] * 100  # 에코가 최속 대비 에너지 절감%
        t_pen = (eco["time_min"] - fast["time_min"]) / fast["time_min"] * 100      # 그 대가인 시간 증가%
        print(f"  OD{done+1}: 최속경로 {fast['energy_MJ']:.1f}MJ/{fast['time_min']:.1f}분 "
              f"vs 에코경로 {eco['energy_MJ']:.1f}MJ/{eco['time_min']:.1f}분 "
              f"→ 에너지 {e_save:+.1f}% (시간 {t_pen:+.1f}%)")
        for k, v in r.items():
            rows.append(dict(od=f"OD{done+1}", route=k, **{kk: round(vv, 3) for kk, vv in v.items()}))
        done += 1

    res = pd.DataFrame(rows)
    OUT_ROUTES.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT_ROUTES, index=False)

    # 요약: 에코 vs 최속 평균 절감
    piv = res.pivot_table(index="od", columns="route", values=["energy_MJ", "time_min", "dist_km"])
    eco_save = ((piv[("energy_MJ", "fastest")] - piv[("energy_MJ", "eco")]) / piv[("energy_MJ", "fastest")] * 100)
    time_pen = ((piv[("time_min", "eco")] - piv[("time_min", "fastest")]) / piv[("time_min", "fastest")] * 100)
    print(f"\n=== 요약 (에코경로 vs 최속경로, OD {done}쌍 평균) ===")
    print(f"  에너지 절감: {eco_save.mean():+.1f}%  |  시간 증가: {time_pen.mean():+.1f}%")
    print(f"  경로 상세 저장: {OUT_ROUTES}")


if __name__ == "__main__":
    main()
