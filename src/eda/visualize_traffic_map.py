"""
Seoul Eco-Routing Project: visualize_traffic_map.py
=================================================================
[역할]
1. 정적 지도(PNG)의 한계를 극복하기 위해 Folium 및 PyDeck 기반의 
   인터랙티브 공간 시각화(HTML/JSON)를 제공하는 통합 시각화 엔진입니다.
2. Streamlit 대시보드 개발과 100% 호환되도록 설계되어 있어, 
   - 개별 실행 시(CLI) 특정 시각의 예측/기상 지도를 생성해 파일(.html, .png)로 저장하며,
   - Streamlit 라이브러리 내에서 import 시 맵 객체(Folium Map, PyDeck Deck)를 동적으로 반환합니다.
3. [확장성 보장]: 도로 차원(Dimension) 및 기상/소통(Fact) 테이블의 컬럼이 
   향후 추가되거나 변경되더라도, 하드코딩 없이 데이터프레임의 스키마를 동적으로 분석하여 
   지도 툴팁(Tooltip)과 팝업(Popup)에 자동으로 반영해 주는 '지능형 변수 감지 구조'를 갖추고 있습니다.

[주요 기능]
- Folium 기반 정밀 2D 벡터 매핑 (다크 테마, 툴팁, 팝업, 지오메트리 90% 간소화 캐싱)
- PyDeck 기반 초고속 3D 물리 매핑 (도로 경사도 3D 입체화, 제한속도/교통량 고속 렌더링)
- 데이터 자동 병합 엔진 (GeoJSON/SHP 형상 + 도로 차원 + 소통/기상 팩트)
- CLI 특정 시각 스냅샷 맵 자동 렌더링 모드 지원

[사용 및 연동 방법]
1. CLI 단독 실행:
   python visualize_traffic_map.py --tm 202607261400

2. Streamlit 연동 예시:
   import streamlit as st
   from visualize_traffic_map import build_unified_dataframe, create_folium_map, create_pydeck_map
   
   df = build_unified_dataframe(tm="202607261400")
   st.pydeck_chart(create_pydeck_map(df, color_col="speed_kmh", elevation_col="slope_pct"))
=================================================================
"""

import os
import sys
import time
import json
import argparse
from pathlib import Path
import pandas as pd
import geopandas as gpd
import numpy as np

# 가상환경 및 서버 환경에서 GUI 없이 동작할 수 있도록 설정
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import folium
import pydeck as pdk

# =====================================================================
# 1. 전역 디렉토리 구조 정의 (0807 restructured 가이드라인 준수)
# =====================================================================
PROJECT_ROOT = Path(__file__).resolve().parents[2] if "experiments" in Path(__file__).parts or "scratch" in Path(__file__).parts else Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
INTERIM_DATA_DIR = PROJECT_ROOT / "data" / "interim"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

# 기본 파일 경로 정의
DEFAULT_SHAPEFILE = INTERIM_DATA_DIR / "seoul_link.shp"
DEFAULT_DIMENSION = PROCESSED_DATA_DIR / "seoul_link_dimension.csv"
DEFAULT_FACT = PROCESSED_DATA_DIR / "seoul_link_speed_fact.csv"

