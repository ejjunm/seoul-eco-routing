"""
[실험용] 지정한 시간대(기본: 08시, 18시, 23시)에 대해
다단계 기상 상태 판정 알고리즘을 적용하여 결과를 시각적으로 출력합니다.

사용법: python experiments/check_rainy_times.py
"""
from pathlib import Path
import re
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RADAR_DIR = PROJECT_ROOT / "data" / "raw" / "weather" / "radar"

# 🎯 확인하고 싶은 특정 시간대(Hour) 지정 (08시, 18시, 23시)
TARGET_HOURS = {"08", "18", "23"}

def parse_kma_ascii_grid(path: Path) -> np.ndarray:
    """KMA 레이더 ASCII 그리드 파일 파싱"""
    text = path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    values = re.findall(r"-?\d+(?:\.\d+)?", "\n".join(lines))
    if len(values) < 3:
        return None
    width, height = int(values[0]), int(values[1])
    data = np.array(values[2:], dtype=np.float32)
    if data.size != width * height:
        return None
    return data.reshape(height, width)

def classify_weather(valid_precip: np.ndarray) -> tuple[str, float, float, float]:
    """
    서울시 전역 강수 배열을 바탕으로 다단계 날씨 상태 및 주요 통계치 반환
    """
    if len(valid_precip) == 0:
        return "☀️ 맑음 (데이터 없음)", 0.0, 0.0, 0.0

    mean_rain = float(np.mean(valid_precip))
    p90_rain = float(np.percentile(valid_precip, 90))
    # 비가 0.1mm 초과로 내리는 링크 비율(%)
    rain_link_ratio = float((np.sum(valid_precip > 0.1) / len(valid_precip)) * 100)

    # --- 다단계 날씨 상태 판정 ---
    if mean_rain >= 1.0 or (rain_link_ratio >= 30.0 and p90_rain >= 2.0):
        weather_status = "🌧️ 비 옴 (광범위/집중)"
    elif mean_rain >= 0.1 or rain_link_ratio >= 10.0:
        weather_status = "🌦️ 약한 비 / 국소 강수"
    else:
        weather_status = "☀️ 맑음 (무강수/노이즈)"

    return weather_status, mean_rain, rain_link_ratio, p90_rain

def main():
    if not RADAR_DIR.exists():
        print(f"❌ 레이더 디렉토리를 찾을 수 없습니다: {RADAR_DIR}")
        return

    radar_files = sorted(RADAR_DIR.glob("hsr_pcph_acc60_*.txt"))
    if not radar_files:
        print(f"⚠️ {RADAR_DIR} 폴더에 레이더 TXT 파일이 없습니다.")
        return

    # 정돈된 헤더 출력
    header = f"{'날짜 및 시각 (tm)':^18} | {'판정 기상 상태':^22} | {'평균 강수량':^10} | {'강수 링크 비율':^12} | {'상위 10% 강수량':^12}"
    divider = "─" * len(header)
    
    print("\n" + "═" * len(header))
    print(" ☔ 서울시 레이더 다단계 강수 상태 분석 리포트 (08시 / 18시 / 23시)")
    print("═" * len(header))
    print(header)
    print(divider)

    checked_count = 0
    status_summary = {"🌧️ 비 옴 (광범위/집중)": 0, "🌦️ 약한 비 / 국소 강수": 0, "☀️ 맑음 (무강수/노이즈)": 0}

    for file_path in radar_files:
        tm_match = re.search(r"\d{12}", file_path.name)
        if not tm_match:
            continue
        tm = tm_match.group(0)
        hour = tm[8:10]

        if hour not in TARGET_HOURS:
            continue

        checked_count += 1
        formatted_time = f"{tm[:4]}-{tm[4:6]}-{tm[6:8]} {hour}:00"

        grid = parse_kma_ascii_grid(file_path)
        if grid is None:
            continue

        raw = grid.reshape(-1)
        precip = raw.astype(np.float32) / 100.0  # 0.01mm -> mm 변환
        precip[raw < 0] = 0.0                     # 무에코 0mm
        precip[raw <= -30000] = np.nan            # 관측 영역 밖 NaN

        valid_precip = precip[~np.isnan(precip)]
        
        # 다단계 상태 판정
        status, mean_rain, ratio, p90_rain = classify_weather(valid_precip)
        
        if status in status_summary:
            status_summary[status] += 1

        print(f" {formatted_time:^18} | {status:<22} | {mean_rain:8.2f} mm | {ratio:10.1f} % | {p90_rain:10.2f} mm")

    print(divider)
    print(f"📊 총 검사 시각: {checked_count}개")
    for st_name, count in status_summary.items():
        print(f"   • {st_name}: {count}개 시각")
    print("═" * len(header) + "\n")

if __name__ == "__main__":
    main()