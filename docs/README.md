# 분석 문서 안내

이 폴더의 문서는 현재 저장소와 실제 생성된 산출물을 기준으로 다시 점검한 **보고서 작성용 기준 문서**입니다. 루트 `README.md`는 빠른 실행 안내, `data/README.md`는 데이터 사전, 아래 문서는 연구 설계와 해석을 담당합니다.

## 먼저 읽을 문서

1. [DATA_ANALYSIS_REPORT.md](DATA_ANALYSIS_REPORT.md): 보고서 본문 초안. 문제 정의, 데이터, 방법론, 결과, 한계, 결론 순서로 읽습니다.
2. [METHODS_AND_PIPELINE.md](METHODS_AND_PIPELINE.md): 모든 공식 코드의 입력·처리·출력과 재현 순서를 설명합니다.
3. [NOTEBOOK_AUDIT.md](NOTEBOOK_AUDIT.md): `01_*`, `02_*`, `03_*`, `04_*` 노트북의 역할, 실험 결과, 현재 배포 코드와의 차이를 정리합니다.
4. [EDA_GUIDE.md](EDA_GUIDE.md): EDA 그림별 사용 데이터, 축, 읽는 법, 보고서에서 할 수 있는 주장과 하면 안 되는 주장을 정리합니다.
5. 각 그림 폴더의 `README.md`: 개별 PNG를 빠르게 찾을 때 사용합니다.
6. [TRANSIT_MAEUL_BUS.md](TRANSIT_MAEUL_BUS.md): 마을버스 탄소·교통약자 분석(`src/transit/`), 차량별 에너지 모델, 실행 순서를 설명합니다.
7. [TRANSIT_REPORT_OUTLINE.md](TRANSIT_REPORT_OUTLINE.md): 마을버스 분석 보고서(5쪽) 구성안. 항목별 계산 방법, 결과, 숫자 출처 파일을 정리합니다.
8. [report/maeul_bus_report.md](report/maeul_bus_report.md): 마을버스 분석 보고서 본문(공모전 제출용 원고)과 그림(`report/images/`, `src/transit/report_figures.py`로 생성).

기본 공간 그림은 [서울 전 도로망 실루엣](figures/network/01_seoul_all_links_silhouette.png)입니다.

## 반드시 구분할 네 가지 값

| 이름 | 의미 | 정답 여부 |
| --- | --- | --- |
| A-Observed | `seoul_link_speed_fact.csv`의 해당 날짜·시간 실제 5분 관측을 1시간 평균한 `평균속도` | 속도 분석의 관측값 |
| A lookup | 관측 링크의 과거 자료를 `LINK_ID × 시간코드 × 평일/주말`로 평균한 `pred_speed` | 관측 이력 기반 예측값. 해당 시점의 정답은 아님 |
| B/C prediction | 관측되지 않은 링크를 XGBoost로 채운 `speed_kmh` | 모델 예측값 |
| Energy estimate | 속도·길이·경사도를 VT-CPEM 근사식에 넣어 계산한 값 | 차량에서 계측한 전력이 아니라 물리모델 추정값 |

## 현재 분석 범위

- 기간: 2026-07-07 01:00부터 2026-07-20 23:00까지
- 제외: 2026-07-07 00:00(공통 입력인 레이더 강수 원본 없음)
- 시점 수: `14일 × 24시간 - 1 = 335`
- 전체 도로 링크: 63,548개
- A 관측 이력 링크: 44,960개
- 현재 전 링크 출력의 계층: A 44,960개, B 16,752개, C 1,836개
- 전 링크 속도 및 에너지 링크-시간 행: `63,548 × 335 = 21,288,580`
- A 실제 관측속도 기반 에너지 행: 15,049,459개

## 라우팅 상태를 읽는 법

최단거리·최단시간·에너지최소 경로 비교는 과거에 실행되었습니다. 다만 사용자 요청에 따른 정리 과정에서 당시의 `src/routing/13·15·16`과 `route_scenario_summary.csv`가 현재 작업 트리에서는 제거되었습니다. 따라서 다음 두 문장은 동시에 참입니다.

- **분석 이력:** 링크별 에너지 비용을 사용한 경로 비교는 수행되었다.
- **현재 재현성:** 당시 사용한 `src/routing/16_eco_route.py`와 `route_scenario_summary.csv`는 현재 트리에 없지만, 같은 비교는 `src/routing/engine.py`(Dijkstra) + `01_route_compare.py`/`02_evaluate_route_scenarios.py`로 재현 가능하다. 대표 30개 OD 기준 무제약 최소에너지 경로는 평균 12.389% 에너지 절감(시간 +20.256%), 15% 지연 상한 균형경로는 평균 8.294% 절감(시간 +8.152%)이다.

과거 `experiments/eco_routing.py`·`experiments/eco_routes.csv`(내연기관 근사 실험)는 공식 코드에서 참조되지 않아 저장소에서 삭제했다.
