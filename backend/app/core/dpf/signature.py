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

지문을 만드는 데는 메시와 변위가 필요하고 그것은 워커(DPF · numpy)에만 있다. 반면 **잇는
계산은 서버가 한다** — 그래서 만들 때 한 번 뽑아 `result.json` 에 싣고, 그 뒤로는 산술만 한다.
모드당 실수 `3 x GRID^3` 개(≈192개, 1.5KB)다.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: 한 변을 몇 칸으로 나누나. 4면 64칸 · 모드당 192개 실수 — 형상을 가르기에 충분하고
#: 결과 파일을 무겁게 하지 않는다.
GRID = 4


def sample(mesh: Any, vectors: Any) -> list[float]:
    """정규화 격자에서 뽑은 변위 지문.

    **크기를 지운다**(단위 벡터) — 모달 변위는 질량 정규화된 상대값이다.
    """
    import numpy as np

    nodes = np.asarray(mesh.nodes.coordinates_field.data, dtype=float).reshape(-1, 3)
    values = np.asarray(vectors, dtype=float).reshape(-1, 3)
    if len(nodes) == 0 or len(values) != len(nodes):
        # **변위는 메시 절점 순서로 맞춰서 넘긴다**(`core/dpf/fields.py`). 순서가 다른 채로
        # 들어오면 지문이 조용히 틀리고, 그 지문은 설계점 사이의 모드를 엉뚱하게 잇는다.
        raise ValueError(f"절점 {len(nodes)} 개와 변위 {len(values)} 개가 맞지 않습니다")

    low, high = nodes.min(axis=0), nodes.max(axis=0)
    span = np.where(high - low > 0, high - low, 1.0)

    picked: list[float] = []
    for ix in range(GRID):
        for iy in range(GRID):
            for iz in range(GRID):
                # 칸 가운데의 정규화 좌표 → 실제 좌표
                target = low + span * ((np.array([ix, iy, iz]) + 0.5) / GRID)
                index = int(np.argmin(((nodes - target) ** 2).sum(axis=1)))
                picked.extend(float(one) for one in values[index])

    length = float(np.sqrt(sum(one * one for one in picked)))
    if length <= 0:
        return [0.0] * len(picked)
    return [round(one / length, 6) for one in picked]
