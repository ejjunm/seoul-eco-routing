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
8. [Notes / 한계](#notes--한계)

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

### 문제 발견

T-data(`1시간 소통정보 (구간별).csv`)를 `LINK_ID`/`링크ID` exact match로 결합했을 때, 매칭률이 지나치게 낮았습니다. 특히 VDS가 가장 촘촘히 깔려있어야 할 고속도로(`ROAD_RANK=101`)조차 매칭률이 2.56%에 불과해, 데이터 자체의 한계가 아니라 매칭 로직 문제일 가능성이 제기됐습니다.

### 진단 과정

1. **유명 간선도로 직접 확인**: 강남대로·올림픽대로로 T-data와 MOCT_LINK를 각각 찍어봄
   - 강남대로: T-data가 참조하는 링크ID 30개 중 현재 MOCT_LINK에 존재하는 건 7개뿐. 그런데 이 7개는 **100% 매칭 성공** → 조인 메커니즘 자체는 정상
   - 즉 "존재하는 ID인데 못 찾는" 버그가 아니라,애초에 T-data가 참조하는 ID가 현재 MOCT_LINK에 없는 게 문제
2. **ID 불일치 패턴 확인**: 강남대로에서 T-data가 참조하는 `1210007600`이 현재 MOCT_LINK엔 없고, 대신 `1210007602`(150.3m), `1210007603`(264.3m), `1210007604`(12.0m) 3개로 쪼개져 있음(합계 426.6m). 즉 표준노드링크가 갱신되며 하나의 링크가 여러 세부 링크로 재번호된 것 — 끝 2자리만 다르고 앞 8자리(논리적 도로 구간)는 동일
3. **정량 검증**: LINK_ID 앞 8자리로 매칭하면 T-data 기준 매칭률이 29.6% → **90.4%**로 상승

### 해결 방식: 2단계 매칭 (`04_merge_tdata_link_speed.py`)

1. **exact match**: `LINK_ID` 10자리가 정확히 일치하는 행을 1:1로 결합
2. **prefix8 fallback**: exact match에 실패한 T-data 행을 `LINK_ID` 앞 8자리로 재매칭. 안전장치:
   - 이미 exact로 매칭된 Seoul 링크는 broadcast 대상(target)에서 제외 — 중복 방지. T-data 행(소스) 자체는 exact 매칭 여부와 무관하게 항상 broadcast 소스로 사용한다 — 그래야 한 prefix 그룹의 유일한 T-data 소스가 마침 다른 형제 링크와 exact 매칭됐더라도, 나머지 형제 링크들이 broadcast를 받을 수 있다
   - `ROAD_NAME`이 T-data `도로명`과 정확히 일치하는 조합만 채택 — 서로 다른 도로가 우연히 같은 8자리를 공유하는 오매칭 제거
   - 하나의 T-data 행이 여러 Seoul 링크에 매칭되면(1:N, 평균 3.57개) 같은 속도값을 broadcast
   - 반대로 하나의 Seoul 링크가 같은 prefix를 공유하는 여러 T-data 행과 매칭되는 경우(예: 원래 상행/하행 두 T-data 구간으로 쪼개져 있던 링크)도 있어, 같은 (LINK_ID, 기준일, 시간코드)에 속도값이 여러 개 모이면 평균으로 합친다

결과 테이블(`seoul_link_speed_merged.csv`)의 `match_method` 컬럼(`exact`/`prefix8`)으로 어떤 방식으로 매칭됐는지 구분할 수 있고, `broadcast_source_link_ids`/`broadcast_source_count`/`broadcast_speed_std` 컬럼으로 prefix8 매칭이 몇 개의 T-data 소스에서 왔는지, 소스 간 속도 편차가 얼마나 큰지 확인할 수 있습니다. 편차가 크면(예: 10km/h 이상) 서로 다른 방향/맥락의 관측이 섞였을 수 있다는 뜻이니 정밀 분석 시 참고합니다(전체 prefix8 매칭 행의 1.32%가 이런 다중 소스 병합 케이스이며, 병합 행의 speed_std 중앙값은 2.28km/h, 10km/h 초과 비율은 0.93%입니다).

### 검증 결과

| 검증 항목 | 결과 |
| --- | --- |
| fan-out 그룹이 F_NODE→T_NODE로 이어지는 연속 체인인지 | 96.1% (분기 허용 시 97.8%) |
| Seoul 측 그룹 내 ROAD_NAME 일치 | 97.47% |
| T-data 도로명 ↔ Seoul ROAD_NAME 교차 일치 | 96.96% |
| fan-out 그룹 내 ROAD_RANK 일치 | 99.11% |
| fan-out 그룹 내 MAX_SPD 일치 | 86.52% |
| fan-out 그룹 내 LANES 일치 | 85.02% |
| fan-out 그룹 합산 LENGTH 분포 | min 17.5m / 중앙값 468.7m / max 9,105m |

MAX_SPD/LANES 불일치(약 13~15%)는 이름·연결성이 모두 정상인 그룹에서도 나타나, 오매칭이 아니라 교차로 진입부 차로 감소 같은 실제 도로 특성으로 판단했습니다(의심군과의 교차 비교 결과 91% 이상이 이름·연결성 모두 정상인 "순수" 불일치).

노드명(`시작노드명`/`종료노드명` vs `MOCT_NODE.NODE_NAME`) 교차검증은 시도했지만 **기각**했습니다 — 이미 확실한 exact match 1,517개로 검증했을 때 노드명 완전 일치율이 1.32%에 불과했습니다. `MOCT_NODE`가 이름 있는 교차로엔 "~교차로/~사거리" 접미사를 붙이거나, 이름 없는 지점은 지번 주소("수유동 535-353")나 "최소노드배치점" 같은 placeholder로 채워서, T-data의 랜드마크 이름과 신뢰성 있게 대조할 방법이 없었습니다.

### 남은 한계

- **8자리로도 매칭되지 않는 잔여 9.6%**: 안양천로·올림픽대로·노들로·천호대로 등 표준노드링크가 앞자리부터 전면 재번호된 도로. 도로명은 Seoul 쪽에 여전히 존재하지만(예: 안양천로 138개 링크) ID 체계 자체가 달라 8자리 prefix로도 복구 불가. 이 정도는 도로명+노드 순서 기반 좌표 재구성이 필요한데, 신뢰성 있는 검증 수단(노드명 대조)이 없어 지금 단계에서는 시도하지 않기로 결정했습니다.
- **1:N broadcast는 근사치**: 순서(`구간순서`) 필드를 활용해 fan-out된 하위 링크마다 정확히 다른 T-data 구간을 1:1로 배정하는 정밀한 방법도 검토했으나, 방향에 따라 순서가 뒤집힐 위험과 분기 그룹(전체의 2.2%)에서는 애초에 일렬로 줄 세울 수 없다는 문제가 있어 보류했습니다. 지금은 같은 그룹 내 모든 하위 링크에 동일한(또는 여러 소스가 있으면 평균낸) 속도를 broadcast합니다.

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
| `data/processed/seoul_link_speed_merged.csv` | T-data 속도 + 서울 링크 속성 (exact/prefix8 2단계 매칭, `match_method`/`broadcast_*` 컬럼 포함) |
| `data/processed/seoul_link_dem_features.csv` | 링크별 DEM 고도/경사도 피처 |
| `data/processed/seoul_link_speed_dem_merged.csv` | 속도 + 링크 속성 + DEM |
| `data/processed/weather_hsr_seoul_grid.npz` | 서울 bbox 주변 HSR 격자 캐시 |
| `data/processed/link_radar_grid_mapping.csv` | 링크 중심점과 가장 가까운 HSR 격자 매핑(캐시, 아래 Notes 참고) |
| `data/processed/seoul_link_radar_precip.csv` | 링크별 시간대 레이더 강수 피처 |
| `data/processed/seoul_link_speed_dem_weather_merged.csv` | 최종 속도 + 링크 + DEM + 강수 결합 테이블 |
| `data/processed/matched_road_rank_coverage.csv` | 도로등급별 T-data 매칭률 |
| `data/processed/matched_graph_components.csv` | 매칭 링크 연결 컴포넌트 |
| `data/processed/matched_link_ids.csv` | T-data와 매칭된 링크 목록 |
| `data/processed/matched_links.geojson` | 매칭 링크 GeoJSON |
| `data/processed/matched_links_map.png` | 매칭 링크 분포 지도 |
| `docs/figures/eda/*.png` | `10_eda_report.ipynb`가 생성하는 GitHub/보고서용 EDA 그래프 이미지 |

`data/raw/`, `data/interim/`, `data/processed/`의 실제 데이터 파일은 대용량 원본/중간/가공 데이터라 Git에 올리지 않고 `.gitkeep`만 둡니다. 예외적으로 `data/raw/boundary/seoul_admin_boundary.geojson`은 커밋합니다(위 라이선스 주의 참고).

---

## Current Results

### T-data Matching

```text
서울 링크 수: 63,548
T-data 행 수: 608,538
T-data 고유 링크ID 수: 5,117

exact 매칭 행 수: 180,488  | 고유 Seoul 링크 수: 1,517
prefix8 매칭 행 수(중복 병합 후): 2,810,987 | 고유 Seoul 링크 수: 23,634

결합된 T-data 행 수: 2,991,475
결합된 고유 Seoul 링크 수: 25,151 (전체 63,548개 중 39.6%)
```

연결성도 함께 크게 개선됐습니다.

```text
연결 컴포넌트 수: 206
최대 컴포넌트 링크 수: 11,465
최대 컴포넌트 링크 비율: 45.58%
```

기존(exact match만 사용, 1.12%) 대비 최대 연결 컴포넌트 비율이 약 41배 늘어, 매칭 링크만으로도 서울 상당 부분의 경로탐색을 시도해볼 수 있는 수준이 됐습니다. 다만 8자리로도 매칭되지 않는 잔여 도로가 있어 완전한 서울 전역 커버리지는 아닙니다("T-data LINK_ID 매칭 > 남은 한계" 참고).

도로등급별 매칭률(`matched_road_rank_coverage.csv`):

| ROAD_RANK | 전체 링크 수 | 매칭 링크 수 | 매칭률 |
| --- | --- | --- | --- |
| 101(고속도로) | 352 | 68 | 19.32% |
| 102 | 1,388 | 345 | 24.86% |
| 103 | 3,057 | 2,259 | 73.90% |
| 104 | 56,913 | 22,313 | 39.21% |
| 105 | 121 | 48 | 39.67% |
| 106 | 168 | 79 | 47.02% |
| 107 | 1,549 | 39 | 2.52% |

### DEM

```text
서울 링크 수: 63,548
DEM 샘플 존재 링크 비율: 100.0%
대부분 링크의 dem_sample_count: 5
```

### Radar Precipitation

```text
T-data 대상 레이더 시각 수: 119
다운로드 완료 레이더 시각 수: 119
누락 레이더 시각 수: 0
최종 결합 행 수: 2,991,475
강수값 존재 행 수: 2,991,475
```

강수량 요약:

```text
mean precip_mm: 5.88
median precip_mm: 0.00
max precip_mm: 47.57
precip_mm > 0 행 수: 829,707
precip_mm > 0 시각 수: 58
```

### Speed Feature EDA

최종 결합 테이블(`seoul_link_speed_dem_weather_merged.csv`)을 입력으로 `notebooks/10_eda_report.ipynb`에서 강수량, 경사도, 도로등급, 첨두시간대에 따른 평균속도 차이를 1차 탐색했습니다. 매칭 링크가 1,517개 → 25,151개로 크게 늘면서 이전보다 훨씬 넓은 표본을 반영합니다.

```text
무강수 평균속도: 23.38 km/h
강수 평균속도: 22.95 km/h
무강수 + 완만 구간 평균속도: 23.32 km/h
강수 + 급경사 구간 평균속도: 23.47 km/h
오전첨두 무강수 평균속도: 23.35 km/h
오전첨두 강수 평균속도: 21.09 km/h
```

표본이 넓어지면서 "강수 + 급경사" 조합의 감속 효과는 이전(1,517개 링크 기준, 25.58 vs 23.65 km/h)보다 뚜렷하지 않게 나타났습니다(23.32 vs 23.47 km/h, 유의미한 차이 없음). 반면 오전 첨두시간대 강수 시 감속 효과는 여전히 뚜렷합니다(23.35 → 21.09 km/h). 매칭 링크 수가 적을 때 나온 경향이 표본이 늘며 바뀐 사례라, 표본 확장이 계속 EDA 결론에 영향을 줄 수 있다는 점을 유의해야 합니다.

이 결과는 인과관계 검증이 아니라 탐색적 분석입니다. 최종 해석에서는 시간대, 도로등급, 제한속도, 링크별 특성을 함께 통제해야 합니다.

---

## Notes / 한계

- `data/raw/` 아래 원본 데이터는 직접 받은 파일이므로 코드에서 수정하지 않는 것을 원칙으로 합니다.
- T-data API 수집 코드는 사용하지 않습니다(사이트에서 내려받은 CSV 사용).
- `data/processed/link_radar_grid_mapping.csv`와 `weather_hsr_seoul_grid.npz`는 캐시 파일입니다(`09_add_radar_precip_features.py`). `link_radar_grid_mapping.csv`는 `seoul_link_speed_dem_merged.csv`의 현재 링크 구성과 캐시된 링크 구성을 자동으로 비교해, 다르면 다시 빌드합니다 — 수동으로 지울 필요는 없습니다.
- `seoul_link_speed_merged.csv`의 `broadcast_speed_std`가 큰 행(예: 10km/h 초과)은 여러 방향/맥락의 T-data 관측이 평균으로 섞였을 가능성이 있으니, 정밀한 분석에는 주의해서 사용해야 합니다.
