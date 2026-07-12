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


PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
EDA_DIR = PROCESSED_DATA_DIR / "eda"
OUT_DIR = EDA_DIR / "tables"

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False


TABLES = [
    ("speed_by_rain_flag.csv", "Rain Presence vs Average Speed"),
    ("speed_by_rain_bin.csv", "Rain Intensity vs Average Speed"),
    ("speed_by_abs_slope_bin.csv", "Absolute Slope vs Average Speed"),
    ("speed_by_rain_slope_group.csv", "Rain and Slope Combination vs Average Speed"),
    ("speed_by_peak_rain.csv", "Peak Period Rain Effect"),
    ("speed_by_road_rank_rain.csv", "Road Rank Rain Effect"),
    ("speed_feature_correlations.csv", "Feature Correlation with Average Speed"),
]


def format_number(value):
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def draw_table(csv_name: str, title: str) -> None:
    df = pd.read_csv(EDA_DIR / csv_name, encoding="utf-8-sig")
    display_df = df.copy()

    for column in display_df.columns:
        display_df[column] = display_df[column].map(format_number)

    row_count = len(display_df)
    col_count = len(display_df.columns)
    fig_width = max(9, col_count * 1.7)
    fig_height = max(2.8, row_count * 0.42 + 1.2)

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis("off")
    ax.set_title(title, fontsize=16, fontweight="bold", pad=16)

    table = ax.table(
        cellText=display_df.values,
        colLabels=display_df.columns,
        cellLoc="center",
        colLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.35)

    for (row, _col), cell in table.get_celld().items():
        cell.set_edgecolor("#D6D6D6")
        if row == 0:
            cell.set_facecolor("#243B53")
            cell.set_text_props(color="white", fontweight="bold")
        elif row % 2 == 0:
            cell.set_facecolor("#F6F8FA")
        else:
            cell.set_facecolor("white")

    fig.tight_layout()
    out_path = OUT_DIR / f"{Path(csv_name).stem}.png"
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    print("저장:", out_path)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for csv_name, title in TABLES:
        draw_table(csv_name, title)
    print("표 이미지 폴더:", OUT_DIR)


if __name__ == "__main__":
    main()
