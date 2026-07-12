from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
EDA_DIR = PROCESSED_DATA_DIR / "eda"

INPUT_PATH = PROCESSED_DATA_DIR / "seoul_link_speed_dem_weather_merged.csv"


def summarize(grouped: pd.core.groupby.generic.DataFrameGroupBy) -> pd.DataFrame:
    return (
        grouped["평균속도"]
        .agg(row_count="count", mean_speed="mean", median_speed="median", std_speed="std")
        .reset_index()
        .assign(
            mean_speed=lambda df: df["mean_speed"].round(2),
            median_speed=lambda df: df["median_speed"].round(2),
            std_speed=lambda df: df["std_speed"].round(2),
        )
    )


def add_bins(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["rain_flag"] = np.where(work["precip_mm"] > 0, "rain", "no_rain")
    work["rain_bin"] = pd.cut(
        work["precip_mm"],
        bins=[-0.001, 0, 1, 5, 10, np.inf],
        labels=["0mm", "0-1mm", "1-5mm", "5-10mm", "10mm+"],
        include_lowest=True,
    )
    work["abs_slope_bin"] = pd.cut(
        work["abs_slope_pct"],
        bins=[-0.001, 1, 3, 5, 10, np.inf],
        labels=["0-1%", "1-3%", "3-5%", "5-10%", "10%+"],
        include_lowest=True,
    )
    work["slope_direction"] = pd.cut(
        work["slope_pct"],
        bins=[-np.inf, -1, 1, np.inf],
        labels=["downhill", "flat", "uphill"],
    )
    work["slope_risk"] = np.where(work["abs_slope_pct"] >= 5, "steep", "not_steep")
    work["rain_slope_group"] = work["rain_flag"] + " + " + work["slope_risk"]
    return work


def save_table(df: pd.DataFrame, name: str) -> None:
    path = EDA_DIR / name
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\n{name}")
    print(df.to_string(index=False))


def main() -> None:
    EDA_DIR.mkdir(parents=True, exist_ok=True)

    usecols = [
        "평균속도",
        "precip_mm",
        "slope_pct",
        "abs_slope_pct",
        "elev_mean_m",
        "elev_delta_m",
        "ROAD_RANK",
        "MAX_SPD",
        "LENGTH",
        "시간코드",
        "첨두시구분(T1/T2/T3:오전/낮/오후)",
    ]
    df = pd.read_csv(INPUT_PATH, usecols=usecols, encoding="utf-8-sig")
    df["평균속도"] = pd.to_numeric(df["평균속도"], errors="coerce")
    df["precip_mm"] = pd.to_numeric(df["precip_mm"], errors="coerce")
    df["slope_pct"] = pd.to_numeric(df["slope_pct"], errors="coerce")
    df["abs_slope_pct"] = pd.to_numeric(df["abs_slope_pct"], errors="coerce")
    df["elev_mean_m"] = pd.to_numeric(df["elev_mean_m"], errors="coerce")
    df["elev_delta_m"] = pd.to_numeric(df["elev_delta_m"], errors="coerce")

    df = df.dropna(subset=["평균속도", "precip_mm", "abs_slope_pct"])
    df = add_bins(df)

    save_table(summarize(df.groupby("rain_flag", observed=True)), "speed_by_rain_flag.csv")
    save_table(summarize(df.groupby("rain_bin", observed=True)), "speed_by_rain_bin.csv")
    save_table(summarize(df.groupby("abs_slope_bin", observed=True)), "speed_by_abs_slope_bin.csv")
    save_table(summarize(df.groupby("slope_direction", observed=True)), "speed_by_slope_direction.csv")
    save_table(summarize(df.groupby("rain_slope_group", observed=True)), "speed_by_rain_slope_group.csv")
    save_table(summarize(df.groupby(["ROAD_RANK", "rain_flag"], observed=True)), "speed_by_road_rank_rain.csv")
    save_table(
        summarize(df.groupby(["첨두시구분(T1/T2/T3:오전/낮/오후)", "rain_flag"], observed=True)),
        "speed_by_peak_rain.csv",
    )
    save_table(
        summarize(df.groupby(["ROAD_RANK", "abs_slope_bin"], observed=True)),
        "speed_by_road_rank_slope.csv",
    )

    corr_cols = ["평균속도", "precip_mm", "abs_slope_pct", "slope_pct", "elev_mean_m", "elev_delta_m", "MAX_SPD", "LENGTH"]
    corr = df[corr_cols].corr(numeric_only=True)["평균속도"].sort_values(ascending=False).reset_index()
    corr.columns = ["feature", "corr_with_avg_speed"]
    corr["corr_with_avg_speed"] = corr["corr_with_avg_speed"].round(4)
    save_table(corr, "speed_feature_correlations.csv")

    print("\nEDA output dir:", EDA_DIR)


if __name__ == "__main__":
    main()
