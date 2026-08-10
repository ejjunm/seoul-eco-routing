"""15. 링크별 에너지 비용 계산 (Stage 2: 속도 -> 에너지)

13번(전 링크 속도 스냅샷)의 결과에 DEM 경사를 결합해, 링크를 통과할 때의 배터리
소비 에너지를 계산한다. 전기차(BEV) 기준이다.

에너지 모델: VT-CPEM (Virginia Tech Comprehensive Power-based Electric vehicle Model)
    Fiori, C., Ahn, K., & Rakha, H. A. (2016). "Power-based electric vehicle energy
    consumption model: Model development and validation." Applied Energy, 168, 257-268.

VT-CPEM 원형은 연속 시간 t에 대한 순간 모델이지만, 우리는 (링크 l, 시간대 t) 단위로
근사 적용한다. 링크 단위에서는 초 단위 감속도 a(t)를 알 수 없으므로 a=0(정속 통과)으로
둔다 — 이 가정의 결과는 아래 '회생제동' 항목 참고.

    u      = v_hat / 3.6                                      [m/s]  링크 통과 속도
    dt     = L / u                                            [s]    링크 통과 시간
    C_rr(u)= 1.75e-3 * (0.0328*u + 4.575)                            속도 의존 구름저항계수
    P_W    = [ m*g*C_rr(u)*cos(th) + m*g*sin(th)
               + 0.5*rho*C_D*A_f*u^2 ] * u                    [W]    바퀴 요구 동력
    E      = ( max(P_W,0)/(eta_D*eta_EM*eta_B) + P_A ) * dt   [J]    배터리 소비 에너지

회생제동(--regen):
    VT-CPEM 원식은 P_W < 0 구간에서 P_W * eta_D*eta_EM*eta_B * eta_rb 로 에너지를
    회수하며, eta_rb = 1/exp(alpha/|a|), alpha = 0.0411 (Fiori et al. 2016 캘리브레이션).
    이 식은 감속도 |a|를 요구하는데 링크 단위에서는 알 수 없다. --regen을 주면 도심
    대표 감속도(--regen-decel, 기본 0.5 m/s^2)를 대입해 eta_rb를 상수로 만들어 적용한다.

    회생을 끄면(기본값) 내리막에서 회수가 0이라 내리막 링크가 평지와 같아진다. 경사가
    에코라우팅의 주된 이득원이므로, 두 설정을 모두 돌려 경로 결과가 달라지는지 확인할 것.

    주의: 다익스트라는 간선 비용이 음수면 쓸 수 없다. 회생 적용 시 급내리막에서 E가
    음수가 될 수 있어 0으로 클리핑한다(그 링크에서 실제로는 순회수가 일어나지만,
    경로탐색을 위해 '이득 없음'으로 보수적으로 처리).

입력:  data/processed/seoul_all_link_speed_{tm}.csv  (routing/13 산출)
       data/processed/seoul_link_dimension.csv       (slope_pct — 13번 산출에 없을 때만)
출력:  data/processed/seoul_all_link_energy_{tm}.csv

사용:  python src/routing/15_add_energy_cost.py --tm 202607160800
       python src/routing/15_add_energy_cost.py --tm 202607160800 --regen
       python src/routing/15_add_energy_cost.py --tm 202607160800 --load-factor 1.0
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED = PROJECT_ROOT / "data" / "processed"
DIMENSION_PATH = PROCESSED / "seoul_link_dimension.csv"

# --- VT-CPEM 상수 (Fiori et al. 2016 / 팀 발표자료 참고문헌 [5]) ---
GRAVITY = 9.8066          # m/s^2
AIR_DENSITY = 1.2256      # kg/m^3 (해수면, 25도C)
CRR_A = 1.75e-3           # C_rr(u) = CRR_A * (CRR_B*u + CRR_C)
CRR_B = 0.0328
CRR_C = 4.575
REGEN_ALPHA = 0.0411      # eta_rb = 1/exp(alpha/|a|)

# --- 기준 차량: 닛산 리프 (BEV) ---
# 아래 값은 Fiori et al.(2016) 원문(저자 프리프린트) 및 이를 재수록한 문헌
# 2~7건을 교차확인한 것이다. 확인 내역은 이 파일 하단 주석 참고.
VEHICLE = dict(
    name="Nissan Leaf (BEV)",
    curb_m=1521.0,        # kg — 공차중량. 논문 검증 시에는 1595kg(공차+운전자 1인,
                          #      JRC 데이터)과 1640kg(운전자+계측장비, INL 데이터)을 썼다.
                          #      실주행 모사에는 1595가 더 현실적이다(--mass로 변경 가능).
    C_D=0.28,
    A_f=2.3316,           # m^2
    eta_D=0.92,           # 구동계
    eta_EM=0.91,          # 전기모터
    eta_B=0.90,           # 배터리
    P_A=700.0,            # W, 보조장치 (참고문헌 [6] Iora & Tribioli 2019)
)
PAYLOAD_KG = 300.0        # 만차 기준 최대 적재 — load-factor로 스케일

V_FLOOR_KMH = 3.0         # 정체/결측 속도 하한 (dt 발산 방지)
J_PER_KWH = 3.6e6
# 2023년 단년도 전력배출계수 0.4173 tCO2eq/MWh = 417.3 gCO2eq/kWh
# 기후에너지환경부·국가온실가스통계관리위원회 2025.12.17 공표
GRID_CO2_G_PER_KWH = 417.3


def rolling_coefficient(u_ms: np.ndarray) -> np.ndarray:
    """속도 의존 구름저항계수 C_rr(u).

    u의 단위는 반드시 m/s다. Fiori et al.(2016) 원문에 "v(t) is the vehicle speed
    in [m/s]"로 명시돼 있고, 같은 식의 공기저항항 0.5*rho*A_f*C_D*v^2 이 N이 되려면
    물리적으로도 m/s여야 한다. km/h를 넣으면 20km/h에서 +10%, 50km/h에서 +23.5%
    과대평가된다(계수 원출처인 Rakha et al. 2001 계열은 km/h 규약을 쓰지만, 그쪽은
    Cr=1.25를 쓰므로 이 계수쌍과 섞으면 안 된다).
    """
    return CRR_A * (CRR_B * u_ms + CRR_C)


def link_energy_J(L_m, v_kmh, slope_pct, mass, regen_eta: float | None):
    """링크 통과 배터리 소비 에너지(J).

    L_m[m], v_kmh[km/h], slope_pct[signed %], mass[kg].
    regen_eta가 None이면 회생 없음(max(P_W,0)), 값이 있으면 그 효율로 회수.
    """
    u = np.maximum(v_kmh, V_FLOOR_KMH) / 3.6                   # m/s
    dt = L_m / u                                               # s
    tan = slope_pct / 100.0
    sin = tan / np.sqrt(1.0 + tan * tan)                       # signed sin(theta)
    cos = 1.0 / np.sqrt(1.0 + tan * tan)

    c_rr = rolling_coefficient(u)
    R_roll = mass * GRAVITY * c_rr * cos
    R_grade = mass * GRAVITY * sin                             # signed
    R_aero = 0.5 * AIR_DENSITY * VEHICLE["C_D"] * VEHICLE["A_f"] * u * u
    P_W = (R_roll + R_grade + R_aero) * u                      # W, 바퀴 요구 동력

    eta_chain = VEHICLE["eta_D"] * VEHICLE["eta_EM"] * VEHICLE["eta_B"]
    P_traction = np.where(P_W >= 0, P_W / eta_chain,
                          P_W * eta_chain * (regen_eta if regen_eta else 0.0))
    E = (P_traction + VEHICLE["P_A"]) * dt
    return np.maximum(E, 0.0), dt                              # 다익스트라용 비음수 보장


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tm", required=True, help="예측 시각 YYYYMMDDHHMM (13번과 동일)")
    ap.add_argument("--load-factor", type=float, default=0.0,
                    help="적재율 0(공차)~1(만차). 총질량 = 공차 + load_factor*300kg")
    ap.add_argument("--mass", type=float, default=None,
                    help="공차중량을 직접 지정[kg]. 미지정 시 1521(공차). "
                         "논문 검증값 1595(공차+운전자) / 1640(INL 시험)도 참고")
    ap.add_argument("--regen", action="store_true",
                    help="회생제동 적용(대표 감속도로 eta_rb를 상수화). 기본은 미적용")
    ap.add_argument("--regen-decel", type=float, default=0.5,
                    help="회생 계산용 대표 감속도 |a| [m/s^2]. 기본 0.5(도심)")
    args = ap.parse_args()

    speed_path = PROCESSED / f"seoul_all_link_speed_{args.tm}.csv"
    if not speed_path.exists():
        raise SystemExit(f"13번 속도 스냅샷이 없습니다: {speed_path}\n"
                         f"먼저 src/routing/13_predict_all_link_speed.py를 실행하세요.")

    df = pd.read_csv(speed_path, dtype={"LINK_ID": str}, encoding="utf-8-sig")
    if "slope_pct" not in df.columns:
        dim = pd.read_csv(DIMENSION_PATH, dtype={"LINK_ID": str},
                          usecols=["LINK_ID", "slope_pct"], encoding="utf-8-sig")
        df = df.merge(dim, on="LINK_ID", how="left")
    df["slope_pct"] = pd.to_numeric(df["slope_pct"], errors="coerce").fillna(0.0)

    L = df["LENGTH"].to_numpy(dtype=float)
    v = df["speed_kmh"].to_numpy(dtype=float)
    s = df["slope_pct"].to_numpy(dtype=float)
    curb = args.mass if args.mass else VEHICLE["curb_m"]
    mass = curb + args.load_factor * PAYLOAD_KG

    regen_eta = None
    if args.regen:
        regen_eta = float(1.0 / np.exp(REGEN_ALPHA / abs(args.regen_decel)))

    E, dt = link_energy_J(L, v, s, mass, regen_eta)
    df["energy_ev_J"] = np.round(E, 1)
    df["energy_ev_per_km"] = np.round(E / (L / 1000.0), 1)
    df["ev_wh"] = np.round(E / J_PER_KWH * 1000.0, 3)
    df["co2_ev_g"] = np.round(E / J_PER_KWH * GRID_CO2_G_PER_KWH, 3)
    if "travel_time_sec" not in df.columns:
        df["travel_time_sec"] = np.round(dt, 1)

    keep = ["LINK_ID", "F_NODE", "T_NODE", "LENGTH", "speed_kmh", "slope_pct",
            "travel_time_sec", "energy_ev_J", "energy_ev_per_km", "ev_wh", "co2_ev_g",
            "tier", "speed_source"]
    out = PROCESSED / f"seoul_all_link_energy_{args.tm}.csv"
    df[[c for c in keep if c in df]].to_csv(out, index=False, encoding="utf-8-sig")

    # 요약
    tot_km = (L / 1000.0).sum()
    wh_per_km = df["ev_wh"].sum() / tot_km
    print(f"[완료] {out.name}   모델: VT-CPEM (Fiori et al. 2016)")
    print(f"  기준차: {VEHICLE['name']} | 총질량 {mass:.0f}kg (적재율 {args.load_factor:.0%})")
    print(f"  회생제동: {'적용 (|a|=%.2f m/s^2, eta_rb=%.3f)' % (args.regen_decel, regen_eta) if regen_eta else '미적용'}")
    print(f"  링크 {len(df):,} | 총연장 {tot_km:,.0f} km")
    print(f"  총 전력 {df['ev_wh'].sum()/1000:,.1f} kWh | CO2 {df['co2_ev_g'].sum()/1000:,.1f} kg")
    print(f"  평균 전비 {wh_per_km:.1f} Wh/km   (실측 도심 참고: 150~200 Wh/km)")
    up = df[df["slope_pct"] > 3]["energy_ev_per_km"].mean()
    flat = df[df["slope_pct"].abs() <= 1]["energy_ev_per_km"].mean()
    down = df[df["slope_pct"] < -3]["energy_ev_per_km"].mean()
    print(f"  급오르막(>3%) {up/1e6:.3f} / 평지(±1%) {flat/1e6:.3f} / 급내리막(<-3%) {down/1e6:.3f} MJ/km"
          f"   -> 오르막이 평지의 {up/flat:.1f}배, 내리막은 {down/flat:.2f}배")


if __name__ == "__main__":
    main()
