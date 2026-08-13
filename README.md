# Seoul Eco Routing

서울 표준노드링크, 5분 교통속도, DEM 경사, KMA 레이더 강수, 교통량·생활인구를 결합해 서울 전 도로 링크의 시간별 속도와 Nissan Leaf 기준 에너지 비용을 구축하는 프로젝트입니다.

## 현재 완료 상태

5분 데이터로도 서울 표준링크 63,548개 중 44,960개(70.75%)만 직접 관측됩니다(나머지는 TOPIS 관측 인프라가 없는 이면도로). 그래서 파이프라인은 관측 링크만 연결해 경로를 찾는 방식이 아니라, 관측값을 학습 라벨로 쓰고 모든 링크에서 구할 수 있는 도로·지형·시간·강수 피처로 나머지 링크의 속도를 추정하는 **전 링크 모델(Model B)** 을 이어 붙입니다.

데이터 스키마, 서울 링크 추출/매칭 방식, 누수 방지 평가, 전 링크 추정 방식과 한계는 **[data/README.md](data/README.md)**를 참고하세요.

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

## Project Structure

```text
.
├── app/
│   └── main.py         # Streamlit 기반 인터랙티브 대시보드 앱
├── src/
│   ├── pipeline/       # 데이터 수집·정제(ETL) — 01~05, 아래 Scripts 참고
│   ├── models/         # 모델 학습·평가 — 01_build_model_a.py, 02_build_model_bc.py
│   ├── routing/        # 라우팅용 다운스트림 — 12/13(전 링크 스냅샷·예측), 15(에너지 비용)
│   └── eda/            # 정식 승격된 진단/시각화 스크립트, maps.py (동적 지도 시각화/스냅샷 자동화)
├── notebooks/
│   ├── 10_eda_report.ipynb        # 주의: 재정비 필요, 아래 Notebooks 참고
│   ├── 11_speed_model_baseline.ipynb  # 주의: 재정비 필요, 아래 Notebooks 참고
│   ├── 12_derived_features_lightgbm.ipynb  # 파생/외부 피처 검증
│   ├── 12b_model_a_history.ipynb   # 관측 링크용 이력 모델
│   └── 13_tier_split_evaluation.ipynb  # A/B/C 계층 분리 평가
├── data/
│   ├── README.md       # 데이터 스키마/매칭 방식/결과 상세 문서
│   ├── raw/
│   │   ├── road/       # MOCT_LINK.*, MOCT_NODE.*, MULTILINK.dbf, TURNINFO.dbf
│   │   ├── boundary/   # seoul_admin_boundary.geojson (서울 25개 자치구 경계)
│   │   ├── traffic/    # 5분 단위 전국 교통소통 원본(202607_5Min/*.csv), bus_lane/, school_zone/, speed_bump/, traffic_volume.xlsx 등
│   │   ├── dem/        # 37608.img, 37612.img, 37705.img, 37709.img
│   │   └── weather/    # KMA key, HSR grid, radar raw files
│   ├── interim/        # pipeline 중간 산출물(seoul_link.*, seoul_link_attr.csv, seoul_link_dem_features.csv,
│   │   │                 seoul_link_speed_5min_hourly.csv, weather_hsr_seoul_grid.npz, link_radar_grid_mapping.csv)
│   │   └── notebook_cache/  # 노트북 전용 캐시(재실행하면 다시 생김, 자유롭게 삭제 가능)
│   └── processed/      # seoul_link_dimension.csv, seoul_link_speed_fact.csv, seoul_all_link_eco_snapshot/, seoul_all_link_speed/, weather_snapshot/
└── docs/
    └── figures/
        ├── eda/       # 10번 노트북이 생성하는 보고서용 EDA 그래프
        ├── model/     # 11/12번 노트북이 생성하는 속도 예측 모델 그래프
        └── model_a/   # 12b_model_a_history 노트북이 생성하는 그래프
```

`data/raw/`, `data/interim/`, `data/processed/`의 실제 데이터 파일은 대용량 원본/중간/가공 데이터이므로 Git에 올리지 않습니다. 대신 각 폴더에는 `.gitkeep`을 두어 필요한 폴더 구조만 GitHub에 표시합니다. 예외적으로 `data/raw/boundary/seoul_admin_boundary.geojson`은 크기가 작은 정적 참조 데이터라 커밋합니다(자세한 내용은 [data/README.md](data/README.md) 참고).

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

