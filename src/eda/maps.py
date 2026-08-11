"""
[역할]
1. 파이프라인(01~05) 및 모델(01,02) 완료 후 단독 실행 시, 
   지정된 시각(7월 9일~13일 0800, 1800, 2300 총 15개)에 대해 12번(날씨) 및 13번(속도) 스냅샷을 자동 일괄 생성합니다.
2. Streamlit 웹 대시보드(app/main.py)용 통합 연산 엔진으로서,
   15번(In-Memory VT-CPEM 에너지 연산)과 16번(In-Memory 다익스트라 최적 경로 탐색)을 동적으로 결합하여
   Folium 2D 지도, PyDeck 3D 지도 및 4대 에너지 분석 통계용 데이터를 0.1초 내로 제공합니다.

[단독 실행 방식]
python src/eda/maps.py
"""

from __future__ import annotations

import importlib
import json
import sys
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import folium
import pydeck as pdk

# 프로젝트 최상위 루트 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
INTERIM_DIR = PROJECT_ROOT / "data" / "interim"

SEOUL_LINK_SHP = INTERIM_DIR / "seoul_link.shp"
DIMENSION_PATH = PROCESSED_DIR / "seoul_link_dimension.csv"

# In-Memory 15번 및 16번 모듈 연동
m15 = importlib.import_module("src.routing.15_add_energy_cost")
calculate_energy_dataframe = m15.calculate_energy_dataframe

m16 = importlib.import_module("src.routing.16_eco_route")
prepare_spatial_cache = m16.prepare_spatial_cache
find_routes_dataframe = m16.find_routes_dataframe
SEOUL_POINTS = m16.SEOUL_POINTS

# 사용자 지정 스냅샷 대상 일시 (7월 9일 ~ 13일, 08:00 / 18:00 / 23:00)
TARGET_DATES = ["20260709", "20260710", "20260711", "20260712", "20260713"]
TARGET_HOURS = ["0800", "1800", "2300"]


# ==========================================
# 1. 스냅샷 자동 생성 파이프라인 (12번 & 13번)
# ==========================================
def build_snapshot_for_tm(tm: str) -> None:
    """단일 시각(tm)에 대한 12번(날씨) 및 13번(속도) 스냅샷 자동 생성"""
    weather_path = PROCESSED_DIR / "weather_snapshot" / f"weather_snapshot_{tm}.csv"
    speed_path = PROCESSED_DIR / "seoul_all_link_speed" / f"seoul_all_link_speed_{tm}.csv"

    # 12번: 기상 스냅샷 생성
    if not weather_path.exists():
        print(f"  [12번] 기상 스냅샷 생성 중... ({tm})")
        cmd_12 = [sys.executable, str(PROJECT_ROOT / "src" / "routing" / "12_build_all_link_weather_snapshot.py"), "--tm", tm]
        subprocess.run(cmd_12, check=True)
    else:
        print(f"  [12번] 기상 스냅샷 존재함: {weather_path.name}")

    # 13번: 속도 추론 스냅샷 생성
    if not speed_path.exists():
        print(f"  [13번] 속도 추론 스냅샷 생성 중... ({tm})")
        cmd_13 = [sys.executable, str(PROJECT_ROOT / "src" / "routing" / "13_predict_all_link_speed.py"), "--tm", tm]
        subprocess.run(cmd_13, check=True)
    else:
        print(f"  [13번] 속도 추론 스냅샷 존재함: {speed_path.name}")


def build_all_target_snapshots() -> None:
    """7월 9일~13일 15개 타겟 시각 전체 스냅샷 일괄 빌드"""
    print("=" * 65)
    print("🚀 [maps.py] 7월 9일~13일 타겟 시각 12/13 스냅샷 자동 생성 시작")
    print("=" * 65)

    total_count = len(TARGET_DATES) * len(TARGET_HOURS)
    idx = 1

    for date_str in TARGET_DATES:
        for hour_str in TARGET_HOURS:
            tm = f"{date_str}{hour_str}"
            print(f"\n[{idx}/{total_count}] 타겟 시각: {tm} 처리 중...")
            build_snapshot_for_tm(tm)
            idx += 1

    print("\n" + "=" * 65)
    print("✅ 모든 타겟 시각 스냅샷 준비 완료!")
    print("=" * 65)


