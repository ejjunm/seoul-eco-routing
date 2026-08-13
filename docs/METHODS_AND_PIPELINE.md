# 방법론과 전체 코드 파이프라인

## 1. 연구 목적과 분석 단위

목표는 서울 도로망의 각 방향성 링크에 대해 시간별 통행속도와 전기차 에너지 비용을 만들고, 이를 경로탐색 간선 가중치로 사용하는 것입니다. 분석의 기본 키는 다음과 같습니다.

- 정적 링크 차원: `LINK_ID` 한 행
- 속도 관측 팩트: `LINK_ID × 기준일 × 시간코드` 한 행
- 전 링크 예측·에너지: `LINK_ID × tm` 한 행
- 링크 방향: `F_NODE → T_NODE`
- 길이 단위: m, 속도 단위: km/h, 경사도 단위: %, 강수 단위: mm
- 프로젝트 시간코드: 00시=`1`, …, 23시=`24`

현재 공통 분석 기간은 2026-07-07~2026-07-20이며, 레이더 파일이 없는 7월 7일 00시는 제외해 335개 시점을 사용합니다.

## 2. 전체 흐름

```text
원시 도로망·행정경계
  → 01 서울 링크 추출
  → 04 링크 차원 테이블(도로·DEM·위상·외부 맥락)

전국 5분 속도
  → 02 서울 링크 필터·1시간 집계
KMA 레이더
  → 03 시점별 강수 원본 수집
  → 05 속도 관측 팩트(속도+강수+교통량+인구)

관측 팩트
  → Model A 이력 조회표
  → Model B/C XGBoost + 이웃속도 조회표
  → 특정 시점/기간 전체 63,548링크 속도

전체 링크 속도 + 길이 + 경사
  → VT-CPEM 링크별 시간·에너지

A 실제 관측속도
  → 관측속도 EDA
  → 관측속도 기반 에너지 EDA
전체 A/B/C 예측속도
  → 전 링크 예측속도·에너지 EDA
실제 A + 예측 B/C
  → 과거 재현용 하이브리드 에너지
```

## 3. 데이터 구축 코드

### 3.1 `src/pipeline/01_extract_seoul_links.py`

목적은 전국 표준노드링크 도로망에서 서울 행정경계와 교차하는 링크만 추출하는 것입니다.

- 입력: `data/raw/road/MOCT_LINK.shp`, `data/raw/boundary/seoul_admin_boundary.geojson`
- 처리: 좌표계를 맞추고 서울 25개 자치구 경계를 하나로 결합한 뒤 공간 교차로 링크를 선택합니다.
- 출력: `data/interim/seoul_link.shp`와 `data/interim/seoul_link_attr.csv`
- 결과: 방향성 링크 63,548개
- 주의: 경계에 걸친 링크는 일부가 아니라 원래 링크 geometry 전체가 남습니다. 따라서 “서울 경계와 교차하는 도로망”이라는 정의입니다.

### 3.2 `src/pipeline/02_aggregate_5min_speed.py`

전국 규모 5분 속도 CSV를 한 번에 메모리에 올리지 않고 Polars lazy scan으로 처리합니다.

- 입력: `data/raw/traffic/202607_5Min/*_5Min.csv`
- 서울 링크 필터: 01 단계의 `LINK_ID` 집합
- 시간 변환: 원시 `HHMM`을 00시=`1`부터 23시=`24`까지의 `시간코드`로 변환
- 집계키: `LINK_ID, 기준일, 시간코드`
- 집계값: `평균속도`, `sample_count_5min`
- 출력: `data/interim/seoul_link_speed_5min_hourly.csv`
- 재실행 특성: 기존 날짜를 보존하고 새 날짜만 누적하는 멱등형 구조입니다.

`sample_count_5min`은 한 시간의 이론상 12개 5분 관측 중 실제로 몇 개가 평균에 들어갔는지를 나타냅니다. 속도의 신뢰도와 학습 표본 가중치로 사용됩니다.

### 3.3 `src/pipeline/03_fetch_kma_radar.py`

KMA HSR 레이더의 60분 누적 강수 자료를 내려받습니다.