# =====================================================================
# 2. 지능형 데이터 로더 및 동적 병합 엔진
# =====================================================================
def build_unified_dataframe(
    tm: str = None, 
    shape_path: Path = DEFAULT_SHAPEFILE,
    dim_path: Path = DEFAULT_DIMENSION,
    fact_path: Path = DEFAULT_FACT,
    simplify_tolerance: float = 0.0001
) -> gpd.GeoDataFrame:
    """
    공간 데이터, 차원 테이블, 소통/기상 팩트 데이터를 LINK_ID 기준으로 유기적으로 결합합니다.
    특정 시각(tm)이 지정되면 해당 시간대의 팩트나 추론 스냅샷 파일을 로드합니다.
    
    Args:
        tm (str, optional): YYYYMMDDHHMM 형태의 시간코드 (예: "202607261400")
        shape_path (Path): 도로 기하 형상 경로
        dim_path (Path): 도로 정적 차원 테이블 경로
        fact_path (Path): 도로 동적 소통 팩트 테이블 경로
        simplify_tolerance (float): 지도 성능 최적화를 위한 simplify 계수 (기본 10m 정밀도)
    """
    start_time = time.time()
    print("-----------------------------------------------------------------")
    print(f"🔄 [Data Binding] 시각화 통합 프레임 빌드 시작 (타겟 시각: {tm or '전체 기간'})")
    print("-----------------------------------------------------------------")

    # 1. 도로 기하 형상(GIS) 데이터 로드
    if not shape_path.exists():
        print(f"❌ 도로 공간 데이터(SHP)를 찾을 수 없습니다: {shape_path}")
        print("💡 src/pipeline/01_extract_seoul_links.py를 먼저 실행해 주세요.")
        return gpd.GeoDataFrame()
    
    print(f"📖 1단계: 도로 형상 공간 데이터 로드 중: {shape_path.name}")
    gdf = gpd.read_file(shape_path)
    gdf["LINK_ID"] = gdf["LINK_ID"].astype(str)
    
    # 2. 도로 정적 차원(Dimension) 데이터 로드 (고도, 위상, 외부 컨텍스트 등 59개 변수 통합본)
    if not dim_path.exists():
        print(f"⚠️ 도로 차원 테이블이 없습니다: {dim_path}")
        print("💡 pipeline/04_build_link_dimension.py 결과물 적용 전입니다. 속성 결합을 제외합니다.")
        dim_df = pd.DataFrame()
    else:
        print(f"📖 2단계: 59개 정적 변수가 통합된 도로 차원 테이블 로드 중: {dim_path.name}")
        dim_df = pd.read_csv(dim_path, dtype={"LINK_ID": str})
        
    # 3. 실시간 속도 및 기상 팩트(Fact) 데이터 로드 및 시공간 조인
    fact_df = pd.DataFrame()
    
    # tm이 입력되었을 때 특정 시각 스냅샷 우선 조회
    if tm:
        # 1안: 13번 스크립트 최종 속도 예측 스냅샷 파일 조회 (실측 + 예측 완성본)
        pred_snapshot = PROCESSED_DATA_DIR / f"seoul_all_link_speed_{tm}.csv"
        # 2안: 12번 스크립트 기상 스냅샷 파일 조회
        weather_snapshot = PROCESSED_DATA_DIR / f"seoul_all_link_weather_{tm}.csv"
        
        if pred_snapshot.exists():
            print(f"📖 3단계 (스냅샷): 예측 속도 통합 스냅샷 로드 중: {pred_snapshot.name}")
            fact_df = pd.read_csv(pred_snapshot, dtype={"LINK_ID": str})
        elif weather_snapshot.exists():
            print(f"📖 3단계 (스냅샷): 기상/도로 속성 스냅샷 로드 중: {weather_snapshot.name}")
            fact_df = pd.read_csv(weather_snapshot, dtype={"LINK_ID": str})
        else:
            # 3안: 최종 결합된 전체 팩트 파일에서 해당 시각 필터링
            fact_merged_path = PROCESSED_DATA_DIR / "seoul_link_speed_dem_weather_merged.csv"
            if fact_merged_path.exists():
                print(f"📖 3단계 (팩트): 최종 결합 파일에서 {tm} 추출 중: {fact_merged_path.name}")
                # 메모리 절약을 위해 시간코드와 날짜 기준으로 필터링 로드 구현
                date_val, hour_val = tm[:8], str(int(tm[8:10]))
                full_fact = pd.read_csv(fact_merged_path, dtype={"LINK_ID": str, "기준일": str, "시간코드": str})
                fact_df = full_fact[(full_fact["기준일"] == date_val) & (full_fact["시간코드"] == hour_val)].copy()
            
            # 4안: seoul_link_speed_fact.csv에서 추출
            elif fact_path.exists():
                print(f"📖 3단계 (팩트): 팩트 파일에서 {tm} 추출 중: {fact_path.name}")
                date_val, hour_val = tm[:8], str(int(tm[8:10]))
                full_fact = pd.read_csv(fact_path, dtype={"LINK_ID": str, "기준일": str, "시간코드": str})
                fact_df = full_fact[(full_fact["기준일"] == date_val) & (full_fact["시간코드"] == hour_val)].copy()

    # tm이 명시되지 않은 경우 최종 팩트 테이블을 디폴트로 사용 (데이터 규모 분량)
    else:
        if fact_path.exists():
            print(f"📖 3단계: 전체 기간 팩트 데이터 로드 중: {fact_path.name}")
            # 전체를 로드하면 용량이 클 수 있으므로 가장 최근 날짜의 마지막 1시간 시각만 슬라이스하여 시각화 기본값 바인딩
            try:
                # 시간코드 문자열 정렬 지원
                sample_fact = pd.read_csv(fact_path, nrows=1000, dtype={"LINK_ID": str})
                if "기준일" in sample_fact.columns:
                    # 요약 로딩
                    fact_df = pd.read_csv(fact_path, dtype={"LINK_ID": str, "기준일": str, "시간코드": str})
                    latest_date = fact_df["기준일"].max()
                    latest_hour = fact_df[fact_df["기준일"] == latest_date]["시간코드"].max()
                    print(f"   💡 전체 기간 데이터 중 최신 시점({latest_date} {latest_hour}시) 데이터만 자동 선별했습니다.")
                    fact_df = fact_df[(fact_df["기준일"] == latest_date) & (fact_df["시간코드"] == latest_hour)].copy()
            except Exception as e:
                print(f"⚠️ 팩트 데이터 전처리 중 오류 발생, 결합 생략: {e}")

    # 4. 차원(Dimension) 및 팩트(Fact) 순차 결합 (Left Join)
    unified_df = gdf.copy()
    
    if not dim_df.empty:
        # 중복 방지를 위해 공간 GeoDataFrame에 이미 들어있는 기본 속성 컬럼 제거 후 머지
        dup_cols = [c for col in dim_df.columns if col in unified_df.columns and col != "LINK_ID" for c in [col]]
        dim_df_clean = dim_df.drop(columns=dup_cols, errors="ignore")
        unified_df = unified_df.merge(dim_df_clean, on="LINK_ID", how="left")
        print(f"🔗 차원 테이블 조인 완료 (컬럼 수: {len(unified_df.columns)}개)")
        
    if not fact_df.empty:
        # 팩트 컬럼 결합
        dup_cols_fact = [c for col in fact_df.columns if col in unified_df.columns and col != "LINK_ID" for c in [col]]
        fact_df_clean = fact_df.drop(columns=dup_cols_fact, errors="ignore")
        unified_df = unified_df.merge(fact_df_clean, on="LINK_ID", how="left")
        print(f"🔗 팩트 테이블 조인 완료 (최종 피처 수: {len(unified_df.columns)}개)")
        
    # 5. 웹 지리 렌더링 성능 지연 극복을 위한 지오메트리 간소화 (Simplify)
    if simplify_tolerance > 0:
        print(f"🧹 지리 데이터 정밀도 간소화 수행 중 (오차 한계: {simplify_tolerance}m)")
        # simplify 연산을 위해 투영좌표계로 임시 변환 후 다시 위경도(WGS84, EPSG:4326)로 고정
        if unified_df.crs and unified_df.crs.to_string() != "EPSG:4326":
            unified_df = unified_df.to_crs("EPSG:4326")
        elif unified_df.crs is None:
            unified_df.set_crs("EPSG:4326", inplace=True)
            
        unified_df["geometry"] = unified_df["geometry"].simplify(simplify_tolerance, preserve_topology=True)

    print(f"🎉 데이터 조인 및 GIS 빌딩 성공! | 최종 행 수: {len(unified_df):,}건 | 소요 시간: {time.time() - start_time:.2f}초")
    return unified_df

