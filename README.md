# Seoul Eco Routing

서울시 도로 링크, T-data 1시간 소통정보, DEM 고도, KMA 레이더 강수량을 결합해 링크별 속도·지형·기상 피처를 만드는 프로젝트입니다.

현재 속도 데이터는 T-data API가 아니라 T-data 사이트에서 내려받은 CSV를 사용합니다. KMA 레이더 강수량은 API로 내려받아 시간·공간 기준으로 링크에 매칭합니다.

## Project Structure

```text
.
├── scripts/
│   ├── inspect_network_schema.py
│   ├── extract_seoul_links.py
│   ├── summarize_seoul_links.py
│   ├── merge_tdata_link_speed.py
│   ├── analyze_matched_links.py
│   ├── plot_matched_links_map.py
│   ├── create_matched_link_map.py
│   ├── add_dem_features.py
│   ├── fetch_kma_radar.py
│   └── add_radar_precip_features.py
├── data/
│   ├── raw/
│   │   ├── road/       # MOCT_LINK.*, MOCT_NODE.*, MULTILINK.dbf, TURNINFO.dbf
│   │   ├── traffic/    # 1시간 소통정보 (구간별).csv
│   │   ├── dem/        # 37608.img, 37612.img, 37705.img, 37709.img
│   │   └── weather/    # KMA key, HSR grid, radar raw files
│   ├── interim/        # seoul_link.*
│   └── processed/      # generated CSV/GeoJSON/PNG/NPZ outputs
├── docs/
│   └── 작업정리.md
└── README.md
```

`data/raw/`, `data/interim/`, `data/processed/`는 대용량 원본/중간/가공 데이터이므로 Git에 올리지 않습니다.

## Main Data

| Data | Path | Usage |
| --- | --- | --- |
| ITS 표준 링크 | `data/raw/road/MOCT_LINK.*` | 도로 링크 geometry와 속성 |
| ITS 표준 노드 | `data/raw/road/MOCT_NODE.*` | 도로망 노드 |
| T-data 1시간 소통정보 | `data/raw/traffic/1시간 소통정보 (구간별).csv` | 링크별 시간대 평균속도 |
| DEM | `data/raw/dem/*.img` | 링크별 고도/경사도 |
| KMA HSR 격자 | `data/raw/weather/grid/hsr_lon.txt`, `hsr_lat.txt` | 레이더 격자 위치 |
| KMA 1시간 누적 강수 | `data/raw/weather/radar/hsr_pcph_acc60_*.txt` | 링크별 시간대 강수량 |

## Scripts

| Script | Description |
| --- | --- |
| `inspect_network_schema.py` | `MOCT_LINK.shp`의 크기, 컬럼, 좌표계 확인 |
| `extract_seoul_links.py` | 서울 bbox 기준 링크를 추출해 `seoul_link.*`, `seoul_link_attr.csv` 생성 |
| `summarize_seoul_links.py` | 서울 링크 속성 기초 통계 출력 |
| `merge_tdata_link_speed.py` | `LINK_ID`와 `링크ID` 기준으로 T-data 속도 결합 |
| `analyze_matched_links.py` | T-data 매칭률, 도로등급별 커버리지, 연결 컴포넌트 분석 |
| `plot_matched_links_map.py` | 매칭 링크 지도 이미지와 GeoJSON 생성 |
| `create_matched_link_map.py` | 외부 GIS 라이브러리 없이 SVG 지도 생성 |
| `add_dem_features.py` | DEM에서 링크별 고도/경사도 피처 생성 |
| `fetch_kma_radar.py` | KMA HSR 격자와 1시간 누적 레이더 강수량 다운로드 |
| `add_radar_precip_features.py` | 레이더 강수량을 링크·시간 기준으로 결합 |

## Raw Schema

### MOCT_LINK

| Item | Value |
| --- | --- |
| Path | `data/raw/road/MOCT_LINK.shp` |
| Geometry | `LINESTRING` |
| Total links | `1,555,158` |
| CRS | `ITRF2000_Central_Belt_60` |
| Unit | metre |

주요 컬럼:

```text
LINK_ID, F_NODE, T_NODE, LANES, ROAD_RANK, ROAD_TYPE,
ROAD_NAME, MAX_SPD, LENGTH, geometry
```

### T-data 1시간 소통정보

주요 컬럼:

```text
기준일, 시간코드, 시간대설명, 첨두시구분(T1/T2/T3:오전/낮/오후),
도로명, 도로방향구분코드, 도로방향구분명, 구간순서,
링크ID, 시작노드명, 종료노드명, 평균속도,
요일코드(1~7:일~토), 요일그룹코드(01:주중/02:주말),
도로코드, 도로구분코드, 도로구분명
```

### DEM

| Item | Value |
| --- | --- |
| Files | `37608.img`, `37612.img`, `37705.img`, `37709.img` |
| Format | HFA `.img` |
| CRS | `EPSG:5179` |
| Resolution | `90m x 90m` |
| Bands | 1 |
| dtype | `float32` |
| nodata | `-9999` |

