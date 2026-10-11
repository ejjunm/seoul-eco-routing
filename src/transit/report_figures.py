"""마을버스 분석 보고서용 그림(PNG)을 만든다. 01~10 산출물만 읽는다.

출력: --out 폴더(기본 docs/figures/transit_report)에 fig01~fig12 PNG(보고서 그림 번호 순, 10·11은 노선 카드)
사용: python src/transit/report_figures.py [--out 폴더]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.colors import LinearSegmentedColormap
from shapely.geometry import LineString, box

from route_data import load_route_stops

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRANSIT = PROJECT_ROOT / "data" / "processed" / "transit"
ROUTE_PATH_CSV = PROJECT_ROOT / "data" / "raw" / "traffic" / "bus_route_path" / "route_paths.csv"
BOUNDARY = PROJECT_ROOT / "data" / "raw" / "boundary" / "seoul_admin_boundary.geojson"

# 색: dataviz 기본 팔레트(밝은 화면). 네 칸은 모든 그림에서 같은 색을 쓴다.
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, BASE, PLANE = "#e1e0d9", "#c3c2b7", "#f0efec"
BLUE, BLUE_DARK, BLUE_LIGHT, BLUE_PALE = "#2a78d6", "#184f95", "#86b6ef", "#cde2fb"
CLASS_COLORS = {1: "#2a78d6", 2: "#eb6834", 3: "#1baf7a", 4: "#7d7c76"}
CLASS_NAMES = {1: "① 증편·지원 우선", 2: "② 소형 차량 전환", 3: "③ 현행 유지", 4: "④ 노선 조정 검토"}
DPI = 200


def setup_style() -> None:
    plt.rcParams.update({
        "font.family": "Malgun Gothic", "axes.unicode_minus": False, "font.size": 10,
        "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 10,
        "axes.edgecolor": BASE, "axes.labelcolor": INK2, "axes.linewidth": 0.8,
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white", "text.color": INK,
        "legend.frameon": False, "legend.fontsize": 9,
    })


def clean_axes(ax, grid_axis: str = "y") -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
    ax.tick_params(length=0)


def hbar(ax, y: float, value: float, height: float, color: str, r_px: float = 4.0) -> None:
    """가로 막대: 값 쪽 끝만 둥글게(4px), 기준선 쪽은 각지게."""
    ax.figure.canvas.draw()
    bbox = ax.get_window_extent()
    px_x = bbox.width / np.ptp(ax.get_xlim())
    px_y = bbox.height / np.ptp(ax.get_ylim())
    rx, ry = r_px / px_x, r_px / px_y
    ax.add_patch(FancyBboxPatch((0, y - height / 2), value, height, boxstyle=f"round,pad=0,rounding_size={rx}",
                                mutation_aspect=ry / rx, facecolor=color, edgecolor="none"))
    ax.add_patch(Rectangle((0, y - height / 2), min(2 * rx, value), height, facecolor=color, edgecolor="none"))


def vbar(ax, x: float, value: float, width: float, color: str, r_px: float = 4.0) -> None:
    ax.figure.canvas.draw()
    bbox = ax.get_window_extent()
    px_x = bbox.width / np.ptp(ax.get_xlim())
    px_y = bbox.height / np.ptp(ax.get_ylim())
    rx, ry = r_px / px_x, r_px / px_y
    ax.add_patch(FancyBboxPatch((x - width / 2, 0), width, value, boxstyle=f"round,pad=0,rounding_size={rx}",
                                mutation_aspect=ry / rx, facecolor=color, edgecolor="none"))
    ax.add_patch(Rectangle((x - width / 2, 0), width, min(2 * ry, value), facecolor=color, edgecolor="none"))


def save(fig, out: Path, name: str) -> None:
    path = out / name
    fig.savefig(path, dpi=DPI, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print(f"  {path.name}")


def load_tables() -> dict[str, pd.DataFrame]:
    read = lambda name: pd.read_csv(TRANSIT / name, dtype={"ROUTE_ID": str})  # noqa: E731
    carbon = read("route_carbon_breakeven.csv")
    return {
        "carbon": carbon[~carbon["load_qa_flag"]].copy(),
        "priority": read("route_priority.csv"),
        "demand": read("route_demand.csv"),
        "hourly": read("route_hourly_load.csv"),
        "ops": read("route_operations.csv"),
        "speed": pd.read_csv(TRANSIT / "ai_speed_validation.csv"),
        "feas": read("route_feasibility.csv"),
        "removal": read("route_removal_access.csv"),
        "removal_cells": read("route_removal_cells.csv"),
    }


def fig01_flow(out: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 46)
    ax.axis("off")
    columns = [
        ("입력 데이터", 1, 22, [("버스 실제 경로", "서울시 버스 API"), ("승하차·운행횟수", "교통카드(7월), TOPIS"),
                               ("생활인구·자동차 등록", "250m 격자, 행정동"), ("도로 속도·경사", "국가교통정보센터 5분 속도, DEM")]),
        ("AI·물리 모델", 27, 22, [("AI 속도 추정", "관측 없는 도로(약 30%)의\n속도를 XGBoost로 채움"),
                                ("차량별 에너지 모델", "같은 길·속도·경사로\n버스 3종, 승용차 5종 계산")]),
        ("분석", 53, 22, [("승객 1명·1km당 탄소", "버스 vs 승용차, 손익분기"), ("시간대별 탑승·증편", "언제 빈 차가 다니는가"),
                         ("교통약자 의존도", "고령 인구, 대체수단,\n승용차 보유")]),
        ("결과", 79, 20, [("네 칸 분류", "교통약자 의존도 ×\n탄소 효율"), ("정책 제안", "차 크기·운행 시간 맞춤")]),
    ]
    for header, x, w, boxes in columns:
        ax.text(x, 44, header, fontsize=10, fontweight="bold", color=MUTED, va="center")
        n = len(boxes)
        gap = 2.2
        h = (40 - gap * (n - 1)) / n
        for i, (title, sub) in enumerate(boxes):
            y = 40 - (i + 1) * h - i * gap
            is_ai = title == "AI 속도 추정"
            ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.2",
                                        facecolor=BLUE_PALE if is_ai else PLANE,
                                        edgecolor=BLUE if is_ai else "none", linewidth=1.2))
            ax.text(x + 1.4, y + h - 1.6, title, fontsize=10, fontweight="bold", color=INK, va="top")
            ax.text(x + 1.4, y + h - 4.6, sub, fontsize=8.5, color=INK2, va="top", linespacing=1.4)
    for x0, x1 in ((23.2, 26.6), (49.2, 52.6), (75.2, 78.6)):
        ax.annotate("", xy=(x1, 20), xytext=(x0, 20), arrowprops=dict(arrowstyle="-|>", color=MUTED, lw=1.4))
    save(fig, out, "fig01_flow.png")


# 검증 R²: docs/DATA_ANALYSIS_REPORT.md 3.2절(A, 시간 순서 분할)과 docs/figures/model/09_bc_groupkfold_r2.png
# (B·C, 도로 단위 3-fold GroupKFold). 이 스크립트에서 다시 계산하지 않는다.
TIER_ROWS = [
    ("A_lookup", "A  관측 이력: 과거 같은 시간대 평균\n검증 R² 0.93 (앞 11일 학습 → 뒤 3일 평가)"),
    ("B_neighbor_model", "B  AI 추정: 이웃 도로 관측 있음\n검증 R² 0.74 (도로 단위로 나눈 평가)"),
    ("C_static_model", "C  AI 추정: 이웃 관측도 없음\n검증 R² 0.32 (도로 단위로 나눈 평가)"),
]


def fig02_ai_tiers(out: Path) -> None:
    links = pd.read_csv(TRANSIT / "route_links.csv", dtype={"ROUTE_ID": str, "LINK_ID": str})
    links = links[links["kind"] == "마을버스"]
    tier = pd.read_parquet(TRANSIT / "link_speed_weekday_profile.parquet", columns=["LINK_ID", "tier"]).drop_duplicates("LINK_ID")
    merged = links.merge(tier, on="LINK_ID")
    route_share = merged.groupby("tier")["LENGTH"].sum() / merged["LENGTH"].sum() * 100
    city_share = tier["tier"].value_counts(normalize=True) * 100
    fig, ax = plt.subplots(figsize=(9, 3.4))
    ax.set_xlim(0, 100)
    ax.set_ylim(len(TIER_ROWS) - 0.4, -0.6)
    clean_axes(ax, "x")
    for i, (key, _) in enumerate(TIER_ROWS):
        for offset, value, color in ((-0.15, city_share[key], BASE), (0.15, route_share[key], BLUE)):
            hbar(ax, i + offset, value, 0.24, color)
            ax.text(value + 1.0, i + offset, f"{value:.1f}%", va="center", fontsize=9, color=INK)
    ax.set_yticks(range(len(TIER_ROWS)), [label for _, label in TIER_ROWS])
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("비중(%)")
    ax.scatter([], [], marker="s", s=60, color=BASE, label="서울 전체 도로 링크 수")
    ax.scatter([], [], marker="s", s=60, color=BLUE, label="마을버스 노선 길이")
    ax.legend(loc="lower right")
    save(fig, out, "fig02_ai_tiers.png")


def fig02_co2_per_km(t: dict, out: Path) -> None:
    c, p = t["carbon"], t["priority"]
    cars = [("현재 구성(서울 등록 비율)", c["car_g_per_km"].median(), True), ("휘발유", c["car_휘발유_g_per_km"].median(), False),
            ("경유", c["car_경유_g_per_km"].median(), False), ("LPG", c["car_LPG_g_per_km"].median(), False),
            ("하이브리드", c["car_하이브리드_g_per_km"].median(), False), ("전기", c["car_전기_g_per_km"].median(), False)]
    buses = [("현재 구성(마을버스 대수 비율)", c["bus_g_per_km"].median(), True), ("경유", c["bus_diesel_g_per_km"].median(), False),
             ("CNG", c["bus_cng_g_per_km"].median(), False), ("전기", c["bus_ev_g_per_km"].median(), False),
             ("소형 전기 승합차(15인승급)", p["van_g_per_km"].median(), False)]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharex=True)
    for ax, (title, rows) in zip(axes, (("승용차 1대", cars), ("마을버스 1대", buses))):
        ax.set_xlim(0, 640)
        ax.set_ylim(len(rows) - 0.4, -0.6)
        clean_axes(ax, "x")
        ax.set_title(title)
        for i, (label, value, highlight) in enumerate(rows):
            hbar(ax, i, value, 0.42 * len(rows) / 6, BLUE_DARK if highlight else BLUE)
            ax.text(value + 10, i, f"{value:,.0f}", va="center", fontsize=9, color=INK,
                    fontweight="bold" if highlight else "normal")
        ax.set_yticks(range(len(rows)), [r[0] for r in rows])
        ax.set_xlabel("1km 주행당 CO₂ (g, 230개 노선 중앙값)")
        ax.spines["left"].set_visible(False)
    fig.tight_layout(w_pad=3)
    save(fig, out, "fig03_co2_per_km.png")


def fig03_load_scatter(t: dict, out: Path) -> None:
    c = t["carbon"]
    worse = c["bus_vs_car"] >= 1
    fig, ax = plt.subplots(figsize=(9, 4.8))
    clean_axes(ax, "both")
    ax.set_yscale("log")
    ax.set_xlim(0, 20)
    ax.set_ylim(20, 2000)
    bus_km, car_pkm = c["bus_g_per_km"].median(), c["car_g_per_pkm"].median()
    x = np.linspace(0.25, 20, 300)
    ax.plot(x, bus_km / x, color=MUTED, lw=1.2)
    ax.axhline(car_pkm, color=INK2, lw=1.2)
    ax.scatter(c.loc[~worse, "avg_load"], c.loc[~worse, "bus_g_per_pkm"], s=30, color=BLUE, alpha=0.75,
               edgecolor="white", linewidth=0.8, label=f"승용차보다 탄소가 적은 노선 {int((~worse).sum())}개", zorder=3)
    ax.scatter(c.loc[worse, "avg_load"], c.loc[worse, "bus_g_per_pkm"], s=42, color=INK, edgecolor="white",
               linewidth=0.8, label=f"승용차보다 많은 노선 {int(worse.sum())}개", zorder=4)
    be = c["breakeven_load"].median()
    ax.scatter([be], [car_pkm], s=60, facecolor="white", edgecolor=INK, linewidth=1.5, zorder=5)
    ax.annotate(f"손익분기: 평균 {be:.2f}명(노선 중앙값)", (be, car_pkm), xytext=(3.2, car_pkm * 2.3), fontsize=9,
                color=INK, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
    ax.text(19.8, car_pkm * 1.08, f"승용차(1.2명 탑승) 승객 1명당 {car_pkm:.0f}g", ha="right", va="bottom", fontsize=9, color=INK2)
    ax.annotate(f"버스 1km {bus_km:.0f}g ÷ 탑승 인원", (14.0, bus_km / 14.0), xytext=(13.2, 85), fontsize=9, color=INK2,
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
    med = c["avg_load"].median()
    ax.axvline(med, color=BASE, lw=1)
    ax.text(med + 0.2, 1500, f"실제 평균 탑승 중앙 {med:.1f}명", fontsize=9, color=INK2, va="top")
    ax.set_yticks([20, 50, 100, 200, 500, 1000, 2000], ["20", "50", "100", "200", "500", "1,000", "2,000"])
    ax.set_xlabel("노선 평균 탑승 인원(명, 차 안에 평균 몇 명이 타고 있나)")
    ax.set_ylabel("승객 1명·1km당 CO₂ (g, 로그 눈금)")
    ax.legend(loc="upper right", bbox_to_anchor=(1.0, 0.86))
    save(fig, out, "fig04_load_vs_carbon.png")


def fig04_hourly(t: dict, out: Path) -> None:
    h = t["hourly"]
    h["low_trips"] = h["trips"].where(h["low_load"], 0.0)
    g = h.groupby("hour").agg(pkm=("pkm", "sum"), vkm=("vkm", "sum"), trips=("trips", "sum"), low=("low_trips", "sum"))
    g["load"] = g["pkm"] / g["vkm"]
    g["low_share"] = g["low"] / g["trips"] * 100
    be = t["carbon"]["breakeven_load"].median()
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 5.4), sharex=True, gridspec_kw={"hspace": 0.45})
    for ax in (a1, a2):
        clean_axes(ax, "y")
        ax.set_xlim(5.4, 22.6)
    a1.set_ylim(0, 11)
    a1.plot(g.index, g["load"], color=BLUE, lw=2, marker="o", ms=5, mec="white", mew=1, zorder=3)
    a1.axhline(be, color=INK2, lw=1)
    a1.text(22.5, be + 0.25, f"손익분기 평균 {be:.2f}명", ha="right", fontsize=9, color=INK2)
    for hour in (8, 18, 21):
        a1.text(hour, g.loc[hour, "load"] + 0.55, f"{g.loc[hour, 'load']:.1f}명", ha="center", fontsize=9, color=INK)
    a1.set_title("시간대별 평균 탑승 인원(명, 운행 거리 가중)")
    a2.set_ylim(0, max(g["low_share"]) * 1.25)
    for hour, value in g["low_share"].items():
        vbar(a2, hour, value, 0.5, BLUE_DARK if hour >= 20 else BLUE_LIGHT)
    for hour in (8, 12, 21):
        a2.text(hour, g.loc[hour, "low_share"] + 1.0, f"{g.loc[hour, 'low_share']:.0f}%", ha="center", fontsize=9, color=INK)
    a2.set_title("차 안 평균 인원이 3명 미만인 운행의 비중(%)")
    a2.set_xticks(range(6, 23, 2), [f"{x}시" for x in range(6, 23, 2)])
    save(fig, out, "fig05_hourly_load.png")


def fig05_reduction(t: dict, out: Path) -> None:
    """감축 수단 비교: 모두 '지금 차량 구성' 대비. 소형차는 크기 효과만(전기 마을버스 대비)도 함께 적는다."""
    c, p, o = t["carbon"], t["priority"], t["ops"]
    electric = (c["bus_co2_kg_per_day"].sum() - c["bus_co2_kg_per_day_all_electric"].sum()) / 1000
    offpeak = o["van_offpeak_cut_vs_current_kg_per_day"].sum() / 1000
    offpeak_size = o["van_offpeak_cut_kg_per_day"].sum() / 1000
    class2 = p["van_co2_cut_vs_current_kg_per_day"].sum() / 1000
    class2_size = p["van_co2_cut_kg_per_day"].sum() / 1000
    h = t["hourly"]
    low_share = h.loc[h["low_load"], "trips"].sum() / h["trips"].sum()
    two = p[p["class_id"] == 2]
    rows = [("경유·CNG 마을버스를 모두 전기버스로", electric, "경유·CNG 1,229대 교체", False),
            ("차 안 평균 3명 미만 시간대만 소형 전기차로", offpeak, f"전체 운행의 {low_share:.0%}만 바꿈 · 크기 효과만 {offpeak_size:.1f}톤", True),
            ("② 칸 노선 차량을 소형 전기차로", class2, f"{int(two['van_feasible'].sum())}개 노선 · 크기 효과만 {class2_size:.1f}톤", False)]
    fig, ax = plt.subplots(figsize=(9, 2.8))
    ax.set_xlim(0, 22)
    ax.set_ylim(len(rows) - 0.4, -0.6)
    clean_axes(ax, "x")
    for i, (label, value, note, highlight) in enumerate(rows):
        hbar(ax, i, value, 0.42, BLUE_DARK if highlight else BLUE)
        ax.text(value + 0.25, i, f"하루 {value:.1f}톤", va="center", fontsize=9.5, color=INK, fontweight="bold")
        ax.text(value + 0.25, i + 0.3, note, va="center", fontsize=8.5, color=INK2)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("하루 CO₂ 감축(톤, 지금 차량 구성 대비, 각 방법을 따로 했을 때)")
    save(fig, out, "fig06_reduction_options.png")


def fig06_quadrant(t: dict, out: Path) -> None:
    p = t["priority"]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    clean_axes(ax, None)
    ax.set_yscale("log")
    for cid, color in CLASS_COLORS.items():
        d = p[p["class_id"] == cid]
        ax.scatter(d["dependence_score"], d["bus_g_per_pkm"], s=34, color=color, edgecolor="white", linewidth=0.8,
                   alpha=0.9, zorder=3, label=f"{CLASS_NAMES[cid]} {len(d)}개")
    xm, ym = p["dependence_score"].median(), p["bus_g_per_pkm"].median()
    ax.axvline(xm, color=BASE, lw=1)
    ax.axhline(ym, color=BASE, lw=1)
    ax.set_ylim(20, 1200)
    ax.set_xlim(0, 1)
    corners = {1: (0.99, 22, "right", "bottom"), 2: (0.99, 1150, "right", "top"),
               3: (0.01, 22, "left", "bottom"), 4: (0.01, 1150, "left", "top")}
    for cid, (x, y, ha, va) in corners.items():
        n = int((p["class_id"] == cid).sum())
        ax.text(x, y, f"{CLASS_NAMES[cid]}  {n}개", ha=ha, va=va, fontsize=9.5, fontweight="bold", color=INK)
    ax.set_yticks([20, 50, 100, 200, 500, 1000], ["20", "50", "100", "200", "500", "1,000"])
    ax.set_xlabel("교통약자 의존도(고령 비율·고령 인구·대체수단 없는 승차 비중의 순위 평균, 0~1) →")
    ax.set_ylabel("승객 1명·1km당 CO₂ (g, 로그 눈금)\n↑ 손님에 비해 차가 큼")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=4, handletextpad=0.3, columnspacing=1.2)
    save(fig, out, "fig08_quadrant.png")


def fig07_elderly_cars(t: dict, out: Path) -> None:
    p = t["priority"].merge(t["demand"][["ROUTE_ID", "route_cars_per_1000"]], on="ROUTE_ID")
    rho = p[["catchment_elderly_share", "route_cars_per_1000"]].corr("spearman").iloc[0, 1]
    two = p["class_id"] == 2
    fig, ax = plt.subplots(figsize=(9, 4.4))
    clean_axes(ax, "both")
    ax.scatter(p.loc[~two, "catchment_elderly_share"] * 100, p.loc[~two, "route_cars_per_1000"], s=30, color=BASE,
               edgecolor="white", linewidth=0.8, label=f"그 밖의 노선 {int((~two).sum())}개", zorder=2)
    ax.scatter(p.loc[two, "catchment_elderly_share"] * 100, p.loc[two, "route_cars_per_1000"], s=36,
               color=CLASS_COLORS[2], edgecolor="white", linewidth=0.8, label=f"{CLASS_NAMES[2]} {int(two.sum())}개", zorder=3)
    ax.text(0.99, 0.97, f"순위상관 {rho:.2f}\n어르신이 많은 노선일수록 승용차가 적다", transform=ax.transAxes,
            ha="right", va="top", fontsize=9.5, color=INK)
    ax.set_xlabel("노선 정류장 300m 안 평일 낮 고령(65세 이상) 비율(%)")
    ax.set_ylabel("주민 1,000명당 자가용 승용차(대)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2)
    save(fig, out, "fig07_elderly_vs_cars.png")


def fig08_map(t: dict, out: Path) -> None:
    p = t["priority"]
    paths = pd.read_csv(ROUTE_PATH_CSV, dtype={"ROUTE_ID": str}).sort_values(["ROUTE_ID", "no"])
    paths = paths[paths["ROUTE_ID"].isin(p["ROUTE_ID"])]
    lines = paths.groupby("ROUTE_ID")[["gpsX", "gpsY"]].apply(lambda g: LineString(g.to_numpy()))
    routes = gpd.GeoDataFrame({"ROUTE_ID": lines.index}, geometry=lines.to_numpy(), crs=4326).to_crs(5179)
    routes = routes.merge(p[["ROUTE_ID", "class_id"]], on="ROUTE_ID")
    seoul = gpd.read_file(BOUNDARY).to_crs(5179)
    fig, axes = plt.subplots(2, 2, figsize=(10, 8.6))
    for ax, cid in zip(axes.ravel(), (1, 2, 3, 4)):
        seoul.plot(ax=ax, color=PLANE, edgecolor="white", linewidth=0.6)
        routes[routes["class_id"] != cid].plot(ax=ax, color="#d6d5cf", linewidth=0.4)
        routes[routes["class_id"] == cid].plot(ax=ax, color=CLASS_COLORS[cid], linewidth=1.1)
        ax.set_title(f"{CLASS_NAMES[cid]}  {int((routes['class_id'] == cid).sum())}개 노선", fontsize=10.5)
        ax.set_axis_off()
    fig.tight_layout(h_pad=1.5, w_pad=1.0)
    save(fig, out, "fig09_route_map.png")


def fig09_speed_check(t: dict, out: Path) -> None:
    s = t["speed"]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    clean_axes(ax, "y")
    ax.plot(s["hour"], s["observed_kmh"], color=INK2, lw=2, marker="o", ms=5, mec="white", mew=1,
            label="실측: 마을버스 공간속도(TOPIS, 2026.10.6~8)")
    ax.plot(s["hour"], s["model_kmh"], color=BLUE, lw=2, marker="o", ms=5, mec="white", mew=1,
            label="분석 입력: 마을버스 노선 도로 속도(관측 + AI 추정, 7월 평일)")
    ax.set_ylim(12, 21)
    ax.set_xticks(range(7, 23, 2), [f"{x}시" for x in range(7, 23, 2)])
    ax.set_ylabel("속도(km/h)")
    ax.legend(loc="upper left", ncol=1)
    save(fig, out, "fig12_speed_check.png")


CARDS = [
    ("서대문01", "fig10_card_seodaemun01.png", "언덕 위 어르신 노선: 작은 저상 전기차로 계속 달리게"),
    ("관악04", "fig11_card_gwanak04.png", "붐비는 구간이 있는 어르신 노선: 차 크기는 그대로, 전기화와 지원 우선"),
]
CELL_RAMP = LinearSegmentedColormap.from_list("ramp", ["#cde2fb", "#6da7ec", "#256abf", "#0d366b"])


def fig_route_card(t: dict, out: Path, name: str, filename: str, headline: str) -> None:
    p, c = t["priority"], t["carbon"]
    row = p[p["노선명"] == name].iloc[0]
    rid = row["ROUTE_ID"]
    feas = t["feas"].set_index("ROUTE_ID").loc[rid]
    rem = t["removal"].set_index("ROUTE_ID").loc[rid]
    car = c.set_index("ROUTE_ID").loc[rid]

    path = pd.read_csv(ROUTE_PATH_CSV, dtype={"ROUTE_ID": str})
    path = path[path["ROUTE_ID"] == rid].sort_values("no")
    line = gpd.GeoSeries([LineString(path[["gpsX", "gpsY"]].to_numpy())], crs=4326).to_crs(5179)
    rs = load_route_stops()
    rs = rs[rs["ROUTE_ID"] == rid].drop_duplicates("NODE_ID")
    stops = gpd.GeoSeries(gpd.points_from_xy(rs["X좌표"], rs["Y좌표"]), crs=4326).to_crs(5179)
    grid = pd.read_csv(TRANSIT / "grid_population_daytime.csv", usecols=["CELL_ID", "cx", "cy"])
    cells = t["removal_cells"][t["removal_cells"]["ROUTE_ID"] == rid].merge(grid, on="CELL_ID")
    cells = cells[cells["added_min_net"] >= 1]
    squares = gpd.GeoDataFrame(cells, geometry=[box(x - 125, y - 125, x + 125, y + 125)
                                                for x, y in zip(cells["cx"], cells["cy"])], crs=5179)
    seoul = gpd.read_file(BOUNDARY).to_crs(5179)

    fig = plt.figure(figsize=(11, 5.6))
    gs = fig.add_gridspec(2, 2, width_ratios=[1.05, 1], height_ratios=[1, 1.15], wspace=0.08, hspace=0.35)
    fig.text(0.01, 0.99, f"{name}  ·  {headline}", fontsize=13, fontweight="bold", color=INK, va="top")
    ax = fig.add_subplot(gs[:, 0])
    xmin, ymin, xmax, ymax = line.total_bounds
    pad = max(xmax - xmin, ymax - ymin) * 0.15 + 300
    seoul.plot(ax=ax, color=PLANE, edgecolor="white", linewidth=0.8)
    if len(squares):
        squares.plot(ax=ax, column=squares["added_min_net"].clip(upper=15), cmap=CELL_RAMP, vmin=1, vmax=15, linewidth=0)
    line.plot(ax=ax, color=CLASS_COLORS[2], linewidth=2.2)
    stops.plot(ax=ax, color=INK, markersize=9, zorder=4)
    ax.set_xlim(xmin - pad, xmax + pad)
    ax.set_ylim(ymin - pad, ymax + pad)
    ax.set_axis_off()
    sm = plt.cm.ScalarMappable(cmap=CELL_RAMP, norm=plt.Normalize(1, 15))
    cbar = fig.colorbar(sm, ax=ax, orientation="horizontal", fraction=0.04, pad=0.02, shrink=0.8)
    cbar.set_label("노선을 없애면 늘어나는 노인 보행 시간(분, 도로망 기준, 15분 이상은 같은 색)", fontsize=8.5, color=INK2)
    cbar.outline.set_visible(False)
    cbar.ax.tick_params(labelsize=8, length=0)

    ah = fig.add_subplot(gs[0, 1])
    hourly = t["hourly"][t["hourly"]["ROUTE_ID"] == rid].set_index("hour")
    clean_axes(ah, "y")
    ah.set_xlim(5.4, 22.6)
    ah.set_ylim(0, max(hourly["avg_load"].max() * 1.25, 4))
    for hour, value in hourly["avg_load"].items():
        vbar(ah, hour, value, 0.55, BLUE_DARK if value < 3 else BLUE)
    ah.axhline(3, color=INK2, lw=1)
    ah.set_xticks(range(6, 23, 4), [f"{x}시" for x in range(6, 23, 4)])
    ah.set_title("시간대별 차 안 평균 인원(명) · 가로선 = 3명", fontsize=10)

    at = fig.add_subplot(gs[1, 1])
    at.axis("off")
    if row["van_feasible"]:
        van_line = f"저상 소형 전기차로 바꾸면 하루 {row['van_co2_cut_vs_current_kg_per_day']:.0f}kg CO₂ 감축(지금 차량 대비)"
    else:
        van_line = f"가장 붐비는 구간이 1회 평균 {row['avg_peak_load_per_trip']:.0f}명 → 소형차로는 부족, 운행 유지·전기화"
    facts = [
        ("이용", f"하루 {row['boardings_per_day']:,.0f}명 승차 · {row['trips_per_day']:.0f}회 운행 · 노선 {row['length_km']:.1f}km"),
        ("탄소", f"승객 1명·1km {row['bus_g_per_pkm']:.0f}g (승용차 {car['car_g_per_pkm']:.0f}g) · 차 안 평균 {row['avg_load']:.1f}명"),
        ("어르신", f"정류장 주변 고령 비율 {row['catchment_elderly_share']:.0%} · 대체수단 없는 승차 {row['no_alt_boarding_share']:.0%}"),
        ("길", f"평균 경사 {feas['slope_mean']:.1f}% · 1차로 {feas['one_lane_share']:.0%} · AI가 채운 구간 {feas['unobserved_share']:.0%}"),
        ("차 크기", van_line),
        ("없애면", f"어르신 {rem['net_elderly_affected']:,.0f}명이 평균 {rem['net_added_min_mean']:.1f}분 더 걷고,\n"
                  f"{rem['simple_elderly_over_10min_new']:,.0f}~{rem['net_elderly_over_10min_new']:,.0f}명은 10분 넘게 걷는다(간이~도로망)"),
    ]
    for i, (label, text) in enumerate(facts):
        y = 0.97 - i * 0.165
        at.text(0.0, y, label, fontsize=9, fontweight="bold", color=MUTED, va="top", transform=at.transAxes)
        at.text(0.15, y, text, fontsize=9.3, color=INK, va="top", transform=at.transAxes, linespacing=1.35)
    save(fig, out, filename)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "docs" / "figures" / "transit_report")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    setup_style()
    tables = load_tables()
    print(f"그림 저장: {args.out}")
    fig01_flow(args.out)
    fig02_ai_tiers(args.out)
    fig02_co2_per_km(tables, args.out)
    fig03_load_scatter(tables, args.out)
    fig04_hourly(tables, args.out)
    fig05_reduction(tables, args.out)
    fig07_elderly_cars(tables, args.out)
    fig06_quadrant(tables, args.out)
    fig08_map(tables, args.out)
    fig09_speed_check(tables, args.out)
    for name, filename, headline in CARDS:
        fig_route_card(tables, args.out, name, filename, headline)


if __name__ == "__main__":
    main()