- `--grid`: HSR 위·경도 격자 받기
- `--tm YYYYMMDDHHMM`: 한 시점 받기
- `--start-tm`, `--end-tm`, `--step-minutes`: 범위 받기
- `--from-5min-times`: 속도 팩트에 존재하는 시간 목록 받기
- `--overwrite`: 기존 파일 교체
- 출력: `data/raw/weather/radar/hsr_pcph_acc60_{tm}.txt`

KMA 원시 코드에서 `-25000`은 관측영역 내 무강수로 0mm 처리하고, `-30000` 이하 값은 관측영역 밖/결측으로 처리합니다. API 키는 환경변수 또는 프로젝트의 키 파일에서 읽습니다.

### 3.4 `src/pipeline/04_build_link_dimension.py`

63,548개 링크 각각에 변하지 않거나 느리게 변하는 피처를 붙여 `data/processed/seoul_link_dimension.csv`를 만듭니다.

주요 피처 묶음은 다음과 같습니다.

| 그룹 | 예시 | 의미 |
| --- | --- | --- |
| 기본 도로 | `F_NODE`, `T_NODE`, `LENGTH`, `LANES`, `MAX_SPD`, `ROAD_RANK`, `ROAD_TYPE`, `ROAD_USE` | 링크의 물리·행정 특성 |
| DEM | 5개 지점 고도, `elev_mean_m`, `elev_delta_m`, `slope_pct`, `abs_slope_pct` | 고도와 방향성 경사 |
| 위상 | 진입·진출 차수, 인접 제한속도/차로수, `node_complexity`, `downstream_speed_delta` | 교차로 및 도로망 연결 구조 |
| 경사 보정 | `slope_pct_clipped`, `slope_length_m` 등 | 짧은 링크의 DEM 오차 영향 완화 |
| 시설·안전 | `bus_lane_ratio`, `school_zone_count`, `accident_hotspot_count`, `speed_bump_count` | 도로 주변 운행 제약 |
| 교통·View-T | AADT, 연평균/첨두속도, 시간대 프로필, 혼잡빈도·혼잡시간 | 희소하지만 유용한 외부 교통 맥락 |

DEM은 링크 선형의 0%, 25%, 50%, 75%, 100% 지점에서 표고를 표본화합니다. `slope_pct`는 `F_NODE → T_NODE` 방향의 고도차를 길이로 나눈 방향성 값입니다. 90m급 DEM과 짧은 링크의 조합은 비현실적인 경사를 만들 수 있으므로 원값을 보존하면서 모델·에너지 계산에는 보정값과 이상치 플래그를 함께 사용합니다.

외부 시설이 없다는 의미가 명확한 카운트·비율은 0으로 채웁니다. 반대로 교통량이나 View-T처럼 조사되지 않은 링크가 많은 값은 0으로 가장하지 않고 결측을 유지해 XGBoost가 결측 분기를 학습하게 합니다.

### 3.5 `src/pipeline/05_build_speed_fact.py`

02의 실제 관측속도에 시공간 피처를 결합해 `data/processed/seoul_link_speed_fact.csv`를 만듭니다.

- 레이더: 링크 중심점과 가장 가까운 HSR 격자를 미리 매핑하고 시점별 강수량을 붙입니다.
- 교통량: 시간대 교통량 `traffic_volume_hourly`와 기준 대비 비율 `traffic_volume_ratio`
- 인구: 250m 격자 생활인구 `grid_pop`, 대표 행정동 인구 `dong_pop`
- 핵심 출력열: `LINK_ID`, `기준일`, `시간코드`, `평균속도`, `sample_count_5min`, `precip_mm`, 교통량·인구

실제 결과는 15,094,335 링크-시간 행과 44,960개 고유 관측 링크입니다. 전체 링크의 70.75%에 관측 이력이 있고 나머지 29.25%는 직접 정답이 없어 B/C 모델로 채웁니다.

## 4. 속도 모델

### 4.1 계층 구조의 의미

A/B/C는 경사도 등급이 아니라 **그 링크에 사용할 수 있는 속도 정보의 수준**입니다.

| 계층 | 현재 링크 수 | 조건 | 속도 산출법 |
| --- | ---: | --- | --- |
| A | 44,960 | 해당 링크 자체의 과거 관측 이력이 있음 | 링크·시간·평일/주말 이력 조회 |
| B | 16,752 | 자체 관측은 없지만 관측 이웃의 이력 속도를 만들 수 있음 | 이웃속도 포함 XGBoost |
| C | 1,836 | 자체 관측과 유효 이웃속도가 모두 없음 | 정적 피처 전용 XGBoost |

