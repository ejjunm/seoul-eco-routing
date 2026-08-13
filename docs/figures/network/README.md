# 서울 전 도로망 실루엣

| 파일 | 데이터 | 의미 |
| --- | --- | --- |
| `01_seoul_all_links_silhouette.png` | `data/interim/seoul_link.shp`의 방향성 링크 63,548개 | 속도·에너지 값 없이 서울 행정경계와 교차하는 전체 도로망의 공간 범위와 연결 밀도를 보여 주는 기본 지도 |

링크는 `F_NODE → T_NODE` 방향 간선이므로, 양방향 도로는 두 개 이상의 선이 겹쳐 보일 수 있다. 연한 외곽선은 서울 행정경계이며, 경계와 교차하는 링크 전체를 포함하는 정의라 일부 외곽 링크가 경계 밖으로 뻗어 보일 수 있다.

재생성 명령:

```powershell
python src/eda/05_plot_network_silhouette.py
```
