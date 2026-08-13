# 데이터 사전

이 문서는 현재 공식 파이프라인이 읽고 쓰는 데이터의 위치, 분석단위, 주요 컬럼과 주의사항을 설명합니다. 자세한 처리 알고리즘은 [방법론 문서](../docs/METHODS_AND_PIPELINE.md), EDA 표와 그림의 해석은 [EDA 가이드](../docs/EDA_GUIDE.md)를 참고합니다.

## 1. 폴더 원칙

| 폴더 | 의미 | 직접 수정 여부 |
| --- | --- | --- |
| `raw/` | 내려받거나 전달받은 원본 | 수정하지 않음 |
| `interim/` | 다음 파이프라인 단계가 읽는 중간 결과와 캐시 | 코드로 재생성 |
| `processed/` | 모델·에너지·EDA가 직접 읽는 분석 산출물 | 코드로 재생성 |

대용량 원본과 산출물은 Git에 일반적으로 포함하지 않습니다. 파일 존재와 스키마를 이 문서로 관리합니다.

`processed/`에는 차원·팩트 두 파일만 있는 것이 아닙니다. 현재는 모델 조회표, 335개 전 링크 속도, 에너지, 관측자료, 하이브리드, EDA 요약도 모두 정식 산출물로 존재합니다.

## 2. 현재 데이터 규모

| 항목 | 실제 값 |
| --- | ---: |
| 서울 전체 방향성 링크 | 63,548 |
| 5분 원자료에서 관측된 링크 | 44,960(70.75%) |
| 미관측 링크 | 18,588(29.25%) |
| 속도 관측 팩트 | 15,094,335행 |
| 공통 분석기간 | 2026-07-07 01:00~2026-07-20 23:00 |
| 공통 시점 수 | 335 |
| 전 링크 예측/에너지 | 21,288,580 링크-시간 |
| 공통기간 실제 A 관측 | 15,049,459 링크-시간 |

7월 7일 00시는 속도 팩트에는 있을 수 있지만 전 링크 일괄 예측에 필요한 레이더 원본이 없어 속도·에너지·EDA의 공통기간에서 제외했습니다.

## 3. `raw/`: 원자료

### 3.1 도로망 `raw/road/`

- `MOCT_LINK.*`: 표준 링크 geometry와 링크 속성
- `MOCT_NODE.*`: 표준 노드 geometry와 노드 유형
- `MULTILINK.dbf`, `TURNINFO.dbf`: 멀티링크·회전/교차 관련 보조정보

주요 링크 식별자는 문자열 `LINK_ID`, 방향은 `F_NODE→T_NODE`입니다. `LENGTH`는 m입니다.

### 3.2 서울 경계 `raw/boundary/`

- `seoul_admin_boundary.geojson`: 서울 25개 자치구 경계, EPSG:4326

표준 링크가 이 경계와 교차하면 서울 링크로 포함됩니다.

### 3.3 교통 `raw/traffic/`

- `202607_5Min/*_5Min.csv`: 전국 링크 5분 단위 통행속도
- `bus_lane/`, `school_zone/`, `speed_bump/`: 외부 시설 공간자료
- 보행자 사고다발 자료
- `traffic_volume.xlsx` 등 AADT·시간교통량 자료
- View-T 연평균·시간대 속도 및 혼잡 자료
- 격자/행정동 생활인구 관련 자료

원시 5분 자료가 가장 큰 입력이며 `pipeline/02`가 서울 `LINK_ID`만 lazy filter합니다.

### 3.4 DEM `raw/dem/`

- `37608.img`, `37612.img`, `37705.img`, `37709.img`

링크당 5개 위치를 표본화해 평균고도, 방향 고도차, 경사도를 만듭니다.

### 3.5 날씨 `raw/weather/`

- `grid/hsr_lon.txt`, `grid/hsr_lat.txt`: KMA HSR 격자 좌표
- `radar/hsr_pcph_acc60_YYYYMMDDHHMM.txt`: 60분 누적 강수 원본
- API 인증키 파일 또는 환경변수

KMA 원시 코드 `-25000`은 무강수 0mm, `-30000` 이하는 결측/영역 밖으로 처리합니다. 레이더 파일은 한 시점 약 수십 MB 규모이므로 Git에 넣지 않습니다.

## 4. `interim/`: 중간 데이터

