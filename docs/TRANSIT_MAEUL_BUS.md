# 마을버스 탄소·교통약자 분석 (`src/transit/`)

기존 에코라우팅(A/B/C 속도 모델 + VT-CPEM 에너지)을 마을버스 분석으로 확장한 단계입니다.

- 서울 마을버스 226개 노선을 실제 경로(서울시 버스 API)로 도로망에 붙이고, AI 속도·경사로 노선별 에너지를 계산합니다.
- 같은 길·같은 시간대에서 **승객 1명·1km당 탄소**를 마을버스와 승용차로 비교합니다. 버스와 승용차 모두 2026년 서울의 실제 연료 구성을 반영합니다.
- 교통약자(고령 생활인구, 대체수단 없는 정류장) 의존도와 탄소 효율로 노선을 네 칸으로 분류합니다.

## 실행 방법

이 단계의 입력 데이터는 저장소 원칙대로 Git에 올리지 않았습니다. 별도로 전달받은 데이터 압축 파일을 **저장소 루트에 풀면** 아래 경로에 파일이 놓입니다(목록은 [데이터](#데이터) 참고).

```powershell
# 패키지 (shapely는 2.x 필요)
pip install pandas numpy geopandas shapely scipy pyarrow openpyxl polars

# 테스트 (10개 통과)
python -m unittest tests.test_link_energy

# 마을버스 분석 — 이 순서대로. 05는 06 결과를 쓰므로 06 다음
python src/transit/01_build_bus_route_links.py
python src/transit/02_build_route_demand.py
python src/transit/03_build_route_feasibility.py
python src/transit/04_build_route_energy.py
python src/transit/06_build_route_carbon_breakeven.py
python src/transit/05_classify_route_priority.py
```

결과는 `data/processed/transit/`에 저장됩니다.

**00(노선 실제 경로 수집)**은 `data/raw/traffic/bus_route_path/route_paths.csv`가 있으면 실행하지 않아도 됩니다. 다시 받으려면 서울시 버스운행정보 API 인증키가 필요합니다. 키는 코드나 문서에 적지 말고 환경변수로만 넣습니다.

```powershell
$env:SEOUL_BUS_API_KEY = "<인증키>"
python src/transit/00_fetch_bus_route_paths.py   # 약 2분, 237개 노선, 노선마다 최대 3회 재시도
```

### 캐시 두 개

| 캐시 파일 | 없을 때 필요한 것 |
|---|---|
| `data/processed/transit/grid_population_daytime.csv` | 02가 생활인구 원자료(`data/raw/traffic/250_LOCAL_RESD_202607/` 약 780MB, `250_LOCAL_RESD_ADMDONG_202607/`, `match/`)로 새로 계산. 원자료가 없고 이 파일이 있으면 그대로 사용 |
| `data/processed/transit/link_speed_weekday_profile.parquet` | 03이 전 링크 속도 예측 CSV 335개(`data/processed/all_link_speed_prediction_*.csv`, 2.8GB)로 새로 계산. 예측 CSV는 `python src/models/04_batch_predict_all_link_speed.py --start-date 20260707 --end-date 20260720`로 생성(약 1시간) |

## 단계별 역할

| 순서 | 파일 | 하는 일 | 주요 산출물 |
|---|---|---|---|
| 00 | `00_fetch_bus_route_paths.py` | 서울시 버스 API(getRoutePath)로 마을버스·자율주행 노선의 실제 경로 좌표 수집 | `data/raw/traffic/bus_route_path/route_paths.csv` |
| 01 | `01_build_bus_route_links.py` | 실제 경로를 표준노드링크에 맵매칭(진행 방향 일치 링크 우선, 한 방향만 그려진 골목은 역방향 통과 허용). 노선 길이·정류장 구간 길이는 실제 경로선에서 측정(정류장 순서를 지키는 동적 계획법 배치). 정류장별 지하철역·일반버스 접근성 | `routes.csv`, `route_links.csv`, `route_segments.csv`, `bus_stops.csv` |
| 02 | `02_build_route_demand.py` | 7월 승하차, 정류장 300m 안 평일 낮 고령 생활인구(격자 총인구 × 행정동 65세 이상 비율), 대체수단 없는 정류장의 승차 비중 | `route_demand.csv`, `stop_ridership.csv` |
| 03 | `03_build_route_feasibility.py` | 평일 시간대별 전 링크 속도 프로필(04~06이 사용) + 자율주행 시범노선 대비 도로 조건(현재 참고용) | `link_speed_weekday_profile.parquet`, `route_feasibility.csv` |
| 04 | `04_build_route_energy.py` | 전기 중형 마을버스(카운티 일렉트릭) 노선별 에너지. 질량·냉방 시나리오 포함 | `route_energy.csv` |
| 06 | `06_build_route_carbon_breakeven.py` | 정류장 순서대로 누적한 구간별 승객 수 → 승객·km, TOPIS 실제 운행횟수 → 평균 탑승 인원, 버스·승용차 승객 1명당 탄소, 손익분기, 증편 1회 손익분기 | `route_carbon_breakeven.csv` |
| 05 | `05_classify_route_priority.py` | 탄소 효율(노선 간 상대) × 교통약자 의존도 네 칸 분류, 15인승급 소형 전기차 시나리오 | `route_priority.csv` |

참고: `src/routing/03_compare_ev_ice_routes.py`는 같은 속도 입력에서 전기차·휘발유차 에코라우팅 효과를 비교합니다(보고서 본문에는 쓰지 않음).

## 차량별 에너지 모델

모든 차량이 **같은 노선, 같은 평일 시간대 속도(AI 모델), 같은 경사**로 계산됩니다. 각 모델은 공인 시험주기 값(또는 서울 실측)으로 보정해서 정지·출발 소비를 같은 기준으로 반영합니다.

| 차량 | 모델 | 보정 근거(대표 차종 공개 제원) | 코드 |
|---|---|---|---|
| 휘발유 승용차 | VT-CPFM 계열 연료 모델(Rakha et al. 2011). 연료율 = 기본 연료율 + 엔진 출력 / (효율 × 발열량) | 쏘나타 디 엣지 2.0(17인치): 1,475kg, 도심 11.2·고속 14.8km/L | `src/energy/ice_fuel.py` |
| 경유 승용차 | 〃 | 쏘렌토 2.2 디젤 2WD: 1,815kg, 도심 12.7·고속 17.0km/L | 〃 |
| LPG 승용차 | 〃 | 쏘나타 디 엣지 LPi 2.0: 1,475kg, 도심 8.3·고속 11.7km/L | 〃 |
| 하이브리드 승용차 | Ahn & Rakha(2019) HEV 모델. 32km/h·10kW 미만은 전기 모드(충전 유지형이라 엔진이 나중에 채우는 연료 반영), 그 외 엔진 모드 2차식(Prius 계수) | 쏘나타 디 엣지 하이브리드(18인치): 1,585kg, 도심 16.8·고속 17.4km/L | `src/energy/hev_fuel.py` |
| 전기 승용차 | VT-CPEM(Fiori et al. 2016) | 아이오닉5 롱레인지 2WD: 2,015kg, 도심 5.8·고속 4.6km/kWh. 공기저항계수·부가 전력 역산 | `src/energy/ev_calibration.py` |
| 전기 마을버스(중형) | VT-CPEM | 카운티 일렉트릭: 배터리 128kWh, 73km/h 정속 338km, 복합 303km. 질량 7t, 냉방 5kW | `src/transit/04_build_route_energy.py` |
| 경유·CNG 마을버스(중형) | 전기버스 모델값 × 서울 실측 비율 | 서울 시내버스 노선 같은 주행 패턴에서 전기 1.43kWh/km, 경유 723g, CNG 721gCO2/km(전기전자학회논문지 24(3), 2020) | `src/energy/bus_fuel.py` |

- **경유·CNG 버스에 전용 모델(VT-CPFM 버스·CNG 버전)을 쓰지 않은 이유**: 그 계수는 초 단위 가감속을 입력으로 보정되어 있어, 링크 정속 근사에 넣으면 정류장 정지·출발 연료가 빠져 버스가 과소 추정됩니다(시험 결과 7t 경유버스가 1.5t 승용차와 비슷하게 나옴). 그래서 같은 노선 조건의 서울 실측 비율로 환산했습니다.
- **탄소 계수**: 전력 0.4173kgCO2/kWh(국가 전력배출계수 2023년도, 2025.12 공표), 휘발유 2.29·경유 2.66kg/L(캐나다 천연자원부), LPG 1.68kg/L(IPCC 기본 배출계수 × 부탄 발열량).
- **가중 비율**: 승용차는 서울 2026년 7월 등록(휘발유 57.4%, 경유 20.1%, 하이브리드 12.7%, LPG 6.0%, 전기·수소 3.9%), 마을버스는 서울 2026년 1월 현황(CNG 885, 경유 344, 전기 397대). 승용차 탑승 인원 1.2명.
- **마을버스 크기는 중형(카운티)으로 고정**했습니다. 실제 서울 마을버스는 대형 76%·중형 24%입니다.

## 데이터

Git에는 올리지 않습니다. 압축 파일로 따로 전달합니다.

### 깃에 없는 기존 파일(실행에 필요)

| 파일 | 쓰는 곳 |
|---|---|
| `data/interim/seoul_link.shp`(+ `.shx` `.dbf` `.prj` `.cpg`) | 01: 도로 형상 |
| `data/processed/seoul_link_dimension.csv` | 01, 03, 04, 05, 06: 링크 속성·경사 |

### 새로 받은 원자료(`data/raw/traffic/`)

| 파일 | 출처 | 사용 |
|---|---|---|
| `서울시버스노선별정류소정보(20260902).xlsx` | 서울 열린데이터광장 OA-1095 | 노선별 정류장 순서·좌표 |
| `bus_route_path/route_paths.csv` | 서울시 버스운행정보 API getRoutePath(00) | 노선 실제 경로 |
| `2026년_버스노선별_정류장별_시간대별_승하차_인원_정보(07월).csv` | OA-12913 | 승하차(분석 기간과 같은 7월) |
| `bus_trips/tpss_sta_route_hturn_2026.07.*.csv` | OA-21220(TOPIS 원천) | 노선·정류장별 일별 운행횟수 |
| `서울시 역사마스터 정보.csv` | OA-21232 | 지하철역 좌표 |
| `vehicle_registration/seoul_fuel_registration_202607.csv` | OA-15640 | 서울 승용차 연료별 등록(2026년 7월) |
| `통행속도 노선 통계.csv` | 서울 버스정보 | 노선유형별·시간대별 버스 실제 속도(2026.10.6~8). AI 속도 검증용, 아직 코드 미반영 |

## 현재 주요 결과(마을버스 노선 중앙값·합계)

| 항목 | 값 |
|---|---|
| 1km당 CO2 | 승용차: 휘발유 404, 경유 413, LPG 402, 하이브리드 204, 전기 132 → 현재 구성 370g / 마을버스: 전기 437, 경유 530, CNG 529 → 현재 구성 507g |
| 마을버스가 승용차보다 나으려면 평균 탑승 | 약 1.7명 |
| 승용차보다 승객 1명당 탄소가 적은 노선 | 201 / 212 |
| 같은 이동을 승용차로 했을 때 대비 감축 | 하루 약 302톤(연 약 11만 톤) |
| 증편 1회가 손해 보지 않으려면 승용차에서 넘어와야 할 승객 | 약 10명 |
| 마을버스 전부 전기로 바꿀 때 | 하루 −15톤(−14%, 현재 전력 배출계수 기준) |
| 소형 전기차(15인승급) 대 전기 마을버스(1km당, 정지·출발 부가 전력을 질량 비례로 동일 적용) | 268g 대 480g |
| 네 칸 분류 | 증편·지원 우선 57 / 소형 차량 전환 49 / 현행 유지 49 / 노선 조정 검토 57개 |

## 알려진 한계

- 노선별로 어떤 연료·크기의 버스가 다니는지 몰라 서울 전체 구성을 모든 노선에 적용했고, 크기는 중형으로 고정했습니다.
- 승용차의 골목 속도(15~20km/h) 연료는 공인 시험주기(평균 34km/h) 보정을 저속으로 늘려 적용한 값이라 높게 잡혔을 수 있습니다(쏘나타 약 5.7km/L).
- 정류장 순서(9월)와 승하차(7월) 시점 차이로 14개 노선은 승객 계산에서 제외했습니다.
- 링크 안은 일정 속도로 달린다고 가정했고, 회생제동은 반영하지 않았습니다.
