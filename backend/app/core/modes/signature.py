"""모드 지문 — **설계점 사이에서 같은 모드를 잇기 위한 것.**

## 왜 필요한가

비교 화면은 「1차 · 2차」 를 **순번**으로 견준다. 그런데 치수가 바뀌면 모드 순서가 뒤바뀐다 —
굽힘은 두께에 크게 오르고 비틀림은 덜 오르기 때문이다(mode crossing). 실측(브래킷 두께 훑기):

    두께  6 → 1336, 1698, 2238, 3045 Hz
    두께 12 → 1651, 3313, 3613, 4706 Hz     ← 2차가 두 배. 같은 모드인가?

순번으로 이으면 「2차 대 두께」 가 **서로 다른 모드를 이은 선**이 되고, 그것은 조용히 틀린
그림이다. 모드를 잇는 정본은 주파수가 아니라 **형상**이다.

## 왜 격자에서 뽑나

설계점마다 메시가 다르다(절점 수 · 위치가 전부 다르다). 그래서 절점끼리 곧바로 견줄 수 없다.
**경계상자를 정규화한 격자**에서 가장 가까운 절점의 변위를 뽑으면, 치수가 달라도 「같은 자리」
를 견줄 수 있다. 두께가 두 배인 형상도 정규화 좌표에서는 같은 자리다.

## 왜 결과 파일에 싣나

지문을 만드는 데는 메시와 변위가 필요하고 그것은 워커에만 있다. 반면 **잇는 계산은 서버가
한다** — 그래서 만들 때 한 번 뽑아 `result.json` 에 싣고, 그 뒤로는 산술만 한다. 모드당 실수
`3 x GRID^3` 개(≈192개, 1.5KB)다.

## 왜 여기 있나

**두 솔버가 같은 규칙으로 뽑아야 한다**(2026-10-24). 처음에는 Ansys 쪽(`core/dpf/signature.py`)
에만 있었고, CalculiX 가 기본 솔버가 된 뒤로 새 모달 DOE 의 「모드 지도」 가 늘 비었다. 칸
가운데 · 순서 · 정규화가 이 파일 하나에 있어야 한 DOE 에 두 솔버가 섞여도 지문끼리 견줄 수
있다. numpy 없이 돈다 — CalculiX 워커에는 numpy 가 없다. Ansys 쪽은 가장 가까운 절점 찾기만
numpy 로 빨리 하고 나머지는 여기 것을 쓴다.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

#: 한 변을 몇 칸으로 나누나. 4면 64칸 · 모드당 192개 실수 — 형상을 가르기에 충분하고
#: 결과 파일을 무겁게 하지 않는다.
GRID = 4


def centers(low: Sequence[float], high: Sequence[float]) -> list[tuple[float, float, float]]:
    """경계상자를 `GRID` 칸씩 나눈 **칸 가운데**의 실제 좌표. 순서는 x · y · z 의 겹 고리다.

    두께가 0 인 축(판을 평면으로 그린 경우)은 폭을 1 로 둔다 — 모든 칸이 그 평면 위에 놓인다.
    """
    span = [float(top) - float(bottom) for bottom, top in zip(low, high, strict=True)]
    span = [one if one > 0 else 1.0 for one in span]
    origin = [float(one) for one in low]
    found: list[tuple[float, float, float]] = []
    for ix in range(GRID):
        for iy in range(GRID):
            for iz in range(GRID):
                found.append(
                    (
                        origin[0] + span[0] * (ix + 0.5) / GRID,
                        origin[1] + span[1] * (iy + 0.5) / GRID,
                        origin[2] + span[2] * (iz + 0.5) / GRID,
                    )
                )
    return found


def anchors(points: Sequence[Sequence[float]]) -> list[int]:
    """칸 가운데마다 **가장 가까운 점의 순번**(`points` 안에서). 메시 하나에 한 번만 찾고
    모드마다 다시 쓴다 — 모드가 바뀌어도 메시는 같다."""
    if not points:
        raise ValueError("점이 없습니다")
    low = [min(one[axis] for one in points) for axis in range(3)]
    high = [max(one[axis] for one in points) for axis in range(3)]
    return [_nearest(points, target) for target in centers(low, high)]


def _nearest(points: Sequence[Sequence[float]], target: tuple[float, float, float]) -> int:
    x, y, z = target
    best, found = float("inf"), 0
    for index, point in enumerate(points):
        far = (point[0] - x) ** 2 + (point[1] - y) ** 2 + (point[2] - z) ** 2
        # **같으면 앞의 것**(`<`) — numpy 의 argmin 과 같은 규칙이라 두 솔버가 같은 점을
        # 고른다.
        if far < best:
            best, found = far, index
    return found


def fingerprint(rows: Iterable[Sequence[float]]) -> list[float]:
    """칸마다 고른 점의 변위(x · y · z)를 이어 붙여 **단위 길이로** — 그것이 지문이다.

    **크기를 지운다** — 모달 변위는 질량 정규화된 상대값이다.
    """
    picked = [float(one) for row in rows for one in row[:3]]
    length = sum(one * one for one in picked) ** 0.5
    if length <= 0:
        return [0.0] * len(picked)
    return [round(one / length, 6) for one in picked]
