from pathlib import Path

import geopandas as gpd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
ROAD_RAW_DIR = RAW_DATA_DIR / "road"
LINK_PATH = ROAD_RAW_DIR / "MOCT_LINK.shp"


def main() -> None:
    link = gpd.read_file(LINK_PATH)

    print("링크 데이터 크기:", link.shape)
    print("컬럼명:")
    print(link.columns)
    print("좌표계:")
    print(link.crs)
    print("상위 5개:")
    print(link.head())


if __name__ == "__main__":
    main()
