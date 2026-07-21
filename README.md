# Seoul Eco Routing

서울시 도로 링크, T-data 1시간 소통정보, DEM 고도, KMA 레이더 강수량을 결합해 링크별 속도·지형·기상 피처를 만드는 프로젝트입니다.

현재 속도 데이터는 T-data API가 아니라 T-data 사이트에서 내려받은 CSV를 사용합니다. KMA 레이더 강수량은 API로 내려받아 시간·공간 기준으로 링크에 매칭합니다.

데이터 스키마, 서울 링크 추출/매칭 방식의 배경과 검증 과정, 현재 결과 수치 등 세부 내용은 **[data/README.md](data/README.md)**를 참고하세요.

## Project Structure

```text
.
├── src/
│   ├── 01_inspect_network_schema.py
│   ├── 02_extract_seoul_links.py
│   ├── 03_summarize_seoul_links.py
│   ├── 04_merge_tdata_link_speed.py
│   ├── 05_analyze_matched_links.py
│   ├── 06_plot_matched_links_map.py
│   ├── 07_add_dem_features.py
│   ├── 08_fetch_kma_radar.py
│   └── 09_add_radar_precip_features.py
├── notebooks/
│   ├── 10_eda_report.ipynb
│   └── 11_speed_model_baseline.ipynb
├── data/
│   ├── README.md       # 데이터 스키마/매칭 방식/결과 상세 문서
│   ├── raw/
│   │   ├── road/       # MOCT_LINK.*, MOCT_NODE.*, MULTILINK.dbf, TURNINFO.dbf
│   │   ├── boundary/   # seoul_admin_boundary.geojson (서울 25개 자치구 경계)
│   │   ├── traffic/    # 1시간 소통정보 (구간별).csv
│   │   ├── dem/        # 37608.img, 37612.img, 37705.img, 37709.img
│   │   └── weather/    # KMA key, HSR grid, radar raw files
│   ├── interim/        # seoul_link.*
│   └── processed/      # generated CSV/GeoJSON/PNG/NPZ outputs
├── docs/
│   └── figures/
│       ├── eda/       # 10번 노트북이 생성하는 보고서용 EDA 그래프
│       └── model/     # 11번 노트북이 생성하는 속도 예측 모델 그래프
└── README.md
```

`data/raw/`, `data/interim/`, `data/processed/`의 실제 데이터 파일은 대용량 원본/중간/가공 데이터이므로 Git에 올리지 않습니다. 대신 각 폴더에는 `.gitkeep`을 두어 필요한 폴더 구조만 GitHub에 표시합니다. 예외적으로 `data/raw/boundary/seoul_admin_boundary.geojson`은 크기가 작은 정적 참조 데이터라 커밋합니다(자세한 내용은 [data/README.md](data/README.md) 참고).

## Main Data

| Data | Path | Usage |
| --- | --- | --- |
| ITS 표준 링크 | `data/raw/road/MOCT_LINK.*` | 도로 링크 geometry와 속성 |
| ITS 표준 노드 | `data/raw/road/MOCT_NODE.*` | 도로망 노드 |
| 서울 행정경계 | `data/raw/boundary/seoul_admin_boundary.geojson` | 서울 링크 추출 기준 (25개 자치구 경계, EPSG:4326) |
| T-data 1시간 소통정보 | `data/raw/traffic/1시간 소통정보 (구간별).csv` | 링크별 시간대 평균속도 |
| DEM | `data/raw/dem/*.img` | 링크별 고도/경사도 |
| KMA HSR 격자 | `data/raw/weather/grid/hsr_lon.txt`, `hsr_lat.txt` | 레이더 격자 위치 |
| KMA 1시간 누적 강수 | `data/raw/weather/radar/hsr_pcph_acc60_*.txt` | 링크별 시간대 강수량 |

각 데이터의 상세 스키마는 [data/README.md](data/README.md)를 참고하세요.

## Scripts

`src/`의 파일명 앞 번호는 실행 순서(파이프라인 순서)를 나타냅니다.

