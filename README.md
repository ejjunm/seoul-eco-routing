# Seoul Eco Routing

서울 표준노드링크, 5분 교통속도, DEM 경사, KMA 레이더 강수, 교통량·생활인구를 결합해 서울 전 도로 링크의 시간별 속도와 Nissan Leaf 기준 에너지 비용을 구축하는 프로젝트입니다.

## 현재 완료 상태

| 단계 | 상태 | 실제 산출물 |
| --- | --- | --- |
| 서울 링크 추출·정적 피처 | 완료 | 63,548링크 차원 테이블 |
| 5분 속도→1시간 관측 팩트 | 완료 | 44,960 관측 링크, 15,094,335행 |
| A/B/C 속도모델 학습 | 완료 | A lookup, 이웃 lookup, B/C XGBoost |
| 14일 전 링크 속도 | 완료 | 7/7 00시 제외 335 CSV, 파일당 63,548행 |
| 전 링크 EV 에너지 | 완료 | 335 Parquet, 총 21,288,580 링크-시간 |
| 관측속도·에너지 EDA | 완료 | 네 종류 폴더, 총 39개 그림 |
| 과거재현 하이브리드 | 완료 | 실제 A + 예측 B/C, 335 Parquet |
| 거리·시간·에너지 라우팅 | 과거 실행 완료 | 당시 실행 코드와 최종 시나리오 CSV는 정리되어 현재 즉시 재현 불가 |

분석기간은 2026-07-07~2026-07-20입니다. 공통 레이더 입력이 없는 2026-07-07 00:00만 제외해 `14×24-1=335`개 시점을 사용합니다.

## 문서

- [데이터 분석 보고서 초안](docs/DATA_ANALYSIS_REPORT.md): 보고서 본문에 사용할 연구 배경·데이터·방법·결과·한계
- [방법론과 코드 파이프라인](docs/METHODS_AND_PIPELINE.md): 모든 공식 스크립트의 입력·처리·출력·실행 순서
- [노트북 전수 검토](docs/NOTEBOOK_AUDIT.md): `11_*`, `12_*`, `13_*` 실험 결과와 현재 코드의 차이
- [EDA 그림·표 해석](docs/EDA_GUIDE.md): 39개 그림 각각의 축, 의미, 주장 가능한 내용과 주의점
- [서울 전 도로망 실루엣](docs/figures/network/01_seoul_all_links_silhouette.png): 속도·에너지 색을 제거한 63,548개 전체 링크 기본 지도
- [분석 문서 안내](docs/README.md): 문서 읽는 순서와 핵심 용어
- [데이터 사전](data/README.md): 폴더·파일·컬럼·행 수·용도

## 가장 중요한 용어 구분

- **A-Observed:** 해당 날짜·시간의 5분 관측을 1시간 평균한 실제 속도 `평균속도`
- **A lookup:** 관측 링크의 `LINK_ID×시간×평일/주말` 과거 평균 `pred_speed`; 실제값이 아니라 예측값
- **B prediction:** 자체 관측은 없지만 관측 이웃의 역사적 시간대 속도가 있는 링크의 XGBoost 예측
- **C prediction:** 이웃속도도 없는 링크의 정적 XGBoost 예측
- **관측속도 기반 에너지:** actual A 속도를 물리식에 넣은 추정치; 차량 실측 전력은 아님
- **전 링크 예측 에너지:** A lookup+B/C 속도를 물리식에 넣은 추정치
- **과거 하이브리드:** 해당 시점 actual A를 우선하고 없는 곳만 lookup/B/C로 채운 후향적 분석 자료

A/B/C는 경사도 등급이 아니라 속도정보 가용성 계층입니다.

## 프로젝트 구조

```text
src/
  pipeline/   원자료 수집·서울 링크 추출·시간 집계·차원/팩트 구축
  models/     A lookup, B/C 학습, 한 시점/기간 전 링크 속도 예측
  energy/     VT-CPEM 링크 에너지 계산
  eda/        관측속도·관측에너지·A lookup·전 링크 결과 EDA
experiments/  과거 탐색 실험; 현재 공식 파이프라인 아님
notebooks/    모델 선택과 피처 실험 기록
data/         raw/interim/processed 데이터와 데이터 사전
docs/         보고서용 문서와 EDA 그림
tests/        에너지식 단위 테스트
```

과거 `src/routing/13_predict_all_link_speed.py`, `15_add_energy_cost.py`, `16_eco_route.py`는 현재 구조에서 사용하지 않습니다. 각각의 역할은 `src/models/03~04`, `src/energy/01~03`으로 대체됐습니다. 단, `16`이 수행했던 최단거리·최단시간·에너지최소 경로 비교 자체는 과거에 실행된 분석입니다.

## 공식 파이프라인

### 1. 원자료 가공

```powershell
python src/pipeline/01_extract_seoul_links.py
python src/pipeline/02_aggregate_5min_speed.py
python src/pipeline/03_fetch_kma_radar.py --from-5min-times
python src/pipeline/04_build_link_dimension.py
python src/pipeline/05_build_speed_fact.py
```

### 2. 속도모델

```powershell
python src/models/01_build_model_a.py
python src/models/02_build_model_bc.py --mode validate
python src/models/02_build_model_bc.py --mode final
```

