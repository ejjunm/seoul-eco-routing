# 에코 라우팅 대시보드 가이드

## 실행

`data/interim/seoul_link.shp`와 `data/processed/historical_hybrid_link_energy/*.parquet`가 있어야 동작합니다. 둘 다 `.gitignore` 대상이라 clone 직후에는 없으므로, 먼저 [README Quickstart](../README.md#quickstart)의 1~4단계를 실행해 만들어야 합니다.

```powershell
uvicorn app.server:app --reload
```

브라우저에서 `http://127.0.0.1:8000`을 열면 됩니다.

## 현재 제공 기능

- 대표 장소 또는 직접 입력한 위도·경도의 출발지/도착지 비교
- 과거 재현(`hybrid`)과 이력 기반 예측(`prediction`) 데이터 구분
- 최단시간, 최소에너지, 최단거리, 시간 제약 균형 에코 경로
- 지도 GeoJSON, 선택 경로 강조, 도로명 기준 구간 안내, 거리·시간·에너지 합계
- 동일 경사에서 35km/h 주행을 기준으로 한 차량당 에너지 비효율 후보와 경사 부담/운영 부담 구분

## 해석 원칙

- `hybrid`는 과거 시점의 A 링크는 실제 5분 관측 평균을 쓰고, B/C는 예측으로 보완합니다.
- `prediction`은 A lookup과 B/C 예측으로 구성되므로 미래 시나리오에 적합하지만 실제 관측값은 아닙니다.
- 비효율 후보는 차량 한 대의 물리모델 추정치입니다. 교통량이 곱해진 사회적 영향도나 정책의 인과 효과로 해석하면 안 됩니다.
- 현재 에너지 모델은 Nissan Leaf, 링크 평균속도 일정, 가속도 0, 회생제동 없음의 가정을 사용합니다.

## API

| 경로 | 역할 |
| --- | --- |
| `GET /api/meta` | 가능한 시점과 대표 장소 |
| `POST /api/routes` | 세 경로와 GeoJSON 비교 |
| `GET /api/hotspots` | 에너지 비효율 후보 |

`POST /api/routes` 요청 예시는 다음과 같습니다.

```json
{
  "tm": "202607160800",
  "dataset": "hybrid",
  "origin": {"lat": 37.4979, "lon": 127.0276},
  "destination": {"lat": 37.5665, "lon": 126.9780},
  "max_time_increase_pct": 15
}
```
