"""Build all-link static/weather features for one routing timestamp."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
INTERIM_DATA_DIR = PROJECT_ROOT / "data" / "interim"

SEOUL_LINK_SHP = INTERIM_DATA_DIR / "seoul_link.shp"
LINK_ATTR_PATH = PROCESSED_DATA_DIR / "seoul_link_attr.csv"
DEM_PATH = PROCESSED_DATA_DIR / "seoul_link_dem_features.csv"
GRID_CACHE_PATH = PROCESSED_DATA_DIR / "weather_hsr_seoul_grid.npz"
ALL_LINK_GRID_MAP_PATH = PROCESSED_DATA_DIR / "all_link_radar_grid_mapping.csv"
RADAR_DIR = RAW_DATA_DIR / "weather" / "radar"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tm", required=True, help="KMA 시각 YYYYMMDDHHMM")
    return parser.parse_args()


def parse_kma_ascii_grid(path: Path) -> np.ndarray:
    text = path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    values = re.findall(r"-?\d+(?:\.\d+)?", "\n".join(lines))
    if len(values) < 3:
        raise SystemExit(f"레이더 격자를 파싱할 수 없습니다: {path}")
    width, height = int(values[0]), int(values[1])
    data = np.asarray(values[2:], dtype=np.float32)
    if data.size != width * height:
        raise SystemExit(f"레이더 격자 크기 불일치: {path.name}")
    return data.reshape(height, width)


def load_or_build_grid_mapping() -> pd.DataFrame:
    all_link_ids = set(pd.read_csv(LINK_ATTR_PATH, usecols=["LINK_ID"], dtype=str, encoding="utf-8-sig")["LINK_ID"])
    if ALL_LINK_GRID_MAP_PATH.exists():
        cached = pd.read_csv(ALL_LINK_GRID_MAP_PATH, dtype={"LINK_ID": str}, encoding="utf-8-sig")
        if set(cached["LINK_ID"]) == all_link_ids:
            return cached

    if not GRID_CACHE_PATH.exists():
        raise SystemExit(f"서울 레이더 격자 캐시가 없습니다: {GRID_CACHE_PATH}")
    grid = np.load(GRID_CACHE_PATH)
    radar_points = np.column_stack([grid["lat"], grid["lon"]])
    tree = cKDTree(radar_points)

    links = gpd.read_file(SEOUL_LINK_SHP)
    links["LINK_ID"] = links["LINK_ID"].astype(str)
    centroids = links.geometry.centroid
    wgs84 = gpd.GeoSeries(centroids, crs=links.crs).to_crs(epsg=4326)
    coordinates = np.column_stack([wgs84.y.to_numpy(), wgs84.x.to_numpy()])
    _, nearest = tree.query(coordinates, k=1)

    mapping = pd.DataFrame(
        {
            "LINK_ID": links["LINK_ID"].to_numpy(),
            "link_lon": wgs84.x.to_numpy(),
            "link_lat": wgs84.y.to_numpy(),
            "radar_row": grid["rows"][nearest],
            "radar_col": grid["cols"][nearest],
            "radar_flat_index": grid["flat_indices"][nearest],
            "radar_lon": grid["lon"][nearest],
            "radar_lat": grid["lat"][nearest],
        }
    )
    mapping.to_csv(ALL_LINK_GRID_MAP_PATH, index=False, encoding="utf-8-sig")
    print("전체 링크-레이더 격자 매핑 저장:", ALL_LINK_GRID_MAP_PATH)
    return mapping


def main() -> None:
    args = parse_args()
    radar_path = RADAR_DIR / f"hsr_pcph_acc60_{args.tm}.txt"
    if not radar_path.exists():
        raise SystemExit(f"레이더 파일이 없습니다: {radar_path}")

    mapping = load_or_build_grid_mapping()
    radar = parse_kma_ascii_grid(radar_path).reshape(-1)
    raw = radar[mapping["radar_flat_index"].to_numpy(dtype=np.int64)]
    precip = raw.astype(np.float32) / 100.0
    precip[raw < 0] = 0.0
    precip[raw <= -30000] = np.nan

    links = pd.read_csv(LINK_ATTR_PATH, dtype={"LINK_ID": str}, encoding="utf-8-sig")
    dem = pd.read_csv(DEM_PATH, dtype={"LINK_ID": str}, encoding="utf-8-sig")
    weather = mapping[["LINK_ID"]].copy()
    weather["tm"] = args.tm
    weather["radar_raw_value"] = raw
    weather["precip_mm"] = precip
    snapshot = links.merge(dem, on="LINK_ID", how="left").merge(weather, on="LINK_ID", how="left")

    out_path = PROCESSED_DATA_DIR / f"seoul_all_link_weather_{args.tm}.csv"
    snapshot.to_csv(out_path, index=False, encoding="utf-8-sig")
    print("전체 링크 기상 스냅샷 저장:", out_path)
    print("링크 수:", len(snapshot), "| 강수 결측:", int(snapshot["precip_mm"].isna().sum()))


if __name__ == "__main__":
    main()
