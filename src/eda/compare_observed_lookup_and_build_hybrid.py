"""Compare raw A observations with A lookup, then build historical hybrid energy.

For the retrospective July analysis, each observed A-link speed replaces the
A-lookup speed in the corresponding all-link energy snapshot.  B/C values stay
model predictions.  The resulting files are explicitly labelled *hybrid* and
must not be presented as a future-only forecast.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBSERVED_DIR = PROJECT_ROOT / "data" / "processed" / "observed_speed_energy"
PREDICTED_ENERGY_DIR = PROJECT_ROOT / "data" / "processed" / "link_energy"
HYBRID_DIR = PROJECT_ROOT / "data" / "processed" / "historical_hybrid_link_energy"
SUMMARY_DIR = PROJECT_ROOT / "data" / "processed" / "eda_summary" / "observed_vs_lookup"
FIGURE_DIR = PROJECT_ROOT / "docs" / "figures" / "observed_vs_lookup"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare observed A speeds with lookup and create hybrid snapshots.")
    parser.add_argument("--skip-hybrid", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def save_fig(filename: str) -> None:
    plt.tight_layout()
    plt.savefig(FIGURE_DIR / filename, dpi=180, bbox_inches="tight")
    plt.close()


def main() -> None:
    args = parse_args()
    date_dirs = sorted(path for path in OBSERVED_DIR.glob("date=*") if path.is_dir())
    if not date_dirs:
        raise SystemExit(f"No observed data under {OBSERVED_DIR}")
    if not args.skip_hybrid and HYBRID_DIR.exists() and any(HYBRID_DIR.glob("*.parquet")):
        if not args.overwrite:
            raise SystemExit(f"Hybrid output already exists: {HYBRID_DIR}; use --overwrite to rebuild.")
        shutil.rmtree(HYBRID_DIR)
    if not args.skip_hybrid:
        HYBRID_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)

    hourly_rows: list[dict] = []
    feature_rows: list[pd.DataFrame] = []
    sample_parts: list[pd.DataFrame] = []
    hybrid_rows: list[dict] = []

    for date_dir in date_dirs:
        observed = pd.concat([pd.read_parquet(path) for path in sorted(date_dir.glob("*.parquet"))], ignore_index=True)
        for tm, obs_tm in observed.groupby("tm", observed=True):
            pred_path = PREDICTED_ENERGY_DIR / f"link_energy_{tm}.parquet"
            if not pred_path.exists():
                raise FileNotFoundError(pred_path)
            predicted = pd.read_parquet(pred_path)
            a_lookup = predicted[predicted["tier"] == "A_lookup"].copy()
            actual = obs_tm[["LINK_ID", "observed_speed_kmh", "travel_time_sec", "energy_ev_wh", "energy_wh_per_km",
                             "battery_power_w", "rolling_force_n", "grade_force_n", "aero_force_n", "wheel_power_w",
                             "slope_pct_used", "ROAD_RANK", "precip_mm", "LENGTH"]].copy()
            matched = a_lookup.merge(actual, on="LINK_ID", how="inner", suffixes=("_lookup", "_observed"), validate="one_to_one")
            error = matched["speed_kmh"] - matched["observed_speed_kmh"]
            energy_delta = matched["energy_wh_per_km_lookup"] - matched["energy_wh_per_km_observed"]
            hourly_rows.append({
                "tm": tm, "matched_links": len(matched),
                "speed_mae_kmh": error.abs().mean(), "speed_bias_kmh": error.mean(),
                "speed_rmse_kmh": np.sqrt(np.mean(np.square(error))),
                "energy_mae_wh_per_km": energy_delta.abs().mean(), "energy_bias_wh_per_km": energy_delta.mean(),
                "observed_network_speed_kmh": matched["LENGTH_observed"].sum() / matched["travel_time_sec_observed"].sum() * 3.6,
                "lookup_network_speed_kmh": matched["LENGTH_lookup"].sum() / matched["travel_time_sec_lookup"].sum() * 3.6,
            })
            matched["abs_speed_error_kmh"] = error.abs()
            matched["speed_error_kmh"] = error
            matched["energy_error_wh_per_km"] = energy_delta
            matched["hour"] = int(str(tm)[8:10])
            matched["rain_bin"] = pd.cut(matched["precip_mm_observed"], [-np.inf, 0, 1, 5, 10, np.inf],
                                         labels=["0", "0-1", "1-5", "5-10", "10+"], include_lowest=True)
            matched["slope_bin"] = pd.cut(matched["slope_pct_used_observed"],
                                          [-np.inf, -6, -3, -1, 1, 3, 6, np.inf],
                                          labels=["<=-6%", "-6--3%", "-3--1%", "-1-1%", "1-3%", "3-6%", ">=6%"],
                                          include_lowest=True)
            feature_rows.append(matched.groupby(["hour", "ROAD_RANK", "rain_bin", "slope_bin"], observed=True).agg(
                n=("LINK_ID", "size"), abs_speed_error_kmh=("abs_speed_error_kmh", "sum"),
                speed_error_kmh=("speed_error_kmh", "sum"), abs_energy_error_wh_per_km=("energy_error_wh_per_km", lambda x: x.abs().sum()),
            ).reset_index())
            sample_mask = pd.util.hash_pandas_object(matched["LINK_ID"], index=False).to_numpy() % 100 == 17
            sample_parts.append(matched.loc[sample_mask, ["observed_speed_kmh", "speed_kmh", "energy_wh_per_km_observed",
                                                            "energy_wh_per_km_lookup", "slope_pct_used_observed"]])

            if not args.skip_hybrid:
                observed_indexed = actual.set_index("LINK_ID")
                replace_pos = observed_indexed.index.get_indexer(predicted["LINK_ID"])
                present = replace_pos >= 0
                lookup_pos = replace_pos[present].astype(np.int64, copy=False)
                # Replace every energy-relevant field available in the observed calculation.
                replacements = {
                    "speed_kmh": "observed_speed_kmh", "travel_time_sec": "travel_time_sec", "rolling_force_n": "rolling_force_n",
                    "grade_force_n": "grade_force_n", "aero_force_n": "aero_force_n", "wheel_power_w": "wheel_power_w",
                    "battery_power_w": "battery_power_w", "energy_ev_wh": "energy_ev_wh", "energy_wh_per_km": "energy_wh_per_km",
                }
                for target, source in replacements.items():
                    predicted.loc[present, target] = observed_indexed[source].to_numpy()[lookup_pos]
                predicted.loc[present, "speed_m_s"] = predicted.loc[present, "speed_kmh"] / 3.6
                predicted.loc[present, "traction_battery_power_w"] = np.maximum(
                    predicted.loc[present, "battery_power_w"] - 700.0, 0.0)
                predicted.loc[present, "energy_ev_j"] = predicted.loc[present, "energy_ev_wh"] * 3600.0
                predicted.loc[present, "energy_ev_kwh"] = predicted.loc[present, "energy_ev_wh"] / 1000.0
                predicted.loc[present, "tier"] = "A_observed"
                predicted.loc[present, "speed_source"] = "observed_hourly_5min_mean"
                predicted.loc[present, "prediction_confidence"] = "observed"
                predicted.to_parquet(HYBRID_DIR / f"hybrid_link_energy_{tm}.parquet", index=False, compression="zstd")
                hybrid_rows.append({"tm": tm, "total_links": len(predicted), "observed_a_links": int(present.sum()),
                                    "lookup_a_fallback_links": int(((predicted["tier"] == "A_lookup")).sum()),
                                    "predicted_bc_links": int(predicted["tier"].isin(["B_neighbor_model", "C_static_model"]).sum()),
                                    "total_energy_wh": float(predicted["energy_ev_wh"].sum())})
        print(f"processed {date_dir.name}")

    hourly = pd.DataFrame(hourly_rows).sort_values("tm")
    hourly.to_csv(SUMMARY_DIR / "hourly_observed_vs_lookup.csv", index=False, encoding="utf-8-sig")
    features = pd.concat(feature_rows, ignore_index=True)
    group_keys = ["hour", "ROAD_RANK", "rain_bin", "slope_bin"]
    features = features.groupby(group_keys, observed=True).sum().reset_index()
    features["speed_mae_kmh"] = features["abs_speed_error_kmh"] / features["n"]
    features["speed_bias_kmh"] = features["speed_error_kmh"] / features["n"]
    features["energy_mae_wh_per_km"] = features["abs_energy_error_wh_per_km"] / features["n"]
    features.to_csv(SUMMARY_DIR / "observed_vs_lookup_by_feature.csv", index=False, encoding="utf-8-sig")
    sample = pd.concat(sample_parts, ignore_index=True)
    sample.to_parquet(SUMMARY_DIR / "observed_vs_lookup_sample.parquet", index=False, compression="zstd")
    if hybrid_rows:
        pd.DataFrame(hybrid_rows).sort_values("tm").to_csv(SUMMARY_DIR / "historical_hybrid_hourly_summary.csv", index=False, encoding="utf-8-sig")

    hourly["datetime"] = pd.to_datetime(hourly["tm"], format="%Y%m%d%H%M")
    fig, ax1 = plt.subplots(figsize=(12, 4.5))
    ax1.plot(hourly["datetime"], hourly["observed_network_speed_kmh"], label="A observed", color="#1976d2")
    ax1.plot(hourly["datetime"], hourly["lookup_network_speed_kmh"], label="A lookup", color="#e65100", alpha=0.9)
    ax1.set_ylabel("Network speed on matched A links (km/h)"); ax1.set_xlabel("Time")
    ax1.set_title("Actual observed A speeds versus A historical lookup")
    ax1.legend()
    save_fig("01_observed_vs_lookup_time_series.png")

    plt.figure(figsize=(8, 4.5))
    plotted = sample.sample(min(len(sample), 50_000), random_state=42)
    plt.scatter(plotted["observed_speed_kmh"], plotted["speed_kmh"], c=plotted["slope_pct_used_observed"],
                cmap="coolwarm", s=2, alpha=0.25, vmin=-12, vmax=12)
    maximum = max(plotted["observed_speed_kmh"].max(), plotted["speed_kmh"].max())
    plt.plot([0, maximum], [0, maximum], color="black", linewidth=0.8, linestyle="--")
    plt.colorbar(label="Slope used (%)")
    plt.xlabel("Actual observed speed (km/h)"); plt.ylabel("A lookup speed (km/h)")
    plt.title("A lookup calibration against actual observations")
    save_fig("02_observed_vs_lookup_scatter.png")

    by_hour = features.groupby("hour", observed=True).agg(n=("n", "sum"), error=("abs_speed_error_kmh", "sum")).reset_index()
    by_hour["mae"] = by_hour["error"] / by_hour["n"]
    plt.figure(figsize=(10, 4.5)); plt.plot(by_hour["hour"], by_hour["mae"], marker="o", color="#59a14f")
    plt.xticks(range(24)); plt.xlabel("Hour"); plt.ylabel("A lookup MAE (km/h)")
    plt.title("A lookup error by hour of day")
    save_fig("03_lookup_speed_mae_by_hour.png")

    by_rain = features.groupby("rain_bin", observed=True).agg(n=("n", "sum"), error=("abs_speed_error_kmh", "sum")).reset_index()
    by_rain["mae"] = by_rain["error"] / by_rain["n"]
    plt.figure(figsize=(8, 4.5)); plt.bar(by_rain["rain_bin"].astype(str), by_rain["mae"], color="#4e79a7")
    plt.xlabel("Hourly rain bin (mm)"); plt.ylabel("A lookup MAE (km/h)")
    plt.title("A lookup error by observed rain")
    save_fig("04_lookup_speed_mae_by_rain.png")

    by_rank = features.groupby("ROAD_RANK", observed=True).agg(
        n=("n", "sum"), speed_error=("abs_speed_error_kmh", "sum"), energy_error=("abs_energy_error_wh_per_km", "sum")).reset_index()
    by_rank["speed_mae"] = by_rank["speed_error"] / by_rank["n"]
    by_rank["energy_mae"] = by_rank["energy_error"] / by_rank["n"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    axes[0].bar(by_rank["ROAD_RANK"].astype(str), by_rank["speed_mae"], color="#76b7b2")
    axes[0].set_title("Speed MAE"); axes[0].set_xlabel("ROAD_RANK"); axes[0].set_ylabel("km/h")
    axes[1].bar(by_rank["ROAD_RANK"].astype(str), by_rank["energy_mae"], color="#edc948")
    axes[1].set_title("Energy-intensity MAE"); axes[1].set_xlabel("ROAD_RANK"); axes[1].set_ylabel("Wh/km")
    fig.suptitle("A lookup error by road rank")
    save_fig("05_lookup_error_by_road_rank.png")

    print(f"Done: {len(hourly)} timestamps | mean speed MAE={hourly['speed_mae_kmh'].mean():.3f} km/h")


if __name__ == "__main__":
    main()
