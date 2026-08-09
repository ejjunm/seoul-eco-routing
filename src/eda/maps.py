"""
[역할]
- Folium 기반의 2D 인터랙티브 지도와 PyDeck 기반의 3D 물리 시각화를
  제공하는 통합 시각화 엔진 모듈입니다.
- Streamlit 대시보드(main.py)를 위한 모든 데이터 준비(Load & Merge)와 
  시각화 객체 생성 역할만을 전담합니다.
- 또한, `python -m src.eda.maps`로 직접 실행 시 시각화에 필요한 모든
  스냅샷 데이터를 생성하는 오케스트레이션 기능을 수행합니다.

[주요 기능]
- (실행 시) 13, 15, 12번 스크립트를 순차 실행하고 그 결과와 차원 테이블을 병합하여
  최종 `seoul_all_link_eco_snapshot_{tm}.csv` 파일 생성
- (main.py에서 호출 시) 사전 연산된 통합 에코 스냅샷과 공간 데이터(Shapefile) 결합
- 사용자가 선택한 변수(속도, 에너지, 강수량 등)에 따른 동적 색상 매핑
- Folium (2D) 및 PyDeck (3D) 동적 맵 객체 생성 함수 제공
"""
import json
import subprocess
import sys
from pathlib import Path

import folium
import numpy as np
import pandas as pd
import geopandas as gpd
import pydeck as pdk
import streamlit as st

# =====================================================================
# 0. 프로젝트 경로 탐색 헬퍼
# =====================================================================
def find_project_root() -> Path:
    """스크립트 실행, streamlit 실행 양쪽에서 모두 프로젝트 루트를 찾습니다."""
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / "data").exists() and (parent / "src").exists():
            return parent
    # Streamlit Cloud 등 경로가 다른 환경 대비
    return Path.cwd()

# =====================================================================
# 1. 데이터 준비 (Streamlit 앱에서 호출)
# =====================================================================
@st.cache_data(show_spinner=False)
def load_eco_snapshot(tm: str, project_root: Path) -> gpd.GeoDataFrame:
    """공간 데이터(SHP)와 사전 생성된 에코 스냅샷을 병합하여 시각화 준비를 끝냅니다."""
    shp_path = project_root / "data" / "interim" / "seoul_link.shp"
    eco_csv_path = project_root / "data" / "processed" / "seoul_all_link_eco_snapshot" / f"seoul_all_link_eco_snapshot_{tm}.csv"

    if not shp_path.exists():
        st.error(f"도로망 형상 파일이 없습니다: {shp_path}")
        return gpd.GeoDataFrame()
    if not eco_csv_path.exists():
        return gpd.GeoDataFrame()

    # SHP 읽기
    gdf = gpd.read_file(shp_path, dtype={"LINK_ID": str})
    if gdf.crs is None or gdf.crs.to_string().upper() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")

    # CSV 읽기
    df_eco = pd.read_csv(eco_csv_path, dtype={"LINK_ID": str})

    # 🛠️ 컬럼 충돌 방지: SHP에서는 위치 정보(geometry)와 조인 키(LINK_ID)만 추출
    gdf_geom = gdf[["LINK_ID", "geometry"]]

    # 병합 실행 (_x, _y 접미사 발생 방지)
    return gdf_geom.merge(df_eco, on="LINK_ID", how="inner")



# =====================================================================
# 2. 동적 색상 할당기
# =====================================================================
def get_color_scheme(val, col_name, q25, q50, q75):
    """선택한 변수에 맞춰 2D/3D 공통 색상을 반환합니다."""
    if pd.isna(val): return "#808080", [128, 128, 128, 100]
    
    # 속도, 제한속도: 높을수록 긍정적 (초록색)
    if "speed" in col_name.lower() or "limit" in col_name.lower():
        if val < q25: return "#d73027", [215, 48, 39, 230] # Red
        if val < q50: return "#fc8d59", [252, 141, 89, 230] # Orange
        if val < q75: return "#fee08b", [254, 224, 139, 230] # Yellow
        return "#1a9850", [26, 152, 80, 230] # Green
    else:
        # 에너지, 강수량, 복잡도, 방지턱, 경사 등: 높을수록 부정적/위험 (빨간색)
        if val <= q25: return "#1a9850", [26, 152, 80, 230]
        if val <= q50: return "#fee08b", [254, 224, 139, 230]
        if val <= q75: return "#fc8d59", [252, 141, 89, 230]
        return "#d73027", [215, 48, 39, 230]