`prediction_confidence=high/medium/low`는 이 계층을 사람이 읽기 쉽게 표시한 상대적 라벨입니다. 확률로 보정된 신뢰구간이 아닙니다.

### 4.2 Model A: `src/models/01_build_model_a.py`

관측 링크별 과거 반복 패턴을 조회표로 만듭니다.

1. 가장 세밀한 평균: `LINK_ID × 시간코드 × is_weekend`
2. 해당 조합이 없으면: `LINK_ID × 시간코드`
3. 그래도 없으면: `LINK_ID` 전체 평균
4. 최종 결측이면: 전역 평균

모든 관측 링크에 24시간×평일/주말 48개 행을 만들어 `model_a_lookup.parquet`에 저장합니다. 실제 파일은 2,158,080행(`44,960×48`)입니다. 대부분 `link_hour_weekend` 소스이고 희소 조합만 상위 폴백을 사용합니다.

중요한 해석은 다음과 같습니다.

- A는 관측된 링크에서 학습했으므로 B/C보다 정보가 많습니다.
- 그러나 특정 날짜의 A 조회값은 그 날짜의 `평균속도` 정답이 아니라 여러 날짜의 같은 시간대 평균입니다.
- 현재 조회표가 분석 대상 14일 전체로 만들어졌으므로 같은 기간에 대한 A 비교는 독립 외부시험이 아닌 후향적 적합도 진단입니다.

### 4.3 Model B/C: `src/models/02_build_model_bc.py`

#### 이웃속도 정의

`02_derived_features_lightgbm.ipynb`의 높은 점수를 낸 실험은 같은 날짜·같은 시간의 이웃 관측속도를 사용했습니다. 미래 예측 시 라이브 이웃 관측이 없으면 만들 수 없는 피처이므로, 공식 코드에서는 이를 다음처럼 교체했습니다.

```text
관측 이웃의 (시간코드, 평일/주말) 과거 평균
  → 1홉 이웃 평균 우선
  → 1홉이 없으면 2홉 이웃 평균
  → 둘 다 없으면 결측(C 계층)
```

이렇게 해야 학습 때의 이웃속도와 실제 예측 때의 이웃속도가 같은 정의를 가져 train/serve 불일치를 막을 수 있습니다. 결과는 전체 링크×48 버킷인 `neighbor_speed_lookup.parquet` 3,050,304행입니다.

#### 입력 피처

배포 아티팩트 기준 Model B는 61개, Model C는 B에서 `neighbor_speed_bucket`을 제외한 60개 피처를 사용합니다.

| 피처군 | 실제 피처 |
| --- | --- |
| 도로·기하 | 차로수, 제한속도, 길이, 도로등급/유형/용도, 멀티링크, 연결로, 통행제한, C-ITS |
| 고도·경사 | 평균고도, 방향 고도차, 원경사, 절대경사, 보정경사, 경사×길이 |
| 시간 | `시간코드`, 요일, 주말, 시간의 sin/cos 순환 인코딩 |
| 날씨 | `precip_mm` |
| 시설 | 버스전용차로 비율, 어린이보호구역·사고다발·과속방지턱 개수 |
| 교통·인구 | AADT, 시간대 교통량/비율, 격자·행정동 생활인구 |
| 도로망 위상 | 양 끝 노드 진입·진출 차수, 인접 링크 평균 제한속도/차로수, 복잡도, 하류 속도차 |
| View-T | 연평균·저녁첨두·해당 시간 프로필 속도, 혼잡빈도·혼잡시간 |
| 회랑·도심 | 같은 도로명 링크수·총길이·평균차로·평균제한속도, 도심거리 |
| 교차로 | 종점 교차로 여부 `is_cross_t` |
| B 전용 | `neighbor_speed_bucket` |

XGBoost 설정은 `reg:squarederror`, 300 trees, learning rate 0.05, max depth 8, histogram tree, native categorical, random seed 42입니다. `sample_count_5min`을 학습 가중치로 주어 관측이 더 충실한 시간대를 더 신뢰합니다.

