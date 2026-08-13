# Seoul Eco Routing

서울 표준노드링크, 5분 교통속도, DEM 경사, KMA 레이더 강수, 교통량·생활인구를 결합해 서울 전 도로 링크의 시간별 속도와 Nissan Leaf 기준 전기차 에너지 비용을 구축하고, 최단시간·최소에너지 경로를 비교하는 프로젝트입니다.

## 핵심 결과와 범위

- 서울 방향성 링크: 63,548개
- 분석 기간: 2026-07-07 01:00~2026-07-20 23:00, 335시간
- 속도 관측 이력 링크: 44,960개(70.75%)
- 미관측 링크: B 16,752개, C 1,836개
- 전 링크 시간별 비용: 21,288,580 링크-시간

2026-07-07 00:00은 공통 레이더 입력이 없어 분석에서 제외했습니다.

## 시작하기 전에

이 저장소는 원본·중간·대용량 산출 데이터를 Git에 포함하지 않습니다. 따라서 **클론 직후에는 라우팅과 대시보드가 실행되지 않습니다.** 먼저 아래 Quickstart의 데이터·모델·에너지 산출 단계를 완료하거나, 프로젝트 소유자로부터 해당 산출물을 받아야 합니다.

특히 다음 파일은 라우팅 및 대시보드 실행에 필요합니다.

- `data/interim/seoul_link.shp` 및 관련 Shapefile 구성 파일
- `data/processed/link_energy/link_energy_{YYYYMMDDHHMM}.parquet` (`prediction` 모드)
- `data/processed/historical_hybrid_link_energy/hybrid_link_energy_{YYYYMMDDHHMM}.parquet` (`hybrid` 모드)

`model_a_lookup.parquet`, `neighbor_speed_lookup.parquet`, `model_nb.pkl`, `model_stat.pkl`만으로는 경로탐색을 할 수 없습니다. 라우팅은 위의 시간별 링크 에너지 Parquet를 직접 읽습니다.

### 자료 모드

- `hybrid`: 해당 시점의 A 링크 실제 관측속도를 우선하고, 미관측분은 A lookup/B/C 예측으로 보완한 과거 재현 자료
- `prediction`: A lookup과 B/C 예측만으로 구성한 이력 기반 예측 자료

## Quickstart: 전체 재현 순서

아래 순서는 `hybrid` 라우팅과 대시보드까지 실행하는 순서입니다. 원본 입력자료가 준비되어 있다는 전제입니다.

### 1. 원자료 가공

```powershell
python src/pipeline/01_extract_seoul_links.py
python src/pipeline/02_aggregate_5min_speed.py
python src/pipeline/03_fetch_kma_radar.py --from-5min-times
python src/pipeline/04_build_link_dimension.py
python src/pipeline/05_build_speed_fact.py
```

### 2. 속도모델 학습

```powershell
python src/models/01_build_model_a.py
python src/models/02_build_model_bc.py --mode validate
python src/models/02_build_model_bc.py --mode final
```

### 3. 전 링크 속도 예측

```powershell
# 한 시점 예측
python src/models/03_predict_all_link_speed.py --tm 202607160800

# 전체 분석 기간 예측
python src/models/04_batch_predict_all_link_speed.py --start-date 20260707 --end-date 20260720
```

출력: `data/processed/all_link_speed_prediction_{YYYYMMDDHHMM}.csv`

### 4. 전기차 링크 에너지 계산

```powershell
# 한 시점 에너지 계산
python src/energy/01_compute_link_energy.py --tm 202607160800

# 전체 분석 기간 에너지 계산
python src/energy/02_batch_compute_link_energy.py --start-date 20260707 --end-date 20260720

# 실제 A 관측속도 기반 에너지 분석용 산출물
python src/energy/03_compute_observed_speed_energy.py --start-date 20260707 --end-date 20260720 --exclude-tm 202607070000
```

출력: `data/processed/link_energy/link_energy_{YYYYMMDDHHMM}.parquet`

### 5. A lookup 진단 및 hybrid 자료 생성

`hybrid` 라우팅과 대시보드를 실행하려면 이 단계를 **라우팅보다 먼저** 실행해야 합니다.

```powershell
python src/eda/compare_observed_lookup_and_build_hybrid.py
```

출력: `data/processed/historical_hybrid_link_energy/hybrid_link_energy_{YYYYMMDDHHMM}.parquet`

선택적으로 전체 EDA를 생성합니다.

```powershell
python src/eda/observed_speed_eda.py
python src/eda/observed_energy_eda.py
python src/eda/14_speed_energy_eda.py --start-date 20260707 --end-date 20260720
```

### 6. 경로 비교 및 평가

