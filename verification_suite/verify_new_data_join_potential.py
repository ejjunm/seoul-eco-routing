from pathlib import Path
import pandas as pd
import polars as pl


def run_verification_with_new_data(new_data_path: Path, project_root: Path):
    """
    새로운 대용량 데이터 파일('20260726_5Min.csv')의 결합 가능성을 단계적으로 검증하고,
    전처리된 피처 파일을 생성합니다.

    파이프라인:
    1. [전처리] 대용량 원본 CSV를 Polars로 처리하여 필요한 컬럼만 담은 Parquet 파일로 저장 (캐싱)
    2. [로드] 분석에 필요한 기준 데이터(서울 링크, 공식 매핑 테이블) 로드
    3. [검증] 두 가지 시나리오(직접 결합, 간접 결합)에 대한 결합률 검증
    4. [출력] 검증 결과에 따라 최적의 방법으로 결합된 최종 피처셋을 Parquet 파일로 생성
    """
    print(f"--- 새로운 데이터({new_data_path.name}) 결합 및 전처리 파이프라인 시작 ---")

    # --- 0. 경로 및 설정 ---
    output_dir = project_root / "verification_suite" / "temp_outputs"
    output_dir.mkdir(exist_ok=True)
    preprocessed_path = output_dir / f"{new_data_path.stem}_preprocessed.parquet"

    if not new_data_path.exists():
        print(f"❌ 오류: 검증할 새로운 데이터 파일을 찾을 수 없습니다 - {new_data_path}")
        return

    # --- 1. [전처리] 대용량 원본 파일 처리 및 캐싱 ---
    print("\n" + "="*50)
    print("  Phase 1: 대용량 원본 파일 전처리")
    print("="*50)

    if preprocessed_path.exists():
        print(f"⚡ [Cache] 기존에 전처리된 파일이 있습니다. 로드합니다: {preprocessed_path}")
        new_df = pl.read_parquet(preprocessed_path)
    else:
        print(f"🔄 [Compute] 전처리된 파일이 없어 원본({new_data_path.name})을 처리합니다.")
        try:
            # has_header=True로 설정하여 CSV의 첫 줄을 헤더로 올바르게 인식합니다.
            # 이 설정이 오류의 근본 원인을 해결합니다.
            lf_new = pl.scan_csv(new_data_path, has_header=True)

            # 사용할 컬럼만 선택하고, 요청에 따라 CREATHM과 ROADINSTTCD는 제외합니다.
            required_cols = ['CREATDE', 'LINKID', 'PASNGSPED', 'PASNGTIME']
            
            # 원본 파일에 필요한 컬럼이 모두 있는지 확인
            if not all(col in lf_new.columns for col in required_cols):
                missing = [col for col in required_cols if col not in lf_new.columns]
                raise ValueError(f"CSV 파일에 필요한 컬럼이 없습니다: {missing}")

            # 타입 변환, 결측치 처리 및 집계
            lf_processed = (
                lf_new.select(required_cols)
                .with_columns([
                    pl.col("LINKID").cast(pl.Utf8),
                    # strict=False를 사용하여 변환 중 오류가 발생하면 null로 처리합니다. (추가적인 안정성 확보)
                    pl.col("PASNGSPED").cast(pl.Float64, strict=False),
                    pl.col("PASNGTIME").cast(pl.Float64, strict=False),
                    pl.col("CREATDE").cast(pl.Utf8),
                ])
                .filter(pl.col('LINKID').is_not_null())
                .filter(pl.col('PASNGSPED').is_not_null()) # 변환에 실패한 행(null)을 제거합니다.
                # CREATHM을 제외하고 링크별로 하나의 속도만 가져오도록 평균 집계
                .group_by(['CREATDE', 'LINKID'], maintain_order=True)
                .agg([
                    pl.col('PASNGSPED').mean().alias('PASNGSPED_AVG'),
                    pl.col('PASNGTIME').mean().alias('PASNGTIME_AVG'),
                ])
                # 원본 LINKID 보존을 위해 이름 변경
                .rename({"LINKID": "LINKID_RAW"}) 
            )
            print("  - Polars 처리 계획 실행 중 (대용량 파일은 시간이 소요될 수 있습니다)...")
            new_df = lf_processed.collect() # 이 시점에 실제 파일 읽기 및 처리가 실행됨

            print(f"  - 전처리 완료. 결과를 Parquet 파일로 저장합니다: {preprocessed_path}")
            new_df.write_parquet(preprocessed_path)

        except Exception as e:
            print(f"❌ 오류: 대용량 CSV 파일 처리 중 오류 발생: {e}")
            return

    print(f"  - 전처리된 데이터 로드 완료: {new_df.height:,} 행")
    print("  - 스키마:", new_df.schema)

    # --- 2. [로드] 기준 데이터 로드 ---
    print("\n" + "="*50)
    print("  Phase 2: 결합을 위한 기준 데이터 로드")
    print("="*50)
    seoul_link_attr_path = project_root / "data" / "processed" / "seoul_link_attr.csv"
    if not seoul_link_attr_path.exists():
        print(f"❌ 오류: 서울 링크 속성 파일(seoul_link_attr.csv)을 찾을 수 없습니다.")
        return
    official_mapping_path = project_root / "data" / "raw" / "traffic" / "서울특별시 교통소통 표준링크 매핑정보_20250306.xlsx"
    if not official_mapping_path.exists():
        print(f"❌ 오류: 공식 매핑 테이블을 찾을 수 없습니다: {official_mapping_path}")
        return

    seoul_links_df = pl.read_csv(seoul_link_attr_path, dtypes={"LINK_ID": pl.Utf8})
    seoul_standard_link_ids = set(seoul_links_df["LINK_ID"].unique())
    print(f"  - 기준 서울 표준 링크: {len(seoul_standard_link_ids):,} 개 로드")

    mapping_pd = pd.read_excel(official_mapping_path, dtype={"서비스링크": str, "표준링크아이디": str})
    mapping_df = pl.from_pandas(mapping_pd).filter(pl.col("표준링크아이디").is_not_null())
    service_to_standard_map = dict(mapping_df.select(["서비스링크", "표준링크아이디"]).iter_rows())
    print(f"  - 공식 매핑 테이블: {len(mapping_df):,} 개 로드")

    # --- 3. [검증] 결합 시나리오별 검증 ---
    print("\n" + "="*50)
    print("  Phase 3: 결합 시나리오별 검증")
    print("="*50)
    new_link_ids = set(new_df['LINKID_RAW'].unique())
    print(f"  - 새로운 데이터의 고유 'LINKID_RAW' 수: {len(new_link_ids):,} 개")

    # 시나리오 1: 'LINKID'가 표준 'LINK_ID'라고 가정하고 직접 결합
    print("\n[시나리오 1] 'LINKID'를 '표준 LINK_ID'로 간주하고 직접 결합")
    matched_direct = new_link_ids.intersection(seoul_standard_link_ids)
    # [수정] 결합률의 분모는 '새로운 데이터의 링크 수'가 아니라 '서울시 기준 링크 수'가 되어야 함.
    match_rate_direct = (len(matched_direct) / len(seoul_standard_link_ids)) * 100 if seoul_standard_link_ids else 0
    print(f"  - 결합 성공 링크 수: {len(matched_direct):,} / {len(seoul_standard_link_ids):,} 개")
    print(f"  - 서울 링크 기준 커버리지: {match_rate_direct:.2f}%")

    # 시나리오 2: 'LINKID'가 '서비스링크' ID라고 가정하고 간접 결합
    print("\n[시나리오 2] 'LINKID'를 '서비스링크'로 간주하고 공식 매핑 테이블 통해 결합")
    mappable_new_links = new_link_ids.intersection(set(service_to_standard_map.keys()))
    print(f"  - 1단계 (매핑 테이블): 새로운 데이터의 LINKID 중 {len(mappable_new_links):,}개가 매핑 테이블에 존재")

    if not mappable_new_links:
        match_rate_indirect = 0
        print("  - 매핑 테이블과 일치하는 'LINKID'가 없어 간접 결합을 진행할 수 없습니다.")
    else:
        mapped_standard_ids = {service_to_standard_map[link] for link in mappable_new_links}
        matched_indirect = mapped_standard_ids.intersection(seoul_standard_link_ids)
        # [수정] 결합률의 분모는 '새로운 데이터의 링크 수'가 아니라 '서울시 기준 링크 수'가 되어야 함.
        match_rate_indirect = (len(matched_indirect) / len(seoul_standard_link_ids)) * 100 if seoul_standard_link_ids else 0
        print(f"  - 2단계 (서울 링크): 매핑된 표준링크 중 {len(matched_indirect):,}개가 실제 서울 링크에 존재")
        print(f"  - 최종 결합 성공 링크 수: {len(matched_indirect):,} / {len(seoul_standard_link_ids):,} 개")
        print(f"  - 서울 링크 기준 커버리지: {match_rate_indirect:.2f}%")

    # --- 4. [출력] 최종 진단 및 피처 파일 생성 ---
    print("\n" + "="*50)
    print("  Phase 4: 최종 진단 및 피처 파일 생성")
    print("="*50)

    final_df = None
    join_method = None

    if match_rate_direct > match_rate_indirect and match_rate_direct > 10:
        print("✅ [진단] 'LINKID'는 '표준 LINK_ID'일 가능성이 높습니다 (직접 결합률 우세).")
        join_method = 'direct'
        final_df = new_df.lazy().rename({'LINKID_RAW': 'LINK_ID'}).join(
            seoul_links_df.lazy().select('LINK_ID'), on='LINK_ID', how='inner'
        ).select(['CREATDE', 'LINK_ID', 'PASNGSPED_AVG', 'PASNGTIME_AVG']).collect()

    elif match_rate_indirect > match_rate_direct and match_rate_indirect > 10:
        print("✅ [진단] 'LINKID'는 '서비스링크 ID'일 가능성이 높습니다 (간접 결합률 우세).")
        join_method = 'indirect'
        final_df = new_df.lazy().join(
            mapping_df.lazy(), left_on='LINKID_RAW', right_on='서비스링크', how='inner'
        ).rename({'표준링크아이디': 'LINK_ID'}).join(
            seoul_links_df.lazy().select('LINK_ID'), on='LINK_ID', how='inner'
        ).select(['CREATDE', 'LINK_ID', 'PASNGSPED_AVG', 'PASNGTIME_AVG', 'LINKID_RAW']).collect()

    else:
        print(f"⚠️ [진단] 결합률이 낮아({match_rate_direct:.2f}%, {match_rate_indirect:.2f}%) 활용이 어렵습니다.")

    if final_df is not None and not final_df.is_empty():
        final_output_path = output_dir / f"{new_data_path.stem}_features_joined.parquet"
        print(f"  - [결론] '{join_method}' 방식으로 {final_df.height:,}개의 레코드를 성공적으로 결합했습니다.")
        print(f"  - 최종 피처셋을 다음 경로에 저장합니다: {final_output_path}")
        final_df.write_parquet(final_output_path)
    else:
        print("  - [결론] 결합률이 낮아 최종 피처셋을 생성하지 않았습니다.")

    print(f"\n--- {new_data_path.name} 검증 및 전처리 완료 ---")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    new_data_file_path = project_root / "verification_suite" / "temp_data" / "20260726_5Min.csv"

    run_verification_with_new_data(new_data_file_path, project_root)