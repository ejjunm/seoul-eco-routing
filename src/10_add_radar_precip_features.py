from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
WEATHER_RAW_DIR = RAW_DATA_DIR / "weather"
GRID_DIR = WEATHER_RAW_DIR / "grid"
RADAR_DIR = WEATHER_RAW_DIR / "radar"
INTERIM_DATA_DIR = PROJECT_ROOT / "data" / "interim"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

GRID_LON_PATH = GRID_DIR / "hsr_lon.txt"
GRID_LAT_PATH = GRID_DIR / "hsr_lat.txt"
SEOUL_LINK_SHP = INTERIM_DATA_DIR / "seoul_link.shp"
SPEED_DEM_PATH = PROCESSED_DATA_DIR / "seoul_link_speed_dem_merged.csv"

GRID_CACHE_PATH = PROCESSED_DATA_DIR / "weather_hsr_seoul_grid.npz"
LINK_GRID_MAP_PATH = PROCESSED_DATA_DIR / "link_radar_grid_mapping.csv"
LINK_PRECIP_OUT = PROCESSED_DATA_DIR / "seoul_link_radar_precip.csv"
SPEED_DEM_WEATHER_OUT = PROCESSED_DATA_DIR / "seoul_link_speed_dem_weather_merged.csv"

SEOUL_BBOX = {
    "lon_min": 126.70,
    "lon_max": 127.25,
    "lat_min": 37.35,
    "lat_max": 37.75,
}


def parse_kma_ascii_grid(path: Path) -> tuple[int, int, np.ndarray]:
    text = path.read_text(encoding="utf-8")
    data_lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    values = re.findall(r"-?\d+(?:\.\d+)?", "\n".join(data_lines))
    if len(values) < 3:
        raise SystemExit(f"KMA 격자 파일을 파싱할 수 없습니다: {path}")

    width = int(values[0])
    height = int(values[1])
    data = np.asarray(values[2:], dtype=np.float32)
    expected = width * height
    if data.size != expected:
        raise SystemExit(f"{path.name} 값 개수 불일치: expected={expected}, actual={data.size}")
    return width, height, data.reshape((height, width))


def load_or_build_seoul_grid() -> dict[str, np.ndarray]:
    if GRID_CACHE_PATH.exists():
        loaded = np.load(GRID_CACHE_PATH)
        return {key: loaded[key] for key in loaded.files}

    print("HSR lon 격자 파싱 중...")
    width, height, lon_grid = parse_kma_ascii_grid(GRID_LON_PATH)
    print("HSR lat 격자 파싱 중...")
    width_lat, height_lat, lat_grid = parse_kma_ascii_grid(GRID_LAT_PATH)
    if (width, height) != (width_lat, height_lat):
        raise SystemExit("lon/lat 격자 크기가 다릅니다.")

    mask = (
        (lon_grid >= SEOUL_BBOX["lon_min"])
        & (lon_grid <= SEOUL_BBOX["lon_max"])
        & (lat_grid >= SEOUL_BBOX["lat_min"])
        & (lat_grid <= SEOUL_BBOX["lat_max"])
    )
    rows, cols = np.where(mask)
    flat_indices = rows * width + cols
    lon_values = lon_grid[rows, cols]
    lat_values = lat_grid[rows, cols]

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        GRID_CACHE_PATH,
        width=np.asarray(width),
        height=np.asarray(height),
        rows=rows,
        cols=cols,
        flat_indices=flat_indices,
        lon=lon_values,
        lat=lat_values,
    )
    print("서울 주변 HSR 격자 캐시 저장:", GRID_CACHE_PATH)
    print("서울 주변 격자 수:", len(flat_indices))

    return {
        "width": np.asarray(width),
        "height": np.asarray(height),
        "rows": rows,
        "cols": cols,
        "flat_indices": flat_indices,
        "lon": lon_values,
        "lat": lat_values,
    }


