"""서울 전 도로 링크의 보고서용 도로망 실루엣 지도를 생성한다.

속도·에너지 색상 없이 서울 경계와 교차하는 63,548개 방향성 링크를 한 색으로
그린다. 같은 방향의 중복 링크도 그대로 표시하므로 실제 경로탐색 도로망의 밀도를
보여 주는 그림이다.

사용:
    python src/eda/plot_network_silhouette.py
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LINK_SHP = PROJECT_ROOT / "data" / "interim" / "seoul_link.shp"
BOUNDARY_PATH = PROJECT_ROOT / "data" / "raw" / "boundary" / "seoul_admin_boundary.geojson"
OUT_DIR = PROJECT_ROOT / "docs" / "figures" / "network"
OUT_PATH = OUT_DIR / "01_seoul_all_links_silhouette.png"


def main() -> None:
    if not LINK_SHP.exists():
        raise SystemExit(f"서울 링크 Shapefile이 없습니다: {LINK_SHP}")

    links = gpd.read_file(LINK_SHP)[["LINK_ID", "geometry"]]
    if links.empty:
        raise SystemExit("서울 링크가 비어 있습니다.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 9), facecolor="white")

    # 경계는 도로망의 공간 범위만 보조적으로 보여 주고, 본문은 링크 실루엣이다.
    if BOUNDARY_PATH.exists():
        boundary = gpd.read_file(BOUNDARY_PATH).to_crs(links.crs)
        boundary.boundary.plot(ax=ax, color="#b8c2cc", linewidth=0.45, zorder=1)

    links.plot(ax=ax, color="#263746", linewidth=0.16, alpha=0.86, zorder=2)
    ax.set_axis_off()
    ax.set_title("Seoul road-network silhouette (63,548 directed links)", pad=12, fontsize=14)
    plt.tight_layout()
    plt.savefig(OUT_PATH, dpi=240, bbox_inches="tight", facecolor="white")
    plt.close()

    print(f"Saved: {OUT_PATH} | links: {len(links):,}")


if __name__ == "__main__":
    main()
