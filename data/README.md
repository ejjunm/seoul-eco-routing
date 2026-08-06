# Data 상세 문서

루트 [README.md](../README.md)는 프로젝트 구조/실행 방법 위주의 뼈대만 담고 있습니다. 이 문서는 각 원본 데이터의 스키마, 서울 링크 추출 기준, 속도 데이터 매칭 방식이 왜 지금 형태가 됐는지에 대한 배경·진단·검증 과정, 미관측 링크를 채우는 Model B의 누수 방지·평가 방식, 현재 결과 수치, 알아둬야 할 한계를 자세히 다룹니다.

## 목차

1. [MOCT_LINK (ITS 표준노드링크)](#moct_link-its-표준노드링크)
2. [서울 행정경계와 링크 추출](#서울-행정경계와-링크-추출)
3. [속도 데이터 매칭](#속도-데이터-매칭)
4. [DEM](#dem)
5. [KMA HSR Radar](#kma-hsr-radar)
6. [Generated Outputs](#generated-outputs)
7. [Current Results](#current-results)
8. [누수 방지와 Model B 평가](#누수-방지와-model-b-평가)
9. [서울 전 링크 속도 생성](#서울-전-링크-속도-생성)
10. [Notes / 한계](#notes--한계)

---

## MOCT_LINK (ITS 표준노드링크)

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

`UPDATEDATE` 컬럼 기준으로 현재 파일의 서울 링크 63,548개 중 62,229개(98%)가 `20250512`로 일괄 갱신된 최신 버전입니다. 과거에 쓰던 T-data(TOPIS 1시간 소통정보)는 이 갱신 시점과 다른 구버전 표준노드링크를 참조해서 단순 LINK_ID 조인이 잘 안 맞았습니다(아래 "속도 데이터 매칭" 참고). 지금 쓰는 5분 단위 속도 데이터는 LINK_ID가 이 최신 버전과 직접 일치합니다.

---

## 서울 행정경계와 링크 추출

### 문제: bbox 기준 추출의 부정확성

초기 버전(`src/pipeline/01_extract_seoul_links.py`)은 서울을 감싸는 사각형(bbox: 경도 126.75~127.20, 위도 37.40~37.72)과 겹치는 링크를 "서울 링크"로 추출했습니다. bbox는 서울의 실제 모양(각지고 불규칙한 25개 자치구 경계)보다 넓은 사각형이라, 경기/인천 일부 링크가 서울로 잘못 포함됐습니다.

### 해결: 행정경계 GeoJSON + intersects

- 경계 데이터: [southkorea/seoul-maps](https://github.com/southkorea/seoul-maps) 저장소의 2015년 서울 25개 자치구 경계 (`juso/2015/json/seoul_municipalities_geo.json`, `EPSG:4326`, `Polygon` 25개)
- `src/pipeline/01_extract_seoul_links.py`가 25개 자치구 폴리곤을 하나로 합친(`union_all()`) 뒤 `MOCT_LINK`의 좌표계로 변환하고, `intersects`로 경계와 조금이라도 겹치는 링크를 추출
- `clip`을 쓰지 않는 이유: 경계선에 걸친 링크의 geometry가 잘리면 그래프 연결성이 오히려 나빠지기 때문(도로가 중간에 끊긴 것처럼 됨)

### 결과

| | bbox 기준 | 행정경계 기준 |
| --- | --- | --- |
| 서울 추정 링크 수 | 109,633 | **63,548** |

행정경계로 바꾸면서 링크 수가 42% 줄었는데, 이는 실제로 서울이 아니었던 경기/인천 인접 링크가 제거됐기 때문입니다.

### 경계 데이터 라이선스 주의

`data/raw/boundary/seoul_admin_boundary.geojson`은 다른 raw 데이터와 달리 예외적으로 Git에 커밋되어 있습니다(크기 1.6MB, 정적 참조 데이터). 다만 출처 저장소(`southkorea/seoul-maps`)에 명시적 라이선스 파일이 없어(`LICENSE` 없음, GitHub API 기준 `license: None`), 이 저장소가 public으로 전환되기 전에 공공누리(KOGL) 라이선스가 명시된 공식 출처(통계청 SGIS, 국토교통부 VWorld, 국가공간정보포털 등)로 교체하는 것을 권장합니다.

---

## 속도 데이터 매칭

### 배경: T-data + 공식 매핑 테이블의 한계

T-data(`1시간 소통정보 (구간별).csv`)를 `LINK_ID`/`링크ID` exact match로 결합하면 매칭률이 매우 낮았습니다. 표준노드링크가 주기적으로 갱신되며 링크 하나가 여러 세부 링크로 재번호되는 경우가 많아, T-data가 참조하는 원래 ID가 현재 MOCT_LINK에 아예 존재하지 않는 경우가 많았기 때문입니다.

이후 서울시가 TOPIS 내부 링크체계(서비스링크)와 표준노드링크 LINK_ID를 공식적으로 연결해주는 매핑 테이블(`서울특별시 교통소통 표준링크 매핑정보_20250306.xlsx`)을 확보해 exact match/prefix8 추정을 이 정답 매핑으로 대체했지만, 매핑률이 17.33%(11,010개 링크)에 그쳤고 연결성도 최대 컴포넌트 0.27%로 매우 낮아 다익스트라 경로탐색에 쓸 수 없었습니다. 근본 원인은 공식 매핑 테이블 자체가 TOPIS가 직접 관측(VDS 등)하는 링크만 담고 있다는 데 있어, 매칭 방법을 아무리 개선해도 이 상한을 넘을 수 없었습니다.

### 현재 방식: 5분 단위 전국 교통소통 데이터 직접 매칭 (`src/pipeline/02_aggregate_5min_speed.py`, `src/pipeline/05_build_speed_fact.py`)

ITS 국가교통정보센터 계열에서 받은 5분 단위 전국 교통소통 원본(`data/raw/traffic/202607_5Min/YYYYMMDD_5Min.csv`, 하루 약 1.7억 행)의 `LINKID` 컬럼이 서울 표준노드링크 `LINK_ID`와 **직접 일치**한다는 것을 검증했습니다(T-data의 서비스링크처럼 별도 매핑 테이블이 필요 없음).

- `src/pipeline/02_aggregate_5min_speed.py`가 원본에서 서울 `LINK_ID`와 일치하는 행만 걸러 (LINK_ID, 기준일, 시간코드) 단위로 5분 값을 평균 내 1시간 단위로 집계합니다(`sample_count_5min` 컬럼에 시간당 몇 개의 5분 샘플이 쓰였는지 남깁니다, 최대 12).
- `src/pipeline/05_build_speed_fact.py`는 이 결과에 레이더 강수·시간대별 교통량만 결합해 `seoul_link_speed_fact.csv`(팩트 테이블)를 만듭니다 — 링크 속성처럼 시간이 지나도 안 변하는 값은 여기 안 들어가고 `src/pipeline/04_build_link_dimension.py`가 만드는 `seoul_link_dimension.csv`(차원 테이블) 쪽에 링크당 1행으로 따로 저장됩니다(옛 버전은 정적 속성을 관측 행마다 최대 336번씩 중복 저장해서 용량이 컸습니다 — 두 테이블은 `LINK_ID`로 merge해서 씁니다). T-data 때와 달리 1:N broadcast나 서비스링크 크로스워크도 필요 없습니다.
- `match_method`(전부 `5min_direct`), `source_section_id`(=`LINK_ID`), `source_observation_id`(=`LINK_ID_기준일_시간코드`), `sample_weight`(전부 `1.0`)는 전부 상수이거나 즉시 유도 가능해서 팩트 테이블에 저장하지 않습니다 — Model B(`src/models/11_evaluate_speed_model.py`, 아래 "누수 방지와 Model B 평가" 참고)처럼 이 컬럼이 필요한 소비 스크립트가 로드 직후 한 줄로 채워 씁니다.

**검증**: 같은 기간 T-data와 비교했을 때, T-data 링크ID가 우연히 현재 LINK_ID와 일치하는 부분집합(약 29.6%, exact match 가능 구간)에서 상관계수 0.94~0.97, 평균절대오차 2~3km/h로 높은 일치도를 보였습니다. 공식 매핑을 거쳐 1:N broadcast가 적용된 구간에서만 상관계수가 0.80으로 낮아졌는데, 형제 링크별로 나눠 확인한 결과 이건 5분 데이터가 부정확해서가 아니라 **T-data 공식 매핑 자체가 같은 값을 여러 형제 링크에 복제하는 근사치 한계** 때문임을 확인했습니다(5분 데이터는 형제 링크마다 실제로 다른 값을 개별 관측).

### 결과: 매칭률과 연결성 모두 크게 개선

| | T-data + 공식 매핑 | 5분 데이터 직접 매칭 |
| --- | --- | --- |
| 매칭 링크 수 | 11,010 (17.33%) | **44,960 (70.75%)** |
| 최대 연결 컴포넌트 | 0.27% | **95.28%** |
| ROAD_RANK 101~106 매칭률 | 대부분 10~46% | **97~100%** |
| 다익스트라 경로탐색 | 불가 | **가능** |
| 기간 | 최대 10일 | 손쉽게 확장 가능(하루 ~7GB 원본, 처리 후엔 압축됨) |

### 남은 미매칭 30%의 정체

미매칭 18,588개 링크를 분석한 결과:

- 96.1%가 `ROAD_RANK=104`, 93.6%가 1차로 — 대부분 TOPIS 관측 인프라(VDS 등)가 없는 좁은 이면도로/골목길입니다.
- T-data 원본 링크ID와 직접 겹치는 게 0개, 공식 매핑 테이블 타겟으로도 21개뿐 — T-data/공식매핑으로도 못 채웠던 도로들과 사실상 같은 집합입니다.
- 서비스링크 보간점(좌표) 기반 공간매칭(버퍼+겹침비율)으로 시도해봐도 6.93%(1,288개)만 닿을 수 있어, 관측 인프라가 아예 없는 도로를 매칭 방법 개선만으로 채우는 데는 한계가 있습니다.

이 나머지는 관측 데이터 확장이 아니라 구조적 피처(`ROAD_RANK`/`MAX_SPD`/`LANES`/경사 등) 기반 외삽 모델이 필요한 영역입니다.

### 검토했으나 채택하지 않은 것

- **prefix8 확장**: 공식 매핑에 없는 T-data 링크를 prefix8+도로명+속성+위상연결로 추가 매칭하면 매칭률을 43%대까지 끌어올릴 수 있었지만, 5분 데이터 직접 매칭(70.75%)이 이를 이미 크게 상회해 더 이상 검토 우선순위가 아닙니다.
- **서비스링크 보간점 기반 공간매칭 확장**: 위 미매칭 분석에서 쓴 방법(8m 버퍼 + 80% 겹침 비율)을 실제 매칭 확장에 쓰면 공식 매핑 대비 재현율 92.5%, 도로명이 같은 추가 후보를 다수 찾긴 하지만, 일부 오탐(다른 도로명)도 섞여 있어 정제 없이 바로 쓰기엔 이릅니다. 5분 데이터가 이미 훨씬 넓은 커버리지를 주므로 현재는 후순위입니다.

---

## DEM

| Item | Value |
| --- | --- |
| Files | `37608.img`, `37612.img`, `37705.img`, `37709.img` |
| Format | HFA `.img` |
| CRS | `EPSG:5179` |
| Resolution | `90m x 90m` |
| Bands | 1 |
| dtype | `float32` |
| nodata | `-9999` |

도로 링크와 DEM의 좌표계가 다르므로 `src/pipeline/04_build_link_dimension.py`에서 링크를 `EPSG:5179`로 변환한 뒤 샘플링합니다. 링크마다 시작/25%/중간/75%/끝 5개 지점을 샘플링해 평균·최소·최대 고도와 경사도를 계산합니다.

DEM이 90m 해상도이므로 짧은 링크에서는 경사도 값이 튈 수 있습니다. 모델링 전 `LENGTH` 기준 필터링이나 경사도 이상치 처리가 필요합니다.

---

## KMA HSR Radar

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

KMA 레이더 원본은 한 시각당 약 48MB이며, 현재 5분 속도 데이터 대상(7/7~7/20, 14일) 336개 시각 원본은 약 16GB입니다. API에 일일 다운로드 용량 제한이 있어 여러 날에 걸쳐 나눠 받아야 할 수 있습니다. `src/pipeline/03_fetch_kma_radar.py`는 이미 받은 파일을 건너뛰는 구조라(`save_text`의 존재 확인), 같은 명령을 다음 날 다시 실행하면 자동으로 이어받습니다. 다만 "일일 한도 초과" 자체를 감지해 그 자리에서 중단하지는 않아서, 한도 초과 이후의 나머지 요청은 각각 실패로 기록됩니다(`radar_failed_tms.txt`). 이 파일은 실패 기록용이라 재실행 후 전부 성공해도 자동으로 삭제되지 않으니, 다운로드가 실제로 완료됐는지는 `radar_failed_tms.txt`가 아니라 `data/raw/weather/radar/` 안의 실제 파일 존재 여부와 크기로 확인해야 합니다.

---

## Generated Outputs

파이프라인 산출물은 "링크당 1행"인 **차원 테이블**과 "(LINK_ID,기준일,시간코드)당 1행"인 **팩트 테이블**로 정규화되어 있습니다(옛 버전은 정적 속성을 관측 행마다 최대 336번씩 중복 저장해 용량이 컸습니다). 진단/시각화(매칭률, 지도 등)는 `src/pipeline/`이 아니라 노트북이 만듭니다.

`data/interim/`과 `data/processed/`는 역할이 다릅니다 — `interim/`은 `src/pipeline/` 스크립트가 다음 단계를 위해 만드는 **중간 재료**(재실행하면 다시 생기고, 최종 소비자가 직접 읽지 않음)이고, `processed/`는 모델링·라우팅이 바로 읽는 **최종 산출물**입니다. 노트북·`experiments/`가 만드는 캐시(예: `nb12_feature_cache_v4.parquet`)는 `interim/` 바로 아래가 아니라 `data/interim/notebook_cache/`에 모아둡니다 — 파이프라인 공식 중간 재료와 뒤섞이면 뭘 지워도 되는지 구분이 안 되기 때문입니다.

| File | Description |
| --- | --- |
| `data/interim/seoul_link.*` | 서울 행정경계 기준 링크 Shapefile(`src/pipeline/01`) |
| `data/processed/seoul_link_attr.csv` | 서울 링크 속성 테이블(`src/pipeline/01`) |
| `data/interim/seoul_link_speed_5min_hourly.csv` | 5분 원본을 서울 링크 기준 1시간 단위로 집계한 결과 — `src/pipeline/05`의 중간 재료일 뿐 최종 산출물이 아니라 `interim/`에 둠(`src/pipeline/02`) |
| `data/processed/weather_hsr_seoul_grid.npz` | 서울 bbox 주변 HSR 격자 캐시(`src/pipeline/03`/`05`) |
| `data/processed/seoul_link_dem_features.csv` | 링크별 DEM 고도/경사도 피처만 담은 부분표(`src/pipeline/04`가 만들며, `src/routing/12`·`src/routing/15`가 아직 이 파일을 직접 읽어 하위 호환용으로 유지) |
| **`data/processed/seoul_link_dimension.csv`** | **차원 테이블**(63,548행×59컬럼) — 도로속성+DEM+도로망 위상+외부컨텍스트(버스전용차로/스쿨존/사고다발/과속방지턱/AADT) 전부 결합(`src/pipeline/04`) |
| `data/processed/link_radar_grid_mapping.csv` | 링크 중심점과 가장 가까운 HSR 격자 매핑(캐시, 아래 Notes 참고) |
| **`data/processed/seoul_link_speed_fact.csv`** | **팩트 테이블**(15,094,335행) — `LINK_ID`,`기준일`,`시간코드`,`평균속도`(라벨),`sample_count_5min`,`precip_mm`,`traffic_volume_hourly`,`traffic_volume_ratio`(`src/pipeline/05`) |
| `data/processed/speed_model_evaluation_enhanced.json` | Model B 시간·공간 일반화 성능, 누수 검증, 피처 중요도(`src/models/11_evaluate_speed_model.py` 실행 시 생성 — 입력 경로를 새 스키마로 옮기기 전까지는 아직 없음) |
| `data/processed/seoul_all_link_weather_YYYYMMDDHHMM.csv` | 특정 시각의 서울 전 링크 정적 속성 + DEM + 강수 스냅샷(`src/routing/12_build_all_link_weather_snapshot.py`) |
| `data/processed/seoul_all_link_speed_YYYYMMDDHHMM.csv` | 특정 시각의 서울 전 링크 속도, 출처, 신뢰도, 통행시간(`src/routing/13_predict_all_link_speed.py`) |
| `docs/figures/eda/*.png` | `10_eda_report.ipynb`가 생성하는 GitHub/보고서용 EDA 그래프 이미지(재정비 전까지 구버전) |
| `docs/figures/model/*.png` | `11_speed_model_baseline.ipynb`/`12_derived_features_lightgbm.ipynb`가 생성하는 속도 예측 모델 결과 그래프 이미지 |
| `docs/figures/model_a/*.png` | `12_model_a_history.ipynb`(관측 링크용 이력 모델)가 생성하는 그래프 이미지 |

매칭률·연결성 진단(도로등급별 매칭률, 연결 컴포넌트, 매칭 지도 등)은 더 이상 `src/pipeline/`이 만드는 공식 산출물이 아닙니다 — 이번 리팩토링에서 파이프라인 범위 밖으로 빼고, 나중에 새 EDA 노트북에서 새 스키마 기준으로 다시 만들 예정입니다(아래 "Current Results"의 관련 수치는 리팩토링 전 원본 산출물 기준으로 남겨둔 기록입니다).

`data/raw/`, `data/interim/`, `data/processed/`의 실제 데이터 파일은 대용량 원본/중간/가공 데이터라 Git에 올리지 않고 `.gitkeep`만 둡니다. 예외적으로 `data/raw/boundary/seoul_admin_boundary.geojson`은 커밋합니다(위 라이선스 주의 참고).

---

## Current Results

### 5분 데이터 매칭 (`src/pipeline/02_aggregate_5min_speed.py`, `src/pipeline/05_build_speed_fact.py`)

```text
서울 링크 수: 63,548
5분 집계 소스 (링크,날짜,시간) 행 수: 15,094,335
5분 집계 소스 고유 LINK_ID 수: 44,960

매칭 링크 수: 44,960 (70.75%)
결합된 행 수: 15,094,335
```

연결성이 크게 좋아졌습니다.

```text
연결 컴포넌트 수: 1,650
최대 컴포넌트 링크 수: 42,840
최대 컴포넌트 노드 수: 35,698
최대 컴포넌트 링크 비율: 95.28%
샘플 경로 탐색: 가능 (107개 링크, 예상 통행시간 37.83분)
```

5분 데이터 관측 링크만으로도 최대 컴포넌트가 95.28%라 그래프 대부분이 이미 연결돼 있습니다(예전 T-data+공식매핑 방식은 0.27%뿐이라 관측 링크만으로는 경로탐색이 불가능했습니다). 그래도 관측이 없는 29.25%(18,588개)는 여전히 남아있어, Model B로 그 구간의 속도를 채워 전 링크 그래프 입력을 완성합니다. 미관측 링크에는 정답이 없으므로 아래 공간 일반화 평가를 대리 검증으로 사용합니다.

도로등급별 매칭률(리팩토링 전 진단 스크립트 산출물 기준 기록, 새 EDA 노트북에서 재생성 예정):

| ROAD_RANK | 전체 링크 수 | 매칭 링크 수 | 매칭률 |
| --- | --- | --- | --- |
| 101(고속도로) | 352 | 342 | 97.16% |
| 102 | 1,388 | 1,365 | 98.34% |
| 103 | 3,057 | 3,021 | 98.82% |
| 104 | 56,913 | 39,058 | 68.63% |
| 105 | 121 | 120 | 99.17% |
| 106 | 168 | 168 | 100.00% |
| 107 | 1,549 | 886 | 57.20% |

미매칭 18,588개는 "속도 데이터 매칭 > 남은 미매칭 30%의 정체"에서 다뤘듯 96.1%가 `ROAD_RANK=104`·93.6%가 1차로인 이면도로/골목길입니다.

### DEM

```text
서울 링크 수: 63,548
DEM 샘플 존재 링크 비율: 100.0%
대부분 링크의 dem_sample_count: 5
```

### Radar Precipitation

```text
5분 데이터 대상 레이더 시각 수: 336 (7/7~7/20, 14일)
다운로드 완료 레이더 시각 수: 336
누락 레이더 시각 수: 0
최종 결합 행 수: 15,094,335
강수값 존재 행 수: 15,094,335
```

강수량 요약:

```text
mean precip_mm: 5.39
median precip_mm: 0.00
max precip_mm: 53.47
precip_mm > 0 행 수: 3,561,198
precip_mm > 0 시각 수: 148
```

### Speed Feature EDA

**재정비 필요**: `notebooks/10_eda_report.ipynb`와 `notebooks/11_speed_model_baseline.ipynb`는 T-data 시절 컬럼(`도로방향구분코드`, `도로구분코드`, `요일코드`, `요일그룹코드`, `첨두시구분`, `도로명`, `시작노드명`/`종료노드명`, `broadcast_source_count` 등)을 피처로 사용하는데, 5분 데이터 기반 파이프라인에서는 이 컬럼들이 전부 빠집니다(대신 `sample_count_5min`이 생깁니다). 두 노트북을 새 스키마에 맞게 정비하고 재실행하기 전까지, 이 섹션의 이전 EDA 수치(공식 매핑 11,010개 링크 기준)는 지금의 5분 데이터(44,960개 링크) 표본과 맞지 않으므로 참고하지 않는 것을 권장합니다.

---

## 누수 방지와 Model B 평가

### 왜 원본 관측 단위가 필요한가

(T-data + 공식 매핑 시절) 서울시 공식 매핑은 하나의 T-data 서비스링크를 여러 표준링크로 확장할 수 있어서, 이 형제 링크들을 임의의 행 단위로 train/test에 나누면 동일한 속도 라벨이 양쪽에 들어가 성능이 실제보다 좋아지는 문제가 있었습니다. 5분 데이터는 이런 broadcast가 없지만(`source_section_id`가 항상 `LINK_ID`와 같음), 같은 링크의 다른 시간대 관측이 train/test에 나뉘어 들어가는 일반적인 시계열 유출을 막기 위해 같은 그룹분할 인프라를 그대로 재사용합니다.

`src/models/11_evaluate_speed_model.py`는 다음 두 기준으로 이를 방지합니다.

| 평가 | 분할 기준 | 의미 |
| --- | --- | --- |
| 시간 일반화 | 과거 날짜 학습, 미래 날짜 평가 | 이미 알려진 도로의 미래 시간대 속도 예측 |
| 공간 일반화 | `source_section_id`(=`LINK_ID`) GroupKFold | 특정 링크를 학습에서 통째로 제외하고 새로운 도로구간 일반화 평가 |

두 평가 모두 `source_observation_id`가 train/test에 동시에 존재하는지 검사합니다.

### 평가 결과 (구 T-data 버전, 재평가 필요)

아래 수치는 T-data+공식 매핑 시절(11,010개 링크, 17.33%) 데이터로 평가한 결과입니다. 5분 데이터(44,960개 링크, 70.75%)로는 아직 재실행하지 않았습니다 — 관측 커버리지가 4배 가까이 늘고 도로등급 대표성도 좋아진 만큼, 재실행하면 이 수치는 달라질 가능성이 높습니다.

| 평가 | RMSE | MAE | R² |
| --- | ---: | ---: | ---: |
| 시간 일반화 | 6.43 km/h | 4.72 km/h | 0.740 |
| 공간 일반화 5-fold 평균 | 7.71 km/h | 5.61 km/h | 0.641 |

MAE 5.61 km/h는 새 원본 구간의 예측값이 실제 속도와 평균적으로 약 5.61 km/h 차이 난다는 뜻입니다. R² 0.641은 평균속도 하나로 예측하는 기준과 비교했을 때 속도 변동의 약 64.1%를 모델이 설명한다는 뜻입니다.

### Model B 피처 범위

Model B는 미관측 링크에도 적용해야 하므로 전 링크 공통 피처만 사용합니다.

- 도로 속성: 차로수, 제한속도, 길이, `ROAD_RANK`, 도로유형·용도, 연결·통행제한 속성
- 지형: 링크 5개 지점의 고도 통계, 고도차, signed/absolute 경사도
- 경사 보정: `-12~12%` 클리핑, 이상치 여부, 오르막·내리막·급오르막, 경사×길이
- 시간: 시각, 요일, 주말, 첨두시간, 시각·요일 순환형 `sin/cos`
- 강수: 원 강수량, 비 여부, 로그 강수량, 강수 등급, 강수×첨두, 강수×제한속도
- 도로망 위상: 출발/도착 노드의 진입·진출 링크 수, 인접 링크 평균 제한속도·차로수, 노드 복잡도
- 조합: 제한속도×차로수, 링크길이×노드복잡도

과거 속도 lag/rolling, T-data 도로구분·방향코드는 미관측 링크에서 생성할 수 없어 제외했습니다. 월·계절·공휴일은 현재 14일짜리 7월 데이터에서 변화가 거의 없으므로 제외했습니다.

---

## 서울 전 링크 속도 생성

`src/routing/12_build_all_link_weather_snapshot.py`가 특정 시각의 63,548개 링크에 정적 도로·DEM·레이더 강수를 결합하고, `src/routing/13_predict_all_link_speed.py`가 다음 우선순위로 최종 속도를 선택합니다.

1. 해당 시각에 5분 데이터 관측이 있으면 `official_observed`
2. 전 링크 공통 피처가 정상이고 학습 범주에 포함되면 `static_model`
3. 모델 입력이 불가능하면 도로등급·제한속도·시간대 기반 `hierarchical_fallback`

**아래는 구 T-data 버전(11,010개 링크) 기준 2026-07-16 08:00 예시 결과입니다 — 5분 데이터로 재실행하면 `official_observed` 비율이 훨씬 커질 것으로 예상됩니다(재실행 전까지 참고용).**

```text
전체 링크: 63,548
official_observed: 11,010
static_model: 46,991
hierarchical_fallback: 5,547
학습에 없던 범주값 링크: 11
속도 결측: 0
통행시간 결측: 0
```

최종 `speed_kmh`로 `travel_time_sec = LENGTH / speed_kmh`를 계산하므로 모든 링크가 시간 비용을 갖습니다. 이 출력은 서울 전역 라우팅 그래프의 시간 비용 입력으로 사용할 수 있습니다.

---

## Notes / 한계

- `data/raw/` 아래 원본 데이터는 직접 받은 파일이므로 코드에서 수정하지 않는 것을 원칙으로 합니다.
- T-data API 수집 코드는 사용하지 않습니다(현재는 T-data 자체를 파이프라인에서 쓰지 않고, 5분 단위 전국 교통소통 데이터로 대체했습니다 — "속도 데이터 매칭" 참고).
- `data/processed/link_radar_grid_mapping.csv`와 `weather_hsr_seoul_grid.npz`는 캐시 파일입니다(`src/pipeline/05_build_speed_fact.py`). `link_radar_grid_mapping.csv`는 대상 링크 구성이 캐시와 다르면 자동으로 다시 빌드합니다 — 수동으로 지울 필요는 없습니다.
- `seoul_link_speed_fact.csv`의 `sample_count_5min`이 낮은 행(예: 시간당 5분 샘플이 12개 중 몇 개뿐인 경우)은 그 시간대 관측이 성기다는 뜻이니, 정밀한 분석에는 참고하는 게 좋습니다.
- `notebooks/10_eda_report.ipynb`, `notebooks/11_speed_model_baseline.ipynb`는 T-data 시절 컬럼에 의존하고 있어 5분 데이터 기반 파이프라인에서는 재실행 시 오류가 납니다 — 재정비가 필요합니다("Current Results > Speed Feature EDA" 참고).
- `data/raw/traffic/`의 서비스링크 보간점 정보, `seoul_lev6_2024`/`seoul_link_lev5.5_2024`/`level5.5_level6_matchingtable`, 지점별 교통량 정보(139개 지점) 파일들은 매칭 확장 가능성을 검토했던 자료로 현재 파이프라인에서는 쓰지 않습니다(5분 데이터가 이미 이들보다 넓은 커버리지를 제공).
- Model B(`src/models/11`, `src/routing/12`·`13`·`15`)의 공간 일반화는 관측 링크 일부를 숨겨 미관측 링크 상황을 모사한 결과입니다. 실제 미관측 29.25%(18,588개) 링크에는 정답 속도가 없으므로 그 링크들의 오차를 직접 계산한 것은 아닙니다. 또한 "평가 결과" 수치는 아직 구 T-data 버전 기준이라 5분 데이터로 재실행하면 달라질 수 있습니다(위 "누수 방지와 Model B 평가" 참고).
- 현재 원본은 2026-07-07~2026-07-20의 14일 데이터입니다. 계절·월·공휴일 일반화를 주장하려면 더 긴 기간의 속도·기상 데이터가 필요합니다.
- `slope_pct`는 짧은 링크와 90m DEM 해상도 때문에 튈 수 있어 Model B에서는 원본값과 함께 클리핑값·이상치 플래그를 사용합니다.
- 전 링크 속도와 통행시간은 준비됐지만, 에너지 비용식과 최소시간/최소에너지 경로탐색은 후속 단계입니다.
