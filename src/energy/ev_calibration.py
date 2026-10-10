"""전기차(VT-CPEM) 파라미터를 공인 전비·주행거리로 보정한다.

휘발유·하이브리드 승용차(ice_fuel.py, hev_fuel.py)는 공인 도심·고속 연비가 각 시험주기 평균속도의
정속 주행에서 재현되도록 시간당 부가 소비(가감속 등)를 넣어 보정한다. 전기차도 같은 기준을 맞추기
위해, 링크 정속 근사의 VT-CPEM에 '보조전력 + 부가 전력'(시간에 비례하는 소비)을 두고 공기저항계수와
부가 전력 두 값을 공인값 두 개로 역산한다. 두 값 모두 1km당 에너지에 선형으로 들어가므로 2×2
연립방정식으로 풀린다.

    1km당 전력[Wh] = [m·g·Crr(u) + ½·ρ·Cd·A·u²] / (η·3.6) + (P_aux + P_extra) / v
                     (u: m/s, v: km/h, 평지)
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from .link_energy import VTCPEMParameters, rolling_resistance_coefficient


def _terms(params: VTCPEMParameters, kmh: float) -> tuple[float, float, float]:
    """(Cd 계수항, 부가전력 계수항, 상수항) — 1km당 Wh가 이 세 항의 선형결합이 되도록 분해한다."""
    u = kmh / 3.6
    rolling = params.mass_kg * params.gravity_m_s2 * float(rolling_resistance_coefficient(np.array([u]))[0])
    aero_per_cd = 0.5 * params.air_density_kg_m3 * params.frontal_area_m2 * u * u
    eff = params.total_efficiency
    return aero_per_cd / eff / 3.6, 1.0 / kmh, rolling / eff / 3.6 + params.auxiliary_power_w / kmh


def calibrate_two_point(params: VTCPEMParameters, points: list[tuple[float, float]]) -> tuple[VTCPEMParameters, float]:
    """정속 두 점 (속도 km/h, 1km당 Wh)을 재현하는 (공기저항계수, 부가 전력 W)를 구한다.

    부가 전력은 보조전력에 더해 돌려준다(시간에 비례하는 소비로 같은 자리에 들어가기 때문).
    """
    a, rhs = [], []
    for kmh, wh_per_km in points:
        cd_term, extra_term, const = _terms(params, kmh)
        a.append([cd_term, extra_term])
        rhs.append(wh_per_km - const)
    cd, extra_w = np.linalg.solve(np.array(a), np.array(rhs))
    if cd <= 0:
        raise ValueError(f"보정 실패: Cd={cd:.3g}")
    return replace(params, drag_coefficient=float(cd)), float(extra_w)


def combined_wh_per_km(params: VTCPEMParameters, extra_w: float, city_kmh: float, hwy_kmh: float,
                       city_share: float = 0.55) -> float:
    """도심·고속 정속 근사를 연비(km/kWh) 기준 가중 조화평균해 복합 1km당 Wh를 낸다."""
    def wh(kmh: float) -> float:
        cd_term, extra_term, const = _terms(params, kmh)
        return params.drag_coefficient * cd_term + extra_w * extra_term + const
    km_per_kwh = city_share * 1000.0 / wh(city_kmh) + (1 - city_share) * 1000.0 / wh(hwy_kmh)
    return 1000.0 / km_per_kwh
