# Seoul Traffic Data Analysis

서울시 도로 링크, T-data 1시간 소통정보, DEM 고도 데이터를 결합해 링크별 속도·지형 피처를 만들고 교통/에너지 분석에 활용하기 위한 프로젝트입니다.

현재 교통 속도 데이터는 T-data API로 수집하지 않고, T-data 사이트에서 내려받은 CSV 파일을 사용합니다.

## Project Structure

```text
.
├── scripts/
│   ├── inspect_network_schema.py       # MOCT_LINK 원본 스키마 확인
│   ├── extract_seoul_links.py          # 서울 bbox 기준 링크 추출
│   ├── summarize_seoul_links.py        # 서울 링크 속성 기초 통계 확인
│   ├── merge_tdata_link_speed.py       # 서울 링크 속성과 T-data 속도 데이터 결합
│   ├── analyze_matched_links.py        # T-data 매칭 링크의 도로등급/연결성 분석
│   ├── plot_matched_links_map.py       # 매칭 링크 지도 이미지/GeoJSON 생성
│   ├── create_matched_link_map.py      # 외부 GIS 라이브러리 없이 SVG 지도 생성
│   ├── add_dem_features.py             # DEM 기반 고도/경사도 피처 생성
│   ├── fetch_kma_radar.py              # KMA HSR 레이더 격자/강수량 원본 다운로드
│   └── add_radar_precip_features.py    # 레이더 강수량 기반 시간·공간 피처 생성
├── data/
│   ├── raw/
│   │   ├── road/
│   │   │   ├── MOCT_LINK.*             # ITS 표준 링크 Shapefile 원본
│   │   │   ├── MOCT_NODE.*             # ITS 표준 노드 Shapefile 원본
│   │   │   ├── MULTILINK.dbf           # 복합 링크 속성
│   │   │   └── TURNINFO.dbf            # 회전 제한/회전 정보
│   │   ├── traffic/
│   │   │   └── 1시간 소통정보 (구간별).csv
│   │   ├── dem/
│   │   │   ├── 37608.img
│   │   │   ├── 37612.img
│   │   │   ├── 37705.img
│   │   │   └── 37709.img
│   │   └── weather/
│   │       ├── kma_api_key.txt         # KMA API 인증키
│   │       ├── grid/
│   │       │   ├── hsr_lon.txt
│   │       │   └── hsr_lat.txt
│   │       └── radar/
│   │           └── hsr_pcph_acc60_*.txt
│   ├── interim/
│   │   └── seoul_link.*                # 서울 bbox 기준으로 추출한 Shapefile
│   └── processed/
│       ├── seoul_link_attr.csv
│       ├── seoul_link_speed_merged.csv
│       ├── seoul_link_dem_features.csv
│       ├── seoul_link_speed_dem_merged.csv
│       ├── weather_hsr_seoul_grid.npz
│       ├── link_radar_grid_mapping.csv
│       ├── seoul_link_radar_precip.csv
│       ├── seoul_link_speed_dem_weather_merged.csv
│       ├── matched_road_rank_coverage.csv
│       ├── matched_graph_components.csv
│       ├── matched_link_ids.csv
│       ├── matched_links.geojson
│       └── matched_links_map.png
├── docs/
│   └── 작업정리.md
├── .gitignore
└── README.md
```

## Data Sources

| Data | Path | Description | Usage |
| --- | --- | --- | --- |
| ITS 표준 링크 | `data/raw/road/MOCT_LINK.*` | 도로 링크 geometry와 속성 | 도로망 edge, 링크 속성 |
| ITS 표준 노드 | `data/raw/road/MOCT_NODE.*` | 도로 노드 geometry와 속성 | 도로망 node |
| T-data 1시간 소통정보 | `data/raw/traffic/1시간 소통정보 (구간별).csv` | 시간대별 링크 평균속도 | `링크ID` 기준 속도 결합 |
| DEM | `data/raw/dem/*.img` | EPSG:5179, 90m 해상도 고도 래스터 | 링크별 고도/경사도 피처 |
| KMA 레이더 격자 | `data/raw/weather/grid/hsr_lon.txt`, `hsr_lat.txt` | HSR 격자별 위도/경도 | 링크 위치와 레이더 격자 매칭 |
| KMA 1시간 누적 강수 | `data/raw/weather/radar/hsr_pcph_acc60_*.txt` | HSR 기반 1시간 누적 레이더 강수량 | 시간·공간 기준 강수 피처 |

## Scripts

