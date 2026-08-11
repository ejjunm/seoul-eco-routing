"""
[역할]
사전 학습된 모델 아티팩트(Model A 조회표, Model B/C XGBoost)를 로드하여,
특정 시각(tm)의 서울시 전체 63,548개 링크 속도 및 통행시간 스냅샷을 초고속으로 추론 생성합니다.

[주요 기능]
- 사전 학습 아티팩트 서빙: src/models/artifacts/에 저장된
  XGBoost 모델(model_nb, model_stat)과 Model A Lookup Parquet을 고속 로드하여 추론합니다.

- 계층적 속도 산출 (Tier A / B / C):
  1. A 계층 (관측/이력): Model A 조회표 및 해당 시각 관측값 우선 반영
  2. B 계층 (미관측·이웃있음): neighbor_speed_lookup과 model_nb (이웃속도 포함 모델) 적용
  3. C 계층 (미관측·이웃없음): model_stat (정적 전용 모델) 적용

[실행 방식]
python src/routing/13_predict_all_link_speed.py --tm 202607090800

[결과물 저장]
- 저장 위치: data/processed/seoul_all_link_speed/seoul_all_link_speed_{tm}.csv
"""

from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
MODELS_DIR = PROJECT_ROOT / "src" / "models" / "artifacts"

DIMENSION_PATH = PROCESSED_DIR / "seoul_link_dimension.csv"
MODEL_A_PATH = PROCESSED_DIR / "model_a_lookup.parquet"
NEIGHBOR_LOOKUP_PATH = PROCESSED_DIR / "neighbor_speed_lookup.parquet"

SPEED_FLOOR_KMH = 3.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tm", required=True, help="예측 시각 YYYYMMDDHHMM")
    return parser.parse_args()


def load_artifacts():
    """사전 학습된 XGBoost 모델 및 Lookup 데이터셋 로드"""
    model_nb_path = MODELS_DIR / "model_nb.pkl"
    model_stat_path = MODELS_DIR / "model_stat.pkl"

    if not model_nb_path.exists() or not model_stat_path.exists():
        raise SystemExit("학습된 모델 아티팩트가 없습니다. 먼저 python src/models/02_build_model_bc.py --mode final 을 실행하세요.")

    with open(model_nb_path, "rb") as f:
        artifact_nb = pickle.load(f)
    with open(model_stat_path, "rb") as f:
        artifact_stat = pickle.load(f)

    return artifact_nb, artifact_stat


