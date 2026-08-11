"""335개 시간대 전 링크 속도·VT-CPEM 에너지 결과의 재현 가능한 EDA.

대용량 Parquet을 한 파일씩 읽어 전체 2,128만 링크-시간 행을 메모리에 올리지 않는다.
결과는 data/processed/eda_summary/와 docs/figures/speed_energy_eda/에 저장한다.
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENERGY_DIR = PROJECT_ROOT / "data" / "processed" / "link_energy"
DIMENSION_PATH = PROJECT_ROOT / "data" / "processed" / "seoul_link_dimension.csv"
LINK_SHP = PROJECT_ROOT / "data" / "interim" / "seoul_link.shp"
SUMMARY_DIR = PROJECT_ROOT / "data" / "processed" / "eda_summary"
FIGURE_DIR = PROJECT_ROOT / "docs" / "figures" / "speed_energy_eda"
FILE_PATTERN = re.compile(r"link_energy_(\d{12})\.parquet$")

SPEED_BINS = [0, 10, 20, 30, 40, 60, 80, np.inf]
SPEED_LABELS = ["0-10", "10-20", "20-30", "30-40", "40-60", "60-80", "80+"]
SLOPE_BINS = [-np.inf, -6, -3, -1, 1, 3, 6, np.inf]
SLOPE_LABELS = ["<=-6%", "-6--3%", "-3--1%", "-1-1%", "1-3%", "3-6%", ">=6%"]
RAIN_BINS = [-np.inf, 0, 1, 5, 10, np.inf]
RAIN_LABELS = ["0", "0-1", "1-5", "5-10", "10+"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="전 링크 속도·에너지 EDA")
    parser.add_argument("--start-date", default="20260707")
    parser.add_argument("--end-date", default="20260720")
    parser.add_argument("--skip-maps", action="store_true")
    return parser.parse_args()


def input_files(start_date: str, end_date: str) -> list[tuple[str, Path]]:
    start = pd.to_datetime(start_date, format="%Y%m%d")
    end = pd.to_datetime(end_date, format="%Y%m%d") + pd.Timedelta(hours=23)
    selected = []
    for path in sorted(ENERGY_DIR.glob("link_energy_*.parquet")):
        match = FILE_PATTERN.match(path.name)
        if match is None:
            continue
        tm = match.group(1)
        timestamp = pd.to_datetime(tm, format="%Y%m%d%H%M")
        if start <= timestamp <= end:
            selected.append((tm, path))
    return selected


def add_bins(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["speed_bin"] = pd.cut(out["speed_kmh"], SPEED_BINS, labels=SPEED_LABELS, right=False)
    out["slope_bin"] = pd.cut(out["slope_pct_used"], SLOPE_BINS, labels=SLOPE_LABELS, include_lowest=True)
    out["rain_bin"] = pd.cut(out["precip_mm"], RAIN_BINS, labels=RAIN_LABELS, include_lowest=True)
    return out


def grouped_mean(frame: pd.DataFrame, by: list[str], value_cols: list[str]) -> pd.DataFrame:
    agg = {"LINK_ID": "size"}
    agg.update({column: "sum" for column in value_cols})
    return frame.groupby(by, observed=True).agg(agg).rename(columns={"LINK_ID": "n"}).reset_index()


def combine_weighted(parts: list[pd.DataFrame], keys: list[str], values: list[str]) -> pd.DataFrame:
    merged = pd.concat(parts, ignore_index=True).groupby(keys, observed=True)[["n", *values]].sum().reset_index()
    for column in values:
        merged[f"mean_{column}"] = merged[column] / merged["n"]
    return merged


def save_fig(name: str) -> None:
    plt.tight_layout()
    plt.savefig(FIGURE_DIR / name, dpi=170, bbox_inches="tight")
    plt.close()


def make_figures(hourly: pd.DataFrame, tier_hourly: pd.DataFrame, joint: pd.DataFrame,
                 slope: pd.DataFrame, rain: pd.DataFrame, sample: pd.DataFrame,
                 link_summary: pd.DataFrame, skip_maps: bool) -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    hourly["datetime"] = pd.to_datetime(hourly["tm"], format="%Y%m%d%H%M")

    fig, ax1 = plt.subplots(figsize=(12, 4.5))
    ax1.plot(hourly["datetime"], hourly["network_speed_kmh"], color="#1976d2", label="Network speed")
    ax1.set_ylabel("Network speed (km/h)", color="#1976d2")
    ax2 = ax1.twinx()
    ax2.plot(hourly["datetime"], hourly["network_wh_per_km"], color="#e65100", label="Energy intensity")
    ax2.set_ylabel("Network energy (Wh/km)", color="#e65100")
    ax1.set_title("Hourly network speed and energy intensity")
    ax1.set_xlabel("Time")
    save_fig("01_hourly_speed_energy.png")

    heat = hourly.assign(date=hourly["datetime"].dt.strftime("%m-%d"), hour=hourly["datetime"].dt.hour)
    pivot = heat.pivot(index="date", columns="hour", values="network_speed_kmh")
    plt.figure(figsize=(12, 5))
    plt.imshow(pivot, aspect="auto", cmap="YlGnBu")
    plt.colorbar(label="Network speed (km/h)")
    plt.xticks(range(24), range(24))
    plt.yticks(range(len(pivot.index)), pivot.index)
    plt.xlabel("Hour")
    plt.ylabel("Date")
    plt.title("Date-hour network speed heatmap")
    save_fig("02_speed_date_hour_heatmap.png")

    tier_hourly["datetime"] = pd.to_datetime(tier_hourly["tm"], format="%Y%m%d%H%M")
    plt.figure(figsize=(12, 4.5))
    for tier, group in tier_hourly.groupby("tier", observed=True):
        plt.plot(group["datetime"], group["mean_speed_kmh"], label=tier)
    plt.legend(title="Speed source tier")
    plt.ylabel("Mean speed (km/h)")
    plt.xlabel("Time")
    plt.title("Hourly speed by A/B/C tier")
    save_fig("03_tier_speed_time_series.png")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for tier, group in sample.groupby("tier", observed=True):
        axes[0].hist(group["speed_kmh"], bins=50, alpha=0.35, density=True, label=tier)
        axes[1].hist(np.log1p(group["energy_ev_wh"]), bins=50, alpha=0.35, density=True, label=tier)
    axes[0].set_title("Speed distribution")
    axes[0].set_xlabel("Speed (km/h)")
    axes[1].set_title("Energy distribution")
    axes[1].set_xlabel("log(1 + Wh per link)")
    axes[1].legend(title="Tier")
    save_fig("04_speed_energy_distributions_by_tier.png")

    pivot_joint = joint.pivot(index="slope_bin", columns="speed_bin", values="mean_energy_wh_per_km").reindex(SLOPE_LABELS)
    plt.figure(figsize=(10, 5))
    plt.imshow(pivot_joint, aspect="auto", cmap="magma")
    plt.colorbar(label="Mean energy intensity (Wh/km)")
    plt.xticks(range(len(SPEED_LABELS)), SPEED_LABELS)
    plt.yticks(range(len(SLOPE_LABELS)), SLOPE_LABELS)
    plt.xlabel("Speed bin (km/h)")
    plt.ylabel("Slope bin")
    plt.title("Energy intensity by speed and slope")
    save_fig("05_energy_speed_slope_heatmap.png")

    slope = slope.reindex(pd.Categorical(slope["slope_bin"], categories=SLOPE_LABELS, ordered=True).argsort()).reset_index(drop=True)
    plt.figure(figsize=(10, 4.5))
    plt.plot(slope["slope_bin"].astype(str), slope["mean_energy_wh_per_km"], marker="o", label="Energy intensity")
    plt.ylabel("Mean Wh/km")
    plt.xlabel("Slope bin")
    plt.title("Energy intensity by slope")
    plt.xticks(rotation=25)
    save_fig("06_energy_by_slope.png")

    component_cols = ["mean_rolling_force_n", "mean_grade_force_n", "mean_aero_force_n"]
    plt.figure(figsize=(10, 4.5))
    for col, label in zip(component_cols, ["Rolling", "Grade", "Aerodynamic"]):
        plt.plot(slope["slope_bin"].astype(str), slope[col], marker="o", label=label)
    plt.axhline(0, color="black", linewidth=0.7)
    plt.ylabel("Mean force (N)")
    plt.xlabel("Slope bin")
    plt.title("Resistance-force components by slope")
    plt.xticks(rotation=25)
    plt.legend()
    save_fig("07_force_components_by_slope.png")

    rain_plot = rain.copy()
    plt.figure(figsize=(10, 4.5))
    for tier, group in rain_plot.groupby("tier", observed=True):
        plt.plot(group["rain_bin"].astype(str), group["mean_speed_kmh"], marker="o", label=tier)
    plt.xlabel("Rain bin (mm)")
    plt.ylabel("Mean speed (km/h)")
    plt.title("Predicted speed by rain bin and tier")
    plt.legend(title="Tier")
    save_fig("08_rain_speed_by_tier.png")

    plt.figure(figsize=(7, 5))
    plotted = sample.sample(min(len(sample), 50_000), random_state=42)
    plt.scatter(plotted["speed_kmh"], plotted["energy_wh_per_km"], c=plotted["slope_pct_used"],
                cmap="coolwarm", s=2, alpha=0.25, vmin=-12, vmax=12)
    plt.colorbar(label="Slope used (%)")
    plt.ylim(0, plotted["energy_wh_per_km"].quantile(0.995))
    plt.xlabel("Speed (km/h)")
    plt.ylabel("Energy intensity (Wh/km)")
    plt.title("Speed-energy relationship, coloured by slope")
    save_fig("09_speed_energy_scatter.png")

    if skip_maps or not LINK_SHP.exists():
        return
    geometry = gpd.read_file(LINK_SHP)[["LINK_ID", "geometry"]]
    geometry["LINK_ID"] = geometry["LINK_ID"].astype(str)
    mapped = geometry.merge(link_summary.reset_index(), on="LINK_ID", how="inner")
    for column, title, filename, cmap in [
        ("speed_mean_kmh", "Mean predicted speed", "10_map_mean_speed.png", "YlGnBu"),
        ("energy_mean_wh_per_km", "Mean energy intensity", "11_map_energy_intensity.png", "magma"),
    ]:
        fig, ax = plt.subplots(figsize=(9, 9))
        vmax = mapped[column].quantile(0.99)
        mapped.plot(column=column, ax=ax, cmap=cmap, linewidth=0.18, legend=True, vmin=0, vmax=vmax)
        ax.set_axis_off()
        ax.set_title(title + " (99th percentile clipped for display)")
        save_fig(filename)


def main() -> None:
    args = parse_args()
    files = input_files(args.start_date, args.end_date)
    if not files:
        raise SystemExit("선택 기간의 링크 에너지 파일이 없습니다.")
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    dimension = pd.read_csv(DIMENSION_PATH, usecols=["LINK_ID", "ROAD_RANK"], dtype={"LINK_ID": str}, encoding="utf-8-sig").set_index("LINK_ID")
    first = pd.read_parquet(files[0][1], columns=["LINK_ID"])
    link_ids = first["LINK_ID"].astype(str).to_numpy()
    link_summary = pd.DataFrame(index=pd.Index(link_ids, name="LINK_ID"))
    for col in ["speed_sum", "speed_sq_sum", "energy_sum", "whkm_sum", "time_sum", "precip_sum"]:
        link_summary[col] = 0.0
    link_summary["speed_min"] = np.inf
    link_summary["speed_max"] = -np.inf
    link_summary["n"] = 0
    link_summary["ROAD_RANK"] = dimension.reindex(link_ids)["ROAD_RANK"].to_numpy()

    hourly_rows: list[dict] = []
    tier_parts: list[pd.DataFrame] = []
    joint_parts: list[pd.DataFrame] = []
    slope_parts: list[pd.DataFrame] = []
    rain_parts: list[pd.DataFrame] = []
    quality_rows: list[dict] = []
    sample_parts: list[pd.DataFrame] = []
    columns = [
        "LINK_ID", "LENGTH", "speed_kmh", "travel_time_sec", "slope_pct_used", "slope_outlier_flag",
        "precip_mm", "tier", "energy_ev_j", "energy_ev_wh", "energy_wh_per_km", "rolling_force_n",
        "grade_force_n", "aero_force_n", "wheel_power_w", "battery_power_w",
    ]

    for index, (tm, path) in enumerate(files, start=1):
        frame = pd.read_parquet(path, columns=columns)
        frame["LINK_ID"] = frame["LINK_ID"].astype(str)
        valid_ids = frame["LINK_ID"].to_numpy()
        if len(frame) != len(link_ids) or len(np.unique(valid_ids)) != len(link_ids):
            raise ValueError(f"링크 수 또는 LINK_ID 중복 오류: {path.name}")
        if not np.array_equal(valid_ids, link_ids):
            frame = frame.set_index("LINK_ID").reindex(link_ids).reset_index()

        quality_rows.append({
            "tm": tm, "rows": len(frame), "unique_links": frame["LINK_ID"].nunique(),
            "null_values": int(frame.isna().sum().sum()), "negative_energy": int((frame["energy_ev_j"] < 0).sum()),
            "slope_outliers": int(frame["slope_outlier_flag"].sum()),
        })
        length_sum = frame["LENGTH"].sum()
        travel_sum = frame["travel_time_sec"].sum()
        hourly_rows.append({
            "tm": tm, "links": len(frame), "speed_mean_kmh": frame["speed_kmh"].mean(),
            "speed_median_kmh": frame["speed_kmh"].median(), "network_speed_kmh": length_sum / travel_sum * 3.6,
            "energy_total_wh": frame["energy_ev_wh"].sum(), "energy_mean_wh": frame["energy_ev_wh"].mean(),
            "network_wh_per_km": frame["energy_ev_wh"].sum() / (length_sum / 1000.0),
            "rain_mean_mm": frame["precip_mm"].mean(), "rain_link_fraction": (frame["precip_mm"] > 0).mean(),
        })

        tier = grouped_mean(frame, ["tier"], ["speed_kmh", "energy_ev_wh", "energy_wh_per_km"])
        tier["tm"] = tm
        tier_parts.append(tier)
        binned = add_bins(frame)
        joint_parts.append(grouped_mean(binned, ["slope_bin", "speed_bin"], ["energy_wh_per_km"]))
        slope_parts.append(grouped_mean(binned, ["slope_bin"], ["energy_wh_per_km", "rolling_force_n", "grade_force_n", "aero_force_n"]))
        rain_parts.append(grouped_mean(binned, ["rain_bin", "tier"], ["speed_kmh", "energy_wh_per_km"]))

        mask = pd.util.hash_pandas_object(frame["LINK_ID"], index=False).to_numpy() % 100 == 0
        sample_parts.append(frame.loc[mask, ["speed_kmh", "energy_ev_wh", "energy_wh_per_km", "slope_pct_used", "tier", "precip_mm"]])
        values = frame.set_index("LINK_ID").reindex(link_ids)
        link_summary["speed_sum"] += values["speed_kmh"].to_numpy()
        link_summary["speed_sq_sum"] += np.square(values["speed_kmh"].to_numpy())
        link_summary["energy_sum"] += values["energy_ev_wh"].to_numpy()
        link_summary["whkm_sum"] += values["energy_wh_per_km"].to_numpy()
        link_summary["time_sum"] += values["travel_time_sec"].to_numpy()
        link_summary["precip_sum"] += values["precip_mm"].to_numpy()
        link_summary["speed_min"] = np.minimum(link_summary["speed_min"], values["speed_kmh"].to_numpy())
        link_summary["speed_max"] = np.maximum(link_summary["speed_max"], values["speed_kmh"].to_numpy())
        link_summary["n"] += 1
        if index % 24 == 0 or index == len(files):
            print(f"[{index}/{len(files)}] {tm} 집계 완료")

    hourly = pd.DataFrame(hourly_rows)
    quality = pd.DataFrame(quality_rows)
    tier_hourly = combine_weighted(tier_parts, ["tm", "tier"], ["speed_kmh", "energy_ev_wh", "energy_wh_per_km"])
    tier_hourly = tier_hourly.rename(columns={
        "mean_speed_kmh": "mean_speed_kmh", "mean_energy_ev_wh": "mean_energy_ev_wh",
        "mean_energy_wh_per_km": "mean_energy_wh_per_km",
    })
    joint = combine_weighted(joint_parts, ["slope_bin", "speed_bin"], ["energy_wh_per_km"])
    slope = combine_weighted(slope_parts, ["slope_bin"], ["energy_wh_per_km", "rolling_force_n", "grade_force_n", "aero_force_n"])
    rain = combine_weighted(rain_parts, ["rain_bin", "tier"], ["speed_kmh", "energy_wh_per_km"])
    sample = pd.concat(sample_parts, ignore_index=True)

    link_summary["speed_mean_kmh"] = link_summary["speed_sum"] / link_summary["n"]
    link_summary["speed_std_kmh"] = np.sqrt(np.maximum(link_summary["speed_sq_sum"] / link_summary["n"] - np.square(link_summary["speed_mean_kmh"]), 0))
    link_summary["speed_cv"] = link_summary["speed_std_kmh"] / link_summary["speed_mean_kmh"]
    link_summary["energy_mean_wh"] = link_summary["energy_sum"] / link_summary["n"]
    link_summary["energy_mean_wh_per_km"] = link_summary["whkm_sum"] / link_summary["n"]
    link_summary["travel_time_mean_sec"] = link_summary["time_sum"] / link_summary["n"]
    link_summary["precip_mean_mm"] = link_summary["precip_sum"] / link_summary["n"]
    link_summary = link_summary.drop(columns=["speed_sum", "speed_sq_sum", "energy_sum", "whkm_sum", "time_sum", "precip_sum"])

    hourly.to_csv(SUMMARY_DIR / "hourly_speed_energy_summary.csv", index=False, encoding="utf-8-sig")
    quality.to_csv(SUMMARY_DIR / "hourly_quality_summary.csv", index=False, encoding="utf-8-sig")
    tier_hourly.to_csv(SUMMARY_DIR / "hourly_tier_summary.csv", index=False, encoding="utf-8-sig")
    joint.to_csv(SUMMARY_DIR / "speed_slope_energy_summary.csv", index=False, encoding="utf-8-sig")
    slope.to_csv(SUMMARY_DIR / "slope_energy_summary.csv", index=False, encoding="utf-8-sig")
    rain.to_csv(SUMMARY_DIR / "rain_speed_energy_summary.csv", index=False, encoding="utf-8-sig")
    link_summary.to_parquet(SUMMARY_DIR / "link_speed_energy_summary.parquet", compression="zstd")
    sample.to_parquet(SUMMARY_DIR / "speed_energy_sample.parquet", index=False, compression="zstd")

    make_figures(hourly, tier_hourly, joint, slope, rain, sample, link_summary, args.skip_maps)
    print(f"완료: {len(files)}개 시간대 | 링크 요약 {len(link_summary):,}개 | 표본 {len(sample):,}행")


if __name__ == "__main__":
    main()