| 파일 | 분석단위 | 생성 코드 | 설명 |
| --- | --- | --- | --- |
| `seoul_link.shp` | LINK_ID | pipeline/01 | 서울 경계와 교차하는 링크 geometry |
| `seoul_link_attr.csv` | LINK_ID | pipeline/01 | 서울 링크 기본속성 |
| `seoul_link_speed_5min_hourly.csv` | LINK_ID×날짜×시간 | pipeline/02 | 5분 속도의 시간평균과 표본수 |
| `weather_hsr_seoul_grid.npz` | HSR 격자 | pipeline/03·05 | 서울 주변 레이더 격자 캐시 |
| `link_radar_grid_mapping.csv` | LINK_ID | pipeline/05 | 링크 중심점과 최근접 레이더 셀 매핑 |
| `seoul_link_dem_features.csv` | LINK_ID | pipeline/04 | DEM 전용 중간 피처 |
| `notebook_cache/` | 노트북별 | notebooks/experiments | 대용량 실험 재실행을 줄이는 캐시 |

중간 캐시는 원자료 또는 앞 단계가 바뀌면 다시 만들어야 합니다. 특히 링크 집합·geometry가 바뀌면 레이더 매핑 캐시를 재사용하면 안 됩니다.

## 5. 핵심 processed 테이블

### 5.1 `processed/seoul_link_dimension.csv`

- 행: 63,548
- 키: `LINK_ID` 유일
- 역할: 모든 정적·준정적 링크 피처의 기준 차원

주요 컬럼군:

| 그룹 | 컬럼 예시 | 단위·의미 |
| --- | --- | --- |
| 식별·방향 | `LINK_ID`, `F_NODE`, `T_NODE`, `ROAD_NAME` | 방향은 F→T |
| 도로 기본 | `ROAD_RANK`, `ROAD_TYPE`, `ROAD_USE`, `LANES`, `MAX_SPD`, `LENGTH` | 차로, km/h, m |
| 제한·특수 | `MULTI_LINK`, `CONNECT`, `REST_VEH`, `REST_W`, `REST_H`, `C-ITS` | 범주형 코드 |
| 고도 | 5개 표본, `elev_mean_m`, `elev_delta_m` | m |
| 경사 | `slope_pct`, `abs_slope_pct`, `slope_pct_clipped`, 이상치 파생 | % |
| 위상 | F/T 노드 진입·진출 차수, 인접 차로·제한속도 평균, `node_complexity` | 도로망 구조 |
| 외부시설 | `bus_lane_ratio`, `school_zone_count`, `accident_hotspot_count`, `speed_bump_count` | 비율·개수 |
| 교통 | `traffic_volume_aadt`, View-T 속도·혼잡, `avg_speed_h0`~`h23` | 희소 조사값 |

`slope_pct`는 F→T 방향 부호를 가집니다. 에너지 파일의 `slope_pct_raw`로 보존되며 계산에는 `slope_pct_used`가 쓰입니다.

### 5.2 `processed/seoul_link_speed_fact.csv`

- 행: 15,094,335
- 고유 관측 링크: 44,960
- 키: `LINK_ID, 기준일, 시간코드`
- 역할: 실제 속도 EDA, A lookup, B/C 학습의 기준 팩트

| 컬럼 | 의미 |
| --- | --- |
| `LINK_ID` | 표준 링크 ID |
| `기준일` | `YYYYMMDD` |
| `시간코드` | 1=00시, …, 24=23시 |
| `sample_count_5min` | 시간평균에 들어간 5분 관측 수 |
| `평균속도` | 실제 5분 관측의 시간평균 km/h |
| `precip_mm` | 링크 최근접 HSR 셀 60분 누적 강수 mm |
| `traffic_volume_hourly` | 시간 교통량, 미조사 링크 결측 가능 |
| `traffic_volume_ratio` | 기준 교통량 대비 시간 비율 |
| `grid_pop` | 250m 격자 시간대 생활인구 |
| `dong_pop` | 대표 행정동 시간대 생활인구 |

`평균속도`가 A-Observed의 정답 열입니다. `model_a_lookup`의 `pred_speed`와 혼동하면 안 됩니다.

## 6. 모델 아티팩트와 조회표

### 6.1 `processed/model_a_lookup.parquet`