현재 전 링크 계층은 A 44,960개, B 16,752개, C 1,836개입니다. B는 61개 피처, C는 이웃속도를 제외한 60개 피처의 XGBoost를 사용합니다.

### 3. 속도 예측

```powershell
# 한 시점: 표준 링크별 레이더 강수 스냅샷 사용
python src/models/03_predict_all_link_speed.py --tm 202607160800

# 한 시점 강수 시나리오
python src/models/03_predict_all_link_speed.py --tm 202607160800 --precip-mm 0

# 기간 전체
python src/models/04_batch_predict_all_link_speed.py --start-date 20260707 --end-date 20260720
```

출력은 `data/processed/all_link_speed_prediction_{YYYYMMDDHHMM}.csv`입니다. 각 파일에 63,548개 링크의 `speed_kmh`, `tier`, `speed_source`, `prediction_confidence`가 있습니다.

### 4. 전기차 에너지

```powershell
# 한 시점
python src/energy/01_compute_link_energy.py --tm 202607160800

# 기간 전체
python src/energy/02_batch_compute_link_energy.py --start-date 20260707 --end-date 20260720

# 실제 A 관측속도만 별도 계산
python src/energy/03_compute_observed_speed_energy.py --start-date 20260707 --end-date 20260720 --exclude-tm 202607070000
```

VT-CPEM은 프로젝트 원문 [에코라우팅.pdf](에코라우팅.pdf)를 따라 링크 내 평균속도 일정, 가속도 0, 회생제동 없음으로 근사합니다. 원경사는 보존하되 계산경사는 ±12%로 제한합니다. 경로 비용은 `energy_ev_j` 또는 `energy_ev_wh`이고 `energy_wh_per_km`는 효율 비교용입니다.

### 5. EDA와 하이브리드

```powershell
python src/eda/observed_speed_eda.py
python src/eda/observed_energy_eda.py
python src/eda/compare_observed_lookup_and_build_hybrid.py
python src/eda/14_speed_energy_eda.py --start-date 20260707 --end-date 20260720
```

각 그림의 정확한 의미는 [EDA_GUIDE.md](docs/EDA_GUIDE.md)를 참고합니다.

## 주요 데이터 결과

| 산출물 | 크기/구성 |
| --- | --- |
| `seoul_link_dimension.csv` | 63,548 링크 |
| `seoul_link_speed_fact.csv` | 15,094,335 관측 링크-시간 |
| `model_a_lookup.parquet` | 2,158,080행 = 44,960×48 |
| `neighbor_speed_lookup.parquet` | 3,050,304행 = 63,548×48 |
| `all_link_speed_prediction_*.csv` | 335개, 각 63,548행 |
| `link_energy/link_energy_*.parquet` | 335개, 각 63,548행 |
| `observed_speed_energy/` | 15,049,459 actual A 링크-시간 |
| `historical_hybrid_link_energy/` | 335개, 총 21,288,580행 |

## 에너지 모델 요약

```text
u = speed_kmh / 3.6
Δt = LENGTH / u
θ = arctan(slope_pct_used / 100)
Crr = 1.75e-3 × (0.0328u + 4.575)
Pwheel = [m g Crr cosθ + m g sinθ + 0.5ρCdAf u²]u
Pbattery = max(Pwheel, 0)/(ηDηEMηB) + 700W
E = Pbattery × Δt
```

기준 차량 상수는 `m=1521kg`, `Cd=0.28`, `Af=2.3316m²`, `ρ=1.2256kg/m³`, `ηD=0.92`, `ηEM=0.91`, `ηB=0.90`입니다. 자세한 가정과 출력은 [방법론 문서](docs/METHODS_AND_PIPELINE.md)를 참고합니다.

## 라우팅 상태

라우팅은 링크를 `F_NODE→T_NODE` 방향 간선으로 보고 비용을 달리해 다음 세 경로를 찾는 것입니다.

- 최단거리: `Σ LENGTH`
- 최단시간: `Σ travel_time_sec`
- 에너지최소: `Σ energy_ev_j`

이 비교는 과거 실행됐습니다. 현재는 당시 `src/routing/16_eco_route.py`와 `route_scenario_summary.csv`가 정리돼 동일 결과를 바로 재실행할 수 없습니다. 남아 있는 `experiments/eco_routing*.py`는 오래된 내연기관 근사·옛 데이터 경로를 사용하므로 현재 Nissan Leaf EV 분석과 혼용하지 않습니다.

## 검증

에너지식은 `tests/test_link_energy.py`에서 평지 양의 에너지, 오르막 증가, 경사 clipping, 필수입력 검증을 검사합니다. 대용량 데이터 품질표에는 시점별 링크수, 속도·에너지 결측, 음의 에너지, 경사 이상치 수가 저장됩니다.

## 한계

- 14일 자료라 연중·계절 일반화가 어렵습니다.
- A lookup의 같은 기간 비교는 외부시험이 아닙니다.
- B/C는 실제 미관측 링크 정답이 없어 관측 링크 GroupKFold로 대리평가합니다.
- 교통량·View-T는 희소하고 일부 동적 입력은 과거 시간대 평균입니다.
- 에너지는 실차 계측값이 아니며 가감속·신호·회생제동·기온·냉난방·SOC를 반영하지 않습니다.
- 현재 라우팅 결과의 실행 코드와 최종 CSV가 함께 보존되지 않아 완전 재현성이 부족합니다.
