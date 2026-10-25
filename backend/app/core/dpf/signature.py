"""모드 지문 — Ansys 쪽. **규칙은 `core/modes/signature.py` 에 있다**(왜 · 어떻게).

여기는 DPF 메시에서 좌표를 꺼내 가장 가까운 절점을 numpy 로 빨리 찾는 일만 한다. 칸 가운데 ·
순서 · 정규화는 CalculiX 쪽과 같은 함수를 쓴다 — 한 DOE 에 두 솔버가 섞여도 지문끼리 견준다.
"""

from __future__ import annotations

from typing import Any

from app.core.modes.signature import centers, fingerprint


def sample(mesh: Any, vectors: Any) -> list[float]:
    """정규화 격자에서 뽑은 변위 지문."""
    import numpy as np

    nodes = np.asarray(mesh.nodes.coordinates_field.data, dtype=float).reshape(-1, 3)
    values = np.asarray(vectors, dtype=float).reshape(-1, 3)
    if len(nodes) == 0 or len(values) != len(nodes):
        # **변위는 메시 절점 순서로 맞춰서 넘긴다**(`core/dpf/fields.py`). 순서가 다른 채로
        # 들어오면 지문이 조용히 틀리고, 그 지문은 설계점 사이의 모드를 엉뚱하게 잇는다.
        raise ValueError(f"절점 {len(nodes)} 개와 변위 {len(values)} 개가 맞지 않습니다")

    targets = centers(nodes.min(axis=0), nodes.max(axis=0))
    picked = [int(np.argmin(((nodes - np.asarray(one)) ** 2).sum(axis=1))) for one in targets]
    return fingerprint(values[index] for index in picked)
