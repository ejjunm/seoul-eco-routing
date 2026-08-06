# Seoul Eco Routing

서울시 도로 링크, ITS 5분 단위 교통소통 데이터, DEM 고도, KMA 레이더 강수량을 결합해 서울 전역 링크의 시간대별 속도와 통행시간을 추정하는 프로젝트입니다.

현재 속도 데이터는 ITS 국가교통정보센터 계열의 5분 단위 전국 교통소통 원본(하루 약 1.7억 행)을 서울 표준노드링크 LINK_ID 기준으로 걸러 1시간 단위로 집계해 사용합니다(과거에 쓰던 T-data 1시간 소통정보 + 공식 매핑 테이블 방식은 커버리지가 17.33%에 그쳐 대체했습니다 — 배경은 [data/README.md](data/README.md) 참고). KMA 레이더 강수량은 API로 내려받아 시간·공간 기준으로 링크에 매칭합니다.

5분 데이터로도 서울 표준링크 63,548개 중 44,960개(70.75%)만 직접 관측됩니다(나머지는 TOPIS 관측 인프라가 없는 이면도로). 그래서 파이프라인은 관측 링크만 연결해 경로를 찾는 방식이 아니라, 관측값을 학습 라벨로 쓰고 모든 링크에서 구할 수 있는 도로·지형·시간·강수 피처로 나머지 링크의 속도를 추정하는 **전 링크 모델(Model B)** 을 이어 붙입니다.

데이터 스키마, 서울 링크 추출/매칭 방식, 누수 방지 평가, 전 링크 추정 방식과 한계는 **[data/README.md](data/README.md)**를 참고하세요.

## Project Structure

