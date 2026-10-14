"""Package added inputs and current code without copying original large datasets."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'output' / 'handoff'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    selected = []
    for folder in ['data/processed/transit_v2/card_partitions',
                   'data/processed/transit_v2/masters',
                   'data/processed/transit_v2/fetch_manifest']:
        selected += sorted((ROOT / folder).glob('*'))
    for name in ['data/raw/maeul_upgrade/aggregates/OA-21220_2608.zip',
                 'data/raw/maeul_upgrade/aggregates/OA-21220_2608.json',
                 'data/processed/transit_v2/official_trip_counts_jul_aug.parquet',
                 'config/maeul_upgrade/scenario.json', 'requirements-upgrade.txt',
                 'src/energy/ev_calibration.py', 'src/energy/link_energy.py',
                 'src/transit/04_build_route_energy.py',
                 'src/transit/06_classify_route_priority.py',
                 'src/transit/10_route_removal_access.py',
                 'tests/test_maeul_upgrade.py',
                 'docs/MAEUL_UPGRADE_IMPLEMENTATION.md',
                 'docs/MAEUL_INTEGRATED_REPORT.md',
                 'docs/report/maeul_bus_integrated_report.md']:
        selected.append(ROOT / name)
    selected += sorted((ROOT / 'src/transit/upgrade').glob('*.py'))
    selected += sorted((ROOT / 'docs/report/images/integrated').glob('*'))
    selected += sorted((ROOT / 'docs/report/metrics/integrated').glob('*'))
    baseline_names = ['routes.csv', 'route_links.csv', 'route_segments.csv',
                      'bus_stops.csv', 'route_demand.csv', 'route_stops.parquet',
                      'grid_population_daytime.csv', 'grid_walk_access.csv',
                      'link_speed_weekday_profile.parquet', 'route_feasibility.csv',
                      'route_priority.csv']
    baseline = [ROOT / 'data/processed/transit' / name for name in baseline_names]
    baseline += [ROOT / 'data/processed/seoul_link_dimension.csv',
                 ROOT / 'data/raw/traffic/2026년_버스노선별_정류장별_시간대별_승하차_인원_정보(07월).csv',
                 ROOT / 'data/raw/traffic/vehicle_registration/seoul_fuel_registration_202607.csv']
    baseline += sorted((ROOT / 'data/interim').glob('seoul_link.*'))
    missing = [str(p) for p in selected + baseline if not p.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    def entry(p):
        return {'path': p.relative_to(ROOT).as_posix(), 'bytes': p.stat().st_size,
                'sha256': digest(p)}
    manifest = {'purpose': 'Additional inputs and local code, not a standalone original-data bundle',
                'service_dates': ['2026-07-06', '2026-08-09'],
                'included': [entry(p) for p in selected],
                'required_existing_inputs_not_included': [entry(p) for p in baseline]}
    manifest_path = DEST / 'maeul_handoff_manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    readme = '''# 친구 전달용: 마을버스 추가 데이터 및 수정 코드

이 ZIP은 기존 프로젝트에 추가하는 패키지입니다. 기존 원자료와 전처리 결과는 포함하지 않습니다.
GitHub의 기존 코드만으로는 새 분석이 재현되지 않으므로 현재 로컬 수정 코드도 포함했습니다.
친구가 수정한 코드가 있다면 먼저 프로젝트를 복사하거나 별도 브랜치에 적용하세요.

## 새로 확보한 핵심 데이터

1. 서울 교통카드 승하차 자료: 실제 이용일 2026-07-06~08-09, 35일.
   출처: https://t-data.seoul.go.kr/dataprovide/trafficdataviewfile.do?data_id=20006
   원본 ZIP 35개(약 17.1GB) 대신, 분석 대상 버스와 필요한 컬럼을 추출한 Parquet를 포함합니다.
   data/processed/transit_v2/card_partitions/ : 35개, 약 290.4MB.
   카드 식별번호 TRCR_ID는 읽거나 저장하지 않았습니다. 차량 식별자는 운행 복원에 사용됩니다.
   원본 파일명 TAIMS_20260710.zip은 실제 이용일 2026-07-06 자료입니다.
   파일명 날짜와 실제 STDR_DE는 4일 차이가 있으므로 실제 이용일을 기준으로 사용합니다.

2. 같은 교통카드 패키지의 노선·정류장 마스터: 35일 × 2종 = 70개, 약 13.3MB.
   data/processed/transit_v2/masters/
   실제 정류장 순서와 거리 대조, 보정 주간의 노선 구조 확인에 필요합니다.
   카드 자료만 보내고 이 폴더를 빼면 전체 파이프라인이 재현되지 않습니다.

3. 서울시 노선·정류장별 버스 운행횟수(OA-21220), 2026년 8월.
   출처: https://data.seoul.go.kr/dataList/OA-21220/F/1/datasetView.do
   data/raw/maeul_upgrade/aggregates/OA-21220_2608.zip : 약 68.8MB.
   8월 최종 검증 주간의 운행횟수 대조에 사용합니다.
   7~8월 분석 대상 노선 추출본 official_trip_counts_jul_aug.parquet(약 8.2MB)도 포함합니다.
   이 추출본은 새 관측 데이터가 아니라 위 공식 운행횟수 자료의 전처리 결과입니다.

4. fetch_manifest/의 35개 JSON: 원본 다운로드 URL, 이용일, SHA256, 추출 행수 기록.
   카드 자료·masters·fetch_manifest를 함께 전달해야 합니다.
   ZIP 원자료 없이 실행할 때는 --download를 붙이지 마세요.

## 새로 받은 자료 중 전달하지 않아도 되는 것

- OA-21217_2607.zip, OA-21218_2607.zip: 탐색용으로 확보했지만 최종 파이프라인에는 쓰지 않습니다.
- OA-21220_2607.zip: 기존 7월 운행횟수 자료와 겹칩니다.
- departure_parts/, trip_partitions*/, audit_partitions/, models/, transit_full/: 재생성 가능한 중간·결과 파일.
- 차량 정원·배터리·질량·차고지 거리 등은 scenario.json에 출처와 가정으로 기록한 설정이며 실측 운행자료가 아닙니다.

## 적용 및 실행

1. 기존 프로젝트의 사본을 만들고, ZIP 안의 data/, src/, config/, docs/ 등을 프로젝트 루트에 합칩니다.
   포함된 동일 경로의 코드 파일은 현재 로컬 버전으로 교체합니다. 기존 data/processed/transit/는 교체하지 않습니다.
2. manifest의 required_existing_inputs_not_included 목록을 확인합니다. 친구가 기존 데이터를 갖고 있다면 다시 받을 필요 없습니다.
   필수 기존 입력: transit/ 노선·수요·경로·속도·고령인구 자료 11개, seoul_link_dimension.csv,
   seoul_link.shp 및 부속 파일, 7월 시간대별 승하차 CSV, 연료별 등록대수 CSV.
   기존 코드 src/transit/route_data.py, route_kinds.py, route_classes.py, road_network.py와
   05_build_route_carbon_breakeven.py, 07_build_route_operations.py 등도 그대로 필요합니다.
   원본 9월 정류장 Excel이 있으면 route_stops.parquet와 같은 버전인지 확인하세요.
3. 기존 GIS 실행환경(geopandas·shapely·pyproj 등)을 준비한 Python 3.13 환경에서:

```powershell
python -m pip install -r requirements-upgrade.txt
python -X utf8 -m unittest discover -s tests -p test_maeul_upgrade.py -v
python -X utf8 -m src.transit.upgrade.run --integrated
```

카드 원본 다운로드·추출부터 재현하는 패키지가 아니라, 카드 전처리 입력부터 분석·모델 학습·보고서를 재현하는 패키지입니다.
원본부터 확인하려면 fetch_manifest의 URL로 35개 ZIP을 별도 확보하세요.
공식 운행횟수 추출 캐시를 삭제하고 다시 생성하려면 기존
data/raw/traffic/bus_trips/tpss_sta_route_hturn_202607.zip도 필요합니다.

## 생성 결과

- data/processed/transit_v2/: 운행별 재차, AI 예측, 검증, 차량 배치 시나리오.
- data/processed/transit_full/: 기존 프로젝트 전체 흐름을 재계산한 노선별 탄소·접근성 결과.
- output/pdf/서울_마을버스_탄소효율_이동권_통합분석보고서_5p.pdf

manifest는 포함 파일과 기존 필수 입력의 SHA256을 기록합니다.
기존 입력이 다른 경우 같은 코드에서도 결과가 달라질 수 있습니다.
이 패키지는 동료에게 전달할 로컬 분석용 자료입니다. 차량 식별자를 포함한 개별 기록을 공개 GitHub에 올리지 마세요.
'''
    readme_path = DEST / '친구전달_추가데이터_재현안내.md'
    readme_path.write_text(readme, encoding='utf-8')
    target = DEST / 'maeul_added_data_and_code_20261014.zip'
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for p in selected:
            archive.write(p, p.relative_to(ROOT).as_posix())
        archive.write(readme_path, '친구전달_추가데이터_재현안내.md')
        archive.write(manifest_path, 'maeul_handoff_manifest.json')
    with zipfile.ZipFile(target) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f'Corrupt archive: {bad}')
    print(json.dumps({'zip': str(target), 'bytes': target.stat().st_size,
                      'included_files': len(selected), 'required_existing': len(baseline),
                      'sha256': digest(target)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
