
import sys
from pathlib import Path
import polars as pl

# 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parents[1]
INTERIM_DATA_DIR = PROJECT_ROOT / "data" / "interim"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

# 검증할 파일 목록
FILES_TO_VERIFY = [
    {
        "path": INTERIM_DATA_DIR / "seoul_link_speed_5min_hourly.csv",
        "name": "5분 단위 속도 집계 데이터",
        "primary_key": ["LINK_ID", "기준일", "시간코드"],
        "date_column": "기준일"
    },
    {
        "path": PROCESSED_DATA_DIR / "seoul_link_dimension.csv",
        "name": "도로 링크 속성 데이터",
        "primary_key": ["LINK_ID"],
        "date_column": None  # 날짜 컬럼 없음
    },
    {
        "path": PROCESSED_DATA_DIR / "seoul_link_speed_fact.csv",
        "name": "도로 링크 속도 최종 팩트 데이터",
        "primary_key": ["LINK_ID", "기준일", "시간코드"],
        "date_column": "기준일"
    }
]

def verify_file(file_path, file_name, primary_key, date_column=None):
    """
    단일 데이터 파일의 무결성을 검증합니다.
    1. 고유 날짜 목록 확인 (날짜 컬럼이 있는 경우)
    2. 기본 키(Primary Key) 기준 중복 데이터 확인
    """
    print(f"--- [{file_name}] 검증 시작 ---")
    print(f"   - 파일 경로: {file_path}")
    print("-" * 70)

    # 1. 파일 존재 여부 확인
    if not file_path.exists():
        print(f"오류: 파일을 찾을 수 없습니다.")
        return

    # 2. 데이터 읽기
    try:
        df = pl.read_csv(
            file_path,
            encoding="utf-8",
            schema_overrides={key: pl.String for key in primary_key if key is not None}
        )
        print(f"파일 읽기 성공. 전체 행 수: {len(df):,} 건")
    except Exception as e:
        print(f"오류: 파일을 읽는 중 에러가 발생했습니다: {e}")
        return

    # 3. 날짜 컬럼 확인
    if date_column:
        if date_column in df.columns:
            stored_dates = sorted(df[date_column].unique().to_list())
            print("[저장된 날짜 확인]")
            if not stored_dates:
                print(" - 파일에 저장된 날짜 정보가 없습니다.")
            else:
                print(f" - {len(stored_dates)}개의 고유한 날짜를 발견했습니다:")
                print(f"   {stored_dates}")
        else:
            print("[저장된 날짜 확인]")
            print(f" - 경고: '{date_column}' 컬럼을 파일에서 찾을 수 없습니다.")

    # 4. 기본 키 중복 확인
    print("[기본 키 중복 확인]")
    
    current_primary_key = list(primary_key)
    missing_keys = [key for key in current_primary_key if key not in df.columns]
    if missing_keys:
        # 깨진 컬럼명에 대한 특별 처리
        if file_name == "도로 링크 속도 최종 팩트 데이터":
            actual_cols = df.columns
            if len(actual_cols) > 2:
                # 'LINK_ID' 다음 두 컬럼을 '기준일', '시간코드'로 간주
                current_primary_key = [actual_cols[0], actual_cols[1], actual_cols[2]]
                print(f" - 경고: 컬럼명이 깨져있어, {current_primary_key} 기준으로 중복 검사를 시도합니다.")
            else:
                 print(f" - 오류: 기본 키 컬럼을 식별할 수 없어 중복 검사를 중단합니다.")
                 return
        else:
            current_primary_key = [key for key in current_primary_key if key in df.columns]
            if not current_primary_key:
                print(" - 중복 검사를 수행할 유효한 기본 키가 없습니다.")
                return
            print(f" - 경고: 기본 키 컬럼 {missing_keys} 을(를) 파일에서 찾을 수 없습니다. {current_primary_key} 기준으로 검사를 진행합니다.")

    duplicates = (
        df.group_by(current_primary_key)
        .len()
        .filter(pl.col("len") > 1)
    )

    if duplicates.is_empty():
        print(f"통과: 기본 키 ({', '.join(current_primary_key)}) 기준 중복된 데이터가 없습니다.")
    else:
        print(f"실패: 기본 키 기준 중복된 데이터가 있습니다.")
        print("   - 아래는 중복된 항목의 일부입니다:")
        print(duplicates.head(5))

def main():
    """메인 검증 파이프라인"""
    print("================================================================")
    print("     데이터 파일 무결성 검증 스크립트")
    print("================================================================")
    for file_info in FILES_TO_VERIFY:
        verify_file(
            file_path=file_info["path"],
            file_name=file_info["name"],
            primary_key=file_info["primary_key"],
            date_column=file_info["date_column"]
        )
    print("" + "="*70)
    print("모든 검증이 완료되었습니다.")
    print("="*70)


if __name__ == "__main__":
    main()
