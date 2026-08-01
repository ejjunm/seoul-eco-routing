# Seoul Eco Routing

서울시 도로 링크, ITS 5분 단위 교통소통 데이터, DEM 고도, KMA 레이더 강수량을 결합해 링크별 속도·지형·기상 피처를 만드는 프로젝트입니다.

현재 속도 데이터는 ITS 국가교통정보센터 계열의 5분 단위 전국 교통소통 원본(하루 약 1.7억 행)을 서울 표준노드링크 LINK_ID 기준으로 걸러 1시간 단위로 집계해 사용합니다(과거에 쓰던 T-data 1시간 소통정보 + 공식 매핑 테이블 방식은 커버리지가 낮아 대체했습니다 — 배경은 [data/README.md](data/README.md) 참고). KMA 레이더 강수량은 API로 내려받아 시간·공간 기준으로 링크에 매칭합니다.

데이터 스키마, 매칭 방식의 배경과 검증 과정, 현재 결과 수치 등 세부 내용은 **[data/README.md](data/README.md)**를 참고하세요.

## Project Structure

```text
.
├── src/
│   ├── 01_inspect_network_schema.py
│   ├── 02_extract_seoul_links.py
│   ├── 03_summarize_seoul_links.py
│   ├── 04_aggregate_5min_speed.py
│   ├── 05_merge_5min_link_speed.py
│   ├── 06_analyze_matched_links.py
│   ├── 07_plot_matched_links_map.py
│   ├── 08_add_dem_features.py
│   ├── 09_fetch_kma_radar.py
│   └── 10_add_radar_precip_features.py
├── notebooks/
│   ├── 10_eda_report.ipynb        # 주의: 재정비 필요, 아래 Notebooks 참고
│   └── 11_speed_model_baseline.ipynb  # 주의: 재정비 필요, 아래 Notebooks 참고
├── data/
│   ├── README.md       # 데이터 스키마/매칭 방식/결과 상세 문서
│   ├── raw/
│   │   ├── road/       # MOCT_LINK.*, MOCT_NODE.*, MULTILINK.dbf, TURNINFO.dbf
│   │   ├── boundary/   # seoul_admin_boundary.geojson (서울 25개 자치구 경계)
│   │   ├── traffic/    # 5분 단위 전국 교통소통 원본(202607_5Min/*.csv) 등
│   │   ├── dem/        # 37608.img, 37612.img, 37705.img, 37709.img
│   │   └── weather/    # KMA key, HSR grid, radar raw files
│   ├── interim/        # seoul_link.*
│   └── processed/      # generated CSV/GeoJSON/PNG/NPZ outputs
├── docs/
│   └── figures/
│       ├── eda/       # 10번 노트북이 생성하는 보고서용 EDA 그래프
│       └── model/     # 11번 노트북이 생성하는 속도 예측 모델 그래프
└── README.md
```

`data/raw/`, `data/interim/`, `data/processed/`의 실제 데이터 파일은 대용량 원본/중간/가공 데이터이므로 Git에 올리지 않습니다. 대신 각 폴더에는 `.gitkeep`을 두어 필요한 폴더 구조만 GitHub에 표시합니다. 예외적으로 `data/raw/boundary/seoul_admin_boundary.geojson`은 크기가 작은 정적 참조 데이터라 커밋합니다(자세한 내용은 [data/README.md](data/README.md) 참고).

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

`src/`의 파일명 앞 번호는 실행 순서(파이프라인 순서)를 나타냅니다.

| Script | Description |
| --- | --- |
| `01_inspect_network_schema.py` | `MOCT_LINK.shp`의 크기, 컬럼, 좌표계 확인 |
| `02_extract_seoul_links.py` | 서울 행정경계(25개 자치구) 기준 링크를 추출해 `seoul_link.*`, `seoul_link_attr.csv` 생성 |
| `03_summarize_seoul_links.py` | 서울 링크 속성 기초 통계 출력 |
| `04_aggregate_5min_speed.py` | 5분 단위 전국 교통소통 원본(하루 약 1.7억 행)에서 서울 링크만 걸러 1시간 단위로 집계 |
| `05_merge_5min_link_speed.py` | 04번 결과를 서울 링크 속성과 결합 |
| `06_analyze_matched_links.py` | 매칭률, 도로등급별 커버리지, 연결 컴포넌트 분석 |
| `07_plot_matched_links_map.py` | 매칭 링크 지도 이미지와 GeoJSON 생성 |
| `08_add_dem_features.py` | DEM에서 링크별 고도/경사도 피처 생성 |
| `09_fetch_kma_radar.py` | KMA HSR 격자와 1시간 누적 레이더 강수량 다운로드 |
| `10_add_radar_precip_features.py` | 레이더 강수량을 링크·시간 기준으로 결합 (최종 산출물) |

