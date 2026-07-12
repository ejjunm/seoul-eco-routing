from pathlib import Path

import geopandas as gpd
from shapely.geometry import box


BASE_DIR = Path(__file__).resolve().parent
LINK_PATH = BASE_DIR / "MOCT_LINK.shp"
OUT_SHP = BASE_DIR / "seoul_link.shp"
OUT_CSV = BASE_DIR / "seoul_link_attr.csv"


link = gpd.read_file(LINK_PATH)

print("전체 링크 수:", link.shape)
print("좌표계:", link.crs)

# 서울시 대략 영역입니다. 정확한 서울 행정경계가 아니라 bbox 필터입니다.
seoul_bbox = gpd.GeoDataFrame(
    geometry=[box(126.75, 37.40, 127.20, 37.72)],
    crs="EPSG:4326",
).to_crs(link.crs)

seoul_link = link[link.intersects(seoul_bbox.geometry.iloc[0])].copy()

print("서울 추정 링크 수:", seoul_link.shape)
print(seoul_link[["LINK_ID", "F_NODE", "T_NODE", "ROAD_NAME", "LENGTH", "MAX_SPD"]].head())

seoul_link.to_file(OUT_SHP, encoding="utf-8")
seoul_link.drop(columns="geometry").to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
