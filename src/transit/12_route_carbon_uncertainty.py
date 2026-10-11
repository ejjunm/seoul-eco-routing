"""속도 분위수+conformal 결과를 노선 에너지·탄소·정책 분류 불확실성으로 전달한다.

05_build_speed_uncertainty.py의 완전 분리 test 링크에서 얻은 보정 구간 폭을
모델 tier×시간대별 중앙값으로 요약해 기존 평일 속도 프로필에 옮긴다. 이후 VT-CPEM을
구간 하한·중앙·상한 속도에서 다시 계산한다. 에너지는 속도에 단조롭지 않으므로 세 값의
최솟값/최댓값을 사용한다.

주의: 개별 속도 행에는 90% conformal 구간이지만, 모든 링크의 끝점을 동시에 합산한
노선 구간은 보수적 민감도 범위이며 '노선 단위 90% 확률구간'은 아니다.

출력
  data/processed/transit/route_carbon_uncertainty.csv
  data/processed/transit/route_carbon_uncertainty_summary.json

사용: python src/transit/12_route_carbon_uncertainty.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from energy import bus_fuel  # noqa: E402
from energy.ev_calibration import calibrate_county_electric  # noqa: E402
from energy.link_energy import VTCPEMParameters, calculate_link_energy  # noqa: E402


PROCESSED = PROJECT_ROOT / "data" / "processed"
TRANSIT = PROCESSED / "transit"
UNCERTAINTY = PROCESSED / "model_uncertainty"
OPERATING_HOURS = range(8, 23)
GRID_KG_CO2_PER_KWH = 0.4173
BUS_FLEET = {"전기": 397, "CNG": 885, "경유": 344}


def interval_width_lookup() -> pd.DataFrame:
    test = pd.read_csv(UNCERTAINTY / "test_predictions.csv", dtype={"LINK_ID": str})
    test["lower_width"] = test["speed_median"] - test["speed_lower"]
    test["upper_width"] = test["speed_upper"] - test["speed_median"]
    lookup = test.groupby(["tier", "시간코드"], as_index=False)[["lower_width", "upper_width"]].median()
    # 드문 C tier×시간대가 비면 tier 전체, 그래도 비면 전체 중앙값으로 보완한다.
    tiers = test.groupby("tier")[["lower_width", "upper_width"]].median()
    overall = test[["lower_width", "upper_width"]].median()
    rows = []
    for tier in ["A_lookup", "B_neighbor_model", "C_static_model"]:
        source_tier = "B_neighbor_model" if tier == "A_lookup" else tier
        for hour in OPERATING_HOURS:
            hit = lookup[(lookup["tier"] == source_tier) & (lookup["시간코드"] == hour)]
            if not hit.empty:
                widths = hit.iloc[0][["lower_width", "upper_width"]]
            elif source_tier in tiers.index:
                widths = tiers.loc[source_tier]
            else:
                widths = overall
            rows.append({"tier": tier, "시간코드": hour,
                         "lower_width": float(widths["lower_width"]),
                         "upper_width": float(widths["upper_width"])})
    return pd.DataFrame(rows)


def route_link_hours() -> pd.DataFrame:
    links = pd.read_csv(TRANSIT / "route_links.csv", dtype={"ROUTE_ID": str, "LINK_ID": str})
    links = links[links["kind"] == "마을버스"].copy()
    dim = pd.read_csv(PROCESSED / "seoul_link_dimension.csv",
                      usecols=["LINK_ID", "slope_pct", "MAX_SPD"], dtype={"LINK_ID": str})
    links = links.merge(dim, on="LINK_ID", how="left")
    links["slope_pct"] = np.where(links["reversed"], -1, 1) * links["slope_pct"].fillna(0)
    profile = pd.read_parquet(TRANSIT / "link_speed_weekday_profile.parquet",
                              columns=["LINK_ID", "시간코드", "speed_kmh", "tier"])
    profile = profile[profile["시간코드"].isin(OPERATING_HOURS)]
    frame = links.merge(profile, on="LINK_ID", how="inner").merge(
        interval_width_lookup(), on=["tier", "시간코드"], how="left", validate="many_to_one"
    )
    if frame[["lower_width", "upper_width"]].isna().any().any():
        raise SystemExit("일부 tier×시간대의 불확실성 폭을 만들지 못했습니다.")
    frame["speed_lower"] = (frame["speed_kmh"] - frame["lower_width"]).clip(lower=3.0)
    frame["speed_upper"] = frame["speed_kmh"] + frame["upper_width"]
    limit = pd.to_numeric(frame["MAX_SPD"], errors="coerce").fillna(110).clip(lower=3)
    frame["speed_upper"] = np.minimum(frame["speed_upper"], limit)
    frame["speed_upper"] = np.maximum(frame["speed_upper"], frame["speed_kmh"])
    return frame


def route_energy_interval(frame: pd.DataFrame) -> pd.DataFrame:
    county, extra_w = calibrate_county_electric()
    params = replace(
        VTCPEMParameters(), mass_kg=7000.0, drag_coefficient=county.drag_coefficient,
        frontal_area_m2=county.frontal_area_m2, auxiliary_power_w=5000.0 + extra_w,
    )
    energy_values = []
    for speed_col in ["speed_lower", "speed_kmh", "speed_upper"]:
        inp = frame[["LINK_ID", "LENGTH", "slope_pct"]].copy()
        inp["speed_kmh"] = frame[speed_col].to_numpy()
        energy_values.append(calculate_link_energy(inp[["LINK_ID", "LENGTH", "speed_kmh", "slope_pct"]], params)[
            "energy_ev_wh"
        ].to_numpy())
    energy = np.column_stack(energy_values)
    frame = frame.copy()
    frame["wh_lower"] = energy.min(axis=1)
    frame["wh_center"] = energy[:, 1]
    frame["wh_upper"] = energy.max(axis=1)
    hourly = frame.groupby(["ROUTE_ID", "시간코드"], as_index=False).agg(
        wh_lower=("wh_lower", "sum"), wh_center=("wh_center", "sum"),
        wh_upper=("wh_upper", "sum"), matched_m=("LENGTH", "sum"),
    )
    per_route = hourly.groupby("ROUTE_ID", as_index=False).agg(
        wh_lower=("wh_lower", "mean"), wh_center=("wh_center", "mean"),
        wh_upper=("wh_upper", "mean"), matched_m=("matched_m", "first"),
    )
    official = pd.read_csv(TRANSIT / "routes.csv", dtype={"ROUTE_ID": str}).set_index("ROUTE_ID")["length_km"]
    scale = per_route["ROUTE_ID"].map(official) / (per_route["matched_m"] / 1000.0)
    for label in ["lower", "center", "upper"]:
        per_route[f"bus_kwh_per_km_{label}"] = per_route[f"wh_{label}"] * scale / 1000.0 / per_route["ROUTE_ID"].map(official)
    return per_route[["ROUTE_ID", "bus_kwh_per_km_lower", "bus_kwh_per_km_center", "bus_kwh_per_km_upper"]]


def fleet_bus_g_per_km(kwh_per_km: pd.Series) -> pd.Series:
    total = sum(BUS_FLEET.values())
    electric = kwh_per_km * GRID_KG_CO2_PER_KWH * 1000.0
    diesel = bus_fuel.diesel_g_per_km(kwh_per_km)
    cng = bus_fuel.cng_g_per_km(kwh_per_km)
    return (BUS_FLEET["전기"] * electric + BUS_FLEET["경유"] * diesel + BUS_FLEET["CNG"] * cng) / total


def class_for(high_dependence: pd.Series, efficient: pd.Series) -> np.ndarray:
    return np.select(
        [high_dependence & efficient, high_dependence & ~efficient, ~high_dependence & efficient],
        [1, 2, 3], default=4,
    )


def main() -> None:
    required = [UNCERTAINTY / "test_predictions.csv", TRANSIT / "link_speed_weekday_profile.parquet"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("먼저 속도 불확실성 모델/노선 파이프라인을 실행하세요:\n- " + "\n- ".join(missing))
    print("[1/4] 노선 링크×시간대에 보정 속도 구간 결합...")
    frame = route_link_hours()
    print("[2/4] VT-CPEM 에너지 민감도 범위 계산...")
    interval = route_energy_interval(frame)

    print("[3/4] 탄소 비교와 정책 분류 안정성 판정...")
    carbon = pd.read_csv(TRANSIT / "route_carbon_breakeven.csv", dtype={"ROUTE_ID": str})
    priority = pd.read_csv(TRANSIT / "route_priority.csv", dtype={"ROUTE_ID": str})[
        ["ROUTE_ID", "노선명", "class_id", "class", "dependence_score"]
    ]
    out = carbon.merge(interval, on="ROUTE_ID", how="inner").merge(priority, on="ROUTE_ID", how="left")
    for label in ["lower", "center", "upper"]:
        out[f"bus_g_per_km_{label}"] = fleet_bus_g_per_km(out[f"bus_kwh_per_km_{label}"])
        out[f"bus_g_per_pkm_{label}"] = out[f"bus_g_per_km_{label}"] / out["avg_load"]
        out[f"bus_vs_car_{label}"] = out[f"bus_g_per_pkm_{label}"] / out["car_g_per_pkm"]

    valid = ~out["load_qa_flag"]
    carbon_threshold = float(out.loc[valid, "bus_g_per_pkm"].median())
    dependence_threshold = float(out.loc[valid, "dependence_score"].median())
    high_dep = out["dependence_score"] >= dependence_threshold
    efficient_low = out["bus_g_per_pkm_lower"] <= carbon_threshold
    efficient_high = out["bus_g_per_pkm_upper"] <= carbon_threshold
    out["class_if_low_energy"] = class_for(high_dep, efficient_low)
    out["class_if_high_energy"] = class_for(high_dep, efficient_high)
    out["class_stable"] = out["class_if_low_energy"] == out["class_if_high_energy"]
    out["car_comparison"] = np.select(
        [out["bus_vs_car_upper"] < 1.0, out["bus_vs_car_lower"] >= 1.0],
        ["버스 우위(구간 전체)", "승용차 우위(구간 전체)"], default="경계/불확실",
    )
    out.to_csv(TRANSIT / "route_carbon_uncertainty.csv", index=False, encoding="utf-8-sig")

    ok = out[valid]
    summary = {
        "n_routes": int(len(ok)),
        "speed_interval_source": "held-out-link conformal interval widths transferred by tier and hour",
        "route_interval_interpretation": "conservative sensitivity range, not a route-level 90% probability interval",
        "carbon_efficiency_threshold_g_per_pkm": carbon_threshold,
        "dependence_threshold": dependence_threshold,
        "stable_class_count": int(ok["class_stable"].sum()),
        "unstable_class_count": int((~ok["class_stable"]).sum()),
        "car_comparison_counts": ok["car_comparison"].value_counts().to_dict(),
        "median_bus_kwh_per_km": {
            label: float(ok[f"bus_kwh_per_km_{label}"].median()) for label in ["lower", "center", "upper"]
        },
    }
    (TRANSIT / "route_carbon_uncertainty_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[4/4] 완료")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