- 행: 2,158,080 = 44,960링크×24시간×평일/주말 2
- 컬럼: `LINK_ID`, `시간코드`, `is_weekend`, `pred_speed`, `n_obs`, `source`
- `source`: `link_hour_weekend`, `link_hour`, `link`, 필요 시 전역 폴백

실제 파일에서 대부분 `link_hour_weekend`이며 희소 조합만 링크·시간 또는 링크 평균을 씁니다. 이는 이력 예측표이지 시점별 actual이 아닙니다.

### 6.2 `processed/neighbor_speed_lookup.parquet`

- 행: 3,050,304 = 63,548링크×48
- 키: `LINK_ID`, `시간코드`, `is_weekend`
- 값: `neighbor_speed_bucket`

관측 가능한 1홉 이웃의 이력 평균을 우선하고 없으면 2홉 평균을 사용합니다. 값이 있으면 B, 없으면 C 모델로 분기됩니다.

### 6.3 `src/models/artifacts/model_nb.pkl`, `model_stat.pkl`

- `model_nb.pkl`: B용 XGBoost, 61개 피처(이웃속도 포함)
- `model_stat.pkl`: C용 XGBoost, 60개 피처
- 각 pickle: 학습 모델, 피처 순서, 범주형 컬럼 메타데이터

pickle은 신뢰할 수 있는 프로젝트 파일만 로드해야 합니다.

## 7. 전 링크 속도 파일

### `processed/all_link_speed_prediction_YYYYMMDDHHMM.csv`

- 파일 수: 335
- 시점 범위: `202607070100`~`202607202300`
- 파일당 행: 63,548, `LINK_ID` 유일
- 속도 결측: 0

컬럼:

| 컬럼 | 의미 |
| --- | --- |
| `LINK_ID`, `F_NODE`, `T_NODE` | 링크와 방향 |
| `LENGTH`, `ROAD_NAME`, `MAX_SPD`, `ROAD_RANK` | 링크 기본정보 |
| `slope_pct` | 원 방향성 경사 |
| `precip_mm` | 해당 시점 링크 강수 |
| `시간코드`, `is_weekend` | 시간 피처 |
| `neighbor_speed_bucket` | B 분기용 이웃 이력 속도 |
| `speed_kmh` | 최종 A/B/C 속도 |
| `tier` | `A_lookup`, `B_neighbor_model`, `C_static_model` |
| `speed_source` | `model_a_lookup`, `model_nb`, `model_stat` |
| `prediction_confidence` | high/medium/low 계층 라벨 |

현재 계층 수는 모든 시점에서 A 44,960, B 16,752, C 1,836입니다. `prediction_confidence`는 보정된 확률이 아닙니다.

## 8. 에너지 데이터

### 8.1 `processed/link_energy/link_energy_YYYYMMDDHHMM.parquet`

- 파일 수: 335
- 파일당 행: 63,548
- 성격: 전 링크 A lookup+B/C **예측속도 기반** VT-CPEM 에너지

| 컬럼군 | 컬럼 |
| --- | --- |
| 키·경로 | `tm`, `LINK_ID`, `F_NODE`, `T_NODE`, `LENGTH`, `ROAD_NAME` |
| 속도·시간 | `speed_kmh`, `speed_m_s`, `travel_time_sec` |
| 경사 | `slope_pct_raw`, `slope_pct_used`, `slope_outlier_flag` |
| 맥락 | `precip_mm`, `tier`, `speed_source`, `prediction_confidence` |
| 저항력 | `crr`, `rolling_force_n`, `grade_force_n`, `aero_force_n` |
| 동력 | `wheel_power_w`, `traction_battery_power_w`, `battery_power_w` |
| 에너지 | `energy_ev_j`, `energy_ev_wh`, `energy_ev_kwh`, `energy_wh_per_km` |

`energy_ev_j` 또는 `energy_ev_wh`는 링크 총량이라 경로의 간선비용으로 더할 수 있습니다. `energy_wh_per_km`는 길이 정규화 효율이므로 지도·그룹 비교용입니다.

### 8.2 `processed/link_energy/link_energy_batch_summary.csv`

각 시점의 링크 수, 결측/음수 에너지, 속도·에너지 요약과 품질 상태를 기록합니다.

### 8.3 `processed/observed_speed_energy/date=YYYYMMDD/*.parquet`

