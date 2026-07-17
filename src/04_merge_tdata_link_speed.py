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
ROAD_NAME_KEY = "ROAD_NAME"
TDATA_ROAD_NAME_KEY = "도로명"
SPEED_KEY = "평균속도"
DATE_KEY = "기준일"
TIME_CODE_KEY = "시간코드"
PREFIX_LEN = 8
PREFIX_COL = "LINK_PREFIX8"
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


def match_exact(seoul_links: pd.DataFrame, tdata_speed: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """LINK_ID 10자리가 정확히 일치하는 T-data 행을 1:1로 결합한다."""
    seoul_link_ids = set(seoul_links[LINK_KEY].dropna())
    is_exact = tdata_speed[TDATA_LINK_KEY].isin(seoul_link_ids)

    merged = tdata_speed[is_exact].merge(
        seoul_links,
        left_on=TDATA_LINK_KEY,
        right_on=LINK_KEY,
        how="inner",
    )
    merged["match_method"] = "exact"
    merged["broadcast_source_link_ids"] = merged[TDATA_LINK_KEY]
    merged["broadcast_source_count"] = 1
    merged["broadcast_speed_std"] = 0.0
    merged = merged.drop(columns=[TDATA_LINK_KEY])
    return merged, is_exact


def match_prefix8(
    seoul_links: pd.DataFrame,
    tdata_speed: pd.DataFrame,
    exact_seoul_ids: set,
) -> pd.DataFrame:
    """
    exact 매칭에 실패한 T-data 행을, LINK_ID 앞 8자리(표준노드링크 개정
    과정에서 붙는 세부 suffix를 뗀 논리적 도로 구간 단위)로 재매칭한다.

    표준노드링크가 갱신되며 T-data가 참조하던 링크 하나가 여러 개의 세부
    링크로 쪼개진 경우가 많아, exact match만으로는 실제 존재하는 도로
    구간의 상당수를 놓친다(검증 결과 T-data 기준 매칭률 29.6% -> 90.4%).

    - 이미 exact로 매칭된 Seoul 링크는 broadcast 대상(target)에서 제외한다
      (같은 링크에 서로 다른 두 값이 겹쳐 붙는 것을 방지).
    - 반대로 T-data 행 자체는 exact 매칭 여부와 무관하게 전부 broadcast
      소스로 사용한다 - 어떤 T-data 행이 형제 Seoul 링크 중 하나와
      exact로 매칭됐다고 해서, 그 행이 나머지 형제 링크에 broadcast하는
      것까지 막을 이유는 없다(그렇게 막으면 그 prefix 그룹의 유일한
      T-data 소스가 사라져 나머지 형제 링크가 전부 미매칭된다).
    - ROAD_NAME이 T-data 도로명과 정확히 일치하는 조합만 채택한다(서로
      다른 도로가 우연히 같은 8자리를 공유하는 오매칭을 제거, 검증 결과
      96.96%가 이 조건을 만족).
    - 하나의 T-data 행이 여러 Seoul 링크에 매칭되면(1:N, 평균 3.57개),
      같은 속도값을 해당 링크 전체에 broadcast한다.
    - 반대로 하나의 Seoul 링크가 같은 prefix를 공유하는 여러 T-data 행과
      동시에 매칭될 수도 있다(예: 하나의 링크가 원래 상행/하행 두 T-data
      구간으로 쪼개져 있던 경우). 이 경우 같은 (LINK_ID, 기준일, 시간코드)
      조합에 서로 다른 속도값이 여러 개 붙는 문제가 생기므로,
      `aggregate_broadcast_duplicates`에서 평균으로 합치고 소스 개수/표준
      편차를 별도 컬럼에 남긴다.
    """
    fallback_tdata = tdata_speed.copy()
    fallback_tdata[PREFIX_COL] = fallback_tdata[TDATA_LINK_KEY].str[:PREFIX_LEN]

    fallback_seoul = seoul_links[~seoul_links[LINK_KEY].isin(exact_seoul_ids)].copy()
    fallback_seoul[PREFIX_COL] = fallback_seoul[LINK_KEY].str[:PREFIX_LEN]

    merged = fallback_tdata.merge(fallback_seoul, on=PREFIX_COL, how="inner")
    merged = merged[merged[TDATA_ROAD_NAME_KEY] == merged[ROAD_NAME_KEY]].copy()
    merged["match_method"] = "prefix8"
    merged = merged.drop(columns=[PREFIX_COL])
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
    validate_columns(tdata_speed, [TDATA_LINK_KEY, TDATA_ROAD_NAME_KEY], str(TDATA_SPEED_PATH))

    exact_merged, _is_exact = match_exact(seoul_links, tdata_speed)
    exact_seoul_ids = set(exact_merged[LINK_KEY])

    prefix8_merged = match_prefix8(seoul_links, tdata_speed, exact_seoul_ids)

    merged = pd.concat([exact_merged, prefix8_merged], ignore_index=True, sort=False)

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print("서울 링크 행 수:", len(seoul_links))
    print("서울 링크 고유 LINK_ID 수:", seoul_links[LINK_KEY].nunique())
    print("T-data 소통정보 행 수:", len(tdata_speed))
    print("T-data 고유 링크ID 수:", tdata_speed[TDATA_LINK_KEY].nunique())
    print()
    print("exact 매칭 행 수:", len(exact_merged), "| 고유 Seoul 링크 수:", exact_merged[LINK_KEY].nunique())
    print("prefix8 매칭 행 수(중복 병합 후):", len(prefix8_merged), "| 고유 Seoul 링크 수:", prefix8_merged[LINK_KEY].nunique())
    multi_source = prefix8_merged[prefix8_merged["broadcast_source_count"] > 1]
    print("여러 T-data 소스가 겹쳐 평균으로 병합된 행 수:", len(multi_source),
          f"({len(multi_source) / len(prefix8_merged) * 100:.2f}%)" if len(prefix8_merged) else "")
    if len(multi_source):
        print("병합된 행의 speed_std 중앙값:", round(multi_source["broadcast_speed_std"].median(), 2),
              "| 10km/h 초과 비율:", f"{(multi_source['broadcast_speed_std'] > 10).mean() * 100:.2f}%")
    print()
    print("결합된 T-data 행 수:", len(merged))
    print("결합된 고유 Seoul 링크 수:", merged[LINK_KEY].nunique())
    print("저장 파일:", OUT_CSV)


if __name__ == "__main__":
    main()
