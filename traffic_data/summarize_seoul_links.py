from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "seoul_link_attr.csv"


df = pd.read_csv(CSV_PATH, dtype={"LINK_ID": str, "F_NODE": str, "T_NODE": str})

print("서울 추정 링크 속성 데이터 크기:", df.shape)
print("주요 컬럼 미리보기:")
print(df[["LINK_ID", "F_NODE", "T_NODE", "ROAD_NAME", "LENGTH", "MAX_SPD", "ROAD_RANK", "ROAD_TYPE", "LANES"]].head())

print("도로 등급 분포:")
print(df["ROAD_RANK"].value_counts(dropna=False).sort_index())

print("제한 속도 분포:")
print(df["MAX_SPD"].value_counts(dropna=False).sort_index())

print("링크 길이 통계:")
print(df["LENGTH"].describe())