```powershell
# 한 OD의 최단시간·최소에너지·최단거리·균형경로 비교
python src/routing/01_route_compare.py --tm 202607160800 --dataset hybrid --origin 37.4979,127.0276 --destination 37.5665,126.9780

# 대표 OD 경로 평가
python src/routing/02_evaluate_route_scenarios.py --timestamps 202607160800 --dataset hybrid
```

`--dataset prediction`을 사용하면 5단계의 hybrid 산출물 없이 4단계의 `link_energy` 결과를 사용합니다.

### 7. 로컬 대시보드

대시보드 의존성을 설치합니다.

```powershell
python -m pip install -r requirements-dashboard.txt
```

그 다음, 4단계까지의 `prediction` 산출물 또는 5단계까지의 `hybrid` 산출물과 Shapefile이 준비된 상태에서 실행합니다.

```powershell
uvicorn app.server:app --reload
```

브라우저에서 `http://127.0.0.1:8000`을 엽니다. 기능과 자료 모드의 해석은 [대시보드 가이드](docs/DASHBOARD_GUIDE.md)를 참고하세요.

## 주요 용어

- **A-observed**: 해당 날짜·시간의 5분 관측을 1시간 평균한 실제 속도
- **A lookup**: 관측 링크의 `LINK_ID × 시간 × 주중/주말` 이력 평균 예측값
- **B prediction**: 자체 관측은 없지만 이웃 관측 링크의 이력속도를 활용할 수 있는 링크 예측값
- **C prediction**: 이웃 이력속도도 없는 링크의 정적 피처 기반 예측값
- **관측속도 기반 에너지**: actual A 속도를 물리식에 넣은 추정치이며, 차량 실측 전력은 아님
- **전 링크 예측 에너지**: A lookup+B/C 예측속도를 물리식에 넣은 추정치

## 프로젝트 구조

```text
app/          FastAPI·Leaflet 로컬 대시보드
src/pipeline/ 원자료 수집·서울 링크 추출·시간 집계·차원/팩트 구축
src/models/   A lookup, B/C 학습, 전 링크 속도 예측
src/energy/   VT-CPEM 링크 에너지 계산
src/eda/      관측·예측 결과 EDA 및 hybrid 자료 생성
src/routing/  경로 비교·다중 OD 평가·경로 엔진
docs/         방법론, EDA 해석, 대시보드 가이드, 보고서 초안
data/         raw/interim/processed 데이터와 데이터 사전
tests/        에너지식·경로 엔진 단위테스트
```

## 문서

- [방법론과 코드 파이프라인](docs/METHODS_AND_PIPELINE.md)
- [데이터 사전](data/README.md)
- [EDA 그림·표 해석](docs/EDA_GUIDE.md)
- [대시보드 가이드](docs/DASHBOARD_GUIDE.md)
- [데이터 분석 보고서 초안](docs/DATA_ANALYSIS_REPORT.md)
- [노트북 전수 검토](docs/NOTEBOOK_AUDIT.md)

## 에너지 모델

Nissan Leaf 기준 VT-CPEM 근사식을 사용합니다.

```text
u = speed_kmh / 3.6
Δt = LENGTH / u
θ = arctan(slope_pct_used / 100)
Crr = 1.75e-3 × (0.0328u + 4.575)
Pwheel = [m g Crr cosθ + m g sinθ + 0.5ρCdAf u²]u
Pbattery = max(Pwheel, 0)/(ηDηEMηB) + 700W
E = Pbattery × Δt
```

기준 차량 상수는 `m=1521kg`, `Cd=0.28`, `Af=2.3316m²`, `ρ=1.2256kg/m³`, `ηD=0.92`, `ηEM=0.91`, `ηB=0.90`입니다. 링크 내 평균속도는 일정하고 가속도는 0으로 가정하며, 회생제동은 적용하지 않습니다. 원시 경사는 보존하되 에너지 계산 시 ±12%로 제한합니다.

## 한계

- 분석기간이 14일이라 계절·연중 일반화가 어렵습니다.
- A lookup의 동일기간 비교는 독립 외부검증이 아닌 후향 진단입니다.
- B/C는 실제 미관측 링크 정답이 없어 관측 링크 GroupKFold 대리평가를 사용합니다.
- 교통량·View-T는 희소하고 일부 동적 입력은 과거 시간대 평균입니다.
- 에너지는 실차 계측값이 아니며 가감속·신호·회생제동·기온·냉난방·SOC를 반영하지 않습니다.
- 현재 라우팅은 선택 시각의 정적 링크 비용을 사용하며, 회전제약·실시간 통제·시간의존 비용을 완전히 반영하지 않습니다.