외부 컨텍스트 피처의 계층별 커버리지(전체 링크 대비 값이 존재하는 비율):

| 계층 | 교통량 | 버스전용차로 | 스쿨존 | 사고다발 | 과속방지턱 |
| --- | ---: | ---: | ---: | ---: | ---: |
| A 관측 | 39.3% | 10.1% | 41.6% | 4.5% | 16.1% |
| B 미관측·이웃있음 | 1.5% | 3.4% | 43.5% | 2.5% | 24.0% |
| C 미관측·이웃없음 | 1.1% | **0.0%** | 44.2% | 1.3% | 34.4% |

버스전용차로는 C 계층 커버리지가 0%라 그 계층에서는 아무 정보도 주지 못합니다(간선도로에만 존재). 반대로 스쿨존·과속방지턱은 C에서 오히려 커버리지가 높은데도 기여가 작아, 이면도로 속도는 시설물보다 **교차로 구조(위상)** 가 설명한다는 쪽에 가깝습니다.

추가 외부 데이터는 **C 계층을 덮는 것만 가치가 있습니다.** View-T 혼잡시간강도는 상세도로망 Level6로 제공되어 C 커버리지가 1.1% → 29.4%가 되며(`seoul_link_lev6_2024.shp`의 `up_its_id`/`dw_its_id`로 `LINK_ID`에 직접 조인), 속도로부터 산출된 지표라 타깃과 단위계가 같습니다. 반대로 서울 열린데이터광장 **도시고속도로 5분단위 링크 속도(OA-22351)는 받을 필요가 없습니다** — 도시고속국도는 이미 관측률 98.3%이고, 미관측 링크의 96%는 특별광역시도입니다.

## Notebooks

| Notebook | Description |
| --- | --- |
| `10_eda_report.ipynb` | 최종 결합 테이블을 입력으로 강수량·경사도·도로등급·첨두시간대별 평균속도 EDA 테이블과 차트를 생성하는 리포트. 집계 테이블은 셀 출력으로 바로 보여주고, 보고서용 차트 7장만 `docs/figures/eda/`에 저장 |
| `11_speed_model_baseline.ipynb` | 초기 LightGBM 베이스라인과 랜덤/그룹 분할 비교 |
| `12_derived_features_lightgbm.ipynb` | 파생/외부 피처(버스전용차로 겹침비율, View-T 추정교통량, 순환 인코딩, 인접 실측 이웃속도)를 LightGBM/XGBoost로 빠르게 검증하는 핵심 노트북(5차~16차) |
| `12b_model_a_history.ipynb` | 관측 링크(Model A)용 이력 모델 — 링크×시간×주중/주말 조회표와 lag 피처 비교. 여기서 검증된 시간분할 설계를 `src/models/01_build_model_a.py`가 그대로 이어받음 |
| `13_tier_split_evaluation.ipynb` | 링크를 A(관측)/B(미관측·이웃있음)/C(미관측·이웃없음)로 나눠 계층별로 성능을 재측정. 인접 이웃속도 피처가 C 계층에서 성능을 떨어뜨리는 문제와 분리 모델 해결책을 검증 — `12_derived_features_lightgbm.ipynb`와 `src/models/02_build_model_bc.py`가 이 결론을 이어받음 |

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

이 비교는 과거 실행됐습니다. 현재는 당시 `src/routing/16_eco_route.py`와 `route_scenario_summary.csv`가 정리돼 동일 결과를 바로 재실행할 수 없습니다.

### 에코라우팅 결과 (Stage 3, 과거 실행)

`src/routing/16_eco_route.py`, 서울 주요 지점 30개 OD, 기준차 닛산 리프(VT-CPEM):

| 시나리오 | 평균속도 | **에너지 절감** | 통행시간 | 주행거리 | 경로변경 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 아침 첨두 (7/14 화 09시) | 18.5 km/h | 17.3% | +23.6% | +0.8% | 29/30 |
| 저녁 첨두 (7/14 화 19시) | 16.6 | 20.1% | +21.5% | −2.7% | 30/30 |
| 심야 (7/14 화 04시) | 25.4 | **24.5%** | +42.3% | −4.2% | 30/30 |
| 강수 (7/9 목 13시) | 19.0 | 19.7% | +23.9% | −3.8% | 30/30 |
| 주간 기준 (7/16 목 08시) | 20.5 | 19.5% | +27.7% | −0.0% | 29/30 |