# ==========================================
# 2. In-Memory 시각화 및 라우팅 오케스트레이터
# ==========================================
def load_integrated_snapshot(tm: str) -> pd.DataFrame:
    """
    13번(속도/통행시간) 스냅샷과 정적 차원 데이터(seoul_link_dimension)를 메모리 상에서 병합
    """
    speed_path = PROCESSED_DIR / "seoul_all_link_speed" / f"seoul_all_link_speed_{tm}.csv"
    if not speed_path.exists():
        print(f"⚠️ {tm} 속도 스냅샷이 없어 즉시 생성합니다...")
        build_snapshot_for_tm(tm)

    speed_df = pd.read_csv(speed_path, dtype={"LINK_ID": str, "F_NODE": str, "T_NODE": str}, encoding="utf-8-sig")
    dim_df = pd.read_csv(DIMENSION_PATH, dtype={"LINK_ID": str}, encoding="utf-8-sig")

    cols_to_use = [c for c in dim_df.columns if c not in speed_df.columns or c == "LINK_ID"]
    full_df = speed_df.merge(dim_df[cols_to_use], on="LINK_ID", how="left")
    return full_df


def prepare_visualization_pipeline(
    tm: str,
    regen: bool = True,
    mass: float | None = None,
    load_factor: float = 0.0,
    start_latlon: tuple[float, float] | None = None,
    end_latlon: tuple[float, float] | None = None,
    spatial_cache: tuple[gpd.GeoDataFrame, pd.DataFrame, dict] | None = None
) -> tuple[pd.DataFrame, dict | None, pd.DataFrame | None]:
    """
    [Streamlit main.py 연동 핵심 오케스트레이션 함수]
    1. 13번 스냅샷 및 차원 테이블 로드
    2. 15번 In-Memory VT-CPEM 에너지 계산 실행
    3. 16번 In-Memory 최적 경로 탐색 실행 (OD 전달 시)
    """
    # 1. 통합 스냅샷 로드
    base_df = load_integrated_snapshot(tm)

    # 2. 15번 동적 에너지 연산
    energy_df = calculate_energy_dataframe(
        df=base_df,
        regen=regen,
        mass=mass,
        load_factor=load_factor
    )

    # 3. 16번 동적 경로 탐색
    routes_geojson = None
    summary_df = None

    if start_latlon and end_latlon:
        link_gdf, nodes_df, link_geom_dict = spatial_cache if spatial_cache else (None, None, None)
        routes_geojson, summary_df = find_routes_dataframe(
            energy_df=energy_df,
            start_latlon=start_latlon,
            end_latlon=end_latlon,
            link_gdf=link_gdf,
            nodes_df=nodes_df,
            link_geom_dict=link_geom_dict
        )

    return energy_df, routes_geojson, summary_df


# ==========================================
# 3. 지도 렌더링 엔진 (Folium 2D & PyDeck 3D)
# ==========================================
def render_folium_map(
    energy_df: pd.DataFrame,
    routes_geojson: dict | None = None
) -> folium.Map:
    """2D Folium 지도 및 최적 경로 Layer 중첩"""
    m = folium.Map(location=[37.5665, 126.9780], zoom_start=11, tiles="cartodbpositron")

    if routes_geojson and "features" in routes_geojson and routes_geojson["features"]:
        color_map = {
            "fastest": "#1f77b4",  # 파란색 (최단시간)
            "eco": "#2ca02c",      # 초록색 (에너지최적)
            "shortest": "#d62728"  # 빨간색 (최단거리)
        }

        def style_fn(feature):
            rtype = feature["properties"].get("route_type", "eco")
            return {
                "color": color_map.get(rtype, "#3388ff"),
                "weight": 6,
                "opacity": 0.85
            }

        folium.GeoJson(
            routes_geojson,
            style_function=style_fn,
            tooltip=folium.GeoJsonTooltip(
                fields=["label", "distance_km", "time_min", "energy_wh"],
                aliases=["유형:", "거리(km):", "소요시간(분):", "에너지소비(Wh):"]
            )
        ).add_to(m)

    return m


def render_pydeck_3d_map(
    energy_df: pd.DataFrame
) -> pdk.Deck:
    """3D PyDeck 경사도/속도 입체 관제 지도"""
    df_sample = energy_df.copy().sample(n=min(8000, len(energy_df)))
    df_sample["elevation"] = np.maximum(df_sample["slope_pct"], 0.0) * 150.0

    layer = pdk.Layer(
        "ColumnLayer",
        df_sample,
        get_position=["link_lon", "link_lat"] if "link_lon" in df_sample.columns else ["lon", "lat"],
        get_elevation="elevation",
        elevation_scale=1,
        radius=30,
        get_fill_color="[255, 128, 0, 180]",
        pickable=True
    )

    view_state = pdk.ViewState(latitude=37.5665, longitude=126.9780, zoom=11, pitch=45)
    return pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip={"text": "속도: {speed_kmh} km/h\n소비 전력: {ev_wh} Wh"})


# ==========================================
# 4. 스크립트 단독 실행 엔트리포인트
# ==========================================
if __name__ == "__main__":
    build_all_target_snapshots()