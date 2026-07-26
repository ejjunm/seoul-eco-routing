# Seoul Eco Routing

서울시 도로 링크, T-data 1시간 소통정보, DEM 고도, KMA 레이더 강수량을 결합해 서울 전역 링크의 시간대별 속도와 통행시간을 추정하는 프로젝트입니다.

현재 속도 데이터는 T-data API가 아니라 T-data 사이트에서 내려받은 CSV를 사용합니다. KMA 레이더 강수량은 API로 내려받아 시간·공간 기준으로 링크에 매칭합니다.

공식 T-data 관측은 서울 표준링크 63,548개 중 11,010개(17.33%)만 포함합니다. 따라서 현재 파이프라인은 관측 링크만 연결해 경로를 찾는 방식이 아니라, 공식 관측을 학습 라벨로 사용하고 모든 링크에서 구할 수 있는 도로·지형·시간·강수 피처로 나머지 링크의 속도를 추정하는 **전 링크 모델(Model B)** 방식입니다.

데이터 스키마, 서울 링크 추출/매칭 방식, 누수 방지 평가, 전 링크 추정 방식과 한계는 **[data/README.md](data/README.md)**를 참고하세요.

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
│   ├── 09_add_radar_precip_features.py
│   ├── 10_evaluate_speed_model.py
│   ├── 11_build_all_link_weather_snapshot.py
│   ├── 12_predict_all_link_speed.py
│   └── 13_build_link_model_features.py
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
| `10_evaluate_speed_model.py` | 원본 관측 누수를 막은 시간·공간 일반화 평가와 피처 중요도 저장 |
| `11_build_all_link_weather_snapshot.py` | 특정 시각의 서울 전체 63,548개 링크 강수 스냅샷 생성 |
| `12_predict_all_link_speed.py` | 관측값, 전 링크 모델, 계층적 fallback을 결합해 전체 링크 속도·통행시간 생성 |
| `13_build_link_model_features.py` | 모든 링크에서 사용할 수 있는 노드 위상·경사 보정·조합 피처 생성 |