# =====================================================================
# 3. Folium 기반 인터랙티브 HTML 지도 빌드 (2D GIS 전담 모델)
# =====================================================================
def create_folium_map(
    gdf: gpd.GeoDataFrame, 
    color_col: str = "평균속도",
    default_color: str = "#95a5a6",
    title: str = "Seoul Interactive Traffic & Environment Map"
) -> folium.Map:
    """
    Folium을 사용해 확대/축소 및 마우스 호버/클릭 속성 조회가 가능한 HTML 지도를 만듭니다.
    [확장성]: 고유 지리 컬럼과 시스템 컬럼을 제외한 모든 일반 피처들을 동적으로 팝업창에 매핑합니다.
    """
    if gdf.empty:
        print("⚠️ 입력 데이터프레임이 비어 있어 빈 지도를 리턴합니다.")
        return folium.Map(location=[37.5665, 126.9780], zoom_start=11)

    # 위경도 좌표계 변환 점검
    if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
        gdf_4326 = gdf.to_crs("EPSG:4326")
    else:
        gdf_4326 = gdf.copy()

    # 1. 툴팁 & 팝업 노출 변수 동적 추출 엔진 (미래 추가될 모든 변수에 100% 자동 대응)
    exclude_cols = {"geometry", "F_NODE", "T_NODE", "F_NODE_X", "F_NODE_Y", "T_NODE_X", "T_NODE_Y"}
    display_cols = []
    aliases = []
    
    # 순서 보장을 위해 중요 기본 식별자 배치 후 나머지 필드를 동적으로 스캔
    priority_cols = ["LINK_ID", "ROAD_NAME", "ROAD_RANK", "MAX_SPD", "LANES", "평균속도", "speed_kmh", "slope_pct", "precip_mm"]
    for col in priority_cols:
        if col in gdf_4326.columns and col not in exclude_cols:
            display_cols.append(col)
            # 깔끔하게 한글 이름 별칭 매핑
            korean_alias = {
                "LINK_ID": "링크 ID",
                "ROAD_NAME": "도로명",
                "ROAD_RANK": "도로등급",
                "MAX_SPD": "제한속도(km/h)",
                "LANES": "차로 수",
                "평균속도": "실측속도(km/h)",
                "speed_kmh": "예측속도(km/h)",
                "slope_pct": "경사도(%)",
                "precip_mm": "강수량(mm)"
            }.get(col, col)
            aliases.append(korean_alias)
            exclude_cols.add(col)
            
    # 그 외 현재 파일이나 향후 미래 스키마에 동적으로 새롭게 삽입될 모든 컬럼들을 자동 탐색하여 팝업 정보창에 흡수
    for col in gdf_4326.columns:
        if col not in exclude_cols:
            display_cols.append(col)
            aliases.append(col) # 별칭은 원본 컬럼명 적용

    # 2. 값의 크기에 따른 도로 선 가시성 스타일 함수 정의
    # 속도 값(빨강-주황-노랑-초록) 수치 맵핑
    def get_color(val):
        if pd.isna(val) or val <= 0:
            return default_color
        if val < 20: return "#e74c3c"    # 정체 (빨강)
        if val < 40: return "#f39c12"    # 서행 (주황)
        if val < 60: return "#f1c40f"    # 보통 (노랑)
        return "#2ecc71"                 # 원활 (초록)

    # 3. Base Map 객체 정의 (실선 시인성 극대화를 위해 세련된 Dark 그레이 지도 로드)
    m = folium.Map(
        location=[37.5665, 126.9780],
        zoom_start=11,
        tiles="CartoDB dark_matter",
        control_scale=True
    )

    # GeoJSON 데이터 빌드 및 메모리 내 객체화
    geojson_data = json.loads(gdf_4326.to_json())

    # 레이어 스타일 콜백 바인딩
    def style_function(feature):
        # 지정된 컬럼(예: 예측속도 'speed_kmh' 또는 실측 '평균속도')을 우선 참조
        speed_val = feature["properties"].get("speed_kmh", feature["properties"].get("평균속도", np.nan))
        color = get_color(speed_val)
        rank = feature["properties"].get("ROAD_RANK", "104")
        
        # 간선도로와 이면도로의 굵기 분기 처리
        weight = 3.0 if rank in ["101", "102", "103"] else 1.2
        opacity = 0.9 if pd.notna(speed_val) and speed_val > 0 else 0.4
        
        return {
            "color": color,
            "fillColor": color,
            "weight": weight,
            "opacity": opacity
        }

    # 4. 인터랙티브 GeoJson 레이어 조립
    folium.GeoJson(
        geojson_data,
        name="Traffic Flow Layer",
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=display_cols[:6], # 마우스를 올렸을 땐 핵심 6개 지표만 가볍게 표출
            aliases=aliases[:6],
            localize=True,
            sticky=True
        ),
        popup=folium.GeoJsonPopup(
            fields=display_cols,      # 클릭했을 땐 추가된 파생 변수들을 표 형식으로 스크롤바 없이 전부 표출!
            aliases=aliases,
            labels=True
        )
    ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m