#### 알고리즘 선택

`01_speed_model_baseline.ipynb`에서 도로 속성 23개(파생 피처 없음)·무작위 분할 조건으로 전체평균(R²=0.000), 제한속도 선형회귀(0.172), 도로등급별 평균(0.266), LightGBM(0.610), XGBoost(0.632), CatBoost(0.556)를 비교해 트리 모델의 우위와 XGBoost의 근소한 우위를 먼저 확인했습니다. 이후 `02_derived_features_lightgbm.ipynb`에서 파생 피처 포함 60개 피처·링크 단위 GroupKFold로 LightGBM(0.737)과 XGBoost(0.740)를 다시 비교해 같은 결론을 재현했고, 두 알고리즘 모두 하이퍼파라미터는 기본값으로 통일했습니다. 베이스라인 대비 최종 모델의 성능 격차(0.632→0.740)는 알고리즘 선택보다 피처 엔지니어링(도로망 위상·이웃속도·View-T 등)의 기여가 훨씬 컸음을 보여줍니다.

#### 피처 중요도

피처 중요도는 gain(트리 분기 시 손실 개선량) 대신 **SHAP**(Shapley value, TreeSHAP)으로 산출합니다. gain은 상관된 피처 간 기여도가 왜곡될 수 있습니다 — 예를 들어 초기 피처 구성에서 `REST_VEH`(통행제한차종)의 gain은 71%에 달했지만, 도로망 위상·이웃속도 등 구조 피처를 추가한 최종 모델에서는 1.4%로 급락했습니다. 다른 피처가 없을 때 `REST_VEH`가 실제 원인 변수의 정보를 간접적으로 대신 나르고 있었다는 뜻이며, gain만으로는 이런 맥락 의존성을 알 수 없습니다.

B 계층 표본 20,000행 기준 SHAP 상위 피처는 이웃 도로 속도(35.6%), 시간대별 평균 속도/View-T(7.2%), 동일 도로명 구간 길이/코리도(4.6%), 시간대(3.3%), 진입차로수 평균(3.1%), 제한속도×차로수(3.0%) 순입니다. 이웃 도로 속도 하나가 전체 기여도의 1/3 이상이며, 값이 높을수록 예측 속도도 함께 상승하는 방향성까지 SHAP에서 확인됩니다(gain에는 이런 방향 정보가 없습니다). 요약 플롯은 `docs/figures/model/07_shap_summary.png`, 계층별 검증 R² 막대는 `docs/figures/model/09_bc_groupkfold_r2.png`에 있습니다.

#### 검증과 최종 학습

- `--mode validate`: 링크 단위 3-fold GroupKFold. 같은 링크가 train/test 양쪽에 들어가지 않으며, 매 fold의 이웃 조회표도 train 링크만으로 다시 만듭니다.
- `--mode final`: 전체 자료로 B/C 두 모델을 학습하고 `model_nb.pkl`, `model_stat.pkl`을 저장합니다.

공식 버킷 이웃 정의의 검증 R² 약 0.7226이 배포 기대 성능입니다. 노트북 16차의 R² 약 0.7403은 정확한 동시점 이웃 관측을 사용한 실험 상한에 가깝기 때문에 공식 운영 점수처럼 쓰면 안 됩니다.

### 4.4 한 시점 예측: `src/models/03_predict_all_link_speed.py`

입력 아티팩트 네 개를 재학습 없이 읽습니다.

- `model_a_lookup.parquet`
- `neighbor_speed_lookup.parquet`
- `model_nb.pkl`
- `model_stat.pkl`

처리 순서는 다음과 같습니다.

1. `tm`을 날짜, 요일, 시간코드로 변환합니다.
2. 링크별 레이더 강수 스냅샷 또는 `--precip-mm` 시나리오 값을 읽습니다.
3. 라이브 값이 없는 교통량·인구는 같은 시간코드·평일/주말의 과거 평균 프로필을 만듭니다.
4. A lookup이 있으면 A, 없고 이웃 버킷이 있으면 B, 둘 다 없으면 C를 적용합니다.
5. 예측속도를 최소 3km/h, 최대 해당 링크 `MAX_SPD`로 제한합니다.
6. 링크 63,548개가 모두 있는 `all_link_speed_prediction_{tm}.csv`를 저장합니다.

