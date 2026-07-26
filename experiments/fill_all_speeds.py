"""
서울 전 도로(63,548개)에 속도를 채운다 — 전역 라우팅의 재료.

방식 (링크 x 시간대 단위):
  센서 있는 도로 (약 11,010개) -> 실측 이력. "링크 x 시간대 x 주중/주말" 과거 평균
                                 (없으면 링크 x 시간대 -> 링크 평균 순 폴백). 우리 최고 모델.
  센서 없는 도로 (약 52,538개) -> 구조 피처 LightGBM 예측. 자기 이력이 없으므로
                                 도로망 생김새(코리도/좌표/교차로)로 시간대별 속도를 추정.

출력: data/processed/all_link_speeds.csv  (LINK_ID, 시간코드, dow_group, v_kmh, speed_source)
      -> 시간대별. 라우팅에서 원하는 시간대를 골라 쓰면 된다.
사용:  /opt/anaconda3/envs/2025ML/bin/python experiments/fill_all_speeds.py
"""
from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = PROJECT_ROOT / "data" / "processed"
OFFICIAL_CACHE = PROCESSED / "speed_model_cache_official.parquet"
STRUCT_PATH = PROCESSED / "link_structural_features.csv"
ATTR_PATH = PROCESSED / "seoul_link_attr.csv"
OUT = PROCESSED / "all_link_speeds.csv"

RANDOM_STATE = 42
V_FLOOR = 3.0


def main():
    # ---------- 1. 재료 로딩 ----------
    obs = pd.read_parquet(OFFICIAL_CACHE, columns=["LINK_ID", "시간코드", "dow_group_code", "평균속도"])
    obs["시간코드"] = obs["시간코드"].astype(int)
    struct = pd.read_csv(STRUCT_PATH, dtype={"LINK_ID": str})
    attr = pd.read_csv(ATTR_PATH, dtype={"LINK_ID": str},
                       usecols=["LINK_ID", "ROAD_RANK", "MAX_SPD", "LANES", "LENGTH"])
    for c in ["MAX_SPD", "LANES", "LENGTH", "ROAD_RANK"]:
        attr[c] = pd.to_numeric(attr[c], errors="coerce")
    sensor_links = set(obs["LINK_ID"].unique())
    all_links = attr["LINK_ID"].tolist()
    print(f"[1] 전체 링크 {len(all_links):,} | 센서 있음 {len(sensor_links):,} | 채울 도로 {len(all_links)-len(sensor_links):,}")

    STRUCT_COLS = [c for c in struct.columns if c != "LINK_ID"]
    ROUTE_HOURS = list(range(1, 25))          # 24개 시간대
    DOW_GROUPS = ["01", "02"]                  # 주중/주말 (T-data 원본 코드값과 통일)

    # ---------- 2. 센서 있는 도로: 실측 이력 조회표 (3단 폴백) ----------
    key3 = obs.groupby(["LINK_ID", "시간코드", "dow_group_code"])["평균속도"].mean()
    key2 = obs.groupby(["LINK_ID", "시간코드"])["평균속도"].mean()
    key1 = obs.groupby(["LINK_ID"])["평균속도"].mean()
    print(f"[2] 실측 조회표: (링크x시간x주말) {len(key3):,} / (링크x시간) {len(key2):,} / (링크) {len(key1):,}")

    # ---------- 3. 센서 없는 도로: 구조 피처 모델 학습 ----------
    # 학습셋 = 센서 있는 도로의 (링크x시간x주말) 평균속도. 피처 = 구조 + 시간대/주말 + 도로속성
    # 타깃 컬럼명은 구조피처(x,y 좌표)와 겹치지 않게 spd_target으로 둔다
    train = key3.rename("spd_target").reset_index()
    train = train.merge(struct, on="LINK_ID", how="left").merge(
        attr[["LINK_ID", "ROAD_RANK", "MAX_SPD", "LANES"]], on="LINK_ID", how="left")
    train["시간코드"] = train["시간코드"].astype(int)
    train["is_weekend"] = (train["dow_group_code"] == "02").astype("int8")
    FEATS = STRUCT_COLS + ["ROAD_RANK", "MAX_SPD", "LANES", "시간코드", "is_weekend"]
    model = lgb.LGBMRegressor(objective="regression", n_estimators=400, learning_rate=0.05,
                              num_leaves=63, random_state=RANDOM_STATE, n_jobs=-1, verbosity=-1)
    model.fit(train[FEATS], train["spd_target"])
    print(f"[3] 구조 피처 모델 학습 완료 (학습행 {len(train):,}, 피처 {len(FEATS)})")

    # ---------- 4. 센서 없는 도로 x 24시간 x 주중/주말 예측판 구성 ----------
    no_sensor = attr[~attr["LINK_ID"].isin(sensor_links)][["LINK_ID", "ROAD_RANK", "MAX_SPD", "LANES"]]
    grid = no_sensor.merge(pd.DataFrame({"시간코드": ROUTE_HOURS}), how="cross")
    grid = grid.merge(pd.DataFrame({"dow_group_code": DOW_GROUPS}), how="cross")
    grid = grid.merge(struct, on="LINK_ID", how="left")
    grid["is_weekend"] = (grid["dow_group_code"] == "02").astype("int8")
    grid["v_pred"] = model.predict(grid[FEATS])
    print(f"[4] 센서 없는 도로 예측: {grid['LINK_ID'].nunique():,}링크 x 24시간 x 2 = {len(grid):,}행")

    # ---------- 5. 두 소스 합치기 ----------
    # (a) 센서 있는 도로: 실측 조회표 값
    obs_full = key3.rename("v_kmh").reset_index()
    obs_full["source"] = "observed"
    # (b) 센서 없는 도로: 예측값
    pred_full = grid[["LINK_ID", "시간코드", "dow_group_code", "v_pred"]].rename(columns={"v_pred": "v_kmh"})
    pred_full["source"] = "structural_pred"

    allsp = pd.concat([obs_full, pred_full], ignore_index=True)
    # 제한속도 상한 + 하한 클리핑
    allsp = allsp.merge(attr[["LINK_ID", "MAX_SPD"]], on="LINK_ID", how="left")
    allsp["v_kmh"] = allsp["v_kmh"].clip(lower=V_FLOOR)
    cap = allsp["MAX_SPD"].clip(lower=V_FLOOR).fillna(allsp["v_kmh"])
    allsp["v_kmh"] = np.minimum(allsp["v_kmh"], cap).round(2)
    allsp = allsp.drop(columns=["MAX_SPD"]).rename(columns={"dow_group_code": "dow_group"})

    allsp.to_csv(OUT, index=False)
    n_link = allsp["LINK_ID"].nunique()
    print(f"\n[완료] {OUT.name}")
    print(f"  {len(allsp):,}행 | 링크 {n_link:,}/{len(all_links):,} ({n_link/len(all_links)*100:.1f}% 커버)")
    print(f"  소스 비율: {allsp['source'].value_counts().to_dict()}")
    print(f"  평균속도: 실측 {allsp[allsp.source=='observed']['v_kmh'].mean():.1f} / "
          f"예측 {allsp[allsp.source=='structural_pred']['v_kmh'].mean():.1f} km/h")


if __name__ == "__main__":
    main()
