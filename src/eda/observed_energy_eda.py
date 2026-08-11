"""EDA of VT-CPEM energy estimated with actual observed A-link speeds."""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBSERVED_DIR = PROJECT_ROOT / "data" / "processed" / "observed_speed_energy"
SUMMARY_DIR = PROJECT_ROOT / "data" / "processed" / "eda_summary" / "observed_energy"
FIGURE_DIR = PROJECT_ROOT / "docs" / "figures" / "observed_speed_energy_eda"
LINK_SHP = PROJECT_ROOT / "data" / "interim" / "seoul_link.shp"
DIMENSION_PATH = PROJECT_ROOT / "data" / "processed" / "seoul_link_dimension.csv"

SPEED_BINS = [0, 10, 20, 30, 40, 60, 80, np.inf]
SPEED_LABELS = ["0-10", "10-20", "20-30", "30-40", "40-60", "60-80", "80+"]
SLOPE_BINS = [-np.inf, -6, -3, -1, 1, 3, 6, np.inf]
SLOPE_LABELS = ["<=-6%", "-6--3%", "-3--1%", "-1-1%", "1-3%", "3-6%", ">=6%"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Observed-speed-based energy EDA")
    parser.add_argument("--skip-maps", action="store_true")
    return parser.parse_args()


def save_fig(filename: str) -> None:
    plt.tight_layout()
    plt.savefig(FIGURE_DIR / filename, dpi=180, bbox_inches="tight")
    plt.close()


def weighted(parts: list[pd.DataFrame], keys: list[str], columns: list[str]) -> pd.DataFrame:
    table = pd.concat(parts, ignore_index=True).groupby(keys, observed=True)[["n", *columns]].sum().reset_index()
    for column in columns:
        table[f"mean_{column}"] = table[column] / table["n"]
    return table


def main() -> None:
    args = parse_args()
    parts = sorted(OBSERVED_DIR.rglob("*.parquet"))
    if not parts:
        raise SystemExit(f"No observed-speed energy data found in {OBSERVED_DIR}")
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    hourly_parts: list[pd.DataFrame] = []
    joint_parts: list[pd.DataFrame] = []
    slope_parts: list[pd.DataFrame] = []
    rank_parts: list[pd.DataFrame] = []
    rain_peak_parts: list[pd.DataFrame] = []
    sample_parts: list[pd.DataFrame] = []
    dim_links = pd.read_csv(DIMENSION_PATH, usecols=["LINK_ID"], dtype={"LINK_ID": str}, encoding="utf-8-sig")["LINK_ID"].to_numpy()
    link_index = pd.Index(dim_links)
    link_speed_sum = np.zeros(len(dim_links), dtype=np.float64)
    link_energy_sum = np.zeros(len(dim_links), dtype=np.float64)
    link_whkm_sum = np.zeros(len(dim_links), dtype=np.float64)
    link_n = np.zeros(len(dim_links), dtype=np.int32)

    for i, path in enumerate(parts, start=1):
        frame = pd.read_parquet(path)
        frame["speed_bin"] = pd.cut(frame["observed_speed_kmh"], SPEED_BINS, labels=SPEED_LABELS, right=False)
        frame["slope_bin"] = pd.cut(frame["slope_pct_used"], SLOPE_BINS, labels=SLOPE_LABELS, include_lowest=True)
        frame["rain_bin"] = pd.cut(frame["precip_mm"], [-np.inf, 0, 1, 5, 10, np.inf],
                                    labels=["0", "0-1", "1-5", "5-10", "10+"], include_lowest=True)
        frame["peak_period"] = pd.cut(frame["hour"], [-1, 6, 9, 16, 19, 23],
                                      labels=["night", "am_peak", "day", "pm_peak", "evening"])
        for keys, values, store in [
            (["tm"], ["energy_ev_wh", "LENGTH", "travel_time_sec", "observed_speed_kmh"], hourly_parts),
            (["slope_bin", "speed_bin"], ["energy_wh_per_km"], joint_parts),
            (["slope_bin"], ["energy_wh_per_km", "rolling_force_n", "grade_force_n", "aero_force_n"], slope_parts),
            (["ROAD_RANK"], ["energy_ev_wh", "energy_wh_per_km", "observed_speed_kmh", "LENGTH"], rank_parts),
            (["rain_bin", "peak_period"], ["energy_wh_per_km", "observed_speed_kmh"], rain_peak_parts),
        ]:
            grouped = frame.groupby(keys, observed=True)[values].sum().reset_index()
            counts = frame.groupby(keys, observed=True).size().rename("n").reset_index()
            grouped = counts.merge(grouped, on=keys, how="inner", validate="one_to_one")
            store.append(grouped)
        mask = pd.util.hash_pandas_object(frame["LINK_ID"], index=False).to_numpy() % 100 == 17
        sample_parts.append(frame.loc[mask, ["observed_speed_kmh", "energy_ev_wh", "energy_wh_per_km", "slope_pct_used"]])

        link_pos = link_index.get_indexer(frame["LINK_ID"])
        np.add.at(link_speed_sum, link_pos, frame["observed_speed_kmh"].to_numpy())
        np.add.at(link_energy_sum, link_pos, frame["energy_ev_wh"].to_numpy())
        np.add.at(link_whkm_sum, link_pos, frame["energy_wh_per_km"].to_numpy())
        np.add.at(link_n, link_pos, 1)
        if i % 50 == 0 or i == len(parts):
            print(f"read {i}/{len(parts)} parquet parts")

    hourly = weighted(hourly_parts, ["tm"], ["energy_ev_wh", "LENGTH", "travel_time_sec", "observed_speed_kmh"])
    hourly["network_speed_kmh"] = hourly["LENGTH"] / hourly["travel_time_sec"] * 3.6
    hourly["network_wh_per_km"] = hourly["energy_ev_wh"] / (hourly["LENGTH"] / 1000.0)
    hourly = hourly.sort_values("tm")
    hourly["datetime"] = pd.to_datetime(hourly["tm"], format="%Y%m%d%H%M")
    joint = weighted(joint_parts, ["slope_bin", "speed_bin"], ["energy_wh_per_km"])
    slope = weighted(slope_parts, ["slope_bin"], ["energy_wh_per_km", "rolling_force_n", "grade_force_n", "aero_force_n"])
    rank = weighted(rank_parts, ["ROAD_RANK"], ["energy_ev_wh", "energy_wh_per_km", "observed_speed_kmh", "LENGTH"])
    rain_peak = weighted(rain_peak_parts, ["rain_bin", "peak_period"], ["energy_wh_per_km", "observed_speed_kmh"])
    for name, table in [("hourly_observed_energy", hourly), ("speed_slope_observed_energy", joint),
                        ("slope_observed_energy", slope), ("road_rank_observed_energy", rank),
                        ("rain_peak_observed_energy", rain_peak)]:
        table.to_csv(SUMMARY_DIR / f"{name}.csv", index=False, encoding="utf-8-sig")

    sample = pd.concat(sample_parts, ignore_index=True)
    sample.to_parquet(SUMMARY_DIR / "observed_speed_energy_sample.parquet", index=False, compression="zstd")
    link_summary = pd.DataFrame({"LINK_ID": dim_links, "speed_sum": link_speed_sum, "energy_sum": link_energy_sum,
                                 "whkm_sum": link_whkm_sum, "n": link_n})
    for column, source in [("observed_speed_mean_kmh", "speed_sum"), ("observed_energy_mean_wh", "energy_sum"),
                           ("observed_energy_mean_wh_per_km", "whkm_sum")]:
        link_summary[column] = link_summary[source] / link_summary["n"]
    link_summary.to_parquet(SUMMARY_DIR / "observed_energy_link_summary.parquet", index=False, compression="zstd")

    # 01: real observed speed, then energy inferred from that speed.
    fig, ax1 = plt.subplots(figsize=(12, 4.5))
    ax1.plot(hourly["datetime"], hourly["network_speed_kmh"], color="#1976d2")
    ax1.set_xlabel("Time"); ax1.set_ylabel("Observed network speed (km/h)", color="#1976d2")
    ax2 = ax1.twinx()
    ax2.plot(hourly["datetime"], hourly["network_wh_per_km"], color="#e65100")
    ax2.set_ylabel("Observed-speed-based energy (Wh/km)", color="#e65100")
    ax1.set_title("Observed speed and observed-speed-based estimated energy")
    save_fig("01_hourly_observed_speed_energy.png")

    heat = hourly.assign(date=hourly["datetime"].dt.strftime("%m-%d"), hour=hourly["datetime"].dt.hour)
    pivot = heat.pivot(index="date", columns="hour", values="network_wh_per_km")
    plt.figure(figsize=(12, 5)); plt.imshow(pivot, aspect="auto", cmap="magma")
    plt.colorbar(label="Observed-speed-based energy (Wh/km)")
    plt.xticks(range(24), range(24)); plt.yticks(range(len(pivot.index)), pivot.index)
    plt.xlabel("Hour"); plt.ylabel("Date"); plt.title("Date-hour energy intensity from observed speeds")
    save_fig("02_observed_energy_date_hour_heatmap.png")

    slope = slope.set_index("slope_bin").reindex(SLOPE_LABELS).reset_index()
    plt.figure(figsize=(9, 4.5)); plt.plot(slope["slope_bin"].astype(str), slope["mean_energy_wh_per_km"], marker="o")
    plt.xticks(rotation=25); plt.xlabel("Slope bin"); plt.ylabel("Mean Wh/km")
    plt.title("Observed-speed-based energy intensity by slope")
    save_fig("03_observed_energy_by_slope.png")

    pivot_joint = joint.pivot(index="slope_bin", columns="speed_bin", values="mean_energy_wh_per_km").reindex(SLOPE_LABELS)
    plt.figure(figsize=(10, 5)); plt.imshow(pivot_joint, aspect="auto", cmap="magma")
    plt.colorbar(label="Mean Wh/km")
    plt.xticks(range(len(SPEED_LABELS)), SPEED_LABELS); plt.yticks(range(len(SLOPE_LABELS)), SLOPE_LABELS)
    plt.xlabel("Observed speed bin (km/h)"); plt.ylabel("Slope bin")
    plt.title("Energy intensity by observed speed and slope")
    save_fig("04_observed_energy_speed_slope_heatmap.png")

    plt.figure(figsize=(9, 4.5))
    order = rank.sort_values("mean_energy_wh_per_km", ascending=False)
    plt.bar(order["ROAD_RANK"].astype(str), order["mean_energy_wh_per_km"], color="#f28e2b")
    plt.xlabel("ROAD_RANK"); plt.ylabel("Mean Wh/km")
    plt.title("Observed-speed-based energy intensity by road rank")
    save_fig("05_observed_energy_by_road_rank.png")

    plt.figure(figsize=(10, 4.5))
    for period, group in rain_peak.groupby("peak_period", observed=True):
        group = group.sort_values("rain_bin")
        plt.plot(group["rain_bin"].astype(str), group["mean_energy_wh_per_km"], marker="o", label=period)
    plt.xlabel("Hourly rain bin (mm)"); plt.ylabel("Mean Wh/km")
    plt.title("Observed-speed-based energy by rain and time period"); plt.legend(title="Period")
    save_fig("06_observed_energy_rain_peak.png")

    plt.figure(figsize=(8, 4.5))
    plt.hist(np.log1p(sample["energy_ev_wh"]), bins=70, color="#af7aa1")
    plt.xlabel("log(1 + Wh per link)"); plt.ylabel("Sampled link-hours")
    plt.title("Distribution of observed-speed-based link energy")
    save_fig("07_observed_link_energy_distribution.png")

    plotted = sample.sample(min(len(sample), 50_000), random_state=42)
    plt.figure(figsize=(7, 5))
    plt.scatter(plotted["observed_speed_kmh"], plotted["energy_wh_per_km"], c=plotted["slope_pct_used"],
                cmap="coolwarm", s=2, alpha=0.25, vmin=-12, vmax=12)
    plt.colorbar(label="Slope used (%)"); plt.ylim(0, plotted["energy_wh_per_km"].quantile(0.995))
    plt.xlabel("Observed speed (km/h)"); plt.ylabel("Energy intensity (Wh/km)")
    plt.title("Observed speed-energy relationship, coloured by slope")
    save_fig("08_observed_speed_energy_scatter.png")

    if not args.skip_maps and LINK_SHP.exists():
        geometry = gpd.read_file(LINK_SHP)[["LINK_ID", "geometry"]]
        geometry["LINK_ID"] = geometry["LINK_ID"].astype(str)
        mapped = geometry.merge(link_summary[["LINK_ID", "observed_energy_mean_wh_per_km"]], on="LINK_ID", how="inner")
        vmax = mapped["observed_energy_mean_wh_per_km"].quantile(0.99)
        fig, ax = plt.subplots(figsize=(9, 9))
        mapped.plot(column="observed_energy_mean_wh_per_km", ax=ax, cmap="magma", linewidth=0.18,
                    legend=True, vmin=0, vmax=vmax)
        ax.set_axis_off(); ax.set_title("Mean energy on observed A links (99th percentile clipped)")
        save_fig("09_map_observed_energy_intensity.png")

    print(f"Done: {len(parts)} parts | {len(hourly)} hours | {len(link_summary):,} observed links")


if __name__ == "__main__":
    main()
