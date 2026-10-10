"""서울시 버스운행정보 API(노선경로목록조회, getRoutePath)로 노선별 실제 경로 좌표를 받는다.

인증키는 저장소에 남기지 않도록 환경변수 SEOUL_BUS_API_KEY에서 읽는다.

입력
  data/raw/traffic/서울시버스노선별정류소정보(20260902).xlsx  (대상 노선 ID: 마을버스·자율주행)
출력
  data/raw/traffic/bus_route_path/route_paths.csv  (ROUTE_ID, 노선명, no, gpsX, gpsY)

사용 (PowerShell):
  $env:SEOUL_BUS_API_KEY = "<키>"; python src/transit/00_fetch_bus_route_paths.py
"""

from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_TRAFFIC = PROJECT_ROOT / "data" / "raw" / "traffic"
ROUTE_STOP_XLSX = RAW_TRAFFIC / "서울시버스노선별정류소정보(20260902).xlsx"
OUT_PATH = RAW_TRAFFIC / "bus_route_path" / "route_paths.csv"
ENDPOINT = "http://ws.bus.go.kr/api/rest/busRouteInfo/getRoutePath"


def fetch(route_id: str, key: str, retries: int = 3) -> list[dict]:
    url = f"{ENDPOINT}?{urlencode({'serviceKey': key, 'busRouteId': route_id}, safe='')}"
    for attempt in range(1, retries + 1):
        try:
            with urlopen(url, timeout=30) as response:
                root = ET.fromstring(response.read())
            break
        except OSError:  # 연결 시간 초과 등 일시적 오류는 잠시 쉬었다가 다시 시도한다.
            if attempt == retries:
                raise
            time.sleep(5 * attempt)
    code = root.findtext("msgHeader/headerCd")
    if code not in ("0", "4"):  # 4 = 결과 없음
        raise RuntimeError(f"{route_id}: {code} {root.findtext('msgHeader/headerMsg')}")
    return [
        {"no": int(item.findtext("no")), "gpsX": float(item.findtext("gpsX")), "gpsY": float(item.findtext("gpsY"))}
        for item in root.iter("itemList")
    ]


def main() -> None:
    key = os.environ.get("SEOUL_BUS_API_KEY")
    if not key:
        raise SystemExit("환경변수 SEOUL_BUS_API_KEY가 없습니다.")
    stops = pd.read_excel(ROUTE_STOP_XLSX, dtype={"ROUTE_ID": str})
    stops["노선명"] = stops["노선명"].astype(str)
    target = stops[stops["노선명"].str.match(r"^[가-힣]+\d{2}$") | stops["노선명"].str.contains(r"A\d")]
    routes = target.drop_duplicates("ROUTE_ID")[["ROUTE_ID", "노선명"]]

    rows, empty = [], []
    for i, (route_id, name) in enumerate(routes.itertuples(index=False), start=1):
        points = fetch(route_id, key)
        if not points:
            empty.append(name)
        rows.extend({"ROUTE_ID": route_id, "노선명": name, **p} for p in points)
        if i % 50 == 0:
            print(f"  {i}/{len(routes)}")
        time.sleep(0.1)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"노선 {len(routes)}개 중 경로 수신 {len(routes) - len(empty)}개, 좌표 {len(rows):,}개 → {OUT_PATH}")
    if empty:
        print("경로 없음:", empty)


if __name__ == "__main__":
    main()
