"""Evaluate a deployable link-speed model without broadcast-label leakage.

The model deliberately uses only fields available for every Seoul standard link.
T-data-only road codes and source identifiers are retained for grouping/weighting,
but are never used as model inputs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
INPUT_PATH = PROCESSED_DATA_DIR / "seoul_link_speed_dem_weather_merged.csv"
OUT_PATH = PROCESSED_DATA_DIR / "speed_model_evaluation.json"

TARGET = "평균속도"
WEIGHT = "sample_weight"
SOURCE_SECTION = "source_section_id"
SOURCE_OBSERVATION = "source_observation_id"
DATE = "기준일"

NUMERIC_FEATURES = [
    "LANES",
    "MAX_SPD",
    "LENGTH",
    "시간코드",
    "elev_start_m",
    "elev_mid_m",
    "elev_end_m",
    "elev_mean_m",
    "elev_min_m",
    "elev_max_m",
    "elev_delta_m",
    "slope_pct",
    "abs_slope_pct",
    "dem_sample_count",
    "precip_mm",
]
CATEGORICAL_FEATURES = [
    "ROAD_RANK",
    "ROAD_TYPE",
    "ROAD_USE",
    "MULTI_LINK",
    "CONNECT",
    "REST_VEH",
    "REST_W",
    "REST_H",
    "C-ITS",
    "weekday",
    "is_weekend",
    "peak_period",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-end", default="20260713")
    parser.add_argument("--test-start", default="20260715")
    parser.add_argument("--spatial-folds", type=int, default=5)
    parser.add_argument("--n-estimators", type=int, default=400)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--num-leaves", type=int, default=63)
    parser.add_argument("--random-state", type=int, default=42)
    return parser.parse_args()


def load_data() -> pd.DataFrame:
    usecols = (
        NUMERIC_FEATURES
        + ["ROAD_RANK", "ROAD_TYPE", "ROAD_USE", "MULTI_LINK", "CONNECT", "REST_VEH", "REST_W", "REST_H", "C-ITS"]
        + [TARGET, WEIGHT, SOURCE_SECTION, SOURCE_OBSERVATION, DATE]
    )
    dtype = {
        "ROAD_RANK": str,
        "ROAD_TYPE": str,
        "ROAD_USE": str,
        "MULTI_LINK": str,
        "CONNECT": str,
        "REST_VEH": str,
        "REST_W": str,
        "REST_H": str,
        "C-ITS": str,
        SOURCE_SECTION: str,
        SOURCE_OBSERVATION: str,
        DATE: str,
    }
    df = pd.read_csv(INPUT_PATH, usecols=usecols, dtype=dtype, encoding="utf-8-sig")

    for column in NUMERIC_FEATURES + [TARGET, WEIGHT]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    date = pd.to_datetime(df[DATE], format="%Y%m%d", errors="coerce")
    df["weekday"] = date.dt.weekday.astype("Int64")
    df["is_weekend"] = (date.dt.weekday >= 5).astype("Int64")
    hour = df["시간코드"].astype("Int64")
    df["peak_period"] = np.select(
        [hour.isin([7, 8, 9]), hour.isin([17, 18, 19])],
        ["morning", "evening"],
        default="off_peak",
    )

    required = NUMERIC_FEATURES + CATEGORICAL_FEATURES + [TARGET, WEIGHT, SOURCE_SECTION, SOURCE_OBSERVATION, DATE]
    before = len(df)
    df = df.dropna(subset=required).copy()
    if len(df) != before:
        print(f"결측 제거: {before:,} -> {len(df):,}")

    for column in CATEGORICAL_FEATURES:
        df[column] = df[column].astype("category")
    return df


def make_model(args: argparse.Namespace) -> lgb.LGBMRegressor:
    return lgb.LGBMRegressor(
        objective="regression",
        n_estimators=args.n_estimators,
        learning_rate=args.learning_rate,
        num_leaves=args.num_leaves,
        random_state=args.random_state,
        n_jobs=-1,
        verbosity=-1,
    )


def metrics(y_true: pd.Series, prediction: np.ndarray, weight: pd.Series) -> dict[str, float]:
    return {
        "rmse": float(mean_squared_error(y_true, prediction, sample_weight=weight) ** 0.5),
        "mae": float(mean_absolute_error(y_true, prediction, sample_weight=weight)),
        "r2": float(r2_score(y_true, prediction, sample_weight=weight)),
    }


def evaluate_split(
    df: pd.DataFrame,
    train_index: np.ndarray,
    test_index: np.ndarray,
    args: argparse.Namespace,
    label: str,
) -> tuple[dict[str, object], lgb.LGBMRegressor]:
    features = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    train = df.iloc[train_index]
    test = df.iloc[test_index]

    overlap = set(train[SOURCE_OBSERVATION]) & set(test[SOURCE_OBSERVATION])
    if overlap:
        raise RuntimeError(f"{label}: source observation leakage detected ({len(overlap):,} IDs)")

    model = make_model(args)
    model.fit(
        train[features],
        train[TARGET],
        sample_weight=train[WEIGHT],
        categorical_feature=CATEGORICAL_FEATURES,
    )
    prediction = model.predict(test[features])
    result: dict[str, object] = {
        "label": label,
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_source_sections": int(train[SOURCE_SECTION].nunique()),
        "test_source_sections": int(test[SOURCE_SECTION].nunique()),
        "source_observation_overlap": int(len(overlap)),
        **metrics(test[TARGET], prediction, test[WEIGHT]),
    }
    return result, model


def main() -> None:
    args = parse_args()
    df = load_data()
    print(f"입력 행: {len(df):,} | 원본 서비스링크: {df[SOURCE_SECTION].nunique():,}")
    print("모델 피처:", ", ".join(NUMERIC_FEATURES + CATEGORICAL_FEATURES))

    time_train = np.flatnonzero(df[DATE].to_numpy() <= args.train_end)
    time_test = np.flatnonzero(df[DATE].to_numpy() >= args.test_start)
    if not len(time_train) or not len(time_test):
        raise SystemExit("시간 분할 결과가 비어 있습니다. --train-end/--test-start를 확인하세요.")
    time_result, time_model = evaluate_split(df, time_train, time_test, args, "temporal_holdout")

    groups = df[SOURCE_SECTION]
    spatial_results: list[dict[str, object]] = []
    if args.spatial_folds == 1:
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=args.random_state)
    else:
        splitter = GroupKFold(n_splits=args.spatial_folds)
    for fold, (train_index, test_index) in enumerate(splitter.split(df, groups=groups), start=1):
        result, _ = evaluate_split(df, train_index, test_index, args, f"spatial_fold_{fold}")
        spatial_results.append(result)

    importance = pd.DataFrame(
        {
            "feature": time_model.feature_name_,
            "gain": time_model.booster_.feature_importance(importance_type="gain"),
        }
    ).sort_values("gain", ascending=False)
    importance["gain_share"] = importance["gain"] / importance["gain"].sum()

    summary = {
        "input_rows": int(len(df)),
        "input_source_sections": int(df[SOURCE_SECTION].nunique()),
        "feature_scope": "all_link_available_only",
        "excluded_tdata_only_features": ["도로구분코드", "도로방향구분코드", "도로코드", "LINK_ID", SOURCE_SECTION],
        "temporal_holdout": time_result,
        "spatial_holdout": spatial_results,
        "top_feature_gain": importance.head(15).to_dict("records"),
    }
    OUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n시간 일반화:", json.dumps(time_result, ensure_ascii=False))
    print("공간 일반화:")
    for result in spatial_results:
        print(json.dumps(result, ensure_ascii=False))
    print("평가 결과 저장:", OUT_PATH)


if __name__ == "__main__":
    main()