- 파티션 파일 수: 278
- 총 행: 15,049,459
- 고유 시점: 335
- 성격: 실제 A `평균속도` 기반 VT-CPEM 추정 에너지

이 데이터는 B/C로 빈 링크를 채우지 않습니다. 따라서 실제 속도와 피처의 관계, 실제 속도를 넣었을 때의 에너지 관계를 분석하는 기준입니다. 에너지 자체는 차량 실측이 아닙니다.

### 8.4 `processed/historical_hybrid_link_energy/hybrid_link_energy_YYYYMMDDHHMM.parquet`

- 파일 수: 335
- 총 행: 21,288,580
- 선택규칙: 해당 시점 actual A → 없으면 A lookup → B/C 예측

과거 14일을 재현할 때 사용합니다. actual A가 들어 있으므로 미래만의 정보로 예측한 데이터가 아니며 미래 경로계획 평가에 사용하면 누수가 됩니다.

## 9. EDA 요약 데이터

### `processed/eda_summary/observed_speed/`

관측속도 시간표, 도로등급, 제한속도, 경사×등급, 교통량×첨두, 위상, 매칭 강수효과, 상관, 링크별 요약이 있습니다.

### `processed/eda_summary/observed_energy/`

관측속도 기반 시간 에너지, 속도×경사, 경사 힘 성분, 도로등급, 강수×첨두, 링크별 요약이 있습니다.

### `processed/eda_summary/observed_vs_lookup/`

A actual과 lookup의 시간별 MAE/bias/RMSE, 피처별 오차, 하이브리드 시점 요약이 있습니다.

### `processed/eda_summary/` 최상위

전 링크 예측속도·에너지의 시간, 계층, 품질, 속도×경사, 강수, 링크별 요약이 있습니다.

정확한 파일별 읽는 법은 [EDA_GUIDE.md](../docs/EDA_GUIDE.md)를 참고합니다.

## 10. 데이터 무결성 규칙

1. 링크 ID와 노드 ID는 숫자로 보이더라도 문자열로 읽습니다.
2. 차원 테이블의 `LINK_ID`는 유일해야 합니다.
3. 속도 파일은 시점당 정확히 63,548행이며 `speed_kmh>0`이어야 합니다.
4. 에너지 입력은 `LENGTH>0`, `speed_kmh>0`, 경사 결측 없음이어야 합니다.
5. `travel_time_sec=LENGTH/(speed_kmh/3.6)`가 성립해야 합니다.
6. `energy_ev_j=energy_ev_wh×3600`이 성립해야 합니다.
7. 경로에 더할 값은 링크 총에너지여야 합니다.
8. actual, lookup, B/C, hybrid의 `speed_source`와 `tier`를 보존합니다.
9. 분석기간 비교 시 7월 7일 00시 제외 여부를 동일하게 맞춥니다.
10. EDA 평균을 다시 합칠 때 chunk 평균을 단순 합하지 말고 합계와 개수를 누적한 뒤 나눕니다.

## 11. 과거 파일과 현재 사용 여부

- 삭제된 `route_scenario_summary.csv`와 `src/routing/16_eco_route.py`: 옛 EV 라우팅 산출물·코드. 같은 비교는 현재 `src/routing/engine.py` + `01_route_compare.py`/`02_evaluate_route_scenarios.py`로 재현합니다.
- 삭제된 `src/routing/13·15`: 옛 전 링크 예측·에너지 코드. 현재 속도와 에너지 생성은 `src/models/03~04`, `src/energy/01~03`이 담당합니다.
- 삭제된 `experiments/`: 팀원 프로토타입 코드였으나 공식 코드 어디에서도 참조되지 않고 옛 경로만 가리켜 저장소에서 제거했습니다(`eco_routes.csv`의 옛 ICE 근사 6개 OD 결과 포함 — Nissan Leaf VT-CPEM 최종 결과로 쓰지 않습니다).
- `notebook_cache/`: 연구 실험 캐시. 공식 결과 스키마가 아니며 삭제 후 재생성할 수 있습니다.

라우팅은 `src/routing/engine.py`(Dijkstra) 기반으로 현재 재현 가능합니다. 대표 30개 OD·2026-07-16 08:00 스냅샷 기준 무제약 최소에너지 경로는 평균 12.389% 에너지 절감(시간 +20.256%), 15% 지연 상한 균형경로는 평균 8.294% 절감(시간 +8.152%)입니다.