def main() -> None:
    args = parse_args()
    if len(args.tm) != 12 or not args.tm.isdigit():
        raise SystemExit("--tm은 YYYYMMDDHHMM 형식이어야 합니다.")
        
    date_str, hour = args.tm[:8], int(args.tm[8:10])
    
    # 1. 기상 스냅샷 사전 존재 여부 검증
    weather_path = PROCESSED_DIR / "weather_snapshot" / f"weather_snapshot_{args.tm}.csv"
    if not weather_path.exists():
        raise SystemExit(f"먼저 기상 스냅샷을 생성하세요: {weather_path}\n"
                         f"  python src/routing/12_build_all_link_weather_snapshot.py --tm {args.tm}")

    print(f"[1/3] 사전 학습된 아티팩트 및 정적 피처 로드 ({args.tm})...")
    artifact_nb, artifact_stat = load_artifacts()

    # 모델 Booster에서 최종 학습된 피처 명단(이름/순서) 추출
    nb_features = artifact_nb["model"].get_booster().feature_names
    stat_features = artifact_stat["model"].get_booster().feature_names
    
    # 2. Polars를 활용한 고속 입출력 및 ID 계열 범주 데이터 Utf8 강제 지정
    schema_overrides = {"LINK_ID": pl.Utf8, "F_NODE": pl.Utf8, "T_NODE": pl.Utf8, "C-ITS": pl.Utf8}
    for col in artifact_nb["categorical_cols"]:
        if col != "c_its":
            schema_overrides[col] = pl.Utf8
            
    dim_pl = pl.read_csv(DIMENSION_PATH, schema_overrides=schema_overrides)
    
    # C-ITS 컬럼 대소문자 표기 정규화
    if "C-ITS" in dim_pl.columns and "c_its" not in dim_pl.columns:
        dim_pl = dim_pl.rename({"C-ITS": "c_its"})
        
    weather_pl = pl.read_csv(weather_path, columns=["LINK_ID", "precip_mm"], schema_overrides={"LINK_ID": pl.Utf8})
    
    # 차원(정적 도로 속성)과 기상 스냅샷 결합
    snapshot_pl = dim_pl.join(weather_pl, on="LINK_ID", how="left")
    
    # 3. 시간 및 시계열 파생 피처 동적 계산
    dt = pd.to_datetime(date_str, format="%Y%m%d")
    weekday = dt.weekday()
    is_weekend = 1 if weekday >= 5 else 0
    
    snapshot_df = snapshot_pl.to_pandas()
    snapshot_df["시간코드"] = hour
    snapshot_df["dow"] = weekday
    # pd.Categorical(
    #     [weekday] * len(snapshot_df),
    #     categories=list(range(7))
    # )
    snapshot_df["is_weekend"] = is_weekend
    snapshot_df["hour_sin"] = np.sin(2 * np.pi * hour / 24).astype("float32")
    snapshot_df["hour_cos"] = np.cos(2 * np.pi * hour / 24).astype("float32")
    
    # View-T 시간대별 속도 매핑
    actual_hour = max(0, min(23, hour - 1))
    if f"avg_speed_h{actual_hour}" in snapshot_df.columns:
        snapshot_df["avg_speed_hourly"] = snapshot_df[f"avg_speed_h{actual_hour}"]
    else:
        snapshot_df["avg_speed_hourly"] = np.nan

    print("[2/3] 계층별(A/B/C) 추론 수행...")
    
    # 1) Model A (이력 조회표) 적용
    model_a = pd.read_parquet(MODEL_A_PATH)
    time_code_key = hour if hour > 0 else 24
    a_match = model_a[(model_a["시간코드"] == time_code_key) & (model_a["is_weekend"] == is_weekend)]
    snapshot_df = snapshot_df.merge(a_match[["LINK_ID", "pred_speed"]].rename(columns={"pred_speed": "speed_model_a"}), on="LINK_ID", how="left")

    # 2) 이웃 속도 Lookup 매핑
    if NEIGHBOR_LOOKUP_PATH.exists():
        nb_lookup = pd.read_parquet(NEIGHBOR_LOOKUP_PATH)
        nb_match = nb_lookup[(nb_lookup["시간코드"] == time_code_key) & (nb_lookup["is_weekend"] == is_weekend)]
        snapshot_df = snapshot_df.merge(nb_match[["LINK_ID", "neighbor_speed_bucket"]], on="LINK_ID", how="left")
    else:
        snapshot_df["neighbor_speed_bucket"] = np.nan

    # 3) 모델 필수 피처 자동 보완 (누락된 컬럼 NaN/기본값 자동 생성)
    cat_cols = artifact_nb.get("categorical_cols", [])

    def prepare_inference_matrix(df: pd.DataFrame, model_xgb, feature_cols: list) -> pd.DataFrame:
        """
        XGBoost C++ 엔진 서빙 시 요구되는 엄격한 피처 순서, 타입, 범주 인덱스를 정렬합니다.
        - 누락 컬럼 NaN 보완
        - dow(요일) 피처의 Native CategoricalDtype(32비트) 스키마 복제
        - 수치형 피처 float32 변환
        - C++ Booster 컬럼 순서 일치
        """
        X = pd.DataFrame(index=df.index)
        
        booster = model_xgb.get_booster()
        booster_features = booster.feature_names
        # 입력받은 tm의 진짜 주간 범위(월~일)를 기반으로 32비트 범주 Dtype 메타데이터 생성
        target_monday = dt - pd.Timedelta(days=dt.weekday())
        dow_dtype = pd.date_range(target_monday, periods=7).weekday.astype("category").dtype
        
        for col in feature_cols:
            if col not in df.columns:
                df[col] = np.nan
            
            if col == "dow":
                # 요일 피처: int32 기반 Native CategoricalDtype 캐스팅
                X[col] = df[col].fillna(0).astype(int).astype(dow_dtype)
            elif col in cat_cols:
                # 일반 범주형 변수 (문자열 기반)
                X[col] = df[col].astype(str).astype("category")
            else:
                # 수치형 피처: 명시적 float32 캐스팅
                X[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")
                
        # 모델 학습 당시 컬럼 순서대로 재배열
        if booster_features:
            for b_col in booster_features:
                if b_col not in X.columns:
                    X[b_col] = np.nan
            X = X[booster_features]
            
        return X

    # Model B / Model C 입력 행렬 생성
    X_nb = prepare_inference_matrix(snapshot_df, artifact_nb["model"], nb_features)
    X_stat = prepare_inference_matrix(snapshot_df, artifact_stat["model"], stat_features)

    # 모델 추론 수행
    pred_nb = artifact_nb["model"].predict(X_nb)
    pred_stat = artifact_stat["model"].predict(X_stat)

    # 물리적 속도 한계 제약 적용 (최대 속도 및 도로 최소 안전 속도)
    max_spd = snapshot_df["MAX_SPD"].to_numpy()
    pred_nb_clipped = np.clip(pred_nb, SPEED_FLOOR_KMH, max_spd)
    pred_stat_clipped = np.clip(pred_stat, SPEED_FLOOR_KMH, max_spd)

    # 5. 계층 분기(Tier Assignment) 및 최종 속도/통행시간 결정
    has_model_a = snapshot_df["speed_model_a"].notna()
    has_neighbor = snapshot_df["neighbor_speed_bucket"].notna()

    snapshot_df["tier"] = np.select(
        [has_model_a, has_neighbor],
        ["A 관측/이력", "B 미관측·이웃있음"],
        default="C 미관측·이웃없음"
    )
    
    snapshot_df["speed_kmh"] = np.select(
        [has_model_a, has_neighbor],
        [snapshot_df["speed_model_a"], pred_nb_clipped],
        default=pred_stat_clipped
    )
    
    snapshot_df["speed_source"] = np.select(
        [has_model_a, has_neighbor],
        ["model_a_lookup", "model_b_xgb_neighbor"],
        default="model_c_xgb_static"
    )

    # 속도(km/h) 기반 통행시간(초) 산출: length_m / 1000 / speed_kmh * 3600
    snapshot_df["travel_time_sec"] = snapshot_df["LENGTH"] / 1000.0 / snapshot_df["speed_kmh"] * 3600.0

    # 6. 최종 스냅샷 파일 저장
    print("[3/3] 결과 저장...")
    keep_cols = [
        "LINK_ID", "F_NODE", "T_NODE", "LENGTH", "MAX_SPD", "ROAD_RANK", 
        "slope_pct", "precip_mm", "tier", "speed_kmh", "speed_source", "travel_time_sec"
    ]
    
    SPEED_SNAPSHOT_DIR = PROCESSED_DIR / "seoul_all_link_speed"
    SPEED_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    
    out_path = SPEED_SNAPSHOT_DIR / f"seoul_all_link_speed_{args.tm}.csv"
    output_df = snapshot_df[[c for c in keep_cols if c in snapshot_df.columns]]
    output_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print()
    print("✅ 전체 링크 속도 스냅샷 초고속 생성 완료:", out_path)
    print("계층 구성 요약:")
    print(snapshot_df["tier"].value_counts().to_string())
    print(f"전체 평균 속도: {snapshot_df['speed_kmh'].mean():.1f} km/h")


if __name__ == "__main__":
    main()