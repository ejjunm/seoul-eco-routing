"""기간 전체의 전 링크 속도 파일을 VT-CPEM 에너지 비용으로 일괄 변환한다."""

from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ONE_SCRIPT = PROJECT_ROOT / "src" / "energy" / "01_compute_link_energy.py"
PATTERN = re.compile(r"all_link_speed_prediction_(\d{12})\.csv$")


def load_one_script():
    """번호로 시작하는 01 스크립트를 안전하게 모듈로 불러온다."""
    spec = importlib.util.spec_from_file_location("compute_link_energy_one", ONE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"계산 스크립트를 불러올 수 없습니다: {ONE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="기간 전체 링크 에너지 비용 배치 계산")
    parser.add_argument("--start-date", default="20260707", help="시작일 YYYYMMDD")
    parser.add_argument("--end-date", default="20260720", help="종료일 YYYYMMDD")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "processed" / "link_energy")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def target_files(start_date: str, end_date: str, processed_dir: Path) -> list[tuple[str, Path]]:
    start = pd.to_datetime(start_date, format="%Y%m%d")
    end = pd.to_datetime(end_date, format="%Y%m%d") + pd.Timedelta(hours=23)
    selected = []
    for path in sorted(processed_dir.glob("all_link_speed_prediction_*.csv")):
        match = PATTERN.match(path.name)
        if not match:
            continue
        tm = match.group(1)
        timestamp = pd.to_datetime(tm, format="%Y%m%d%H%M")
        if start <= timestamp <= end:
            selected.append((tm, path))
    return selected


def main() -> None:
    args = parse_args()
    one = load_one_script()
    files = target_files(args.start_date, args.end_date, one.PROCESSED)
    if not files:
        raise SystemExit("해당 기간의 속도 예측 CSV를 찾지 못했습니다.")

    summaries = []
    for index, (tm, input_path) in enumerate(files, start=1):
        result = one.compute_one(tm, input_path, one.output_path_for(tm, args.output_dir), args.overwrite)
        summaries.append(result)
        print(f"[{index}/{len(files)}] {tm} {result['status']}")

    summary = pd.DataFrame(summaries)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.output_dir / "link_energy_batch_summary.csv", index=False, encoding="utf-8-sig")
    created = int((summary["status"] == "created").sum())
    print(f"완료: 생성 {created}개 / 전체 {len(summary)}개")


if __name__ == "__main__":
    main()
