from pathlib import Path

import geopandas as gpd
from shapely.geometry import box


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
ROAD_RAW_DIR = RAW_DATA_DIR / "road"
INTERIM_DATA_DIR = PROJECT_ROOT / "data" / "interim"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

LINK_PATH = ROAD_RAW_DIR / "MOCT_LINK.shp"
OUT_SHP = INTERIM_DATA_DIR / "seoul_link.shp"
OUT_CSV = PROCESSED_DATA_DIR / "seoul_link_attr.csv"


def main() -> None:
    link = gpd.read_file(LINK_PATH)

    print("전체 링크 수:", link.shape)
    print("좌표계:", link.crs)

    # 서울 대략 영역입니다. 정확한 서울 행정경계가 아니라 bbox 필터입니다.
    seoul_bbox = gpd.GeoDataFrame(
        geometry=[box(126.75, 37.40, 127.20, 37.72)],
        crs="EPSG:4326",
    ).to_crs(link.crs)

    seoul_link = link[link.intersects(seoul_bbox.geometry.iloc[0])].copy()

    print("서울 추정 링크 수:", seoul_link.shape)
    print(seoul_link[["LINK_ID", "F_NODE", "T_NODE", "ROAD_NAME", "LENGTH", "MAX_SPD"]].head())

    INTERIM_DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    seoul_link.to_file(OUT_SHP, encoding="utf-8")
    seoul_link.drop(columns="geometry").to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print("서울 링크 Shapefile 저장:", OUT_SHP)
    print("서울 링크 속성 CSV 저장:", OUT_CSV)


if __name__ == "__main__":
    main()
