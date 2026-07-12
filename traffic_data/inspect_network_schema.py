from pathlib import Path

import geopandas as gpd


BASE_DIR = Path(__file__).resolve().parent
LINK_PATH = BASE_DIR / "MOCT_LINK.shp"


link = gpd.read_file(LINK_PATH)

print("링크 데이터 크기:", link.shape)
print("컬럼명:")
print(link.columns)
print("좌표계:")
print(link.crs)
print("상위 5개 행:")
print(link.head())
