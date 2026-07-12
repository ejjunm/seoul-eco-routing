from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
TRAFFIC_RAW_DIR = RAW_DATA_DIR / "traffic"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

SEOUL_LINK_ATTR_PATH = PROCESSED_DATA_DIR / "seoul_link_attr.csv"
TDATA_SPEED_PATH = TRAFFIC_RAW_DIR / "1시간 소통정보 (구간별).csv"
OUT_CSV = PROCESSED_DATA_DIR / "seoul_link_speed_merged.csv"

LINK_KEY = "LINK_ID"
TDATA_LINK_KEY = "링크ID"


def read_seoul_links() -> pd.DataFrame:
    return pd.read_csv(
        SEOUL_LINK_ATTR_PATH,
        dtype={
            "LINK_ID": str,
            "F_NODE": str,
            "T_NODE": str,
        },
    )


def read_tdata_speed() -> pd.DataFrame:
    return pd.read_csv(
        TDATA_SPEED_PATH,
        dtype={
            "링크ID": str,
            "기준일": str,
            "시간코드": str,
            "도로방향구분코드": str,
            "요일코드(1~7:일~토)": str,
            "요일그룹코드(01:주중/02:주말)": str,
            "도로코드": str,
            "도로구분코드": str,
        },
        encoding="utf-8-sig",
    )


def validate_columns(df: pd.DataFrame, required_columns: list[str], file_label: str) -> None:
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise SystemExit(f"{file_label}에 필요한 컬럼이 없습니다: {missing_columns}")


def main() -> None:
    seoul_links = read_seoul_links()
    tdata_speed = read_tdata_speed()

    validate_columns(seoul_links, [LINK_KEY], str(SEOUL_LINK_ATTR_PATH))
    validate_columns(tdata_speed, [TDATA_LINK_KEY], str(TDATA_SPEED_PATH))

    seoul_link_ids = set(seoul_links[LINK_KEY].dropna())
    matched_speed = tdata_speed[tdata_speed[TDATA_LINK_KEY].isin(seoul_link_ids)].copy()

    merged = matched_speed.merge(
        seoul_links,
        left_on=TDATA_LINK_KEY,
        right_on=LINK_KEY,
        how="inner",
        suffixes=("_tdata", "_link"),
    )

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print("서울 링크 행 수:", len(seoul_links))
    print("서울 링크 고유 LINK_ID 수:", seoul_links[LINK_KEY].nunique())
    print("T-data 소통정보 행 수:", len(tdata_speed))
    print("T-data 고유 링크ID 수:", tdata_speed[TDATA_LINK_KEY].nunique())
    print("결합된 T-data 행 수:", len(merged))
    print("결합된 고유 링크ID 수:", merged[TDATA_LINK_KEY].nunique())
    print("저장 파일:", OUT_CSV)


if __name__ == "__main__":
    main()
