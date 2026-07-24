"""
센서 없는 도로(일 B) 예측용 '구조 피처' 생성.

이력이 없는 링크는 자기 과거를 못 쓰므로, '이 도로가 구조적으로 어떤 도로인가'를
도로망 자체에서 뽑아 대신 쓴다. 라벨(속도)을 전혀 안 쓰므로 누수가 없고, 63,548 링크 100% 커버.

만드는 피처 (LINK_ID 단위):
  [코리도 규모]  rn_links, rn_len, rn_lanes, rn_maxspd   — ROAD_NAME(도로명)별 집계
  [노드 좌표]    x, y, dist_cbd                          — F/T 노드 중점, 시청 기준 거리
  [노드 위상]    nodetype_f, nodetype_t, turnp_f, turnp_t, deg_f, deg_t, deg_sum,
                turn_n_f, turn_n_t, is_cross_f, is_cross_t  — 교차로 종류/회전제한/차수

출력: data/processed/link_structural_features.csv  (LINK_ID + 위 피처)
사용:  /opt/anaconda3/envs/2025ML/bin/python experiments/build_structural_features.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW = PROJECT_ROOT / "data" / "raw" / "road"
PROCESSED = PROJECT_ROOT / "data" / "processed"
OUT = PROCESSED / "link_structural_features.csv"

# 서울시청 부근 좌표 (ITRF2000 Central Belt, meter) — 도심거리 기준점
CBD_X, CBD_Y = 198000.0, 552000.0


def main():
    attr = pd.read_csv(PROCESSED / "seoul_link_attr.csv",
                       dtype={c: str for c in ["LINK_ID", "F_NODE", "T_NODE", "ROAD_NAME", "ROAD_RANK"]})
    for c in ["LANES", "MAX_SPD", "LENGTH"]:
        attr[c] = pd.to_numeric(attr[c], errors="coerce")
    n = len(attr)
    out = attr[["LINK_ID", "F_NODE", "T_NODE"]].copy()

    # ---------- 1. 코리도(도로명) 규모 ----------
    valid = attr["ROAD_NAME"].notna() & ~attr["ROAD_NAME"].isin(["", "-", "None"])
    rn = attr[valid].groupby("ROAD_NAME").agg(
        rn_links=("LINK_ID", "size"), rn_len=("LENGTH", "sum"),
        rn_lanes=("LANES", "mean"), rn_maxspd=("MAX_SPD", "mean")).reset_index()
    out = out.merge(attr[["LINK_ID", "ROAD_NAME", "LENGTH"]], on="LINK_ID").merge(rn, on="ROAD_NAME", how="left")
    # 이름 없는 도로는 '단독 링크'로 취급 (자기 링크 하나 = 그 도로 전체)
    out["rn_links"] = out["rn_links"].fillna(1)
    out["rn_len"] = out["rn_len"].fillna(out["LENGTH"])
    out["rn_lanes"] = out["rn_lanes"].fillna(attr["LANES"].median())
    out["rn_maxspd"] = out["rn_maxspd"].fillna(attr["MAX_SPD"].median())
    out = out.drop(columns=["LENGTH"])
    print(f"[1] 코리도 규모: {valid.sum():,}/{n:,} 링크가 이름 있는 도로 | 고유 도로명 {rn.shape[0]:,}")

    # ---------- 2. 노드 좌표 (전국 MOCT_NODE에서, 서울 링크의 F/T가 참조) ----------
    nd = pyogrio.read_dataframe(RAW / "MOCT_NODE.shp", columns=["NODE_ID", "NODE_TYPE", "TURN_P"])
    nd["NODE_ID"] = nd["NODE_ID"].astype(str)
    nd["nx"] = nd.geometry.x.values
    nd["ny"] = nd.geometry.y.values
    coord = nd.set_index("NODE_ID")[["nx", "ny", "NODE_TYPE", "TURN_P"]]

    fx = coord.reindex(out["F_NODE"]); tx = coord.reindex(out["T_NODE"])
    out["x"] = (fx["nx"].values + tx["nx"].values) / 2      # 링크 중점
    out["y"] = (fx["ny"].values + tx["ny"].values) / 2
    out["dist_cbd"] = np.sqrt((out["x"] - CBD_X) ** 2 + (out["y"] - CBD_Y) ** 2)
    print(f"[2] 노드 좌표: 좌표 결측 링크 {out['x'].isna().sum():,}")

    # ---------- 3. 노드 위상 ----------
    def code(vals):
        return pd.to_numeric(pd.Series(vals), errors="coerce")
    out["nodetype_f"] = code(fx["NODE_TYPE"].values).values
    out["nodetype_t"] = code(tx["NODE_TYPE"].values).values
    out["turnp_f"] = code(fx["TURN_P"].values).fillna(0).values
    out["turnp_t"] = code(tx["TURN_P"].values).fillna(0).values

    # 차수: 전국 MOCT_LINK로 계산해야 시계 노드가 정확 (서울만 쓰면 과소집계)
    ml = pyogrio.read_dataframe(RAW / "MOCT_LINK.shp", columns=["F_NODE", "T_NODE"], read_geometry=False)
    deg = pd.concat([ml["F_NODE"].astype(str), ml["T_NODE"].astype(str)]).value_counts()
    out["deg_f"] = deg.reindex(out["F_NODE"]).fillna(1).values
    out["deg_t"] = deg.reindex(out["T_NODE"]).fillna(1).values
    out["deg_sum"] = out["deg_f"] + out["deg_t"]

    # 회전제한 건수 (노드별)
    ti = pyogrio.read_dataframe(RAW / "TURNINFO.dbf", columns=["NODE_ID"])
    turn_n = ti["NODE_ID"].astype(str).value_counts()
    out["turn_n_f"] = turn_n.reindex(out["F_NODE"]).fillna(0).values
    out["turn_n_t"] = turn_n.reindex(out["T_NODE"]).fillna(0).values

    # 교차로 여부 (NODE_TYPE 101 = 교차로)
    out["is_cross_f"] = (out["nodetype_f"] == 101).astype("int8")
    out["is_cross_t"] = (out["nodetype_t"] == 101).astype("int8")
    print(f"[3] 노드 위상: 차수 평균 {out['deg_sum'].mean():.1f} | 회전제한 노드 {turn_n.size:,} | 교차로 끝 링크 {(out['is_cross_f']|out['is_cross_t']).sum():,}")

    # ---------- 저장 ----------
    feat_cols = ["LINK_ID",
                 "rn_links", "rn_len", "rn_lanes", "rn_maxspd",
                 "x", "y", "dist_cbd",
                 "nodetype_f", "nodetype_t", "turnp_f", "turnp_t",
                 "deg_f", "deg_t", "deg_sum", "turn_n_f", "turn_n_t", "is_cross_f", "is_cross_t"]
    out[feat_cols].to_csv(OUT, index=False)
    print(f"\n[완료] {OUT.name}: {len(out):,}행 x {len(feat_cols)-1}피처")


if __name__ == "__main__":
    main()
