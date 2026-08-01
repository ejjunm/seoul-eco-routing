from collections import defaultdict
from heapq import heappop, heappush
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

SEOUL_LINK_ATTR_PATH = PROCESSED_DATA_DIR / "seoul_link_attr.csv"
MERGED_PATH = PROCESSED_DATA_DIR / "seoul_link_speed_merged.csv"
ROAD_RANK_OUT = PROCESSED_DATA_DIR / "matched_road_rank_coverage.csv"
COMPONENT_OUT = PROCESSED_DATA_DIR / "matched_graph_components.csv"
MATCHED_LINKS_OUT = PROCESSED_DATA_DIR / "matched_link_ids.csv"


class DisjointSet:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.size: dict[str, int] = {}

    def add(self, item: str) -> None:
        if item not in self.parent:
            self.parent[item] = item
            self.size[item] = 1

    def find(self, item: str) -> str:
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != item:
            parent = self.parent[item]
            self.parent[item] = root
            item = parent
        return root

    def union(self, left: str, right: str) -> None:
        self.add(left)
        self.add(right)
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if self.size[left_root] < self.size[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        self.size[left_root] += self.size[right_root]


def read_seoul_links() -> pd.DataFrame:
    return pd.read_csv(
        SEOUL_LINK_ATTR_PATH,
        dtype={"LINK_ID": str, "F_NODE": str, "T_NODE": str},
    )


def read_merged() -> pd.DataFrame:
    return pd.read_csv(
        MERGED_PATH,
        dtype={
            "LINK_ID": str,
            "F_NODE": str,
            "T_NODE": str,
            "시간코드": str,
        },
        encoding="utf-8-sig",
    )


def analyze_road_rank_coverage(seoul_links: pd.DataFrame, matched_links: pd.DataFrame) -> pd.DataFrame:
    total = (
        seoul_links.groupby("ROAD_RANK")["LINK_ID"]
        .nunique()
        .rename("total_link_count")
        .reset_index()
    )
    matched = (
        matched_links.groupby("ROAD_RANK")["LINK_ID"]
        .nunique()
        .rename("matched_link_count")
        .reset_index()
    )
    coverage = total.merge(matched, on="ROAD_RANK", how="left")
    coverage["matched_link_count"] = coverage["matched_link_count"].fillna(0).astype(int)
    coverage["match_rate_pct"] = (
        coverage["matched_link_count"] / coverage["total_link_count"] * 100
    ).round(2)
    return coverage.sort_values("ROAD_RANK")


def build_unique_matched_links(merged: pd.DataFrame) -> pd.DataFrame:
    link_columns = [
        "LINK_ID",
        "F_NODE",
        "T_NODE",
        "ROAD_RANK",
        "ROAD_TYPE",
        "ROAD_NAME",
        "LENGTH",
        "MAX_SPD",
        "LANES",
    ]
    return merged[link_columns].drop_duplicates("LINK_ID").copy()


def analyze_components(matched_links: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    dsu = DisjointSet()
    for row in matched_links[["F_NODE", "T_NODE"]].itertuples(index=False):
        dsu.union(row.F_NODE, row.T_NODE)

    node_component = {node: dsu.find(node) for node in dsu.parent}
    matched_links = matched_links.copy()
    matched_links["component_id"] = matched_links["F_NODE"].map(node_component)

    components = (
        matched_links.groupby("component_id")
        .agg(
            link_count=("LINK_ID", "nunique"),
            node_count=("F_NODE", lambda values: 0),
        )
        .reset_index()
    )

    node_counts = defaultdict(set)
    for row in matched_links[["component_id", "F_NODE", "T_NODE"]].itertuples(index=False):
        node_counts[row.component_id].add(row.F_NODE)
        node_counts[row.component_id].add(row.T_NODE)
    components["node_count"] = components["component_id"].map(lambda component: len(node_counts[component]))
    components = components.sort_values(["link_count", "node_count"], ascending=False).reset_index(drop=True)
    components.insert(0, "component_rank", range(1, len(components) + 1))
    components["link_share_pct"] = (components["link_count"] / len(matched_links) * 100).round(2)
    return components, node_component


def build_average_speed_graph(merged: pd.DataFrame) -> dict[str, list[tuple[str, float, str]]]:
    work = merged[["LINK_ID", "F_NODE", "T_NODE", "LENGTH", "평균속도"]].copy()
    work["평균속도"] = pd.to_numeric(work["평균속도"], errors="coerce")
    work["LENGTH"] = pd.to_numeric(work["LENGTH"], errors="coerce")
    work = work.dropna(subset=["평균속도", "LENGTH"])
    work = work[work["평균속도"] > 0]
    link_speed = (
        work.groupby(["LINK_ID", "F_NODE", "T_NODE", "LENGTH"], as_index=False)["평균속도"]
        .mean()
    )

    graph: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    for row in link_speed.itertuples(index=False):
        travel_time_hours = (row.LENGTH / 1000) / row.평균속도
        graph[row.F_NODE].append((row.T_NODE, travel_time_hours, row.LINK_ID))
    return graph


def dijkstra(
    graph: dict[str, list[tuple[str, float, str]]],
    source: str,
    target: str,
) -> tuple[float, list[str]]:
    heap = [(0.0, source, [])]
    best = {source: 0.0}
    while heap:
        cost, node, path = heappop(heap)
        if node == target:
            return cost, path
        if cost > best.get(node, float("inf")):
            continue
        for next_node, weight, link_id in graph.get(node, []):
            next_cost = cost + weight
            if next_cost < best.get(next_node, float("inf")):
                best[next_node] = next_cost
                heappush(heap, (next_cost, next_node, path + [link_id]))
    return float("inf"), []


def main() -> None:
    seoul_links = read_seoul_links()
    merged = read_merged()
    matched_links = build_unique_matched_links(merged)

    coverage = analyze_road_rank_coverage(seoul_links, matched_links)
    components, node_component = analyze_components(matched_links)

    coverage.to_csv(ROAD_RANK_OUT, index=False, encoding="utf-8-sig")
    components.to_csv(COMPONENT_OUT, index=False, encoding="utf-8-sig")
    matched_links.to_csv(MATCHED_LINKS_OUT, index=False, encoding="utf-8-sig")

    largest_component = components.iloc[0]
    largest_component_id = largest_component["component_id"]
    largest_links = matched_links[
        matched_links["F_NODE"].map(node_component) == largest_component_id
    ]

    graph = build_average_speed_graph(merged[merged["LINK_ID"].isin(largest_links["LINK_ID"])])
    source = largest_links.iloc[0]["F_NODE"]
    target = largest_links.iloc[-1]["T_NODE"]
    cost, path = dijkstra(graph, source, target)

    print("도로등급별 매칭률 저장:", ROAD_RANK_OUT)
    print(coverage.to_string(index=False))
    print()
    print("연결 컴포넌트 저장:", COMPONENT_OUT)
    print("컴포넌트 수:", len(components))
    print("최대 컴포넌트 링크 수:", int(largest_component["link_count"]))
    print("최대 컴포넌트 노드 수:", int(largest_component["node_count"]))
    print("최대 컴포넌트 링크 비율(%):", largest_component["link_share_pct"])
    print()
    print("샘플 방향 그래프 경로 탐색")
    print("출발 노드:", source)
    print("도착 노드:", target)
    if path:
        print("경로 탐색 가능: yes")
        print("경로 링크 수:", len(path))
        print("예상 통행시간(분):", round(cost * 60, 2))
    else:
        print("경로 탐색 가능: no")
    print()
    print("매칭 링크 목록 저장:", MATCHED_LINKS_OUT)


if __name__ == "__main__":
    main()
