import argparse
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
DEM_RAW_DIR = RAW_DATA_DIR / "dem"
INTERIM_DATA_DIR = PROJECT_ROOT / "data" / "interim"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

SEOUL_LINK_SHP = INTERIM_DATA_DIR / "seoul_link.shp"
SPEED_MERGED_PATH = PROCESSED_DATA_DIR / "seoul_link_speed_merged.csv"
LINK_DEM_OUT = PROCESSED_DATA_DIR / "seoul_link_dem_features.csv"
SPEED_DEM_OUT = PROCESSED_DATA_DIR / "seoul_link_speed_dem_merged.csv"

SAMPLE_POSITIONS = [0.0, 0.25, 0.5, 0.75, 1.0]


def load_dem_sources() -> list:
    import rasterio

    dem_paths = sorted(DEM_RAW_DIR.glob("*.img")) + sorted(DEM_RAW_DIR.glob("*.tif"))
    if not dem_paths:
        raise SystemExit(f"DEM 파일이 없습니다: {DEM_RAW_DIR}")
    return [rasterio.open(path) for path in dem_paths]


def get_dem_crs(dem_sources: list):
    crs_values = {source.crs.to_string() for source in dem_sources if source.crs is not None}
    if len(crs_values) != 1:
        raise SystemExit(f"DEM 좌표계가 하나로 통일되어 있지 않습니다: {sorted(crs_values)}")
    return dem_sources[0].crs


def point_in_bounds(x: float, y: float, bounds) -> bool:
    return bounds.left <= x <= bounds.right and bounds.bottom <= y <= bounds.top


def sample_elevation(
    x: float,
    y: float,
    dem_sources: list,
) -> float:
    for source in dem_sources:
        if not point_in_bounds(x, y, source.bounds):
            continue
        value = next(source.sample([(x, y)]))[0]
        if source.nodata is not None and value == source.nodata:
            continue
        if np.isnan(value):
            continue
        return float(value)
    return np.nan


def sample_link_elevations(
    geometry,
    dem_sources: list,
) -> list[float]:
    values = []
    for position in SAMPLE_POSITIONS:
        point = geometry.interpolate(position, normalized=True)
        values.append(sample_elevation(point.x, point.y, dem_sources))
    return values


def build_dem_features() -> pd.DataFrame:
    import geopandas as gpd

    dem_sources = load_dem_sources()
    try:
        dem_crs = get_dem_crs(dem_sources)
        links = gpd.read_file(SEOUL_LINK_SHP)
        links["LINK_ID"] = links["LINK_ID"].astype(str)
        links_dem_crs = links.to_crs(dem_crs)

        records = []
        total = len(links_dem_crs)
        for index, row in enumerate(links_dem_crs.itertuples(index=False), start=1):
            elevations = sample_link_elevations(row.geometry, dem_sources)
            valid_elevations = [value for value in elevations if not np.isnan(value)]
            length = float(row.LENGTH) if row.LENGTH and row.LENGTH > 0 else float(row.geometry.length)

            if valid_elevations:
                elev_start = elevations[0]
                elev_mid = elevations[2]
                elev_end = elevations[-1]
                elev_mean = float(np.mean(valid_elevations))
                elev_min = float(np.min(valid_elevations))
                elev_max = float(np.max(valid_elevations))
            else:
                elev_start = elev_mid = elev_end = elev_mean = elev_min = elev_max = np.nan

            elev_delta = elev_end - elev_start if not np.isnan(elev_start) and not np.isnan(elev_end) else np.nan
            slope_pct = elev_delta / length * 100 if length > 0 and not np.isnan(elev_delta) else np.nan

            records.append(
                {
                    "LINK_ID": row.LINK_ID,
                    "elev_start_m": elev_start,
                    "elev_mid_m": elev_mid,
                    "elev_end_m": elev_end,
                    "elev_mean_m": elev_mean,
                    "elev_min_m": elev_min,
                    "elev_max_m": elev_max,
                    "elev_delta_m": elev_delta,
                    "slope_pct": slope_pct,
                    "abs_slope_pct": abs(slope_pct) if not np.isnan(slope_pct) else np.nan,
                    "dem_sample_count": len(valid_elevations),
                }
            )

            if index % 10000 == 0:
                print(f"DEM 샘플링 진행: {index:,}/{total:,}")

        return pd.DataFrame(records)
    finally:
        for source in dem_sources:
            source.close()


def merge_speed_with_dem(dem_features: pd.DataFrame) -> None:
    if not SPEED_MERGED_PATH.exists():
        print("결합할 속도 데이터가 없습니다:", SPEED_MERGED_PATH)
        return

    speed = pd.read_csv(
        SPEED_MERGED_PATH,
        dtype={"LINK_ID": str},
        encoding="utf-8-sig",
    )
    merged = speed.merge(dem_features, on="LINK_ID", how="left")
    merged.to_csv(SPEED_DEM_OUT, index=False, encoding="utf-8-sig")
    print("속도+DEM 결합 저장:", SPEED_DEM_OUT)
    print("속도+DEM 결합 행 수:", len(merged))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--merge-only",
        action="store_true",
        help="기존 DEM 피처를 재사용해 속도 데이터만 다시 결합합니다.",
    )
    args = parser.parse_args()

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if args.merge_only:
        dem_features = pd.read_csv(LINK_DEM_OUT, dtype={"LINK_ID": str}, encoding="utf-8-sig")
        print("기존 DEM 피처 재사용:", LINK_DEM_OUT)
    else:
        dem_features = build_dem_features()
        dem_features.to_csv(LINK_DEM_OUT, index=False, encoding="utf-8-sig")
        valid_ratio = dem_features["dem_sample_count"].gt(0).mean() * 100
        print("DEM 피처 저장:", LINK_DEM_OUT)
        print("링크 수:", len(dem_features))
        print("DEM 샘플 존재 링크 비율(%):", round(valid_ratio, 2))

    merge_speed_with_dem(dem_features)


if __name__ == "__main__":
    main()