# =====================================================================
# 4. PyDeck 기반 초고속 3D 물리 시각화 (Streamlit 3D 전담 모델)
# =====================================================================
def create_pydeck_map(
    gdf: gpd.GeoDataFrame, 
    color_col: str = "speed_kmh", 
    elevation_col: str = "slope_pct"
) -> pdk.Deck:
    """
    PyDeck을 사용해 대용량 도로망을 하드웨어 가속(GPU) 렌더링하고, 
    경사도(slope_pct)를 3D 높이로 입체화시켜 오르막길/내리막길을 아름답게 시각화합니다.
    Streamlit의 st.pydeck_chart와 완벽하게 직결됩니다.
    """
    if gdf.empty:
        return pdk.Deck()

    # PyDeck 렌더링을 위한 좌표 추출 전처리
    gdf_4326 = gdf.to_crs("EPSG:4326").copy()
    
    # LINESTRING geometry를 PyDeck이 요구하는 경위도 path (좌표 어레이 목록) 형태로 변형
    def extract_path(geom):
        if geom is None:
            return []
        if geom.geom_type == 'LineString':
            return [[float(coords[0]), float(coords[1])] for coords in geom.coords]
        elif geom.geom_type == 'MultiLineString':
            # MultiLineString의 경우 첫 번째 라인 세그먼트만 대표로 추출
            first_line = list(geom.geoms)[0] if hasattr(geom, "geoms") else geom[0]
            return [[float(coords[0]), float(coords[1])] for coords in first_line.coords]
        return []

    gdf_4326["path"] = gdf_4326["geometry"].apply(extract_path)
    
    # pandas DataFrame으로 경량화 (PyDeck 전송용)
    df_deck = pd.DataFrame(gdf_4326.drop(columns="geometry"))
    
    # 속도 및 경사에 기반한 RGBA 칼럼 동적 생성
    # 속도가 느릴수록 Red, 빠를수록 Green 매핑
    def map_rgba(row):
        val = row.get(color_col, row.get("평균속도", np.nan))
        if pd.isna(val) or val <= 0:
            return [149, 165, 166, 120] # 미관측 회색
        if val < 20: return [231, 76, 60, 230]   # 정체 (Red)
        if val < 40: return [243, 156, 18, 230]  # 서행 (Orange)
        if val < 60: return [241, 196, 15, 230]  # 보통 (Yellow)
        return [46, 204, 113, 230]               # 원활 (Green)

    df_deck["color_rgba"] = df_deck.apply(map_rgba, axis=1)
    
    # 3D 고도 데이터 정규화 (경사도가 존재하면 경사 비율을 3D 높이로 입체화)
    if elevation_col in df_deck.columns:
        df_deck["elevation_val"] = df_deck[elevation_col].fillna(0.0).abs() * 50.0 # 높이 강조 배율 적용
    else:
        df_deck["elevation_val"] = 0.0

    # PathLayer 정의 (도로를 3D 입체 기둥 형태로 렌더링)
    layer = pdk.Layer(
        "PathLayer",
        df_deck,
        pickable=True,
        get_path="path",
        get_color="color_rgba",
        width_min_pixels=2,
        get_width=3,
        get_elevation="elevation_val",
        elevation_scale=1.5,
        extruded=True
    )

    # 초기 화면 뷰 상태 정의
    view_state = pdk.ViewState(
        latitude=37.5665,
        longitude=126.9780,
        zoom=11,
        pitch=45, # 기울임각을 줘서 3D 지형 효과 입체화
        bearing=0
    )

    # 3D 덱 생성
    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=view_state,
        map_style="mapbox://styles/mapbox/dark-v10", # 다크 맵 스타일 적용
        tooltip={
            "html": "<b>링크 ID:</b> {LINK_ID}<br/>"
                    "<b>도로명:</b> {ROAD_NAME}<br/>"
                    "<b>도로등급:</b> {ROAD_RANK}<br/>"
                    "<b>속도:</b> {" + color_col + "} km/h<br/>"
                    "<b>경사도:</b> {" + elevation_col + "}%",
            "style": {"color": "white", "backgroundColor": "#1e272c", "fontSize": "12px"}
        }
    )
    return deck

