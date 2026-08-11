# Seoul Eco Routing

서울시 도로 링크, ITS 5분 단위 교통소통 데이터, DEM 고도, KMA 레이더 강수량을 결합해 서울 전역 링크의 시간대별 속도와 통행시간을 추정하는 프로젝트입니다.

현재 속도 데이터는 ITS 국가교통정보센터 계열의 5분 단위 전국 교통소통 원본(하루 약 1.7억 행)을 서울 표준노드링크 LINK_ID 기준으로 걸러 1시간 단위로 집계해 사용합니다(과거에 쓰던 T-data 1시간 소통정보 + 공식 매핑 테이블 방식은 커버리지가 17.33%에 그쳐 대체했습니다 — 배경은 [data/README.md](data/README.md) 참고). KMA 레이더 강수량은 API로 내려받아 시간·공간 기준으로 링크에 매칭합니다.

5분 데이터로도 서울 표준링크 63,548개 중 44,960개(70.75%)만 직접 관측됩니다(나머지는 TOPIS 관측 인프라가 없는 이면도로). 그래서 파이프라인은 관측 링크만 연결해 경로를 찾는 방식이 아니라, 관측값을 학습 라벨로 쓰고 모든 링크에서 구할 수 있는 도로·지형·시간·강수 피처로 나머지 링크의 속도를 추정하는 **전 링크 모델(Model B)** 을 이어 붙입니다.

