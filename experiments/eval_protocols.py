"""
평가 체계 4종 — '무엇을 검증하느냐'에 따라 분할을 달리한 정직한 성능표.

팀 개선안 §3의 4가지 평가를 모두 구현한다. 하나의 데이터/모델을 분할 전략만 바꿔 돌려,
각 시나리오에서의 실제 성능을 한 표로 보고한다.

  1. 복제 누수 방지 : 원본 관측키(section+기준일+시간+방향) GroupKFold
                     같은 관측값 복제가 train/test에 섞이지 않는지 (누수 검증 조건)
  2. 시간 일반화   : 날짜 순차분할 (과거→미래). 관측 링크의 대표 성능
  3. 공간 일반화   : section_id(T-data 구간) GroupKFold. 처음 보는 구간 일반화
  4. 링크 공백 모사 : section GroupKFold + 'Model B' 정적 피처만. 미관측 링크 추정

피처:
  CLEAN(Model B) = 83% 미관측 링크에도 실제 존재하는 컬럼만 (구조/MOCT/지형/시간)
  FULL           = CLEAN + T-data 전용(도로구분코드/방향코드) — 미관측 링크엔 없음(누수)

사용:  /opt/anaconda3/envs/2025ML/bin/python experiments/eval_protocols.py [--dataset official]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = PROJECT_ROOT / "data" / "processed"
RANDOM_STATE = 42

STRUCT = None  # 로딩 후 채움
MOCT_CAT = ["ROAD_RANK", "ROAD_TYPE", "ROAD_USE", "MULTI_LINK", "CONNECT"]
MOCT_NUM = ["LANES", "MAX_SPD", "LENGTH"]
DEM = ["slope_pct", "abs_slope_pct", "elev_mean_m", "elev_delta_m"]
TIME = ["시간코드", "is_weekend"]
TDATA_ONLY = ["도로구분코드", "도로방향구분코드"]   # 미관측 링크에 없는 T-data 전용


def load(dataset="official"):
    cache = {"official": "speed_model_cache_official.parquet",
             "prefix8": "speed_model_cache.parquet"}[dataset]
    c = pd.read_parquet(PROCESSED / cache)
    sf = pd.read_csv(PROCESSED / "link_structural_features.csv", dtype={"LINK_ID": str})
    c = c.merge(sf, on="LINK_ID", how="left")
    c["is_weekend"] = (c["dow_group_code"] == "02").astype("int8")
    for col in MOCT_CAT + TDATA_ONLY:
        if col in c:
            c[col] = c[col].astype(str).astype("category")
    global STRUCT
    STRUCT = [x for x in sf.columns if x != "LINK_ID"]
    # 원본 관측키: 같은 T-data 관측이 복제된 링크들을 한 그룹으로
    c["obs_id"] = (c["section_id"].astype(str) + "|" + c["기준일"].astype(str) + "|" +
                   c["시간코드"].astype(str) + "|" + c["도로방향구분코드"].astype(str))
    return c


def fit_eval(c, feats, tr, te):
    catf = [f for f in feats if str(c[f].dtype) == "category"]
    m = lgb.LGBMRegressor(n_estimators=250, num_leaves=63, learning_rate=0.05,
                          random_state=RANDOM_STATE, n_jobs=-1, verbosity=-1)
    m.fit(c.iloc[tr][feats], c.iloc[tr]["평균속도"], categorical_feature=catf)
    p = m.predict(c.iloc[te][feats])
    return r2_score(c.iloc[te]["평균속도"], p), mean_absolute_error(c.iloc[te]["평균속도"], p)


def kfold(c, feats, groupcol, k=3):
    g = c[groupcol].astype(str).values
    r2s, maes = [], []
    for tr, te in GroupKFold(n_splits=k).split(c, c["평균속도"], g):
        r2, mae = fit_eval(c, feats, tr, te)
        r2s.append(r2); maes.append(mae)
    return np.mean(r2s), np.mean(maes), c[groupcol].nunique()


def time_split(c, feats, test_frac=0.2):
    tm = c["tm"].astype(str).values
    uniq = np.sort(np.unique(tm))
    cut = uniq[-max(1, int(round(len(uniq) * test_frac)))]
    tr = np.where(tm < cut)[0]; te = np.where(tm >= cut)[0]
    return (*fit_eval(c, feats, tr, te), None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="official")
    args = ap.parse_args()

    c = load(args.dataset)
    CLEAN = STRUCT + MOCT_CAT + MOCT_NUM + DEM + TIME       # Model B (미관측 링크에도 있는 것만)
    FULL = CLEAN + TDATA_ONLY                                # + T-data 전용(누수)
    print(f"데이터 {args.dataset} | {len(c):,}행 | 링크 {c['LINK_ID'].nunique():,} | "
          f"section {c['section_id'].nunique():,} | obs {c['obs_id'].nunique():,}\n")

    print("=== 4대 평가 프로토콜 (동일 데이터, 분할 전략만 변경) ===")
    print(f"{'평가':22} {'분할키':16} {'피처':9} {'R2':>7} {'MAE':>7}")
    print("-" * 66)
    rows = []

    r2, mae, ng = kfold(c, CLEAN, "obs_id")
    print(f"{'1.복제누수방지':22} {'관측키(3fold)':16} {'CLEAN':9} {r2:7.4f} {mae:7.3f}"); rows.append(("복제누수방지", r2, mae))

    r2, mae, _ = time_split(c, CLEAN)
    print(f"{'2.시간일반화(대표)':20} {'날짜순차':16} {'CLEAN':9} {r2:7.4f} {mae:7.3f}"); rows.append(("시간일반화", r2, mae))

    r2, mae, ng = kfold(c, FULL, "section_id")
    print(f"{'3.공간일반화':22} {'section(3fold)':16} {'FULL':9} {r2:7.4f} {mae:7.3f}"); rows.append(("공간일반화", r2, mae))

    r2, mae, ng = kfold(c, CLEAN, "section_id")
    print(f"{'4.링크공백모사(ModelB)':18} {'section(3fold)':16} {'CLEAN':9} {r2:7.4f} {mae:7.3f}"); rows.append(("링크공백ModelB", r2, mae))

    print("\n=== 진단: 그룹키에 따른 누수 크기 (동일 CLEAN 피처) ===")
    r2p, maep, _ = kfold(c, CLEAN, "link_group")
    r2s, maes, _ = kfold(c, CLEAN, "section_id")
    print(f"  prefix8(앞8자리, 현행)  R2={r2p:.4f}")
    print(f"  section(공식 구간, 정직) R2={r2s:.4f}   차이 {r2p-r2s:+.4f}  ← 클수록 prefix8이 낙관 편향")

    print("\n=== 참고: 관측 링크 시간일반화에 '이력' 추가 시 (배포용 실제 성능) ===")
    key = c.groupby(["LINK_ID", "시간코드", "dow_group_code"])  # 링크x시간x주중주말 이력
    print("  (link x 시간 x 주중/주말) 조회표는 speed_model_lab --mode compare 참고: R2 0.928")


if __name__ == "__main__":
    main()
