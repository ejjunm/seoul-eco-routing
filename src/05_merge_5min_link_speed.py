from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

SEOUL_LINK_ATTR_PATH = PROCESSED_DATA_DIR / "seoul_link_attr.csv"
FIVEMIN_SPEED_PATH = PROCESSED_DATA_DIR / "seoul_link_speed_5min_hourly.csv"
OUT_CSV = PROCESSED_DATA_DIR / "seoul_link_speed_merged.csv"

LINK_KEY = "LINK_ID"
SPEED_KEY = "평균속도"
DATE_KEY = "기준일"
TIME_CODE_KEY = "시간코드"


def read_seoul_links() -> pd.DataFrame:
    return pd.read_csv(
        SEOUL_LINK_ATTR_PATH,
        dtype={"LINK_ID": str, "F_NODE": str, "T_NODE": str},
    )


def read_5min_speed() -> pd.DataFrame:
    """
    04_aggregate_5min_speed.py가 만든 (LINK_ID, 기준일, 시간코드)별 1시간
    집계 속도를 읽는다. 이 LINK_ID는 서울 표준노드링크 LINK_ID와 이미
    직접 일치하는 값이라(별도 검증 완료), T-data 때와 달리 서비스링크
    매핑이나 1:N broadcast 없이 그대로 결합할 수 있다.
    """
    if not FIVEMIN_SPEED_PATH.exists():
        raise SystemExit(
            f"5분 집계 속도 파일이 없습니다: {FIVEMIN_SPEED_PATH}\n"
            "04_aggregate_5min_speed.py를 먼저 실행하세요."
        )
    return pd.read_csv(
        FIVEMIN_SPEED_PATH,
        dtype={LINK_KEY: str, DATE_KEY: str, TIME_CODE_KEY: str},
        encoding="utf-8-sig",
    )


def main() -> None:
    seoul_links = read_seoul_links()
    speed = read_5min_speed()

    merged = speed.merge(seoul_links, on=LINK_KEY, how="inner")
    merged["match_method"] = "5min_direct"

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print("서울 링크 수:", len(seoul_links))
    print("5분 집계 소스 (링크,날짜,시간) 행 수:", len(speed))
    print("5분 집계 소스 고유 LINK_ID 수:", speed[LINK_KEY].nunique())
    print()
    matched_link_count = merged[LINK_KEY].nunique()
    print("매칭 링크 수:", matched_link_count,
          f"({matched_link_count / seoul_links[LINK_KEY].nunique() * 100:.2f}%)")
    print("결합된 행 수:", len(merged))
    print("저장 파일:", OUT_CSV)


if __name__ == "__main__":
    main()
