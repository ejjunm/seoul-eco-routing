# Data 상세 문서

루트 [README.md](../README.md)는 프로젝트 구조/실행 방법 위주의 뼈대만 담고 있습니다. 이 문서는 각 원본 데이터의 스키마, 서울 링크 추출 기준, T-data 매칭 방식이 왜 지금 형태가 됐는지에 대한 배경·진단·검증 과정, 현재 결과 수치, 알아둬야 할 한계를 자세히 다룹니다.

## 목차

1. [MOCT_LINK (ITS 표준노드링크)](#moct_link-its-표준노드링크)
2. [서울 행정경계와 링크 추출](#서울-행정경계와-링크-추출)
3. [T-data LINK_ID 매칭](#t-data-link_id-매칭)
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

`UPDATEDATE` 컬럼 기준으로 현재 파일의 서울 링크 63,548개 중 62,229개(98%)가 `20250512`로 일괄 갱신된 최신 버전입니다. 이 갱신 시점이 T-data가 참조하는 표준노드링크 버전과 달라서(아래 "T-data LINK_ID 매칭" 참고) 단순 LINK_ID 조인이 잘 안 맞는 근본 원인이 됩니다.

---

## 서울 행정경계와 링크 추출

### 문제: bbox 기준 추출의 부정확성

초기 버전(`02_extract_seoul_links.py`)은 서울을 감싸는 사각형(bbox: 경도 126.75~127.20, 위도 37.40~37.72)과 겹치는 링크를 "서울 링크"로 추출했습니다. bbox는 서울의 실제 모양(각지고 불규칙한 25개 자치구 경계)보다 넓은 사각형이라, 경기/인천 일부 링크가 서울로 잘못 포함됐습니다.

### 해결: 행정경계 GeoJSON + intersects

- 경계 데이터: [southkorea/seoul-maps](https://github.com/southkorea/seoul-maps) 저장소의 2015년 서울 25개 자치구 경계 (`juso/2015/json/seoul_municipalities_geo.json`, `EPSG:4326`, `Polygon` 25개)
- `02_extract_seoul_links.py`가 25개 자치구 폴리곤을 하나로 합친(`union_all()`) 뒤 `MOCT_LINK`의 좌표계로 변환하고, `intersects`로 경계와 조금이라도 겹치는 링크를 추출
- `clip`을 쓰지 않는 이유: 경계선에 걸친 링크의 geometry가 잘리면 그래프 연결성이 오히려 나빠지기 때문(도로가 중간에 끊긴 것처럼 됨)

### 결과

| | bbox 기준 | 행정경계 기준 |
| --- | --- | --- |
| 서울 추정 링크 수 | 109,633 | **63,548** |

행정경계로 바꾸면서 링크 수가 42% 줄었는데, 이는 실제로 서울이 아니었던 경기/인천 인접 링크가 제거됐기 때문입니다.

### 경계 데이터 라이선스 주의

`data/raw/boundary/seoul_admin_boundary.geojson`은 다른 raw 데이터와 달리 예외적으로 Git에 커밋되어 있습니다(크기 1.6MB, 정적 참조 데이터). 다만 출처 저장소(`southkorea/seoul-maps`)에 명시적 라이선스 파일이 없어(`LICENSE` 없음, GitHub API 기준 `license: None`), 이 저장소가 public으로 전환되기 전에 공공누리(KOGL) 라이선스가 명시된 공식 출처(통계청 SGIS, 국토교통부 VWorld, 국가공간정보포털 등)로 교체하는 것을 권장합니다.

---

## T-data LINK_ID 매칭

### 배경

T-data(`1시간 소통정보 (구간별).csv`)를 `LINK_ID`/`링크ID` exact match로 결합하면 매칭률이 매우 낮습니다. 표준노드링크가 주기적으로 갱신되며 링크 하나가 여러 세부 링크로 재번호되는 경우가 많아(끝 2자리만 바뀌고 앞 8자리 논리적 도로 구간은 동일), T-data가 참조하는 원래 ID가 현재 MOCT_LINK에 아예 존재하지 않는 경우가 많기 때문입니다.

이 버전 drift 문제를 8자리 prefix 추정으로 우회하는 방식(prefix8 휴리스틱)을 초기에 검증해 매칭률을 크게 끌어올렸으나, 이후 서울시가 TOPIS 내부 링크체계(서비스링크)와 표준노드링크 LINK_ID를 공식적으로 연결해주는 매핑 테이블(`서울특별시 교통소통 표준링크 매핑정보_20250306.xlsx`)을 확보하면서, 추정이 아닌 정답 매핑으로 대체했습니다.

### 해결 방식: 공식 매핑 테이블 (`04_merge_tdata_link_speed.py`)

`서비스링크`(=T-data `링크ID`) → `표준링크아이디`(=Seoul `LINK_ID`) 1:N 매핑을 그대로 사용합니다.

- 하나의 서비스링크가 여러 `표준링크아이디`(물리적 세부 구간)에 대응하면, 같은 속도값을 해당 구간 전체에 broadcast합니다 — `표준링크순서` 컬럼이 이 1:N 관계가 실제 도로 구간의 순차 분할임을 보여줍니다.
- `표준링크아이디`는 매핑 테이블 내에서 서로 다른 서비스링크에 중복 등장하지 않는 것으로 검증됐습니다(target 측 모호성 없음) — 그래서 prefix8과 달리 서로 다른 T-data 소스의 값이 같은 타겟 링크에 겹쳐 붙는 경우가 없습니다.
- 같은 (LINK_ID, 기준일, 시간코드)에 그래도 여러 소스 행이 모이면(T-data 자체의 상행/하행 분리 등) 평균으로 합치고, `broadcast_source_link_ids`/`broadcast_source_count`/`broadcast_speed_std` 컬럼에 소스 개수와 표준편차를 남깁니다.
- 한 서비스링크 관측이 여러 표준링크 학습 행으로 복제되더라도 원본을 추적할 수 있도록 `source_section_id`와 `source_observation_id`를 보존합니다.
- 복제 개수가 많은 서비스링크가 학습에서 과도한 영향력을 갖지 않도록 각 행에 `sample_weight = 1 / mapping_copy_count`를 부여합니다. 같은 원본 관측에서 파생된 행들의 가중치 합은 항상 1입니다.

`match_method` 컬럼 값은 `official_mapping` 하나입니다.

### 검토했으나 채택하지 않은 것: prefix8 확장

매핑 테이블에 없는 T-data 링크를 prefix8+도로명+속성(MAX_SPD/LANES/ROAD_RANK)+위상연결로 추가 매칭하면 매칭률을 43%대까지 끌어올릴 수 있고, 5-fold 교차검증에서 정확도 손실 없이 도로등급 불균형을 완화하는 것도 확인했습니다. 다만 이 확장분은 "진짜 정답인지 검증할 방법이 원천적으로 없다"는 한계가 있어(검증 가능한 사례는 이미 항상 공식 매핑에 포함되어 있음), 팀 논의 후 적용 여부를 결정하기로 하고 현재 파이프라인에는 포함하지 않았습니다.

### 남은 한계

- **매칭률 17.33%**: 공식 매핑 테이블 자체가 TOPIS가 관측하는 링크만 포함하므로, 매핑에 없는 도로는 애초에 매칭 대상이 아닙니다.
- **연결성이 매우 낮음**: 매칭 링크만으로 그래프를 구성하면 최대 연결 컴포넌트가 전체의 0.27%에 불과해(`05_analyze_matched_links.py`), 현재 상태로는 다익스트라 등 경로탐색에 쓰기 어렵습니다. 링크별 속도 예측 자체는 가능하지만, 경로 비교(최소시간 vs 최소에너지)를 하려면 위 prefix8 확장 또는 다른 커버리지 보완이 필요합니다.
- **ROAD_RANK 쏠림**: 매칭 링크의 82%가 `ROAD_RANK=104`에 몰려 있어(간선/이면 도로가 섞인 코드), 학습 시 `MAX_SPD`/`LANES`를 함께 쓰는 것을 권장합니다(단독으로 `ROAD_RANK`를 대체하면 오히려 RMSE가 악화되는 것을 확인했으므로 대체가 아니라 보완으로 사용).

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

도로 링크와 DEM의 좌표계가 다르므로 `07_add_dem_features.py`에서 링크를 `EPSG:5179`로 변환한 뒤 샘플링합니다. 링크마다 시작/25%/중간/75%/끝 5개 지점을 샘플링해 평균·최소·최대 고도와 경사도를 계산합니다.

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

KMA 레이더 원본은 한 시각당 약 48MB이며, 현재 T-data 대상 119개 시각 원본은 약 5.7GB입니다. API에 일일 다운로드 용량 제한이 있어 여러 날에 걸쳐 나눠 받아야 할 수 있습니다. `fetch_kma_radar.py`는 이미 받은 파일을 건너뛰는 구조라(`save_text`의 존재 확인), 같은 명령을 다음 날 다시 실행하면 자동으로 이어받습니다. 다만 "일일 한도 초과" 자체를 감지해 그 자리에서 중단하지는 않아서, 한도 초과 이후의 나머지 요청은 각각 실패로 기록됩니다(`radar_failed_tms.txt`). 이 파일은 실패 기록용이라 재실행 후 전부 성공해도 자동으로 삭제되지 않으니, 다운로드가 실제로 완료됐는지는 `radar_failed_tms.txt`가 아니라 `data/raw/weather/radar/` 안의 실제 파일 존재 여부와 크기로 확인해야 합니다.

---

## Generated Outputs

| File | Description |
| --- | --- |
| `data/interim/seoul_link.*` | 서울 행정경계 기준 링크 Shapefile |
| `data/processed/seoul_link_attr.csv` | 서울 링크 속성 테이블 |
| `data/processed/seoul_link_speed_merged.csv` | T-data 속도 + 서울 링크 속성 (공식 매핑 테이블 기반 매칭, `match_method`/`broadcast_*` 컬럼 포함) |
| `data/processed/seoul_link_dem_features.csv` | 링크별 DEM 고도/경사도 피처 |
| `data/processed/seoul_link_speed_dem_merged.csv` | 속도 + 링크 속성 + DEM |
| `data/processed/weather_hsr_seoul_grid.npz` | 서울 bbox 주변 HSR 격자 캐시 |
| `data/processed/link_radar_grid_mapping.csv` | 링크 중심점과 가장 가까운 HSR 격자 매핑(캐시, 아래 Notes 참고) |
| `data/processed/seoul_link_radar_precip.csv` | 링크별 시간대 레이더 강수 피처 |
| `data/processed/seoul_link_speed_dem_weather_merged.csv` | 최종 속도 + 링크 + DEM + 강수 결합 테이블 |
| `data/processed/seoul_link_model_features.csv` | 서울 63,548개 링크의 노드 위상·경사 보정·조합 피처 |
| `data/processed/speed_model_evaluation_enhanced.json` | Model B 시간·공간 일반화 성능, 누수 검증, 피처 중요도 |
| `data/processed/seoul_all_link_weather_YYYYMMDDHHMM.csv` | 특정 시각의 서울 전 링크 정적 속성 + DEM + 강수 스냅샷 |
| `data/processed/seoul_all_link_speed_YYYYMMDDHHMM.csv` | 특정 시각의 서울 전 링크 속도, 출처, 신뢰도, 통행시간 |
| `data/processed/matched_road_rank_coverage.csv` | 도로등급별 T-data 매칭률 |
| `data/processed/matched_graph_components.csv` | 매칭 링크 연결 컴포넌트 |
| `data/processed/matched_link_ids.csv` | T-data와 매칭된 링크 목록 |
| `data/processed/matched_links.geojson` | 매칭 링크 GeoJSON |
| `data/processed/matched_links_map.png` | 매칭 링크 분포 지도 |
| `data/processed/matched_links_map_highlight.png` | 매칭(빨강)/미매칭(파랑) 링크를 함께 표시해 미매칭 링크가 어디에 몰려있는지 보여주는 지도 |
| `docs/figures/eda/*.png` | `10_eda_report.ipynb`가 생성하는 GitHub/보고서용 EDA 그래프 이미지 |
| `docs/figures/model/*.png` | `11_speed_model_baseline.ipynb`가 생성하는 속도 예측 모델 결과 그래프 이미지 |

`data/raw/`, `data/interim/`, `data/processed/`의 실제 데이터 파일은 대용량 원본/중간/가공 데이터라 Git에 올리지 않고 `.gitkeep`만 둡니다. 예외적으로 `data/raw/boundary/seoul_admin_boundary.geojson`은 커밋합니다(위 라이선스 주의 참고).

---

## Current Results

### T-data Matching

```text
서울 링크 수: 63,548
T-data 행 수: 1,217,135
T-data 고유 링크ID 수: 5,117

공식 매핑 매칭 링크 수: 11,010 (17.33%)
여러 T-data 소스가 겹쳐 평균으로 병합된 행 수: 0 (0.00%)

결합된 T-data 행 수: 2,619,332
결합된 고유 Seoul 링크 수: 11,010
```

연결성은 매우 낮습니다.

```text
연결 컴포넌트 수: 7,142
최대 컴포넌트 링크 수: 30
최대 컴포넌트 링크 비율: 0.27%
샘플 경로 탐색: 불가
```

공식 매핑 테이블이 TOPIS가 실제로 관측하는 링크만 담고 있어서, **관측 링크만 사용한 그래프**는 도로망 전역에 흩어진 짧은 조각들로 남습니다. 현재는 Model B로 미관측 링크의 속도를 채워 전 링크 그래프 입력을 생성합니다. 다만 미관측 링크에는 정답이 없으므로 아래 공간 일반화 평가를 대리 검증으로 사용합니다.

도로등급별 매칭률(`matched_road_rank_coverage.csv`):

| ROAD_RANK | 전체 링크 수 | 매칭 링크 수 | 매칭률 |
| --- | --- | --- | --- |
| 101(고속도로) | 352 | 42 | 11.93% |
| 102 | 1,388 | 446 | 32.13% |
| 103 | 3,057 | 1,225 | 40.07% |
| 104 | 56,913 | 9,014 | 15.84% |
| 105 | 121 | 56 | 46.28% |
| 106 | 168 | 63 | 37.50% |
| 107 | 1,549 | 164 | 10.59% |

### DEM

```text
서울 링크 수: 63,548
DEM 샘플 존재 링크 비율: 100.0%
대부분 링크의 dem_sample_count: 5
```

### Radar Precipitation

```text
T-data 대상 레이더 시각 수: 238
다운로드 완료 레이더 시각 수: 238
누락 레이더 시각 수: 0
최종 결합 행 수: 2,619,332
강수값 존재 행 수: 2,619,332
```

강수량 요약:

```text
mean precip_mm: 4.59
median precip_mm: 0.00
max precip_mm: 47.32
precip_mm > 0 행 수: 550,587
precip_mm > 0 시각 수: 94
```

### Speed Feature EDA

최종 결합 테이블(`seoul_link_speed_dem_weather_merged.csv`)을 입력으로 `notebooks/10_eda_report.ipynb`에서 강수량, 경사도, 도로등급, 첨두시간대에 따른 평균속도 차이를 1차 탐색했습니다. 공식 매핑 테이블 기반 매칭(11,010개 링크, 17.33%)으로 표본이 바뀌었습니다 — 이전 prefix8 확장 버전(25,151개)보다 표본이 작지만, 정답이 검증된 링크만 포함합니다.

```text
무강수 평균속도: 26.05 km/h
강수 평균속도: 25.59 km/h
무강수 + 완만 구간 평균속도: 25.88 km/h
강수 + 급경사 구간 평균속도: 26.88 km/h
오전첨두 무강수 평균속도: 25.34 km/h
오전첨두 강수 평균속도: 23.01 km/h
```

공식 매핑만 사용한 이번 표본은 이전(prefix8 확장 포함, 39.6%) 표본보다 평균속도가 전반적으로 높게 나타납니다(예: 무강수 23.38 → 26.05 km/h) — 공식 매핑이 TOPIS가 직접 관측하는 간선 위주 도로에 집중돼 있어(ROAD_RANK 분포 자체가 다름), 이면도로 비중이 낮기 때문으로 보입니다. "강수 + 급경사" 조합은 여전히 감속이 아니라 오히려 소폭 증가로 나타나 뚜렷한 경향이 없고, 오전 첨두시간대 강수 시 감속 효과는 이번에도 확인됩니다(25.34 → 23.01 km/h). 매칭 방식에 따라 표본의 도로 구성 자체가 바뀌면서 EDA 경향도 달라질 수 있다는 점에 유의해야 합니다.

이 결과는 인과관계 검증이 아니라 탐색적 분석입니다. 최종 해석에서는 시간대, 도로등급, 제한속도, 링크별 특성을 함께 통제해야 합니다.

---

## 누수 방지와 Model B 평가

### 왜 원본 관측 단위가 필요한가

서울시 공식 매핑은 하나의 T-data 서비스링크를 여러 표준링크로 확장할 수 있습니다. 이 형제 링크들을 임의의 행 단위로 train/test에 나누면 동일한 속도 라벨이 양쪽에 들어가 성능이 실제보다 좋아집니다.

`10_evaluate_speed_model.py`는 다음 두 기준으로 이를 방지합니다.

| 평가 | 분할 기준 | 의미 |
| --- | --- | --- |
| 시간 일반화 | 과거 날짜 학습, 미래 날짜 평가 | 이미 알려진 도로의 미래 시간대 속도 예측 |
| 공간 일반화 | `source_section_id` GroupKFold | 특정 원본 T-data 서비스구간을 학습에서 통째로 제외하고 새로운 도로구간 일반화 평가 |

두 평가 모두 `source_observation_id`가 train/test에 동시에 존재하는지 검사합니다. 현재 중복은 0건입니다.

### 평가 결과

| 평가 | RMSE | MAE | R² |
| --- | ---: | ---: | ---: |
| 시간 일반화 | 6.43 km/h | 4.72 km/h | 0.740 |
| 공간 일반화 5-fold 평균 | 7.71 km/h | 5.61 km/h | 0.641 |

MAE 5.61 km/h는 새 원본 서비스구간의 예측값이 실제 속도와 평균적으로 약 5.61 km/h 차이 난다는 뜻입니다. R² 0.641은 평균속도 하나로 예측하는 기준과 비교했을 때 속도 변동의 약 64.1%를 모델이 설명한다는 뜻입니다.

초기 전 링크 베이스라인과 비교하면 시간 MAE는 4.88에서 4.72로, 공간 MAE는 5.74에서 5.61로 개선됐습니다.

### Model B 피처 범위

Model B는 미관측 링크에도 적용해야 하므로 전 링크 공통 피처만 사용합니다.

- 도로 속성: 차로수, 제한속도, 길이, `ROAD_RANK`, 도로유형·용도, 연결·통행제한 속성
- 지형: 링크 5개 지점의 고도 통계, 고도차, signed/absolute 경사도
- 경사 보정: `-12~12%` 클리핑, 이상치 여부, 오르막·내리막·급오르막, 경사×길이
- 시간: 시각, 요일, 주말, 첨두시간, 시각·요일 순환형 `sin/cos`
- 강수: 원 강수량, 비 여부, 로그 강수량, 강수 등급, 강수×첨두, 강수×제한속도
- 도로망 위상: 출발/도착 노드의 진입·진출 링크 수, 인접 링크 평균 제한속도·차로수, 노드 복잡도
- 조합: 제한속도×차로수, 링크길이×노드복잡도

과거 속도 lag/rolling, T-data 도로구분·방향코드는 미관측 링크에서 생성할 수 없어 제외했습니다. 월·계절·공휴일은 현재 10일짜리 7월 데이터에서 변화가 거의 없으므로 제외했습니다.

---

## 서울 전 링크 속도 생성

`11_build_all_link_weather_snapshot.py`가 특정 시각의 63,548개 링크에 정적 도로·DEM·레이더 강수를 결합하고, `12_predict_all_link_speed.py`가 다음 우선순위로 최종 속도를 선택합니다.

1. 해당 시각에 공식 관측이 있으면 `official_observed`
2. 전 링크 공통 피처가 정상이고 학습 범주에 포함되면 `static_model`
3. 모델 입력이 불가능하면 도로등급·제한속도·시간대 기반 `hierarchical_fallback`

2026-07-16 08:00 결과:

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
- T-data API 수집 코드는 사용하지 않습니다(사이트에서 내려받은 CSV 사용).
- `data/processed/link_radar_grid_mapping.csv`와 `weather_hsr_seoul_grid.npz`는 캐시 파일입니다(`09_add_radar_precip_features.py`). `link_radar_grid_mapping.csv`는 `seoul_link_speed_dem_merged.csv`의 현재 링크 구성과 캐시된 링크 구성을 자동으로 비교해, 다르면 다시 빌드합니다 — 수동으로 지울 필요는 없습니다.
- `seoul_link_speed_merged.csv`의 `broadcast_speed_std`가 큰 행(예: 10km/h 초과)은 여러 방향/맥락의 T-data 관측이 평균으로 섞였을 가능성이 있으니, 정밀한 분석에는 주의해서 사용해야 합니다.
- 공간 일반화는 관측 서비스구간 일부를 숨겨 미관측 링크 상황을 모사한 결과입니다. 실제 미관측 82.67% 링크에는 정답 속도가 없으므로 그 링크들의 오차를 직접 계산한 것은 아닙니다.
- 현재 원본은 2026-07-07~2026-07-16의 10일 데이터입니다. 계절·월·공휴일 일반화를 주장하려면 더 긴 기간의 T-data와 기상 데이터가 필요합니다.
- `slope_pct`는 짧은 링크와 90m DEM 해상도 때문에 튈 수 있어 Model B에서는 원본값과 함께 클리핑값·이상치 플래그를 사용합니다.
- 전 링크 속도와 통행시간은 준비됐지만, 에너지 비용식과 최소시간/최소에너지 경로탐색은 후속 단계입니다.
