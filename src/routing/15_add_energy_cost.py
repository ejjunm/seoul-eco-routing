"""
[역할]
13번 스크립트(전체 링크 속도 및 통행시간 스냅샷)의 결과를 바탕으로,
DEM 경사도(slope_pct) 및 차량 구동 물리학을 반영하여 링크별 전기차(BEV) 배터리 소비 에너지를 계산합니다.  (속도 -> 에너지)

[주요 기능]
- VT-CPEM (Virginia Tech Comprehensive Power-based EV Energy Consumption Model) 물리학 공식 적용 (구름저항, 공기저항, 경사 위치에너지, 회생제동 효율 계산)
- 13번 스크립트의 계층 정보(tier) 및 속도 출처(speed_source)를 원본 그대로 보존
- 회생 제동 적용 옵션(--regen) 및 차량 적재율/공차중량 사용자 설정 지원
- 웹에서 동적으로 옵션(전기차,화물량) 설정 가능하다 (별도로 단독 실행 필요 X)

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
VEHICLE = dict(
    name="Nissan Leaf (BEV)",
    curb_m=1521.0,        # kg — 공차중량
    C_D=0.28,             # 공기저항 계수
    A_f=2.3316,           # m^2
    eta_D=0.92,           # 구동계
    eta_EM=0.91,          # 전기모터
    eta_B=0.90,           # 배터리
    P_A=700.0,            # W, 보조장치 소비 전력
)
PAYLOAD_KG = 300.0        # 만차 기준 최대 적재 

V_FLOOR_KMH = 3.0         # 정체/결측 속도 하한 (dt 발산 방지)
J_PER_KWH = 3.6e6
# 2023년 단년도 전력배출계수 0.4173 tCO2eq/MWh = 417.3 gCO2eq/kWh
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


def link_energy_J(
    L_m: np.ndarray,
    v_kmh: np.ndarray,
    slope_pct: np.ndarray,
    mass: float,
    regen_eta: float | None
) -> tuple[np.ndarray, np.ndarray]:
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

def calculate_energy_dataframe(
    df: pd.DataFrame,
    regen: bool = True,
    regen_decel: float = 0.5,
    mass: float | None = None,
    load_factor: float = 0.0
) -> pd.DataFrame:
    """
    [웹/모듈 전용 함수]
    속도 DataFrame 상에서 에너지 필드를 즉시 산출하여 반환 (파일 저장 없음).
    """
    df = df.copy()
    
    # 경사도 누락 시 자동 매핑
    if "slope_pct" not in df.columns:
        dim_df = pd.read_csv(
            DIMENSION_PATH,
            dtype={"LINK_ID": str},
            usecols=["LINK_ID", "slope_pct"],
            encoding="utf-8-sig"
        )
        df = df.merge(dim_df, on="LINK_ID", how="left")
        
    df["slope_pct"] = pd.to_numeric(df["slope_pct"], errors="coerce").fillna(0.0)

    L = df["LENGTH"].to_numpy(dtype=float)
    v = df["speed_kmh"].to_numpy(dtype=float)
    s = df["slope_pct"].to_numpy(dtype=float)
    
    curb_weight = mass if mass is not None else VEHICLE["curb_m"]
    total_mass = curb_weight + (load_factor * PAYLOAD_KG)

    regen_eta = None
    if regen:
        regen_eta = float(1.0 / np.exp(REGEN_ALPHA / abs(regen_decel)))

    E, dt = link_energy_J(L, v, s, total_mass, regen_eta)
    
    df["energy_ev_J"] = np.round(E, 1)
    df["energy_ev_per_km"] = np.round(E / (L / 1000.0), 1)
    df["ev_wh"] = np.round(E / J_PER_KWH * 1000.0, 3)
    df["co2_ev_g"] = np.round(E / J_PER_KWH * GRID_CO2_G_PER_KWH, 3)
    
    if "travel_time_sec" not in df.columns:
        df["travel_time_sec"] = np.round(dt, 1)

    return df