출력에는 `speed_kmh`, `tier`, `speed_source`, `prediction_confidence`와 에너지 계산에 필요한 길이·경사·강수가 포함됩니다.

### 4.5 기간 일괄 예측: `src/models/04_batch_predict_all_link_speed.py`

한 시점 코드를 335번 단순 실행하지 않고, 공통 정적 피처와 동적 프로필을 재사용합니다. 레이더 원본이 실제로 존재하고 날짜 범위에 들어가는 시점만 처리하며 기존 출력은 기본적으로 건너뜁니다. 현재 335개 CSV가 모두 생성되어 있고 각 파일은 63,548행, 속도 결측 0건입니다.

### 4.6 강수 스냅샷 보조: `src/routing/12_build_all_link_weather_snapshot.py`

한 시점 HSR 레이더를 모든 링크 중심점에 붙여 `seoul_all_link_weather_{tm}.csv`를 만듭니다. `models/03`의 기본 날씨 입력이며, `models/04`는 같은 로직을 기간 전체에 효율적으로 내장해 사용합니다.

## 5. 에너지 모델

### 5.1 구현 파일

- `src/energy/link_energy.py`: 순수 계산 함수와 차량 상수
- `src/energy/01_compute_link_energy.py`: 한 시점 속도 CSV를 에너지 Parquet으로 변환
- `src/energy/02_batch_compute_link_energy.py`: 기간 전체 변환과 배치 요약
- `src/energy/03_compute_observed_speed_energy.py`: A 실제 관측속도만 별도 에너지 계산

### 5.2 VT-CPEM 링크 근사식

프로젝트 원문 [`에코라우팅.pdf`](../에코라우팅.pdf)의 링크 단위 수식을 구현했습니다. 예측 또는 관측 평균속도가 한 링크를 지나는 동안 일정하고 가속도는 0이라고 둡니다.

```text
u = speed_kmh / 3.6
Δt = LENGTH / u
θ = arctan(slope_pct_used / 100)
Crr(u) = 1.75×10⁻³ × (0.0328u + 4.575)

Froll  = m g Crr(u) cos(θ)
Fgrade = m g sin(θ)
Faero  = 0.5 ρ Cd Af u²
Pwheel = (Froll + Fgrade + Faero) u

Pbattery = max(Pwheel, 0)/(ηD ηEM ηB) + PA
E = Pbattery × Δt
```

기준 차량은 Nissan Leaf이며 상수는 다음과 같습니다.

| 상수 | 값 |
| --- | ---: |
| 질량 `m` | 1,521 kg |
| 공기저항계수 `Cd` | 0.28 |
| 전면적 `Af` | 2.3316 m² |
| 공기밀도 `ρ` | 1.2256 kg/m³ |
| 중력가속도 `g` | 9.8066 m/s² |
| 구동계 효율 `ηD` | 0.92 |
| 모터 효율 `ηEM` | 0.91 |
| 배터리 효율 `ηB` | 0.90 |
| 보조장치 전력 `PA` | 700 W |

원경사는 감사용으로 보존하고 실제 계산에는 `[-12%, +12%]`로 자릅니다. 내리막에서 바퀴 동력이 음수가 되더라도 현재 모델은 회생제동을 계산하지 않으며 추진 배터리 전력을 0으로 제한하고 보조장치 700W는 계속 소비합니다.

### 5.3 에너지 출력과 라우팅 비용

각 Parquet은 속도·통행시간·보정경사, 저항력과 동력의 중간항, `energy_ev_j/wh/kwh`, `energy_wh_per_km`를 보존합니다.

- 경로탐색 비용: 링크 총량인 `energy_ev_j` 또는 동치인 `energy_ev_wh`
- 도로 효율 비교: 길이를 정규화한 `energy_wh_per_km`
- 잘못된 사용: `Wh/km`를 링크마다 그대로 더하면 링크 길이가 빠지므로 에너지 최소경로가 아닙니다.

현재 335개 전 링크 에너지 파일은 각각 63,548행이고 에너지 결측·음수는 0건입니다. 매 시점 3,430개 링크가 원경사 ±12% 밖이라 보정 플래그를 갖습니다.