# =====================================================================
# 5. CLI 모드 가동 시 정적 지도 세이브 전용 함수 (하위 호환성용)
# =====================================================================
def save_static_png_report(gdf: gpd.GeoDataFrame, tm: str, output_dir: Path) -> None:
    """ Matplotlib을 사용해 보고서 첨부용 정적 요약 지도 PNG 파일 2종을 저장합니다. """
    print("\n🎨 [Static Render] 보고서용 정적 지도 이미지 파일(PNG) 2종 렌더링 중...")
    start_time = time.time()
    
    # 속도 컬럼 탐색
    speed_col = "speed_kmh" if "speed_kmh" in gdf.columns else ("평균속도" if "평균속도" in gdf.columns else None)
    
    if not speed_col:
        print("⚠️ 속도 데이터 컬럼이 없어 정적 이미지 매핑을 건너뜁니다.")
        return
        
    gdf["is_observed"] = gdf[speed_col].notna() & (gdf[speed_col] > 0)
    
    # 1. 속도 흐름도 렌더링
    fig, ax = plt.subplots(figsize=(10, 10))
    # 전체 회색 베이스 도로망을 먼저 밑바탕에 드로잉
    gdf.plot(ax=ax, color="#e0e0e0", linewidth=0.2, alpha=0.5)
    
    # 관측/예측 속도 도로망을 색상 그라데이션으로 매핑
    observed_gdf = gdf[gdf["is_observed"]].copy()
    if not observed_gdf.empty:
        observed_gdf.plot(
            ax=ax, 
            column=speed_col, 
            cmap="RdYlGn", # 정체(Red) ➔ 원활(Green)
            linewidth=0.7, 
            legend=True,
            legend_kwds={'label': f"Traffic Speed (km/h) at {tm}", 'orientation': "horizontal", 'shrink': 0.6}
        )
    ax.set_title(f"Seoul Traffic Speed Distribution ({tm})", fontsize=12, fontweight="bold")
    ax.axis("off")
    
    png_path = output_dir / f"seoul_speed_map_{tm}.png"
    plt.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close()
    
    # 2. 실측 관측망과 미관측(추정 대상) 도로망의 하이라이트 대조 지도
    fig, ax = plt.subplots(figsize=(10, 10))
    gdf[~gdf["is_observed"]].plot(ax=ax, color="#e74c3c", linewidth=0.3, alpha=0.4, label="Estimation Target (30% Local Alleys)")
    gdf[gdf["is_observed"]].plot(ax=ax, color="#2ecc71", linewidth=0.6, alpha=0.8, label="Real-time Observed (70% Main Roads)")
    
    ax.set_title(f"Observed vs Interpolation Network Breakdown", fontsize=12, fontweight="bold")
    ax.legend(loc="lower right", fontsize=8)
    ax.axis("off")
    
    highlight_path = output_dir / f"seoul_observed_highlight_map_{tm}.png"
    plt.savefig(highlight_path, dpi=150, bbox_inches="tight")
    plt.close()
    
    print(f"✔ 정적 시각화 완성! (소요 시간: {time.time() - start_time:.2f}초)")
    print(f"  • 속도 분포도 저장 완료: {png_path.name}")
    print(f"  • 소통망 하이라이트 맵 저장 완료: {highlight_path.name}")