# =====================================================================
# 3. 2D Folium Map 생성
# =====================================================================
def create_folium_map(gdf: gpd.GeoDataFrame, color_col: str) -> folium.Map:
    if gdf.empty: return folium.Map(location=[37.5665, 126.9780], zoom_start=11)
        
    q25, q50, q75 = gdf[color_col].quantile([0.25, 0.5, 0.75])
    if q25 == q75: q75 += 0.001

    m = folium.Map(location=[37.5665, 126.9780], zoom_start=11.5, tiles="CartoDB dark_matter")
    
    # NaN 값 때문에 to_json이 실패하는 경우 방지
    gdf_copy = gdf.copy()
    for col in gdf_copy.columns:
        if gdf_copy[col].dtype.kind in 'fc':
            gdf_copy[col] = gdf_copy[col].fillna(np.nan)
    geojson_data = json.loads(gdf_copy.to_json())


    def style_function(feature):
        val = feature["properties"].get(color_col)
        hex_color, _ = get_color_scheme(val, color_col, q25, q50, q75)
        return {"color": hex_color, "weight": 3, "opacity": 0.85}

    # 팝업에 표시할 컬럼들
    popup_cols = ["LINK_ID", "ROAD_NAME", color_col, "MAX_SPD", "LANES", "ROAD_RANK", "slope_pct", "precip_mm", "school_zone_count", "node_complexity", "fuel_ml", "ev_wh"]
    
    folium.GeoJson(
        geojson_data,
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(fields=["ROAD_NAME", color_col]),
        popup=folium.GeoJsonPopup(fields=[c for c in popup_cols if c in gdf.columns])
    ).add_to(m)

    return m

# =====================================================================
# 4. 3D PyDeck Map 생성
# =====================================================================
def create_pydeck_map(gdf: gpd.GeoDataFrame, color_col: str, elevation_col: str = "slope_pct") -> pdk.Deck:
    if gdf.empty: return pdk.Deck(initial_view_state=pdk.ViewState(latitude=37.5665, longitude=126.9780, zoom=10))

    df_deck = pd.DataFrame(gdf.drop(columns=["geometry"]))
    df_deck["path"] = gdf["geometry"].apply(lambda geom: [[float(c[0]), float(c[1])] for c in geom.coords] if geom else [])

    q25, q50, q75 = df_deck[color_col].quantile([0.25, 0.5, 0.75])
    if q25 == q75: q75 += 0.001
    
    df_deck["color_rgba"] = df_deck[color_col].apply(lambda val: get_color_scheme(val, color_col, q25, q50, q75)[1])
    
    if elevation_col in df_deck:
        df_deck["elevation_val"] = df_deck[elevation_col].fillna(0.0).abs() * 30
    else:
        df_deck["elevation_val"] = 0.0

    layer = pdk.Layer(
        "PathLayer",
        df_deck,
        pickable=True,
        get_path="path",
        get_color="color_rgba",
        width_min_pixels=2.5,
        get_width=3,
        get_elevation="elevation_val",
        elevation_scale=1,
        extruded=True
    )

    tooltip_html = f"<b>Road:</b> {{ROAD_NAME}} <br/><b>{color_col}:</b> {{{color_col}}}<br/><b>경사도(Z축):</b> {{{elevation_col}}}"

    return pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(latitude=37.5665, longitude=126.9780, zoom=11, pitch=45),
        map_style="mapbox://styles/mapbox/dark-v10",
        tooltip={"html": tooltip_html, "style": {"color": "white", "backgroundColor": "#222", "fontSize": "12px"}}
    )