**에너지 최적 경로는 최단시간 경로 대비 전력을 평균 20.2% 줄입니다.** 통행시간은 늘지만 **주행거리는 거의 같습니다** — 멀리 돌아가서 아끼는 것이 아니라 같은 거리를 다른 경로로 가며 경사 부담을 피하는 것입니다. 링크 에너지 순위를 지배하는 것은 경사(순위상관 **+0.907**)이고 통행시간과의 상관은 +0.262에 그칩니다.

절감이 가장 큰 구간은 북부 구릉지로 향하는 경로입니다(여의도→북한산우이 **50.4% 절감**, 주행거리는 오히려 19.2% 짧음). 반대로 평지 구간(강남역→잠실역)은 0.0%로, 바꿀 여지가 없을 때는 경로가 그대로 유지됩니다. 정체가 심할수록 절감 여지가 줄어드는 경향도 확인됩니다(심야 24.5% vs 아침 첨두 17.3%).

산출물: `routes_{tm}.geojson`(EPSG:4326, `route_type`=shortest/fastest/eco), `route_comparison_{tm}.csv`, `route_scenario_summary.csv`(과거 실행분, 현재 재생성 불가)

전체 수치, 도로등급별 매칭률, 미매칭 링크 특성은 [data/README.md의 "Current Results"](data/README.md#current-results)를 참고하세요.

## 검증

에너지식은 `tests/test_link_energy.py`에서 평지 양의 에너지, 오르막 증가, 경사 clipping, 필수입력 검증을 검사합니다. 대용량 데이터 품질표에는 시점별 링크수, 속도·에너지 결측, 음의 에너지, 경사 이상치 수가 저장됩니다.

## 한계

- 14일 자료라 연중·계절 일반화가 어렵습니다.
- A lookup의 같은 기간 비교는 외부시험이 아닙니다.
- B/C는 실제 미관측 링크 정답이 없어 관측 링크 GroupKFold로 대리평가합니다.
- 교통량·View-T는 희소하고 일부 동적 입력은 과거 시간대 평균입니다.
- 에너지는 실차 계측값이 아니며 가감속·신호·회생제동·기온·냉난방·SOC를 반영하지 않습니다.
- 현재 라우팅 결과의 실행 코드와 최종 CSV가 함께 보존되지 않아 완전 재현성이 부족합니다.

## Notes

- T-data API 수집 코드는 사용하지 않습니다(현재는 T-data 자체를 파이프라인에서 쓰지 않고, 5분 단위 전국 교통소통 데이터로 대체했습니다).
- `data/raw/` 아래 원본 데이터는 직접 받은 파일이므로 코드에서 수정하지 않는 것을 원칙으로 합니다.
- 5분 단위 원본은 하루치가 약 7GB(전국 단위)라 `src/pipeline/02_aggregate_5min_speed.py`가 서울 링크만 걸러 1시간 단위로 압축합니다. 원본 용량 때문에 `data/raw/traffic/202607_5Min/`에는 보통 최근 받은 날짜만 남아있는데, 02번은 실행할 때마다 기존 `seoul_link_speed_5min_hourly.csv`를 읽어 지금 폴더에 없는 과거 날짜는 보존하고 폴더에 있는 날짜만 새로 반영합니다 — 새 날짜를 추가하려면 그 날짜 파일만 폴더에 넣고 02번을 다시 실행하면 됩니다.
- Model B의 공간 일반화 평가는 관측 링크 일부를 통째로 제외하는 방식입니다. 실제 미관측 29.25% 링크에는 정답 속도가 없으므로 그 구간의 정확도를 직접 측정한 결과는 아닙니다.
- 현재 전 링크 출력으로 연결된 서울 도로망의 경로탐색 입력은 만들 수 있지만, 최소시간·최소에너지 라우팅 로직 자체는 별도 단계입니다.
- 서울 링크 추출 기준(bbox → 행정경계), 속도 데이터 매칭 방식과 그 배경, 캐시 무효화 시 주의사항 등은 모두 [data/README.md](data/README.md)에 정리되어 있습니다.