데이터 스키마, 서울 링크 추출/매칭 방식, 누수 방지 평가, 전 링크 추정 방식과 한계는 **[data/README.md](data/README.md)**를 참고하세요.

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
├── experiments/        # 팀원 각자의 프로토타입·1회성 실험 코드(정식 반영 전 단계)
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
│   │   ├── traffic/    # 5분 단위 전국 교통소통 원본(202607_5Min/*.csv), bus_lane/, school_zone/, speed_bump/, traffic_volume.xlsx 등
│   │   ├── dem/        # 37608.img, 37612.img, 37705.img, 37709.img
│   │   └── weather/    # KMA key, HSR grid, radar raw files
│   ├── interim/        # pipeline 중간 산출물(seoul_link.*, seoul_link_attr.csv, seoul_link_dem_features.csv,
│   │   │                 seoul_link_speed_5min_hourly.csv, weather_hsr_seoul_grid.npz, link_radar_grid_mapping.csv)
│   │   └── notebook_cache/  # 노트북·experiments 전용 캐시(재실행하면 다시 생김, 자유롭게 삭제 가능)
│   └── processed/      # seoul_link_dimension.csv, seoul_link_speed_fact.csv, seoul_all_link_eco_snapshot/, seoul_all_link_speed/, weather_snapshot/
├── docs/
│   └── figures/
│       ├── eda/       # 10번 노트북이 생성하는 보고서용 EDA 그래프
│       ├── model/     # 11/12번 노트북이 생성하는 속도 예측 모델 그래프
│       └── model_a/   # 12_model_a_history 노트북이 생성하는 그래프
└── README.md
```

`data/raw/`, `data/interim/`, `data/processed/`의 실제 데이터 파일은 대용량 원본/중간/가공 데이터이므로 Git에 올리지 않습니다. 대신 각 폴더에는 `.gitkeep`을 두어 필요한 폴더 구조만 GitHub에 표시합니다. 예외적으로 `data/raw/boundary/seoul_admin_boundary.geojson`은 크기가 작은 정적 참조 데이터라 커밋합니다(자세한 내용은 [data/README.md](data/README.md) 참고).

**`experiments/`와 `notebooks/`의 차이**: `experiments/`는 파라미터를 바꿔가며 반복 실행하는 코드형 실험 하네스입니다(CLI 인자로 설정을 바꾸고, 결과를 `results.csv` 같은 구조화된 파일에 계속 append) — 사람이 읽는 서사보다 재현 가능한 실험 코드 자체가 목적입니다. `notebooks/`는 마크다운 설명·실행 로그·차트가 셀 안에 함께 있는 서술형 분석 리포트로, "왜 이 결론에 도달했는지"를 사람이 읽도록 남기는 게 목적입니다. 둘 다 `src/`(정식 반영·검증된 코드)로 승격되기 전 단계라는 공통점이 있습니다.

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

`src/pipeline/`의 파일명 앞 번호는 실행 순서(파이프라인 순서)를 나타냅니다. 데이터를 "링크당 1행(차원 테이블)"과 "(LINK_ID,기준일,시간코드)당 1행(팩트 테이블)"로 정규화해서 저장합니다(옛 버전은 정적 속성을 관측 행마다 중복 저장해 용량이 컸습니다) — 스키마는 [data/README.md](data/README.md) 참고.

| Script | Description |
| --- | --- |
| `src/pipeline/01_extract_seoul_links.py` | 서울 행정경계(25개 자치구) 기준 링크를 추출해 `seoul_link.*`, `seoul_link_attr.csv` 생성 |
| `src/pipeline/02_aggregate_5min_speed.py` | 5분 단위 전국 교통소통 원본(하루 약 1.7억 행)에서 서울 링크만 걸러 1시간 단위로 집계. Polars 기반의 멀티스레딩 지연 연산을 통해 대용량 데이터를 고속 처리하며, 기존 데이터는 보존하고 새 데이터만 점진적으로 업데이트하는 멱등성이 내장 |
| `src/pipeline/03_fetch_kma_radar.py` | KMA HSR 격자와 1시간 누적 레이더 강수량 다운로드 |
| `src/pipeline/04_build_link_dimension.py` | DEM 고도/경사, 도로망 위상, 외부 컨텍스트(버스전용차로/스쿨존/사고다발/과속방지턱/AADT)를 전부 결합한 링크 차원 테이블(`seoul_link_dimension.csv`, 63,548행) 생성 |
| `src/pipeline/05_build_speed_fact.py` | 레이더 강수, 시간대별 교통량을 02번 결과에 결합한 속도 팩트 테이블(`seoul_link_speed_fact.csv`, 15,094,335행) 생성 |
| `src/eda/maps.py` | 기존 정적 PNG 지도의 한계를 극복하기 위해 시각화 엔진과 데이터 연산 역할 분리. Folium(2D) 및 PyDeck(3D) 동적 지도 지원, 분위수 기반 지능형 색상 매핑(get_color_scheme), 시각화용 12/13/15번 순차 자동 실행 파이프라인(prepare_visualization_data)을 통해 최종 결합 스냅샷(seoul_all_link_eco_snapshot_{tm}.csv)을 생성 |
| `src/models/11_evaluate_speed_model.py` | 원본 관측 누수를 막은 시간·공간 일반화 평가와 피처 중요도 저장 |
| `src/routing/12_build_all_link_weather_snapshot.py` | 특정 시각의 서울 전체 63,548개 링크 강수 스냅샷 생성
| `src/routing/13_predict_all_link_speed.py` | 사전 학습 아티팩트(model_nb.pkl, model_stat.pkl 등)를 로드해 추론 수행 → 계층적 fallback 순으로 전체 링크 속도·통행시간 생성 |
| `src/routing/15_add_energy_cost.py` | 13번 속도 스냅샷 + 경사로 링크별 배터리 소비 에너지 계산 — **VT-CPEM**(Fiori et al. 2016), 기준차 닛산 리프 |
| `src/routing/16_eco_route.py` | 링크 에너지를 간선 비용으로 써서 최단거리/최단시간/**에너지최적** 3경로를 비교. 경로 GeoJSON과 절감률 표 생성 |
| `app/main.py` | Streamlit 대시보드 구축 및 동적 UI 제어: maps.py가 사전 연산한 스냅샷을 활용한 실시간 대시보드. 컨트롤 패널(날짜/시간/기준변수 선택), 3D PyDeck 탭(경사도 Z축 렌더링), 2D Folium 탭(도로 클릭 시 툴팁 상세 속성 조회), 다중 속성 테이블 탐색기(도로명 필터링) 제공 |

진단·시각화(매칭률, 지도 등)는 `src/pipeline/`에 두지 않고 `notebooks/`에서 다룹니다 — 이전 T-data+공식매핑 방식에서 5분 데이터 방식으로 왜 바꿨는지, 매칭 방법이 어떻게 검증됐는지는 [data/README.md의 "속도 데이터 매칭"](data/README.md#속도-데이터-매칭)에 자세히 정리되어 있습니다.

## Pipeline

현재 작업은 다음 순서로 이어집니다.

1. `pipeline/01`: 전국 표준노드링크에서 서울 행정경계와 교차하는 63,548개 링크를 추출합니다.
2. `pipeline/02`: 5분 단위 전국 교통소통 원본에서 서울 링크만 걸러 1시간 단위로 집계합니다(44,960개 링크, 70.75%).
3. `pipeline/03`: 필요한 시각의 KMA 레이더 원본을 수집합니다.
4. `pipeline/04`: DEM 고도/경사, 도로망 위상, 외부 컨텍스트를 전부 결합해 링크 차원 테이블을 만듭니다.
5. `pipeline/05`: 레이더 강수·시간대별 교통량을 결합해 속도 팩트 테이블을 만듭니다.
6. `models/11`: 날짜 순차 분할과 원본 링크 GroupKFold로 시간·공간 일반화를 평가합니다.
7. `routing/12~13`: 원하는 시각의 전 링크 기상 스냅샷을 만든 뒤 63,548개 링크 모두의 속도와 통행시간을 생성합니다.
8. `routing/15`: 속도 스냅샷에 DEM 경사를 결합해 링크별 배터리 소비 에너지를 계산합니다(VT-CPEM).
9. `routing/16`: 링크 에너지를 간선 비용으로 써서 에너지 최적 경로를 찾고, 최단거리·최단시간 경로와 비교합니다.

속도 산출 우선순위는 다음과 같습니다.

```text
해당 시각 팩트 테이블 관측값                              (A 계층 44,960)
    -> 1홉에 관측 이웃이 있으면  이웃속도 포함 모델        (B 계층 14,006)
    -> 1홉에 관측 이웃이 없으면  정적 전용 모델            (C 계층  4,582)
    -> 학습에 없던 범주/지원 표본 부족이면 계층적 fallback
    -> speed_kmh로 링크 통행시간 계산
