from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "raw"
OUT_DIR = BASE_DIR / "processed"
API_KEY_PATH = BASE_DIR / "api_key.txt"

API_URL = "http://t-data.seoul.go.kr/apig/apiman-gateway/tapi/TopisIccStTimesLinkTrfSectionStats/1.0"
DEFAULT_START_DATE = "20260601"
DEFAULT_END_DATE = "20260630"
DEFAULT_START_ROW = 1
DEFAULT_ROW_COUNT = 1000


def load_api_key() -> str:
    env_key = os.environ.get("TDATA_API_KEY", "").strip()
    if env_key:
        return env_key

    if API_KEY_PATH.exists():
        file_key = API_KEY_PATH.read_text(encoding="utf-8").strip()
        if file_key:
            return file_key

    raise SystemExit(
        "API 키가 없습니다. traffic_data/api_key.txt에 키를 입력하거나 "
        "환경변수 TDATA_API_KEY를 설정한 뒤 다시 실행하세요."
    )


def validate_date(value: str, label: str = "날짜") -> str:
    if len(value) != 8 or not value.isdigit():
        raise SystemExit(f"{label}는 YYYYMMDD 형식의 8자리 숫자여야 합니다: {value}")

    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise SystemExit(f"{label}가 실제 날짜가 아닙니다: {value}") from exc

    return value


def masked_url(url: str, api_key: str) -> str:
    if not api_key:
        return url
    return url.replace(api_key, "***API_KEY***")


def build_url(api_key: str, stnd_dt: str, start_row: int, row_count: int) -> str:
    stnd_dt = validate_date(stnd_dt, "stndDt")
    query = urlencode(
        {
            "apikey": api_key,
            "stndDt": stnd_dt,
            "startRow": start_row,
            "rowCnt": row_count,
        }
    )
    return f"{API_URL}?{query}"


def fetch_text(url: str) -> tuple[str, str]:
    request = Request(url, headers={"User-Agent": "traffic-data-analysis/0.1"})
    with urlopen(request, timeout=60) as response:
        content_type = response.headers.get("Content-Type", "")
        charset = response.headers.get_content_charset() or "utf-8"
        text = response.read().decode(charset, errors="replace")
    return text, content_type


def find_records_json(value):
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        return value

    if isinstance(value, dict):
        for child in value.values():
            records = find_records_json(child)
            if records:
                return records

    return []


def parse_json_records(text: str) -> list[dict]:
    data = json.loads(text)
    if isinstance(data, list):
        return data
    return find_records_json(data)


def parse_xml_records(text: str) -> list[dict]:
    root = ElementTree.fromstring(text)
    rows = []

    for element in root.iter():
        children = list(element)
        if children and all(len(child) == 0 for child in children):
            row = {child.tag: (child.text or "") for child in children}
            if len(row) >= 2:
                rows.append(row)

    return rows


def parse_records(text: str) -> list[dict]:
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return parse_json_records(text)
    if stripped.startswith("<"):
        return parse_xml_records(text)
    return []


def iter_dates(start_date: str, end_date: str):
    start_date = validate_date(start_date, "시작일")
    end_date = validate_date(end_date, "종료일")

    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()

    if start > end:
        raise SystemExit("시작일이 종료일보다 늦습니다.")

    current = start
    while current <= end:
        yield current.strftime("%Y%m%d")
        current += timedelta(days=1)


def fetch_one_day(api_key: str, stnd_dt: str, start_row: int, row_count: int) -> pd.DataFrame | None:
    url = build_url(api_key, stnd_dt, start_row, row_count)
    print(f"[{stnd_dt}] 호출 URL:", masked_url(url, api_key))

    text, content_type = fetch_text(url)

    raw_path = RAW_DIR / f"topis_link_speed_{stnd_dt}.txt"
    raw_path.write_text(text, encoding="utf-8")

    print(f"[{stnd_dt}] 응답 Content-Type:", content_type)
    print(f"[{stnd_dt}] 원본 저장:", raw_path)
    print(f"[{stnd_dt}] 응답 앞부분:")
    print(text[:1000])

    records = parse_records(text)
    if not records:
        print(f"[{stnd_dt}] 표 형태 레코드를 찾지 못했습니다.")
        return None

    df = pd.DataFrame(records)
    if "stndDt" not in df.columns:
        df.insert(0, "stndDt", stnd_dt)

    csv_path = OUT_DIR / f"topis_link_speed_{stnd_dt}.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"[{stnd_dt}] 파싱된 행/열:", df.shape)
    print(f"[{stnd_dt}] CSV 저장:", csv_path)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="T-data 1시간 링크 소통정보를 내려받습니다.")
    parser.add_argument("--date", help="조회 기준일, 예: 20260609")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE, help="조회 시작일, 예: 20260601")
    parser.add_argument("--end-date", default=DEFAULT_END_DATE, help="조회 종료일, 예: 20260630")
    parser.add_argument("--start-row", type=int, default=DEFAULT_START_ROW, help="API startRow 값")
    parser.add_argument("--row-count", type=int, default=DEFAULT_ROW_COUNT, help="API rowCnt 값")
    args = parser.parse_args()

    if args.start_row < 1:
        raise SystemExit("startRow는 1 이상이어야 합니다.")
    if args.row_count < 1:
        raise SystemExit("rowCnt는 1 이상이어야 합니다.")

    api_key = load_api_key()

    RAW_DIR.mkdir(exist_ok=True)
    OUT_DIR.mkdir(exist_ok=True)

    dates = [validate_date(args.date, "조회일")] if args.date else list(iter_dates(args.start_date, args.end_date))
    dataframes = []
    empty_dates = []

    for stnd_dt in dates:
        df = fetch_one_day(api_key, stnd_dt, args.start_row, args.row_count)
        if df is not None:
            dataframes.append(df)
        else:
            empty_dates.append(stnd_dt)

    if not dataframes:
        print("조회 기간에서 파싱 가능한 데이터가 없습니다.")
        if empty_dates:
            print("빈 응답 날짜:", ", ".join(empty_dates))
        return

    combined = pd.concat(dataframes, ignore_index=True)
    combined_path = OUT_DIR / f"topis_link_speed_{dates[0]}_{dates[-1]}.csv"
    combined.to_csv(combined_path, index=False, encoding="utf-8-sig")

    print("전체 합본 행/열:", combined.shape)
    print("컬럼명:")
    print(combined.columns)
    print("상위 5개 행:")
    print(combined.head())
    print("합본 CSV 저장:", combined_path)
    if empty_dates:
        print("빈 응답 날짜:", ", ".join(empty_dates))


if __name__ == "__main__":
    main()
