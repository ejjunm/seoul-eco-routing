"""미관측 링크 속도의 분위수 XGBoost + split conformal 예측구간을 만든다.

핵심 원칙은 같은 링크의 시계열이 train/calibration/test에 섞이지 않게 링크 단위로
분리하는 것이다. 1,509만 행 전체를 한꺼번에 메모리에 올리지 않고, 분리된 링크 중
일부 링크의 모든 시간 관측을 청크로 읽어 학습한다. 이웃 속도는 train 링크만 원천으로
사용하므로 검증 링크의 정답이 새는 일도 없다.

출력
  src/models/artifacts/speed_quantile_conformal.pkl
  data/processed/model_uncertainty/{metrics.json,test_predictions.csv,split_manifest.csv}

사용 예
  python src/models/05_build_speed_uncertainty.py
  python src/models/05_build_speed_uncertainty.py --train-links 2500 --cal-links 600 --test-links 600
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED = PROJECT_ROOT / "data" / "processed"
ARTIFACTS = PROJECT_ROOT / "src" / "models" / "artifacts"
OUTPUT = PROCESSED / "model_uncertainty"
BUILDER_PATH = PROJECT_ROOT / "src" / "models" / "02_build_model_bc.py"
PREDICTOR_PATH = PROJECT_ROOT / "src" / "models" / "03_predict_all_link_speed.py"
SEED = 42


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"모듈을 불러올 수 없습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-links", type=int, default=1200, help="학습에 표본으로 쓸 링크 수")
    parser.add_argument("--cal-links", type=int, default=350, help="conformal 보정 링크 수")
    parser.add_argument("--test-links", type=int, default=350, help="최종 평가 링크 수")
    parser.add_argument("--n-estimators", type=int, default=160)
    parser.add_argument("--alpha", type=float, default=0.10, help="목표 오차율(0.10이면 90%% 구간)")
    return parser.parse_args()


def split_links(observed_links: np.ndarray, args: argparse.Namespace) -> tuple[set[str], set[str], set[str], pd.DataFrame]:
    rng = np.random.default_rng(SEED)
    links = np.asarray(observed_links, dtype=str).copy()
    rng.shuffle(links)
    n = len(links)
    train_pool = links[: int(n * 0.60)]
    cal_pool = links[int(n * 0.60): int(n * 0.80)]
    test_pool = links[int(n * 0.80):]

    def choose(pool: np.ndarray, count: int) -> np.ndarray:
        return pool[: min(count, len(pool))]

    train_sample, cal_sample, test_sample = (
        choose(train_pool, args.train_links), choose(cal_pool, args.cal_links), choose(test_pool, args.test_links)
    )
    manifest = pd.concat([
        pd.DataFrame({"LINK_ID": train_sample, "split": "train"}),
        pd.DataFrame({"LINK_ID": cal_sample, "split": "calibration"}),
        pd.DataFrame({"LINK_ID": test_sample, "split": "test"}),
    ], ignore_index=True)
    # 첫 반환값은 이웃 lookup 원천이 되는 전체 train pool, 나머지는 실제 표본 링크다.
    return set(train_pool), set(cal_pool), set(test_pool), manifest


def load_fact_for_links(builder, selected_links: set[str]) -> pd.DataFrame:
    usecols = ["LINK_ID", "기준일", "시간코드", builder.TARGET, "precip_mm",
               "traffic_volume_hourly", "traffic_volume_ratio", "grid_pop", "dong_pop", "sample_count_5min"]
    parts: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        builder.FACT_PATH, usecols=usecols, dtype={"LINK_ID": str, "기준일": str},
        encoding="utf-8-sig", chunksize=500_000,
    ):
        part = chunk[chunk["LINK_ID"].isin(selected_links)]
        if not part.empty:
            parts.append(part.copy())
    if not parts:
        raise SystemExit("선택한 링크의 속도 관측을 찾지 못했습니다.")
    fact = pd.concat(parts, ignore_index=True)
    for col in [builder.TARGET, "precip_mm", "traffic_volume_hourly", "traffic_volume_ratio",
                "grid_pop", "dong_pop", "sample_count_5min"]:
        fact[col] = pd.to_numeric(fact[col], errors="coerce")
    fact["시간코드"] = pd.to_numeric(fact["시간코드"], errors="coerce").astype(int)
    return fact.dropna(subset=[builder.TARGET])


def assemble_sample(builder, dimension: pd.DataFrame, fact: pd.DataFrame) -> pd.DataFrame:
    df = fact.merge(dimension.drop(columns=["ROAD_NAME"], errors="ignore"), on="LINK_ID", how="left")
    date = pd.to_datetime(df["기준일"], format="%Y%m%d", errors="coerce")
    df["dow"] = pd.Categorical(date.dt.weekday, categories=np.arange(7, dtype="int32"))
    df["is_weekend"] = (date.dt.weekday >= 5).astype("int8")
    hour = df["시간코드"].astype("float32")
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24).astype("float32")
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24).astype("float32")
    actual_hour = (df["시간코드"].astype(int) - 1).clip(0, 23).to_numpy()
    hour_cols = [f"avg_speed_h{h}" for h in range(24)]
    hourly = dimension.set_index("LINK_ID")[hour_cols].reindex(df["LINK_ID"]).to_numpy(dtype="float32")
    df["avg_speed_hourly"] = hourly[np.arange(len(df)), actual_hour]
    for col in builder.CATEGORICAL_COLS:
        df[col] = df[col].astype("category")
    return df


def quantile_levels(alpha: float) -> np.ndarray:
    return np.array([alpha / 2, 0.50, 1 - alpha / 2], dtype=np.float32)


def make_model(n_estimators: int, alpha: float) -> xgb.XGBRegressor:
    return xgb.XGBRegressor(
        objective="reg:quantileerror", quantile_alpha=quantile_levels(alpha),
        n_estimators=n_estimators, learning_rate=0.05, max_depth=7,
        min_child_weight=5, subsample=0.85, colsample_bytree=0.85,
        tree_method="hist", enable_categorical=True, random_state=SEED,
        n_jobs=-1, verbosity=0,
    )


def ordered_predictions(model: xgb.XGBRegressor, x: pd.DataFrame) -> np.ndarray:
    pred = np.asarray(model.predict(x), dtype=float)
    if pred.ndim == 1:
        pred = pred.reshape(-1, 3)
    return np.sort(pred, axis=1)


def tier_predictions(frame: pd.DataFrame, builder, model_b, model_c) -> tuple[np.ndarray, np.ndarray]:
    has_neighbor = frame[builder.NEIGHBOR_COL].notna().to_numpy()
    pred = np.empty((len(frame), 3), dtype=float)
    if has_neighbor.any():
        pred[has_neighbor] = ordered_predictions(model_b, frame.loc[has_neighbor, builder.FEATURE_COLS])
    if (~has_neighbor).any():
        pred[~has_neighbor] = ordered_predictions(model_c, frame.loc[~has_neighbor, builder.STATIC_COLS])
    return pred, has_neighbor


def conformal_quantile(scores: np.ndarray, alpha: float) -> float:
    scores = np.asarray(scores, dtype=float)
    scores = scores[np.isfinite(scores)]
    if len(scores) == 0:
        raise ValueError("conformal 점수가 비었습니다.")
    level = min(1.0, np.ceil((len(scores) + 1) * (1 - alpha)) / len(scores))
    return float(np.quantile(scores, level, method="higher"))


def qhat_by_tier(y: np.ndarray, pred: np.ndarray, has_neighbor: np.ndarray, alpha: float) -> dict[str, float]:
    scores = np.maximum.reduce([pred[:, 0] - y, y - pred[:, 2], np.zeros(len(y))])
    result = {"all": conformal_quantile(scores, alpha)}
    for name, mask in (("B_neighbor_model", has_neighbor), ("C_static_model", ~has_neighbor)):
        result[name] = conformal_quantile(scores[mask], alpha) if mask.sum() >= 30 else result["all"]
    return result


def apply_conformal(pred: np.ndarray, has_neighbor: np.ndarray, qhat: dict[str, float]) -> np.ndarray:
    out = pred.copy()
    adjustment = np.where(has_neighbor, qhat["B_neighbor_model"], qhat["C_static_model"])
    out[:, 0] -= adjustment
    out[:, 2] += adjustment
    out[:, 0] = np.maximum(out[:, 0], 3.0)
    out[:, 1] = np.maximum(out[:, 1], 3.0)
    out[:, 2] = np.maximum(out[:, 2], out[:, 1])
    return out


def metric_rows(y: np.ndarray, raw: np.ndarray, calibrated: np.ndarray,
                has_neighbor: np.ndarray) -> list[dict]:
    rows = []
    for tier, mask in (("all", np.ones(len(y), dtype=bool)),
                       ("B_neighbor_model", has_neighbor), ("C_static_model", ~has_neighbor)):
        if not mask.any():
            continue
        rows.append({
            "tier": tier,
            "n": int(mask.sum()),
            "median_mae_kmh": float(mean_absolute_error(y[mask], raw[mask, 1])),
            "raw_coverage": float(((y[mask] >= raw[mask, 0]) & (y[mask] <= raw[mask, 2])).mean()),
            "raw_mean_width_kmh": float((raw[mask, 2] - raw[mask, 0]).mean()),
            "conformal_coverage": float(((y[mask] >= calibrated[mask, 0]) & (y[mask] <= calibrated[mask, 2])).mean()),
            "conformal_mean_width_kmh": float((calibrated[mask, 2] - calibrated[mask, 0]).mean()),
        })
    return rows


def main() -> None:
    args = parse_args()
    if not 0 < args.alpha < 1:
        raise SystemExit("--alpha는 0과 1 사이여야 합니다.")
    builder = load_module("model_bc_builder", BUILDER_PATH)
    predictor = load_module("all_link_predictor", PREDICTOR_PATH)
    model_a = pd.read_parquet(PROCESSED / "model_a_lookup.parquet")
    observed_links = np.sort(model_a["LINK_ID"].astype(str).unique())

    train_pool, _, _, manifest = split_links(observed_links, args)
    sample_sets = {
        split: set(manifest.loc[manifest["split"] == split, "LINK_ID"])
        for split in ["train", "calibration", "test"]
    }
    selected = set().union(*sample_sets.values())
    print(f"[1/6] 속도 fact 청크 읽기: 선택 링크 {len(selected):,}/{len(observed_links):,}")
    fact = load_fact_for_links(builder, selected)
    print(f"      표본 행 {len(fact):,}")

    print("[2/6] 정적·시간 피처와 누수 없는 이웃속도 구성...")
    dimension = predictor.load_dimension(builder)
    df = assemble_sample(builder, dimension, fact)
    lookup = model_a[model_a["LINK_ID"].isin(train_pool)][
        ["LINK_ID", "시간코드", "is_weekend", "pred_speed"]
    ]
    graph_1, graph_2 = builder.build_link_graph(dimension)
    neighbor = builder.build_neighbor_bucket_feature(
        lookup, graph_1, graph_2, dimension["LINK_ID"].to_numpy(), train_pool
    )
    keys = ["LINK_ID", "시간코드", "is_weekend"]
    df = df.merge(neighbor, on=keys, how="left", validate="many_to_one")
    split_map = manifest.set_index("LINK_ID")["split"]
    df["split"] = df["LINK_ID"].map(split_map)
    train = df[df["split"] == "train"].copy()
    cal = df[df["split"] == "calibration"].copy()
    test = df[df["split"] == "test"].copy()
    for frame in (train, cal, test):
        for col in builder.CATEGORICAL_COLS:
            frame[col] = frame[col].cat.set_categories(df[col].cat.categories)

    print("[3/6] 분위수 XGBoost 학습(B: 이웃 있음, C: 정적 피처)...")
    train_b = train[train[builder.NEIGHBOR_COL].notna()]
    if len(train_b) < 1000:
        raise SystemExit(f"B 학습 행이 너무 적습니다: {len(train_b):,}")
    weights_b = train_b["sample_count_5min"].fillna(1).clip(lower=1).to_numpy(dtype="float32")
    weights_c = train["sample_count_5min"].fillna(1).clip(lower=1).to_numpy(dtype="float32")
    model_b = make_model(args.n_estimators, args.alpha)
    model_c = make_model(args.n_estimators, args.alpha)
    model_b.fit(train_b[builder.FEATURE_COLS], train_b[builder.TARGET], sample_weight=weights_b)
    model_c.fit(train[builder.STATIC_COLS], train[builder.TARGET], sample_weight=weights_c)

    print("[4/6] calibration 링크로 conformal 보정...")
    cal_raw, cal_has_b = tier_predictions(cal, builder, model_b, model_c)
    cal_y = cal[builder.TARGET].to_numpy(dtype=float)
    qhat = qhat_by_tier(cal_y, cal_raw, cal_has_b, args.alpha)

    print("[5/6] 완전히 분리된 test 링크 평가...")
    test_raw, test_has_b = tier_predictions(test, builder, model_b, model_c)
    test_cal = apply_conformal(test_raw, test_has_b, qhat)
    test_y = test[builder.TARGET].to_numpy(dtype=float)
    metrics = metric_rows(test_y, test_raw, test_cal, test_has_b)
    print(pd.DataFrame(metrics).round(3).to_string(index=False))

    print("[6/6] 모델과 재현 산출물 저장...")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    artifact = {
        "model_b": model_b,
        "model_c": model_c,
        "feature_cols_b": builder.FEATURE_COLS,
        "feature_cols_c": builder.STATIC_COLS,
        "categorical_cols": builder.CATEGORICAL_COLS,
        "quantiles": quantile_levels(args.alpha).tolist(),
        "alpha": args.alpha,
        "qhat_by_tier": qhat,
        "random_state": SEED,
    }
    with open(ARTIFACTS / "speed_quantile_conformal.pkl", "wb") as file:
        pickle.dump(artifact, file)
    manifest.to_csv(OUTPUT / "split_manifest.csv", index=False, encoding="utf-8-sig")
    pred_out = test[["LINK_ID", "기준일", "시간코드", builder.TARGET]].copy()
    pred_out["tier"] = np.where(test_has_b, "B_neighbor_model", "C_static_model")
    pred_out[["q05_raw", "q50", "q95_raw"]] = test_raw
    pred_out[["speed_lower", "speed_median", "speed_upper"]] = test_cal
    pred_out.to_csv(OUTPUT / "test_predictions.csv", index=False, encoding="utf-8-sig")
    metadata = {
        "target_coverage": 1 - args.alpha,
        "quantiles": quantile_levels(args.alpha).tolist(),
        "qhat_by_tier_kmh": qhat,
        "link_counts": manifest["split"].value_counts().to_dict(),
        "row_counts": {"train": len(train), "calibration": len(cal), "test": len(test)},
        "metrics": metrics,
        "note": "Coverage is an empirical held-out-link result; repeated hours within a link are correlated.",
    }
    (OUTPUT / "metrics.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {ARTIFACTS / 'speed_quantile_conformal.pkl'}")
    print(f"평가: {OUTPUT / 'metrics.json'}")


if __name__ == "__main__":
    main()
