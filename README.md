# Seoul Traffic Data Analysis

서울시 도로 네트워크를 기반으로 링크별 교통 속도, 지형, 강수 피처를 결합해 경로 탐색 및 교통 분석에 활용하기 위한 프로젝트입니다.

## Project Structure

```text
.
├── traffic_data/
│   ├── MOCT_LINK.*                  # ITS 표준 링크 Shapefile 원본
│   ├── MOCT_NODE.*                  # ITS 표준 노드 Shapefile 원본
│   ├── MULTILINK.dbf                # 복합 링크 속성
│   ├── TURNINFO.dbf                 # 회전 제한/회전 정보
│   ├── seoul_link.*                 # 서울 bbox 기준으로 추출한 링크 Shapefile
│   ├── seoul_link_attr.csv          # 서울 링크 속성 CSV
│   ├── inspect_network_schema.py    # 원본 링크 데이터 스키마 확인
│   ├── extract_seoul_links.py       # 서울 링크 추출
│   ├── summarize_seoul_links.py     # 서울 링크 기초 통계 확인
│   ├── fetch_tdata_link_speed.py    # T-data 링크 속도 API 수집
│   ├── raw/                         # T-data 원본 응답 저장
│   └── processed/                   # T-data CSV 변환 결과 저장
└── README.md
```

## Data Sources

| Data | Description | Usage |
| --- | --- | --- |
| `MOCT_LINK` | 도로 링크 geometry와 속성 | 도로망 그래프의 edge |
| `MOCT_NODE` | 도로 노드 geometry와 속성 | 도로망 그래프의 node |
| T-data 링크 소통정보 | 시간대별 링크 평균 속도 | `LINK_ID` 기준 속도 결합 |
| `DEM.tif` | 고도 래스터 데이터 | 링크별 경사도 계산 |
| 레이더강수량 | 시간·공간 강수 데이터 | 링크별 강수 피처 생성 |

## Main Scripts

| File | Description |
| --- | --- |
| `traffic_data/inspect_network_schema.py` | `MOCT_LINK.shp`의 크기, 컬럼명, 좌표계, 샘플 데이터를 출력합니다. |
| `traffic_data/extract_seoul_links.py` | 전국 링크 데이터에서 서울 bbox와 교차하는 링크만 추출합니다. |
| `traffic_data/summarize_seoul_links.py` | 추출된 서울 링크 CSV의 도로 등급, 제한속도, 길이 통계를 확인합니다. |
| `traffic_data/fetch_tdata_link_speed.py` | T-data API에서 링크별 시간대 평균 속도 데이터를 수집하고 CSV로 저장합니다. |

## MOCT_LINK Schema

원본 링크 데이터는 ITS 표준 노드/링크 Shapefile입니다.

| Item | Value |
| --- | --- |
| Source file | `traffic_data/MOCT_LINK.shp` |
| Geometry type | `LINESTRING` |
| Link count | `1,555,158` |
| CRS | `ITRF2000_Central_Belt_60` |
| Unit | metre |

주요 컬럼:

| Column | Meaning | Usage |
| --- | --- | --- |
| `LINK_ID` | 도로 링크 ID | T-data 속도 데이터와 조인 |
| `F_NODE` | 시작 노드 ID | 그래프 edge의 출발 노드 |
| `T_NODE` | 끝 노드 ID | 그래프 edge의 도착 노드 |
| `LANES` | 차로 수 | 교통 속도/용량 피처 |
| `ROAD_RANK` | 도로 등급 | 도로 유형 피처 |
| `ROAD_TYPE` | 도로 유형 | 도로 유형 피처 |
| `ROAD_NAME` | 도로명 | 해석 및 시각화 |
| `MAX_SPD` | 제한속도 | 속도 기준 피처 |
| `LENGTH` | 링크 길이 | 통행시간, 비용 계산 |
| `geometry` | 링크 선형 좌표 | 지도 시각화, DEM 샘플링 |

## T-data Link Speed Schema

T-data API 응답은 링크별 시간대 평균 속도 정보를 포함합니다.

| Column | Meaning | Usage |
| --- | --- | --- |
| `stndDt` | 기준일 | 날짜 기준 결합 |
| `timeCd` | 시간 코드 | 시간대 구분 |
| `timeNm` | 시간명 | 시간대 라벨 |
| `linkId` | 링크 ID | `MOCT_LINK.LINK_ID`와 조인 |
| `avgSpd` | 평균 속도 | 경로 비용 및 예측 타깃/피처 |
| `roadDivCd` | 도로 구분 코드 | 도로 유형 피처 |
| `roadDivNm` | 도로 구분명 | 해석용 도로 유형 |
| `axisCd` | 축 코드 | 도로축 구분 |
| `axisDirDivNm` | 방향명 | 상행/하행 구분 |
| `stNodeNm` | 시작 지점명 | 해석 및 검증 |
| `edNodeNm` | 종료 지점명 | 해석 및 검증 |

## Generated Data

| File | Description |
| --- | --- |
| `traffic_data/seoul_link.shp` | 서울 bbox 기준으로 추출한 링크 geometry |
| `traffic_data/seoul_link_attr.csv` | 서울 링크 속성 테이블 |
| `traffic_data/raw/topis_link_speed_*.txt` | T-data API 원본 응답 |
| `traffic_data/processed/topis_link_speed_*.csv` | T-data 응답을 CSV로 변환한 파일 |

## Workflow

1. `MOCT_LINK`, `MOCT_NODE`로 도로망 그래프를 구성합니다.
2. 서울시 분석 범위에 맞게 링크를 추출합니다.
3. T-data 링크 소통정보를 `LINK_ID`/`linkId` 기준으로 결합합니다.
4. DEM 고도 데이터에서 링크별 고도와 경사도를 계산합니다.
5. 레이더강수량을 시간·공간 기준으로 링크에 매칭합니다.
6. 거리, 속도, 경사도, 강수량을 반영해 경로 탐색 또는 예측 모델에 활용합니다.

## Run

가상환경 활성화:

```bat
.venv\Scripts\activate.bat
```

링크 데이터 스키마 확인:

```bat
cd traffic_data
python inspect_network_schema.py
```

서울 링크 추출:

```bat
python extract_seoul_links.py
```

서울 링크 기초 통계:

```bat
python summarize_seoul_links.py
```

T-data 링크 속도 수집:

```bat
python fetch_tdata_link_speed.py
```

API 키는 `traffic_data/api_key.txt`에 저장합니다. 이 파일은 저장소에 포함하지 않습니다.
