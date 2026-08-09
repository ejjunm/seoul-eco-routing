import streamlit as st
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime

# =====================================================================
# 1. 환경 설정 및 maps.py 임포트
# =====================================================================
def find_project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / "data").exists() or (parent / "src").exists(): return parent
    return Path.cwd()

PROJECT_ROOT = find_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# maps.py 하나에서 시각화를 위한 모든 준비를 끝내고 가져옵니다.
try:
    from src.eda.maps import load_eco_snapshot, create_folium_map, create_pydeck_map, prepare_visualization_data
except ImportError as e:
    st.error(f"src/eda/maps.py 파일을 찾을 수 없습니다: {e}")
    st.stop()

st.set_page_config(page_title="Seoul Eco-Routing", layout="wide", page_icon="🗺️")

# =====================================================================
# 2. 데이터 유틸리티 함수
# =====================================================================
@st.cache_data(show_spinner=False)
def get_available_snapshots(project_root: Path) -> tuple[list[str], list[str]]:
    """처리된 스냅샷 디렉토리를 스캔하여 사용 가능한 날짜와 시간 목록을 반환합니다."""
    snapshot_dir = project_root / "data" / "processed" / "seoul_all_link_eco_snapshot"
    if not snapshot_dir.exists():
        return [], []

    dates, hours = set(), set()
    for f in snapshot_dir.glob("seoul_all_link_eco_snapshot_*.csv"):
        try:
            # 파일명에서 타임스탬프 부분 추출 (예: 202607090800)
            timestamp_str = f.stem.split("_")[-1]
            if len(timestamp_str) == 12:
                dates.add(timestamp_str[:8]) # YYYYMMDD
                hours.add(timestamp_str[8:10]) # HH
        except (IndexError, ValueError):
            # 예상치 못한 파일명 형식은 건너뜁니다.
            continue
            
    return sorted(list(dates)), sorted(list(hours))

# =====================================================================
# 3. UI 구성 (동적 시간대 선택)
# =====================================================================
st.title("🗺️ 서울시 도로망 다이내믹 에코 라우팅 대시보드")
st.markdown("사전 연산된 에코 스냅샷을 바탕으로, **지도 시각화 및 속성 확인**을 초고속으로 수행합니다.")

st.sidebar.header("⚙️ 시각화 컨트롤 패널")

# --- 데이터 준비 섹션 ---
with st.sidebar.expander("데이터 준비/업데이트", expanded=False):
    st.info("아래 버튼은 시각화에 필요한 모든 데이터를 생성/업데이트합니다. (최초 실행 또는 데이터 변경 시 필수)")
    
    # 데이터 생성용 기본값 (하드코딩 유지)
    GENERATION_DATES = ["20260709", "20260710", "20260711", "20260712", "20260713"]
    GENERATION_HOURS = ["08", "12", "18", "23"]

    if st.button("🚀 시각화 데이터 준비", help=f"{len(GENERATION_DATES) * len(GENERATION_HOURS)}개의 스냅샷을 생성/업데이트합니다. (수 분 소요)"):
        st.toast("데이터 생성을 시작합니다... 완료 시 알림이 표시됩니다.")
        progress_bar = st.progress(0.0, text="(0/0) 작업을 시작합니다...")
        try:
            prepare_visualization_data(GENERATION_DATES, GENERATION_HOURS, PROJECT_ROOT, st_progress=progress_bar)
            st.success("데이터 준비가 완료되었습니다! 이제 원하는 시간을 선택하여 분석하세요.")
            st.toast("✅ 데이터 준비 완료!", icon="🎉")
            # 데이터 생성 후, 선택 목록을 업데이트하기 위해 캐시를 지우고 새로고침
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"데이터 준비 중 오류가 발생했습니다: {e}")
            st.toast("🚨 데이터 준비 실패", icon="🔥")

# --- 시각화 시간 선택 ---
st.sidebar.markdown("---")
st.sidebar.subheader("분석 시간 선택")

# 사용 가능한 스냅샷 목록을 동적으로 가져오기
available_dates, available_hours = get_available_snapshots(PROJECT_ROOT)

if not available_dates or not available_hours:
    st.sidebar.warning(
        "분석 가능한 데이터가 없습니다. "
        "왼쪽 '데이터 준비/업데이트' 섹션에서 '시각화 데이터 준비' 버튼을 눌러 데이터를 먼저 생성해주세요."
    )
    st.warning("표시할 데이터가 없습니다. 사이드바에서 데이터 생성을 먼저 진행해주세요.")
    st.stop()

