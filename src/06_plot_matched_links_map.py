from pathlib import Path

import geopandas as gpd
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INTERIM_DATA_DIR = PROJECT_ROOT / "data" / "interim"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
MPL_CONFIG_DIR = PROJECT_ROOT / ".matplotlib"

MPL_CONFIG_DIR.mkdir(exist_ok=True)

import os

os.environ["MPLCONFIGDIR"] = str(MPL_CONFIG_DIR)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

SEOUL_LINK_SHP = INTERIM_DATA_DIR / "seoul_link.shp"
MATCHED_LINKS_PATH = PROCESSED_DATA_DIR / "matched_link_ids.csv"
OUT_PNG = PROCESSED_DATA_DIR / "matched_links_map.png"
OUT_HIGHLIGHT_PNG = PROCESSED_DATA_DIR / "matched_links_map_highlight.png"
OUT_GEOJSON = PROCESSED_DATA_DIR / "matched_links.geojson"


def main() -> None:
    seoul_links = gpd.read_file(SEOUL_LINK_SHP)
    matched_ids = pd.read_csv(
        MATCHED_LINKS_PATH,
        usecols=["LINK_ID"],
        dtype={"LINK_ID": str},
    )

    seoul_links["LINK_ID"] = seoul_links["LINK_ID"].astype(str)
    is_matched = seoul_links["LINK_ID"].isin(set(matched_ids["LINK_ID"]))
    matched = seoul_links[is_matched].copy()
    unmatched = seoul_links[~is_matched].copy()

    matched.to_crs(epsg=4326).to_file(OUT_GEOJSON, driver="GeoJSON")

    fig, ax = plt.subplots(figsize=(10, 10))
    seoul_links.plot(ax=ax, color="#d9d9d9", linewidth=0.15, alpha=0.45)
    matched.plot(ax=ax, color="#d62728", linewidth=0.9, alpha=0.95)

    ax.set_title("T-data Matched Links on Seoul Link Network", fontsize=15, pad=12)
    ax.set_axis_off()
    ax.text(
        0.01,
        0.01,
        f"Seoul links: {len(seoul_links):,} / matched links: {len(matched):,}",
        transform=ax.transAxes,
        fontsize=10,
        color="#333333",
        bbox={"facecolor": "white", "edgecolor": "#cccccc", "alpha": 0.85},
    )

    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=220)
    plt.close(fig)

    # 매칭/미매칭을 둘 다 눈에 띄게 칠한 버전: 미매칭 링크가 얼마나, 어디에 몰려있는지 보기 위함
    fig2, ax2 = plt.subplots(figsize=(10, 10))
    unmatched.plot(ax=ax2, color="#1f77b4", linewidth=0.35, alpha=0.75)
    matched.plot(ax=ax2, color="#d62728", linewidth=0.9, alpha=0.95)

    ax2.set_title("Matched (red) vs Unmatched (blue) Seoul Links", fontsize=15, pad=12)
    ax2.set_axis_off()
    ax2.text(
        0.01,
        0.01,
        f"Seoul links: {len(seoul_links):,} / matched: {len(matched):,} / unmatched: {len(unmatched):,}",
        transform=ax2.transAxes,
        fontsize=10,
        color="#333333",
        bbox={"facecolor": "white", "edgecolor": "#cccccc", "alpha": 0.85},
    )

    fig2.tight_layout()
    fig2.savefig(OUT_HIGHLIGHT_PNG, dpi=220)
    plt.close(fig2)

    print("서울 링크 수:", len(seoul_links))
    print("매칭 링크 수:", len(matched))
    print("미매칭 링크 수:", len(unmatched))
    print("지도 이미지 저장:", OUT_PNG)
    print("매칭/미매칭 강조 지도 저장:", OUT_HIGHLIGHT_PNG)
    print("매칭 링크 GeoJSON 저장:", OUT_GEOJSON)


if __name__ == "__main__":
    main()
