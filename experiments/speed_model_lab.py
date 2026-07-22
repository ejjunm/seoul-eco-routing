"""
Stage1 속도예측 빠른 실험 harness.

- 최종 결합테이블(seoul_link_speed_dem_weather_merged.csv, ~2.5GB)에서 필요한 컬럼만
  뽑아 parquet로 1회 캐싱 -> 이후 실험마다 로딩이 수초로 줄어든다.
- 피처 config / 분할 방식만 바꿔가며 LightGBM을 반복 학습/평가하고, 결과를
  experiments/results.csv에 자동 append 한다.

두 가지 평가(분할) 시나리오를 지원한다:
  * split="group" : LINK_ID 앞 8자리 그룹분할 = "처음 보는 도로"의 속도를 정적 피처로 예측.
                    T-data broadcast 유출을 막는 정직한 평가지만, 도로 이력을 못 써서 R²≈0.57이 천장.
  * split="time"  : tm(YYYYMMDDHHMM) 기준 시간분할 = "아는 도로의 새로운 시간대" 예측.
                    에코라우팅의 실제 상황. 링크별 시간대 이력(target encoding)을 train에서만 계산해
                    적용할 수 있어(누수 없음) 정확도를 크게 끌어올릴 수 있다.

target encoding(temporal 피처)은 반드시 train 구간에서만 통계를 내서 전체에 매핑한다.
시간분할에서는 train=과거, test=미래라 test 행에는 과거 평균만 쓰이므로 누수가 없다.

사용:
  python experiments/speed_model_lab.py --mode time            # 시간분할 배치(기본)
  python experiments/speed_model_lab.py --mode group           # 그룹분할 배치
  python experiments/speed_model_lab.py --mode time --rebuild  # parquet 캐시 재생성 후 실행
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupShuffleSplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = PROJECT_ROOT / "data" / "processed"
# 두 가지 라벨 데이터셋을 전환해가며 비교한다.
#   prefix8  = 04번 스크립트의 휴리스틱 broadcast (25,151링크 = 서울의 39.6%)
#   official = 공식 표준링크 매핑표 기반 (11,010링크 = 17.3%), experiments/build_official_17pct.py 생성
DATASETS = {
    "prefix8":  ("seoul_link_speed_dem_weather_merged.csv", "speed_model_cache.parquet"),
    "official": ("seoul_link_speed_dem_weather_official.csv", "speed_model_cache_official.parquet"),
}
DATASET = "prefix8"
CSV_PATH = PROCESSED / DATASETS[DATASET][0]
CACHE_PATH = PROCESSED / DATASETS[DATASET][1]  # data/processed/**는 gitignore됨
RESULTS_PATH = PROJECT_ROOT / "experiments" / "results.csv"


def set_dataset(key: str):
    """사용할 라벨 데이터셋 전환 (경로 + 프로세스 내 캐시 초기화)."""
    global DATASET, CSV_PATH, CACHE_PATH, _DATA, _ENC_CACHE
    DATASET = key
    CSV_PATH = PROCESSED / DATASETS[key][0]
    CACHE_PATH = PROCESSED / DATASETS[key][1]
    _DATA = None
    _ENC_CACHE = {}

RANDOM_STATE = 42
TARGET = "평균속도"
GROUP_SOURCE = "LINK_ID"

# notebooks/11과 동일한 '원본 컬럼' 구성 (파생 피처는 build_feature_frame에서 실험별로 추가)
BASE_NUMERIC = [
    "LANES", "MAX_SPD", "LENGTH", "시간코드",
    "elev_start_m", "elev_mid_m", "elev_end_m", "elev_mean_m", "elev_min_m", "elev_max_m", "elev_delta_m",
    "slope_pct", "abs_slope_pct", "dem_sample_count", "precip_mm",
]
BASE_CATEGORICAL = [
    "ROAD_RANK", "ROAD_TYPE", "ROAD_USE", "MULTI_LINK", "CONNECT",
    "REST_VEH", "REST_W", "REST_H", "C-ITS",
    "도로방향구분코드", "도로구분코드",
    "요일코드(1~7:일~토)", "요일그룹코드(01:주중/02:주말)",
    "첨두시구분(T1/T2/T3:오전/낮/오후)",
]
TIME_COLS = ["기준일", "tm"]  # 시간분할 정렬 및 이력 피처용
# LightGBM은 컬럼명에 특수문자(괄호/콜론/슬래시)를 허용하지 않아 모델용 이름으로 치환(값·의미 동일)
RENAME_MAP = {
    "요일코드(1~7:일~토)": "dow_code",
    "요일그룹코드(01:주중/02:주말)": "dow_group_code",
    "첨두시구분(T1/T2/T3:오전/낮/오후)": "peak_period",
    "C-ITS": "c_its",
}
NUMERIC = [RENAME_MAP.get(c, c) for c in BASE_NUMERIC]
CATEGORICAL = [RENAME_MAP.get(c, c) for c in BASE_CATEGORICAL]

# target encoding 키 (train에서만 평균 계산)
ENCODING_KEYS = {
    "link": ["LINK_ID"],                          # 이 링크의 전형 속도
    "link_hour": ["LINK_ID", "시간코드"],           # 이 링크의 이 시간대 전형 속도
    "link_hour_dow": ["LINK_ID", "시간코드", "dow_code"],  # 요일 7단계 — 표본부족으로 과적합(실측 악화)
    # 요일을 7단계가 아니라 주중/주말 2단계로만 쪼갠 버전. 셀당 표본이 충분해 과적합 없이 이득.
    "link_hour_dowgrp": ["LINK_ID", "시간코드", "dow_group_code"],
}

_DATA = None       # 프로세스 내 1회 로딩 캐시
_ENC_CACHE = {}    # (split_sig, enc) -> 인코딩 배열 재사용


def build_cache(verbose: bool = True) -> pd.DataFrame:
    usecols = BASE_NUMERIC + BASE_CATEGORICAL + TIME_COLS + [TARGET, GROUP_SOURCE]
    dtype = {c: str for c in BASE_CATEGORICAL + TIME_COLS}
    dtype[GROUP_SOURCE] = str
    t = time.time()
    df = pd.read_csv(CSV_PATH, usecols=usecols, dtype=dtype, encoding="utf-8-sig")
    for c in BASE_NUMERIC + [TARGET]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.rename(columns=RENAME_MAP)
    df = df.dropna(subset=[TARGET] + NUMERIC)
    df["link_group"] = df[GROUP_SOURCE].str[:8]  # 그룹분할 키
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE_PATH, index=False)
    if verbose:
        tm = df["tm"].astype(str)
        print(f"[cache] built {CACHE_PATH.name}: {len(df):,}행 x {df.shape[1]}컬럼 ({time.time()-t:.1f}s)")
        print(f"[cache] tm {tm.min()}~{tm.max()} | 고유 tm {tm.nunique()} | "
              f"시간코드 {int(df['시간코드'].min())}~{int(df['시간코드'].max())} | "
              f"강수>0 {(df['precip_mm']>0).mean():.1%} | 고유 link_group {df['link_group'].nunique():,}")
    return df


def load_data(rebuild: bool = False) -> pd.DataFrame:
    global _DATA
    if _DATA is not None and not rebuild:
        return _DATA
    if rebuild or not CACHE_PATH.exists():
        _DATA = build_cache()
    else:
        t = time.time()
        _DATA = pd.read_parquet(CACHE_PATH)
        print(f"[cache] loaded {CACHE_PATH.name}: {len(_DATA):,}행 ({time.time()-t:.1f}s)")
    return _DATA


def build_feature_frame(base: pd.DataFrame, feats: set):
    """원본 컬럼 + 선택된 정적 파생 피처로 (X, cat_cols) 구성. base는 변형하지 않는다."""
    X = base[NUMERIC + CATEGORICAL].copy()
    extra_cat = []
    if "time_cyclic" in feats:
        period = float(base["시간코드"].max())
        ang = 2 * np.pi * base["시간코드"] / period
        X["sin_hour"], X["cos_hour"] = np.sin(ang), np.cos(ang)
    if "rain" in feats:
        X["is_rain"] = (base["precip_mm"] > 0).astype("int8")
        X["rain_bin"] = pd.cut(base["precip_mm"], bins=[-0.001, 0, 1, 5, 10, np.inf],
                               labels=["0", "0-1", "1-5", "5-10", "10+"])
        extra_cat.append("rain_bin")
    if "log_length" in feats:
        X["log_length"] = np.log1p(base["LENGTH"])
    if "interactions" in feats:
        is_peak = (base["peak_period"] != "N").astype("int8")
        X["precip_x_peak"] = base["precip_mm"] * is_peak
        X["slope_x_rain"] = base["abs_slope_pct"] * base["precip_mm"]
    cat_cols = CATEGORICAL + extra_cat
    for c in cat_cols:
        X[c] = X[c].astype("category")
    return X, cat_cols


def group_split(base):
    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=RANDOM_STATE)
    return next(gss.split(base, base[TARGET], base["link_group"]))


def time_split(base, test_frac=0.2):
    """tm 기준 시간분할: 가장 늦은 test_frac 비율의 tm들을 test로."""
    tm = base["tm"].astype(str).values
    uniq = np.sort(np.unique(tm))
    n_test = max(1, int(round(len(uniq) * test_frac)))
    test_set = set(uniq[-n_test:])
    is_test = np.fromiter((t in test_set for t in tm), dtype=bool, count=len(tm))
    test_idx = np.where(is_test)[0]
    train_idx = np.where(~is_test)[0]
    span = (uniq[0], uniq[-n_test - 1] if len(uniq) > n_test else uniq[0], uniq[-n_test], uniq[-1])
    return train_idx, test_idx, span


def build_encoding(base, train_idx, enc, split_sig, smooth=0.0):
    """train 구간에서만 target 평균을 내 전체 행에 매핑.
    smooth>0이면 count 기반 shrinkage: (m*n + gmean*smooth)/(n+smooth) — 표본 적은 조합을 전체평균으로 당김.
    세부키 결측은 link평균->전체평균으로 fallback."""
    ck = (split_sig, enc, smooth)
    if ck in _ENC_CACHE:
        return _ENC_CACHE[ck]
    keys = ENCODING_KEYS[enc]
    tr = base.iloc[train_idx]
    gmean = float(tr[TARGET].mean())

    def enc_table(gkeys, col):
        g = tr.groupby(gkeys, observed=True)[TARGET].agg(m="mean", n="count").reset_index()
        g[col] = (g["m"] * g["n"] + gmean * smooth) / (g["n"] + smooth) if smooth > 0 else g["m"]
        return g[gkeys + [col]]

    te = base[keys].merge(enc_table(keys, "__te"), on=keys, how="left")["__te"]
    if enc != "link":
        lte = base[["LINK_ID"]].merge(enc_table(["LINK_ID"], "__lte"), on="LINK_ID", how="left")["__lte"]
        te = te.fillna(lte)
    arr = te.fillna(gmean).astype("float32").values
    _ENC_CACHE[ck] = arr
    return arr


def run_experiment(name, feats=(), temporal=(), params=None, split="group", test_frac=0.2, log=True, smooth=0.0):
    base = load_data()
    feats = set(feats)
    X, cat_cols = build_feature_frame(base, feats)
    y = base[TARGET]

    if split == "time":
        train_idx, test_idx, span = time_split(base, test_frac)
        split_sig = f"time_{test_frac}"
        note = f"train {span[0][:8]}~{span[1][:8]} / test {span[2][:8]}~{span[3][:8]}"
    else:
        train_idx, test_idx = group_split(base)
        split_sig = "group_0.2"
        note = "group(LINK_ID prefix8)"

    for enc in temporal:
        X[f"te_{enc}"] = build_encoding(base, train_idx, enc, split_sig, smooth)

    Xtr, Xte = X.iloc[train_idx], X.iloc[test_idx]
    ytr, yte = y.iloc[train_idx], y.iloc[test_idx]

    p = dict(objective="regression", n_estimators=300, learning_rate=0.05,
             num_leaves=63, random_state=RANDOM_STATE, n_jobs=-1, verbosity=-1)
    if params:
        p.update(params)

    t = time.time()
    model = lgb.LGBMRegressor(**p)
    model.fit(Xtr, ytr, categorical_feature=cat_cols)
    pred = model.predict(Xte)
    dt = time.time() - t

    rmse = mean_squared_error(yte, pred) ** 0.5
    mae = mean_absolute_error(yte, pred)
    r2 = r2_score(yte, pred)
    tuned = {k: v for k, v in p.items() if k in ("n_estimators", "num_leaves", "learning_rate", "min_child_samples")}
    if smooth:
        tuned["smooth"] = smooth
    row = dict(name=name, split=split, rmse=round(rmse, 4), mae=round(mae, 4), r2=round(r2, 4),
               n_features=X.shape[1], feats="+".join(sorted(feats)) or "base",
               temporal="+".join(temporal) or "-", params=str(tuned), seconds=round(dt, 1))
    print(f"  {name:22} RMSE={rmse:6.4f} MAE={mae:6.4f} R2={r2:6.4f}  ({X.shape[1]}feat {dt:.0f}s) [{note}]")
    if log:
        _append_result(row)
    return row, model


def _append_result(row: dict):
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame([{"dataset": DATASET, **row}])
    allc = pd.concat([pd.read_csv(RESULTS_PATH), new], ignore_index=True) if RESULTS_PATH.exists() else new
    allc.to_csv(RESULTS_PATH, index=False)


def run_lookup(name, enc="link_hour", split="time", test_frac=0.2, smooth=0.0, log=True):
    """ML 없이 train 이력 평균(target encoding)을 그대로 예측으로 써서 평가 — ML의 추가 가치 비교용."""
    base = load_data()
    if split == "time":
        train_idx, test_idx, _ = time_split(base, test_frac)
        sig = f"time_{test_frac}"
    else:
        train_idx, test_idx = group_split(base)
        sig = "group_0.2"
    pred_all = build_encoding(base, train_idx, enc, sig, smooth)
    yte = base[TARGET].values[test_idx]
    pred = pred_all[test_idx]
    rmse = mean_squared_error(yte, pred) ** 0.5
    mae = mean_absolute_error(yte, pred)
    r2 = r2_score(yte, pred)
    row = dict(name=name, split=split, rmse=round(rmse, 4), mae=round(mae, 4), r2=round(r2, 4),
               n_features=1, feats=f"lookup", temporal=enc, params=f"smooth={smooth}", seconds=0.0)
    print(f"  {name:22} RMSE={rmse:6.4f} MAE={mae:6.4f} R2={r2:6.4f}  (ML 없이 이력표 직접, {enc})")
    if log:
        _append_result(row)
    return row


def run_refine(test_frac=0.2):
    """진단 배치: ML의 추가가치 / smoothing으로 미세키 살리기 / 다른 시간구간 강건성."""
    rows = []
    # (1) ML 없이 이력표 직접 예측 (link_hour) — 베스트 ML과 비교
    rows.append(run_lookup("x_lookup_link_hour", "link_hour", "time", test_frac))
    # (2) 베스트 ML 재현 (link_hour만)
    rows.append(run_experiment("x_ml_link_hour", (), ("link_hour",), None, "time", test_frac)[0])
    # (3) 현재조건 위에 link_hour (날씨 등으로 이력 보정)
    rows.append(run_experiment("x_ml_lh+cond", ("time_cyclic", "rain", "interactions"), ("link_hour",), None, "time", test_frac)[0])
    # (4) smoothing으로 요일 미세키 규제해서 넣기
    rows.append(run_experiment("x_ml_lh+dow_sm50", (), ("link_hour", "link_hour_dow"), None, "time", test_frac, smooth=50)[0])
    rows.append(run_experiment("x_ml_lh+dow_sm200", (), ("link_hour", "link_hour_dow"), None, "time", test_frac, smooth=200)[0])
    # (5) 강건성: 다른 test 구간(30%)에서 베스트 재확인
    rows.append(run_experiment("x_ml_link_hour_tf30", (), ("link_hour",), None, "time", 0.3)[0])
    return rows


def build_dev_features(base, feats):
    """편차 모델용 피처 — (link×hour) 평소값에 이미 담긴 '링크 고정 속성'이 아니라,
    같은 링크·시간대에서 '날마다 달라지는' 조건만 넣는다."""
    X = pd.DataFrame(index=base.index)
    cat = []
    if "dow" in feats:
        X["시간코드"] = base["시간코드"]
        for c in ["dow_code", "dow_group_code", "peak_period"]:
            X[c] = base[c].astype("category")
            cat.append(c)
    if "weather" in feats:
        X["precip_mm"] = base["precip_mm"]
        X["is_rain"] = (base["precip_mm"] > 0).astype("int8")
        X["rain_bin"] = pd.cut(base["precip_mm"], bins=[-0.001, 0, 1, 5, 10, np.inf],
                               labels=["0", "0-1", "1-5", "5-10", "10+"]).astype("category")
        cat.append("rain_bin")
    if "interact" in feats:
        is_peak = (base["peak_period"] != "N").astype("int8")
        X["precip_x_peak"] = base["precip_mm"] * is_peak
        X["slope_x_rain"] = base["abs_slope_pct"] * base["precip_mm"]
        X["abs_slope_pct"] = base["abs_slope_pct"]
        X["ROAD_RANK"] = base["ROAD_RANK"].astype("category")
        cat.append("ROAD_RANK")
    return X, cat


def run_deviation(name, dev_feats, split="time", test_frac=0.2, params=None, log=True):
    """target = 실제속도 - 평소속도(te_link_hour, train fit). 조건 피처가 편차를 설명하는지 검증."""
    base = load_data()
    train_idx, test_idx, _ = time_split(base, test_frac)
    typical = build_encoding(base, train_idx, "link_hour", f"time_{test_frac}")
    y = base[TARGET].values
    dev = y - typical

    X, cat_cols = build_dev_features(base, set(dev_feats))
    Xtr, Xte = X.iloc[train_idx], X.iloc[test_idx]
    dtr, dte = dev[train_idx], dev[test_idx]

    p = dict(objective="regression", n_estimators=300, learning_rate=0.05,
             num_leaves=63, random_state=RANDOM_STATE, n_jobs=-1, verbosity=-1)
    if params:
        p.update(params)

    t = time.time()
    model = lgb.LGBMRegressor(**p).fit(Xtr, dtr, categorical_feature=cat_cols)
    dpred = model.predict(Xte)
    dt = time.time() - t

    r2_dev = r2_score(dte, dpred)                 # 편차 자체를 얼마나 설명하나
    speed_pred = typical[test_idx] + dpred        # 재구성 속도
    yte = y[test_idx]
    rmse = mean_squared_error(yte, speed_pred) ** 0.5
    mae = mean_absolute_error(yte, speed_pred)
    r2 = r2_score(yte, speed_pred)
    row = dict(name=name, split="time-dev", rmse=round(rmse, 4), mae=round(mae, 4), r2=round(r2, 4),
               r2_dev=round(r2_dev, 4), n_features=X.shape[1], feats="+".join(dev_feats),
               temporal="link_hour(base)", params=str({k: p[k] for k in ("n_estimators", "num_leaves")}),
               seconds=round(dt, 1))
    print(f"  {name:20} 속도R2={r2:6.4f} (편차R2={r2_dev:+.4f}) RMSE={rmse:.4f} MAE={mae:.4f}  ({X.shape[1]}feat {dt:.0f}s)")
    if log:
        _append_result(row)
    return row


def run_compare(test_frac=0.2):
    """40%(prefix8) vs 17%(official) 비교용 핵심 실험 세트 + 주중/주말 룩업키 검증."""
    rows = []
    # 처음 보는 도로 (그룹분할) — 기존 0.573과 비교
    rows.append(run_experiment("c00_group_static", (), (), None, "group", test_frac)[0])
    # 아는 도로 (시간분할)
    rows.append(run_experiment("c01_time_static", (), (), None, "time", test_frac)[0])
    rows.append(run_lookup("c02_lookup_link_hour", "link_hour", "time", test_frac))
    rows.append(run_lookup("c03_lookup_lh_dowgrp", "link_hour_dowgrp", "time", test_frac))  # ★ 주중/주말
    rows.append(run_experiment("c04_ml_link_hour", (), ("link_hour",), None, "time", test_frac)[0])
    rows.append(run_experiment("c05_ml_lh_dowgrp", (), ("link_hour_dowgrp",), None, "time", test_frac)[0])
    return rows


def run_deviation_batch(test_frac=0.2):
    print("  [기준] typical-only(link_hour 룩업, 편차예측 0) = 속도 R2 0.900")
    rows = [run_lookup("dv_typical_only", "link_hour", "time", test_frac)]
    rows.append(run_deviation("dv_dow", ["dow"], test_frac=test_frac))
    rows.append(run_deviation("dv_weather", ["weather"], test_frac=test_frac))
    rows.append(run_deviation("dv_dow+weather", ["dow", "weather"], test_frac=test_frac))
    rows.append(run_deviation("dv_all", ["dow", "weather", "interact"], test_frac=test_frac))
    return rows


# 정적 파생/튜닝 배치 (그룹분할) — 이미 R²≈0.57 천장 확인
BATCH_GROUP = [
    ("g00_baseline",     (), (),                                                None, "group"),
    ("g01_time_cyclic",  ("time_cyclic",), (),                                  None, "group"),
    ("g04_interactions", ("interactions",), (),                                 None, "group"),
    ("g05_all_feats",    ("time_cyclic", "rain", "log_length", "interactions"), (), None, "group"),
]

# 시간분할 + 이력(target encoding) 배치 — 에코라우팅 실제 시나리오
BATCH_TIME = [
    ("t00_static_time",    (), (),                                    None, "time"),
    ("t01_te_link",        (), ("link",),                             None, "time"),
    ("t02_te_link_hour",   (), ("link_hour",),                        None, "time"),
    ("t03_te_link_hr_dow", (), ("link_hour_dow",),                    None, "time"),
    ("t04_te_all",         (), ("link", "link_hour", "link_hour_dow"), None, "time"),
    ("t05_te_all+cond",    ("time_cyclic", "rain", "interactions"),
                           ("link", "link_hour", "link_hour_dow"),    None, "time"),
    ("t06_te_all_tuned",   ("time_cyclic", "rain", "interactions"),
                           ("link", "link_hour", "link_hour_dow"),
                           dict(n_estimators=600, num_leaves=127, learning_rate=0.03, min_child_samples=50), "time"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["time", "group", "both", "refine", "deviation", "compare"], default="time")
    ap.add_argument("--dataset", choices=list(DATASETS), default="prefix8",
                    help="prefix8=휴리스틱 25,151링크(39.6%%) / official=공식매핑 11,010링크(17.3%%)")
    ap.add_argument("--rebuild", action="store_true", help="parquet 캐시 강제 재생성")
    ap.add_argument("--test-frac", type=float, default=0.2)
    args = ap.parse_args()

    set_dataset(args.dataset)
    load_data(rebuild=args.rebuild)
    print(f"\n=== 실험 배치 시작 (dataset={args.dataset}, mode={args.mode}) ===")
    if args.mode == "compare":
        rows = run_compare(args.test_frac)
    elif args.mode == "refine":
        rows = run_refine(args.test_frac)
    elif args.mode == "deviation":
        rows = run_deviation_batch(args.test_frac)
    else:
        batch = {"time": BATCH_TIME, "group": BATCH_GROUP, "both": BATCH_GROUP + BATCH_TIME}[args.mode]
        rows = [run_experiment(n, f, tmp, p, sp, args.test_frac)[0] for n, f, tmp, p, sp in batch]

    res = pd.DataFrame(rows).sort_values("rmse").reset_index(drop=True)
    print("\n=== 결과 (RMSE 낮은 순) ===")
    cols = ["name", "split", "rmse", "mae", "r2"] + (["r2_dev"] if "r2_dev" in res.columns else []) + ["n_features", "seconds"]
    print(res[cols].to_string(index=False))
    best = res.iloc[0]
    print(f"\n최고: {best['name']} ({best['split']}) | RMSE {best['rmse']} | MAE {best['mae']} | R2 {best['r2']}")
    print(f"누적 로그: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
