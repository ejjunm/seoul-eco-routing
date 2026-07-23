from pathlib import Path

import pandas as pd


# 1. 경로 정의
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "verification_suite" / "temp_outputs"
SEOUL_LINK_ATTR_PATH = OUTPUT_DIR / "seoul_link_attr.csv"
SPEED_MERGED_PATH = OUTPUT_DIR / "seoul_link_speed_merged.csv"

LINK_KEY = "LINK_ID"


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
    unmatched_link_ids = all_link_ids - matched_link_ids

    unmatched_links_df = all_links_df[all_links_df[LINK_KEY].isin(unmatched_link_ids)].copy()

    # 5. 분석 및 결과 출력
    print("\n" + "=" * 80)
    print("1. 전체 링크의 속성 완전성 검증")
    print("=" * 80)

    total_links = len(all_links_df)
    missing_max_spd = all_links_df['MAX_SPD'].fillna(0).le(0).sum()
    missing_road_rank = all_links_df['ROAD_RANK'].isna().sum()

    print(f"- 전체 서울 링크 수: {total_links:,} 개")
    print(f"- 제한속도(MAX_SPD)가 없거나 0인 링크 수: {missing_max_spd:,} 개 ({(missing_max_spd/total_links)*100:.2f}%)")
    print(f"- 도로등급(ROAD_RANK)이 없는 링크 수: {missing_road_rank:,} 개 ({(missing_road_rank/total_links)*100:.2f}%)")
    if missing_max_spd == 0 and missing_road_rank == 0:
        print("  -> [결론] 모든 링크에 제한속도와 도로등급 정보가 존재하여 속도 추정의 기반이 됩니다.")
    else:
        print("  -> [결론] 일부 링크에 속성 정보가 누락되어 있어, 속도 추정 시 예외 처리가 필요합니다.")

    print("\n" + "=" * 80)
    print("2. T-data 속도 미보유 링크 특성 분석")
    print("=" * 80)

    total_unmatched = len(unmatched_links_df)
    print(f"- 전체 서울 링크 수: {total_links:,} 개")
    print(f"- T-data 매칭 성공 링크 수: {len(matched_link_ids):,} 개")
    print(f"- T-data 속도 미보유 링크 수: {total_unmatched:,} 개 (전체의 {(total_unmatched/total_links)*100:.2f}%)")

    if total_unmatched > 0:
        print("\n--- [분석 1] 속도 미보유 링크의 도로등급(ROAD_RANK) 분포 ---")
        road_rank_dist = unmatched_links_df['ROAD_RANK'].value_counts(dropna=False).sort_index()
        print(road_rank_dist.to_string())
        print("\n  -> [진단] 위 분포를 통해 어떤 종류의 도로에서 주로 속도 데이터가 누락되는지 파악할 수 있습니다.")
        print("     (예: '104' 등급 도로가 대부분이라면, 간선/이면도로의 속도 데이터 확보가 어렵다는 의미)")

        print("\n--- [분석 2] 속도 미보유 링크의 제한속도(MAX_SPD) 유효성 ---")
        unmatched_missing_max_spd = unmatched_links_df['MAX_SPD'].fillna(0).le(0).sum()
        print(f"- 속도 미보유 링크 중, 제한속도가 없거나 0인 링크 수: {unmatched_missing_max_spd:,} 개 (미보유 링크 중 {(unmatched_missing_max_spd/total_unmatched)*100:.2f}%)")
        if unmatched_missing_max_spd == 0:
            print("\n  -> [결론] 모든 속도 미보유 링크에 유효한 'MAX_SPD' 값이 존재합니다.")
            print("     '제한속도(MAX_SPD) × 통행 효율 계수(α)' 방식의 속도 추정 전략을 바로 적용할 수 있습니다.")
        else:
            print("\n  -> [결론] 일부 속도 미보유 링크에는 'MAX_SPD' 값도 없어, 이들에 대한 별도의 처리 방안이 필요합니다.")

    print("\n" + "=" * 80)
    print("3. 도로 등급(ROAD_RANK)별 T-data 결합률 분석")
    print("=" * 80)

    # 도로등급별 전체 링크 수 집계
    total_by_rank = all_links_df.groupby('ROAD_RANK').agg(
        total_links=('LINK_ID', 'count')
    ).reset_index()

    # T-data와 결합된 링크만 필터링하여 도로등급별로 집계
    matched_links_df = all_links_df[all_links_df[LINK_KEY].isin(matched_link_ids)]
    matched_by_rank = matched_links_df.groupby('ROAD_RANK').agg(
        matched_links=('LINK_ID', 'count')
    ).reset_index()

    # 전체 링크 수와 결합 성공 링크 수를 병합하고 결합률 계산
    rank_analysis = pd.merge(total_by_rank, matched_by_rank, on='ROAD_RANK', how='left')
    rank_analysis['matched_links'] = rank_analysis['matched_links'].fillna(0).astype(int)
    rank_analysis['match_rate(%)'] = (rank_analysis['matched_links'] / rank_analysis['total_links']) * 100

    rank_analysis = rank_analysis.sort_values('ROAD_RANK')

    rank_analysis.rename(columns={
        'ROAD_RANK': '도로등급',
        'total_links': '전체 링크 수',
        'matched_links': '결합 성공 링크 수',
        'match_rate(%)': '결합률 (%)'
    }, inplace=True)

    print(rank_analysis.to_string(index=False, formatters={'결합률 (%)': '{:.2f}'.format}))
    print("\n  -> [진단] 위 표는 어떤 도로 등급에서 T-data 결합률이 높은지/낮은지 보여줍니다.")
    print("     결합률이 낮은 등급의 도로는 속도 정보가 부족하여, 속도 추정 모델의 중요성이 더 큽니다.")


if __name__ == "__main__":
    main()