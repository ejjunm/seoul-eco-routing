# 마을버스 ML·불확실성 발표용 EDA

생성 명령: `python src/eda/06_transit_ml_eda.py`

## 발표 슬라이드 권장 순서

1. `01_executive_summary.png` — 핵심 결과 한 장 요약
2. `02_carbon_dependence_quadrants.png` — 정책 4분류의 구조와 경계 노선
3. `03_route_carbon_interval_forest.png` — 승용차 비교가 확실하지 않은 개별 노선
4. `04_all_route_carbon_uncertainty.png` — 230개 전체 노선의 탄소 민감도
5. `05_classification_transition.png` — 불확실성에 따른 분류 이동
6. `06_speed_conformal_by_hour.png` — 시간대별 conformal 검증
7. `07_speed_error_calibration.png` — 예측 대 실제 및 구간 폭 진단
8. `08_hdbscan_diagnostics.png` — 자연 군집이 안정적이지 않다는 근거
9. `09_route_feature_correlation.png` — 노선 특성 EDA
10. `10_load_carbon_relationship.png` — 낮은 탑승인원이 승객당 탄소를 키우는 관계
11. `11_route_uncertainty_map.png` — 경계 노선의 공간 분포
12. `12_presentation_route_tables.png` — 발표용 대표 노선 표

## 현재 핵심 수치

- 분석 노선: 230개
- 정책 분류 안정: 100개, 경계: 130개
- 속도 민감도 범위 전체에서 버스 우위: 192개
- 승용차 비교 경계: 33개
- 범위 전체에서 승용차 우위: 5개

주의: 노선 탄소 구간은 행 단위 conformal 속도 구간을 전달한 보수적 민감도 범위이며,
노선 단위 90% 확률구간으로 해석하지 않는다.
