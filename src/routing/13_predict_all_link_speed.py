"""라우팅용 전 링크 속도·통행시간 스냅샷 생성 (Stage 1 산출물).

입력 스키마가 차원(seoul_link_dimension.csv) + 팩트(seoul_link_speed_fact.csv)로
바뀌면서 재작성했다. 정적 속성은 차원 테이블에서 링크당 1행으로 읽고, 관측 속도와
강수는 팩트 테이블에서 (LINK_ID, 기준일, 시간코드) 단위로 읽어 LINK_ID로 결합한다.

핵심 변경 — 미관측 링크를 이웃 관측 유무로 나눠 다른 모델로 예측한다.
  `notebooks/13_tier_split_evaluation.ipynb`에서, 인접 실측 이웃속도 피처가 계층에
  따라 효과의 부호가 반대라는 걸 확인했다(공간 블록분할 3-fold):

    계층                        이웃속도 없음  이웃속도 포함
    B 미관측·1홉에 관측 이웃 있음      0.713    ->   0.780   (+0.067)
    C 미관측·1홉에 관측 이웃 없음      0.492    ->   0.314   (-0.178)

  훈련 행 대부분에 이웃속도가 있어 모델이 그 피처에 의존하도록 학습되는데, C에서는
  결측이라 오히려 정적 피처를 제대로 못 쓴다. 그래서 모델을 두 개 학습해
  B는 이웃속도 포함 모델, C는 정적 전용 모델로 예측한다(결측 폴백은 C를 0.419까지만
  회복해서 채택하지 않았다).

속도 산출 우선순위:
    해당 시각 팩트 테이블 관측값
      -> B 계층: 이웃속도 포함 모델
      -> C 계층: 정적 전용 모델
      -> 학습에 없던 범주이거나 지원 표본이 부족하면 계층적 fallback
      -> speed_kmh로 링크 통행시간 계산

입력:  data/processed/seoul_link_dimension.csv        (pipeline/04)
       data/processed/seoul_link_speed_fact.csv       (pipeline/05)
       data/processed/seoul_all_link_weather_{tm}.csv (routing/12 — precip_mm만 사용)
출력:  data/processed/seoul_all_link_speed_{tm}.csv

사용:  python src/routing/13_predict_all_link_speed.py --tm 202607160800 --train-end 20260715
       python src/routing/13_predict_all_link_speed.py --tm 202607160800 --train-end 20260715 --sample-frac 0.2
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DIMENSION_PATH = PROCESSED_DIR / "seoul_link_dimension.csv"
FACT_PATH = PROCESSED_DIR / "seoul_link_speed_fact.csv"

TARGET = "평균속도"
NB_FEATURE = "nb_speed"

# --- 차원 테이블에서 오는 정적 피처 (전 링크에서 항상 구할 수 있음) ---
DIM_BASE_NUMERIC = [
    "LANES", "MAX_SPD", "LENGTH",
    "elev_start_m", "elev_mid_m", "elev_end_m", "elev_mean_m", "elev_min_m", "elev_max_m",
    "elev_delta_m", "slope_pct", "abs_slope_pct",
]
DIM_TOPOLOGY = [
    "f_node_node_in_degree", "f_node_incoming_max_spd_mean", "f_node_incoming_lanes_mean",
    "f_node_node_out_degree", "f_node_outgoing_max_spd_mean", "f_node_outgoing_lanes_mean",
    "f_node_node_total_degree",
    "t_node_node_in_degree", "t_node_incoming_max_spd_mean", "t_node_incoming_lanes_mean",
    "t_node_node_out_degree", "t_node_outgoing_max_spd_mean", "t_node_outgoing_lanes_mean",
    "t_node_node_total_degree",
    "upstream_max_spd_mean", "downstream_max_spd_mean", "upstream_lanes_mean", "downstream_lanes_mean",
    "node_complexity", "downstream_speed_delta", "slope_pct_clipped", "slope_outlier_flag",
    "is_uphill", "is_downhill", "steep_uphill", "slope_length_m", "max_spd_x_lanes",
    "length_x_node_complexity",
]
# 외부 컨텍스트는 원본을 안 받았으면 차원 테이블에 없을 수 있어 실행 시점에 걸러 쓴다
DIM_EXTERNAL_CANDIDATES = [
    "traffic_volume_aadt", "bus_lane_ratio", "school_zone_count",
    "accident_hotspot_count", "speed_bump_count",
]
DIM_CATEGORICAL = [
    "ROAD_RANK", "ROAD_TYPE", "ROAD_USE", "MULTI_LINK", "CONNECT",
    "REST_VEH", "REST_W", "REST_H", "C-ITS",
]

# --- 시각마다 달라지는 피처 ---
TIME_NUMERIC = [
    "시간코드", "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "is_morning_peak", "is_evening_peak",
]
WEATHER_NUMERIC = [
    "precip_mm", "is_rain", "log_precip", "rain_morning_peak", "rain_evening_peak", "rain_x_max_spd",
]
TIME_CATEGORICAL = ["weekday", "is_weekend", "peak_period", "rain_class"]

RAIN_BINS = [-np.inf, 0, 1, 5, 10, np.inf]
RAIN_LABELS = ["none", "light", "moderate", "heavy", "very_heavy"]
MORNING_PEAK = (7, 8, 9)
EVENING_PEAK = (17, 18, 19)
SPEED_FLOOR_KMH = 3.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tm", required=True, help="예측 시각 YYYYMMDDHHMM")
    parser.add_argument("--train-end", required=True, help="학습 마지막 날짜 YYYYMMDD (이 날짜까지만 학습)")
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--min-supported-links", type=int, default=20,
                        help="ROAD_RANK x MAX_SPD 조합의 학습 링크 수가 이보다 적으면 fallback")
    parser.add_argument("--sample-frac", type=float, default=1.0,
                        help="학습 행 샘플링 비율(빠른 확인용). 기본 1.0")
    return parser.parse_args()


def add_time_weather_features(df: pd.DataFrame, hours: pd.Series, weekdays: pd.Series) -> pd.DataFrame:
    """시각·요일·강수에서 파생 피처를 만든다(학습/스냅샷 공용)."""
    df["시간코드"] = hours.astype("float32")
    df["weekday"] = weekdays.astype("int8")
    df["is_weekend"] = (weekdays >= 5).astype("int8")
    df["peak_period"] = np.select(
        [hours.isin(MORNING_PEAK), hours.isin(EVENING_PEAK)], ["morning", "evening"], default="off_peak"
    )
    df["hour_sin"] = np.sin(2 * np.pi * hours / 24).astype("float32")
    df["hour_cos"] = np.cos(2 * np.pi * hours / 24).astype("float32")
    df["dow_sin"] = np.sin(2 * np.pi * weekdays / 7).astype("float32")
    df["dow_cos"] = np.cos(2 * np.pi * weekdays / 7).astype("float32")
    df["is_morning_peak"] = hours.isin(MORNING_PEAK).astype("int8")
    df["is_evening_peak"] = hours.isin(EVENING_PEAK).astype("int8")

    precip = df["precip_mm"].fillna(0.0).clip(lower=0)
    df["precip_mm"] = precip.astype("float32")
    df["is_rain"] = (precip > 0).astype("int8")
    df["log_precip"] = np.log1p(precip).astype("float32")
    df["rain_class"] = pd.cut(precip, bins=RAIN_BINS, labels=RAIN_LABELS).astype(str)
    df["rain_morning_peak"] = (df["is_rain"] * df["is_morning_peak"]).astype("int8")
    df["rain_evening_peak"] = (df["is_rain"] * df["is_evening_peak"]).astype("int8")
    df["rain_x_max_spd"] = (df["log_precip"] * df["MAX_SPD"]).astype("float32")
    return df


def build_neighbor_graph(dim: pd.DataFrame) -> dict:
    """노드를 공유하는 1홉 인접 링크 사전."""
    node_to_links = defaultdict(set)
    for lid, fn, tn in zip(dim["LINK_ID"], dim["F_NODE"], dim["T_NODE"]):
        node_to_links[fn].add(lid)
        node_to_links[tn].add(lid)
    neighbors = defaultdict(set)
    for group in node_to_links.values():
        for lid in group:
            neighbors[lid] |= (group - {lid})
    return neighbors


def neighbor_speed_matrix(fact: pd.DataFrame, neighbors: dict) -> tuple:
    """(링크 x 시각) 관측 속도 행렬에 인접행렬을 곱해 '1홉 관측 이웃 평균 실측속도'를 계산.

    관측 링크만 이웃으로 인정하므로, 미관측 링크의 값이 새어 들어갈 여지가 없다.
    """
    links = np.sort(fact["LINK_ID"].unique())
    link_pos = {l: i for i, l in enumerate(links)}
    tms = np.sort(fact["tm_key"].unique())
    tm_pos = {t: i for i, t in enumerate(tms)}

    rows = fact["LINK_ID"].map(link_pos).to_numpy()
    cols = fact["tm_key"].map(tm_pos).to_numpy()
    speed = np.zeros((len(links), len(tms)), dtype="float32")
    valid = np.zeros_like(speed)
    speed[rows, cols] = fact[TARGET].to_numpy()
    valid[rows, cols] = 1.0

    observed = set(links)
    src, dst = [], []
    for lid in links:
        i = link_pos[lid]
        for n in neighbors.get(lid, ()):
            if n in observed:
                src.append(i)
                dst.append(link_pos[n])
    adj = csr_matrix((np.ones(len(src), "float32"), (src, dst)), shape=(len(links), len(links)))
    num, den = adj @ speed, adj @ valid
    with np.errstate(invalid="ignore", divide="ignore"):
        mat = num / den
    mat[den == 0] = np.nan
    return mat, links, link_pos, tm_pos


def neighbor_speed_at_time(all_link_ids: np.ndarray, neighbors: dict,
                           observed: pd.Series) -> np.ndarray:
    """예측 시각의 관측값만으로 링크별 '1홉 관측 이웃 평균 실측속도'를 만든다.

    학습 구간이 아니라 **그 시각에 실제로 들어온 관측**을 쓴다. 배포 시점에는 관측
    링크의 그 시각 속도가 이미 있으므로, 미관측 링크는 그 값을 이웃으로 참조할 수 있다.
    """
    pos = {l: i for i, l in enumerate(all_link_ids)}
    obs = observed.dropna()
    obs_set = set(obs.index)

    src, dst = [], []
    for lid in all_link_ids:
        i = pos[lid]
        for n in neighbors.get(lid, ()):
            if n in obs_set:
                src.append(i)
                dst.append(pos[n])
    n_links = len(all_link_ids)
    adj = csr_matrix((np.ones(len(src), "float32"), (src, dst)), shape=(n_links, n_links))

    speed_vec = np.zeros(n_links, dtype="float32")
    valid_vec = np.zeros(n_links, dtype="float32")
    obs_idx = [pos[l] for l in obs.index if l in pos]
    speed_vec[obs_idx] = obs.loc[[l for l in obs.index if l in pos]].to_numpy(dtype="float32")
    valid_vec[obs_idx] = 1.0

    num, den = adj @ speed_vec, adj @ valid_vec
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / den
    out[den == 0] = np.nan
    return out


def load_training_data(train_end: str, dim: pd.DataFrame, external: list,
                       sample_frac: float) -> tuple:
    """팩트 x 차원을 결합한 학습 테이블과 이웃 속도 조회 자료를 만든다."""
    chunks = []
    reader = pd.read_csv(
        FACT_PATH, usecols=["LINK_ID", "기준일", "시간코드", TARGET, "precip_mm"],
        dtype={"LINK_ID": str, "기준일": str}, encoding="utf-8-sig", chunksize=3_000_000,
    )
    for chunk in reader:
        chunk = chunk[chunk["기준일"] <= train_end]
        if chunk.empty:
            continue
        for col in ["시간코드", TARGET, "precip_mm"]:
            chunk[col] = pd.to_numeric(chunk[col], errors="coerce").astype("float32")
        chunks.append(chunk.dropna(subset=[TARGET]))
    if not chunks:
        raise SystemExit(f"--train-end {train_end} 이전 관측이 팩트 테이블에 없습니다.")
    fact = pd.concat(chunks, ignore_index=True)
    fact["tm_key"] = fact["기준일"] + "_" + fact["시간코드"].astype(int).astype(str)

    neighbors = build_neighbor_graph(dim)
    nb_mat, links, link_pos, tm_pos = neighbor_speed_matrix(fact, neighbors)

    if sample_frac < 1.0:
        fact = fact.sample(frac=sample_frac, random_state=42).reset_index(drop=True)

    fact[NB_FEATURE] = nb_mat[fact["LINK_ID"].map(link_pos).to_numpy(),
                              fact["tm_key"].map(tm_pos).to_numpy()]

    static_cols = ["LINK_ID"] + DIM_CATEGORICAL + DIM_BASE_NUMERIC + DIM_TOPOLOGY + external
    train = fact.merge(dim[static_cols], on="LINK_ID", how="left", validate="many_to_one")
    for col in DIM_BASE_NUMERIC + DIM_TOPOLOGY + external:
        train[col] = pd.to_numeric(train[col], errors="coerce").astype("float32")

    dates = pd.to_datetime(train["기준일"], format="%Y%m%d")
    train = add_time_weather_features(train, train["시간코드"].astype(int), dates.dt.weekday)
    return train, neighbors, nb_mat, link_pos, tm_pos, set(links)


def fit_model(train: pd.DataFrame, features: list, categorical: list, n_estimators: int):
    model = lgb.LGBMRegressor(
        objective="regression", n_estimators=n_estimators, learning_rate=0.05,
        num_leaves=63, random_state=42, n_jobs=-1, verbosity=-1,
    )
    model.fit(train[features], train[TARGET], categorical_feature=categorical)
    return model


def align_categories(train: pd.DataFrame, snapshot: pd.DataFrame, categorical: list) -> pd.Series:
    """스냅샷 범주를 학습 범주에 맞추고, 학습에 없던 값이 있는 행을 표시한다."""
    unseen = pd.Series(False, index=snapshot.index)
    for col in categorical:
        train_cats = pd.Index(train[col].cat.categories.astype(str))
        values = snapshot[col].astype(str)
        unseen |= ~values.isin(train_cats)
        snapshot[col] = pd.Categorical(values, categories=train_cats.union(pd.Index(values.unique())))
    return unseen


def build_fallback_speed(train: pd.DataFrame, snapshot: pd.DataFrame, hour: int, weekday: int) -> pd.Series:
    """ROAD_RANK x MAX_SPD 계층의 속도비율(v/MAX_SPD)로 채우는 최후 수단."""
    ratio = (train[TARGET] / train["MAX_SPD"]).clip(lower=0.05, upper=1.2)
    work = train.assign(speed_ratio=ratio)
    same_time = work[(work["시간코드"] == hour) & (work["weekday"] == weekday)]
    if same_time.empty:
        same_time = work[work["시간코드"] == hour]
    by_combo = same_time.groupby(["ROAD_RANK", "MAX_SPD"], observed=True)["speed_ratio"].mean()
    by_rank = same_time.groupby("ROAD_RANK", observed=True)["speed_ratio"].mean()
    global_ratio = float(same_time["speed_ratio"].mean())

    combo = pd.MultiIndex.from_frame(snapshot[["ROAD_RANK", "MAX_SPD"]])
    value = pd.Series(combo.map(by_combo), index=snapshot.index, dtype=float)
    value = value.fillna(snapshot["ROAD_RANK"].map(by_rank)).fillna(global_ratio)
    return (snapshot["MAX_SPD"] * value).clip(lower=SPEED_FLOOR_KMH, upper=snapshot["MAX_SPD"])


def main() -> None:
    args = parse_args()
    if len(args.tm) != 12 or not args.tm.isdigit():
        raise SystemExit("--tm은 YYYYMMDDHHMM 형식이어야 합니다.")
    date_value, hour = args.tm[:8], int(args.tm[8:10])
    weather_path = PROCESSED_DIR / f"seoul_all_link_weather_{args.tm}.csv"
    if not weather_path.exists():
        raise SystemExit(f"먼저 기상 스냅샷을 생성하세요: {weather_path}\n"
                         f"  python src/12_build_all_link_weather_snapshot.py --tm {args.tm}")

    dim = pd.read_csv(
        DIMENSION_PATH,
        dtype={c: str for c in DIM_CATEGORICAL + ["LINK_ID", "F_NODE", "T_NODE"]},
        encoding="utf-8-sig",
    )
    external = [c for c in DIM_EXTERNAL_CANDIDATES if c in dim.columns]
    missing_external = [c for c in DIM_EXTERNAL_CANDIDATES if c not in dim.columns]
    if missing_external:
        print(f"[주의] 차원 테이블에 없는 외부 컨텍스트 피처: {missing_external}")
        print("       data/raw/traffic/에 원본을 받고 src/pipeline/04를 다시 돌리면 채워집니다.")

    print(f"[1/4] 학습 데이터 로드 (기준일 <= {args.train_end})...")
    train, neighbors, nb_mat, link_pos, tm_pos, observed_links = load_training_data(
        args.train_end, dim, external, args.sample_frac
    )
    categorical = DIM_CATEGORICAL + TIME_CATEGORICAL
    for col in categorical:
        train[col] = train[col].astype("category")
    static_features = DIM_BASE_NUMERIC + DIM_TOPOLOGY + external + TIME_NUMERIC + WEATHER_NUMERIC + categorical
    nb_features = static_features + [NB_FEATURE]
    print(f"      학습 {len(train):,}행 | 관측 링크 {len(observed_links):,} | "
          f"정적 피처 {len(static_features)}개")

    print("[2/4] 모델 2개 학습 (B: 이웃속도 포함 / C: 정적 전용)...")
    model_nb = fit_model(train, nb_features, categorical, args.n_estimators)
    model_static = fit_model(train, static_features, categorical, args.n_estimators)

    print("[3/4] 예측 시각 스냅샷 구성...")
    weather = pd.read_csv(weather_path, usecols=["LINK_ID", "precip_mm"],
                          dtype={"LINK_ID": str}, encoding="utf-8-sig")
    snapshot = dim.merge(weather, on="LINK_ID", how="left", validate="one_to_one")
    for col in DIM_BASE_NUMERIC + DIM_TOPOLOGY + external:
        snapshot[col] = pd.to_numeric(snapshot[col], errors="coerce").astype("float32")
    weekday = pd.Timestamp(date_value).weekday()
    snapshot = add_time_weather_features(
        snapshot,
        pd.Series(hour, index=snapshot.index, dtype="int64"),
        pd.Series(weekday, index=snapshot.index, dtype="int64"),
    )

    # 그 시각의 관측값 — 예측 시각이 학습 구간 밖이어도 관측은 이미 들어와 있다
    observed = pd.read_csv(FACT_PATH, usecols=["LINK_ID", "기준일", "시간코드", TARGET],
                           dtype={"LINK_ID": str, "기준일": str}, encoding="utf-8-sig")
    observed["시간코드"] = pd.to_numeric(observed["시간코드"], errors="coerce")
    observed = observed[(observed["기준일"] == date_value) & (observed["시간코드"] == hour)]
    observed = (observed[["LINK_ID", TARGET]].drop_duplicates("LINK_ID")
                .rename(columns={TARGET: "observed_speed_kmh"}))
    if observed.empty:
        print(f"      [주의] {date_value} {hour}시 관측이 팩트 테이블에 없습니다 — "
              f"전 링크를 모델로 예측하고, 이웃속도 없이 C 계층으로 처리합니다.")
    snapshot = snapshot.merge(observed, on="LINK_ID", how="left", validate="one_to_one")

    # 이웃 속도는 '그 시각의 관측값'에서 만든다(학습 구간이 아니라)
    snapshot[NB_FEATURE] = neighbor_speed_at_time(
        snapshot["LINK_ID"].to_numpy(), neighbors,
        snapshot.set_index("LINK_ID")["observed_speed_kmh"],
    )

    print("[4/4] 계층별 예측...")
    unseen = align_categories(train, snapshot, categorical)
    max_spd = snapshot["MAX_SPD"]
    pred_nb = pd.Series(model_nb.predict(snapshot[nb_features]), index=snapshot.index)
    pred_static = pd.Series(model_static.predict(snapshot[static_features]), index=snapshot.index)

    support = train.groupby(["ROAD_RANK", "MAX_SPD"], observed=True)["LINK_ID"].nunique()
    support_count = pd.Series(
        pd.MultiIndex.from_frame(snapshot[["ROAD_RANK", "MAX_SPD"]]).map(support),
        index=snapshot.index,
    ).fillna(0).astype(int)
    fallback = build_fallback_speed(train, snapshot, hour, weekday)

    is_observed = snapshot["observed_speed_kmh"].notna()
    has_neighbor = snapshot[NB_FEATURE].notna()
    is_supported = (support_count >= args.min_supported_links) & ~unseen

    snapshot["tier"] = np.select(
        [is_observed, has_neighbor], ["A 관측", "B 미관측·이웃있음"], default="C 미관측·이웃없음"
    )
    snapshot["speed_kmh"] = np.select(
        [is_observed,
         is_supported & has_neighbor,
         is_supported & ~has_neighbor],
        [snapshot["observed_speed_kmh"],
         pred_nb.clip(lower=SPEED_FLOOR_KMH, upper=max_spd),
         pred_static.clip(lower=SPEED_FLOOR_KMH, upper=max_spd)],
        default=fallback,
    )
    snapshot["speed_source"] = np.select(
        [is_observed, is_supported & has_neighbor, is_supported & ~has_neighbor],
        ["observed", "model_with_neighbor", "model_static_only"],
        default="hierarchical_fallback",
    )
    snapshot["prediction_confidence"] = np.select(
        [is_observed, is_supported & has_neighbor, is_supported & ~has_neighbor],
        ["high", "medium", "low"], default="low",
    )
    snapshot["travel_time_sec"] = snapshot["LENGTH"] / 1000 / snapshot["speed_kmh"] * 3600

    keep = (["LINK_ID", "F_NODE", "T_NODE", "LENGTH", "MAX_SPD", "ROAD_RANK", "slope_pct",
             "precip_mm", "tier", "speed_kmh", "speed_source", "prediction_confidence",
             "travel_time_sec", "observed_speed_kmh"])
    out_path = PROCESSED_DIR / f"seoul_all_link_speed_{args.tm}.csv"
    snapshot[[c for c in keep if c in snapshot]].to_csv(out_path, index=False, encoding="utf-8-sig")

    print()
    print("전체 링크 속도 스냅샷 저장:", out_path)
    print("계층 구성:")
    print(snapshot["tier"].value_counts().to_string())
    print("속도 출처:")
    print(snapshot["speed_source"].value_counts().to_string())
    print("학습에 없던 범주값 링크:", int(unseen.sum()))
    print("통행시간 결측:", int(snapshot["travel_time_sec"].isna().sum()))
    print(f"평균 속도: {snapshot['speed_kmh'].mean():.1f} km/h")


if __name__ == "__main__":
    main()
