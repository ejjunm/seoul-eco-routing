"""
공식 매핑표 기반 '17%' 결합 데이터셋 생성.

기존(40%, 25,151링크)은 04번 스크립트의 prefix8 휴리스틱(LINK_ID 앞 8자리 + 도로명 일치)으로
T-data 속도를 broadcast한 결과다. 이 스크립트는 그 대신
  data/raw/traffic/서울특별시 교통소통 표준링크 매핑정보_20250306.xlsx
의 공식 (서비스링크 -> 표준링크아이디) 매핑을 사용해 라벨 근거가 확실한 데이터셋을 만든다.

  공식 표준링크 11,535개 중 현재 서울 링크에 실존하는 것 = 11,025개 (63,548의 17.3%)

강수 처리: 기존 seoul_link_radar_precip.csv는 25,151링크만 커버하므로,
공식표에만 있고 기존에 없던 링크(약 2,149개)는 '가장 가까운 기존 매핑 링크'의 강수 시계열을 사용한다.
KMA HSR 레이더 격자는 약 1km 해상도이고(서울 25,151링크가 격자 1,576개를 공유),
최근접 거리 중앙값이 110m(93%가 500m 이내)라 사실상 같은 격자값이다. 11GB 원본 재처리 불필요.

출력: data/processed/seoul_link_speed_dem_weather_official.csv  (기존과 동일한 54컬럼 스키마)
사용:  python experiments/build_official_17pct.py
"""
from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
from scipy.spatial import cKDTree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW = PROJECT_ROOT / "data" / "raw"
PROCESSED = PROJECT_ROOT / "data" / "processed"
INTERIM = PROJECT_ROOT / "data" / "interim"
TRAFFIC = RAW / "traffic"
OUT = PROCESSED / "seoul_link_speed_dem_weather_official.csv"

# 기존 최종 테이블과 동일한 컬럼 순서 (harness 재사용을 위해)
TDATA_COLS = ["기준일", "시간코드", "시간대설명", "첨두시구분(T1/T2/T3:오전/낮/오후)", "도로명",
              "도로방향구분코드", "도로방향구분명", "구간순서", "시작노드명", "종료노드명", "평균속도",
              "요일코드(1~7:일~토)", "요일그룹코드(01:주중/02:주말)", "도로코드", "도로구분코드", "도로구분명"]
ATTR_COLS = ["LINK_ID", "F_NODE", "T_NODE", "LANES", "ROAD_RANK", "ROAD_TYPE", "ROAD_NO", "ROAD_NAME",
             "ROAD_USE", "MULTI_LINK", "CONNECT", "MAX_SPD", "REST_VEH", "REST_W", "REST_H", "C-ITS",
             "LENGTH", "UPDATEDATE", "REMARK", "HIST_TYPE", "HISTREMARK"]
META_COLS = ["match_method", "broadcast_source_link_ids", "broadcast_source_count", "broadcast_speed_std"]
DEM_COLS = ["elev_start_m", "elev_mid_m", "elev_end_m", "elev_mean_m", "elev_min_m", "elev_max_m",
            "elev_delta_m", "slope_pct", "abs_slope_pct", "dem_sample_count"]
RADAR_COLS = ["tm", "radar_raw_value", "precip_mm"]


def nfc_listdir(d: Path, suffix: str) -> list[Path]:
    """macOS NFD 파일명 대응: 정규화해서 확장자 매칭."""
    return sorted(d / f for f in os.listdir(d) if unicodedata.normalize("NFC", f).endswith(suffix))


def tdata_tm(date: str, time_code) -> str:
    """T-data (기준일, 시간코드) -> 레이더 tm(YYYYMMDDHHMM). 시간코드 24 = 익일 0시."""
    tc = int(time_code)
    if tc == 24:
        return (pd.Timestamp(date) + pd.Timedelta(days=1)).strftime("%Y%m%d") + "0000"
    return f"{date}{tc:02d}00"


