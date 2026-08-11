"""한 시각의 전 링크 속도 파일을 VT-CPEM 에너지 비용으로 변환한다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.energy.link_energy import calculate_link_energy, energy_output_columns


PROCESSED = PROJECT_ROOT / "data" / "processed"
DEFAULT_OUTPUT_DIR = PROCESSED / "link_energy"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="한 시간의 링크별 VT-CPEM 에너지 비용 계산")
    parser.add_argument("--tm", required=True, help="시각 YYYYMMDDHHMM")
    parser.add_argument("--input", type=Path, help="속도 CSV 경로. 생략 시 표준 파일명 사용")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def input_path_for(tm: str, explicit: Path | None = None) -> Path:
    return explicit or PROCESSED / f"all_link_speed_prediction_{tm}.csv"


def output_path_for(tm: str, output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    return output_dir / f"link_energy_{tm}.parquet"


def compute_one(tm: str, input_path: Path, output_path: Path, overwrite: bool = False) -> dict:
    if not input_path.exists():
        raise FileNotFoundError(f"속도 예측 파일이 없습니다: {input_path}")
    if output_path.exists() and not overwrite:
        return {"tm": tm, "status": "skipped", "output": str(output_path)}

    usecols = [
        "LINK_ID", "F_NODE", "T_NODE", "LENGTH", "ROAD_NAME", "speed_kmh", "slope_pct", "precip_mm",
        "tier", "speed_source", "prediction_confidence",
    ]
    speed = pd.read_csv(input_path, usecols=usecols, dtype={"LINK_ID": str, "F_NODE": str, "T_NODE": str}, encoding="utf-8-sig")
    energy = calculate_link_energy(speed)
    energy.insert(0, "tm", tm)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    energy[energy_output_columns(energy)].to_parquet(output_path, index=False, compression="zstd")

    return {
        "tm": tm,
        "status": "created",
        "output": str(output_path),
        "links": len(energy),
        "null_energy": int(energy["energy_ev_j"].isna().sum()),
        "negative_energy": int((energy["energy_ev_j"] < 0).sum()),
        "slope_outliers": int(energy["slope_outlier_flag"].sum()),
        "mean_wh": float(energy["energy_ev_wh"].mean()),
    }


def main() -> None:
    args = parse_args()
    input_path = input_path_for(args.tm, args.input)
    output_path = output_path_for(args.tm, args.output_dir)
    result = compute_one(args.tm, input_path, output_path, args.overwrite)
    print(result)


if __name__ == "__main__":
    main()
