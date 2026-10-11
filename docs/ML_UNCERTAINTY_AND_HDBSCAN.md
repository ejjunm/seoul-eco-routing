# ML 불확실성·HDBSCAN 실험

## 한 줄 결론

- 속도 모델의 90% 분위수 구간을 split conformal로 보정할 수 있다. 완전히 분리된 시험 링크에서 실제 포함률은 92.7%였다.
- 그 구간을 노선 에너지·탄소에 보수적으로 전달하면 230개 노선 중 100개만 기존 4분류가 유지되고 130개는 탄소효율 중앙값 경계에 걸린다.
- HDBSCAN은 현재 10개 노선 변수에서 안정적인 자연 군집을 찾지 못했다. 이것은 실패가 아니라, 기존 4유형을 “데이터가 스스로 만든 네 유형”이라고 주장하면 안 된다는 진단이다.

## 1. 분위수 XGBoost + conformal

실행:

```powershell
python src/models/05_build_speed_uncertainty.py
python src/transit/12_route_carbon_uncertainty.py
```

설계:

1. 관측 링크를 train 60%, calibration 20%, test 20% 풀로 먼저 나눈다.
2. 같은 링크의 다른 날짜·시간이 서로 다른 split에 들어가지 않게 한다.
3. 이웃 속도도 train 링크에서만 만들기 때문에 calibration/test 정답이 피처로 새지 않는다.
4. XGBoost `reg:quantileerror`로 5·50·95 분위수를 동시에 학습한다.
5. calibration의 CQR 비적합도 점수로 B/C tier를 따로 보정한다.
6. 마지막 test 링크는 모델 선택과 보정에 한 번도 쓰지 않고 커버리지를 평가한다.

현재 실행 결과(기본 1,200/350/350 링크 표본):

| 대상 | 시험 행 | 중앙값 MAE | 원시 포함률 | 보정 포함률 | 보정 평균 폭 |
|---|---:|---:|---:|---:|---:|
| 전체 | 117,600 | 5.11 km/h | 88.9% | 92.7% | 26.93 km/h |
| B 이웃모델 | 116,256 | 5.11 km/h | 88.9% | 92.8% | 26.98 km/h |
| C 정적모델 | 1,344 | 5.23 km/h | 89.7% | 90.6% | 23.29 km/h |

목표 90%보다 보정 포함률이 높아 과소포착 문제는 줄었지만 구간이 넓다. “정확한 한 값”보다 “미관측 링크에서는 이만큼 흔들릴 수 있다”는 표현이 맞다. 시간 행들은 같은 링크 안에서 상관되어 있으므로 92.7%를 모든 미래 상황에 대한 엄밀한 보장으로 확대 해석하지 않는다.

노선 전달은 test 링크의 tier×시간대별 구간 폭 중앙값을 기존 속도 프로필로 옮긴 뒤, VT-CPEM을 속도 하한·중앙·상한에서 다시 계산한다. 모든 링크 끝점을 함께 합산하므로 결과는 **보수적 민감도 범위**이며 노선 단위 90% 확률구간은 아니다.

현재 노선 결과:

- 4분류 유지: 100/230개
- 탄소효율 경계로 분류가 바뀔 수 있음: 130/230개
- 속도 범위 전체에서 승용차보다 버스 우위: 192개
- 승용차 비교 경계/불확실: 33개
- 속도 범위 전체에서 승용차 우위: 5개

산출물:

- `src/models/artifacts/speed_quantile_conformal.pkl`
- `data/processed/model_uncertainty/metrics.json`
- `data/processed/model_uncertainty/test_predictions.csv`
- `data/processed/transit/route_carbon_uncertainty.csv`
- `data/processed/transit/route_carbon_uncertainty_summary.json`

## 2. HDBSCAN

실행:

```powershell
python src/transit/11_route_typology_hdbscan.py
```

`min_cluster_size`, `min_samples`, EOM/leaf를 바꿔가며 다음 조건을 동시에 확인한다.

- 2개 이상 군집
- 전체 노선의 50% 이상을 군집으로 설명
- 최소 군집 5개 이상
- 군집 내부 실루엣
- 80% 부분표본 재학습 ARI 안정성
- 평균 소속 확률

어떤 설정도 위 최소 조건을 통과하지 못했다. 가장 많은 노선을 설명하는 진단용 해는 2개 군집, 102개 소속, 128개(55.7%) 비정형/경계였고, 군집 실루엣 0.138, 부분표본 ARI 중앙값 0.0이었다. 정책 4분류와의 ARI도 0.015로 사실상 무관하다.

따라서 발표에서는 HDBSCAN을 새로운 확정 유형으로 쓰기보다 다음처럼 쓰는 편이 안전하다.

> 밀도기반 군집을 추가 검증했으나 안정적인 자연 군집은 확인되지 않았다. 이에 4분류는 자연 군집이 아니라 탄소효율과 교통약자 의존도를 명시적으로 교차한 정책 의사결정 프레임으로 해석한다.

산출물:

- `data/processed/transit/route_typology_hdbscan.csv`
- `data/processed/transit/hdbscan_profile.csv`
- `data/processed/transit/hdbscan_sensitivity.csv`
- `data/processed/transit/hdbscan_summary.json`

## 3. 물리모델 + ML 잔차보정용 외부 데이터

가장 적합한 공개 원자료는 ETH Zurich의 **ZTBus**다.

- 공식 저장소: https://doi.org/10.3929/ethz-b-000626723
- 2019-04-30~2022-12-11, 1,000회가 넘는 실제 운행 mission
- 동기화된 차량 총 전력수요, 속도/주행계, GNSS 위치·고도, 외기온, 문 열림, 승객 수, 노선·배차 정보
- 전체 압축본 약 1.9GB, 작은 sample 약 84MB, CC BY 4.0

권장 잔차 타깃:

```text
잔차 Wh = 실측 electric_powerDemand 적분값 - 현재 VT-CPEM 계산 Wh
```

권장 피처는 속도, 가속도, 경사, 정차·문 열림, 외기온, 승객 수, 시간대다. split은 행 무작위가 아니라 mission/날짜/차량 단위로 해야 한다. XGBoost가 잔차를 예측하고 최종값을 `물리식 + 예측 잔차`로 만들며, 마지막에 mission 단위 conformal 구간을 붙이는 순서가 적합하다.

한계도 크다. ZTBus는 취리히의 대형 배터리 트롤리버스 2대라 서울의 카운티 일렉트릭과 질량·공조·구동계·도로환경이 다르다. 따라서 절대 kWh/km를 그대로 서울에 이식하면 안 되고, 잔차 구조 사전학습·방법 검증용으로 쓴 뒤 국내 중형 전기버스의 충전량/SOC/주행거리 자료로 마지막 보정을 해야 한다.

보조 후보:

- NREL Fleet DNA: 미국 시내버스 19대·472일의 실제 운행 데이터 요약/도구. 주행 사이클 검증에는 좋지만 공개 화면만으로는 ZTBus만큼 세밀한 전력 시계열 접근이 분명하지 않다.
- 중국 7개 도시 EV 데이터: 버스 충전전력·일주행거리의 집계 통계는 있으나 원시 운행 시계열이 아니라 잔차학습 주자료로는 부족하다.

국내 공개 포털에서는 버스 위치·도착·운행횟수, 충전소 상태, 차종별 주행거리 통계는 확인되지만, 노선 주행과 동기화된 버스별 SOC·충전 kWh·구동전력 원자료는 찾지 못했다. 최종 국내 보정에는 서울시/운수사/충전사업자 협조 자료가 필요하다.