| File | Input | Output | Description |
| --- | --- | --- | --- |
| `scripts/inspect_network_schema.py` | `data/raw/road/MOCT_LINK.shp` | 콘솔 출력 | 원본 링크 수, 컬럼, 좌표계, 샘플 확인 |
| `scripts/extract_seoul_links.py` | `data/raw/road/MOCT_LINK.shp` | `data/interim/seoul_link.*`, `data/processed/seoul_link_attr.csv` | 서울 bbox와 교차하는 링크 추출 |
| `scripts/summarize_seoul_links.py` | `data/processed/seoul_link_attr.csv` | 콘솔 출력 | 도로등급, 제한속도, 길이 통계 |
| `scripts/merge_tdata_link_speed.py` | `seoul_link_attr.csv`, T-data CSV | `data/processed/seoul_link_speed_merged.csv` | `LINK_ID`와 `링크ID` 기준 결합 |
| `scripts/analyze_matched_links.py` | `seoul_link_attr.csv`, `seoul_link_speed_merged.csv` | 매칭률/연결성 CSV | 도로등급별 매칭률, 연결 컴포넌트, 샘플 경로 탐색 |
| `scripts/plot_matched_links_map.py` | `data/interim/seoul_link.shp`, `matched_link_ids.csv` | `matched_links_map.png`, `matched_links.geojson` | 매칭 링크 분포 지도 생성 |
| `scripts/create_matched_link_map.py` | `MOCT_LINK.shp/dbf`, `matched_link_ids.csv` | `matched_links_map.svg` | GeoPandas 없이 Shapefile을 직접 읽어 SVG 생성 |
| `scripts/add_dem_features.py` | `data/interim/seoul_link.shp`, `data/raw/dem/*.img`, `seoul_link_speed_merged.csv` | `seoul_link_dem_features.csv`, `seoul_link_speed_dem_merged.csv` | 링크별 고도/경사도 피처 생성 및 속도 데이터와 결합 |
| `scripts/fetch_kma_radar.py` | KMA API | `data/raw/weather/grid/*.txt`, `data/raw/weather/radar/*.txt` | HSR 격자 위경도와 1시간 누적 레이더 강수량 다운로드 |
| `scripts/add_radar_precip_features.py` | HSR 격자/레이더 파일, `seoul_link_speed_dem_merged.csv` | `seoul_link_radar_precip.csv`, `seoul_link_speed_dem_weather_merged.csv` | 링크별 가장 가까운 레이더 격자의 시간대별 강수량 결합 |

## Raw Data Schema

### MOCT_LINK

| Item | Value |
| --- | --- |
| Path | `data/raw/road/MOCT_LINK.shp` |
| Geometry | `LINESTRING` |
| Total links | `1,555,158` |
| CRS | `ITRF2000_Central_Belt_60` |
| Unit | metre |

주요 컬럼:

| Column | Meaning | Usage |
| --- | --- | --- |
| `LINK_ID` | 도로 링크 ID | T-data `링크ID`와 조인 |
| `F_NODE` | 시작 노드 ID | 그래프 출발 노드 |
| `T_NODE` | 종료 노드 ID | 그래프 도착 노드 |
| `LANES` | 차로 수 | 도로 용량/속도 피처 |
| `ROAD_RANK` | 도로 등급 | 도로 위계 분석 |
| `ROAD_TYPE` | 도로 유형 | 도로 유형 피처 |
| `ROAD_NAME` | 도로명 | 해석 및 시각화 |
| `MAX_SPD` | 제한속도 | 속도 기준 피처 |
| `LENGTH` | 링크 길이 | 통행시간, 경사도 계산 |
| `geometry` | 링크 선형 | 지도 시각화, DEM 샘플링 |

### T-data 1시간 소통정보

| Column | Meaning | Usage |
| --- | --- | --- |
| `기준일` | 데이터 기준 날짜 | 날짜 기준 분석 |
| `시간코드` | 시간대 코드 | 시간대 구분 |
| `시간대설명` | 시간대 설명 | 시간대 라벨 |
| `첨두시구분(T1/T2/T3:오전/낮/오후)` | 첨두/비첨두 구분 | 시간대 피처 |
| `도로명` | T-data 도로명 | 해석 및 검증 |
| `도로방향구분코드` | 방향 코드 | 상행/하행 구분 |
| `도로방향구분명` | 방향명 | 상행/하행 라벨 |
| `구간순서` | 도로 내 구간 순서 | 동일 도로 내 정렬 |
| `링크ID` | T-data 링크 ID | `MOCT_LINK.LINK_ID`와 조인 |
| `시작노드명` | 시작 지점명 | 해석 및 검증 |
| `종료노드명` | 종료 지점명 | 해석 및 검증 |
| `평균속도` | 평균 속도 | 예측 대상/경로 비용 |
| `요일코드(1~7:일~토)` | 요일 코드 | 요일 패턴 |
| `요일그룹코드(01:주중/02:주말)` | 주중/주말 구분 | 주중/주말 패턴 |
| `도로코드` | 도로 코드 | 도로 식별 |
| `도로구분코드` | 도로 구분 코드 | 도로 유형 피처 |
| `도로구분명` | 도로 구분명 | 도로 유형 라벨 |

