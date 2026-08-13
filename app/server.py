"""서울 EV 에코 라우팅 로컬 대시보드 서버.

실행:
    uvicorn app.server:app --reload
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.energy.link_energy import calculate_link_energy
from src.routing.engine import EcoRoutingEngine, RouteNotFoundError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
PROCESSED = PROJECT_ROOT / "data" / "processed"
SHAPEFILE = PROJECT_ROOT / "data" / "interim" / "seoul_link.shp"

app = FastAPI(title="Seoul Eco Routing", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

PLACES = {
    "강남역": {"lat": 37.4979, "lon": 127.0276},
    "서울시청": {"lat": 37.5665, "lon": 126.9780},
    "여의도": {"lat": 37.5219, "lon": 126.9245},
    "잠실역": {"lat": 37.5133, "lon": 127.1000},
    "홍대입구": {"lat": 37.5572, "lon": 126.9245},
    "청량리": {"lat": 37.5800, "lon": 127.0470},
    "사당": {"lat": 37.4765, "lon": 126.9816},
}


class Point(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class RouteRequest(BaseModel):
    tm: str = Field(pattern=r"^\d{12}$")
    dataset: Literal["hybrid", "prediction"] = "hybrid"
    origin: Point
    destination: Point
    max_time_increase_pct: float = Field(default=15.0, ge=0, le=100)


def parquet_path(tm: str, dataset: str) -> Path:
    if dataset == "hybrid":
        return PROCESSED / "historical_hybrid_link_energy" / f"hybrid_link_energy_{tm}.parquet"
    return PROCESSED / "link_energy" / f"link_energy_{tm}.parquet"


@lru_cache(maxsize=4)
def engine_for(tm: str, dataset: str) -> EcoRoutingEngine:
    path = parquet_path(tm, dataset)
    if not path.exists():
        raise FileNotFoundError(path)
    engine = EcoRoutingEngine.from_parquet(path)
    engine.load_geometry(SHAPEFILE)
    return engine


def route_payload(routes: dict, engine: EcoRoutingEngine, source: str, target: str) -> dict:
    fastest = routes["fastest"]
    eco = routes["eco"]
    return {
        "routes": [route.summary() for route in routes.values()],
        "directions": {route_key: route.guidance() for route_key, route in routes.items()},
        "geojson": engine.routes_geojson(routes.values()),
        "snapped_nodes": {"origin": source, "destination": target},
        "eco_vs_fastest": {
            "energy_saved_wh": round(fastest.energy_wh - eco.energy_wh, 2),
            "energy_saved_pct": round((1 - eco.energy_wh / fastest.energy_wh) * 100, 2),
            "time_penalty_min": round(eco.time_min - fastest.time_min, 2),
            "time_penalty_pct": round((eco.time_min / fastest.time_min - 1) * 100, 2),
        },
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/meta")
def meta() -> dict:
    timestamps = sorted(
        path.stem.removeprefix("hybrid_link_energy_")
        for path in (PROCESSED / "historical_hybrid_link_energy").glob("hybrid_link_energy_*.parquet")
    )
    return {
        "timestamps": timestamps,
        "places": PLACES,
        "default_tm": "202607160800" if "202607160800" in timestamps else (timestamps[0] if timestamps else None),
        "datasets": {
            "hybrid": "과거 재현: 해당 시점 A 관측 + B/C 예측",
            "prediction": "이력 예측: A lookup + B/C 예측",
        },
    }


@app.post("/api/routes")
def routes(request: RouteRequest) -> dict:
    try:
        engine = engine_for(request.tm, request.dataset)
        source = engine.snap(request.origin.lon, request.origin.lat)
        target = engine.snap(request.destination.lon, request.destination.lat)
        computed = engine.compare_with_balanced(source, target, request.max_time_increase_pct)
        payload = route_payload(computed, engine, source, target)
        payload.update({"tm": request.tm, "dataset": request.dataset, "max_time_increase_pct": request.max_time_increase_pct})
        return payload
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"선택한 시점의 에너지 파일이 없습니다: {exc}") from exc
    except RouteNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/hotspots")
def hotspots(tm: str, dataset: Literal["hybrid", "prediction"] = "hybrid", limit: int = 12) -> dict:
    """동일 경사에서 35km/h로 주행했을 때보다 에너지 소모가 큰 후보를 반환한다.

    이는 정책 확정 점수가 아니라, 저속·정체로 생기는 차량당 추가 에너지를 찾는
    1차 스크리닝 지표다. 급경사 자체의 구조적 부담은 같은 경사를 기준으로 상쇄한다.
    """
    path = parquet_path(tm, dataset)
    if not path.exists():
        raise HTTPException(status_code=404, detail="선택한 시점의 에너지 파일이 없습니다.")
    frame = pd.read_parquet(
        path,
        columns=["LINK_ID", "ROAD_NAME", "LENGTH", "speed_kmh", "slope_pct_raw", "energy_ev_wh", "tier", "prediction_confidence"],
    )
    reference = frame[["LINK_ID", "LENGTH", "slope_pct_raw"]].rename(columns={"slope_pct_raw": "slope_pct"}).copy()
    reference["speed_kmh"] = 35.0
    reference_energy = calculate_link_energy(reference)[["LINK_ID", "energy_ev_wh"]].rename(
        columns={"energy_ev_wh": "reference_wh_at_35kmh"}
    )
    result = frame.merge(reference_energy, on="LINK_ID", how="inner")
    result["operational_excess_wh"] = (result["energy_ev_wh"] - result["reference_wh_at_35kmh"]).clip(lower=0)
    result["operational_excess_wh_per_km"] = result["operational_excess_wh"] / (result["LENGTH"] / 1000)
    flat = frame[["LINK_ID", "LENGTH", "speed_kmh"]].copy()
    flat["slope_pct"] = 0.0
    flat_energy = calculate_link_energy(flat)[["LINK_ID", "energy_ev_wh"]].rename(columns={"energy_ev_wh": "flat_wh_at_current_speed"})
    result = result.merge(flat_energy, on="LINK_ID", how="inner")
    result["structural_grade_wh"] = (result["energy_ev_wh"] - result["flat_wh_at_current_speed"]).clip(lower=0)

    def diagnosis(row: pd.Series) -> str:
        if row["prediction_confidence"] == "low":
            return "데이터 검증 우선"
        if abs(row["slope_pct_raw"]) >= 3 and row["structural_grade_wh"] >= row["operational_excess_wh"]:
            return "경사 부담: 우회 안내 후보"
        if row["speed_kmh"] < 20 and row["operational_excess_wh"] > 0:
            return "저속 운영: 신호·병목 후보"
        return "복합 요인: 현장 진단 후보"

    result["diagnosis"] = result.apply(diagnosis, axis=1)
    result = result.sort_values("operational_excess_wh", ascending=False).head(max(1, min(limit, 50)))
    columns = [
        "LINK_ID", "ROAD_NAME", "speed_kmh", "slope_pct_raw", "energy_ev_wh", "operational_excess_wh",
        "operational_excess_wh_per_km", "structural_grade_wh", "tier", "prediction_confidence", "diagnosis",
    ]
    records = result[columns].round({"speed_kmh": 1, "slope_pct_raw": 2, "energy_ev_wh": 1, "operational_excess_wh": 1, "operational_excess_wh_per_km": 1, "structural_grade_wh": 1})
    return {
        "tm": tm,
        "reference": "동일 링크·동일 경사에서 35km/h로 주행하는 물리모델 기준",
        "warning": "교통량을 곱한 사회적 영향도나 인과적 정책 효과가 아닌 차량당 1차 스크리닝 지표입니다. 경사 부담과 운영 부담을 분리해 참고하세요.",
        "items": records.to_dict(orient="records"),
    }