`04_merge_tdata_link_speed.py`의 공식 매핑 테이블 기반 매칭 방식(왜 필요한지, prefix8 확장을 검토했다가 채택하지 않은 이유)은 [data/README.md의 "T-data LINK_ID 매칭"](data/README.md#t-data-link_id-매칭)에 자세히 정리되어 있습니다.

## Pipeline

현재 작업은 다음 순서로 이어집니다.

1. `01~03`: 전국 표준노드링크 스키마를 확인하고 서울 행정경계와 교차하는 63,548개 링크를 추출합니다.
2. `04`: T-data 서비스링크를 서울시 공식 매핑 테이블로 표준링크에 연결합니다. 한 원본 관측이 여러 표준링크로 복제되는 구조를 추적할 수 있도록 `source_section_id`, `source_observation_id`, `mapping_copy_count`, `sample_weight`를 보존합니다.
3. `05~06`: 관측 커버리지와 도로망 연결성을 분석하고 지도로 확인합니다.
4. `07`: 링크 시작·중간·끝 고도, 고도차, signed/absolute 경사도를 생성합니다.
5. `08~09`: T-data 대상 시각의 KMA 레이더를 수집하고 링크별 1시간 누적 강수량을 결합합니다.
6. `13`: 전 링크 공통 노드 연결 구조, 경사 이상치 보정, 도로 용량 조합 피처를 생성합니다.
7. `10`: 날짜 순차 분할과 원본 서비스구간 GroupKFold로 시간·공간 일반화를 평가합니다.
8. `11~12`: 원하는 시각의 전 링크 기상 스냅샷을 만든 뒤 63,548개 링크 모두의 속도와 통행시간을 생성합니다.

속도 산출 우선순위는 다음과 같습니다.

```text
해당 시각 공식 관측값
    -> 관측값이 없으면 전 링크 Model B 예측
    -> 학습에 없던 범주/피처 결측이면 계층적 fallback
    -> speed_kmh로 링크 통행시간 계산
```

## Model B Features

Model B에는 **서울 전체 링크에서 예측 시점에도 얻을 수 있는 값만** 넣습니다.

| 구분 | 주요 피처 |
| --- | --- |
| 도로 기본 | `LANES`, `MAX_SPD`, `LENGTH`, `ROAD_RANK`, `ROAD_TYPE`, `ROAD_USE`, `MULTI_LINK`, `CONNECT`, 통행제한 속성 |
| 지형 | 시작·중간·끝·평균·최소·최대 고도, 고도차, signed/absolute 경사도, DEM 샘플 수 |
| 경사 보정 | `slope_pct_clipped`, 경사 이상치 여부, 오르막·내리막·급오르막, 경사×길이 |
| 시간 | 시간코드, 요일, 주말, 오전·오후 첨두, 시간/요일 `sin`·`cos` |
| 강수 | 원 강수량, 비 여부, `log(1+강수량)`, 강수 등급, 강수×첨두, 강수×제한속도 |
| 도로 위상 | F/T 노드 진입·진출 링크 수, 주변 링크 평균 제한속도·차로수, 노드 복잡도, 하류 제한속도 차이 |
| 조합 | 제한속도×차로수, 링크길이×노드복잡도 |

`speed_lag_1`, `rolling_mean_3h`, `same_hour_mean` 같은 과거 속도 피처는 T-data가 없는 82.67% 링크에서 만들 수 없으므로 Model B에서 제외합니다. T-data 전용 `도로구분코드`, `도로방향구분코드`도 같은 이유로 제외합니다. 현재 데이터가 2026년 7월의 10일뿐이므로 월·계절·공휴일 효과도 아직 사용하지 않습니다.

## Notebooks

| Notebook | Description |
| --- | --- |
| `10_eda_report.ipynb` | 최종 결합 테이블을 입력으로 강수량·경사도·도로등급·첨두시간대별 평균속도 EDA 테이블과 차트를 생성하는 리포트. 집계 테이블은 셀 출력으로 바로 보여주고, 보고서용 차트 7장만 `docs/figures/eda/`에 저장 |
| `11_speed_model_baseline.ipynb` | 초기 LightGBM 베이스라인과 랜덤/그룹 분할 비교. 현재 공식 원본 관측 단위 평가 기준은 `10_evaluate_speed_model.py`가 담당 |

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
시간 일반화: MAE 4.72 km/h | R² 0.740
공간 일반화(5-fold 평균): MAE 5.61 km/h | R² 0.641
원본 관측 train/test 중복: 0건
전 링크 예측 결과: 63,548개 | 속도/통행시간 결측 0건
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

python src\13_build_link_model_features.py
python src\10_evaluate_speed_model.py --spatial-folds 5 --n-estimators 200

# 예: 2026-07-16 08:00 서울 전 링크 예측
python src\11_build_all_link_weather_snapshot.py --tm 202607160800
python src\12_predict_all_link_speed.py --tm 202607160800 --train-end 20260715

python -m nbconvert --to notebook --execute --inplace notebooks\10_eda_report.ipynb
python -m nbconvert --to notebook --execute --inplace notebooks\11_speed_model_baseline.ipynb
```

DEM과 레이더 원본 피처가 이미 생성되어 있고 속도 라벨만 다시 결합할 때는 대용량 원본을 재처리하지 않아도 됩니다.

```bat
python src\07_add_dem_features.py --merge-only
python src\09_add_radar_precip_features.py --merge-only
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
- Model B의 공간 일반화 평가는 관측 서비스구간 일부를 통째로 제외하는 방식입니다. 실제 미관측 82.67% 링크에는 정답 속도가 없으므로 그 구간의 정확도를 직접 측정한 결과는 아닙니다.
- 현재 전 링크 출력으로 연결된 서울 도로망의 경로탐색 입력은 만들 수 있지만, 최소시간·최소에너지 라우팅 로직 자체는 별도 단계입니다.
- 서울 링크 추출 기준(bbox → 행정경계), T-data LINK_ID 매칭 방식과 그 배경, 캐시 무효화 시 주의사항 등은 모두 [data/README.md](data/README.md)에 정리되어 있습니다.