selected_date = st.sidebar.selectbox("🗓️ 분석 날짜", available_dates, index=0)
selected_hour = st.sidebar.selectbox("⏰ 분석 시간", available_hours, index=0)
target_tm = f"{selected_date}{selected_hour}00"

dt_obj = datetime.strptime(target_tm, "%Y%m%d%H%M")
st.sidebar.success(f"**선택된 시간:** {dt_obj.strftime('%Y년 %m월 %d일 %H:%M')}")


# --- 시각화 변수 선택 ---
st.sidebar.markdown("---")
st.sidebar.subheader("지도 시각화 변수")
viz_options = {
    "평균 속도 (km/h)": "speed_kmh",
    "내연기관 연료소모 (mL)": "fuel_ml",
    "EV 전력소모 (Wh)": "ev_wh",
    "시간대별 강수량 (mm)": "precip_mm",
    "도로 경사도 (%)": "slope_pct",
    "도로 복잡도 (Node)": "node_complexity",
    "어린이보호구역 개수": "school_zone_count",
    "보행자사고다발": "accident_hotspot_count"
}
selected_metric = st.sidebar.selectbox("🎨 지도 색상(Color) 기준 변수", list(viz_options.keys()))
color_col = viz_options[selected_metric]

# =====================================================================
# 4. 데이터 로딩 및 시각화 렌더링
# =====================================================================
with st.spinner(f"맵핑 데이터를 로딩 중입니다... ({dt_obj.strftime('%m/%d %H:%M')})"):
    gdf_main = load_eco_snapshot(target_tm, PROJECT_ROOT)

if gdf_main.empty:
    st.warning(
        f"**데이터를 찾을 수 없습니다.**\n"
        f"1. `seoul_all_link_eco_snapshot_{target_tm}.csv` 파일이 `data/processed/seoul_all_link_eco_snapshot` 폴더에 있는지 확인해주세요.\n"
        f"2. 파일이 없다면, 왼쪽 사이드바의 **'시각화 데이터 준비'** 버튼을 클릭하여 데이터를 먼저 생성해주세요."
    )
    st.stop()

st.subheader(f"📊 실시간 지표 요약 ({dt_obj.strftime('%Y-%m-%d %H:%M')}, {selected_metric} 기준)")
c1, c2, c3, c4 = st.columns(4)
c1.metric("총 렌더링 도로 링크 수", f"{len(gdf_main):,} 개")
c2.metric("전체 평균 속도", f"{gdf_main['speed_kmh'].mean():.1f} km/h")

if "fuel_ml" in gdf_main.columns and gdf_main['fuel_ml'].notna().any():
    c3.metric("평균 내연기관 연료소모", f"{gdf_main['fuel_ml'].mean():.2f} mL")
else:
    c3.metric("평균 내연기관 연료소모", "N/A")

if "ev_wh" in gdf_main.columns and gdf_main['ev_wh'].notna().any():
    c4.metric("평균 EV 전력소모", f"{gdf_main['ev_wh'].mean():.2f} Wh")
else:
    c4.metric("평균 EV 전력소모", "N/A")


# 2D/3D 지도 렌더링
tab1, tab2 = st.tabs(["🌐 3D 물리 공간 분석 (PyDeck - 고도/경사 반영)", "📍 2D 정밀 속성 맵 (Folium)"])
with tab1:
    st.caption("고도와 경사도를 Z축으로 반영하여, 입체적인 지형 위에서 선택한 변수를 분석합니다.")
    deck = create_pydeck_map(gdf_main, color_col=color_col)
    st.pydeck_chart(deck)
with tab2:
    st.caption("도로 선분을 클릭하여 모든 속성 변수(차로수, 도로등급, 강수량 등)를 정밀하게 조회합니다.")
    folium_m = create_folium_map(gdf_main, color_col=color_col)
    st.components.v1.html(folium_m._repr_html_(), height=600, scrolling=True)

# 테이블 뷰
st.markdown("---")
st.subheader("📋 전체 도로망 다중 속성 데이터 테이블 탐색기")
search = st.text_input("🔍 특정 도로명 검색 (예: 종로, 세종대로)")

df_view = pd.DataFrame(gdf_main.drop(columns="geometry"))
if search: 
    df_view = df_view[df_view["ROAD_NAME"].str.contains(search, na=False)]

# 가독성 좋은 순서로 컬럼 재배치
col_order = ["LINK_ID", "ROAD_NAME", "ROAD_RANK", "MAX_SPD", "LANES", color_col] + [c for c in viz_options.values() if c != color_col]

display_cols = [c for c in col_order if c in df_view.columns] + [c for c in df_view.columns if c not in col_order]

st.dataframe(df_view[display_cols].head(500), use_container_width=True)
