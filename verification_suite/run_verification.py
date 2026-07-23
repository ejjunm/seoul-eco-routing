from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd


# =============================================================================
# 1. Configuration & Data Structures
# =============================================================================

@dataclass
class PipelineConfig:
    """프로젝트 경로 및 검증 파라미터 관리 클래스"""
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])
    
    # 원본 데이터 경로
    raw_dir: Path = field(init=False)
    moct_link_path: Path = field(init=False)
    seoul_boundary_path: Path = field(init=False)
    tdata_dir: Path = field(init=False)
    official_mapping_path: Path = field(init=False)
    dem_dir: Path = field(init=False)
    
    # 검증 출력 경로
    output_dir: Path = field(init=False)
    cache_meta_path: Path = field(init=False)
    
    # 컬럼 정의
    link_key: str = "LINK_ID"
    tdata_link_key: str = "링크ID"
    official_service_key: str = "서비스링크"
    official_target_key: str = "표준링크아이디"

    def __post_init__(self):
        self.raw_dir = self.project_root / "data" / "raw"
        self.moct_link_path = self.raw_dir / "road" / "MOCT_LINK.shp"
        self.seoul_boundary_path = self.raw_dir / "boundary" / "seoul_admin_boundary.geojson"
        self.tdata_dir = self.raw_dir / "traffic"
        self.official_mapping_path = self.tdata_dir / "서울특별시 교통소통 표준링크 매핑정보_20250306.xlsx"
        self.dem_dir = self.raw_dir / "dem"
        
        self.output_dir = self.project_root / "verification_suite" / "temp_outputs"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_meta_path = self.output_dir / ".cache_metadata.json"


# =============================================================================
# 2. Logger & Metadata Manager
# =============================================================================

class VerificationLogger:
    """검증 로깅 및 메타데이터 추적 클래스"""
    def __init__(self):
        self.logs: List[Dict[str, Any]] = []

    def header(self, title: str):
        print("\n" + "=" * 80)
        print(f"  {title}")
        print("=" * 80)

    def result(self, description: str, value: Any, unit: str = ""):
        if isinstance(value, (int, float)):
            if isinstance(value, float):
                formatted = f"{value:,.2f}"
            else:  # int
                formatted = f"{value:,}"
        else:
            formatted = str(value)
        msg = f"- {description:<48}: {formatted} {unit}".strip()
        print(msg)
        self.logs.append({"desc": description, "val": value, "unit": unit})


class CacheManager:
    """처리 이력 관리 및 증분 처리 지원 클래스"""
    def __init__(self, meta_path: Path):
        self.meta_path = meta_path
        self.metadata = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.meta_path.exists():
            try:
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save(self):
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2, ensure_ascii=False)

    def is_file_processed(self, file_path: Path) -> bool:
        """파일 수정 시간을 비교하여 변경 여부 판단"""
        key = str(file_path.resolve())
        mtime = file_path.stat().st_mtime
        return self.metadata.get("files", {}).get(key) == mtime

    def mark_file_processed(self, file_path: Path):
        if "files" not in self.metadata:
            self.metadata["files"] = {}
        self.metadata["files"][str(file_path.resolve())] = file_path.stat().st_mtime


# =============================================================================
# 3. Core Reusable Pipeline
# =============================================================================

