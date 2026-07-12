import html
import struct
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
ROAD_RAW_DIR = RAW_DATA_DIR / "road"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

DBF_PATH = ROAD_RAW_DIR / "MOCT_LINK.dbf"
SHP_PATH = ROAD_RAW_DIR / "MOCT_LINK.shp"
SEOUL_LINK_ATTR_PATH = PROCESSED_DATA_DIR / "seoul_link_attr.csv"
MATCHED_LINKS_PATH = PROCESSED_DATA_DIR / "matched_link_ids.csv"
OUT_SVG = PROCESSED_DATA_DIR / "matched_links_map.svg"

MAX_BACKGROUND_LINKS = 25000
WIDTH = 1200
HEIGHT = 900
PADDING = 30


def read_dbf_link_ids(dbf_path: Path) -> list[str]:
    with dbf_path.open("rb") as file:
        header = file.read(32)
        record_count = struct.unpack("<I", header[4:8])[0]
        header_length = struct.unpack("<H", header[8:10])[0]
        record_length = struct.unpack("<H", header[10:12])[0]

        fields = []
        while True:
            descriptor = file.read(32)
            if descriptor[0] == 0x0D:
                break
            name = descriptor[:11].split(b"\x00", 1)[0].decode("ascii")
            length = descriptor[16]
            fields.append((name, length))

        link_start = 1
        link_length = None
        offset = 1
        for name, length in fields:
            if name == "LINK_ID":
                link_start = offset
                link_length = length
                break
            offset += length
        if link_length is None:
            raise SystemExit("MOCT_LINK.dbf에서 LINK_ID 필드를 찾지 못했습니다.")

        file.seek(header_length)
        link_ids = []
        for _ in range(record_count):
            record = file.read(record_length)
            if not record or record[0:1] == b"*":
                link_ids.append("")
                continue
            raw_link_id = record[link_start : link_start + link_length]
            link_ids.append(raw_link_id.decode("ascii", errors="ignore").strip())
    return link_ids


def iter_shp_polylines(shp_path: Path):
    with shp_path.open("rb") as file:
        file.seek(100)
        while True:
            record_header = file.read(8)
            if len(record_header) < 8:
                break
            record_number, content_length_words = struct.unpack(">2i", record_header)
            content = file.read(content_length_words * 2)
            if len(content) < 44:
                continue
            shape_type = struct.unpack("<i", content[:4])[0]
            if shape_type == 0:
                continue
            if shape_type not in {3, 13, 23}:
                continue
            num_parts = struct.unpack("<i", content[36:40])[0]
            num_points = struct.unpack("<i", content[40:44])[0]
            parts_start = 44
            points_start = parts_start + num_parts * 4
            if len(content) < points_start + num_points * 16:
                continue
            parts = list(struct.unpack(f"<{num_parts}i", content[parts_start:points_start]))
            parts.append(num_points)
            points = [
                struct.unpack("<2d", content[points_start + i * 16 : points_start + (i + 1) * 16])
                for i in range(num_points)
            ]
            part_points = [points[parts[i] : parts[i + 1]] for i in range(num_parts)]
            yield record_number, part_points


def collect_shapes(
    link_ids: list[str],
    seoul_ids: set[str],
    matched_ids: set[str],
) -> tuple[list[list[tuple[float, float]]], list[list[tuple[float, float]]]]:
    seoul_shapes = []
    matched_shapes = []
    background_step = max(1, len(seoul_ids) // MAX_BACKGROUND_LINKS)
    seoul_seen = 0

    for record_number, parts in iter_shp_polylines(SHP_PATH):
        index = record_number - 1
        if index < 0 or index >= len(link_ids):
            continue
        link_id = link_ids[index]
        is_seoul = link_id in seoul_ids
        is_matched = link_id in matched_ids
        if not is_seoul and not is_matched:
            continue

        if is_seoul:
            seoul_seen += 1
        for points in parts:
            if len(points) < 2:
                continue
            if is_matched:
                matched_shapes.append(points)
            elif seoul_seen % background_step == 0:
                seoul_shapes.append(points)

    return seoul_shapes, matched_shapes


def bounds(shapes: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
    xs = [x for shape in shapes for x, _ in shape]
    ys = [y for shape in shapes for _, y in shape]
    return min(xs), min(ys), max(xs), max(ys)


def make_transform(bounds_value: tuple[float, float, float, float]):
    min_x, min_y, max_x, max_y = bounds_value
    scale_x = (WIDTH - PADDING * 2) / (max_x - min_x)
    scale_y = (HEIGHT - PADDING * 2) / (max_y - min_y)
    scale = min(scale_x, scale_y)

    def transform(point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        screen_x = PADDING + (x - min_x) * scale
        screen_y = HEIGHT - PADDING - (y - min_y) * scale
        return screen_x, screen_y

    return transform


def path_data(points: list[tuple[float, float]], transform) -> str:
    transformed = [transform(point) for point in points]
    commands = [f"M {transformed[0][0]:.1f} {transformed[0][1]:.1f}"]
    commands.extend(f"L {x:.1f} {y:.1f}" for x, y in transformed[1:])
    return " ".join(commands)


def write_svg(
    seoul_shapes: list[list[tuple[float, float]]],
    matched_shapes: list[list[tuple[float, float]]],
) -> None:
    transform = make_transform(bounds(seoul_shapes + matched_shapes))
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="30" y="28" font-family="Arial" font-size="18" font-weight="700">Matched T-data links over Seoul link network</text>',
        '<text x="30" y="52" font-family="Arial" font-size="13" fill="#555">gray: sampled Seoul links, red: links matched with T-data speed records</text>',
        '<g fill="none" stroke-linecap="round" stroke-linejoin="round">',
    ]
    for shape in seoul_shapes:
        lines.append(f'<path d="{html.escape(path_data(shape, transform))}" stroke="#d0d0d0" stroke-width="0.35" opacity="0.55"/>')
    for shape in matched_shapes:
        lines.append(f'<path d="{html.escape(path_data(shape, transform))}" stroke="#d62728" stroke-width="1.15" opacity="0.9"/>')
    lines.extend(["</g>", "</svg>"])
    OUT_SVG.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    seoul_ids = set(pd.read_csv(SEOUL_LINK_ATTR_PATH, usecols=["LINK_ID"], dtype={"LINK_ID": str})["LINK_ID"])
    matched_ids = set(pd.read_csv(MATCHED_LINKS_PATH, usecols=["LINK_ID"], dtype={"LINK_ID": str})["LINK_ID"])

    print("DBF에서 LINK_ID 읽는 중...")
    link_ids = read_dbf_link_ids(DBF_PATH)
    print("Shapefile geometry 추출 중...")
    seoul_shapes, matched_shapes = collect_shapes(link_ids, seoul_ids, matched_ids)
    write_svg(seoul_shapes, matched_shapes)

    print("서울 배경 링크 선 수:", len(seoul_shapes))
    print("매칭 링크 선 수:", len(matched_shapes))
    print("저장 파일:", OUT_SVG)


if __name__ == "__main__":
    main()
