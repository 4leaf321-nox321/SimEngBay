"""DPF 필드를 **메시 절점 순서로** 맞춘다 — 이 규칙을 두 곳에 적지 않는다.

**실측(2026-09-20)**: 메시의 절점 순서는 1 · 2 · 3 … 인데 변위 필드의 순서는 1 · 137 · 129 …
였다. 순서대로 붙이면 값이 엉뚱한 절점에 붙는데, **그것은 오류로 드러나지 않는다** — 모드
형상이 뒤죽박죽인 그림이 되고(그림은 원래 낯설다), 모드 지문은 조용히 틀린 값이 되어 설계점
사이의 모드를 엉뚱하게 잇는다.

그래서 필드를 쓰는 자리는 전부 여기를 지난다.
"""

from __future__ import annotations

from typing import Any


def ordered_by(node_ids: Any, field: Any) -> Any:
    """`node_ids` 순서에 맞춘 (n, 3) 배열. 값이 없는 절점은 0 이다."""
    import numpy as np

    wanted = np.asarray(node_ids)
    source = np.asarray(field.scoping.ids)
    values = np.asarray(field.data, dtype=float).reshape(-1, 3)

    lookup = np.full(int(max(source.max(), wanted.max())) + 1, -1, dtype=np.int64)
    lookup[source] = np.arange(len(source))
    picked = lookup[wanted]

    out = np.zeros((len(wanted), 3), dtype=float)
    found = picked >= 0
    out[found] = values[picked[found]]
    return out
