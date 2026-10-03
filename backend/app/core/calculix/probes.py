"""**측정점** — CAD 가 보낸 점 그룹에서 값을 읽는다.

CompCore 는 선택 그룹에 점(vertex)을 담아 보낸다(`{"point": [5, 5, 90]}`). 그 점은 구속이나
하중을 걸 자리가 아니라 **값을 읽을 자리**다 — 실험에서 센서를 붙인 그 지점이고, 그래서 해석과
실측을 견주는 유일한 공통 좌표다.

전체 최대만 보면 그 비교를 못 한다. 최대는 모델 어디에서든 날 수 있고(구속 모서리의 수치적
첨두가 흔하다), 센서는 그 자리에 없다. 그래서 **그 점의 값**을 따로 적는다.

## 가장 가까운 절점을 쓴다

메시 절점이 그 좌표에 정확히 있을 이유는 없다. 그래서 가장 가까운 절점을 찾고 **얼마나
떨어졌는지도 함께 적는다** — 멀면 그 값은 다른 자리의 값이다. 요소 안을 보간하면 더 정확하지만,
거리를 적어 두면 사람이 그 판단을 할 수 있고 거짓 정밀도도 안 생긴다.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from app.core.probes import FAR_MM, body_of, row, wanted

logger = logging.getLogger(__name__)

__all__ = ["FAR_MM", "nearest", "read", "wanted"]


def nearest(
    nodes: dict[int, tuple[float, float, float]], point: tuple[float, float, float]
) -> tuple[int, float] | None:
    """그 좌표에 가장 가까운 절점과 거리(mm)."""
    best: tuple[int, float] | None = None
    for node, place in nodes.items():
        distance = math.dist(place, point)
        if best is None or distance < best[1]:
            best = (node, distance)
    return best


def read(
    topology: dict[str, Any],
    nodes: dict[int, tuple[float, float, float]],
    values: dict[int, float],
    *,
    unit: str,
    vectors: dict[int, list[float]] | None = None,
    body_nodes: dict[str, set[int]] | None = None,
) -> list[dict[str, Any]]:
    """측정점마다 `{이름, 좌표, 값, 절점, 떨어진 거리}`. 점 그룹이 없으면 빈 목록.

    `values` 는 절점 → 값이다(변위 크기 · 응력 …). 값이 없는 절점이면 그 점을 건너뛴다 —
    0 으로 적으면 「그 자리는 안 움직였다」 로 읽힌다.

    `body_nodes` 를 주면 **그 측정점의 바디 안에서만** 찾는다(지문의 `body`). 같은 자리에 두
    바디의 꼭짓점이 겹치는 이음 입구에서, 안 가르면 두 측정점이 같은 절점을 잡아 미끄럼이 늘 0
    으로 나온다. `vectors` 를 주면 성분도 싣는다 — 미끄럼은 X 성분의 차다.
    """
    made: list[dict[str, Any]] = []
    for name, point in wanted(topology).items():
        body = body_of(topology, name)
        pool = nodes
        if body is not None and body_nodes and body in body_nodes:
            pool = {node: nodes[node] for node in body_nodes[body] if node in nodes}
        hit = nearest(pool, point)
        if hit is None:
            continue
        node, distance = hit
        if node not in values:
            logger.warning("측정점 %s: 절점 %s 에 값이 없습니다", name, node)
            continue
        made.append(
            row(
                name=name,
                point=point,
                node=node,
                distance_mm=distance,
                value=values[node],
                unit=unit,
                vector=(vectors or {}).get(node),
                body=body,
            )
        )
    return made
