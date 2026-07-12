from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MPL_CONFIG_DIR = PROJECT_ROOT / ".matplotlib"
MPL_CONFIG_DIR.mkdir(exist_ok=True)
os.environ["MPLCONFIGDIR"] = str(MPL_CONFIG_DIR)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


EDA_DIR = PROJECT_ROOT / "data" / "processed" / "eda"
OUT_DIR = EDA_DIR / "charts"
DOCS_OUT_DIR = PROJECT_ROOT / "docs" / "figures" / "eda"

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

COLORS = {
    "no_rain": "#4C78A8",
    "rain": "#E45756",
    "bar": "#59A14F",
    "bar2": "#F28E2B",
    "line": "#2F4B7C",
}


def read_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(EDA_DIR / name, encoding="utf-8-sig")


def add_labels(ax, fmt="{:.1f}", dy=0.25):
    for patch in ax.patches:
        height = patch.get_height()
        if pd.isna(height):
            continue
        ax.text(
            patch.get_x() + patch.get_width() / 2,
            height + dy,
            fmt.format(height),
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )


def finish(fig, ax, out_name: str, ylim_pad=0.16):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax.set_axisbelow(True)
    top = ax.get_ylim()[1]
    ax.set_ylim(0, top * (1 + ylim_pad))
    fig.tight_layout()
    out_path = OUT_DIR / out_name
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    docs_out_path = DOCS_OUT_DIR / out_name
    fig.savefig(docs_out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    print("saved", out_path)
    print("saved", docs_out_path)


def plot_rain_flag():
    df = read_csv("speed_by_rain_flag.csv")
    order = ["no_rain", "rain"]
    df = df.set_index("rain_flag").loc[order].reset_index()

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.bar(
        ["비 없음", "비 옴"],
        df["mean_speed"],
        color=[COLORS["no_rain"], COLORS["rain"]],
        width=0.55,
    )
    ax.set_title("강수 여부별 평균속도", fontsize=17, fontweight="bold", pad=16)
    ax.set_ylabel("평균속도 (km/h)")
    add_labels(ax)
    finish(fig, ax, "01_rain_flag_speed.png")


def plot_rain_bin():
    df = read_csv("speed_by_rain_bin.csv")
    labels = df["rain_bin"].tolist()

    fig, ax = plt.subplots(figsize=(8.4, 4.8))
    ax.plot(labels, df["mean_speed"], color=COLORS["line"], marker="o", linewidth=2.8)
    ax.scatter(labels, df["mean_speed"], s=90, color=COLORS["rain"], zorder=3)
    for x, y in zip(labels, df["mean_speed"]):
        ax.text(x, y + 0.08, f"{y:.1f}", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_title("강수량 구간별 평균속도", fontsize=17, fontweight="bold", pad=16)
    ax.set_xlabel("1시간 누적 강수량")
    ax.set_ylabel("평균속도 (km/h)")
    finish(fig, ax, "02_rain_intensity_speed.png", ylim_pad=0.08)


def plot_abs_slope_bin():
    df = read_csv("speed_by_abs_slope_bin.csv")

    fig, ax = plt.subplots(figsize=(8.4, 4.8))
    ax.bar(df["abs_slope_bin"], df["mean_speed"], color=COLORS["bar"], width=0.58)
    ax.set_title("경사도 구간별 평균속도", fontsize=17, fontweight="bold", pad=16)
    ax.set_xlabel("절대경사도")
    ax.set_ylabel("평균속도 (km/h)")
    add_labels(ax)
    finish(fig, ax, "03_slope_bin_speed.png")


def plot_rain_slope_group():
    df = read_csv("speed_by_rain_slope_group.csv")
    order = ["no_rain + not_steep", "rain + not_steep", "no_rain + steep", "rain + steep"]
    labels = ["무강수\n완만", "강수\n완만", "무강수\n급경사", "강수\n급경사"]
    df = df.set_index("rain_slope_group").loc[order].reset_index()

    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.bar(labels, df["mean_speed"], color=["#4C78A8", "#E45756", "#76B7B2", "#F28E2B"], width=0.58)
    ax.set_title("강수와 급경사 조합별 평균속도", fontsize=17, fontweight="bold", pad=16)
    ax.set_ylabel("평균속도 (km/h)")
    add_labels(ax)
    finish(fig, ax, "04_rain_slope_combo_speed.png")


def plot_peak_rain():
    df = read_csv("speed_by_peak_rain.csv")
    period_col = df.columns[0]
    pivot = df.pivot(index=period_col, columns="rain_flag", values="mean_speed").loc[["N", "T1", "T2", "T3"]]
    labels = ["비첨두", "오전첨두", "낮", "오후첨두"]
    x = range(len(pivot))
    width = 0.36

    fig, ax = plt.subplots(figsize=(8.8, 5.0))
    ax.bar([i - width / 2 for i in x], pivot["no_rain"], width, label="비 없음", color=COLORS["no_rain"])
    ax.bar([i + width / 2 for i in x], pivot["rain"], width, label="비 옴", color=COLORS["rain"])
    ax.set_xticks(list(x), labels)
    ax.set_title("첨두시간대별 강수 시 평균속도 변화", fontsize=17, fontweight="bold", pad=16)
    ax.set_ylabel("평균속도 (km/h)")
    ax.legend(frameon=False, ncols=2, loc="upper right")
    add_labels(ax, dy=0.35)
    finish(fig, ax, "05_peak_rain_speed.png")


def plot_road_rank_rain():
    df = read_csv("speed_by_road_rank_rain.csv")
    pivot = df.pivot(index="ROAD_RANK", columns="rain_flag", values="mean_speed").sort_index()
    x = range(len(pivot))
    width = 0.36

    fig, ax = plt.subplots(figsize=(9.2, 5.2))
    ax.bar([i - width / 2 for i in x], pivot["no_rain"], width, label="비 없음", color=COLORS["no_rain"])
    ax.bar([i + width / 2 for i in x], pivot["rain"], width, label="비 옴", color=COLORS["rain"])
    ax.set_xticks(list(x), [str(v) for v in pivot.index])
    ax.set_title("도로등급별 강수 시 평균속도 변화", fontsize=17, fontweight="bold", pad=16)
    ax.set_xlabel("ROAD_RANK")
    ax.set_ylabel("평균속도 (km/h)")
    ax.legend(frameon=False, ncols=2, loc="upper right")
    add_labels(ax, dy=0.55)
    finish(fig, ax, "06_road_rank_rain_speed.png", ylim_pad=0.2)


def plot_correlations():
    df = read_csv("speed_feature_correlations.csv")
    df = df[df["feature"] != "평균속도"].copy()
    df = df.sort_values("corr_with_avg_speed")
    colors = ["#E45756" if v < 0 else "#4C78A8" for v in df["corr_with_avg_speed"]]

    fig, ax = plt.subplots(figsize=(8.2, 5.0))
    ax.barh(df["feature"], df["corr_with_avg_speed"], color=colors)
    ax.axvline(0, color="#111827", linewidth=1)
    ax.set_title("평균속도와 주요 변수 상관계수", fontsize=17, fontweight="bold", pad=16)
    ax.set_xlabel("상관계수")
    ax.set_xlim(-0.14, 0.56)
    for patch in ax.patches:
        width = patch.get_width()
        x = width + (0.015 if width >= 0 else -0.015)
        ha = "left" if width >= 0 else "right"
        ax.text(x, patch.get_y() + patch.get_height() / 2, f"{width:.3f}", va="center", ha=ha, fontsize=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", color="#E5E7EB", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    out_path = OUT_DIR / "07_feature_correlation_speed.png"
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    docs_out_path = DOCS_OUT_DIR / "07_feature_correlation_speed.png"
    fig.savefig(docs_out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    print("saved", out_path)
    print("saved", docs_out_path)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_OUT_DIR.mkdir(parents=True, exist_ok=True)
    plot_rain_flag()
    plot_rain_bin()
    plot_abs_slope_bin()
    plot_rain_slope_group()
    plot_peak_rain()
    plot_road_rank_rain()
    plot_correlations()
    print("chart output dir:", OUT_DIR)


if __name__ == "__main__":
    main()
