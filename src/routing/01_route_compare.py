"""현재 EV 에너지 Parquet으로 한 OD의 세 경로를 비교한다.

예시
----
python src/routing/01_route_compare.py --tm 202607160800 \
  --origin 37.4979,127.0276 --destination 37.5665,126.9780
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.routing.engine import EcoRoutingEngine


def parse_point(value: str) -> tuple[float, float]:
    try:
        latitude, longitude = (float(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("좌표는 '위도,경도' 형식이어야 합니다.") from exc
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise argparse.ArgumentTypeError("좌표 범위가 올바르지 않습니다.")
    return latitude, longitude


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="서울 EV 최단시간·최소에너지 경로 비교")
    parser.add_argument("--tm", required=True, help="시각 YYYYMMDDHHMM")
    parser.add_argument("--origin", required=True, type=parse_point, help="출발 위도,경도")
    parser.add_argument("--destination", required=True, type=parse_point, help="도착 위도,경도")
    parser.add_argument(
        "--dataset", choices=["hybrid", "prediction"], default="hybrid",
        help="hybrid=과거 재현, prediction=이력 기반 예측",
    )
    parser.add_argument(
        "--max-time-increase-pct", type=float, default=15.0,
        help="균형 경로에 허용할 최단시간 대비 시간 증가율(%%)",
    )
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "processed" / "route_results")
    return parser.parse_args()


def input_path(tm: str, dataset: str) -> Path:
    if dataset == "hybrid":
        return PROJECT_ROOT / "data" / "processed" / "historical_hybrid_link_energy" / f"hybrid_link_energy_{tm}.parquet"
    return PROJECT_ROOT / "data" / "processed" / "link_energy" / f"link_energy_{tm}.parquet"


def main() -> None:
    args = parse_args()
    source_path = input_path(args.tm, args.dataset)
    if not source_path.exists():
        raise SystemExit(f"에너지 파일이 없습니다: {source_path}")

    engine = EcoRoutingEngine.from_parquet(source_path)
    engine.load_geometry(PROJECT_ROOT / "data" / "interim" / "seoul_link.shp")
    origin_lat, origin_lon = args.origin
    destination_lat, destination_lon = args.destination
    source = engine.snap(origin_lon, origin_lat)
    target = engine.snap(destination_lon, destination_lat)
    routes = engine.compare_with_balanced(source, target, args.max_time_increase_pct)

    fastest = routes["fastest"]
    eco = routes["eco"]
    comparison = {
        "tm": args.tm,
        "dataset": args.dataset,
        "balanced_max_time_increase_pct": args.max_time_increase_pct,
        "snapped_nodes": {"origin": source, "destination": target},
        "routes": [route.summary() for route in routes.values()],
        "eco_vs_fastest": {
            "energy_saved_wh": round(fastest.energy_wh - eco.energy_wh, 2),
            "energy_saved_pct": round((1 - eco.energy_wh / fastest.energy_wh) * 100, 2),
            "time_penalty_min": round(eco.time_min - fastest.time_min, 2),
            "time_penalty_pct": round((eco.time_min / fastest.time_min - 1) * 100, 2),
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"route_compare_{args.tm}_{args.dataset}"
    (args.output_dir / f"{stem}.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / f"{stem}.geojson").write_text(
        json.dumps(engine.routes_geojson(routes.values()), ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(comparison, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