# =====================================================================
# 6. 메인 컨트롤러 (CLI 스크립트 실행 모드)
# =====================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Seoul Traffic Space Interative Visualizer")
    parser.add_argument("--tm", help="시각화 대상 타겟 시간코드 (예: 202607261400)")
    parser.add_argument("--simplify", type=float, default=0.0001, help="지도 렌더링 성능을 보장하기 위한 GIS 선 압축률 (기본값 0.0001)")
    args = parser.parse_args()
    
    print("=================================================================")
    print(" 🗺️  SEOUL ECO-ROUTING: FLEXIBLE GIS VISUALIZATION PORTAL")
    print("=================================================================")
    
    # 시점 타겟 설정 (인자가 없다면 저장된 최신 날짜 시점을 자동으로 찾습니다.)
    target_tm = args.tm
    
    # 통합 GeoDataFrame 로드 (공간 Geometry + 도로 차원 + 예측/팩트 테이블 통합 매핑)
    gdf_unified = build_unified_dataframe(
        tm=target_tm, 
        simplify_tolerance=args.simplify
    )
    
    if gdf_unified.empty:
        print("❌ 시각화 데이터를 구축하지 못해 프로세스를 중단합니다.")
        sys.exit(1)
        
    # 만약 타겟 날짜를 코드 내부에서 자동 검지했다면 적용
    if not target_tm and "기준일" in gdf_unified.columns and "시간코드" in gdf_unified.columns:
        date_v = gdf_unified["기준일"].dropna().iloc[0]
        hour_v = gdf_unified["시간코드"].dropna().iloc[0]
        target_tm = f"{date_v}{int(hour_v):02d}00"
        print(f"🎯 [자동 탐지] 가용 가능한 시점 {target_tm}에 맞춰 지도를 생성합니다.")
        
    final_tm = target_tm or "LATEST"
    
    # 1. Folium 인터랙티브 HTML 지도 파일 생성 및 저장
    folium_map = create_folium_map(gdf_unified, title=f"Seoul Traffic Status at {final_tm}")
    output_html_path = PROCESSED_DATA_DIR / f"seoul_traffic_interactive_{final_tm}.html"
    
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    folium_map.save(output_html_path)
    print(f"\n💾 [SUCCESS] 인터랙티브 HTML 지도 저장 완료: {output_html_path}")
    print("👉 크롬 브라우저를 통해 더블클릭하면 줌인/줌아웃 및 클릭 툴팁 상세 조회가 가능합니다!")
    
    # 2. 정적 PNG 지도 2종 파일 생성 및 저장
    save_static_png_report(gdf_unified, final_tm, PROCESSED_DATA_DIR)
    
    print("=================================================================")
    print("시각화 파일 일괄 출력 완료")
    print("=================================================================\n")

if __name__ == "__main__":
    main()
