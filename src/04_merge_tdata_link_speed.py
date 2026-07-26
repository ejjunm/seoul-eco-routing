import fnmatch
import unicodedata
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
TRAFFIC_RAW_DIR = RAW_DATA_DIR / "traffic"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

SEOUL_LINK_ATTR_PATH = PROCESSED_DATA_DIR / "seoul_link_attr.csv"
TDATA_SPEED_GLOB = "1시간 소통정보 (구간별)*.csv"
OFFICIAL_MAPPING_PATH = TRAFFIC_RAW_DIR / "서울특별시 교통소통 표준링크 매핑정보_20250306.xlsx"
OUT_CSV = PROCESSED_DATA_DIR / "seoul_link_speed_merged.csv"

LINK_KEY = "LINK_ID"
TDATA_LINK_KEY = "링크ID"
ROAD_NAME_KEY = "ROAD_NAME"
TDATA_ROAD_NAME_KEY = "도로명"
SPEED_KEY = "평균속도"
DATE_KEY = "기준일"
TIME_CODE_KEY = "시간코드"
OFFICIAL_SERVICE_LINK_KEY = "서비스링크"
OFFICIAL_TARGET_LINK_KEY = "표준링크아이디"
AGG_KEYS = [LINK_KEY, DATE_KEY, TIME_CODE_KEY]


def read_seoul_links() -> pd.DataFrame:
    return pd.read_csv(
        SEOUL_LINK_ATTR_PATH,
        dtype={
            "LINK_ID": str,
            "F_NODE": str,
            "T_NODE": str,
        },
    )


def find_tdata_paths() -> list[Path]:
    """
    TDATA_SPEED_GLOB에 맞는 T-data CSV 경로를 찾는다.

    Path.glob을 그대로 쓰지 않는 이유: macOS(APFS)는 한글 파일명을 NFD(자모 분리)로
    저장하는데 소스코드의 패턴 문자열은 NFC(조합형)라, 파일이 있는데도 매칭이 0건이 된다
    (Windows는 NFC로 저장돼 정상 동작). 실제 파일명과 패턴을 모두 NFC로 정규화해
    비교하므로 macOS/Windows 양쪽에서 동일하게 찾는다.
    """
    if not TRAFFIC_RAW_DIR.is_dir():
        return []
    pattern = unicodedata.normalize("NFC", TDATA_SPEED_GLOB)
    return sorted(
        p for p in TRAFFIC_RAW_DIR.iterdir()
        if p.is_file() and fnmatch.fnmatch(unicodedata.normalize("NFC", p.name), pattern)
    )


def read_tdata_speed() -> pd.DataFrame:
    """
    data/raw/traffic/ 아래 "1시간 소통정보 (구간별)*.csv"에 맞는 파일을
    전부 읽어서 합친다. T-data는 기간별로 별도 파일(예: "... (1).csv")로
    추가되는 경우가 많아, 파일명 하나를 고정하지 않고 패턴으로 찾는다.
    """
    paths = find_tdata_paths()
    if not paths:
        raise SystemExit(f"T-data 파일이 없습니다: {TRAFFIC_RAW_DIR / TDATA_SPEED_GLOB}")

    dtype = {
        "링크ID": str,
        "기준일": str,
        "시간코드": str,
        "도로방향구분코드": str,
        "요일코드(1~7:일~토)": str,
        "요일그룹코드(01:주중/02:주말)": str,
        "도로코드": str,
        "도로구분코드": str,
    }
    frames = [pd.read_csv(path, dtype=dtype, encoding="utf-8-sig") for path in paths]
    combined = pd.concat(frames, ignore_index=True)

    dup_key = ["기준일", "시간코드", "링크ID", "도로방향구분코드"]
    dup_count = combined.duplicated(subset=dup_key).sum()
    if dup_count:
        print(f"경고: T-data 파일 {len(paths)}개를 합쳤는데 중복 행이 {dup_count}건 있습니다 (겹치는 기간 확인 필요).")

    print(f"T-data 파일 {len(paths)}개 로드:", ", ".join(path.name for path in paths))
    return combined


def validate_columns(df: pd.DataFrame, required_columns: list[str], file_label: str) -> None:
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise SystemExit(f"{file_label}에 필요한 컬럼이 없습니다: {missing_columns}")


def read_official_mapping() -> pd.DataFrame:
    mapping = pd.read_excel(
        OFFICIAL_MAPPING_PATH,
        dtype={OFFICIAL_SERVICE_LINK_KEY: str, OFFICIAL_TARGET_LINK_KEY: str},
    )
    return mapping[[OFFICIAL_SERVICE_LINK_KEY, OFFICIAL_TARGET_LINK_KEY]].dropna()