### DEM

| Item | Value |
| --- | --- |
| Path | `data/raw/dem/*.img` |
| Files | `37608.img`, `37612.img`, `37705.img`, `37709.img` |
| Format | HFA `.img` |
| CRS | `EPSG:5179` |
| Resolution | `90m x 90m` |
| Bands | 1 |
| dtype | `float32` |
| nodata | `-9999` |

DEM과 도로 링크의 좌표계가 다르므로, `add_dem_features.py`에서 도로 링크를 DEM 좌표계인 `EPSG:5179`로 변환한 뒤 고도를 샘플링합니다.

### KMA HSR Radar

| Item | Value |
| --- | --- |
| API key file | `data/raw/weather/kma_api_key.txt` |
| Grid lon/lat API | `nph-rdr_latlon_api` |
| 1-hour accumulation API | `nph-rdr_cmp1_api` |
| Grid type | `cmp=HSR` |
| Precipitation product | `cmp=PCPH`, `acc=60` |
| Grid size | `2305 x 2881` |
| Raw grid files | `data/raw/weather/grid/hsr_lon.txt`, `hsr_lat.txt` |
| Raw radar files | `data/raw/weather/radar/hsr_pcph_acc60_YYYYMMDDHHMM.txt` |

레이더 원본은 한 시각당 약 48MB입니다. T-data의 119개 시각을 모두 받으면 원본 레이더 파일만 약 5~6GB가 될 수 있습니다.

## Processed Data Schema

### `data/processed/seoul_link_attr.csv`

서울 bbox 기준으로 추출한 링크 속성 테이블입니다. `geometry`는 제외되어 있고, geometry가 필요하면 `data/interim/seoul_link.shp`를 사용합니다.

주요 컬럼:

```text
LINK_ID, F_NODE, T_NODE, LANES, ROAD_RANK, ROAD_TYPE, ROAD_NO,
ROAD_NAME, ROAD_USE, MULTI_LINK, CONNECT, MAX_SPD, LENGTH
```

### `data/processed/seoul_link_speed_merged.csv`

T-data 시간대별 속도 행에 서울 링크 속성을 붙인 결과입니다.

결합 기준:

```text
T-data: 링크ID
서울 링크 속성: LINK_ID
```

주요 컬럼:

```text
기준일, 시간코드, 시간대설명, 도로명, 링크ID, 평균속도,
LINK_ID, F_NODE, T_NODE, ROAD_NAME, ROAD_RANK, MAX_SPD, LENGTH
```

현재 결합 결과:

```text
서울 링크 수: 109,633
T-data 행 수: 608,538
결합된 T-data 행 수: 183,821
결합된 고유 링크ID 수: 1,546
```

### `data/processed/seoul_link_dem_features.csv`

서울 링크별 DEM 피처입니다.

| Column | Meaning |
| --- | --- |
| `LINK_ID` | 도로 링크 ID |
| `elev_start_m` | 링크 시작점 고도 |
| `elev_mid_m` | 링크 중간점 고도 |
| `elev_end_m` | 링크 끝점 고도 |
| `elev_mean_m` | 샘플 지점 평균 고도 |
| `elev_min_m` | 샘플 지점 최소 고도 |
| `elev_max_m` | 샘플 지점 최대 고도 |
| `elev_delta_m` | 끝점 고도 - 시작점 고도 |
| `slope_pct` | `elev_delta_m / LENGTH * 100` |
| `abs_slope_pct` | 경사도 절댓값 |
| `dem_sample_count` | 유효 DEM 샘플 수 |

현재 DEM 결합 결과:

```text
링크 수: 109,633
DEM 샘플 존재 링크 비율: 100.0%
대부분 링크의 dem_sample_count: 5
```

### `data/processed/seoul_link_speed_dem_merged.csv`

`seoul_link_speed_merged.csv`에 DEM 피처를 `LINK_ID` 기준으로 붙인 최종 결합 테이블입니다.

현재 행 수:

```text
183,821
```

### `data/processed/seoul_link_radar_precip.csv`

KMA 레이더 격자와 링크 중심점을 공간 매칭한 뒤, 시각별 강수량을 붙인 링크 단위 강수 피처입니다.

| Column | Meaning |
| --- | --- |
| `tm` | KMA 레이더 기준시각, `YYYYMMDDHHMM` |
| `LINK_ID` | 도로 링크 ID |
| `radar_raw_value` | KMA 레이더 원자료 값 |
| `precip_mm` | 강수량 mm. 음수 무강수 코드는 0mm, `-30000` 이하는 결측 처리 |

