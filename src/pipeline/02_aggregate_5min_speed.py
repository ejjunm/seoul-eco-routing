"""5분 단위 전국 교통소통 원본에서 서울 링크만 걸러 1시간 단위로 집계한다.

구 src/04_aggregate_5min_speed.py와 로직 동일(이미 올바른 grain — LINK_ID x
기준일 x 시간코드 — 이라 변경 불필요), src/pipeline/으로 위치만 이동.

출력: data/processed/seoul_link_speed_5min_hourly.csv

사용: python src/pipeline/02_aggregate_5min_speed.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
TRAFFIC_RAW_DIR = RAW_DATA_DIR / "traffic"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

SEOUL_LINK_ATTR_PATH = PROCESSED_DATA_DIR / "seoul_link_attr.csv"
FIVEMIN_DIR = TRAFFIC_RAW_DIR / "202607_5Min"
FIVEMIN_GLOB = "*_5Min.csv"
OUT_CSV = PROCESSED_DATA_DIR / "seoul_link_speed_5min_hourly.csv"

LINK_KEY = "LINK_ID"
FIVEMIN_LINK_KEY = "LINKID"
SPEED_KEY = "PASNGSPED"
DATE_KEY_RAW = "CREATDE"
TIME_KEY_RAW = "CREATHM"
DATE_KEY = "기준일"
TIME_CODE_KEY = "시간코드"
CHUNK_SIZE = 10_000_000
GROUP_KEYS = [FIVEMIN_LINK_KEY, DATE_KEY_RAW, TIME_CODE_KEY]

USECOLS = [FIVEMIN_LINK_KEY, DATE_KEY_RAW, TIME_KEY_RAW, SPEED_KEY]
READ_DTYPE = {FIVEMIN_LINK_KEY: str, DATE_KEY_RAW: str, TIME_KEY_RAW: str, SPEED_KEY: "float32"}


def read_seoul_link_ids() -> set:
    seoul_links = pd.read_csv(SEOUL_LINK_ATTR_PATH, usecols=[LINK_KEY], dtype=str)
    return set(seoul_links[LINK_KEY].dropna())


def aggregate_one_file(path: Path, seoul_ids: set) -> pd.DataFrame:
    """
    5분 단위 원본(전국 단위, 하루 약 1.7억 행)을 청크로 읽어 서울 링크만
    남기고, CREATHM(HHMM)에서 시간코드(01~24, 00시대=01 ... 23시대=24)를
    만들어 (LINKID, 기준일, 시간코드)로 평균 낸다. 청크마다 부분합/개수를
    구해뒀다가 마지막에 합치는 방식이라 메모리에 원본 전체를 올리지 않는다.
    """
    parts = []
    reader = pd.read_csv(
        path, usecols=USECOLS, dtype=READ_DTYPE, chunksize=CHUNK_SIZE, encoding="utf-8-sig",
    )
    for i, chunk in enumerate(reader, start=1):
        chunk = chunk[chunk[FIVEMIN_LINK_KEY].isin(seoul_ids)]
        if not chunk.empty:
            work = chunk.copy()
            work[TIME_CODE_KEY] = (work[TIME_KEY_RAW].str[:2].astype(int) + 1).astype(str).str.zfill(2)
            part = work.groupby(GROUP_KEYS)[SPEED_KEY].agg(["sum", "count"]).reset_index()
            parts.append(part)
        print(f"  청크 {i} ({i * CHUNK_SIZE:,}행 이하) 처리 완료", flush=True)

    if not parts:
        return pd.DataFrame(columns=GROUP_KEYS + ["sum", "count"])

    combined = pd.concat(parts, ignore_index=True)
    return combined.groupby(GROUP_KEYS, as_index=False).sum()


def main() -> None:
    seoul_ids = read_seoul_link_ids()
    paths = sorted(FIVEMIN_DIR.glob(FIVEMIN_GLOB))
    if not paths:
        raise SystemExit(f"5분 데이터 파일이 없습니다: {FIVEMIN_DIR / FIVEMIN_GLOB}")

    daily_results = []
    for path in paths:
        print(f"=== {path.name} 처리 시작 ===", flush=True)
        result = aggregate_one_file(path, seoul_ids)
        matched_links = result[FIVEMIN_LINK_KEY].nunique()
        print(f"{path.name}: (링크,시간) 조합 {len(result):,}건 | 고유 링크 {matched_links:,}개")
        daily_results.append(result)

    combined = pd.concat(daily_results, ignore_index=True)
    combined = combined.groupby(GROUP_KEYS, as_index=False).sum()
    combined["평균속도"] = combined["sum"] / combined["count"]
    combined = combined.rename(columns={FIVEMIN_LINK_KEY: LINK_KEY, DATE_KEY_RAW: DATE_KEY, "count": "sample_count_5min"})
    combined = combined.drop(columns=["sum"])

    new_dates = set(combined[DATE_KEY].unique())
    if OUT_CSV.exists():
        previous = pd.read_csv(OUT_CSV, dtype={LINK_KEY: str, DATE_KEY: str, TIME_CODE_KEY: str}, encoding="utf-8-sig")
        kept_previous = previous[~previous[DATE_KEY].isin(new_dates)]
        dropped = previous[DATE_KEY].nunique() - kept_previous[DATE_KEY].nunique()
        if dropped:
            print(f"기존 결과 중 {dropped}개 날짜는 이번 실행분으로 덮어씁니다(같은 날짜 재처리).")
        combined = pd.concat([kept_previous, combined], ignore_index=True)

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print()
    print("이번 실행에서 처리한 일자 수:", len(paths))
    print("저장 파일에 누적된 전체 일자 수:", combined[DATE_KEY].nunique())
    print("서울 링크 수:", len(seoul_ids))
    print("누적 (링크, 날짜, 시간코드) 행 수:", len(combined))
    print("누적 고유 LINK_ID 수:", combined[LINK_KEY].nunique(), f"({combined[LINK_KEY].nunique() / len(seoul_ids) * 100:.2f}%)")
    print("시간당 5분 샘플 수 평균:", round(combined["sample_count_5min"].mean(), 2), "(최대 12)")
    print("저장 파일:", OUT_CSV)


if __name__ == "__main__":
    main()