```text
.
├── src/
│   ├── 01_inspect_network_schema.py
│   ├── 02_extract_seoul_links.py
│   ├── 03_summarize_seoul_links.py
│   ├── 04_aggregate_5min_speed.py
│   ├── 05_merge_5min_link_speed.py
│   ├── 06_analyze_matched_links.py
│   ├── 07_plot_matched_links_map.py
│   ├── 08_add_dem_features.py
│   ├── 09_fetch_kma_radar.py
│   ├── 10_add_radar_precip_features.py
│   ├── 11_evaluate_speed_model.py
│   ├── 12_build_all_link_weather_snapshot.py
│   ├── 13_predict_all_link_speed.py
│   └── 14_build_link_model_features.py
├── notebooks/
│   ├── 10_eda_report.ipynb        # 주의: 재정비 필요, 아래 Notebooks 참고
│   ├── 11_speed_model_baseline.ipynb  # 주의: 재정비 필요, 아래 Notebooks 참고
│   ├── 12_derived_features_lightgbm.ipynb  # 파생/외부 피처 검증
│   ├── 12_model_a_history.ipynb   # 관측 링크용 이력 모델
│   └── 13_tier_split_evaluation.ipynb  # A/B/C 계층 분리 평가
├── data/
│   ├── README.md       # 데이터 스키마/매칭 방식/결과 상세 문서
│   ├── raw/
│   │   ├── road/       # MOCT_LINK.*, MOCT_NODE.*, MULTILINK.dbf, TURNINFO.dbf
│   │   ├── boundary/   # seoul_admin_boundary.geojson (서울 25개 자치구 경계)
│   │   ├── traffic/    # 5분 단위 전국 교통소통 원본(202607_5Min/*.csv) 등
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
| 5분 단위 전국 교통소통 | `data/raw/traffic/202607_5Min/*_5Min.csv` | 링크별 5분 단위 통과속도(하루치 약 7GB, 전국 단위) |
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
| `04_aggregate_5min_speed.py` | 5분 단위 전국 교통소통 원본(하루 약 1.7억 행)에서 서울 링크만 걸러 1시간 단위로 집계 |
| `05_merge_5min_link_speed.py` | 04번 결과를 서울 링크 속성과 결합. `source_section_id`/`source_observation_id`/`sample_weight`도 채워서 Model B 학습이 그대로 쓸 수 있게 함 |
| `06_analyze_matched_links.py` | 매칭률, 도로등급별 커버리지, 연결 컴포넌트 분석 |
| `07_plot_matched_links_map.py` | 매칭 링크 지도 이미지와 GeoJSON 생성 |
| `08_add_dem_features.py` | DEM에서 링크별 고도/경사도 피처 생성(`--merge-only`로 속도 라벨만 재결합 가능) |
| `09_fetch_kma_radar.py` | KMA HSR 격자와 1시간 누적 레이더 강수량 다운로드 |
| `10_add_radar_precip_features.py` | 레이더 강수량을 링크·시간 기준으로 결합(`--merge-only` 지원) |
| `11_evaluate_speed_model.py` | 원본 관측 누수를 막은 시간·공간 일반화 평가와 피처 중요도 저장 |
| `12_build_all_link_weather_snapshot.py` | 특정 시각의 서울 전체 63,548개 링크 강수 스냅샷 생성 |
| `13_predict_all_link_speed.py` | 관측값, 전 링크 모델, 계층적 fallback을 결합해 전체 링크 속도·통행시간 생성 |
| `14_build_link_model_features.py` | 모든 링크에서 사용할 수 있는 노드 위상·경사 보정·조합 피처 생성 |

이전 T-data+공식매핑 방식에서 5분 데이터 방식으로 왜 바꿨는지, 매칭 방법이 어떻게 검증됐는지는 [data/README.md의 "속도 데이터 매칭"](data/README.md#속도-데이터-매칭)에 자세히 정리되어 있습니다.

## Pipeline

현재 작업은 다음 순서로 이어집니다.

1. `01~03`: 전국 표준노드링크 스키마를 확인하고 서울 행정경계와 교차하는 63,548개 링크를 추출합니다.
2. `04~05`: 5분 단위 전국 교통소통 원본에서 서울 링크만 걸러 1시간 단위로 집계하고 링크 속성과 결합합니다(44,960개 링크, 70.75%).
3. `06~07`: 관측 커버리지와 도로망 연결성을 분석하고 지도로 확인합니다.
4. `08`: 링크 시작·중간·끝 고도, 고도차, signed/absolute 경사도를 생성합니다.
5. `09~10`: 필요한 시각의 KMA 레이더를 수집하고 링크별 1시간 누적 강수량을 결합합니다.
6. `14`: 전 링크 공통 노드 연결 구조, 경사 이상치 보정, 도로 용량 조합 피처를 생성합니다.
7. `11`: 날짜 순차 분할과 원본 링크 GroupKFold로 시간·공간 일반화를 평가합니다.
8. `12~13`: 원하는 시각의 전 링크 기상 스냅샷을 만든 뒤 63,548개 링크 모두의 속도와 통행시간을 생성합니다.

속도 산출 우선순위는 다음과 같습니다.

```text
해당 시각 5분 데이터 관측값
    -> 관측값이 없으면 전 링크 Model B 예측
    -> 학습에 없던 범주/피처 결측이면 계층적 fallback
    -> speed_kmh로 링크 통행시간 계산
```

**주의**: `11~14`(Model B)는 이전 T-data 기반 데이터(11,010개 링크, 17.33%)로 학습·평가됐던 코드입니다. 5분 데이터(44,960개 링크, 70.75%) 기준으로는 아직 재학습/재평가하지 않았습니다 — 컬럼 구조는 `05_merge_5min_link_speed.py`가 호환되게 맞춰놨지만(`sample_weight`/`source_section_id`/`source_observation_id` 포함), 관측 커버리지가 커진 만큼 성능도 달라질 가능성이 높습니다. "Current Results"의 Model B 수치는 이전 버전 기준이니 재실행 전까지 참고용으로만 보세요.

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

`speed_lag_1`, `rolling_mean_3h`, `same_hour_mean` 같은 과거 속도 피처는 관측이 없는 링크에서 만들 수 없으므로 Model B에서 제외합니다. T-data 전용이었던 `도로구분코드`, `도로방향구분코드`도 5분 데이터에는 없어서 같은 이유로 제외합니다. 현재 데이터가 2026년 7월 14일뿐이므로 월·계절·공휴일 효과도 아직 사용하지 않습니다.

## Notebooks

| Notebook | Description |
| --- | --- |
| `10_eda_report.ipynb` | 최종 결합 테이블을 입력으로 강수량·경사도·도로등급·첨두시간대별 평균속도 EDA 테이블과 차트를 생성하는 리포트. 집계 테이블은 셀 출력으로 바로 보여주고, 보고서용 차트 7장만 `docs/figures/eda/`에 저장 |
| `11_speed_model_baseline.ipynb` | 초기 LightGBM 베이스라인과 랜덤/그룹 분할 비교. 현재 공식 원본 관측 단위 평가 기준은 `11_evaluate_speed_model.py`가 담당 |
| `12_derived_features_lightgbm.ipynb` | 파생/외부 피처(버스전용차로 겹침비율, View-T 추정교통량, 순환 인코딩, 인접 실측 이웃속도)를 LightGBM 하나로 빠르게 검증 |
| `12_model_a_history.ipynb` | 관측 링크(Model A)용 이력 모델 — 링크×시간×주중/주말 조회표와 lag 피처 비교 |
| `13_tier_split_evaluation.ipynb` | 링크를 A(관측)/B(미관측·이웃있음)/C(미관측·이웃없음)로 나눠 계층별로 성능을 재측정. 인접 이웃속도 피처가 C 계층에서 성능을 떨어뜨리는 문제와 분리 모델 해결책을 검증 |

**주의**: `10`/`11` 두 노트북은 예전 T-data 기반 컬럼(`도로방향구분코드`, `도로구분코드`, `요일코드`, `요일그룹코드`, `첨두시구분`, `도로명`, `시작노드명`/`종료노드명`, `broadcast_source_count` 등)을 참조합니다. 5분 데이터 기반 파이프라인으로 바뀌면서 이 컬럼들이 최종 테이블에서 전부 빠졌기 때문에(대신 `sample_count_5min`이 생김), **지금 상태로 재실행하면 오류가 납니다.** `요일`/`첨두시구분`류는 `기준일`/`시간코드`로 직접 계산해서 대체할 수 있지만, `도로구분코드`(TOPIS 자체 간선/이면 분류)는 5분 데이터에 대응 정보가 없어 복원이 안 됩니다. 재실행 전에 두 노트북의 피처 목록을 새 스키마에 맞게 다시 정비해야 합니다.

노트북을 실행하려면:

```bat
jupyter lab notebooks\10_eda_report.ipynb
```

또는 커널 없이 일괄 실행 후 저장하려면:

```bat
python -m nbconvert --to notebook --execute --inplace notebooks\10_eda_report.ipynb
python -m nbconvert --to notebook --execute --inplace notebooks\11_speed_model_baseline.ipynb
python -m nbconvert --to notebook --execute --inplace notebooks\13_tier_split_evaluation.ipynb
```

`13_tier_split_evaluation.ipynb`는 15.1M행을 6번 학습해서 약 15분 걸립니다. 빠르게 확인만 하려면 설정 셀의 `SAMPLE_FRAC`을 `0.15`로 낮추면 5분 안에 끝나며 결론은 동일합니다. 실행 시 `data/interim/nb13_feature_cache.parquet`(피처 캐시)와 `nb13_results.csv`(폴드별 원시 결과)가 생성되며, 둘 다 이 노트북 전용 산출물이라 공식 파이프라인 목록에는 포함되지 않습니다.

## Current Results (요약)

```text
서울 링크 수: 63,548
속도 데이터 결합 고유 링크 수: 44,960 (70.75%)
연결 컴포넌트 수: 1,650 | 최대 컴포넌트 링크 비율: 95.28%
DEM 샘플 존재 링크 비율: 100.0%
레이더 강수 결합 완료 시각: 336/336
```

Model B(구 T-data 버전, 11,010개 링크 기준 — 5분 데이터로 재평가 전):

```text
시간 일반화: MAE 4.72 km/h | R² 0.740
공간 일반화(5-fold 평균): MAE 5.61 km/h | R² 0.641
원본 관측 train/test 중복: 0건
전 링크 예측 결과: 63,548개 | 속도/통행시간 결측 0건
```

계층별 성능(`13_tier_split_evaluation.ipynb`, 5분 데이터 44,960개 링크 · 15.1M행 기준):

| 계층 | 링크수 | 연장 | 배포 시 쓰는 방법 | 평가 분할 | R² | MAE |
| --- | ---: | ---: | --- | --- | ---: | ---: |
| A 관측 | 44,960 (70.7%) | 4,858 km | 이력 조회표(링크×시간×주중/주말) | 날짜 순차 | 0.877 | 2.75 |
| B 미관측·이웃있음 | 14,006 (22.0%) | 787 km | LightGBM + 인접 실측 이웃속도 | 공간 블록 2km | 0.763 | 5.81 |
| C 미관측·이웃없음 | 4,582 (7.2%) | 402 km | LightGBM 정적+교통량 (이웃속도 **제외**) | 공간 블록 2km | 0.454 | 6.22 |

C 계층에 이웃속도 피처를 그대로 넣으면 R²가 0.454 → 0.302로 **떨어집니다**(훈련 때 있던 피처가 배포 때 결측이 되는 문제). 미관측 링크는 계층별로 다른 모델을 써야 합니다 — 근거와 해결책 비교는 노트북 6절 참고.

외부 피처의 계층별 커버리지(노트북 2절):

| 계층 | 현재 View-T 추정교통량(Level5.5) | View-T 상세도로망 Level6 |
| --- | ---: | ---: |
| A 관측 | 17,675 (39.3%) | 26,384 (58.7%) |
| B 미관측·이웃있음 | 204 (1.5%) | 3,412 (24.4%) |
| C 미관측·이웃없음 | 50 (1.1%) | 1,347 (29.4%) |

추가 외부 데이터는 **C 계층을 덮는 것만 가치가 있습니다.** View-T 혼잡시간강도는 Level6로 제공되어 C 커버리지가 1.1% → 29.4%가 되며, `data/raw/traffic/seoul_lev6_2024/seoul_link_lev6_2024.shp`의 `up_its_id`/`dw_its_id`로 `LINK_ID`에 바로 조인됩니다.

전체 수치, 도로등급별 매칭률, 미매칭 링크 특성은 [data/README.md의 "Current Results"](data/README.md#current-results)를 참고하세요.

## Workflow

```bat
.venv\Scripts\activate.bat

python src\01_inspect_network_schema.py
python src\02_extract_seoul_links.py
python src\03_summarize_seoul_links.py
python src\04_aggregate_5min_speed.py
python src\05_merge_5min_link_speed.py
python src\06_analyze_matched_links.py
python src\07_plot_matched_links_map.py
python src\08_add_dem_features.py
python src\09_fetch_kma_radar.py --grid
python src\09_fetch_kma_radar.py --from-5min-times
python src\10_add_radar_precip_features.py

python src\14_build_link_model_features.py
python src\11_evaluate_speed_model.py --spatial-folds 5 --n-estimators 200

# 예: 2026-07-16 08:00 서울 전 링크 예측
python src\12_build_all_link_weather_snapshot.py --tm 202607160800
python src\13_predict_all_link_speed.py --tm 202607160800 --train-end 20260715

python -m nbconvert --to notebook --execute --inplace notebooks\10_eda_report.ipynb
python -m nbconvert --to notebook --execute --inplace notebooks\11_speed_model_baseline.ipynb
```

DEM과 레이더 원본 피처가 이미 생성되어 있고 속도 라벨만 다시 결합할 때는 대용량 원본을 재처리하지 않아도 됩니다.

```bat
python src\08_add_dem_features.py --merge-only
python src\10_add_radar_precip_features.py --merge-only
```

가상환경을 활성화하지 않고 실행할 때:

```bat
.venv\Scripts\python.exe src\10_add_radar_precip_features.py
```

KMA 레이더 한 시각만 받을 때:

```bat
python src\09_fetch_kma_radar.py --tm 202607070300
```

## Notes

- T-data API 수집 코드는 사용하지 않습니다(현재는 T-data 자체를 파이프라인에서 쓰지 않고, 5분 단위 전국 교통소통 데이터로 대체했습니다).
- `data/raw/` 아래 원본 데이터는 직접 받은 파일이므로 코드에서 수정하지 않는 것을 원칙으로 합니다.
- 5분 단위 원본은 하루치가 약 7GB(전국 단위)라 `04_aggregate_5min_speed.py`가 서울 링크만 걸러 1시간 단위로 압축합니다. 원본 용량 때문에 `data/raw/traffic/202607_5Min/`에는 보통 최근 받은 날짜만 남아있는데, 04번은 실행할 때마다 기존 `seoul_link_speed_5min_hourly.csv`를 읽어 지금 폴더에 없는 과거 날짜는 보존하고 폴더에 있는 날짜만 새로 반영합니다 — 새 날짜를 추가하려면 그 날짜 파일만 폴더에 넣고 04번을 다시 실행하면 됩니다.
- Model B의 공간 일반화 평가는 관측 링크 일부를 통째로 제외하는 방식입니다. 실제 미관측 29.25% 링크에는 정답 속도가 없으므로 그 구간의 정확도를 직접 측정한 결과는 아닙니다.
- 현재 전 링크 출력으로 연결된 서울 도로망의 경로탐색 입력은 만들 수 있지만, 최소시간·최소에너지 라우팅 로직 자체는 별도 단계입니다.
- 서울 링크 추출 기준(bbox → 행정경계), 속도 데이터 매칭 방식과 그 배경, 캐시 무효화 시 주의사항 등은 모두 [data/README.md](data/README.md)에 정리되어 있습니다.