def match_official(seoul_links: pd.DataFrame, tdata_speed: pd.DataFrame) -> pd.DataFrame:
    """
    서울시가 직접 발행한 'TOPIS-표준노드링크 매핑정보'(서비스링크 ->
    표준링크아이디, 1:N)로 T-data를 결합한다. TOPIS 내부 링크체계와
    표준노드링크 LINK_ID를 공식적으로 연결해주는 정답 테이블이라
    prefix8 같은 추정 로직 없이 그대로 신뢰할 수 있다.

    하나의 서비스링크가 여러 표준링크아이디(물리적 세부 구간)에 대응하는
    경우, 같은 속도값을 해당 구간 전체에 broadcast한다(표준링크순서
    컬럼이 이 1:N 관계가 실제 도로 구간의 순차 분할임을 보여준다).
    표준링크아이디는 매핑 테이블 내에서 서로 다른 서비스링크에 중복
    등장하지 않으므로(검증 완료), 이 broadcast로 같은 타겟 링크에 서로
    다른 서비스링크의 값이 겹쳐 붙는 경우는 없다.

    같은 (LINK_ID, 기준일, 시간코드)에 그래도 여러 소스 행이 모이면
    (T-data 자체의 상행/하행 분리 등) `aggregate_broadcast_duplicates`가
    평균으로 합친다.
    """
    mapping = read_official_mapping()
    seoul_ids = set(seoul_links[LINK_KEY].dropna())
    mapping = mapping[mapping[OFFICIAL_TARGET_LINK_KEY].isin(seoul_ids)]

    merged = tdata_speed.merge(
        mapping,
        left_on=TDATA_LINK_KEY,
        right_on=OFFICIAL_SERVICE_LINK_KEY,
        how="inner",
    )
    merged = merged.merge(
        seoul_links,
        left_on=OFFICIAL_TARGET_LINK_KEY,
        right_on=LINK_KEY,
        how="inner",
    )
    merged["match_method"] = "official_mapping"
    merged = merged.drop(columns=[OFFICIAL_SERVICE_LINK_KEY, OFFICIAL_TARGET_LINK_KEY])
    return aggregate_broadcast_duplicates(merged)


def aggregate_broadcast_duplicates(merged: pd.DataFrame) -> pd.DataFrame:
    """
    같은 (LINK_ID, 기준일, 시간코드)에 여러 T-data 소스 행이 broadcast되면
    (예: 한 링크가 원래 상행/하행 두 T-data 구간으로 쪼개져 있던 경우)
    평균속도를 평균으로 합치고, 소스 T-data 링크ID 목록/개수/표준편차를
    남긴다. 표준편차가 크면(예: 10km/h 이상) 서로 다른 방향/맥락의 관측이
    섞였을 수 있다는 뜻이니 분석 시 참고한다.
    """
    merged = merged.copy()
    merged[SPEED_KEY] = pd.to_numeric(merged[SPEED_KEY], errors="coerce")

    stats = merged.groupby(AGG_KEYS)[SPEED_KEY].agg(["mean", "count", "std"]).reset_index()
    stats.columns = AGG_KEYS + [SPEED_KEY, "broadcast_source_count", "broadcast_speed_std"]
    stats["broadcast_speed_std"] = stats["broadcast_speed_std"].fillna(0.0)

    source_ids = (
        merged.groupby(AGG_KEYS)[TDATA_LINK_KEY]
        .agg(lambda values: ",".join(sorted(set(values))))
        .rename("broadcast_source_link_ids")
        .reset_index()
    )

    deduped = merged.drop(columns=[SPEED_KEY, TDATA_LINK_KEY]).groupby(AGG_KEYS, as_index=False).first()
    deduped = deduped.merge(stats, on=AGG_KEYS, how="left")
    deduped = deduped.merge(source_ids, on=AGG_KEYS, how="left")
    return deduped


def main() -> None:
    seoul_links = read_seoul_links()
    tdata_speed = read_tdata_speed()

    validate_columns(seoul_links, [LINK_KEY, ROAD_NAME_KEY], str(SEOUL_LINK_ATTR_PATH))
    validate_columns(tdata_speed, [TDATA_LINK_KEY, TDATA_ROAD_NAME_KEY], f"T-data ({TDATA_SPEED_GLOB})")

    merged = match_official(seoul_links, tdata_speed)

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print("서울 링크 행 수:", len(seoul_links))
    print("서울 링크 고유 LINK_ID 수:", seoul_links[LINK_KEY].nunique())
    print("T-data 소통정보 행 수:", len(tdata_speed))
    print("T-data 고유 링크ID 수:", tdata_speed[TDATA_LINK_KEY].nunique())
    print()
    matched_link_count = merged[LINK_KEY].nunique()
    print("공식 매핑 매칭 링크 수:", matched_link_count,
          f"({matched_link_count / seoul_links[LINK_KEY].nunique() * 100:.2f}%)")
    multi_source = merged[merged["broadcast_source_count"] > 1]
    print("여러 T-data 소스가 겹쳐 평균으로 병합된 행 수:", len(multi_source),
          f"({len(multi_source) / len(merged) * 100:.2f}%)" if len(merged) else "")
    if len(multi_source):
        print("병합된 행의 speed_std 중앙값:", round(multi_source["broadcast_speed_std"].median(), 2),
              "| 10km/h 초과 비율:", f"{(multi_source['broadcast_speed_std'] > 10).mean() * 100:.2f}%")
    print()
    print("결합된 T-data 행 수:", len(merged))
    print("결합된 고유 Seoul 링크 수:", merged[LINK_KEY].nunique())
    print("저장 파일:", OUT_CSV)


if __name__ == "__main__":
    main()