### 5.4 관측속도 기반 에너지

`03_compute_observed_speed_energy.py`는 `평균속도`가 실제로 존재하는 A 링크-시간만 처리합니다. 예측값으로 결측을 채우지 않으므로 실제 관측속도와 속도-에너지 관계를 먼저 분석할 수 있습니다. 다만 전력량 자체는 계측하지 않았으므로 명칭은 반드시 **관측속도 기반 추정 에너지**로 씁니다.

## 6. EDA와 하이브리드 구축 코드

| 코드 | 입력 | 핵심 출력 |
| --- | --- | --- |
| `src/eda/observed_speed_eda.py` | speed fact + dimension | 관측속도 시간·도로·경사·강수·품질 EDA 13종 |
| `src/eda/observed_energy_eda.py` | observed speed energy | 관측속도 기반 에너지 EDA 9종 |
| `src/eda/compare_observed_lookup_and_build_hybrid.py` | A actual + A lookup + 전 링크 energy | A 오차 EDA 5종과 과거 하이브리드 335개 |
| `src/eda/14_speed_energy_eda.py` | 전 링크 predicted energy 335개 | A/B/C 예측속도·에너지·품질·공간 EDA 11종 |
| `src/eda/plot_network_silhouette.py` | seoul_link 도로망 geometry | 속도·에너지 색 없는 63,548개 링크 실루엣 지도(보고서용 기본 지도) |

하이브리드 파일의 선택 우선순위는 다음과 같습니다.

```text
과거 해당 시점 A 실제 관측이 있으면 actual A
→ 없으면 기존 A lookup
→ 미관측 링크 B/C는 기존 예측 유지
```

따라서 `historical_hybrid_link_energy`는 과거 상황을 최대한 실제 A로 재구성하는 분석용 데이터입니다. 미래 예측에는 사용할 수 없습니다.

## 7. 라우팅(Stage 3): `src/routing/engine.py`

라우팅은 도로망을 `F_NODE→T_NODE` 방향 그래프로 만들고, 같은 출발지·목적지에 대해 간선 비용을 바꿔 Dijkstra로 최적 경로를 찾는 단계입니다. `EcoRoutingEngine`(`src/routing/engine.py`)이 그래프 구축·좌표 스냅·최단경로 탐색을 담당합니다.

| 경로 | 간선 비용 | 의미 |
| --- | --- | --- |
| 최단거리(`shortest`) | `LENGTH` | 물리적 이동거리 최소 |
| 최단시간(`fastest`) | `travel_time_sec` | 해당 시점 예상 통행시간 최소 |
| 에너지최소(`eco`) | `energy_ev_j` | Nissan Leaf 추정 배터리 에너지 최소 |
| 균형(`balanced`) | 시간 제약 내 에너지최소 | 최단시간 대비 지연 상한 안에서 에너지 최소화 |

무제약 에코 경로는 시간 증가를 고려하지 않으므로, `energy_route_with_time_limit`(Pareto label-setting)이 최단시간 대비 허용 지연율(기본 15%) 안에서 에너지를 최소화하는 균형 경로를 추가로 탐색합니다(`compare_with_balanced`).

- 단일 OD 비교: `src/routing/01_route_compare.py`
- 대표 지점 다중 OD 평가: `src/routing/02_evaluate_route_scenarios.py --timestamps <tm 목록> --max-pairs 30 --max-time-increase-pct 15`
  - 강남역·서울시청·여의도·잠실역·홍대입구·청량리·구로디지털단지·서울대입구·사당 9개 POI 조합 중 최대 30개 OD
  - 기본 입력은 `historical_hybrid_link_energy_{tm}.parquet`(`--dataset hybrid`), 예측만 쓰려면 `--dataset prediction`
  - 출력은 `data/processed/route_results/`에 저장

2026-07-16 08:00 스냅샷·대표 30개 OD 기준 결과는 다음과 같습니다.

| 경로 | 평균 에너지 절감 | 평균 시간 증가 |
| --- | ---: | ---: |
| 무제약 최소에너지 | 12.389% | 20.256% |
| 15% 지연 상한 균형경로 | 8.294% | 8.152% |

