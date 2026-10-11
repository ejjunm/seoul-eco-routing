"""HDBSCAN으로 마을버스 노선의 자연스러운 유형과 비정형 노선을 찾는다.

08_route_typology.py의 K-평균은 모든 노선을 반드시 네 집단 중 하나에 넣는다.
이 스크립트는 같은 10개 변수를 쓰되 집단 수를 미리 정하지 않고, 밀도가 낮은
노선은 ``cluster=-1``(비정형/경계)로 남긴다.

출력 (data/processed/transit/)
  route_typology_hdbscan.csv  노선별 군집, 소속 확률, 비정형 여부
  hdbscan_profile.csv         군집별 변수 중앙값
  hdbscan_sensitivity.csv     후보 설정별 군집 수/노이즈/실루엣/안정성
  hdbscan_summary.json        최종 설정과 핵심 진단값

사용: python src/transit/11_route_typology_hdbscan.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN, KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRANSIT = PROJECT_ROOT / "data" / "processed" / "transit"
SEED = 42
N_BOOTSTRAPS = 20

FEATURES = {
    "catchment_elderly_share": "고령 비율",
    "catchment_elderly_day": "고령 인구",
    "no_alt_boarding_share": "대체수단 없는 승차",
    "bus_g_per_pkm": "승객km당 CO2",
    "route_cars_per_1000": "승용차 보유",
    "boardings_per_day": "하루 승차",
    "slope_mean": "평균 경사",
    "one_lane_share": "1차로 비중",
    "day_speed_kmh": "낮 속도",
    "trips_per_day": "하루 운행",
}


def load_data() -> pd.DataFrame:
    data = pd.read_csv(TRANSIT / "route_priority.csv", dtype={"ROUTE_ID": str})
    demand = pd.read_csv(TRANSIT / "route_demand.csv", dtype={"ROUTE_ID": str})[
        ["ROUTE_ID", "route_cars_per_1000"]
    ]
    feasibility = pd.read_csv(TRANSIT / "route_feasibility.csv", dtype={"ROUTE_ID": str})[
        ["ROUTE_ID", "slope_mean", "one_lane_share", "day_speed_kmh"]
    ]
    return data.merge(demand, on="ROUTE_ID", how="left").merge(
        feasibility, on="ROUTE_ID", how="left"
    )


def bootstrap_stability(x: np.ndarray, labels: np.ndarray, params: dict) -> float:
    """80% 부분표본 재학습 때 원래 군집과의 ARI 중앙값을 계산한다.

    두 결과에서 모두 군집으로 판정된 행만 비교한다. 비교 가능한 행이 너무 적거나
    한쪽이 한 군집뿐이면 그 반복은 0점으로 처리한다.
    """
    rng = np.random.default_rng(SEED)
    scores: list[float] = []
    sample_size = max(30, int(len(x) * 0.8))
    for _ in range(N_BOOTSTRAPS):
        idx = np.sort(rng.choice(len(x), size=sample_size, replace=False))
        boot_labels = HDBSCAN(**params).fit_predict(x[idx])
        base_labels = labels[idx]
        keep = (base_labels >= 0) & (boot_labels >= 0)
        if keep.sum() < 20 or len(np.unique(base_labels[keep])) < 2 or len(np.unique(boot_labels[keep])) < 2:
            scores.append(0.0)
        else:
            scores.append(float(adjusted_rand_score(base_labels[keep], boot_labels[keep])))
    return float(np.median(scores))


def evaluate_candidate(x: np.ndarray, min_cluster_size: int, min_samples: int,
                       method: str) -> tuple[dict, np.ndarray, np.ndarray]:
    params = {
        "min_cluster_size": min_cluster_size,
        "min_samples": min_samples,
        "cluster_selection_method": method,
        "allow_single_cluster": False,
        "copy": True,
    }
    model = HDBSCAN(**params).fit(x)
    labels = model.labels_
    clustered = labels >= 0
    clusters = np.unique(labels[clustered])
    n_clusters = len(clusters)
    coverage = float(clustered.mean())
    smallest = int(pd.Series(labels[clustered]).value_counts().min()) if n_clusters else 0
    if n_clusters >= 2 and clustered.sum() >= 30:
        silhouette = float(silhouette_score(x[clustered], labels[clustered]))
        stability = bootstrap_stability(x, labels, params)
    else:
        silhouette = float("nan")
        stability = 0.0
    mean_probability = float(model.probabilities_[clustered].mean()) if clustered.any() else 0.0

    # 실루엣만 최대화하면 대부분을 노이즈로 버린 작은 군집이 뽑힐 수 있다.
    # 최소 50%를 설명하는 해 중 분리도·부분표본 안정성·소속 확률을 함께 본다.
    valid = n_clusters >= 2 and coverage >= 0.50 and smallest >= 5
    score = (
        0.45 * silhouette + 0.35 * stability + 0.20 * mean_probability - 0.15 * (1.0 - coverage)
        if valid else float("-inf")
    )
    row = {
        "algorithm": "HDBSCAN",
        "min_cluster_size": min_cluster_size,
        "min_samples": min_samples,
        "selection_method": method,
        "n_clusters": n_clusters,
        "noise_count": int((~clustered).sum()),
        "noise_share": 1.0 - coverage,
        "smallest_cluster": smallest,
        "silhouette_clustered": silhouette,
        "bootstrap_ari_median": stability,
        "mean_membership_probability": mean_probability,
        "selection_score": score,
        "eligible": valid,
    }
    return row, labels, model.probabilities_


def cluster_names(x_frame: pd.DataFrame, labels: np.ndarray) -> dict[int, str]:
    z_median = x_frame.assign(cluster=labels).query("cluster >= 0").groupby("cluster").median()
    names: dict[int, str] = {}
    for cluster, row in z_median.iterrows():
        feature = row.abs().idxmax()
        direction = "높음" if row[feature] >= 0 else "낮음"
        names[int(cluster)] = f"밀도군집 {int(cluster)} · {FEATURES[feature]} {direction}"
    names[-1] = "비정형/경계"
    return names


def main() -> None:
    data = load_data()
    cols = list(FEATURES)
    missing = data[cols].isna().sum()
    if missing.any():
        print("결측(전체 노선 중앙값으로 채움):", missing[missing > 0].to_dict())
    filled = data[cols].fillna(data[cols].median())
    x = StandardScaler().fit_transform(filled)

    rows: list[dict] = []
    fits: list[tuple[np.ndarray, np.ndarray]] = []
    print("[1/3] HDBSCAN 민감도와 부분표본 안정성 평가...")
    for min_cluster_size in [5, 8, 10, 12, 15, 20, 25, 30]:
        for min_samples in [3, 5, 8, 10]:
            if min_samples > min_cluster_size:
                continue
            for method in ["eom", "leaf"]:
                row, labels, probabilities = evaluate_candidate(
                    x, min_cluster_size, min_samples, method
                )
                rows.append(row)
                fits.append((labels, probabilities))

    sensitivity = pd.DataFrame(rows)
    eligible = sensitivity.loc[sensitivity["eligible"]]
    if eligible.empty:
        # 이 경우도 결과다. 군집을 억지로 만들지 않고 가장 넓게 설명하는 해를
        # 진단용으로 저장하되 summary의 reliable_solution=false로 명시한다.
        best_index = int(sensitivity.sort_values(
            ["noise_share", "silhouette_clustered", "n_clusters"],
            ascending=[True, False, False], na_position="last"
        ).index[0])
        reliable = False
    else:
        best_index = int(eligible["selection_score"].idxmax())
        reliable = True
    best = sensitivity.loc[best_index]
    labels, probabilities = fits[best_index]
    sensitivity.to_csv(TRANSIT / "hdbscan_sensitivity.csv", index=False, encoding="utf-8-sig")

    print("[2/3] 선택된 해 저장...")
    z_frame = pd.DataFrame(x, columns=cols)
    names = cluster_names(z_frame, labels)
    data["hdbscan_cluster"] = labels
    data["hdbscan_type"] = pd.Series(labels, index=data.index).map(names)
    data["membership_probability"] = probabilities
    data["is_noise"] = labels < 0
    keep = ["ROUTE_ID", "노선명", "hdbscan_cluster", "hdbscan_type",
            "membership_probability", "is_noise", "class", *cols]
    data[keep].to_csv(TRANSIT / "route_typology_hdbscan.csv", index=False, encoding="utf-8-sig")

    clustered = data.loc[data["hdbscan_cluster"] >= 0].copy()
    profile = clustered.groupby(["hdbscan_cluster", "hdbscan_type"])[cols].median()
    profile.insert(0, "노선수", clustered.groupby(["hdbscan_cluster", "hdbscan_type"]).size())
    profile = profile.rename(columns=FEATURES)
    profile.to_csv(TRANSIT / "hdbscan_profile.csv", encoding="utf-8-sig")

    kmeans = []
    for k in range(2, 7):
        k_labels = KMeans(k, n_init=50, random_state=SEED).fit_predict(x)
        kmeans.append({"k": k, "silhouette": float(silhouette_score(x, k_labels))})
    summary = {
        "n_routes": int(len(data)),
        "reliable_solution": reliable,
        "selection_rule": "coverage>=0.50, clusters>=2, smallest_cluster>=5; composite score",
        "selected_parameters": {
            "min_cluster_size": int(best["min_cluster_size"]),
            "min_samples": int(best["min_samples"]),
            "cluster_selection_method": str(best["selection_method"]),
        },
        "n_clusters": int(best["n_clusters"]),
        "noise_count": int(best["noise_count"]),
        "noise_share": float(best["noise_share"]),
        "silhouette_clustered": None if pd.isna(best["silhouette_clustered"]) else float(best["silhouette_clustered"]),
        "bootstrap_ari_median": float(best["bootstrap_ari_median"]),
        "mean_membership_probability": float(best["mean_membership_probability"]),
        "ari_vs_policy_classes": float(adjusted_rand_score(data["class_id"], labels)),
        "kmeans_reference": kmeans,
    }
    (TRANSIT / "hdbscan_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("[3/3] 완료")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not profile.empty:
        print("\n군집 프로필(중앙값):")
        print(profile.round(2).to_string())


if __name__ == "__main__":
    main()
