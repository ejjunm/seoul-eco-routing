"""같은 속도 입력에서 전기차(VT-CPEM)와 휘발유차(ice_fuel)의 에코라우팅 효과를 비교한다.

02_evaluate_route_scenarios.py와 같은 대표 9개 지점(30개 OD)과 Pareto 균형경로(최단시간 대비
지연 상한)를 쓰되, 링크 비용을 models/04의 전 링크 속도 예측 CSV 한 시점에서 직접 만든다.
엔진의 energy 필드에 전기차는 배터리 Wh, 휘발유차는 CO2 g을 넣으므로 각 차량 안에서의
절감률(%)만 비교한다. 휘발유차의 최단시간 경로는 전기차와 같다(시간 비용이 같기 때문).

예시
----
python src/routing/03_compare_ev_ice_routes.py --timestamps 202607160800,202607141900,202607142300
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.energy.ice_fuel import calculate_link_fuel
from src.energy.link_energy import calculate_link_energy
from src.routing.engine import Edge, EcoRoutingEngine, RouteNotFoundError

ROUTE_EVAL = PROJECT_ROOT / "src" / "routing" / "02_evaluate_route_scenarios.py"
PREDICTION_DIR = PROJECT_ROOT / "data" / "processed"


def load_poi_pairs(max_pairs: int):
    import importlib.util

    spec = importlib.util.spec_from_file_location("route_eval", ROUTE_EVAL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.poi_pairs(max_pairs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="전기차·휘발유차 에코라우팅 효과 비교")
    parser.add_argument("--timestamps", default="202607160800,202607141900,202607142300")
    parser.add_argument("--max-pairs", type=int, default=30)
    parser.add_argument("--max-time-increase-pct", type=float, default=15.0)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "processed" / "route_results")
    return parser.parse_args()


def link_costs(tm: str) -> pd.DataFrame:
    path = PREDICTION_DIR / f"all_link_speed_prediction_{tm}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} — 먼저 src/models/04_batch_predict_all_link_speed.py를 실행하세요.")
    frame = pd.read_csv(path, dtype={"LINK_ID": str, "F_NODE": str, "T_NODE": str})
    frame = frame[(frame["LENGTH"] > 0) & (frame["speed_kmh"] > 0)].copy()
    frame["slope_pct"] = frame["slope_pct"].fillna(0.0)
    energy_input = frame[["LINK_ID", "LENGTH", "speed_kmh", "slope_pct"]]
    frame["travel_time_sec"] = frame["LENGTH"] / (frame["speed_kmh"] / 3.6)
    frame["ev_wh"] = calculate_link_energy(energy_input)["energy_ev_wh"].to_numpy()
    frame["ice_co2_g"] = calculate_link_fuel(energy_input)["co2_g"].to_numpy()
    return frame


def build_engine(frame: pd.DataFrame, cost_column: str) -> EcoRoutingEngine:
    edges = (
        Edge(
            link_id=row.LINK_ID, from_node=row.F_NODE, to_node=row.T_NODE, length_m=float(row.LENGTH),
            travel_time_sec=float(row.travel_time_sec), energy_wh=float(getattr(row, cost_column)),
            speed_kmh=float(row.speed_kmh), slope_pct=float(row.slope_pct), tier=str(row.tier),
            confidence=str(row.prediction_confidence), road_name=str(row.ROAD_NAME) if pd.notna(row.ROAD_NAME) else "",
        )
        for row in frame.itertuples(index=False)
    )
    engine = EcoRoutingEngine(edges)
    engine.load_geometry(PROJECT_ROOT / "data" / "interim" / "seoul_link.shp")
    return engine


def main() -> None:
    args = parse_args()
    pairs = load_poi_pairs(args.max_pairs)
    records = []
    for tm in [t.strip() for t in args.timestamps.split(",") if t.strip()]:
        print(f"[평가] {tm}")
        frame = link_costs(tm)
        for vehicle, column in (("전기차", "ev_wh"), ("휘발유차", "ice_co2_g")):
            engine = build_engine(frame, column)
            for od, origin, destination in pairs:
                source = engine.snap(origin[1], origin[0])
                target = engine.snap(destination[1], destination[0])
                try:
                    routes = engine.compare_with_balanced(source, target, args.max_time_increase_pct)
                except RouteNotFoundError:
                    continue
                fastest, eco, balanced = routes["fastest"], routes["eco"], routes["balanced"]
                records.append({
                    "tm": tm, "vehicle": vehicle, "od": od,
                    "fastest_cost": fastest.energy_wh, "fastest_time_min": fastest.time_min,
                    "fastest_km": fastest.distance_km,
                    "eco_saved_pct": (1 - eco.energy_wh / fastest.energy_wh) * 100,
                    "eco_time_pct": (eco.time_min / fastest.time_min - 1) * 100,
                    "balanced_saved_pct": (1 - balanced.energy_wh / fastest.energy_wh) * 100,
                    "balanced_time_pct": (balanced.time_min / fastest.time_min - 1) * 100,
                })
    detail = pd.DataFrame(records)
    if detail.empty:
        raise SystemExit("경로 비교 결과가 없습니다.")
    summary = detail.groupby(["tm", "vehicle"], as_index=False).agg(
        od=("od", "nunique"),
        eco_saved_pct=("eco_saved_pct", "mean"), eco_time_pct=("eco_time_pct", "mean"),
        balanced_saved_pct=("balanced_saved_pct", "mean"), balanced_time_pct=("balanced_time_pct", "mean"),
    )
    ice = detail[detail["vehicle"] == "휘발유차"]
    summary_ice_g = ice.groupby("tm")["fastest_cost"].mean().rename("ice_fastest_co2_g_mean")
    summary = summary.join(summary_ice_g, on="tm")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    detail.to_csv(args.output_dir / "ev_ice_route_detail.csv", index=False, encoding="utf-8-sig")
    summary.round(3).to_csv(args.output_dir / "ev_ice_route_summary.csv", index=False, encoding="utf-8-sig")
    print(summary.round(2).to_string(index=False))
    overall = detail.groupby("vehicle")[["eco_saved_pct", "eco_time_pct", "balanced_saved_pct", "balanced_time_pct"]].mean()
    print("\n전체 평균\n" + overall.round(2).to_string())


if __name__ == "__main__":
    main()
