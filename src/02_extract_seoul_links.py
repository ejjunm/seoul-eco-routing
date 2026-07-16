from pathlib import Path

import geopandas as gpd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
ROAD_RAW_DIR = RAW_DATA_DIR / "road"
BOUNDARY_RAW_DIR = RAW_DATA_DIR / "boundary"
INTERIM_DATA_DIR = PROJECT_ROOT / "data" / "interim"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

LINK_PATH = ROAD_RAW_DIR / "MOCT_LINK.shp"
BOUNDARY_PATH = BOUNDARY_RAW_DIR / "seoul_admin_boundary.geojson"
OUT_SHP = INTERIM_DATA_DIR / "seoul_link.shp"
OUT_CSV = PROCESSED_DATA_DIR / "seoul_link_attr.csv"


def load_seoul_boundary(target_crs) -> "gpd.GeoSeries":
    boundary = gpd.read_file(BOUNDARY_PATH)
    if boundary.crs is None:
        boundary = boundary.set_crs("EPSG:4326")
    seoul_polygon = boundary.union_all()
    return gpd.GeoSeries([seoul_polygon], crs=boundary.crs).to_crs(target_crs)


def main() -> None:
    link = gpd.read_file(LINK_PATH)

    print("전체 링크 수:", link.shape)
    print("좌표계:", link.crs)

    # 서울시 25개 자치구 경계(seoul-maps, EPSG:4326)를 하나로 합쳐 사용합니다.
    seoul_boundary = load_seoul_boundary(link.crs)

    seoul_link = link[link.intersects(seoul_boundary.iloc[0])].copy()

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
