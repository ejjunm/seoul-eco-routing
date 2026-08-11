"""Build VT-CPEM energy estimates from hourly *observed* A-link speeds.

This is deliberately separate from ``link_energy/``.  The latter uses the
all-link A/B/C prediction snapshots; this script uses the raw hourly label
``평균속도`` from ``seoul_link_speed_fact.csv``.  Energy is still modelled,
not directly measured by a vehicle, so its outputs are named
"observed-speed-based estimated energy" throughout the EDA.
"""
from __future__ import annotations

import argparse
import shutil
from collections import defaultdict
from pathlib import Path

import pandas as pd

from link_energy import calculate_link_energy, validate_energy_inputs


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED = PROJECT_ROOT / "data" / "processed"
FACT_PATH = PROCESSED / "seoul_link_speed_fact.csv"
DIMENSION_PATH = PROCESSED / "seoul_link_dimension.csv"
OUT_DIR = PROCESSED / "observed_speed_energy"
SUMMARY_DIR = PROCESSED / "eda_summary"

DATE_COL = "기준일"
HOUR_COL = "시간코드"
SPEED_COL = "평균속도"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute energy from observed hourly A-link speeds.")
    parser.add_argument("--start-date", default="20260707")
    parser.add_argument("--end-date", default="20260720")
    parser.add_argument("--exclude-tm", default="202607070000",
                        help="Timestamp excluded from the common weather/energy period.")
    parser.add_argument("--chunksize", type=int, default=400_000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def load_dimension() -> pd.DataFrame:
    cols = ["LINK_ID", "F_NODE", "T_NODE", "LENGTH", "ROAD_NAME", "ROAD_RANK", "MAX_SPD", "LANES", "slope_pct",
            "node_complexity", "downstream_speed_delta", "bus_lane_ratio", "school_zone_count",
            "accident_hotspot_count", "speed_bump_count"]
    dim = pd.read_csv(DIMENSION_PATH, usecols=cols, dtype={"LINK_ID": str}, encoding="utf-8-sig")
    dim["LENGTH"] = pd.to_numeric(dim["LENGTH"], errors="coerce")
    dim["slope_pct"] = pd.to_numeric(dim["slope_pct"], errors="coerce")
    return dim


def main() -> None:
    args = parse_args()
    start = pd.to_datetime(args.start_date, format="%Y%m%d")
    end = pd.to_datetime(args.end_date, format="%Y%m%d") + pd.Timedelta(hours=23)
    excluded = pd.to_datetime(args.exclude_tm, format="%Y%m%d%H%M") if args.exclude_tm else None

    if OUT_DIR.exists() and any(OUT_DIR.rglob("*.parquet")):
        if not args.overwrite:
            raise SystemExit(f"Output already exists: {OUT_DIR}. Use --overwrite to rebuild it.")
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    dim = load_dimension()
    usecols = ["LINK_ID", DATE_COL, HOUR_COL, "sample_count_5min", SPEED_COL, "precip_mm",
               "traffic_volume_hourly", "traffic_volume_ratio", "grid_pop", "dong_pop"]
    quality: dict[str, int | float] = defaultdict(int)
    hourly_parts: list[pd.DataFrame] = []
    part_number = 0

    for chunk in pd.read_csv(FACT_PATH, usecols=usecols, dtype={"LINK_ID": str, DATE_COL: str},
                             encoding="utf-8-sig", chunksize=args.chunksize):
        quality["rows_read"] += len(chunk)
        chunk[HOUR_COL] = pd.to_numeric(chunk[HOUR_COL], errors="coerce")
        chunk[SPEED_COL] = pd.to_numeric(chunk[SPEED_COL], errors="coerce")
        dates = pd.to_datetime(chunk[DATE_COL], format="%Y%m%d", errors="coerce")
        tm = dates + pd.to_timedelta(chunk[HOUR_COL] - 1, unit="h")
        mask = (tm >= start) & (tm <= end)
        if excluded is not None:
            mask &= tm != excluded
        selected = chunk.loc[mask].copy()
        selected_tm = tm.loc[mask]
        if selected.empty:
            continue
        selected["_tm_dt"] = selected_tm.to_numpy()

        quality["rows_period_before_validation"] += len(selected)
        invalid_speed = selected[SPEED_COL].isna() | (selected[SPEED_COL] <= 0)
        quality["invalid_or_nonpositive_speed"] += int(invalid_speed.sum())
        selected = selected.loc[~invalid_speed].copy()
        if selected.empty:
            continue

        selected = selected.merge(dim, on="LINK_ID", how="left", validate="many_to_one")
        missing_dimension = selected["LENGTH"].isna() | selected["slope_pct"].isna()
        quality["missing_dimension"] += int(missing_dimension.sum())
        selected = selected.loc[~missing_dimension].copy()
        if selected.empty:
            continue
        selected_tm = pd.to_datetime(selected.pop("_tm_dt"))

        selected = selected.rename(columns={SPEED_COL: "observed_speed_kmh"})
        selected["speed_kmh"] = selected["observed_speed_kmh"]
        validate_energy_inputs(selected)
        energy = calculate_link_energy(selected)
        energy["tm"] = selected_tm.dt.strftime("%Y%m%d%H00").to_numpy()
        energy["date"] = selected_tm.dt.strftime("%Y%m%d").to_numpy()
        energy["hour"] = selected_tm.dt.hour.astype("int8").to_numpy()
        energy["speed_source"] = "observed_hourly_5min_mean"
        energy["prediction_confidence"] = "observed"

        keep = ["LINK_ID", "F_NODE", "T_NODE", "LENGTH", "ROAD_NAME", "ROAD_RANK", "MAX_SPD", "LANES",
                "node_complexity", "downstream_speed_delta", "bus_lane_ratio", "school_zone_count",
                "accident_hotspot_count", "speed_bump_count",
                "date", "tm", "hour", "observed_speed_kmh", "sample_count_5min", "precip_mm",
                "traffic_volume_hourly", "traffic_volume_ratio", "grid_pop", "dong_pop", "slope_pct",
                "slope_pct_raw", "slope_pct_used", "slope_outlier_flag", "travel_time_sec", "crr",
                "rolling_force_n", "grade_force_n", "aero_force_n", "wheel_power_w", "battery_power_w",
                "energy_ev_j", "energy_ev_wh", "energy_ev_kwh", "energy_wh_per_km", "speed_source",
                "prediction_confidence"]
        energy = energy[keep]
        quality["rows_written"] += len(energy)
        quality["slope_outliers"] += int(energy["slope_outlier_flag"].sum())
        quality["negative_energy"] += int((energy["energy_ev_wh"] < 0).sum())

        # 청크별 평균을 나중에 더하면 값이 청크 수만큼 부풀기 때문에, 결합 가능한
        # 합계와 유효 개수만 저장하고 전체 청크 결합 뒤 평균을 계산한다.
        grouped = energy.groupby("tm", observed=True).agg(
            links=("LINK_ID", "size"), speed_sum_kmh=("observed_speed_kmh", "sum"),
            length_m=("LENGTH", "sum"), travel_time_sec=("travel_time_sec", "sum"),
            energy_total_wh=("energy_ev_wh", "sum"), rain_sum_mm=("precip_mm", "sum"),
            rain_count=("precip_mm", "count"), sample_count_sum=("sample_count_5min", "sum"),
            sample_count_valid=("sample_count_5min", "count"),
        ).reset_index()
        hourly_parts.append(grouped)

        for date, frame in energy.groupby("date", observed=True):
            folder = OUT_DIR / f"date={date}"
            folder.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(folder / f"part-{part_number:05d}.parquet", index=False, compression="zstd")
        part_number += 1
        print(f"chunk {part_number}: {quality['rows_written']:,} observed link-hours written")

    hourly = pd.concat(hourly_parts, ignore_index=True).groupby("tm", as_index=False).sum(numeric_only=True)
    hourly["speed_mean_kmh"] = hourly["speed_sum_kmh"] / hourly["links"]
    hourly["energy_mean_wh"] = hourly["energy_total_wh"] / hourly["links"]
    hourly["rain_mean_mm"] = hourly["rain_sum_mm"] / hourly["rain_count"]
    hourly["sample_count_mean"] = hourly["sample_count_sum"] / hourly["sample_count_valid"]
    hourly["network_speed_kmh"] = hourly["length_m"] / hourly["travel_time_sec"] * 3.6
    hourly["network_wh_per_km"] = hourly["energy_total_wh"] / (hourly["length_m"] / 1000.0)
    hourly = hourly.sort_values("tm")
    hourly = hourly.drop(columns=["speed_sum_kmh", "rain_sum_mm", "rain_count",
                                  "sample_count_sum", "sample_count_valid"])
    hourly.to_csv(SUMMARY_DIR / "observed_hourly_speed_energy_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([quality]).to_csv(SUMMARY_DIR / "observed_energy_quality_summary.csv", index=False, encoding="utf-8-sig")
    print(f"Done: {quality['rows_written']:,} rows | {len(hourly)} timestamps | output={OUT_DIR}")


if __name__ == "__main__":
    main()
