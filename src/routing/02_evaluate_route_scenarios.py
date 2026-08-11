"""대표 OD와 시간대에서 EV 경로 trade-off를 재현 가능하게 집계한다.

예시
----
python src/routing/02_evaluate_route_scenarios.py --timestamps 202607090800,202607141900,202607160800
"""

from __future__ import annotations

import argparse
from itertools import combinations
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.routing.engine import EcoRoutingEngine, RouteNotFoundError


POIS = {
    "강남역": (37.4979, 127.0276),
    "서울시청": (37.5665, 126.9780),
    "여의도": (37.5219, 126.9245),
    "잠실역": (37.5133, 127.1000),
    "홍대입구": (37.5572, 126.9245),
    "청량리": (37.5800, 127.0470),
    "구로디지털단지": (37.4853, 126.9016),
    "서울대입구": (37.4813, 126.9527),
    "사당": (37.4765, 126.9816),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="대표 OD의 EV 경로 절감률·시간 페널티 평가")
    parser.add_argument(
        "--timestamps", default="202607090800,202607140900,202607141900,202607160800",
        help="쉼표로 구분한 YYYYMMDDHHMM 시점 목록",
    )
    parser.add_argument("--max-pairs", type=int, default=30, help="POI 조합 중 평가할 최대 OD 수")
    parser.add_argument("--max-time-increase-pct", type=float, default=15.0)
    parser.add_argument("--dataset", choices=["hybrid", "prediction"], default="hybrid")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "processed" / "route_results")
    return parser.parse_args()


def source_path(tm: str, dataset: str) -> Path:
    directory = "historical_hybrid_link_energy" if dataset == "hybrid" else "link_energy"
    prefix = "hybrid_link_energy" if dataset == "hybrid" else "link_energy"
    return PROJECT_ROOT / "data" / "processed" / directory / f"{prefix}_{tm}.parquet"


def poi_pairs(max_pairs: int) -> list[tuple[str, tuple[float, float], tuple[float, float]]]:
    pairs = []
    for (origin_name, origin), (destination_name, destination) in combinations(POIS.items(), 2):
        pairs.append((f"{origin_name}→{destination_name}", origin, destination))
    return pairs[:max_pairs]


def evaluate_timestamp(tm: str, args: argparse.Namespace) -> list[dict]:
    path = source_path(tm, args.dataset)
    if not path.exists():
        raise FileNotFoundError(path)
    engine = EcoRoutingEngine.from_parquet(path)
    engine.load_geometry(PROJECT_ROOT / "data" / "interim" / "seoul_link.shp")
    records = []
    for od, origin, destination in poi_pairs(args.max_pairs):
        source = engine.snap(origin[1], origin[0])
        target = engine.snap(destination[1], destination[0])
        try:
            routes = engine.compare_with_balanced(source, target, args.max_time_increase_pct)
        except RouteNotFoundError:
            continue
        fastest, eco, balanced = routes["fastest"], routes["eco"], routes["balanced"]
        for route_name, route in routes.items():
            records.append({
                "tm": tm,
                "dataset": args.dataset,
                "od": od,
                "route_key": route_name,
                "route_type": route_name,
                **route.summary(),
                "fastest_energy_wh": fastest.energy_wh,
                "fastest_time_min": fastest.time_min,
                "eco_energy_saved_pct": (1 - eco.energy_wh / fastest.energy_wh) * 100,
                "eco_time_penalty_pct": (eco.time_min / fastest.time_min - 1) * 100,
                "balanced_energy_saved_pct": (1 - balanced.energy_wh / fastest.energy_wh) * 100,
                "balanced_time_penalty_pct": (balanced.time_min / fastest.time_min - 1) * 100,
            })
    return records


def main() -> None:
    args = parse_args()
    timestamps = [tm.strip() for tm in args.timestamps.split(",") if tm.strip()]
    if not timestamps:
        raise SystemExit("평가할 시점을 하나 이상 입력해야 합니다.")

    records: list[dict] = []
    for tm in timestamps:
        print(f"[평가] {tm}")
        records.extend(evaluate_timestamp(tm, args))
    detail = pd.DataFrame(records)
    if detail.empty:
        raise SystemExit("경로 비교 결과가 없습니다.")

    base = detail[detail["route_key"] == "fastest"]
    summary = base.groupby("tm", as_index=False).agg(
        od_count=("od", "nunique"),
        eco_energy_saved_pct_mean=("eco_energy_saved_pct", "mean"),
        eco_energy_saved_pct_median=("eco_energy_saved_pct", "median"),
        eco_time_penalty_pct_mean=("eco_time_penalty_pct", "mean"),
        balanced_energy_saved_pct_mean=("balanced_energy_saved_pct", "mean"),
        balanced_time_penalty_pct_mean=("balanced_time_penalty_pct", "mean"),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    detail.to_csv(args.output_dir / "route_evaluation_detail.csv", index=False, encoding="utf-8-sig")
    summary.round(3).to_csv(args.output_dir / "route_evaluation_summary.csv", index=False, encoding="utf-8-sig")
    print(summary.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
