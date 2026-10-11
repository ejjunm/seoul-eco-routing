"""마을버스 ML 불확실성·정책분류·HDBSCAN 결과의 발표용 EDA를 만든다.

입력
  data/processed/model_uncertainty/test_predictions.csv
  data/processed/transit/{route_carbon_uncertainty,route_typology_hdbscan,
                          hdbscan_sensitivity,route_feasibility,route_demand,
                          route_operations,route_links}.csv
  data/interim/seoul_link.shp

출력
  docs/figures/transit_ml_eda/01_*.png ... 12_*.png
  data/processed/transit_eda/*.csv

사용: python src/eda/06_transit_ml_eda.py
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[2]
TRANSIT = ROOT / "data" / "processed" / "transit"
MODEL_UNCERTAINTY = ROOT / "data" / "processed" / "model_uncertainty"
OUTPUT = ROOT / "data" / "processed" / "transit_eda"
FIGURES = ROOT / "docs" / "figures" / "transit_ml_eda"
LINK_SHP = ROOT / "data" / "interim" / "seoul_link.shp"
BOUNDARY = ROOT / "data" / "raw" / "boundary" / "seoul_admin_boundary.geojson"

BLUE = "#0072B2"
SKY = "#56B4E9"
GREEN = "#009E73"
ORANGE = "#E69F00"
RED = "#D55E00"
PURPLE = "#CC79A7"
GRAY = "#7A7A7A"
LIGHT_GRAY = "#D9D9D9"
CLASS_COLORS = {1: BLUE, 2: ORANGE, 3: GREEN, 4: PURPLE}
CLASS_NAMES = {1: "1 증편·지원", 2: "2 소형차 전환", 3: "3 현행 유지", 4: "4 조정 검토"}
COMPARISON_COLORS = {
    "버스 우위(구간 전체)": GREEN,
    "경계/불확실": ORANGE,
    "승용차 우위(구간 전체)": RED,
}
HDB_FEATURES = [
    "catchment_elderly_share", "catchment_elderly_day", "no_alt_boarding_share",
    "bus_g_per_pkm", "route_cars_per_1000", "boardings_per_day", "slope_mean",
    "one_lane_share", "day_speed_kmh", "trips_per_day",
]


def set_style() -> None:
    plt.rcParams.update({
        "font.family": "Malgun Gothic",
        "axes.unicode_minus": False,
        "font.size": 10,
        "axes.titlesize": 15,
        "axes.labelsize": 11,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
    })


def save(fig: plt.Figure, filename: str) -> None:
    fig.tight_layout()
    fig.savefig(FIGURES / filename, dpi=220, bbox_inches="tight")
    plt.close(fig)


def load_routes() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    carbon = pd.read_csv(TRANSIT / "route_carbon_uncertainty.csv", dtype={"ROUTE_ID": str})
    carbon["노선명"] = carbon["노선명_y"].fillna(carbon["노선명_x"])
    routes = carbon.loc[~carbon["load_qa_flag"]].copy()
    routes["interval_width"] = routes["bus_vs_car_upper"] - routes["bus_vs_car_lower"]
    routes["class_id"] = routes["class_id"].astype(int)

    hdb = pd.read_csv(TRANSIT / "route_typology_hdbscan.csv", dtype={"ROUTE_ID": str})
    feas = pd.read_csv(TRANSIT / "route_feasibility.csv", dtype={"ROUTE_ID": str})[
        ["ROUTE_ID", "slope_p90", "slope_mean", "one_lane_share", "congestion_ratio",
         "unobserved_share", "day_speed_kmh", "n_within_envelope"]
    ]
    demand = pd.read_csv(TRANSIT / "route_demand.csv", dtype={"ROUTE_ID": str})[
        ["ROUTE_ID", "route_cars_per_1000", "median_dist_to_station_m", "n_stops"]
    ]
    operations = pd.read_csv(TRANSIT / "route_operations.csv", dtype={"ROUTE_ID": str})[
        ["ROUTE_ID", "low_load_trip_share", "deficit_at_600", "deficit_at_900",
         "deficit_at_1200", "carbon_service_candidate"]
    ]
    routes = (routes.merge(feas, on="ROUTE_ID", how="left")
              .merge(demand, on="ROUTE_ID", how="left")
              .merge(operations, on="ROUTE_ID", how="left")
              .merge(hdb[["ROUTE_ID", "hdbscan_cluster", "hdbscan_type",
                          "membership_probability", "is_noise",
                          "catchment_elderly_share", "catchment_elderly_day",
                          "no_alt_boarding_share"]], on="ROUTE_ID", how="left"))
    speed = pd.read_csv(MODEL_UNCERTAINTY / "test_predictions.csv", dtype={"LINK_ID": str})
    sensitivity = pd.read_csv(TRANSIT / "hdbscan_sensitivity.csv")
    return routes, speed, sensitivity


def make_tables(routes: pd.DataFrame, speed: pd.DataFrame) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    summary = routes[[
        "ROUTE_ID", "노선명", "class_id", "class", "class_stable", "car_comparison",
        "dependence_score", "boardings_per_day", "avg_load", "bus_g_per_pkm",
        "bus_g_per_pkm_lower", "bus_g_per_pkm_upper", "bus_vs_car",
        "bus_vs_car_lower", "bus_vs_car_upper", "co2_saved_kg_per_day",
        "route_cars_per_1000", "slope_mean", "one_lane_share", "day_speed_kmh",
        "hdbscan_cluster", "is_noise",
    ]].sort_values(["class_id", "dependence_score"], ascending=[True, False])
    summary.to_csv(OUTPUT / "route_presentation_summary.csv", index=False, encoding="utf-8-sig")

    robust = routes[routes["car_comparison"] == "버스 우위(구간 전체)"].nlargest(
        20, "co2_saved_kg_per_day"
    )
    robust[["ROUTE_ID", "노선명", "class", "co2_saved_kg_per_day", "bus_vs_car",
            "bus_vs_car_upper", "avg_load", "boardings_per_day", "class_stable"]].to_csv(
        OUTPUT / "top_robust_carbon_benefit_routes.csv", index=False, encoding="utf-8-sig"
    )
    boundary = routes[routes["car_comparison"] != "버스 우위(구간 전체)"].sort_values(
        ["car_comparison", "bus_vs_car"], ascending=[True, False]
    )
    boundary[["ROUTE_ID", "노선명", "class", "car_comparison", "bus_vs_car_lower",
              "bus_vs_car", "bus_vs_car_upper", "avg_load", "class_stable"]].to_csv(
        OUTPUT / "carbon_boundary_routes.csv", index=False, encoding="utf-8-sig"
    )
    unstable = routes[~routes["class_stable"]].sort_values("interval_width", ascending=False)
    unstable[["ROUTE_ID", "노선명", "class", "class_if_low_energy", "class_if_high_energy",
              "bus_g_per_pkm_lower", "bus_g_per_pkm", "bus_g_per_pkm_upper",
              "interval_width"]].to_csv(
        OUTPUT / "classification_boundary_routes.csv", index=False, encoding="utf-8-sig"
    )

    class_summary = routes.groupby(["class_id", "class"], as_index=False).agg(
        노선수=("ROUTE_ID", "size"),
        하루승차_중앙=("boardings_per_day", "median"),
        평균탑승_중앙=("avg_load", "median"),
        승객km당CO2_중앙=("bus_g_per_pkm", "median"),
        분류안정_노선=("class_stable", "sum"),
        하루감축_합계kg=("co2_saved_kg_per_day", "sum"),
    )
    class_summary["분류안정률"] = class_summary["분류안정_노선"] / class_summary["노선수"]
    class_summary.to_csv(OUTPUT / "class_summary.csv", index=False, encoding="utf-8-sig")

    speed["raw_hit"] = speed["평균속도"].between(speed["q05_raw"], speed["q95_raw"])
    speed["conformal_hit"] = speed["평균속도"].between(speed["speed_lower"], speed["speed_upper"])
    speed["interval_width"] = speed["speed_upper"] - speed["speed_lower"]
    speed["abs_error"] = (speed["평균속도"] - speed["speed_median"]).abs()
    hourly = speed.groupby("시간코드", as_index=False).agg(
        n=("LINK_ID", "size"), raw_coverage=("raw_hit", "mean"),
        conformal_coverage=("conformal_hit", "mean"),
        mean_width_kmh=("interval_width", "mean"), mae_kmh=("abs_error", "mean"),
    )
    hourly.to_csv(OUTPUT / "speed_uncertainty_by_hour.csv", index=False, encoding="utf-8-sig")


def executive_summary(routes: pd.DataFrame, speed: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(13.33, 7.5))
    fig.suptitle("마을버스 ML 보완 결과: 효과는 크지만 분류 불확실성도 크다", fontsize=18, y=1.01)

    ax = axes[0, 0]
    counts = routes["car_comparison"].value_counts()
    order = ["버스 우위(구간 전체)", "경계/불확실", "승용차 우위(구간 전체)"]
    left = 0
    for label in order:
        value = int(counts.get(label, 0))
        ax.barh([0], [value], left=left, color=COMPARISON_COLORS[label], height=.55)
        ax.text(left + value / 2, 0, f"{value}개", ha="center", va="center", color="white", fontweight="bold")
        left += value
    ax.set_xlim(0, len(routes)); ax.set_yticks([]); ax.set_xlabel("노선 수")
    ax.set_title("승용차 대비 탄소 우위의 견고성", loc="left")
    ax.legend([Patch(color=COMPARISON_COLORS[x]) for x in order], order, frameon=False,
              loc="lower center", bbox_to_anchor=(.5, -0.42), ncol=3)

    ax = axes[0, 1]
    table = pd.crosstab(routes["class_id"], routes["class_stable"]).reindex(range(1, 5), fill_value=0)
    stable = table.get(True, pd.Series(0, index=table.index))
    unstable = table.get(False, pd.Series(0, index=table.index))
    x = np.arange(4)
    ax.bar(x, stable, color=BLUE, label="분류 안정")
    ax.bar(x, unstable, bottom=stable, color=ORANGE, label="경계")
    for i in range(4):
        ax.text(i, stable.iloc[i] / 2, str(int(stable.iloc[i])), ha="center", va="center", color="white")
        ax.text(i, stable.iloc[i] + unstable.iloc[i] / 2, str(int(unstable.iloc[i])), ha="center", va="center", color="white")
    ax.set_xticks(x, [CLASS_NAMES[i] for i in range(1, 5)], rotation=12)
    ax.set_ylabel("노선 수"); ax.set_title("정책 4분류 안정성", loc="left"); ax.legend(frameon=False)

    ax = axes[1, 0]
    raw = speed["평균속도"].between(speed["q05_raw"], speed["q95_raw"]).mean()
    calibrated = speed["평균속도"].between(speed["speed_lower"], speed["speed_upper"]).mean()
    values = [0.9, raw, calibrated]
    bars = ax.bar([0, 1, 2], values, color=[GRAY, SKY, BLUE], width=.62)
    ax.axhline(.9, color=RED, linewidth=1, linestyle="--")
    ax.set_ylim(.82, .96); ax.set_yticks(np.arange(.82, .961, .02), [f"{v:.0%}" for v in np.arange(.82, .961, .02)])
    ax.set_xticks([0, 1, 2], ["목표", "원시 분위수", "Conformal"])
    ax.set_title("별도 시험 링크의 속도구간 포함률", loc="left")
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, value + .004, f"{value:.1%}", ha="center")
    ax.text(.98, .08, "MAE 5.11 km/h · 평균 구간 폭 26.93 km/h",
            transform=ax.transAxes, ha="right", color=GRAY,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": .82, "pad": 2})

    ax = axes[1, 1]
    hcounts = routes["is_noise"].value_counts()
    clustered = int(hcounts.get(False, 0)); noise = int(hcounts.get(True, 0))
    ax.barh([0], [clustered], color=GRAY, height=.55)
    ax.barh([0], [noise], left=clustered, color=ORANGE, height=.55)
    ax.text(clustered/2, 0, f"군집 {clustered}", ha="center", va="center", color="white", fontweight="bold")
    ax.text(clustered + noise/2, 0, f"비정형 {noise}", ha="center", va="center", color="white", fontweight="bold")
    ax.set_yticks([]); ax.set_xlim(0, len(routes)); ax.set_xlabel("노선 수")
    ax.set_title("HDBSCAN: 안정적인 자연 군집 없음", loc="left")
    ax.text(.02, -.36, "실루엣 0.138 · 부분표본 ARI 0.000 · 정책분류와 ARI 0.015",
            transform=ax.transAxes, color=GRAY)
    save(fig, "01_executive_summary.png")


def carbon_dependence_scatter(routes: pd.DataFrame) -> None:
    xcut = routes["dependence_score"].median()
    ycut = routes["bus_g_per_pkm"].median()
    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    ax.axvspan(xcut, 1.01, color=BLUE, alpha=.035)
    ax.axhspan(routes["bus_g_per_pkm"].min() * .85, ycut, color=GREEN, alpha=.04)
    stable = routes[routes["class_stable"]]
    unstable = routes[~routes["class_stable"]]
    sizes_stable = 20 + 75 * np.sqrt(stable["boardings_per_day"] / routes["boardings_per_day"].max())
    sizes_unstable = 20 + 75 * np.sqrt(unstable["boardings_per_day"] / routes["boardings_per_day"].max())
    ax.scatter(stable["dependence_score"], stable["bus_g_per_pkm"], s=sizes_stable,
               color=BLUE, alpha=.72, label=f"분류 안정 {len(stable)}")
    ax.scatter(unstable["dependence_score"], unstable["bus_g_per_pkm"], s=sizes_unstable,
               facecolors="none", edgecolors=ORANGE, linewidths=1.3, label=f"경계 {len(unstable)}")
    ax.axvline(xcut, color=GRAY, linestyle="--", linewidth=1)
    ax.axhline(ycut, color=GRAY, linestyle="--", linewidth=1)
    ax.set_xlabel("교통약자 의존도 점수 → 높음")
    ax.set_ylabel("버스 승객 1명·km당 배출량 (gCO₂/pkm) → 낮을수록 효율적")
    ax.set_title("탄소효율 × 교통약자 의존도: 정책 4분류와 경계 노선")
    ax.legend(frameon=False, loc="upper left")
    labels = pd.concat([
        routes.nlargest(6, "co2_saved_kg_per_day"),
        routes.nlargest(5, "bus_vs_car"),
    ]).drop_duplicates("ROUTE_ID")
    for _, row in labels.iterrows():
        ax.annotate(row["노선명"], (row["dependence_score"], row["bus_g_per_pkm"]),
                    xytext=(4, 4), textcoords="offset points", fontsize=8)
    ax.text(xcut + .01, ycut * .55, "1 증편·지원", color=BLUE)
    ax.text(xcut + .01, ycut * 1.72, "2 소형차 전환", color=ORANGE)
    ax.text(xcut - .23, ycut * .55, "3 현행 유지", color=GREEN)
    ax.text(xcut - .23, ycut * 1.72, "4 조정 검토", color=PURPLE)
    save(fig, "02_carbon_dependence_quadrants.png")


def carbon_interval_forest(routes: pd.DataFrame) -> None:
    selected = routes[routes["car_comparison"] != "버스 우위(구간 전체)"].copy()
    selected = selected.sort_values("bus_vs_car")
    split_at = (len(selected) + 1) // 2
    parts = [selected.iloc[:split_at], selected.iloc[split_at:]]
    fig, axes = plt.subplots(1, 2, figsize=(13.33, 7.5), sharex=True)
    fig.suptitle("승용차 대비 탄소 결과가 경계이거나 불리한 노선", fontsize=17)
    for ax, part in zip(axes, parts):
        y = np.arange(len(part))
        colors = part["car_comparison"].map(COMPARISON_COLORS)
        for yi, (_, row), color in zip(y, part.iterrows(), colors):
            ax.plot([row["bus_vs_car_lower"], row["bus_vs_car_upper"]], [yi, yi], color=color, linewidth=2)
            ax.scatter(row["bus_vs_car"], yi, color=color, s=24, zorder=3)
        ax.axvline(1, color=GRAY, linestyle="--", linewidth=1)
        ax.set_yticks(y, part["노선명"])
        ax.invert_yaxis(); ax.set_xlabel("버스/승용차 승객km당 탄소 비율 (1 미만 = 버스 우위)")
        ax.grid(axis="x", color=LIGHT_GRAY, linewidth=.6)
    axes[0].legend(
        [Line2D([0], [0], color=ORANGE, lw=2, marker="o"), Line2D([0], [0], color=RED, lw=2, marker="o")],
        ["경계/불확실", "구간 전체에서 승용차 우위"], frameon=False, loc="lower right"
    )
    save(fig, "03_route_carbon_interval_forest.png")


def all_route_interval_band(routes: pd.DataFrame) -> None:
    ordered = routes.sort_values("bus_vs_car").reset_index(drop=True)
    x = np.arange(len(ordered))
    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    ax.fill_between(x, ordered["bus_vs_car_lower"], ordered["bus_vs_car_upper"], color=SKY, alpha=.28,
                    label="속도 불확실성 민감도 범위")
    ax.plot(x, ordered["bus_vs_car"], color=BLUE, linewidth=1.6, label="현재 중앙 추정")
    ax.axhline(1, color=RED, linestyle="--", linewidth=1.4, label="버스=승용차")
    ax.set_yscale("log")
    ax.set_xlabel("노선 순위(현재 탄소비율 낮은 순)")
    ax.set_ylabel("버스/승용차 승객km당 탄소 비율 (로그 축)")
    ax.set_title("230개 노선의 탄소 비교: 중앙 추정은 좋아도 일부 구간은 1을 넘는다")
    ax.legend(frameon=False, loc="upper left")
    for idx in [0, len(ordered)-1]:
        row = ordered.iloc[idx]
        ax.annotate(row["노선명"], (idx, row["bus_vs_car"]), xytext=(5, 5), textcoords="offset points")
    save(fig, "04_all_route_carbon_uncertainty.png")


def class_transition(routes: pd.DataFrame) -> None:
    matrix = pd.crosstab(routes["class_if_low_energy"], routes["class_if_high_energy"]).reindex(
        index=range(1, 5), columns=range(1, 5), fill_value=0
    )
    fig, axes = plt.subplots(1, 2, figsize=(13.33, 6.6))
    ax = axes[0]
    im = ax.imshow(matrix, cmap="Blues", vmin=0, vmax=max(1, matrix.to_numpy().max()))
    for i in range(4):
        for j in range(4):
            ax.text(j, i, str(int(matrix.iloc[i, j])), ha="center", va="center",
                    color="white" if matrix.iloc[i, j] > matrix.to_numpy().max() * .5 else "black", fontsize=13)
    ax.set_xticks(range(4), [CLASS_NAMES[i] for i in range(1, 5)], rotation=20)
    ax.set_yticks(range(4), [CLASS_NAMES[i] for i in range(1, 5)])
    ax.set_xlabel("에너지 상한에서 분류"); ax.set_ylabel("에너지 하한에서 분류")
    ax.set_title("불확실성 양끝의 분류 이동")
    fig.colorbar(im, ax=ax, label="노선 수", shrink=.8)

    ax = axes[1]
    by_class = routes.groupby("class_id")["class_stable"].agg(["sum", "count"]).reindex(range(1, 5))
    rate = by_class["sum"] / by_class["count"]
    bars = ax.barh(range(4), rate, color=[CLASS_COLORS[i] for i in range(1, 5)])
    ax.set_yticks(range(4), [CLASS_NAMES[i] for i in range(1, 5)])
    ax.set_xlim(0, 1); ax.set_xticks(np.arange(0, 1.01, .2), [f"{v:.0%}" for v in np.arange(0, 1.01, .2)])
    ax.set_xlabel("분류 안정률"); ax.set_title("현재 분류별 안정률")
    for bar, value, n, total in zip(bars, rate, by_class["sum"], by_class["count"]):
        ax.text(value + .02, bar.get_y() + bar.get_height()/2, f"{int(n)}/{int(total)}", va="center")
    save(fig, "05_classification_transition.png")


def speed_diagnostics(speed: pd.DataFrame) -> None:
    speed = speed.copy()
    speed["raw_hit"] = speed["평균속도"].between(speed["q05_raw"], speed["q95_raw"])
    speed["conformal_hit"] = speed["평균속도"].between(speed["speed_lower"], speed["speed_upper"])
    speed["width"] = speed["speed_upper"] - speed["speed_lower"]
    speed["error"] = (speed["평균속도"] - speed["speed_median"]).abs()
    hourly = speed.groupby("시간코드").agg(
        raw=("raw_hit", "mean"), calibrated=("conformal_hit", "mean"),
        width=("width", "mean"), error=("error", "mean")
    )
    fig, axes = plt.subplots(1, 2, figsize=(13.33, 5.8))
    ax = axes[0]
    ax.plot(hourly.index - 1, hourly["raw"], marker="o", color=SKY, label="원시 분위수")
    ax.plot(hourly.index - 1, hourly["calibrated"], marker="o", color=BLUE, label="Conformal")
    ax.axhline(.9, color=RED, linestyle="--", label="목표 90%")
    ax.set_ylim(.76, 1.01); ax.set_xticks(range(0, 24, 3)); ax.set_xlabel("시각")
    ax.set_ylabel("실제 속도가 구간 안에 든 비율"); ax.set_title("시간대별 예측구간 포함률")
    ax.legend(frameon=False)

    ax = axes[1]
    ax.plot(hourly.index - 1, hourly["width"], marker="o", color=ORANGE, label="구간 폭")
    ax.plot(hourly.index - 1, hourly["error"], marker="s", color=PURPLE, label="중앙예측 MAE")
    ax.set_xticks(range(0, 24, 3)); ax.set_xlabel("시각"); ax.set_ylabel("km/h")
    ax.set_title("시간대별 구간 폭과 오차"); ax.legend(frameon=False)
    save(fig, "06_speed_conformal_by_hour.png")

    speed["width_decile"] = pd.qcut(speed["width"], 10, labels=False, duplicates="drop")
    bins = speed.groupby("width_decile").agg(
        width=("width", "mean"), coverage=("conformal_hit", "mean"), mae=("error", "mean")
    )
    sample = speed.sample(min(6000, len(speed)), random_state=42)
    fig, axes = plt.subplots(1, 2, figsize=(13.33, 5.8))
    ax = axes[0]
    ax.scatter(sample["speed_median"], sample["평균속도"], s=5, alpha=.16, color=BLUE)
    lim = [0, max(sample["speed_median"].quantile(.995), sample["평균속도"].quantile(.995))]
    ax.plot(lim, lim, color=RED, linestyle="--"); ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_xlabel("예측 중앙속도 (km/h)"); ax.set_ylabel("실제 속도 (km/h)")
    ax.set_title("별도 시험 링크: 예측 대 실제")
    ax = axes[1]
    ax.plot(bins["width"], bins["coverage"], marker="o", color=BLUE, label="포함률")
    ax.axhline(.9, color=RED, linestyle="--", linewidth=1)
    ax.set_xlabel("구간 폭 분위군의 평균 폭 (km/h)"); ax.set_ylabel("포함률")
    ax2 = ax.twinx(); ax2.plot(bins["width"], bins["mae"], marker="s", color=ORANGE, label="MAE")
    ax2.set_ylabel("MAE (km/h)", color=ORANGE); ax.set_title("구간이 넓은 사례는 실제 오차도 큰가")
    handles = [Line2D([0],[0], color=BLUE, marker="o"), Line2D([0],[0], color=ORANGE, marker="s")]
    ax.legend(handles, ["포함률", "MAE"], frameon=False, loc="lower right")
    save(fig, "07_speed_error_calibration.png")


def hdbscan_eda(routes: pd.DataFrame, sensitivity: pd.DataFrame) -> None:
    values = routes[HDB_FEATURES].copy().fillna(routes[HDB_FEATURES].median())
    x = StandardScaler().fit_transform(values)
    pca = PCA(n_components=2).fit_transform(x)
    explained = PCA(n_components=2).fit(x).explained_variance_ratio_  # deterministic, for labels
    fig, axes = plt.subplots(1, 2, figsize=(13.33, 6.3))
    ax = axes[0]
    for cluster, color, label in [(-1, LIGHT_GRAY, "비정형/경계"), (0, BLUE, "밀도군집 0"), (1, RED, "밀도군집 1")]:
        mask = routes["hdbscan_cluster"] == cluster
        ax.scatter(pca[mask, 0], pca[mask, 1], s=34 if cluster >= 0 else 20,
                   color=color, alpha=.8 if cluster >= 0 else .6, label=f"{label} ({mask.sum()})")
    small = routes[routes["hdbscan_cluster"] == 1]
    for idx, row in small.iterrows():
        pos = routes.index.get_loc(idx)
        ax.annotate(row["노선명"], (pca[pos, 0], pca[pos, 1]), xytext=(4,4), textcoords="offset points", fontsize=8)
    ax.set_xlabel(f"PCA 1 ({explained[0]:.1%})"); ax.set_ylabel(f"PCA 2 ({explained[1]:.1%})")
    ax.set_title("10개 노선 특성의 PCA 투영"); ax.legend(frameon=False)

    ax = axes[1]
    usable = sensitivity[sensitivity["n_clusters"] >= 2].copy()
    for method, marker, color in [("eom", "o", BLUE), ("leaf", "s", ORANGE)]:
        part = usable[usable["selection_method"] == method]
        ax.scatter(part["noise_share"], part["silhouette_clustered"],
                   s=25 + part["n_clusters"] * 12, marker=marker, color=color, alpha=.7, label=method)
    selected = usable.sort_values(["noise_share", "silhouette_clustered"], ascending=[True, False]).iloc[0]
    ax.scatter(selected["noise_share"], selected["silhouette_clustered"], s=180, marker="*", color=RED,
               label="진단용 선택")
    ax.axvline(.5, color=GRAY, linestyle="--", linewidth=1, label="허용 노이즈 50%")
    ax.set_xlabel("비정형/노이즈 비율"); ax.set_ylabel("군집 내부 실루엣")
    ax.set_title("HDBSCAN 설정 민감도: 최소조건 통과 0개")
    ax.legend(frameon=False)
    save(fig, "08_hdbscan_diagnostics.png")


def route_feature_eda(routes: pd.DataFrame) -> None:
    cols = {
        "boardings_per_day": "하루 승차",
        "avg_load": "평균 탑승",
        "trips_per_day": "하루 운행",
        "dependence_score": "교통약자 의존",
        "catchment_elderly_share": "고령 비율",
        "no_alt_boarding_share": "대체수단 없음",
        "route_cars_per_1000": "승용차 보유",
        "slope_mean": "평균 경사",
        "one_lane_share": "1차로 비중",
        "day_speed_kmh": "낮 속도",
        "bus_vs_car": "버스/승용차 탄소",
    }
    corr = routes[list(cols)].corr(method="spearman").rename(index=cols, columns=cols)
    corr.to_csv(OUTPUT / "route_feature_spearman.csv", encoding="utf-8-sig")
    fig, ax = plt.subplots(figsize=(10.5, 8.5))
    im = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr)), corr.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(corr)), corr.index)
    for i in range(len(corr)):
        for j in range(len(corr)):
            value = corr.iloc[i, j]
            if i != j:
                ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=8,
                        color="white" if abs(value) > .55 else "black")
    fig.colorbar(im, ax=ax, label="Spearman 상관계수", shrink=.8)
    ax.set_title("노선 특성 EDA: 순위 상관관계")
    save(fig, "09_route_feature_correlation.png")

    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    for class_id in range(1, 5):
        part = routes[routes["class_id"] == class_id]
        size = 18 + 120 * np.sqrt(part["boardings_per_day"] / routes["boardings_per_day"].max())
        ax.scatter(part["avg_load"], part["bus_vs_car"], s=size, color=CLASS_COLORS[class_id],
                   alpha=.68, label=CLASS_NAMES[class_id])
    ax.axhline(1, color=RED, linestyle="--", linewidth=1.2)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("평균 탑승인원 (로그 축)"); ax.set_ylabel("버스/승용차 탄소 비율 (로그 축)")
    ax.set_title("평균 탑승인원이 낮을수록 승객당 탄소가 급격히 커진다")
    ax.legend(frameon=False, ncol=2)
    for _, row in routes.nlargest(7, "bus_vs_car").iterrows():
        ax.annotate(row["노선명"], (row["avg_load"], row["bus_vs_car"]), xytext=(4,4),
                    textcoords="offset points", fontsize=8)
    rho = routes[["avg_load", "bus_vs_car"]].corr(method="spearman").iloc[0, 1]
    ax.text(.02, .04, f"Spearman ρ = {rho:.2f}", transform=ax.transAxes, fontsize=12, color=GRAY)
    save(fig, "10_load_carbon_relationship.png")


def route_map(routes: pd.DataFrame) -> None:
    if not LINK_SHP.exists():
        return
    link_geom = gpd.read_file(LINK_SHP)[["LINK_ID", "geometry"]]
    link_geom["LINK_ID"] = link_geom["LINK_ID"].astype(str)
    route_links = pd.read_csv(TRANSIT / "route_links.csv", dtype={"ROUTE_ID": str, "LINK_ID": str})
    route_links = route_links[route_links["ROUTE_ID"].isin(routes["ROUTE_ID"])]
    joined = gpd.GeoDataFrame(route_links.merge(link_geom, on="LINK_ID", how="inner"), geometry="geometry", crs=link_geom.crs)
    dissolved = joined[["ROUTE_ID", "geometry"]].dissolve(by="ROUTE_ID").reset_index()
    dissolved = dissolved.merge(routes[["ROUTE_ID", "car_comparison", "class_stable"]], on="ROUTE_ID", how="left")
    boundary = gpd.read_file(BOUNDARY).to_crs(dissolved.crs) if BOUNDARY.exists() else None
    fig, axes = plt.subplots(1, 2, figsize=(13.33, 7.0))
    for ax in axes:
        if boundary is not None:
            boundary.plot(ax=ax, facecolor="none", edgecolor="#BDBDBD", linewidth=.7)
        ax.set_axis_off()
    for label in ["버스 우위(구간 전체)", "경계/불확실", "승용차 우위(구간 전체)"]:
        dissolved[dissolved["car_comparison"] == label].plot(
            ax=axes[0], color=COMPARISON_COLORS[label], linewidth=.8 if label != "버스 우위(구간 전체)" else .35,
            alpha=.9 if label != "버스 우위(구간 전체)" else .3,
        )
    axes[0].set_title("노선별 승용차 대비 탄소 결과")
    axes[0].legend([Patch(color=COMPARISON_COLORS[x]) for x in COMPARISON_COLORS], list(COMPARISON_COLORS),
                   frameon=False, loc="lower left")
    dissolved[dissolved["class_stable"]].plot(ax=axes[1], color=BLUE, linewidth=.35, alpha=.3)
    dissolved[~dissolved["class_stable"]].plot(ax=axes[1], color=ORANGE, linewidth=.9, alpha=.85)
    axes[1].set_title("정책 4분류 경계 노선의 공간 분포")
    axes[1].legend([Patch(color=BLUE), Patch(color=ORANGE)], ["분류 안정", "경계"], frameon=False, loc="lower left")
    save(fig, "11_route_uncertainty_map.png")


def presentation_tables(routes: pd.DataFrame) -> None:
    robust = routes[(routes["car_comparison"] == "버스 우위(구간 전체)") & routes["class_stable"]].nlargest(
        10, "co2_saved_kg_per_day"
    )
    risky = routes[routes["car_comparison"] != "버스 우위(구간 전체)"].nlargest(10, "bus_vs_car_upper")
    fig, axes = plt.subplots(1, 2, figsize=(13.33, 7.5))
    fig.suptitle("발표용 노선 사례 표", fontsize=17)
    for ax in axes:
        ax.axis("off")
    left = robust[["노선명", "class_id", "co2_saved_kg_per_day", "bus_vs_car_upper"]].copy()
    left["co2_saved_kg_per_day"] = left["co2_saved_kg_per_day"].map(lambda x: f"{x:,.0f}")
    left["bus_vs_car_upper"] = left["bus_vs_car_upper"].map(lambda x: f"{x:.2f}")
    table = axes[0].table(cellText=left.values, colLabels=["노선", "분류", "하루 감축 kg", "비율 상한"],
                          loc="center", cellLoc="center", colLoc="center")
    table.auto_set_font_size(False); table.set_fontsize(9); table.scale(1, 1.55)
    axes[0].set_title("효과와 분류가 모두 견고한 상위 노선", pad=14)

    right = risky[["노선명", "class_id", "car_comparison", "bus_vs_car", "bus_vs_car_upper"]].copy()
    right["car_comparison"] = right["car_comparison"].replace({"승용차 우위(구간 전체)": "승용차 우위", "경계/불확실": "경계"})
    right["bus_vs_car"] = right["bus_vs_car"].map(lambda x: f"{x:.2f}")
    right["bus_vs_car_upper"] = right["bus_vs_car_upper"].map(lambda x: f"{x:.2f}")
    table = axes[1].table(cellText=right.values,
                          colLabels=["노선", "분류", "판정", "중앙", "상한"],
                          loc="center", cellLoc="center", colLoc="center")
    table.auto_set_font_size(False); table.set_fontsize(9); table.scale(1, 1.55)
    axes[1].set_title("추가 검토가 필요한 노선", pad=14)
    save(fig, "12_presentation_route_tables.png")


def write_readme(routes: pd.DataFrame) -> None:
    stable = int(routes["class_stable"].sum())
    text = f"""# 마을버스 ML·불확실성 발표용 EDA

