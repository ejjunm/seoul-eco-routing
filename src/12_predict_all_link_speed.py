"""Create one all-link speed and travel-time snapshot for routing."""

from __future__ import annotations

import argparse
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
TRAIN_PATH = PROCESSED_DATA_DIR / "seoul_link_speed_dem_weather_merged.csv"
LINK_FEATURE_PATH = PROCESSED_DATA_DIR / "seoul_link_model_features.csv"

TARGET = "평균속도"
BASE_NUMERIC_FEATURES = [
    "LANES", "MAX_SPD", "LENGTH", "시간코드",
    "elev_start_m", "elev_mid_m", "elev_end_m", "elev_mean_m", "elev_min_m", "elev_max_m", "elev_delta_m",
    "slope_pct", "abs_slope_pct", "dem_sample_count", "precip_mm",
]
STATIC_NUMERIC_FEATURES = [
    "f_node_node_in_degree", "f_node_incoming_max_spd_mean", "f_node_incoming_lanes_mean",
    "f_node_node_out_degree", "f_node_outgoing_max_spd_mean", "f_node_outgoing_lanes_mean", "f_node_node_total_degree",
    "t_node_node_in_degree", "t_node_incoming_max_spd_mean", "t_node_incoming_lanes_mean",
    "t_node_node_out_degree", "t_node_outgoing_max_spd_mean", "t_node_outgoing_lanes_mean", "t_node_node_total_degree",
    "upstream_max_spd_mean", "downstream_max_spd_mean", "upstream_lanes_mean", "downstream_lanes_mean",
    "node_complexity", "downstream_speed_delta", "slope_pct_clipped", "slope_outlier_flag",
    "is_uphill", "is_downhill", "steep_uphill", "slope_length_m", "max_spd_x_lanes", "length_x_node_complexity",
]
DYNAMIC_NUMERIC_FEATURES = [
    "hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_morning_peak", "is_evening_peak",
    "is_rain", "log_precip", "rain_morning_peak", "rain_evening_peak", "rain_x_max_spd",
]
NUMERIC_FEATURES = BASE_NUMERIC_FEATURES + STATIC_NUMERIC_FEATURES + DYNAMIC_NUMERIC_FEATURES
BASE_CATEGORICAL = ["ROAD_RANK", "ROAD_TYPE", "ROAD_USE", "MULTI_LINK", "CONNECT", "REST_VEH", "REST_W", "REST_H", "C-ITS"]
CATEGORICAL_FEATURES = BASE_CATEGORICAL + ["weekday", "is_weekend", "peak_period", "rain_class"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tm", required=True, help="예측 시각 YYYYMMDDHHMM")
    parser.add_argument("--train-end", required=True, help="학습 마지막 날짜 YYYYMMDD")
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--min-supported-sections", type=int, default=20)
    return parser.parse_args()


def add_calendar_features(df: pd.DataFrame, date_value: str, hour: int) -> pd.DataFrame:
    result = df.copy()
    date = pd.Timestamp(date_value)
    result["시간코드"] = hour
    result["weekday"] = date.weekday()
    result["is_weekend"] = int(date.weekday() >= 5)
    result["peak_period"] = "morning" if hour in (7, 8, 9) else "evening" if hour in (17, 18, 19) else "off_peak"
    result["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    result["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    result["dow_sin"] = np.sin(2 * np.pi * result["weekday"] / 7)
    result["dow_cos"] = np.cos(2 * np.pi * result["weekday"] / 7)
    result["is_morning_peak"] = int(hour in (7, 8, 9))
    result["is_evening_peak"] = int(hour in (17, 18, 19))
    result["is_rain"] = (result["precip_mm"] > 0).astype(int)
    result["log_precip"] = np.log1p(result["precip_mm"].clip(lower=0))
    result["rain_class"] = pd.cut(
        result["precip_mm"], bins=[-np.inf, 0, 1, 5, 10, np.inf],
        labels=["none", "light", "moderate", "heavy", "very_heavy"],
    ).astype(str)
    result["rain_morning_peak"] = result["is_rain"] * result["is_morning_peak"]
    result["rain_evening_peak"] = result["is_rain"] * result["is_evening_peak"]
    result["rain_x_max_spd"] = result["log_precip"] * result["MAX_SPD"]
    return result


def load_training_data(train_end: str) -> pd.DataFrame:
    usecols = BASE_NUMERIC_FEATURES + BASE_CATEGORICAL + ["LINK_ID", TARGET, "sample_weight", "source_section_id", "기준일"]
    dtype = {column: str for column in BASE_CATEGORICAL + ["LINK_ID", "source_section_id", "기준일"]}
    train = pd.read_csv(TRAIN_PATH, usecols=usecols, dtype=dtype, encoding="utf-8-sig")
    train = train[train["기준일"] <= train_end].copy()
    for column in BASE_NUMERIC_FEATURES + [TARGET, "sample_weight"]:
        train[column] = pd.to_numeric(train[column], errors="coerce")
    static = pd.read_csv(LINK_FEATURE_PATH, dtype={"LINK_ID": str}, encoding="utf-8-sig")
    train = train.merge(static, on="LINK_ID", how="left", validate="many_to_one")
    for column in STATIC_NUMERIC_FEATURES:
        train[column] = pd.to_numeric(train[column], errors="coerce")
    dates = pd.to_datetime(train["기준일"], format="%Y%m%d", errors="coerce")
    train["weekday"] = dates.dt.weekday.astype("Int64")
    train["is_weekend"] = (dates.dt.weekday >= 5).astype("Int64")
    hours = train["시간코드"].astype("Int64")
    train["peak_period"] = np.select(
        [hours.isin([7, 8, 9]), hours.isin([17, 18, 19])], ["morning", "evening"], default="off_peak"
    )
    train["hour_sin"] = np.sin(2 * np.pi * hours / 24)
    train["hour_cos"] = np.cos(2 * np.pi * hours / 24)
    train["dow_sin"] = np.sin(2 * np.pi * train["weekday"] / 7)
    train["dow_cos"] = np.cos(2 * np.pi * train["weekday"] / 7)
    train["is_morning_peak"] = hours.isin([7, 8, 9]).astype(int)
    train["is_evening_peak"] = hours.isin([17, 18, 19]).astype(int)
    train["is_rain"] = (train["precip_mm"] > 0).astype(int)
    train["log_precip"] = np.log1p(train["precip_mm"].clip(lower=0))
    train["rain_class"] = pd.cut(
        train["precip_mm"], bins=[-np.inf, 0, 1, 5, 10, np.inf],
        labels=["none", "light", "moderate", "heavy", "very_heavy"],
    ).astype(str)
    train["rain_morning_peak"] = train["is_rain"] * train["is_morning_peak"]
    train["rain_evening_peak"] = train["is_rain"] * train["is_evening_peak"]
    train["rain_x_max_spd"] = train["log_precip"] * train["MAX_SPD"]
    train = train.dropna(subset=NUMERIC_FEATURES + CATEGORICAL_FEATURES + [TARGET, "sample_weight", "source_section_id"])
    for column in CATEGORICAL_FEATURES:
        train[column] = train[column].astype("category")
    return train


def build_fallback_speed(train: pd.DataFrame, snapshot: pd.DataFrame) -> pd.Series:
    ratio = (train[TARGET] / train["MAX_SPD"]).clip(lower=0.05, upper=1.2)
    work = train.assign(speed_ratio=ratio)
    target_hour = int(snapshot["시간코드"].iloc[0])
    target_weekday = int(snapshot["weekday"].iloc[0])
    same_time = work[(work["시간코드"] == target_hour) & (work["weekday"] == target_weekday)]
    if same_time.empty:
        same_time = work[work["시간코드"] == target_hour]
    ratio_by_combo = same_time.groupby(["ROAD_RANK", "MAX_SPD"], observed=True)["speed_ratio"].mean()
    ratio_by_rank = same_time.groupby("ROAD_RANK", observed=True)["speed_ratio"].mean()
    global_ratio = float(same_time["speed_ratio"].mean())
    combo_index = pd.MultiIndex.from_frame(snapshot[["ROAD_RANK", "MAX_SPD"]])
    ratio_value = pd.Series(combo_index.map(ratio_by_combo), index=snapshot.index, dtype=float)
    ratio_value = ratio_value.fillna(snapshot["ROAD_RANK"].map(ratio_by_rank)).fillna(global_ratio)
    return (snapshot["MAX_SPD"] * ratio_value).clip(lower=3.0, upper=snapshot["MAX_SPD"])


def main() -> None:
    args = parse_args()
    if len(args.tm) != 12 or not args.tm.isdigit():
        raise SystemExit("--tm은 YYYYMMDDHHMM 형식이어야 합니다.")
    date_value, hour = args.tm[:8], int(args.tm[8:10])
    snapshot_path = PROCESSED_DATA_DIR / f"seoul_all_link_weather_{args.tm}.csv"
    if not snapshot_path.exists():
        raise SystemExit(f"먼저 기상 스냅샷을 생성하세요: {snapshot_path}")

    train = load_training_data(args.train_end)
    snapshot = pd.read_csv(snapshot_path, dtype={column: str for column in BASE_CATEGORICAL + ["LINK_ID"]}, encoding="utf-8-sig")
    static = pd.read_csv(LINK_FEATURE_PATH, dtype={"LINK_ID": str}, encoding="utf-8-sig")
    snapshot = snapshot.merge(static, on="LINK_ID", how="left", validate="one_to_one")
    snapshot = add_calendar_features(snapshot, date_value, hour)
    for column in NUMERIC_FEATURES:
        snapshot[column] = pd.to_numeric(snapshot[column], errors="coerce")
    if snapshot[NUMERIC_FEATURES].isna().any().any():
        raise SystemExit("전체 링크 스냅샷에 모델 피처 결측이 있습니다.")
    unseen_category = pd.Series(False, index=snapshot.index)
    for column in CATEGORICAL_FEATURES:
        train_categories = pd.Index(train[column].cat.categories.astype(str))
        snapshot_values = snapshot[column].astype(str)
        unseen_category |= ~snapshot_values.isin(train_categories)
        categories = train_categories.union(pd.Index(snapshot_values.dropna().unique()))
        snapshot[column] = pd.Categorical(snapshot_values, categories=categories)

    features = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    model = lgb.LGBMRegressor(
        objective="regression", n_estimators=args.n_estimators, learning_rate=0.05,
        num_leaves=63, random_state=42, n_jobs=-1, verbosity=-1,
    )
    model.fit(train[features], train[TARGET], sample_weight=train["sample_weight"], categorical_feature=CATEGORICAL_FEATURES)
    model_speed = pd.Series(model.predict(snapshot[features]), index=snapshot.index).clip(lower=3.0, upper=snapshot["MAX_SPD"])

    support = train.groupby(["ROAD_RANK", "MAX_SPD"], observed=True)["source_section_id"].nunique()
    support_index = pd.MultiIndex.from_frame(snapshot[["ROAD_RANK", "MAX_SPD"]])
    support_count = pd.Series(support_index.map(support), index=snapshot.index).fillna(0).astype(int)
    fallback_speed = build_fallback_speed(train, snapshot)

    observed = pd.read_csv(
        TRAIN_PATH,
        usecols=["LINK_ID", "기준일", "시간코드", TARGET],
        dtype={"LINK_ID": str, "기준일": str},
        encoding="utf-8-sig",
    )
    observed["시간코드"] = pd.to_numeric(observed["시간코드"], errors="coerce")
    observed = observed[(observed["기준일"] == date_value) & (observed["시간코드"] == hour)]
    observed = observed[["LINK_ID", TARGET]].drop_duplicates("LINK_ID").rename(columns={TARGET: "observed_speed_kmh"})
    result = snapshot.merge(observed, on="LINK_ID", how="left")
    result["model_speed_kmh"] = model_speed.to_numpy()
    result["fallback_speed_kmh"] = fallback_speed.to_numpy()
    result["support_section_count"] = support_count.to_numpy()
    is_observed = result["observed_speed_kmh"].notna()
    is_supported = (result["support_section_count"] >= args.min_supported_sections) & ~unseen_category.to_numpy()
    result["speed_kmh"] = np.select(
        [is_observed, is_supported],
        [result["observed_speed_kmh"], result["model_speed_kmh"]],
        default=result["fallback_speed_kmh"],
    )
    result["speed_source"] = np.select(
        [is_observed, is_supported],
        ["official_observed", "static_model"],
        default="hierarchical_fallback",
    )
    result["prediction_confidence"] = np.select(
        [is_observed, is_supported], ["high", "medium"], default="low"
    )
    result["travel_time_sec"] = result["LENGTH"] / 1000 / result["speed_kmh"] * 3600

    out_path = PROCESSED_DATA_DIR / f"seoul_all_link_speed_{args.tm}.csv"
    result.to_csv(out_path, index=False, encoding="utf-8-sig")
    print("전체 링크 속도 스냅샷 저장:", out_path)
    print(result["speed_source"].value_counts().to_string())
    print("학습에 없던 범주값 링크:", int(unseen_category.sum()))
    print("통행시간 결측:", int(result["travel_time_sec"].isna().sum()))


if __name__ == "__main__":
    main()