```

미관측 링크에 모델을 하나만 쓰지 않고 둘로 나누는 이유는 `notebooks/13_tier_split_evaluation.ipynb`에 있습니다 — 이웃속도 피처가 B에서는 R² +0.067이지만 C에서는 **−0.178**이라, 단일 모델로 쓰면 정보가 가장 부족한 계층이 오히려 나빠집니다.


**스크립트별 상태** (파이프라인 리팩토링 이후):

| 스크립트 | 상태 |
| --- | --- |
| `routing/12_build_all_link_weather_snapshot.py` | ✅ 이동 및 최적화 완료 — src/routing/ 이동, C-레벨 정규식 제거/NumPy/Polars 엔진 도입으로 고속화, data/processed/weather_snapshot/ 폴더화 및 멱등성 확립 |
| `routing/13_predict_all_link_speed.py` | ✅ 최신 모델 및 새 스키마(dimension+fact) 적용 · 사전 학습 아티팩트 기반 빠른 추론 · Polars 고속화 및 Feature 정렬 최적화 |
| `routing/15_add_energy_cost.py` | ✅ VT-CPEM(Fiori et al. 2016)으로 재작성 · 기준차 닛산 리프 |
| `routing/16_eco_route.py` | ✅ 신규 — 5개 시각 실행 완료 |
| `models/11_evaluate_speed_model.py` | ❌ 미이전 — 삭제된 `seoul_link_speed_dem_weather_merged.csv`를 직접 가리킵니다. 파일도 아직 `src/` 루트에 있습니다 |
| `experiments/*` | ❌ 미이전 — `build_official_17pct.py`, `build_structural_features.py`, `eco_routing.py`, `eco_routing_global.py`, `fill_all_speeds.py`가 옛 경로를 참조합니다 |

`13`의 학습 데이터는 `seoul_link_speed_fact.csv`(관측 라벨·강수)와 `seoul_link_dimension.csv`(정적 속성)를 `LINK_ID`로 merge해서 만듭니다. `sample_weight`/`source_section_id`는 5분 데이터에서 각각 상수 1.0과 `LINK_ID`라 팩트 테이블에 저장하지 않으므로 코드에서 쓰지 않습니다. "Current Results"의 Model B 수치는 이전 T-data 버전 기준이니 재실행 전까지 참고용으로만 보세요.

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


## Streamlit 시각화 Pipeline
```
# Step 1: 기본 데이터 수집 및 팩트/차원 테이블 빌드
python src/pipeline/01_extract_seoul_links.py
python src/pipeline/02_aggregate_5min_speed.py
python src/pipeline/03_fetch_kma_radar.py
python src/pipeline/04_build_link_dimension.py
python src/pipeline/05_build_speed_fact.py

# Step 2: 시각화용 에코 스냅샷 일괄 생성 (maps.py 실행)
python -m src.eda.maps

# Step 3: Streamlit 대시보드 구동
streamlit run app/main.py
```

## Streamlit 기능 요약
- **원하는 분석 조건 즉시 변경 (단일화된 컨트롤 패널)**
    - 왼쪽 사이드바에서 분석하고 싶은 '날짜'와 '시간'을 고르고, 지도에 색상으로 표현할 '기준 변수(속도, 연료소모량, 강수량 등)'를 선택하면 즉시 맵 화면이 그에 맞게 업데이트됩니다
- **입체적인 지형 및 혼잡 관제 (3D PyDeck 탭)**
    - 도로의 실제 경사도(`slope_pct`)를 Z축(높이)으로 띄웁니다
    - 이를 통해 어느 도로가 급격한 오르막/내리막인지 입체적으로 보면서 선택한 변수(예: 속도, 에너지 소모)를 직관적으로 분석할 수 있습니다
- **정밀한 도로 속성 조회 (2D Folium 탭)**
    - 지도 위의 특정 도로 선분을 마우스로 클릭하면, 해당 도로의 어린이보호구역 유무, 교차로 복잡도, 차로 수 등 10여 가지가 넘는 세부 환경 변수 정보를 팝업 툴팁으로 바로 확인할 수 있습니다
- **특정 도로명 검색 및 전체 데이터 표 확인 (다중 속성 테이블 탐색기)**
    - 지도 아래의 표에서 시각화된 전체 도로 데이터를 한눈에 엑셀처럼 볼 수 있습니다
    - 검색창에 '종로', '세종대로' 등을 입력해 원하는 도로의 수치만 빠르게 필터링해 찾아보는 것도 가능합니다

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
| B 미관측·이웃있음 | 14,006 (22.0%) | 787 km | LightGBM + 인접 실측 이웃속도 | 공간 블록 2km | 0.780 | 5.49 |
| C 미관측·이웃없음 | 4,582 (7.2%) | 402 km | LightGBM 정적 전부 (이웃속도 **제외**) | 공간 블록 2km | 0.492 | 5.99 |

링크수 가중 평균 MAE 3.59 km/h. C 계층에 이웃속도 피처를 그대로 넣으면 R²가 0.492 → **0.314로 떨어집니다** — 훈련 행 대부분에 이웃속도가 있어 모델이 그 피처에 의존하도록 학습되는데, C에서는 결측이기 때문입니다. 미관측 링크는 계층별로 다른 모델을 써야 합니다(결측 폴백은 0.419까지만 회복). 근거와 해결책 비교는 노트북 7절 참고.

피처 그룹별 R² 기여도(공간 블록분할):

| 피처 그룹 | B 이웃있음 | C 이웃없음 |
| --- | ---: | ---: |
| 도로망 위상·파생 28개 (`pipeline/04`) | +0.026 | **+0.043** |
| 외부 컨텍스트 7개 (교통량/버스전용차로/스쿨존/사고다발/과속방지턱) | +0.006 | +0.010 |
| 인접 실측 이웃속도 | **+0.067** | **−0.178** |

**정적 피처 중에서는 외부 시설물보다 도로망 위상이 4배 이상 기여합니다**(모델 gain 비중도 위상·파생 12.7% vs 외부 2.5%). 외부 컨텍스트가 계속 +0.01에 그치는 이유는 계층별 커버리지에서 드러납니다(노트북 2절):

| 계층 | 교통량 | 버스전용차로 | 스쿨존 | 사고다발 | 과속방지턱 |
| --- | ---: | ---: | ---: | ---: | ---: |
| A 관측 | 39.3% | 10.1% | 41.6% | 4.5% | 16.1% |
| B 미관측·이웃있음 | 1.5% | 3.4% | 43.5% | 2.5% | 24.0% |
| C 미관측·이웃없음 | 1.1% | **0.0%** | 44.2% | 1.3% | 34.4% |

버스전용차로는 C 계층 커버리지가 0%라 그 계층에서는 아무 정보도 주지 못합니다(간선도로에만 존재). 반대로 스쿨존·과속방지턱은 C에서 오히려 커버리지가 높은데도 기여가 작아, 이면도로 속도는 시설물보다 **교차로 구조(위상)** 가 설명한다는 쪽에 가깝습니다.

추가 외부 데이터는 **C 계층을 덮는 것만 가치가 있습니다.** View-T 혼잡시간강도는 상세도로망 Level6로 제공되어 C 커버리지가 1.1% → 29.4%가 되며(`seoul_link_lev6_2024.shp`의 `up_its_id`/`dw_its_id`로 `LINK_ID`에 직접 조인), 속도로부터 산출된 지표라 타깃과 단위계가 같습니다. 반대로 서울 열린데이터광장 **도시고속도로 5분단위 링크 속도(OA-22351)는 받을 필요가 없습니다** — 도시고속국도는 이미 관측률 98.3%이고, 미관측 링크의 96%는 특별광역시도입니다.

### 에코라우팅 결과 (Stage 3)

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

산출물: `routes_{tm}.geojson`(EPSG:4326, `route_type`=shortest/fastest/eco), `route_comparison_{tm}.csv`, `route_scenario_summary.csv`

전체 수치, 도로등급별 매칭률, 미매칭 링크 특성은 [data/README.md의 "Current Results"](data/README.md#current-results)를 참고하세요.

## Workflow

**참고**: `src/pipeline/`은 이번 리팩토링으로 실제로 이 위치에 옮겨졌습니다. `src/models/`, `src/routing/`, `src/eda/`는 폴더만 먼저 만들어둔 상태이고, 아래 11/12/13/15는 아직 물리적으로는 예전 위치(`src/` 바로 아래)에 있습니다 — 파일 이동은 각자 작업 중인 부분과 충돌하지 않도록 팀원별로 진행합니다.

```bat
.venv\Scripts\activate.bat

python src\pipeline\01_extract_seoul_links.py
python src\pipeline\02_aggregate_5min_speed.py
python src\pipeline\03_fetch_kma_radar.py --grid
python src\pipeline\03_fetch_kma_radar.py --from-5min-times
python src\pipeline\04_build_link_dimension.py
python src\pipeline\05_build_speed_fact.py

python src\11_evaluate_speed_model.py --spatial-folds 5 --n-estimators 200

# 예: 2026-07-16 08:00 서울 전 링크 예측
python src\routing\12_build_all_link_weather_snapshot.py --tm 202607160800
python src\routing\13_predict_all_link_speed.py --tm 202607160800
python src\15_add_energy_cost.py --tm 202607160800

python -m nbconvert --to notebook --execute --inplace notebooks\10_eda_report.ipynb
python -m nbconvert --to notebook --execute --inplace notebooks\11_speed_model_baseline.ipynb
```


가상환경을 활성화하지 않고 실행할 때:

```bat
.venv\Scripts\python.exe src\pipeline\05_build_speed_fact.py
```

KMA 레이더 한 시각만 받을 때:

```bat
python src\pipeline\03_fetch_kma_radar.py --tm 202607070300
```

## Notes

- T-data API 수집 코드는 사용하지 않습니다(현재는 T-data 자체를 파이프라인에서 쓰지 않고, 5분 단위 전국 교통소통 데이터로 대체했습니다).
- `data/raw/` 아래 원본 데이터는 직접 받은 파일이므로 코드에서 수정하지 않는 것을 원칙으로 합니다.
- 5분 단위 원본은 하루치가 약 7GB(전국 단위)라 `src/pipeline/02_aggregate_5min_speed.py`가 서울 링크만 걸러 1시간 단위로 압축합니다. 원본 용량 때문에 `data/raw/traffic/202607_5Min/`에는 보통 최근 받은 날짜만 남아있는데, 02번은 실행할 때마다 기존 `seoul_link_speed_5min_hourly.csv`를 읽어 지금 폴더에 없는 과거 날짜는 보존하고 폴더에 있는 날짜만 새로 반영합니다 — 새 날짜를 추가하려면 그 날짜 파일만 폴더에 넣고 02번을 다시 실행하면 됩니다.
- Model B의 공간 일반화 평가는 관측 링크 일부를 통째로 제외하는 방식입니다. 실제 미관측 29.25% 링크에는 정답 속도가 없으므로 그 구간의 정확도를 직접 측정한 결과는 아닙니다.
- 현재 전 링크 출력으로 연결된 서울 도로망의 경로탐색 입력은 만들 수 있지만, 최소시간·최소에너지 라우팅 로직 자체는 별도 단계입니다.
- 서울 링크 추출 기준(bbox → 행정경계), 속도 데이터 매칭 방식과 그 배경, 캐시 무효화 시 주의사항 등은 모두 [data/README.md](data/README.md)에 정리되어 있습니다.