# =====================================================================
# 5. 데이터 생성 오케스트레이션 (스크립트 실행 시)
# =====================================================================
def run_subprocess(cmd: list[str], project_root: Path):
    """subprocess를 실행하고 에러를 체크하는 헬퍼. Windows의 cp949 인코딩을 처리합니다."""
    import platform
    encoding = 'cp949' if platform.system() == 'Windows' else 'utf-8'
    try:
        # Streamlit 앱에서 실행 시 출력을 숨기기 위해 stdout, stderr 파이프
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=project_root, encoding=encoding)
        print(result.stdout)
        if result.stderr:
            print("--- stderr ---")
            print(result.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Error executing: {' '.join(cmd)}")
        print(e.stdout)
        print(e.stderr)
        raise

def prepare_visualization_data(dates: list[str], hours: list[str], project_root: Path, st_progress=None):
    """
    대시보드 시각화에 필요한 모든 스냅샷 데이터를 생성하는 오케스트레이션 함수.
    """
    from datetime import datetime, timedelta
    py_executable = sys.executable
    total_steps = len(dates) * len(hours) * 3 + 1 # 스텝 수 (dimension 확인 + 3 스크립트)
    current_step = 0

    def update_progress(message):
        nonlocal current_step
        current_step += 1
        if st_progress:
            progress = min(current_step / total_steps, 1.0)
            st_progress.progress(progress, text=f"({current_step}/{total_steps}) {message}")
        print(message)

    update_progress("Step 1: 기본 차원 테이블 확인...")
    dim_path = project_root / "data" / "processed" / "seoul_link_dimension.csv"
    if not dim_path.exists():
        update_progress("`seoul_link_dimension.csv` 생성 중...")
        run_subprocess([py_executable, str(project_root / "src/pipeline/04_build_link_dimension.py")], project_root)
    else:
        update_progress("`seoul_link_dimension.csv` 확인 완료.")

    print("기본 차원 테이블 로딩...")
    df_dim = pd.read_csv(dim_path, dtype={"LINK_ID": str})

    # 12번 스크립트의 물리적 위치를 루프 시작 전에 미리 파악
    script12_path = project_root / "src/routing/12_build_all_link_weather_snapshot.py"
    if not script12_path.exists():
        script12_path = project_root / "src/12_build_all_link_weather_snapshot.py"
    if not script12_path.exists():
        raise FileNotFoundError(f"12번 기상 스냅샷 스크립트를 찾을 수 없습니다: {script12_path}")

    for date in dates:
        for hour in hours:
            tm = f"{date}{hour}00"
            msg_prefix = f"[{tm}]"

            # --train-end 인자를 예측일 하루 전으로 설정
            pred_date = datetime.strptime(date, "%Y%m%d")
            train_end_date = pred_date - timedelta(days=1)
            train_end_str = train_end_date.strftime("%Y%m%d")

            # CORRECTED ORDER
            update_progress(f"{msg_prefix} Step 2: 날씨 데이터 처리...")
            run_subprocess([py_executable, str(script12_path), "--tm", tm], project_root)

            update_progress(f"{msg_prefix} Step 3: 전체 링크 속도 예측...")
            run_subprocess([
                py_executable,
                str(project_root / "src/routing/13_predict_all_link_speed.py"),
                "--tm", tm,
                "--train-end", train_end_str
            ], project_root)

            update_progress(f"{msg_prefix} Step 4: 에너지 소비 계산...")
            run_subprocess([py_executable, str(project_root / "src/routing/15_add_energy_cost.py"), "--tm", tm], project_root)
            
            update_progress(f"{msg_prefix} Step 5: 모든 데이터 소스 병합...")
            
            try:
                df_energy = pd.read_csv(project_root / "data" / "processed" / f"seoul_all_link_energy_{tm}.csv", dtype={"LINK_ID": str})
                df_weather = pd.read_csv(project_root / "data" / "processed" / f"seoul_all_link_weather_{tm}.csv", dtype={"LINK_ID": str})

                # `df_dim`에 시간 기반 데이터를 병합
                final_df = df_dim.merge(df_energy, on="LINK_ID", how="left")
                final_df = final_df.merge(df_weather[["LINK_ID", "precip_mm"]], on="LINK_ID", how="left")

                output_path = project_root / "data" / "processed" / "seoul_all_link_eco_snapshot" / f"seoul_all_link_eco_snapshot_{tm}.csv"
                
                # 시각화에 필요한 최종 컬럼만 선택하여 파일 크기 최적화
                viz_cols = [
                    "LINK_ID", "ROAD_NAME", "ROAD_RANK", "MAX_SPD", "LANES", 
                    "LENGTH", "speed_kmh", "travel_time_sec", "slope_pct", "abs_slope_pct",
                    "precip_mm", "bus_lane_ratio", "traffic_volume_aadt", 
                    "school_zone_count", "accident_hotspot_count", 
                    "speed_bump_count", "node_complexity", "dist_cbd",
                    "fuel_ml", "ev_wh", "co2_ice_g", "co2_ev_g"
                ]
                
                # 중복 컬럼 처리
                final_df = final_df.loc[:, ~final_df.columns.duplicated()]
                
                cols_to_save = [c for c in viz_cols if c in final_df.columns]
                
                final_df[cols_to_save].to_csv(output_path, index=False, encoding='utf-8-sig')
                print(f"✅ {msg_prefix} 성공적으로 스냅샷 저장: {output_path.name}")

            except FileNotFoundError as e:
                print(f"🚨 {msg_prefix} 데이터 병합 실패: {e}. 몇몇 하위 스크립트가 파일을 생성하지 않은 것 같습니다.")


if __name__ == "__main__":
    """
    이 스크립트를 직접 실행하면 지정된 날짜와 시간에 대한 모든 에코 스냅샷을 생성합니다.
    사용법: python -m src.eda.maps
    """
    project_root = find_project_root()
    print(f"프로젝트 루트: {project_root}")
    
    # 여기서 날짜와 시간 지정
    TARGET_DATES = ["20260709", "20260710", "20260711", "20260712", "20260713"]
    TARGET_HOURS = ["08", "12", "18", "23"]
    
    print(f"총 {len(TARGET_DATES) * len(TARGET_HOURS)}개의 타임스탬프에 대한 데이터 생성을 시작합니다.")
    prepare_visualization_data(TARGET_DATES, TARGET_HOURS, project_root)
    print("모든 작업이 완료되었습니다.")