생성 명령: `python src/eda/06_transit_ml_eda.py`

## 발표 슬라이드 권장 순서

1. `01_executive_summary.png` — 핵심 결과 한 장 요약
2. `02_carbon_dependence_quadrants.png` — 정책 4분류의 구조와 경계 노선
3. `03_route_carbon_interval_forest.png` — 승용차 비교가 확실하지 않은 개별 노선
4. `04_all_route_carbon_uncertainty.png` — 230개 전체 노선의 탄소 민감도
5. `05_classification_transition.png` — 불확실성에 따른 분류 이동
6. `06_speed_conformal_by_hour.png` — 시간대별 conformal 검증
7. `07_speed_error_calibration.png` — 예측 대 실제 및 구간 폭 진단
8. `08_hdbscan_diagnostics.png` — 자연 군집이 안정적이지 않다는 근거
9. `09_route_feature_correlation.png` — 노선 특성 EDA
10. `10_load_carbon_relationship.png` — 낮은 탑승인원이 승객당 탄소를 키우는 관계
11. `11_route_uncertainty_map.png` — 경계 노선의 공간 분포
12. `12_presentation_route_tables.png` — 발표용 대표 노선 표

## 현재 핵심 수치

- 분석 노선: {len(routes)}개
- 정책 분류 안정: {stable}개, 경계: {len(routes) - stable}개
- 속도 민감도 범위 전체에서 버스 우위: {(routes['car_comparison'] == '버스 우위(구간 전체)').sum()}개
- 승용차 비교 경계: {(routes['car_comparison'] == '경계/불확실').sum()}개
- 범위 전체에서 승용차 우위: {(routes['car_comparison'] == '승용차 우위(구간 전체)').sum()}개

주의: 노선 탄소 구간은 행 단위 conformal 속도 구간을 전달한 보수적 민감도 범위이며,
노선 단위 90% 확률구간으로 해석하지 않는다.
"""
    (FIGURES / "README.md").write_text(text, encoding="utf-8")


def main() -> None:
    set_style()
    FIGURES.mkdir(parents=True, exist_ok=True)
    routes, speed, sensitivity = load_routes()
    make_tables(routes, speed)
    executive_summary(routes, speed)
    carbon_dependence_scatter(routes)
    carbon_interval_forest(routes)
    all_route_interval_band(routes)
    class_transition(routes)
    speed_diagnostics(speed)
    hdbscan_eda(routes, sensitivity)
    route_feature_eda(routes)
    route_map(routes)
    presentation_tables(routes)
    write_readme(routes)
    summary = {
        "routes": len(routes), "figures": len(list(FIGURES.glob("*.png"))),
        "stable_classes": int(routes["class_stable"].sum()),
        "boundary_classes": int((~routes["class_stable"]).sum()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("그림:", FIGURES)
    print("표:", OUTPUT)


if __name__ == "__main__":
    main()
