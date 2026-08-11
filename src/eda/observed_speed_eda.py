"""EDA of raw hourly observed speeds (A-Observed), not A lookup predictions.

Input is the partitioned output of ``energy/03_compute_observed_speed_energy.py``.
It streams parquet parts so the 15M observed link-hour records are never loaded
at once.  Results are saved independently from predicted all-link EDA.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBSERVED_DIR = PROJECT_ROOT / "data" / "processed" / "observed_speed_energy"
DIMENSION_PATH = PROJECT_ROOT / "data" / "processed" / "seoul_link_dimension.csv"
LINK_SHP = PROJECT_ROOT / "data" / "interim" / "seoul_link.shp"
SUMMARY_DIR = PROJECT_ROOT / "data" / "processed" / "eda_summary" / "observed_speed"
FIGURE_DIR = PROJECT_ROOT / "docs" / "figures" / "observed_speed_eda"

RAIN_LABELS = ["0-1", "1-5", "5-10", "10+"]
SLOPE_BINS = [-np.inf, -6, -3, -1, 1, 3, 6, np.inf]
SLOPE_LABELS = ["<=-6%", "-6--3%", "-3--1%", "-1-1%", "1-3%", "3-6%", ">=6%"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Observed A-link speed EDA")
    parser.add_argument("--skip-maps", action="store_true")
    return parser.parse_args()


def save_fig(filename: str) -> None:
    plt.tight_layout()
    plt.savefig(FIGURE_DIR / filename, dpi=180, bbox_inches="tight")
    plt.close()


def aggregate_sum(frame: pd.DataFrame, keys: list[str], values: list[str]) -> pd.DataFrame:
    return frame.groupby(keys, observed=True)[values].agg(["sum", "count"]).reset_index()


def flatten_aggregate(parts: list[pd.DataFrame], keys: list[str], value: str = "observed_speed_kmh") -> pd.DataFrame:
    table = pd.concat(parts, ignore_index=True)
    summed = table.groupby(keys, observed=True)[[(value, "sum"), (value, "count")]].sum().reset_index()
    summed.columns = keys + ["speed_sum", "n"]
    summed["mean_speed_kmh"] = summed["speed_sum"] / summed["n"]
    return summed


def main() -> None:
    args = parse_args()
    parts = sorted(OBSERVED_DIR.rglob("*.parquet"))
    if not parts:
        raise SystemExit(f"No observed-speed energy parquet files found under {OBSERVED_DIR}")

    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    dim = pd.read_csv(DIMENSION_PATH, usecols=["LINK_ID", "ROAD_RANK"], dtype={"LINK_ID": str}, encoding="utf-8-sig")
    link_ids = dim["LINK_ID"].to_numpy()
    link_pos = pd.Index(link_ids)
    n_links = len(link_ids)
    link_speed_sum = np.zeros(n_links, dtype=np.float64)
    link_speed_n = np.zeros(n_links, dtype=np.int32)
    link_energy_sum = np.zeros(n_links, dtype=np.float64)
    link_whkm_sum = np.zeros(n_links, dtype=np.float64)

    hourly_parts: list[pd.DataFrame] = []
    hour_weekend_parts: list[pd.DataFrame] = []
    rank_parts: list[pd.DataFrame] = []
    limit_parts: list[pd.DataFrame] = []
    slope_rank_parts: list[pd.DataFrame] = []
    traffic_parts: list[pd.DataFrame] = []
    topology_parts: list[pd.DataFrame] = []
    sample_frames: list[pd.DataFrame] = []
    sample_count_hist: defaultdict[int, int] = defaultdict(int)

    # Same-link, same-hour, same weekend baseline.  This removes much of the
    # road-class and time-of-day composition bias from the rain comparison.
    key_count = n_links * 48
    dry_sum = np.zeros(key_count, dtype=np.float64)
    dry_n = np.zeros(key_count, dtype=np.int16)
    wet_sum = np.zeros(key_count * 4, dtype=np.float64)
    wet_n = np.zeros(key_count * 4, dtype=np.int16)

    for i, path in enumerate(parts, start=1):
        frame = pd.read_parquet(path)
        frame["ROAD_RANK"] = frame["ROAD_RANK"].astype(str)
        date_dt = pd.to_datetime(frame["date"], format="%Y%m%d")
        frame["is_weekend"] = (date_dt.dt.dayofweek >= 5).astype("int8")
        frame["peak_period"] = pd.cut(frame["hour"], bins=[-1, 6, 9, 16, 19, 23],
                                      labels=["night", "am_peak", "day", "pm_peak", "evening"])
        frame["limit_bin"] = pd.cut(frame["MAX_SPD"], bins=[0, 30, 50, 60, 80, np.inf],
                                    labels=["<=30", "31-50", "51-60", "61-80", "80+"])
        frame["slope_bin"] = pd.cut(frame["slope_pct_used"], SLOPE_BINS, labels=SLOPE_LABELS,
                                    include_lowest=True)
        frame["traffic_bin"] = pd.cut(frame["traffic_volume_hourly"], bins=[-np.inf, 250, 500, 1000, 2000, np.inf],
                                      labels=["<=250", "251-500", "501-1000", "1001-2000", "2000+"])
        frame["topology_bin"] = pd.cut(frame["node_complexity"], bins=[-np.inf, 2, 4, 6, 10, np.inf],
                                       labels=["<=2", "2-4", "4-6", "6-10", "10+"])

        hourly_parts.append(frame.groupby("tm", observed=True).agg(
            links=("LINK_ID", "size"), speed_sum=("observed_speed_kmh", "sum"),
            length_m=("LENGTH", "sum"), travel_time_sec=("travel_time_sec", "sum"),
            rain_sum_mm=("precip_mm", "sum"), rain_count=("precip_mm", "count"),
            sample_count_sum=("sample_count_5min", "sum"),
            sample_count_valid=("sample_count_5min", "count"),
        ).reset_index())
        hour_weekend_parts.append(aggregate_sum(frame, ["hour", "is_weekend"], ["observed_speed_kmh"]))
        rank_parts.append(aggregate_sum(frame, ["ROAD_RANK"], ["observed_speed_kmh"]))
        limit_parts.append(aggregate_sum(frame, ["limit_bin"], ["observed_speed_kmh"]))
        slope_rank_parts.append(aggregate_sum(frame, ["slope_bin", "ROAD_RANK"], ["observed_speed_kmh"]))
        traffic_parts.append(aggregate_sum(frame, ["traffic_bin", "peak_period"], ["observed_speed_kmh"]))
        topology_parts.append(aggregate_sum(frame, ["topology_bin"], ["observed_speed_kmh"]))

        pos = link_pos.get_indexer(frame["LINK_ID"])
        np.add.at(link_speed_sum, pos, frame["observed_speed_kmh"].to_numpy())
        np.add.at(link_speed_n, pos, 1)
        np.add.at(link_energy_sum, pos, frame["energy_ev_wh"].to_numpy())
        np.add.at(link_whkm_sum, pos, frame["energy_wh_per_km"].to_numpy())
        for count, n in frame["sample_count_5min"].value_counts().items():
            sample_count_hist[int(count)] += int(n)

        rain_bin = pd.cut(frame["precip_mm"], bins=[-np.inf, 0, 1, 5, 10, np.inf],
                          labels=[0, 1, 2, 3, 4], include_lowest=True).astype("int8").to_numpy()
        keys = pos * 48 + frame["hour"].to_numpy(dtype=np.int64) * 2 + frame["is_weekend"].to_numpy(dtype=np.int64)
        speed = frame["observed_speed_kmh"].to_numpy(dtype=np.float64)
        dry = rain_bin == 0
        np.add.at(dry_sum, keys[dry], speed[dry])
        np.add.at(dry_n, keys[dry], 1)
        wet = rain_bin > 0
        wet_keys = keys[wet] * 4 + (rain_bin[wet] - 1)
        np.add.at(wet_sum, wet_keys, speed[wet])
        np.add.at(wet_n, wet_keys, 1)

        # Deterministic 1% link sample for distributions/correlation; each
        # selected link contributes all its available hours.
        hash_mask = (pd.util.hash_pandas_object(frame["LINK_ID"], index=False).to_numpy() % 100 == 17)
        sample_frames.append(frame.loc[hash_mask, ["observed_speed_kmh", "MAX_SPD", "LENGTH", "slope_pct_used",
                                                    "precip_mm", "traffic_volume_hourly", "LANES", "node_complexity"]])
        if i % 50 == 0 or i == len(parts):
            print(f"read {i}/{len(parts)} parquet parts")

    hourly = pd.concat(hourly_parts, ignore_index=True).groupby("tm", as_index=False).sum(numeric_only=True)
    hourly["network_speed_kmh"] = hourly["length_m"] / hourly["travel_time_sec"] * 3.6
    hourly["mean_speed_kmh"] = hourly["speed_sum"] / hourly["links"]
    hourly["rain_mean_mm"] = hourly["rain_sum_mm"] / hourly["rain_count"]
    hourly["sample_count_mean"] = hourly["sample_count_sum"] / hourly["sample_count_valid"]
    hourly = hourly.drop(columns=["rain_sum_mm", "rain_count", "sample_count_sum", "sample_count_valid"])
    hourly = hourly.sort_values("tm")
    hourly["datetime"] = pd.to_datetime(hourly["tm"], format="%Y%m%d%H%M")
    hourly.to_csv(SUMMARY_DIR / "hourly_observed_speed_summary.csv", index=False, encoding="utf-8-sig")

    profile = flatten_aggregate(hour_weekend_parts, ["hour", "is_weekend"])
    rank = flatten_aggregate(rank_parts, ["ROAD_RANK"])
    limit = flatten_aggregate(limit_parts, ["limit_bin"])
    slope_rank = flatten_aggregate(slope_rank_parts, ["slope_bin", "ROAD_RANK"])
    traffic = flatten_aggregate(traffic_parts, ["traffic_bin", "peak_period"])
    topology = flatten_aggregate(topology_parts, ["topology_bin"])
    for name, table in [("hour_weekend_profile", profile), ("road_rank_speed", rank),
                        ("limit_speed_ratio", limit), ("slope_rank_speed", slope_rank),
                        ("traffic_peak_speed", traffic), ("topology_speed", topology)]:
        table.to_csv(SUMMARY_DIR / f"{name}.csv", index=False, encoding="utf-8-sig")

    link_summary = pd.DataFrame({"LINK_ID": link_ids, "observation_count": link_speed_n,
                                 "observed_speed_mean_kmh": np.divide(link_speed_sum, link_speed_n,
                                                                       out=np.full(n_links, np.nan), where=link_speed_n > 0),
                                 "observed_energy_mean_wh": np.divide(link_energy_sum, link_speed_n,
                                                                        out=np.full(n_links, np.nan), where=link_speed_n > 0),
                                 "observed_energy_mean_wh_per_km": np.divide(link_whkm_sum, link_speed_n,
                                                                               out=np.full(n_links, np.nan), where=link_speed_n > 0)})
    link_summary = link_summary.merge(dim, on="LINK_ID", how="left", validate="one_to_one")
    link_summary.to_parquet(SUMMARY_DIR / "observed_link_summary.parquet", index=False, compression="zstd")
    coverage = pd.DataFrame({
        "observation_status": ["observed_history", "no_observed_history"],
        "link_count": [int((link_summary["observation_count"] > 0).sum()), int((link_summary["observation_count"] == 0).sum())],
    })
    coverage["link_share_pct"] = coverage["link_count"] / coverage["link_count"].sum() * 100.0
    coverage.to_csv(SUMMARY_DIR / "link_observation_coverage.csv", index=False, encoding="utf-8-sig")

    # Clean count/share graphic for the observed-versus-unobserved coverage table.
    observed_row = coverage.iloc[0]
    missing_row = coverage.iloc[1]
    plt.figure(figsize=(9, 2.8))
    plt.barh([0], [observed_row["link_share_pct"]], color="#2b6cb0", height=0.5,
             label="Observed history")
    plt.barh([0], [missing_row["link_share_pct"]], left=[observed_row["link_share_pct"]], color="#9eabb9",
             height=0.5, label="No observed history")
    plt.text(observed_row["link_share_pct"] / 2, 0,
             f"Observed  {int(observed_row['link_count']):,} links\n{observed_row['link_share_pct']:.2f}%",
             ha="center", va="center", color="white", fontsize=12, fontweight="bold")
    plt.text(observed_row["link_share_pct"] + missing_row["link_share_pct"] / 2, 0,
             f"Unobserved  {int(missing_row['link_count']):,} links\n{missing_row['link_share_pct']:.2f}%",
             ha="center", va="center", color="#172b4d", fontsize=11, fontweight="bold")
    plt.xlim(0, 100); plt.xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    plt.yticks([]); plt.xlabel("Share of all Seoul road links")
    plt.title("Observed-link coverage (total: 63,548 links)")
    save_fig("14_link_observation_coverage_bar.png")
    pd.DataFrame(sorted(sample_count_hist.items()), columns=["sample_count_5min", "link_hours"]).to_csv(
        SUMMARY_DIR / "sample_count_distribution.csv", index=False, encoding="utf-8-sig")

    dry_mean = np.divide(dry_sum, dry_n, out=np.full(key_count, np.nan), where=dry_n > 0)
    rain_rows = []
    for bin_index, label in enumerate(RAIN_LABELS):
        start_idx = bin_index
        values = wet_sum[start_idx::4]
        counts = wet_n[start_idx::4]
        wet_mean = np.divide(values, counts, out=np.full(key_count, np.nan), where=counts > 0)
        valid = np.isfinite(dry_mean) & np.isfinite(wet_mean)
        weights = counts[valid]
        rain_rows.append({"rain_bin_mm": label, "matched_link_hour_profiles": int(valid.sum()),
                          "wet_observations": int(weights.sum()),
                          "dry_baseline_kmh": float(np.average(dry_mean[valid], weights=weights)),
                          "wet_speed_kmh": float(np.average(wet_mean[valid], weights=weights)),
                          "delta_wet_minus_dry_kmh": float(np.average(wet_mean[valid] - dry_mean[valid], weights=weights))})
    rain_matched = pd.DataFrame(rain_rows)
    rain_matched.to_csv(SUMMARY_DIR / "matched_rain_speed_effect.csv", index=False, encoding="utf-8-sig")

    sample = pd.concat(sample_frames, ignore_index=True)
    sample["speed_ratio_to_limit"] = sample["observed_speed_kmh"] / sample["MAX_SPD"]
    corr_cols = ["observed_speed_kmh", "speed_ratio_to_limit", "MAX_SPD", "LENGTH", "slope_pct_used",
                 "precip_mm", "traffic_volume_hourly", "LANES", "node_complexity"]
    corr = sample[corr_cols].corr(method="spearman")
    corr.to_csv(SUMMARY_DIR / "spearman_correlation_sample.csv", encoding="utf-8-sig")

    # 01 quality: how many five-minute measurements support an hourly label.
    hist = pd.DataFrame(sorted(sample_count_hist.items()), columns=["sample_count_5min", "link_hours"])
    plt.figure(figsize=(8, 4.5))
    plt.bar(hist["sample_count_5min"].astype(str), hist["link_hours"] / 1_000_000, color="#4c78a8")
    plt.xlabel("Number of 5-minute observations in an hourly mean")
    plt.ylabel("Observed link-hours (millions)")
    plt.title("Observed-speed label support")
    save_fig("01_hourly_observation_support.png")

    # 02 coverage heatmap.
    heat = hourly.assign(date=hourly["datetime"].dt.strftime("%m-%d"), hour=hourly["datetime"].dt.hour)
    pivot = heat.pivot(index="date", columns="hour", values="links")
    plt.figure(figsize=(12, 5))
    plt.imshow(pivot, aspect="auto", cmap="Blues")
    plt.colorbar(label="Observed links")
    plt.xticks(range(24), range(24)); plt.yticks(range(len(pivot.index)), pivot.index)
    plt.xlabel("Hour"); plt.ylabel("Date"); plt.title("Observed-link coverage by date and hour")
    save_fig("02_observed_coverage_heatmap.png")

    # 03 actual temporal pattern, split by weekday/weekend.
    plt.figure(figsize=(11, 4.5))
    for weekend, label, color in [(0, "Weekday", "#1976d2"), (1, "Weekend", "#ef6c00")]:
        group = profile[profile["is_weekend"] == weekend].sort_values("hour")
        plt.plot(group["hour"], group["mean_speed_kmh"], marker="o", label=label, color=color)
    plt.xticks(range(24)); plt.xlabel("Hour"); plt.ylabel("Observed mean speed (km/h)")
    plt.title("Observed speed profile by weekday/weekend"); plt.legend()
    save_fig("03_observed_speed_hour_profile.png")

    # 04 actual speed distribution and 05 road classes.
    plt.figure(figsize=(8, 4.5))
    plt.hist(sample["observed_speed_kmh"], bins=70, color="#4c78a8", alpha=0.85)
    plt.xlabel("Observed speed (km/h)"); plt.ylabel("Sampled link-hours")
    plt.title("Distribution of observed hourly speed (1% link sample)")
    save_fig("04_observed_speed_distribution.png")

    rank = rank.sort_values("mean_speed_kmh", ascending=False)
    plt.figure(figsize=(9, 4.5))
    plt.bar(rank["ROAD_RANK"], rank["mean_speed_kmh"], color="#59a14f")
    for x, y, n in zip(range(len(rank)), rank["mean_speed_kmh"], rank["n"]):
        plt.text(x, y, f"{y:.1f}\n(n={n/1e6:.1f}M)", ha="center", va="bottom", fontsize=8)
    plt.xlabel("ROAD_RANK"); plt.ylabel("Observed mean speed (km/h)")
    plt.title("Observed speed by road rank")
    save_fig("05_observed_speed_by_road_rank.png")

    plt.figure(figsize=(8, 4.5))
    plt.bar(limit["limit_bin"].astype(str), limit["mean_speed_kmh"], color="#e15759")
    plt.xlabel("Posted speed limit (km/h)"); plt.ylabel("Observed mean speed (km/h)")
    plt.title("Observed speed by posted speed-limit band")
    save_fig("06_observed_speed_by_limit.png")

    plt.figure(figsize=(10, 5))
    for rank_value, group in slope_rank.groupby("ROAD_RANK", observed=True):
        group = group.set_index("slope_bin").reindex(SLOPE_LABELS).reset_index()
        plt.plot(group["slope_bin"].astype(str), group["mean_speed_kmh"], marker="o", label=rank_value)
    plt.xticks(rotation=25); plt.xlabel("Signed slope bin"); plt.ylabel("Observed mean speed (km/h)")
    plt.title("Observed speed by slope, stratified by road rank"); plt.legend(title="ROAD_RANK", ncol=2)
    save_fig("07_observed_speed_slope_by_rank.png")

    plt.figure(figsize=(8, 4.5))
    x = np.arange(len(rain_matched))
    plt.bar(x, rain_matched["delta_wet_minus_dry_kmh"], color="#7f7f7f")
    plt.axhline(0, color="black", linewidth=0.8)
    for i, row in rain_matched.iterrows():
        plt.text(i, row["delta_wet_minus_dry_kmh"], f"{row['delta_wet_minus_dry_kmh']:.2f}", ha="center",
                 va="bottom" if row["delta_wet_minus_dry_kmh"] >= 0 else "top")
    plt.xticks(x, rain_matched["rain_bin_mm"]); plt.xlabel("Hourly rain (mm)")
    plt.ylabel("Wet speed − matched dry baseline (km/h)")
    plt.title("Rain effect after matching link, hour, and weekend")
    save_fig("08_matched_rain_speed_effect.png")

    plt.figure(figsize=(10, 4.5))
    for period, group in traffic.groupby("peak_period", observed=True):
        group = group.sort_values("traffic_bin")
        plt.plot(group["traffic_bin"].astype(str), group["mean_speed_kmh"], marker="o", label=period)
    plt.xlabel("Hourly traffic-volume band"); plt.ylabel("Observed mean speed (km/h)")
    plt.title("Observed speed by traffic volume and time period"); plt.legend(title="Period")
    save_fig("09_observed_speed_traffic_peak.png")

    plt.figure(figsize=(8, 4.5))
    plt.plot(topology["topology_bin"].astype(str), topology["mean_speed_kmh"], marker="o", color="#b279a2")
    plt.xlabel("Node-complexity band"); plt.ylabel("Observed mean speed (km/h)")
    plt.title("Observed speed by road-network node complexity")
    save_fig("10_observed_speed_topology.png")

    corr_speed = corr["observed_speed_kmh"].drop("observed_speed_kmh").sort_values()
    plt.figure(figsize=(8, 4.5))
    colors = ["#e15759" if value < 0 else "#4c78a8" for value in corr_speed]
    plt.barh(corr_speed.index, corr_speed.values, color=colors)
    plt.axvline(0, color="black", linewidth=0.8)
    plt.xlabel("Spearman correlation with observed speed")
    plt.title("Unadjusted feature associations (1% link sample)")
    save_fig("11_observed_speed_feature_association.png")

    if not args.skip_maps and LINK_SHP.exists():
        geometry = gpd.read_file(LINK_SHP)[["LINK_ID", "geometry"]]
        geometry["LINK_ID"] = geometry["LINK_ID"].astype(str)
        mapped = geometry.merge(link_summary, on="LINK_ID", how="inner")
        vmax = mapped["observed_speed_mean_kmh"].quantile(0.99)
        fig, ax = plt.subplots(figsize=(9, 9))
        mapped.plot(column="observed_speed_mean_kmh", ax=ax, cmap="YlGnBu", linewidth=0.18,
                    legend=True, vmin=0, vmax=vmax)
        ax.set_axis_off(); ax.set_title("Mean observed speed on A links (99th percentile clipped)")
        save_fig("12_map_mean_observed_speed.png")

        # Clean EDA coverage map: link color indicates data availability, not speed.
        fig, ax = plt.subplots(figsize=(9, 9))
        mapped.loc[mapped["observation_count"] == 0].plot(ax=ax, color="#9eabb9", linewidth=0.18)
        mapped.loc[mapped["observation_count"] > 0].plot(ax=ax, color="#2b6cb0", linewidth=0.18)
        ax.set_axis_off()
        ax.set_title("Observed-link coverage (blue: history available; gray: no history)")
        save_fig("13_map_observed_link_coverage.png")

    print(f"Done: {len(parts)} parts | {len(hourly)} hours | {len(link_summary):,} links")


if __name__ == "__main__":
    main()
