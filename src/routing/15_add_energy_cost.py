"""
15. 링크별 에너지 비용 계산 (Stage 2: 속도 -> 에너지)

13번(전 링크 속도 스냅샷)의 결과에 DEM 경사를 결합해, 링크를 통과할 때의
'통과 에너지'를 물리(도로하중) 모델로 계산한다. 내연기관(ICE)과 전기차(EV)를
모두 산출한다.

에너지 모델 (거리기반 도로하중, CMEM 계열):
  E[J] = L * ( P_aux/(eta*v) + (m*g*Cr + 0.5*rho*Cd*A*v^2 + m*g*sinθ) / eta )  (+ EV 회생)

  - P_aux/(eta*v) : 공회전/보조장치 전력(시간 비례 -> 거리로는 /v)
  - m*g*Cr        : 구름저항
  - 0.5*rho*Cd*A*v^2 : 공기저항
  - m*g*sinθ      : 중력(경사) — signed. 오르막(+)은 소비, 내리막(-)은 저항을 상쇄
  * 팀 초안의 순간파워형 Y=L*(a+bv+cv^3+dv*sinθ)은 링크길이 곱 시 v배 과대평가 -> 거리기반형 사용.

경사(내리막) 처리 — 명관 개선안 반영:
  - 오르막/내리막을 분리(signed slope). 내리막을 단순 음수로 두지 않는다.
  - ICE: 내리막 여유 에너지를 회수하지 못함(회생 0) -> 통과에너지 = 공회전(보조) 에너지 하한.
  - EV : 내리막 저항 상쇄분을 회생효율(eta_regen)로 일부 회수. 단 전체 에너지는 보조전력 하한 이상으로 클리핑
         -> 경로탐색(Dijkstra)에 필요한 '비음수' 비용 보장.

주의: 차량 실측 자료가 없으므로 이 값은 '에너지 예측'이 아니라 '기준 차량 시뮬레이션'이다.
      계수(질량/효율 등)는 대표값이며 조정 가능하다.

입력:  data/processed/seoul_all_link_speed_{tm}.csv  (routing/13 산출: LINK_ID, speed_kmh, LENGTH, ...)
       data/processed/seoul_link_dimension.csv       (slope_pct: signed 경사 % — 13번 산출에 없을 때만)
출력:  data/processed/seoul_all_link_energy_{tm}.csv

사용:  python src/routing/15_add_energy_cost.py --tm 202607160800
       python src/routing/15_add_energy_cost.py --tm 202607160800 --load-factor 1.0   # 만차(4️⃣ 시나리오)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED = PROJECT_ROOT / "data" / "processed"
DIMENSION_PATH = PROCESSED / "seoul_link_dimension.csv"   # 경사는 차원 테이블에 링크당 1행

GRAVITY = 9.81
V_FLOOR_KMH = 3.0                 # 정체/결측 속도 하한
GASOLINE_J_PER_L = 34.2e6         # 가솔린 에너지밀도
GASOLINE_CO2_G_PER_L = 2310.0     # 가솔린 연소 CO2
J_PER_KWH = 3.6e6
EV_GRID_CO2_G_PER_KWH = 424.0     # 한국 전력배출계수(근사)
PAYLOAD_KG = 300.0                # 만차 기준 최대 적재(승객+화물) — load-factor로 스케일

# 기준 차량 계수 (대표값, 조정 가능)
VEHICLES = {
    "ice": dict(name="내연기관 승용차", curb_m=1500.0, Cr=0.011, rho=1.225, Cd=0.30, A=2.2,
                P_aux=3000.0, eta=0.30, regen=0.0),
    "ev":  dict(name="전기 승용차",   curb_m=1700.0, Cr=0.010, rho=1.225, Cd=0.28, A=2.2,
                P_aux=1000.0, eta=0.90, regen=0.60),
}


def link_energy_J(L_m, v_kmh, slope_pct, veh, mass):
    """링크 통과 에너지(J). L_m[m], v_kmh[km/h], slope_pct[signed %], mass[kg]."""
    v = np.maximum(v_kmh, V_FLOOR_KMH) / 3.6                    # m/s
    tan = slope_pct / 100.0
    sin = tan / np.sqrt(1.0 + tan * tan)                        # signed sinθ
    F_roll = mass * GRAVITY * veh["Cr"]
    F_aero = 0.5 * veh["rho"] * veh["Cd"] * veh["A"] * v * v
    F_grade = mass * GRAVITY * sin                             # signed
    F_trac = F_roll + F_aero + F_grade                        # 총 주행저항(내리막이면 음수 가능)

    E_pos = L_m * np.maximum(F_trac, 0.0) / veh["eta"]         # 양의 견인일 (구동효율로 나눔)
    E_regen = L_m * np.minimum(F_trac, 0.0) * veh["regen"]     # 음의 견인일(내리막) 회생 회수(≤0)
    E_aux = veh["P_aux"] * (L_m / v)                           # 보조/공회전 시간에너지
    E = E_pos + E_regen + E_aux
    return np.maximum(E, 0.1 * E_aux)                          # 비음수 보장(Dijkstra 안전)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tm", required=True, help="예측 시각 YYYYMMDDHHMM (13번과 동일)")
    ap.add_argument("--load-factor", type=float, default=0.0,
                    help="적재율 0(공차)~1(만차). 총질량 = 공차 + load_factor*300kg")
    args = ap.parse_args()

    speed_path = PROCESSED / f"seoul_all_link_speed_{args.tm}.csv"
    if not speed_path.exists():
        raise SystemExit(f"13번 속도 스냅샷이 없습니다: {speed_path}\n"
                         f"먼저 src/routing/13_predict_all_link_speed.py를 실행하세요.")

    df = pd.read_csv(speed_path, dtype={"LINK_ID": str}, encoding="utf-8-sig")
    # 13번 스냅샷에 이미 slope_pct(signed 경사)가 포함돼 있으면 그대로 사용, 없으면 차원 테이블에서 결합
    if "slope_pct" not in df.columns:
        dim = pd.read_csv(DIMENSION_PATH, dtype={"LINK_ID": str},
                          usecols=["LINK_ID", "slope_pct"], encoding="utf-8-sig")
        df = df.merge(dim, on="LINK_ID", how="left")
    df["slope_pct"] = pd.to_numeric(df["slope_pct"], errors="coerce").fillna(0.0)

    L = df["LENGTH"].to_numpy(dtype=float)
    v = df["speed_kmh"].to_numpy(dtype=float)
    s = df["slope_pct"].to_numpy(dtype=float)

    for key, veh in VEHICLES.items():
        mass = veh["curb_m"] + args.load_factor * PAYLOAD_KG
        e = link_energy_J(L, v, s, veh, mass)
        df[f"energy_{key}_J"] = np.round(e, 1)
        df[f"energy_{key}_per_km"] = np.round(e / (L / 1000.0), 1)   # J/km (비효율 진단용)
        if key == "ice":
            df["fuel_ml"] = np.round(e / GASOLINE_J_PER_L * 1000.0, 3)
            df["co2_ice_g"] = np.round(e / GASOLINE_J_PER_L * GASOLINE_CO2_G_PER_L, 2)
        else:
            df["ev_wh"] = np.round(e / J_PER_KWH * 1000.0, 2)
            df["co2_ev_g"] = np.round(e / J_PER_KWH * EV_GRID_CO2_G_PER_KWH, 2)

    out = PROCESSED / f"seoul_all_link_energy_{args.tm}.csv"
    keep = ["LINK_ID", "LENGTH", "speed_kmh", "slope_pct", "travel_time_sec",
            "energy_ice_J", "energy_ice_per_km", "fuel_ml", "co2_ice_g",
            "energy_ev_J", "energy_ev_per_km", "ev_wh", "co2_ev_g"]
    if "speed_source" in df:
        keep.append("speed_source")
    df[[c for c in keep if c in df]].to_csv(out, index=False, encoding="utf-8-sig")

    # 요약
    tot_km = (L / 1000.0).sum()
    print(f"[완료] {out.name}")
    print(f"  링크 {len(df):,} | 총연장 {tot_km:,.0f} km | 적재율 {args.load_factor:.0%} (총질량 ICE {VEHICLES['ice']['curb_m']+args.load_factor*PAYLOAD_KG:.0f}kg)")
    print(f"  ICE 총 연료 {df['fuel_ml'].sum()/1000:,.1f} L | CO2 {df['co2_ice_g'].sum()/1000:,.1f} kg")
    print(f"  EV  총 전력 {df['ev_wh'].sum()/1000:,.1f} kWh | CO2 {df['co2_ev_g'].sum()/1000:,.1f} kg")
    print(f"  링크당 평균 에너지: ICE {df['energy_ice_per_km'].mean()/1e6:.3f} MJ/km | EV {df['energy_ev_per_km'].mean()/1e6:.3f} MJ/km")
    print(f"  EV가 ICE 대비 CO2 {(1 - df['co2_ev_g'].sum()/df['co2_ice_g'].sum())*100:.0f}% 절감")
    # 경사 효과 확인
    up = df[df["slope_pct"] > 3]["energy_ice_per_km"].mean()
    flat = df[df["slope_pct"].abs() <= 1]["energy_ice_per_km"].mean()
    print(f"  급오르막(>3%) vs 평지(±1%) ICE 에너지: {up/1e6:.3f} vs {flat/1e6:.3f} MJ/km ({up/flat:.1f}배)")


if __name__ == "__main__":
    main()
