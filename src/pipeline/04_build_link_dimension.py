"""링크당 값이 고정된(시간에 안 변하는) 모든 정적 피처를 하나로 합쳐
seoul_link_dimension.csv(63,548행)를 만든다.

구 src/08_add_dem_features.py(DEM 샘플링) + src/14_build_link_model_features.py
(도로망 위상) + src/16_add_link_context_features.py(버스전용차로/스쿨존/
사고다발지역/과속방지턱/교통량 AADT, 이번 세션에 검증)를 통합한다.

data/processed/seoul_link_dem_features.csv는 src/12_build_all_link_weather_snapshot.py/
src/15_add_energy_cost.py가 직접 읽으므로 계속 별도 파일로도 저장한다.

bus_lane_ratio/school_zone_count/accident_hotspot_count/speed_bump_count는
"없으면 0"이 맞다(해당 시설이 진짜 없다는 뜻). traffic_volume_aadt는
"없으면 NaN"이 맞다(KOTI 조사 대상이 아니었을 뿐 실제 교통량이 0이라는 뜻이
아님) — 0으로 채우면 안 된다.

출력:
  data/processed/seoul_link_dem_features.csv (12/15번 호환용, 기존과 동일 스키마)
  data/processed/seoul_link_dimension.csv    (도로속성+DEM+위상+외부컨텍스트 전부)

사용: python src/pipeline/04_build_link_dimension.py
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import shape

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
INTERIM_DIR = PROJECT_ROOT / "data" / "interim"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

SEOUL_LINK_SHP = INTERIM_DIR / "seoul_link.shp"
LINK_ATTR_PATH = PROCESSED_DIR / "seoul_link_attr.csv"
DEM_RAW_DIR = RAW_DIR / "dem"
DEM_OUT = PROCESSED_DIR / "seoul_link_dem_features.csv"
DIMENSION_OUT = PROCESSED_DIR / "seoul_link_dimension.csv"

BUS_LANE_SHP = RAW_DIR / "traffic" / "bus_lane" / "bus_lane.shp"
SCHOOL_FACILITY_SHP = RAW_DIR / "traffic" / "school_zone" / "school_zone.shp"
PEDESTRIAN_ACCIDENT_CSV = RAW_DIR / "traffic" / "pedestrian_accident_2019_2024.csv"
SPEED_BUMP_SHP = RAW_DIR / "traffic" / "speed_bump" / "speed_bump.shp"
TRAFFIC_VOLUME_XLSX = RAW_DIR / "traffic" / "traffic_volume.xlsx"

SAMPLE_POSITIONS = [0.0, 0.25, 0.5, 0.75, 1.0]
SCHOOL_TARGET_TYPES = ["유치원", "초등학교", "어린이집", "초교", "특수학교"]
ZERO_FILL_COLS = ["bus_lane_ratio", "school_zone_count", "accident_hotspot_count", "speed_bump_count"]
KEEP_NA_COLS = ["traffic_volume_aadt"]


# ---------- 1. DEM (구 08) ----------

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


def sample_elevation(x: float, y: float, dem_sources: list) -> float:
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


def sample_link_elevations(geometry, dem_sources: list) -> list[float]:
    return [
        sample_elevation(geometry.interpolate(pos, normalized=True).x, geometry.interpolate(pos, normalized=True).y, dem_sources)
        for pos in SAMPLE_POSITIONS
    ]


def build_dem_features(seoul_link: gpd.GeoDataFrame) -> pd.DataFrame:
    dem_sources = load_dem_sources()
    try:
        dem_crs = get_dem_crs(dem_sources)
        links_dem_crs = seoul_link.to_crs(dem_crs)

        records = []
        total = len(links_dem_crs)
        for index, row in enumerate(links_dem_crs.itertuples(index=False), start=1):
            elevations = sample_link_elevations(row.geometry, dem_sources)
            valid = [v for v in elevations if not np.isnan(v)]
            length = float(row.LENGTH) if row.LENGTH and row.LENGTH > 0 else float(row.geometry.length)

            if valid:
                elev_start, elev_mid, elev_end = elevations[0], elevations[2], elevations[-1]
                elev_mean, elev_min, elev_max = float(np.mean(valid)), float(np.min(valid)), float(np.max(valid))
            else:
                elev_start = elev_mid = elev_end = elev_mean = elev_min = elev_max = np.nan

            elev_delta = elev_end - elev_start if not np.isnan(elev_start) and not np.isnan(elev_end) else np.nan
            slope_pct = elev_delta / length * 100 if length > 0 and not np.isnan(elev_delta) else np.nan

            records.append({
                "LINK_ID": row.LINK_ID,
                "elev_start_m": elev_start, "elev_mid_m": elev_mid, "elev_end_m": elev_end,
                "elev_mean_m": elev_mean, "elev_min_m": elev_min, "elev_max_m": elev_max,
                "elev_delta_m": elev_delta, "slope_pct": slope_pct,
                "abs_slope_pct": abs(slope_pct) if not np.isnan(slope_pct) else np.nan,
                "dem_sample_count": len(valid),
            })
            if index % 10000 == 0:
                print(f"DEM 샘플링 진행: {index:,}/{total:,}")
        return pd.DataFrame(records)
    finally:
        for source in dem_sources:
            source.close()


# ---------- 2. 도로망 위상 (구 14) ----------

def build_node_features(links: pd.DataFrame) -> pd.DataFrame:
    incoming = links.groupby("T_NODE").agg(
        node_in_degree=("LINK_ID", "size"),
        incoming_max_spd_mean=("MAX_SPD", "mean"),
        incoming_lanes_mean=("LANES", "mean"),
    )
    outgoing = links.groupby("F_NODE").agg(
        node_out_degree=("LINK_ID", "size"),
        outgoing_max_spd_mean=("MAX_SPD", "mean"),
        outgoing_lanes_mean=("LANES", "mean"),
    )
    nodes = incoming.join(outgoing, how="outer").fillna(0.0)
    nodes["node_total_degree"] = nodes["node_in_degree"] + nodes["node_out_degree"]
    return nodes


def build_topology_features(links: pd.DataFrame) -> pd.DataFrame:
    nodes = build_node_features(links)
    feature = links[["LINK_ID", "F_NODE", "T_NODE", "MAX_SPD", "LANES", "LENGTH", "slope_pct", "abs_slope_pct"]].copy()
    for endpoint, prefix in [("F_NODE", "f_node"), ("T_NODE", "t_node")]:
        mapped = nodes.add_prefix(f"{prefix}_")
        feature = feature.merge(mapped, left_on=endpoint, right_index=True, how="left")

    feature["upstream_max_spd_mean"] = feature["f_node_incoming_max_spd_mean"].replace(0, np.nan).fillna(feature["MAX_SPD"])
    feature["downstream_max_spd_mean"] = feature["t_node_outgoing_max_spd_mean"].replace(0, np.nan).fillna(feature["MAX_SPD"])
    feature["upstream_lanes_mean"] = feature["f_node_incoming_lanes_mean"].replace(0, np.nan).fillna(feature["LANES"])
    feature["downstream_lanes_mean"] = feature["t_node_outgoing_lanes_mean"].replace(0, np.nan).fillna(feature["LANES"])
    feature["node_complexity"] = feature["f_node_node_total_degree"] + feature["t_node_node_total_degree"]
    feature["downstream_speed_delta"] = feature["MAX_SPD"] - feature["downstream_max_spd_mean"]

    feature["slope_pct_clipped"] = feature["slope_pct"].clip(-12.0, 12.0)
    feature["slope_outlier_flag"] = (feature["abs_slope_pct"] > 12.0).astype(int)
    feature["is_uphill"] = (feature["slope_pct_clipped"] > 0.5).astype(int)
    feature["is_downhill"] = (feature["slope_pct_clipped"] < -0.5).astype(int)
    feature["steep_uphill"] = (feature["slope_pct_clipped"] >= 3.0).astype(int)
    feature["slope_length_m"] = feature["slope_pct_clipped"] / 100.0 * feature["LENGTH"]
    feature["max_spd_x_lanes"] = feature["MAX_SPD"] * feature["LANES"]
    feature["length_x_node_complexity"] = feature["LENGTH"] * feature["node_complexity"]

    drop_cols = ["F_NODE", "T_NODE", "MAX_SPD", "LANES", "LENGTH", "slope_pct", "abs_slope_pct"]
    return feature.drop(columns=drop_cols)


# ---------- 3. 외부 컨텍스트 (구 src/16) ----------

def build_bus_lane_ratio(seoul_link: gpd.GeoDataFrame) -> pd.DataFrame:
    bus = gpd.read_file(BUS_LANE_SHP).to_crs(seoul_link.crs)
    buf = bus.buffer(8).union_all()
    overlap_len = seoul_link.geometry.intersection(buf).length
    ratio = (overlap_len / seoul_link.geometry.length).clip(upper=1).fillna(0)
    return pd.DataFrame({"LINK_ID": seoul_link["LINK_ID"], "bus_lane_ratio": ratio.astype("float32")})


def build_school_zone_count(seoul_link: gpd.GeoDataFrame) -> pd.DataFrame:
    facilities = gpd.read_file(SCHOOL_FACILITY_SHP)
    facilities = facilities[facilities["fac_type"].isin(SCHOOL_TARGET_TYPES)].to_crs(seoul_link.crs)
    buf_gdf = gpd.GeoDataFrame(geometry=facilities.buffer(200), crs=seoul_link.crs)
    joined = gpd.sjoin(seoul_link[["LINK_ID", "geometry"]], buf_gdf, how="inner", predicate="intersects")
    count = joined.groupby("LINK_ID").size()
    out = pd.DataFrame({"LINK_ID": seoul_link["LINK_ID"]})
    out["school_zone_count"] = out["LINK_ID"].map(count).fillna(0).astype("float32")
    return out


def build_accident_hotspot_count(seoul_link: gpd.GeoDataFrame) -> pd.DataFrame:
    accidents = pd.read_csv(PEDESTRIAN_ACCIDENT_CSV, encoding="cp949")
    accidents = accidents[accidents["시도시군구명"].str.startswith("서울특별시")].copy()
    accidents["geometry"] = accidents["다발지역폴리곤"].apply(lambda s: shape(json.loads(s)))
    accidents_gdf = gpd.GeoDataFrame(
        accidents[["사고건수", "geometry"]], geometry="geometry", crs="EPSG:4326"
    ).to_crs(seoul_link.crs)
    joined = gpd.sjoin(seoul_link[["LINK_ID", "geometry"]], accidents_gdf, how="inner", predicate="intersects")
    count = joined.groupby("LINK_ID")["사고건수"].sum()
    out = pd.DataFrame({"LINK_ID": seoul_link["LINK_ID"]})
    out["accident_hotspot_count"] = out["LINK_ID"].map(count).fillna(0).astype("float32")
    return out


def build_speed_bump_count(seoul_link: gpd.GeoDataFrame) -> pd.DataFrame:
    humps = gpd.read_file(SPEED_BUMP_SHP, on_invalid="fix").to_crs(seoul_link.crs)
    buf_gdf = gpd.GeoDataFrame(geometry=humps.buffer(10), crs=seoul_link.crs)
    joined = gpd.sjoin(seoul_link[["LINK_ID", "geometry"]], buf_gdf, how="inner", predicate="intersects")
    count = joined.groupby("LINK_ID").size()
    out = pd.DataFrame({"LINK_ID": seoul_link["LINK_ID"]})
    out["speed_bump_count"] = out["LINK_ID"].map(count).fillna(0).astype("float32")
    return out


def build_traffic_volume_aadt(seoul_ids: set) -> pd.DataFrame:
    tv_col_names = [
        "LEVEL55_LINK_ID", "ITS_LINK_ID", "road_rank_tv", "road_name_tv", "region_tv",
        "length_km_tv", "lanes_tv", "aadt",
    ] + [f"vol_h{h}" for h in range(1, 25)]
    tv = pd.read_excel(TRAFFIC_VOLUME_XLSX, sheet_name="Sheet0", header=6, skiprows=[7])
    tv.columns = tv_col_names
    tv["its_id_list"] = tv["ITS_LINK_ID"].astype(str).str.split(",")
    exp = tv.explode("its_id_list")
    exp["LINK_ID"] = exp["its_id_list"].str.strip()
    exp = exp[(exp["LINK_ID"] != "0") & exp["LINK_ID"].isin(seoul_ids)]
    return exp.groupby("LINK_ID", as_index=False)["aadt"].mean().rename(columns={"aadt": "traffic_volume_aadt"})


def build_external_context(seoul_link: gpd.GeoDataFrame, seoul_ids: set) -> pd.DataFrame:
    base = pd.DataFrame({"LINK_ID": seoul_link["LINK_ID"]})
    for builder in (build_bus_lane_ratio, build_school_zone_count, build_accident_hotspot_count, build_speed_bump_count):
        base = base.merge(builder(seoul_link), on="LINK_ID", how="left")
    base = base.merge(build_traffic_volume_aadt(seoul_ids), on="LINK_ID", how="left")
    for col in ZERO_FILL_COLS:
        base[col] = base[col].fillna(0.0).astype("float32")
    for col in KEEP_NA_COLS:
        base[col] = base[col].astype("float32")  # NaN 유지
    return base


def main() -> None:
    seoul_link = gpd.read_file(SEOUL_LINK_SHP)
    seoul_link["LINK_ID"] = seoul_link["LINK_ID"].astype(str)
    seoul_ids = set(seoul_link["LINK_ID"])

    attr = pd.read_csv(LINK_ATTR_PATH, dtype={"LINK_ID": str, "F_NODE": str, "T_NODE": str}, encoding="utf-8-sig")
    for col in ["LANES", "MAX_SPD", "LENGTH"]:
        attr[col] = pd.to_numeric(attr[col], errors="coerce")

    print("[1/4] DEM 샘플링 중...")
    dem = build_dem_features(seoul_link)
    dem.to_csv(DEM_OUT, index=False, encoding="utf-8-sig")
    print("DEM 피처 저장:", DEM_OUT, "| 링크 수:", len(dem))

    attr_dem = attr.merge(dem.drop(columns=["dem_sample_count"]), on="LINK_ID", how="left")

    print("[2/4] 도로망 위상 계산 중...")
    topology = build_topology_features(attr_dem)

    print("[3/4] 외부 컨텍스트(버스전용차로/스쿨존/사고다발지역/과속방지턱/교통량) 결합 중...")
    context = build_external_context(seoul_link, seoul_ids)

    print("[4/4] 전부 결합...")
    dimension = (
        attr_dem
        .merge(topology.drop(columns=[c for c in ["slope_pct_clipped_dup"] if c in topology.columns]), on="LINK_ID", how="left")
        .merge(context, on="LINK_ID", how="left")
    )
    dimension.to_csv(DIMENSION_OUT, index=False, encoding="utf-8-sig")

    print()
    print("링크 차원 테이블 저장:", DIMENSION_OUT)
    print("링크 수:", len(dimension), "| 컬럼 수:", len(dimension.columns))
    print("경사 이상치 링크:", int(dimension["slope_outlier_flag"].sum()))
    for col in ZERO_FILL_COLS:
        nonzero = (dimension[col] > 0).sum()
        print(f"  {col}: >0인 링크 {nonzero:,}개 ({nonzero / len(dimension) * 100:.1f}%)")
    for col in KEEP_NA_COLS:
        present = dimension[col].notna().sum()
        print(f"  {col}: 값 있는 링크 {present:,}개 ({present / len(dimension) * 100:.1f}%, 나머지는 NaN)")


if __name__ == "__main__":
    main()
