# app/main.py
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

# 프로젝트 루트 경로 설정 및 sys.path 추가
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# src/eda/maps.py 모듈 연동 (에너지 및 라우팅 오케스트레이터)
import src.eda.maps as maps

# Streamlit 대지 기본 설정
st.set_page_config(
    page_title="서울시 에코라우팅 관제 대시보드",
    page_icon="🚗",
    layout="wide"
)

# ----------------------------------------------------
# 1. 공간 캐시 및 기본 데이터 초기화 (@st.cache_resource)
# ----------------------------------------------------
@st.cache_resource
def init_spatial_cache():
    """공간 데이터 및 그래프 노드 캐시 생성 (최초 1회 실행)"""
    return maps.prepare_spatial_cache()

spatial_cache = init_spatial_cache()

# ----------------------------------------------------
# 2. 사이드바 - 제어 패널 (Control Panel)
# ----------------------------------------------------
st.sidebar.title("🎛️ 분석 옵션 제어")

# 1) 분석 일시 선택 (7월 9일 ~ 13일, 08:00 / 18:00 / 23:00)
st.sidebar.subheader("📅 분석 시각 선택")
selected_date = st.sidebar.selectbox("날짜 선택", maps.TARGET_DATES, index=0)
selected_hour = st.sidebar.selectbox("시간대 선택", maps.TARGET_HOURS, index=0)
tm = f"{selected_date}{selected_hour}"

# 2) 전기차(BEV) 및 물리 변수 설정
st.sidebar.subheader("⚡ 전기차(BEV) 파라미터")
regen_option = st.sidebar.checkbox("회생제동(Regen) 적용", value=True)
load_factor = st.sidebar.slider("차량 적재율 (0: 공차 ~ 1: 만차)", min_value=0.0, max_value=1.0, value=0.0, step=0.1)

# 3) 경로 탐색 OD(출발지/목적지) 선택
st.sidebar.subheader("📍 경로 탐색 (OD)")
point_names = list(maps.SEOUL_POINTS.keys())
origin_name = st.sidebar.selectbox("출발지 선택", point_names, index=1)  # 서울시청
dest_name = st.sidebar.selectbox("목적지 선택", point_names, index=8)   # 북한산우이

start_latlon = maps.SEOUL_POINTS[origin_name]
end_latlon = maps.SEOUL_POINTS[dest_name]

# ----------------------------------------------------
# 3. 데이터 파이프라인 연산 실행
# ----------------------------------------------------
with st.spinner(f"시각 {tm} 데이터를 처리 중입니다..."):
    energy_df, routes_geojson, summary_df = maps.prepare_visualization_pipeline(
        tm=tm,
        regen=regen_option,
        load_factor=load_factor,
        start_latlon=start_latlon,
        end_latlon=end_latlon,
        spatial_cache=spatial_cache
    )

st.title("🚗 서울시 친환경 전기차(BEV) 에코라우팅 관제 시스템")
st.caption(f"분석 대상 시각: {tm[:4]}-{tm[4:6]}-{tm[6:8]} {tm[8:10]}:00 | 출발: {origin_name} ➔ 도착: {dest_name}")

# ----------------------------------------------------
# 4. 요약 대시보드 지표 (KPI Cards)
# ----------------------------------------------------
if summary_df is not None and not summary_df.empty:
    st.subheader("📊 경로 탐색 요약 결과")
    col1, col2, col3, col4 = st.columns(4)
    
    fastest_row = summary_df[summary_df["route_type"] == "fastest"]
    eco_row = summary_df[summary_df["route_type"] == "eco"]
    
    if not fastest_row.empty and not eco_row.empty:
        fast_time = fastest_row["time_min"].values[0]
        eco_time = eco_row["time_min"].values[0]
        fast_wh = fastest_row["energy_wh"].values[0]
        eco_wh = eco_row["energy_wh"].values[0]
        
        saving_pct = eco_row["energy_saving_pct"].values[0] if "energy_saving_pct" in eco_row.columns else round((fast_wh - eco_wh) / fast_wh * 100, 1)
        
        col1.metric("⏱️ 최단시간 소요", f"{fast_time} 분", f"{fast_wh} Wh")
        col2.metric("🌱 에코경로 소요", f"{eco_time} 분", f"{eco_wh} Wh")
        col3.metric("⚡ 에너지 절감률", f"{saving_pct}%", f"{round(fast_wh - eco_wh, 1)} Wh 절약", delta_color="normal")
        col4.metric("🛣️ 에코경로 거리", f"{eco_row['distance_km'].values[0]} km", f"CO2: {eco_row['co2_g'].values[0]} g")

# ----------------------------------------------------
# 5. 시각화 지도 탭 (2D Folium & 3D PyDeck)
# ----------------------------------------------------
tab1, tab2, tab3 = st.tabs(["🗺️ 2D 라우팅 지도 (Folium)", "🏙️ 3D 경사도 관제 (PyDeck)", "📋 전체 링크 데이터 탐색"])

with tab1:
    st.markdown("### 2D 최단시간 vs 에코 경로 비교")
    st.write("🔵 **파란색**: 최단시간 경로 | 🟢 **초록색**: 에너지 최적(Eco) 경로 | 🔴 **빨간색**: 최단거리 경로")
    
    folium_map = maps.render_folium_map(energy_df, routes_geojson)
    st_folium(folium_map, width=1200, height=600)

with tab2:
    st.markdown("### 3D 도로 경사도 및 속도/에너지 관제")
    st.write("도로의 실제 경사도(`slope_pct`)를 높이(Z축)로 시각화한 3D 입체 지도입니다.")
    
    deck = maps.render_pydeck_3d_map(energy_df)
    st.pydeck_chart(deck)

with tab3:
    st.markdown("### 🔍 서울시 링크별 속도/에너지 통합 데이터")
    
    # 도로명 필터링 기능
    search_keyword = st.text_input("도로명/LINK_ID 검색", "")
    filtered_df = energy_df
    if search_keyword:
        if "ROAD_NAME" in energy_df.columns:
            filtered_df = energy_df[
                energy_df["ROAD_NAME"].astype(str).str.contains(search_keyword) | 
                energy_df["LINK_ID"].astype(str).str.contains(search_keyword)
            ]
        else:
            filtered_df = energy_df[energy_df["LINK_ID"].astype(str).str.contains(search_keyword)]
            
    st.dataframe(
        filtered_df[[
            "LINK_ID", "ROAD_RANK", "MAX_SPD", "speed_kmh", "slope_pct", 
            "precip_mm", "travel_time_sec", "ev_wh", "co2_ev_g", "tier"
        ]].head(500),
        use_container_width=True
    )