| Script | Description |
| --- | --- |
| `01_inspect_network_schema.py` | `MOCT_LINK.shp`의 크기, 컬럼, 좌표계 확인 |
| `02_extract_seoul_links.py` | 서울 행정경계(25개 자치구) 기준 링크를 추출해 `seoul_link.*`, `seoul_link_attr.csv` 생성 |
| `03_summarize_seoul_links.py` | 서울 링크 속성 기초 통계 출력 |
| `04_merge_tdata_link_speed.py` | 서울시 공식 "TOPIS-표준노드링크 매핑정보"(서비스링크→표준링크아이디)로 T-data 속도 결합 |
| `05_analyze_matched_links.py` | T-data 매칭률, 도로등급별 커버리지, 연결 컴포넌트 분석 |
| `06_plot_matched_links_map.py` | 매칭 링크 지도 이미지와 GeoJSON 생성 |
| `07_add_dem_features.py` | DEM에서 링크별 고도/경사도 피처 생성 |
| `08_fetch_kma_radar.py` | KMA HSR 격자와 1시간 누적 레이더 강수량 다운로드 |
| `09_add_radar_precip_features.py` | 레이더 강수량을 링크·시간 기준으로 결합 |

`04_merge_tdata_link_speed.py`의 공식 매핑 테이블 기반 매칭 방식(왜 필요한지, prefix8 확장을 검토했다가 채택하지 않은 이유)은 [data/README.md의 "T-data LINK_ID 매칭"](data/README.md#t-data-link_id-매칭)에 자세히 정리되어 있습니다.

## Notebooks

| Notebook | Description |
| --- | --- |
| `10_eda_report.ipynb` | 최종 결합 테이블을 입력으로 강수량·경사도·도로등급·첨두시간대별 평균속도 EDA 테이블과 차트를 생성하는 리포트. 집계 테이블은 셀 출력으로 바로 보여주고, 보고서용 차트 7장만 `docs/figures/eda/`에 저장 |
| `11_speed_model_baseline.ipynb` | 최종 결합 테이블의 원본 컬럼(파생 피처 제외)만으로 링크 평균속도를 예측하는 LightGBM 베이스라인. T-data가 1:N으로 broadcast되는 구조로 인한 그룹(형제 링크) 유출을 막기 위해 `LINK_ID` 앞 8자리 기준 그룹 분할을 쓰고, 랜덤 분할과 비교해 유출 효과를 정량적으로 보여줌. 결과 차트 4장은 `docs/figures/model/`에 저장 |

노트북을 다시 실행하려면:

```bat
jupyter lab notebooks\10_eda_report.ipynb
```

또는 커널 없이 일괄 실행 후 저장하려면:

```bat
python -m nbconvert --to notebook --execute --inplace notebooks\10_eda_report.ipynb
python -m nbconvert --to notebook --execute --inplace notebooks\11_speed_model_baseline.ipynb
```

## Current Results (요약)

```text
서울 링크 수: 63,548
T-data 결합 고유 링크 수: 11,010 (17.33%)
연결 컴포넌트 수: 7,142 | 최대 컴포넌트 링크 비율: 0.27%
DEM 샘플 존재 링크 비율: 100.0%
레이더 강수 결합 완료 시각: 238/238
```

전체 수치, 도로등급별 매칭률, EDA 결과, 대표 그래프는 [data/README.md의 "Current Results"](data/README.md#current-results)를 참고하세요.

## Workflow

```bat
.venv\Scripts\activate.bat

python src\01_inspect_network_schema.py
python src\02_extract_seoul_links.py
python src\03_summarize_seoul_links.py
python src\04_merge_tdata_link_speed.py
python src\05_analyze_matched_links.py
python src\06_plot_matched_links_map.py
python src\07_add_dem_features.py
python src\08_fetch_kma_radar.py --grid
python src\08_fetch_kma_radar.py --from-tdata-times
python src\09_add_radar_precip_features.py

python -m nbconvert --to notebook --execute --inplace notebooks\10_eda_report.ipynb
python -m nbconvert --to notebook --execute --inplace notebooks\11_speed_model_baseline.ipynb
```

가상환경을 활성화하지 않고 실행할 때:

```bat
.venv\Scripts\python.exe src\09_add_radar_precip_features.py
```

KMA 레이더 한 시각만 받을 때:

```bat
python src\08_fetch_kma_radar.py --tm 202607070300
```

## Notes

- T-data API 수집 코드는 사용하지 않습니다.
- `data/raw/` 아래 원본 데이터는 직접 받은 파일이므로 코드에서 수정하지 않는 것을 원칙으로 합니다.
- 서울 링크 추출 기준(bbox → 행정경계), T-data LINK_ID 매칭 방식과 그 배경, 캐시 무효화 시 주의사항 등은 모두 [data/README.md](data/README.md)에 정리되어 있습니다.