### `data/processed/seoul_link_speed_dem_weather_merged.csv`

`seoul_link_speed_dem_merged.csv`에 강수 피처를 `tm`, `LINK_ID` 기준으로 붙인 테이블입니다.

현재는 테스트용으로 일부 레이더 시각만 내려받은 상태입니다. 전체 T-data 시간대의 강수 피처를 채우려면 `fetch_kma_radar.py --from-tdata-times`로 누락 레이더 파일을 내려받은 뒤 `add_radar_precip_features.py`를 다시 실행해야 합니다.

### Weather Helper Files

| File | Description |
| --- | --- |
| `weather_hsr_seoul_grid.npz` | 서울 bbox 주변 HSR 격자만 추린 캐시 |
| `link_radar_grid_mapping.csv` | 각 `LINK_ID` 중심점과 가장 가까운 HSR 레이더 격자 매핑 |

### Matching Diagnostics

| File | Description |
| --- | --- |
| `matched_road_rank_coverage.csv` | 도로등급별 전체 링크 수, 매칭 링크 수, 매칭률 |
| `matched_graph_components.csv` | 매칭 링크 그래프의 연결 컴포넌트 요약 |
| `matched_link_ids.csv` | T-data와 매칭된 고유 링크 목록 |
| `matched_links_map.png` | 서울 링크망 위에 매칭 링크를 표시한 지도 이미지 |
| `matched_links.geojson` | 매칭 링크 GeoJSON |

현재 연결성 분석 결과:

```text
T-data 매칭 고유 링크 수: 1,546
연결 컴포넌트 수: 1,382
최대 컴포넌트 링크 수: 17
최대 컴포넌트 링크 비율: 1.1%
```

따라서 현재 데이터만으로는 서울 전체 OD 경로탐색보다, T-data 속도 이력이 확보된 주요 링크의 속도/에너지 비효율 구간 분석이 더 안전합니다.

## Workflow

1. 원본 도로망 데이터는 `data/raw/road/`, T-data CSV는 `data/raw/traffic/`, DEM은 `data/raw/dem/`에 둡니다.
2. `scripts/extract_seoul_links.py`로 서울 bbox 기준 링크를 추출합니다.
3. `scripts/merge_tdata_link_speed.py`로 T-data 속도를 `LINK_ID` 기준으로 결합합니다.
4. `scripts/analyze_matched_links.py`와 `scripts/plot_matched_links_map.py`로 매칭 커버리지와 분포를 확인합니다.
5. `scripts/add_dem_features.py`로 DEM 고도/경사도 피처를 생성합니다.
6. `scripts/fetch_kma_radar.py`로 KMA HSR 격자와 시간대별 레이더 강수량을 내려받습니다.
7. `scripts/add_radar_precip_features.py`로 링크별 시간·공간 강수 피처를 추가합니다.

## Run

가상환경 활성화:

```bat
.venv\Scripts\activate.bat
```

전체 기본 흐름:

```bat
python scripts\inspect_network_schema.py
python scripts\extract_seoul_links.py
python scripts\summarize_seoul_links.py
python scripts\merge_tdata_link_speed.py
python scripts\analyze_matched_links.py
python scripts\plot_matched_links_map.py
python scripts\add_dem_features.py
python scripts\fetch_kma_radar.py --grid
python scripts\fetch_kma_radar.py --from-tdata-times
python scripts\add_radar_precip_features.py
```

가상환경을 활성화하지 않고 실행할 때:

```bat
.venv\Scripts\python.exe scripts\add_dem_features.py
```

KMA 레이더 한 시각만 받을 때:

```bat
python scripts\fetch_kma_radar.py --tm 202607070300
```

## Notes

- `extract_seoul_links.py`는 정확한 서울 행정경계가 아니라 bbox 기준으로 링크를 추출합니다.
- 정확한 서울 행정구역 내부 링크만 필요하면 서울 행정경계 Shapefile 또는 GeoJSON을 사용해 `clip` 또는 `sjoin` 방식으로 다시 추출해야 합니다.
- T-data API 수집 코드는 사용하지 않습니다. 속도 데이터는 사이트에서 내려받은 CSV를 사용합니다.
- `data/raw/` 아래의 원본 데이터는 직접 받은 파일이므로 코드에서 수정하지 않는 것을 원칙으로 합니다.
- DEM은 90m 해상도이므로 짧은 링크에서는 경사도 값이 튈 수 있습니다. 모델링 전 `LENGTH` 기준 필터링이나 경사도 이상치 처리가 필요합니다.
- KMA 레이더 원본은 파일 크기가 큽니다. 전체 시간대 다운로드 전에 저장공간을 확인해야 합니다.