과거 `src/routing/16_eco_route.py`와 그 산출물 `route_scenario_summary.csv`는 정리되어 현재 트리에 없지만, 같은 비교는 현재 `engine.py` + `01_route_compare.py`/`02_evaluate_route_scenarios.py`로 재현 가능합니다.

## 8. 실행 순서

원자료부터 전부 다시 만든다는 전제의 순서입니다. 대용량 단계는 이미 산출물이 있으면 불필요하게 재실행하지 않는 것이 좋습니다.

```powershell
python src/pipeline/01_extract_seoul_links.py
python src/pipeline/02_aggregate_5min_speed.py
python src/pipeline/03_fetch_kma_radar.py --from-5min-times
python src/pipeline/04_build_link_dimension.py
python src/pipeline/05_build_speed_fact.py

python src/models/01_build_model_a.py
python src/models/02_build_model_bc.py --mode validate
python src/models/02_build_model_bc.py --mode final
python src/models/04_batch_predict_all_link_speed.py --start-date 20260707 --end-date 20260720

python src/energy/02_batch_compute_link_energy.py --start-date 20260707 --end-date 20260720
python src/energy/03_compute_observed_speed_energy.py --start-date 20260707 --end-date 20260720 --exclude-tm 202607070000

python src/routing/02_evaluate_route_scenarios.py --timestamps 202607160800 --max-pairs 30

python src/eda/observed_speed_eda.py
python src/eda/observed_energy_eda.py
python src/eda/compare_observed_lookup_and_build_hybrid.py
python src/eda/14_speed_energy_eda.py --start-date 20260707 --end-date 20260720
```

지도 의존성이 없거나 빠른 재생성이 필요하면 EDA 스크립트에 `--skip-maps`를 사용할 수 있습니다. 기존 산출물을 덮어쓸 때만 각 스크립트의 `--overwrite`를 명시합니다.

## 9. 공식 코드와 실험 코드의 경계

### 현재 공식 분석 코드

`src/pipeline`, `src/models`, `src/energy`, `src/eda`와 `tests/test_link_energy.py`가 현재 데이터·모델·에너지·EDA를 재현하는 코드입니다.

### 노트북

결정 과정과 비교 실험을 보여 주는 연구 기록입니다. 출력 성능을 그대로 배포 성능으로 간주하지 않고 [NOTEBOOK_AUDIT.md](NOTEBOOK_AUDIT.md)의 조건을 함께 봐야 합니다.

### `experiments/`

팀원 각자의 프로토타입·1회성 실험 코드가 있었으나, 어떤 공식 코드에서도 import/실행되지 않고 옛 파이프라인 경로(구 T-data 매핑, 옛 ICE 에너지 근사 등)만 참조하는 것을 확인해 저장소에서 삭제했습니다. `build_structural_features.py`의 구조 피처 아이디어는 `pipeline/04`로, `fill_all_speeds.py`의 전 링크 속도 보완은 `models/03~04`로 이미 흡수됐습니다.

## 10. 재현성·해석상 한계

1. 분석기간이 14일뿐이라 계절성과 장기 요일효과를 일반화하기 어렵습니다.
2. A lookup은 현재 14일 전체 이력으로 만들어 같은 기간 비교 시 시간 누수가 없는 외부시험이 아닙니다.
3. 미관측 B/C 링크에는 직접 속도 정답이 없으므로 GroupKFold 성능은 관측 링크를 가상 미관측으로 만든 대리평가입니다.
4. 교통량·View-T 피처는 약 60.7%가 결측인 희소 자료이며 모든 링크의 실시간 상태를 뜻하지 않습니다.
5. 경사는 DEM 해상도와 짧은 링크 때문에 오차가 커 ±12%로 보정했습니다.
6. 에너지 모델은 평균속도 일정, 가속도 0, 회생제동 없음, 단일 차량·효율·보조전력 고정이라는 단순화가 있습니다.
7. 에너지는 차량 계측값으로 검증되지 않았습니다.
8. 강수 EDA는 관찰적 연관성이며 사고·공사·시간대·도로등급 같은 혼란변수를 완전히 통제한 인과효과가 아닙니다.
9. 라우팅은 선택한 시각의 정적 스냅샷 기준이며, 신호대기·교차로 회전비용·공사·통제·실시간 교통 변화를 반영하지 않는 연구용 경로 비교 프로토타입입니다.
