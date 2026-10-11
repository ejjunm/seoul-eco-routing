"""마을버스·자율주행 노선의 수요(필요도) 지표를 만든다.

입력
  data/processed/transit/{bus_stops,routes}.csv           (01 산출물)
  data/raw/traffic/서울시버스노선별정류소정보(20260902).xlsx  (노선-정류소 소속)
  data/raw/traffic/2026년_버스노선별_정류장별_시간대별_승하차_인원_정보(07월).csv
  data/raw/traffic/250_LOCAL_RESD_202607/            (250m 격자 생활인구, 일별)
  data/raw/traffic/250_LOCAL_RESD_ADMDONG_202607/    (행정동 생활인구, 일별·연령별)
  data/raw/traffic/match/match.shp                   (250m 격자 CELL_ID -> polygon)
  생활인구 원자료가 없고 grid_population_daytime.csv가 이미 있으면 그 결과를 재사용한다.

처리
  1. 승하차: 7월 월합계를 31일로 나눠 노선·정류소별 일평균 승차·하차를 만든다.
     마을버스는 '노선번호'가 정류소 파일의 '노선명'과 같다(예: 강남01).
  2. 고령 생활인구: 격자 연령별 칸은 소수 인원이 '*'로 가려져 있어 그대로 합하면
     과소 추정된다. 대신 격자 총인구에 같은 일자·시간 행정동의 65세 이상 비율을
     곱해 추정한다. 평일(7/7~7/20 중 월~금) 10~16시 평균을 낮 시간 대표값으로 쓴다.
     분기 노선(서대문02대·02소 등)은 승하차가 합쳐져 있어 route_kinds.py 규칙으로 정류장별로 나눈다.
  3. 노선 단위로 정류소 반경 300m 격자(중복 제거)의 낮 시간 인구·고령 인구를 합산하고,
     지하철역 500m 밖이면서 일반버스 정류소 200m 안에도 없는 '대체수단 없는 정류소'
     비율과 그 정류소들의 승차 비중을 계산한다.

출력 (data/processed/transit/)
  grid_population_daytime.csv  격자 1행: 중심좌표(EPSG:5179), 낮 인구, 고령 인구, 고령 비율
  stop_ridership.csv           노선×정류소 일평균 승하차
  route_demand.csv             노선 1행 수요 지표

사용: python src/transit/02_build_route_demand.py
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from route_kinds import branch_stop_weights, ridership_key

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_TRAFFIC = PROJECT_ROOT / "data" / "raw" / "traffic"
TRANSIT = PROJECT_ROOT / "data" / "processed" / "transit"
ROUTE_STOP_XLSX = RAW_TRAFFIC / "서울시버스노선별정류소정보(20260902).xlsx"
RIDERSHIP_CSV = RAW_TRAFFIC / "2026년_버스노선별_정류장별_시간대별_승하차_인원_정보(07월).csv"
GRID_POP_DIR = RAW_TRAFFIC / "250_LOCAL_RESD_202607"
DONG_POP_DIR = RAW_TRAFFIC / "250_LOCAL_RESD_ADMDONG_202607"
GRID_SHP = RAW_TRAFFIC / "match" / "match.shp"

DAYS_IN_MONTH = 31
DAYTIME_HOURS = range(10, 17)
STOP_CATCHMENT_M = 300.0
STATION_WALK_M = 500.0
ELDERLY_COLS = ["남자 65~69세", "남자 70세 이상", "여자 65~69세", "여자 70세 이상"]


def is_weekday(date_text: pd.Series) -> pd.Series:
    return pd.to_datetime(date_text.astype(str), format="%Y%m%d").dt.dayofweek < 5


def build_daytime_population() -> pd.DataFrame:
    """격자별 평일 낮(10~16시) 평균 생활인구와 고령 인구 추정치."""
    dong_frames = []
    for path in sorted(DONG_POP_DIR.glob("*.csv")):
        dong = pd.read_csv(path, encoding="cp949", usecols=["일자", "시간", "행정동코드", "생활인구합계", *ELDERLY_COLS])
        dong = dong[is_weekday(dong["일자"]) & dong["시간"].isin(DAYTIME_HOURS)]
        elderly = dong[ELDERLY_COLS].apply(pd.to_numeric, errors="coerce").sum(axis=1)
        dong_frames.append(pd.DataFrame({
            "일자": dong["일자"].astype(str), "시간": dong["시간"].astype(int),
            "행정동코드": dong["행정동코드"].astype(str).str.strip(),
            "elderly_share": elderly / dong["생활인구합계"].where(dong["생활인구합계"] > 0),
        }))
    dong_share = pd.concat(dong_frames, ignore_index=True)

    grid_frames = []
    for path in sorted(GRID_POP_DIR.glob("*.csv")):
        grid = pd.read_csv(path, encoding="cp949", usecols=["일자", "시간", "행정동코드", "250M격자", "생활인구합계"], dtype=str)
        grid = grid[is_weekday(grid["일자"]) & grid["시간"].astype(int).isin(DAYTIME_HOURS)]
        grid_frames.append(pd.DataFrame({
            "일자": grid["일자"], "시간": grid["시간"].astype(int), "행정동코드": grid["행정동코드"].str.strip(),
            "CELL_ID": grid["250M격자"].str.strip(), "pop": pd.to_numeric(grid["생활인구합계"], errors="coerce"),
        }))
    grid = pd.concat(grid_frames, ignore_index=True).merge(dong_share, on=["일자", "시간", "행정동코드"], how="left")
    grid["elderly"] = grid["pop"] * grid["elderly_share"]
    # 격자가 행정동 경계에 걸치면 행이 나뉘므로 (격자, 일자, 시간)으로 먼저 합친 뒤 시간 평균을 낸다.
    per_hour = grid.groupby(["CELL_ID", "일자", "시간"], as_index=False)[["pop", "elderly"]].sum(min_count=1)
    cells = per_hour.groupby("CELL_ID", as_index=False)[["pop", "elderly"]].mean()
    cells["elderly_share"] = cells["elderly"] / cells["pop"].where(cells["pop"] > 0)

    geometry = gpd.read_file(GRID_SHP)[["CELL_ID", "geometry"]].to_crs(5179)
    geometry["cx"] = geometry.geometry.centroid.x
    geometry["cy"] = geometry.geometry.centroid.y
    return cells.merge(geometry[["CELL_ID", "cx", "cy"]], on="CELL_ID", how="inner")


def build_stop_ridership() -> pd.DataFrame:
    ride = pd.read_csv(RIDERSHIP_CSV, encoding="cp949", low_memory=False, dtype={"노선번호": str, "표준버스정류장ID": str})
    board_cols = [c for c in ride.columns if c.endswith("승차총승객수")]
    alight_cols = [c for c in ride.columns if c.endswith("하차총승객수")]
    out = ride[["노선번호", "표준버스정류장ID"]].rename(columns={"노선번호": "노선명", "표준버스정류장ID": "NODE_ID"})
    out["boardings_per_day"] = ride[board_cols].sum(axis=1) / DAYS_IN_MONTH
    out["alightings_per_day"] = ride[alight_cols].sum(axis=1) / DAYS_IN_MONTH
    out["peak_hour_boardings"] = ride[board_cols].max(axis=1) / DAYS_IN_MONTH
    return out.groupby(["노선명", "NODE_ID"], as_index=False).sum()


def main() -> None:
    print("[1/4] 격자 낮 시간 생활인구·고령 인구 추정...")
    cached = TRANSIT / "grid_population_daytime.csv"
    if not any(GRID_POP_DIR.glob("*.csv")) and cached.exists():
        # 생활인구 원자료(약 800MB)가 없는 환경에서는 이전에 만든 격자 결과를 그대로 쓴다.
        print(f"  생활인구 원자료가 없어 기존 결과를 사용: {cached}")
        cells = pd.read_csv(cached)
    else:
        cells = build_daytime_population()
        cells.to_csv(cached, index=False, encoding="utf-8-sig")
    print(f"  격자 {len(cells):,}개, 서울 낮 인구 합 {cells['pop'].sum():,.0f}, 고령 비율 {cells['elderly'].sum() / cells['pop'].sum():.1%}")

    print("[2/4] 정류소별 승하차...")
    ridership = build_stop_ridership()
    ridership.to_csv(TRANSIT / "stop_ridership.csv", index=False, encoding="utf-8-sig")

    print("[3/4] 노선 단위 수요 지표...")
    routes = pd.read_csv(TRANSIT / "routes.csv", dtype={"ROUTE_ID": str})
    stops = pd.read_csv(TRANSIT / "bus_stops.csv", dtype={"NODE_ID": str})
    route_stops = pd.read_excel(ROUTE_STOP_XLSX, dtype={"ROUTE_ID": str, "NODE_ID": str})
    route_stops["노선명"] = route_stops["노선명"].astype(str)
    weights = branch_stop_weights(route_stops[route_stops["ROUTE_ID"].isin(routes["ROUTE_ID"])])
    membership = route_stops[["ROUTE_ID", "NODE_ID"]]
    membership = membership[membership["ROUTE_ID"].isin(routes["ROUTE_ID"])].drop_duplicates()

    stop_xy = gpd.GeoSeries(gpd.points_from_xy(stops["X좌표"], stops["Y좌표"]), crs=4326).to_crs(5179)
    stops["sx"], stops["sy"] = stop_xy.x.to_numpy(), stop_xy.y.to_numpy()
    stops["no_alternative"] = (stops["dist_to_station_m"] > STATION_WALK_M) & ~stops["trunk_stop_within_200m"]
    cell_tree = cKDTree(cells[["cx", "cy"]].to_numpy())

    rows = []
    for route_id, group in membership.merge(stops, on="NODE_ID", how="left").groupby("ROUTE_ID"):
        meta = routes.loc[routes["ROUTE_ID"] == route_id].iloc[0]
        hits = cell_tree.query_ball_point(group[["sx", "sy"]].dropna().to_numpy(), STOP_CATCHMENT_M)
        cell_idx = sorted({i for hit in hits for i in hit})
        catchment = cells.iloc[cell_idx]
        ride = ridership[(ridership["노선명"] == ridership_key(meta["노선명"])) & ridership["NODE_ID"].isin(group["NODE_ID"])].copy()
        ride["boardings_per_day"] *= [weights.get((route_id, n), 1.0) for n in ride["NODE_ID"]]
        ride = ride.merge(group[["NODE_ID", "no_alternative"]], on="NODE_ID", how="left")
        boardings = ride["boardings_per_day"].sum()
        rows.append({
            "ROUTE_ID": route_id, "노선명": meta["노선명"], "kind": meta["kind"], "length_km": meta["length_km"],
            "n_stops": group["NODE_ID"].nunique(),
            "boardings_per_day": boardings if len(ride) else np.nan,
            "boardings_per_km": boardings / meta["length_km"] if len(ride) and meta["length_km"] > 0 else np.nan,
            "catchment_pop_day": catchment["pop"].sum(),
            "catchment_elderly_day": catchment["elderly"].sum(),
            "catchment_elderly_share": catchment["elderly"].sum() / catchment["pop"].sum() if catchment["pop"].sum() > 0 else np.nan,
            "no_alt_stop_share": group["no_alternative"].mean(),
            "no_alt_boarding_share": (ride.loc[ride["no_alternative"].fillna(False), "boardings_per_day"].sum() / boardings) if boardings > 0 else np.nan,
            "median_dist_to_station_m": group["dist_to_station_m"].median(),
        })
    demand = pd.DataFrame(rows)
    demand.to_csv(TRANSIT / "route_demand.csv", index=False, encoding="utf-8-sig")

    print("[4/4] 요약")
    village = demand[demand["kind"] == "마을버스"]
    print(village[["boardings_per_day", "boardings_per_km", "catchment_elderly_day", "catchment_elderly_share",
                   "no_alt_stop_share", "no_alt_boarding_share", "median_dist_to_station_m"]].describe().round(3).to_string())
    print(f"  승하차 매칭 안 된 마을버스 노선: {village['boardings_per_day'].isna().sum()}개")
    print(f"  저장: {TRANSIT}")


if __name__ == "__main__":
    main()