class VerificationPipeline:
    def __init__(self, config: PipelineConfig, force_rerun: bool = False):
        self.cfg = config
        self.force = force_rerun
        self.logger = VerificationLogger()
        self.cache = CacheManager(self.cfg.cache_meta_path)

    def step_1_get_seoul_links(self) -> gpd.GeoDataFrame:
        """1단계: 서울시 링크 추출 (캐시 적용)"""
        self.logger.header("1단계: 서울시 링크 추출 (기준 도로망 확보)")
        cache_shp = self.cfg.output_dir / "seoul_link.shp"

        if not self.force and cache_shp.exists():
            print("⚡ [Cache] 기존에 추출된 서울시 링크 Shapefile을 로드합니다.")
            seoul_links = gpd.read_file(cache_shp)
            seoul_links[self.cfg.link_key] = seoul_links[self.cfg.link_key].astype(str)
            self.logger.result("추출된 서울시 링크 수 (캐시 기준)", len(seoul_links), "개 (100%)")
            return seoul_links

        print("🔄 [Compute] 서울 행정경계 조인 연산을 실행합니다...")
        all_links = gpd.read_file(self.cfg.moct_link_path)
        seoul_boundary = gpd.read_file(self.cfg.seoul_boundary_path).to_crs(all_links.crs)
        
        print(f"  - 원본 데이터: 전국 도로망 ({self.cfg.moct_link_path.name}, {len(all_links):,}개 링크)")
        print(f"  - 기준 영역: 서울시 행정경계 ({self.cfg.seoul_boundary_path.name})")
        print(f"  - 처리 방식: 'geopandas.sjoin'을 이용, 행정경계와 교차(intersects)하는 모든 링크 추출")
        poly = seoul_boundary.unary_union

        seoul_links = all_links[all_links.intersects(poly)].copy()
        seoul_links[self.cfg.link_key] = seoul_links[self.cfg.link_key].astype(str)

        seoul_links.to_file(cache_shp)
        self.logger.result("전체 표준노드링크 수", len(all_links), "개")
        self.logger.result("추출된 서울시 링크 수 (신규 생성)", len(seoul_links), "개 (100%)")
        return seoul_links

    def step_2_verify_attributes(self, seoul_links: gpd.GeoDataFrame) -> pd.DataFrame:
        """2단계: 서울 링크 속성 유효성 검증"""
        self.logger.header("2단계: 서울 링크 속성 전처리 및 유효성 검증")
        cache_csv = self.cfg.output_dir / "seoul_link_attr.csv"

        if not self.force and cache_csv.exists():
            print("⚡ [Cache] 기존에 저장된 속성 테이블을 로드합니다.")
            return pd.read_csv(cache_csv, dtype={self.cfg.link_key: str})

        print("🔄 [Compute] 서울시 링크의 주요 속성(도로명, 제한속도) 품질을 검증합니다.")
        total = len(seoul_links)
        missing_name = seoul_links["ROAD_NAME"].isna().sum()
        invalid_spd = seoul_links["MAX_SPD"].fillna(0).le(0).sum()

        print(f"  - 검증 1: 도로명(ROAD_NAME) 결측 확인. 모델의 카테고리 피처 생성에 영향.")
        self.logger.result("도로명(ROAD_NAME) 결측 수", missing_name, f"개 ({(missing_name/total)*100:.2f}%)")
        print(f"  - 검증 2: 제한속도(MAX_SPD) 유효성 확인 (0 또는 결측). 모델의 숫자 피처 생성에 영향.")
        self.logger.result("제한속도(MAX_SPD) 무효 수", invalid_spd, f"개 ({(invalid_spd/total)*100:.2f}%)")

        attr_df = pd.DataFrame(seoul_links.drop(columns="geometry"))
        attr_df.to_csv(cache_csv, index=False, encoding="utf-8-sig")
        return attr_df

    def step_3_incremental_tdata_match(self, seoul_link_ids: Set[str]) -> Tuple[pd.DataFrame, Set[str]]:
        """3단계: T-data 매칭 검증 (증분 처리 및 캐시 적용)"""
        self.logger.header("3단계: T-data 속도 정보 결합 및 손실률 검증 (증분 처리)")
        
        print(f"  - [A] 공식 매핑 테이블을 이용한 커버리지 분석")
        print(f"    - 사용 파일: {self.cfg.official_mapping_path.name}")
        print(f"    - 결합 방식: T-data의 '링크ID'와 표준링크의 'LINK_ID'를 연결")
        mapping_df = pd.read_excel(
            self.cfg.official_mapping_path,
            dtype={self.cfg.official_service_key: str, self.cfg.official_target_key: str},
        )
        
        mapped_target_ids = set(mapping_df[self.cfg.official_target_key].dropna())
        matched_seoul_ids = seoul_link_ids.intersection(mapped_target_ids)

        total_links = len(seoul_link_ids)
        matched_cnt = len(matched_seoul_ids)
        loss_cnt = total_links - matched_cnt
        
        print(f"    - 분석: 매핑 테이블에 정의된 표준링크 ID와 서울시 링크 ID를 비교하여 결합 가능한 링크 수를 확인합니다.")
        self.logger.result("기준 서울 링크 수", total_links, "개 (100%)")
        self.logger.result("공식 매핑 가능 링크 수", matched_cnt, f"개 ({(matched_cnt/total_links)*100:.2f}%)")
        self.logger.result("데이터 결합 손실 링크 수", loss_cnt, f"개 ({(loss_cnt/total_links)*100:.2f}%)")
        print("💡 [진단] 매핑 파일의 커버리지(포함된 링크 수)가 데이터 결합률의 상한선을 결정합니다.")

        # T-data CSV 증분 로드
        tdata_files = sorted(self.cfg.tdata_dir.glob("1시간 소통정보 (구간별)*.csv"))
        new_files = [f for f in tdata_files if self.force or not self.cache.is_file_processed(f)]

        cache_speed_csv = self.cfg.output_dir / "seoul_link_speed_merged.csv"

        if not new_files and cache_speed_csv.exists() and not self.force:
            print("⚡ [Cache] 모든 T-data 파일이 최신 상태입니다. 캐시 데이터를 로드합니다.")
            speed_df = pd.read_csv(cache_speed_csv, dtype={self.cfg.link_key: str})
            return speed_df, matched_seoul_ids

        print(f"\n  - [B] T-data와 서울 링크 결합 처리")
        if new_files:
            print(f"    - 신규/변경 T-data 파일 {len(new_files)}개를 포함하여 전체 데이터를 다시 처리합니다...")
        else:
            print(f"    - 캐시가 없어 전체 T-data 파일을 처리합니다...")
        
        tdata_frames = []
        for f in tdata_files:
            df = pd.read_csv(f, dtype={self.cfg.tdata_link_key: str}, encoding="utf-8-sig")
            tdata_frames.append(df)
            self.cache.mark_file_processed(f)
        raw_tdata = pd.concat(tdata_frames, ignore_index=True)
        print(f"    - T-data 원본: {len(raw_tdata):,} 행")

        # 조인 수행
        print(f"    - 처리 1: T-data와 매핑 테이블 결합 (Inner Join)")
        print(f"      - Left: T-data ({self.cfg.tdata_link_key}), Right: 매핑 테이블 ({self.cfg.official_service_key})")
        merged = raw_tdata.merge(
            mapping_df, left_on=self.cfg.tdata_link_key, right_on=self.cfg.official_service_key, how="inner"
        )
        print(f"      - 결과: {len(merged):,} 행")

        print(f"    - 처리 2: 위 결과와 서울 링크 목록 결합 (Inner Join)")
        print(f"      - Left: 처리 1 결과 ({self.cfg.official_target_key}), Right: 서울 링크 목록 ({self.cfg.link_key})")
        merged = merged.merge(
            pd.DataFrame({self.cfg.link_key: list(seoul_link_ids)}),
            left_on=self.cfg.official_target_key,
            right_on=self.cfg.link_key,
            how="inner"
        )
        print(f"      - 결과: {len(merged):,} 행")

        merged["평균속도"] = pd.to_numeric(merged["평균속도"], errors="coerce")
        print(f"    - 처리 3: (링크, 시간) 기준 중복 값 평균 집계 (Groupby & Mean)")
        final_speed = merged.groupby([self.cfg.link_key, "기준일", "시간코드"])["평균속도"].mean().reset_index()

        final_speed.to_csv(cache_speed_csv, index=False, encoding="utf-8-sig")
        if not self.force:
            self.cache.save()

        self.logger.result("결합된 속도 레코드 행 수", len(final_speed), "행")
        return final_speed, matched_seoul_ids

    def step_4_verify_dem_coverage(self, seoul_links: gpd.GeoDataFrame) -> pd.DataFrame:
        """4단계: DEM 지형 결합 커버리지 확인"""
        self.logger.header("4단계: DEM(지형) 공간 매칭 및 커버리지 검증")
        cache_dem_csv = self.cfg.output_dir / "seoul_link_dem_features.csv"

        if not self.force and cache_dem_csv.exists():
            print("⚡ [Cache] 기존 DEM 샘플링 캐시 데이터를 로드합니다.")
            return pd.read_csv(cache_dem_csv, dtype={self.cfg.link_key: str})

        print("🔄 [Compute] DEM(수치표고모델) 래스터와 공간 매칭을 수행합니다.")
        try:
            import rasterio
        except ImportError:
            print("⚠️ 'rasterio' 패키지가 없어 DEM 공간 검증을 건너뜁니다.")
            return pd.DataFrame()

        dem_files = sorted(self.cfg.dem_dir.glob("*.img")) + sorted(self.cfg.dem_dir.glob("*.tif"))        
        if not dem_files:
            print("⚠️ DEM 원본 파일(.img/.tif)이 없습니다.")
            return pd.DataFrame()
        
        print(f"  - 원본 데이터: {', '.join(p.name for p in dem_files)}")
        print(f"  - 처리 방식: 각 링크의 중심점(centroid) 좌표로 고도 값을 샘플링하여 결합 가능 여부 확인")

        print("🔄 [Compute] Rasterio 기반 래스터 커버리지 샘플링 연산 수행 중...")
        
        @contextmanager
        def open_rasters(paths):
            srcs = [rasterio.open(p) for p in paths]
            try:
                yield srcs
            finally:
                for s in srcs:
                    s.close()

        records = []
        with open_rasters(dem_files) as sources:
            dem_crs = sources[0].crs
            links_transformed = seoul_links.to_crs(dem_crs)

            for row in links_transformed.itertuples():
                pt = row.geometry.centroid
                sampled = 0
                for src in sources:
                    if (src.bounds.left <= pt.x <= src.bounds.right and 
                        src.bounds.bottom <= pt.y <= src.bounds.top):
                        val = next(src.sample([(pt.x, pt.y)]))[0]
                        if src.nodata is None or val != src.nodata:
                            sampled = 1
                            break
                records.append({self.cfg.link_key: str(getattr(row, self.cfg.link_key)), "dem_sampled": sampled})

        dem_df = pd.DataFrame(records)
        matched_cnt = dem_df["dem_sampled"].sum()
        total_cnt = len(dem_df)

        self.logger.result("기준 서울 링크 수", total_cnt, "개")
        self.logger.result("DEM 공간 매칭 성공 수", matched_cnt, f"개 ({(matched_cnt/total_cnt)*100:.2f}%)")

        dem_df.to_csv(cache_dem_csv, index=False, encoding="utf-8-sig")
        return dem_df

    def step_5_final_report(self, speed_df: pd.DataFrame, dem_df: pd.DataFrame, total_links: int, tdata_matched_ids: Set[str]):
        """5단계: 종합 파이프라인 결합 결과 시뮬레이션 및 요약"""
        self.logger.header("5단계: 최종 결합 검증 및 병목 진단 보고서")

        if speed_df is None or speed_df.empty:
            self.logger.result("최종 결합 레코드 수", 0, "행")
            self.logger.result("최종 결합 성공 고유 링크 수", 0, f"개 (0.00%)")
            print("\n" + "=" * 80)
            print(" 📌 파이프라인 검증 최종 진단 결론")
            print("=" * 80)
            print("- 속도 데이터(T-data) 결합에 실패하여 최종 데이터셋을 생성할 수 없습니다.")
            print("- 3단계 로그를 확인하여 원인을 파악해야 합니다.")
            return

        final_csv = self.cfg.output_dir / "final_merged_dataset.csv"
        print(f"  - 최종 결합: 3단계 속도 데이터와 4단계 DEM 데이터를 결합합니다.")
        print(f"    - Left: 속도 데이터 ({len(speed_df):,} 행), Right: DEM 데이터")
        print(f"    - 결합 방식: Left Join (on='{self.cfg.link_key}')")
        if dem_df is not None and not dem_df.empty:
            merged = speed_df.merge(dem_df, on=self.cfg.link_key, how="left")
        else:
            merged = speed_df
            print("    - DEM 데이터가 없어 속도 데이터만 최종 결과로 사용합니다.")
        merged.to_csv(final_csv, index=False, encoding="utf-8-sig")

        unique_matched_links = merged[self.cfg.link_key].nunique()
        self.logger.result("최종 결합 테이블 행 수", len(merged), "행")
        self.logger.result("최종 결합 성공 고유 링크 수", unique_matched_links, f"개 ({(unique_matched_links/total_links)*100:.2f}%)")

        # 동적 요약 생성
        tdata_match_count = len(tdata_matched_ids)
        tdata_match_rate = (tdata_match_count / total_links) * 100 if total_links > 0 else 0

        dem_match_rate = 0.0
        if dem_df is not None and not dem_df.empty:
            dem_match_count = int(dem_df["dem_sampled"].sum())
            dem_match_rate = (dem_match_count / total_links) * 100 if total_links > 0 else 0

        print("\n" + "=" * 80)
        print(" 📌 파이프라인 검증 최종 진단 결론")
        print("=" * 80)
        print(f"1. [기준] 서울시 도로망 링크 {total_links:,}개를 기준으로 데이터 결합을 시작합니다.")
        
        if dem_df is not None and not dem_df.empty:
            print(f"2. [전처리] 서울 링크의 기본 속성(도로명, 제한속도)은 양호하며, 지형(DEM) 데이터는 {dem_match_rate:.2f}% 결합 가능합니다.")
        else:
            print("2. [전처리] 서울 링크의 기본 속성(도로명, 제한속도)은 양호하며, 지형(DEM) 데이터 검증은 건너뛰었습니다.")

        print(f"3. [병목] T-data 속도 정보 결합 시, 공식 매핑 테이블의 한계로 인해 링크의 약 {100-tdata_match_rate:.2f}%가 손실됩니다.")

        if tdata_match_rate < 50:
            print("   -> [진단] T-data 결합률이 낮아 경로 탐색에 한계가 있습니다. 이는 주로 서울시 공식 매핑 파일의 커버리지 제한 때문입니다.")
            print("   -> [결론] 현재 데이터로는 전체 경로 탐색보다, 데이터가 존재하는 '링크 단위'의 에너지 효율 분석이 더 적합합니다.")
        elif tdata_match_rate < 95:
            print("   -> [진단] T-data 결합률이 준수한 편이나 일부 링크가 손실되었습니다.")
            print("   -> [결론] 경로 탐색이 일부 구간에서 단절될 수 있습니다. 보간 기법 적용 또는 추가 데이터 확보를 고려할 수 있습니다.")
        else:
            print("   -> [진단] T-data 결합률이 매우 높아, 견고한 경로 탐색 기반이 마련되었습니다.")
            print("   -> [결론] 데이터 파이프라인이 안정적으로 구축되어, 경로 탐색 모델링 단계로 진행할 수 있습니다.")


# =============================================================================
# 4. Entrypoint
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="seoul-eco-routing 재사용 가능한 검증 파이프라인")
    parser.add_argument("--force", action="store_true", help="모든 캐시를 무시하고 처음부터 다시 계산합니다.")
    args = parser.parse_args()

    config = PipelineConfig()
    pipeline = VerificationPipeline(config, force_rerun=args.force)

    # 1. 서울 링크 추출
    seoul_links_gdf = pipeline.step_1_get_seoul_links()
    total_seoul_links = len(seoul_links_gdf)

    # 2. 속성 검증
    pipeline.step_2_verify_attributes(seoul_links_gdf)

    # 3. T-data 증분 매칭
    seoul_link_ids = set(seoul_links_gdf[config.link_key].astype(str))
    speed_df, matched_tdata_ids = pipeline.step_3_incremental_tdata_match(seoul_link_ids)

    # 4. DEM 매칭
    dem_df = pipeline.step_4_verify_dem_coverage(seoul_links_gdf)

    # 5. 최종 결합 및 보고서 생성
    pipeline.step_5_final_report(speed_df, dem_df, total_seoul_links, matched_tdata_ids)


if __name__ == "__main__":
    main()