def main():
    # ---------- 1. 공식 매핑표 ----------
    xl = [p for p in nfc_listdir(TRAFFIC, ".xlsx") if "매핑정보" in unicodedata.normalize("NFC", p.name)][0]
    mp = pd.read_excel(xl, dtype=str)
    mp.columns = ["svc", "seq", "LINK_ID"]
    mp = mp.dropna(subset=["svc", "LINK_ID"])
    fanout = mp.groupby("svc")["LINK_ID"].size()          # 서비스링크당 표준링크 수
    print(f"[1] 공식 매핑표: {len(mp):,}행 | 서비스링크 {mp['svc'].nunique():,} -> 표준링크 {mp['LINK_ID'].nunique():,}")

    # ---------- 2. T-data ----------
    tpaths = [p for p in nfc_listdir(TRAFFIC, ".csv") if "소통정보" in unicodedata.normalize("NFC", p.name)]
    td = pd.concat([pd.read_csv(p, dtype=str, encoding="utf-8-sig") for p in tpaths], ignore_index=True)
    td["평균속도"] = pd.to_numeric(td["평균속도"], errors="coerce")
    print(f"[2] T-data: {len(td):,}행 | 고유 링크ID {td['링크ID'].nunique():,} ({[p.name for p in tpaths]})")

    # ---------- 3. 공식 매핑으로 표준링크에 배정 ----------
    df = td.merge(mp[["svc", "LINK_ID"]], left_on="링크ID", right_on="svc", how="inner")
    print(f"[3] 공식 매핑 조인 후: {len(df):,}행 | 표준링크 {df['LINK_ID'].nunique():,}")

    # ---------- 4. 서울 링크 속성 조인 (서울에 실존하는 표준링크만 남음) ----------
    attr = pd.read_csv(PROCESSED / "seoul_link_attr.csv",
                       dtype={c: str for c in ["LINK_ID", "F_NODE", "T_NODE"]}, encoding="utf-8-sig")
    attr = attr[[c for c in ATTR_COLS if c in attr.columns]]
    df = df.merge(attr, on="LINK_ID", how="inner")
    print(f"[4] 서울 링크 조인 후: {len(df):,}행 | 링크 {df['LINK_ID'].nunique():,} "
          f"({df['LINK_ID'].nunique()/63548*100:.1f}% of 63,548)")

    # ---------- 5. 매칭 메타 ----------
    df["match_method"] = "official"
    df["broadcast_source_link_ids"] = df["svc"]
    df["broadcast_source_count"] = df["svc"].map(fanout).astype("int32")
    df["broadcast_speed_std"] = 0.0        # 공식 매핑은 표준링크당 소스 1개 -> 편차 없음

    # ---------- 6. DEM ----------
    dem = pd.read_csv(PROCESSED / "seoul_link_dem_features.csv", dtype={"LINK_ID": str}, encoding="utf-8-sig")
    df = df.merge(dem[["LINK_ID"] + DEM_COLS], on="LINK_ID", how="left")
    print(f"[5] DEM 조인: 경사 결측 {df['slope_pct'].isna().sum():,}행")

    # ---------- 7. tm ----------
    uniq = df[["기준일", "시간코드"]].drop_duplicates()
    uniq["tm"] = [tdata_tm(d, t) for d, t in zip(uniq["기준일"], uniq["시간코드"])]
    df = df.merge(uniq, on=["기준일", "시간코드"], how="left")

    # ---------- 8. 강수: 기존 커버분 직접 조인 ----------
    precip = pd.read_csv(PROCESSED / "seoul_link_radar_precip.csv",
                         dtype={"LINK_ID": str, "tm": str}, encoding="utf-8-sig")
    df = df.merge(precip[["tm", "LINK_ID", "radar_raw_value", "precip_mm"]], on=["tm", "LINK_ID"], how="left")
    need = df.loc[df["precip_mm"].isna(), "LINK_ID"].unique()
    print(f"[6] 강수 직접조인: 결측 링크 {len(need):,}개 -> 최근접 링크에서 대체")

    # ---------- 9. 강수 결측분: 최근접 기존 링크의 시계열 복사 ----------
    if len(need):
        grid = pd.read_csv(PROCESSED / "link_radar_grid_mapping.csv", dtype={"LINK_ID": str})
        gl = pyogrio.read_dataframe(INTERIM / "seoul_link.shp", columns=["LINK_ID"])
        gl["LINK_ID"] = gl["LINK_ID"].astype(str)
        gl = gl[gl["LINK_ID"].isin(set(need))]
        cent = gl.geometry.centroid.to_crs(4326)          # 투영좌표에서 중심 -> WGS84
        pts = np.c_[cent.x.values, cent.y.values]
        tree = cKDTree(np.c_[grid["link_lon"], grid["link_lat"]])
        dist, idx = tree.query(pts)
        donor = pd.DataFrame({"LINK_ID": gl["LINK_ID"].values,
                              "donor": grid["LINK_ID"].values[idx],
                              "dist_m": dist * 111000})
        print(f"    최근접 거리: 중앙값 {donor['dist_m'].median():.0f}m | 90%tile {donor['dist_m'].quantile(.9):.0f}m")

        dp = precip[precip["LINK_ID"].isin(set(donor["donor"]))].rename(
            columns={"LINK_ID": "donor", "radar_raw_value": "rv2", "precip_mm": "pm2"})
        miss = df["precip_mm"].isna()
        fill = df.loc[miss, ["tm", "LINK_ID"]].merge(donor[["LINK_ID", "donor"]], on="LINK_ID", how="left") \
                                              .merge(dp, on=["tm", "donor"], how="left")
        df.loc[miss, "radar_raw_value"] = fill["rv2"].values
        df.loc[miss, "precip_mm"] = fill["pm2"].values
        df["precip_source"] = np.where(miss, "nearest_link", "direct")
        print(f"    대체 후 강수 결측: {df['precip_mm'].isna().sum():,}행")

    # ---------- 10. 저장 ----------
    cols = TDATA_COLS + ATTR_COLS + META_COLS + DEM_COLS + RADAR_COLS
    cols = [c for c in cols if c in df.columns]
    if "precip_source" in df.columns:
        cols.append("precip_source")
    out = df[cols]
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"\n[완료] {OUT.name}")
    print(f"  행 {len(out):,} | 링크 {out['LINK_ID'].nunique():,} | 시각 {out['tm'].nunique()} | 컬럼 {out.shape[1]}")
    print(f"  용량 {OUT.stat().st_size/1024/1024:.0f}MB")
    print(f"  평균속도 결측 {out['평균속도'].isna().sum():,} | 강수 결측 {out['precip_mm'].isna().sum():,}")


if __name__ == "__main__":
    main()