이전 T-data+공식매핑 방식에서 5분 데이터 방식으로 왜 바꿨는지, 매칭 방법이 어떻게 검증됐는지는 [data/README.md의 "속도 데이터 매칭"](data/README.md#속도-데이터-매칭)에 자세히 정리되어 있습니다.

## Notebooks

| Notebook | Description |
| --- | --- |
| `10_eda_report.ipynb` | 최종 결합 테이블을 입력으로 강수량·경사도·도로등급·첨두시간대별 평균속도 EDA 테이블과 차트를 생성하는 리포트 |
| `11_speed_model_baseline.ipynb` | 최종 결합 테이블의 원본 컬럼만으로 링크 평균속도를 예측하는 LightGBM 베이스라인 |

**주의**: 두 노트북 모두 예전 T-data 기반 컬럼(`도로방향구분코드`, `도로구분코드`, `요일코드`, `요일그룹코드`, `첨두시구분`, `도로명`, `시작노드명`/`종료노드명`, `broadcast_source_count` 등)을 참조합니다. 5분 데이터 기반 파이프라인으로 바뀌면서 이 컬럼들이 최종 테이블에서 전부 빠졌기 때문에(대신 `sample_count_5min`이 생김), **지금 상태로 재실행하면 오류가 납니다.** `요일`/`첨두시구분`류는 `기준일`/`시간코드`로 직접 계산해서 대체할 수 있지만, `도로구분코드`(TOPIS 자체 간선/이면 분류)는 5분 데이터에 대응 정보가 없어 복원이 안 됩니다. 재실행 전에 두 노트북의 피처 목록을 새 스키마에 맞게 다시 정비해야 합니다.

노트북을 실행하려면:

```bat
jupyter lab notebooks\10_eda_report.ipynb
```

또는 커널 없이 일괄 실행 후 저장하려면:

```bat
python -m nbconvert --to notebook --execute --inplace notebooks\10_eda_report.ipynb
python -m nbconvert --to notebook --execute --inplace notebooks\11_speed_model_baseline.ipynb
```

## Current Results (요약)

```text
서울 링크 수: 63,548
속도 데이터 결합 고유 링크 수: 44,960 (70.75%)
연결 컴포넌트 수: 1,650 | 최대 컴포넌트 링크 비율: 95.28%
DEM 샘플 존재 링크 비율: 100.0%
레이더 강수 결합 완료 시각: 336/336
```

전체 수치, 도로등급별 매칭률, 미매칭 링크 특성은 [data/README.md의 "Current Results"](data/README.md#current-results)를 참고하세요.

## Workflow

```bat
.venv\Scripts\activate.bat

python src\01_inspect_network_schema.py
python src\02_extract_seoul_links.py
python src\03_summarize_seoul_links.py
python src\04_aggregate_5min_speed.py
python src\05_merge_5min_link_speed.py
python src\06_analyze_matched_links.py
python src\07_plot_matched_links_map.py
python src\08_add_dem_features.py
python src\09_fetch_kma_radar.py --grid
python src\09_fetch_kma_radar.py --from-5min-times
python src\10_add_radar_precip_features.py
```

가상환경을 활성화하지 않고 실행할 때:

```bat
.venv\Scripts\python.exe src\10_add_radar_precip_features.py
```

KMA 레이더 한 시각만 받을 때:

```bat
python src\09_fetch_kma_radar.py --tm 202607070300
```

## Notes

- T-data API 수집 코드는 사용하지 않습니다.
- `data/raw/` 아래 원본 데이터는 직접 받은 파일이므로 코드에서 수정하지 않는 것을 원칙으로 합니다.
- 5분 단위 원본은 하루치가 약 7GB(전국 단위)라 `04_aggregate_5min_speed.py`가 서울 링크만 걸러 1시간 단위로 압축합니다. 원본 용량 때문에 `data/raw/traffic/202607_5Min/`에는 보통 최근 받은 날짜만 남아있는데, 04번은 실행할 때마다 기존 `seoul_link_speed_5min_hourly.csv`를 읽어 지금 폴더에 없는 과거 날짜는 보존하고 폴더에 있는 날짜만 새로 반영합니다 — 새 날짜를 추가하려면 그 날짜 파일만 폴더에 넣고 04번을 다시 실행하면 됩니다.
- 서울 링크 추출 기준(bbox → 행정경계), 속도 데이터 매칭 방식과 그 배경, 캐시 무효화 시 주의사항 등은 모두 [data/README.md](data/README.md)에 정리되어 있습니다.