def build_link_grid_mapping(grid: dict[str, np.ndarray]) -> pd.DataFrame:
    speed_links = pd.read_csv(
        SPEED_DEM_PATH,
        usecols=["LINK_ID"],
        dtype={"LINK_ID": str},
        encoding="utf-8-sig",
    )["LINK_ID"].drop_duplicates()
    target_link_ids = set(speed_links)

    if LINK_GRID_MAP_PATH.exists():
        cached = pd.read_csv(LINK_GRID_MAP_PATH, dtype={"LINK_ID": str})
        if set(cached["LINK_ID"]) == target_link_ids:
            return cached
        print("링크 구성이 바뀌어 링크-레이더 격자 매핑 캐시를 다시 생성합니다:", LINK_GRID_MAP_PATH)

    links = gpd.read_file(SEOUL_LINK_SHP)
    links["LINK_ID"] = links["LINK_ID"].astype(str)
    links = links[links["LINK_ID"].isin(target_link_ids)].copy()
    link_points = links.copy()
    link_points["geometry"] = link_points.geometry.centroid
    link_points_wgs = link_points.to_crs(epsg=4326)
    centroids = link_points_wgs.geometry

    radar_lon = grid["lon"]
    radar_lat = grid["lat"]
    flat_indices = grid["flat_indices"]
    rows = grid["rows"]
    cols = grid["cols"]

    records = []
    for link_id, point in zip(link_points_wgs["LINK_ID"], centroids):
        distances = (radar_lon - point.x) ** 2 + (radar_lat - point.y) ** 2
        nearest_position = int(np.argmin(distances))
        records.append(
            {
                "LINK_ID": link_id,
                "link_lon": point.x,
                "link_lat": point.y,
                "radar_row": int(rows[nearest_position]),
                "radar_col": int(cols[nearest_position]),
                "radar_flat_index": int(flat_indices[nearest_position]),
                "radar_lon": float(radar_lon[nearest_position]),
                "radar_lat": float(radar_lat[nearest_position]),
            }
        )

    mapping = pd.DataFrame(records)
    mapping.to_csv(LINK_GRID_MAP_PATH, index=False, encoding="utf-8-sig")
    print("링크-레이더 격자 매핑 저장:", LINK_GRID_MAP_PATH)
    return mapping


def speed_row_to_tm(date_value, time_code_value) -> str:
    date = datetime.strptime(str(int(date_value)), "%Y%m%d")
    time_code = int(time_code_value)
    if time_code == 24:
        return (date + timedelta(days=1)).strftime("%Y%m%d") + "0000"
    return date.strftime("%Y%m%d") + f"{time_code:02d}00"


def radar_path_for_tm(tm: str) -> Path:
    return RADAR_DIR / f"hsr_pcph_acc60_{tm}.txt"


def raw_to_precip_mm(raw_values: np.ndarray) -> np.ndarray:
    precip = raw_values.astype(np.float32) / 100.0
    precip[raw_values < 0] = 0.0
    precip[raw_values <= -30000] = np.nan
    return precip


def process_existing_radar(mapping: pd.DataFrame) -> pd.DataFrame:
    speed_times = pd.read_csv(
        SPEED_DEM_PATH,
        usecols=["기준일", "시간코드"],
        encoding="utf-8-sig",
    ).drop_duplicates()
    speed_times["tm"] = [
        speed_row_to_tm(date_value, time_code_value)
        for date_value, time_code_value in zip(speed_times["기준일"], speed_times["시간코드"])
    ]

    flat_indices = mapping["radar_flat_index"].to_numpy(dtype=np.int64)
    link_ids = mapping["LINK_ID"].to_numpy()

    records = []
    missing_tms = []
    for tm in sorted(speed_times["tm"].unique()):
        radar_path = radar_path_for_tm(tm)
        if not radar_path.exists():
            missing_tms.append(tm)
            continue

        print("레이더 파일 처리:", radar_path.name)
        width, height, radar_grid = parse_kma_ascii_grid(radar_path)
        flat_values = radar_grid.reshape(-1)[flat_indices]
        precip_values = raw_to_precip_mm(flat_values)

        for link_id, raw_value, precip_mm in zip(link_ids, flat_values, precip_values):
            records.append(
                {
                    "tm": tm,
                    "LINK_ID": link_id,
                    "radar_raw_value": float(raw_value),
                    "precip_mm": float(precip_mm) if not np.isnan(precip_mm) else np.nan,
                }
            )

    precip = pd.DataFrame(records)
    precip.to_csv(LINK_PRECIP_OUT, index=False, encoding="utf-8-sig")

    print("강수 피처 저장:", LINK_PRECIP_OUT)
    print("처리된 레이더 시각 수:", precip["tm"].nunique() if not precip.empty else 0)
    print("누락 레이더 시각 수:", len(missing_tms))
    if missing_tms:
        print("누락 예시:", ", ".join(missing_tms[:10]))
    return precip


def merge_weather(precip: pd.DataFrame) -> None:
    if precip.empty:
        print("결합할 강수 피처가 없습니다.")
        return

    speed = pd.read_csv(
        SPEED_DEM_PATH,
        dtype={"LINK_ID": str},
        encoding="utf-8-sig",
    )
    speed["tm"] = [
        speed_row_to_tm(date_value, time_code_value)
        for date_value, time_code_value in zip(speed["기준일"], speed["시간코드"])
    ]

    merged = speed.merge(precip, on=["tm", "LINK_ID"], how="left")
    merged.to_csv(SPEED_DEM_WEATHER_OUT, index=False, encoding="utf-8-sig")

    print("속도+DEM+강수 결합 저장:", SPEED_DEM_WEATHER_OUT)
    print("결합 행 수:", len(merged))
    print("강수값 존재 행 수:", int(merged["precip_mm"].notna().sum()))


def main() -> None:
    grid = load_or_build_seoul_grid()
    mapping = build_link_grid_mapping(grid)
    precip = process_existing_radar(mapping)
    merge_weather(precip)


if __name__ == "__main__":
    main()
