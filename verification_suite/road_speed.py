from pathlib import Path

import pandas as pd


# 1. 경로 정의
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "verification_suite" / "temp_outputs"
SEOUL_LINK_ATTR_PATH = OUTPUT_DIR / "seoul_link_attr.csv"
SPEED_MERGED_PATH = OUTPUT_DIR / "seoul_link_speed_merged.csv"

LINK_KEY = "LINK_ID"


def analyze_match_rate_by_attribute(
    all_links_df: pd.DataFrame,
    matched_link_ids: set,
    attribute_name: str,
    attribute_label: str,
    section_number: int
) -> None:
    """주어진 속성(도로유형, 차선 수 등)에 따라 T-data 결합률을 분석하고 출력합니다."""
    print("\n" + "=" * 80)
    print(f"{section_number}. {attribute_label}({attribute_name})별 T-data 결합률 분석")
    print("=" * 80)

    df = all_links_df.copy()
    # 그룹화를 위해 결측값 처리
    if pd.api.types.is_numeric_dtype(df[attribute_name]):
        df[attribute_name] = df[attribute_name].fillna(0).astype(int)
    else:
        df[attribute_name] = df[attribute_name].fillna("N/A")

    # 속성별 전체 링크 수 집계
    total_by_attr = df.groupby(attribute_name).agg(
        total_links=(LINK_KEY, 'count')
    ).reset_index()

    # 속성별 결합 성공 링크 수 집계
    matched_links_df = df[df[LINK_KEY].isin(matched_link_ids)]
    matched_by_attr = matched_links_df.groupby(attribute_name).agg(
        matched_links=(LINK_KEY, 'count')
    ).reset_index()

    # 데이터 병합 및 결합률 계산
    analysis_df = pd.merge(total_by_attr, matched_by_attr, on=attribute_name, how='left')
    analysis_df['matched_links'] = analysis_df['matched_links'].fillna(0).astype(int)
    analysis_df['match_rate(%)'] = (analysis_df['matched_links'] / analysis_df['total_links']) * 100
    analysis_df = analysis_df.sort_values(by=attribute_name)

    analysis_df.rename(columns={
        attribute_name: attribute_label, 'total_links': '전체 링크 수',
        'matched_links': '결합 성공 링크 수', 'match_rate(%)': '결합률 (%)'
    }, inplace=True)

    print(analysis_df.to_string(index=False, formatters={'결합률 (%)': '{:.2f}'.format}))
    print(f"\n  -> [진단] 위 표는 '{attribute_label}'에 따라 T-data 결합률이 어떻게 달라지는지 보여줍니다.")
    print("     결합률이 낮은 그룹은 속도 정보가 부족하여, 속도 추정 모델의 중요성이 더 큽니다.")


def main():
    """
    T-data 속도 정보가 없는 링크의 특성을 분석하여,
    속도 추정(imputation) 전략 수립을 위한 데이터를 검증합니다.
    """
    # 2. 분석에 필요한 파일 존재 여부 확인
    if not SEOUL_LINK_ATTR_PATH.exists() or not SPEED_MERGED_PATH.exists():
        print("=" * 80)
        print("⚠️ [오류] 분석에 필요한 파일이 없습니다.")
        print("먼저 'run_verification.py'를 실행하여 'temp_outputs' 폴더에 중간 결과물을 생성해주세요.")
        print(f"  - 필요한 파일 1: {SEOUL_LINK_ATTR_PATH}")
        print(f"  - 필요한 파일 2: {SPEED_MERGED_PATH}")
        print("=" * 80)
        return

    # 3. 데이터 로딩
    print("=" * 80)
    print("데이터 로딩 및 전처리 중...")
    print("=" * 80)
    all_links_df = pd.read_csv(SEOUL_LINK_ATTR_PATH, dtype={LINK_KEY: str})
    matched_speed_df = pd.read_csv(SPEED_MERGED_PATH, usecols=[LINK_KEY], dtype={LINK_KEY: str})

    print(f"- 전체 서울 링크 속성 로드 완료: {len(all_links_df):,} 개")
    print("- T-data 결합 속도 데이터 로드 완료")

    # 4. T-data 매칭/미매칭 링크 구분
    all_link_ids = set(all_links_df[LINK_KEY])
    matched_link_ids = set(matched_speed_df[LINK_KEY].unique())

    # 5. 분석 및 결과 출력
    print("\n" + "=" * 80)
    print("1. 전체 링크의 속성 완전성 검증")
    print("=" * 80)

    total_links = len(all_links_df)
    missing_max_spd = all_links_df['MAX_SPD'].fillna(0).le(0).sum()
    missing_lanes = all_links_df['LANES'].fillna(0).le(0).sum()
    missing_road_type = all_links_df['ROAD_TYPE'].isna().sum()
    missing_road_rank = all_links_df['ROAD_RANK'].isna().sum()

    print(f"- 전체 서울 링크 수: {total_links:,} 개")
    print(f"- 제한속도(MAX_SPD)가 없거나 0인 링크 수: {missing_max_spd:,} 개 ({(missing_max_spd/total_links)*100:.2f}%)")
    print(f"- 차선 수(LANES)가 없거나 0인 링크 수: {missing_lanes:,} 개 ({(missing_lanes/total_links)*100:.2f}%)")
    print(f"- 도로유형(ROAD_TYPE)이 없는 링크 수: {missing_road_type:,} 개 ({(missing_road_type/total_links)*100:.2f}%)")
    print(f"- 도로등급(ROAD_RANK)이 없는 링크 수: {missing_road_rank:,} 개 ({(missing_road_rank/total_links)*100:.2f}%)")

    if missing_max_spd == 0 and missing_lanes == 0 and missing_road_type == 0 and missing_road_rank == 0:
        print("  -> [결론] 모든 링크에 분석에 필요한 주요 속성(제한속도, 차선 수, 도로유형, 도로등급)이 존재합니다.")
    else:
        print("  -> [결론] 일부 링크에 속성 정보가 누락되어 있어, 분석 시 '0' 또는 'N/A' 그룹으로 집계됩니다.")

    print("\n" + "=" * 80)
    print("2. T-data 결합 현황 요약")
    print("=" * 80)

    total_unmatched = total_links - len(matched_link_ids)
    print(f"- 전체 서울 링크 수: {total_links:,} 개")
    print(f"- T-data 매칭 성공 링크 수: {len(matched_link_ids):,} 개 (전체의 {(len(matched_link_ids)/total_links)*100:.2f}%)")
    print(f"- T-data 속도 미보유 링크 수: {total_unmatched:,} 개 (전체의 {(total_unmatched/total_links)*100:.2f}%)")

    # 도로 특성별 결합률 심층 분석
    analyze_match_rate_by_attribute(all_links_df, matched_link_ids, 'ROAD_RANK', '도로등급', 3)
    analyze_match_rate_by_attribute(all_links_df, matched_link_ids, 'ROAD_TYPE', '도로유형', 4)
    analyze_match_rate_by_attribute(all_links_df, matched_link_ids, 'LANES', '차선 수', 5)
    analyze_match_rate_by_attribute(all_links_df, matched_link_ids, 'MAX_SPD', '제한속도', 6)


if __name__ == "__main__":
    main()