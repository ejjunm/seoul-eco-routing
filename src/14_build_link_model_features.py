"""Build static topology and slope features available for every Seoul link."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
LINK_ATTR_PATH = PROCESSED_DATA_DIR / "seoul_link_attr.csv"
DEM_PATH = PROCESSED_DATA_DIR / "seoul_link_dem_features.csv"
OUT_PATH = PROCESSED_DATA_DIR / "seoul_link_model_features.csv"


def build_node_features(links: pd.DataFrame) -> pd.DataFrame:
    incoming = links.groupby("T_NODE").agg(
        node_in_degree=("LINK_ID", "size"),
        incoming_max_spd_mean=("MAX_SPD", "mean"),
        incoming_lanes_mean=("LANES", "mean"),
    )
    outgoing = links.groupby("F_NODE").agg(
        node_out_degree=("LINK_ID", "size"),
        outgoing_max_spd_mean=("MAX_SPD", "mean"),
        outgoing_lanes_mean=("LANES", "mean"),
    )
    nodes = incoming.join(outgoing, how="outer").fillna(0.0)
    nodes["node_total_degree"] = nodes["node_in_degree"] + nodes["node_out_degree"]
    return nodes


def main() -> None:
    links = pd.read_csv(
        LINK_ATTR_PATH,
        usecols=["LINK_ID", "F_NODE", "T_NODE", "LANES", "MAX_SPD", "LENGTH"],
        dtype={"LINK_ID": str, "F_NODE": str, "T_NODE": str},
        encoding="utf-8-sig",
    )
    dem = pd.read_csv(
        DEM_PATH,
        usecols=["LINK_ID", "slope_pct", "abs_slope_pct"],
        dtype={"LINK_ID": str},
        encoding="utf-8-sig",
    )
    links = links.merge(dem, on="LINK_ID", how="left")
    nodes = build_node_features(links)

    feature = links[["LINK_ID", "F_NODE", "T_NODE", "MAX_SPD", "LANES", "LENGTH", "slope_pct", "abs_slope_pct"]].copy()
    for endpoint, prefix in [("F_NODE", "f_node"), ("T_NODE", "t_node")]:
        mapped = nodes.add_prefix(f"{prefix}_")
        feature = feature.merge(mapped, left_on=endpoint, right_index=True, how="left")

    feature["upstream_max_spd_mean"] = feature["f_node_incoming_max_spd_mean"].replace(0, np.nan).fillna(feature["MAX_SPD"])
    feature["downstream_max_spd_mean"] = feature["t_node_outgoing_max_spd_mean"].replace(0, np.nan).fillna(feature["MAX_SPD"])
    feature["upstream_lanes_mean"] = feature["f_node_incoming_lanes_mean"].replace(0, np.nan).fillna(feature["LANES"])
    feature["downstream_lanes_mean"] = feature["t_node_outgoing_lanes_mean"].replace(0, np.nan).fillna(feature["LANES"])
    feature["node_complexity"] = feature["f_node_node_total_degree"] + feature["t_node_node_total_degree"]
    feature["downstream_speed_delta"] = feature["MAX_SPD"] - feature["downstream_max_spd_mean"]

    feature["slope_pct_clipped"] = feature["slope_pct"].clip(-12.0, 12.0)
    feature["slope_outlier_flag"] = (feature["abs_slope_pct"] > 12.0).astype(int)
    feature["is_uphill"] = (feature["slope_pct_clipped"] > 0.5).astype(int)
    feature["is_downhill"] = (feature["slope_pct_clipped"] < -0.5).astype(int)
    feature["steep_uphill"] = (feature["slope_pct_clipped"] >= 3.0).astype(int)
    feature["slope_length_m"] = feature["slope_pct_clipped"] / 100.0 * feature["LENGTH"]
    feature["max_spd_x_lanes"] = feature["MAX_SPD"] * feature["LANES"]
    feature["length_x_node_complexity"] = feature["LENGTH"] * feature["node_complexity"]

    drop_columns = ["F_NODE", "T_NODE", "MAX_SPD", "LANES", "LENGTH", "slope_pct", "abs_slope_pct"]
    feature = feature.drop(columns=drop_columns)
    feature.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print("링크 모델 피처 저장:", OUT_PATH)
    print("링크 수:", len(feature), "| 컬럼 수:", len(feature.columns))
    print("경사 이상치 링크:", int(feature["slope_outlier_flag"].sum()))


if __name__ == "__main__":
    main()