도로 링크와 DEM의 좌표계가 다르므로 `add_dem_features.py`에서 링크를 `EPSG:5179`로 변환한 뒤 샘플링합니다.

### KMA HSR Radar

| Item | Value |
| --- | --- |
| API key file | `data/raw/weather/kma_api_key.txt` |
| Grid lon/lat API | `nph-rdr_latlon_api` |
| 1-hour accumulation API | `nph-rdr_cmp1_api` |
| Grid type | `cmp=HSR` |
| Precipitation product | `cmp=PCPH`, `qcd=MSK`, `obs=ECHO`, `acc=60`, `map=HB`, `disp=A` |
| Grid size | `2305 x 2881` |
| Raw radar file pattern | `data/raw/weather/radar/hsr_pcph_acc60_YYYYMMDDHHMM.txt` |

KMA ASCII 포맷에서 `-30000`은 레이더 관측영역 밖, `-25000`은 관측영역 안 무에코입니다. 강수 피처 생성 시 `-25000`은 `0mm`, `-30000` 이하는 결측으로 처리합니다.

## Generated Outputs

| File | Description |
| --- | --- |
| `data/interim/seoul_link.*` | 서울 bbox 기준 링크 Shapefile |
| `data/processed/seoul_link_attr.csv` | 서울 링크 속성 테이블 |
| `data/processed/seoul_link_speed_merged.csv` | T-data 속도 + 서울 링크 속성 |
| `data/processed/seoul_link_dem_features.csv` | 링크별 DEM 고도/경사도 피처 |
| `data/processed/seoul_link_speed_dem_merged.csv` | 속도 + 링크 속성 + DEM |
| `data/processed/weather_hsr_seoul_grid.npz` | 서울 bbox 주변 HSR 격자 캐시 |
| `data/processed/link_radar_grid_mapping.csv` | 링크 중심점과 가장 가까운 HSR 격자 매핑 |
| `data/processed/seoul_link_radar_precip.csv` | 링크별 시간대 레이더 강수 피처 |
| `data/processed/seoul_link_speed_dem_weather_merged.csv` | 최종 속도 + 링크 + DEM + 강수 결합 테이블 |
| `data/processed/matched_road_rank_coverage.csv` | 도로등급별 T-data 매칭률 |
| `data/processed/matched_graph_components.csv` | 매칭 링크 연결 컴포넌트 |
| `data/processed/matched_link_ids.csv` | T-data와 매칭된 링크 목록 |
| `data/processed/matched_links.geojson` | 매칭 링크 GeoJSON |
| `data/processed/matched_links_map.png` | 매칭 링크 분포 지도 |

## Current Results

### T-data Matching

```text
서울 링크 수: 109,633
T-data 행 수: 608,538
결합된 T-data 행 수: 183,821
결합된 고유 링크ID 수: 1,546
```

T-data 매칭 링크만으로 만든 그래프의 연결성은 낮습니다.

```text
연결 컴포넌트 수: 1,382
최대 컴포넌트 링크 수: 17
최대 컴포넌트 링크 비율: 1.1%
```

따라서 현재 데이터만으로는 서울 전체 OD 경로탐색보다, T-data 속도 이력이 확보된 주요 링크의 속도/에너지 비효율 구간 분석이 더 안전합니다.

### DEM

```text
서울 링크 수: 109,633
DEM 샘플 존재 링크 비율: 100.0%
대부분 링크의 dem_sample_count: 5
```

### Radar Precipitation

```text
T-data 대상 레이더 시각 수: 119
다운로드 완료 레이더 시각 수: 119
누락 레이더 시각 수: 0
최종 결합 행 수: 183,821
강수값 존재 행 수: 183,821
```

강수량 요약:

```text
mean precip_mm: 5.90
median precip_mm: 0.00
max precip_mm: 47.57
precip_mm > 0 행 수: 50,972
precip_mm > 0 시각 수: 53
```

## Workflow

```bat
.venv\Scripts\activate.bat

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
.venv\Scripts\python.exe scripts\add_radar_precip_features.py
```

KMA 레이더 한 시각만 받을 때:

```bat
python scripts\fetch_kma_radar.py --tm 202607070300
```

## Notes

- `extract_seoul_links.py`는 정확한 서울 행정경계가 아니라 bbox 기준으로 링크를 추출합니다.
- 정확한 서울 행정구역 내부 링크만 필요하면 서울 행정경계 Shapefile 또는 GeoJSON을 사용해 `clip` 또는 `sjoin` 방식으로 다시 추출해야 합니다.
- T-data API 수집 코드는 사용하지 않습니다.
- `data/raw/` 아래 원본 데이터는 직접 받은 파일이므로 코드에서 수정하지 않는 것을 원칙으로 합니다.
- DEM은 90m 해상도이므로 짧은 링크에서는 경사도 값이 튈 수 있습니다. 모델링 전 `LENGTH` 기준 필터링이나 경사도 이상치 처리가 필요합니다.
- KMA 레이더 원본은 한 시각당 약 48MB이며, 현재 T-data 대상 119개 시각 원본은 약 5.7GB입니다.
