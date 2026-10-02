"""**측정점** — Ansys 쪽. CAD 가 보낸 점 그룹에서 값을 읽는다.

CalculiX 쪽(`app/core/calculix/probes.py`)과 **같은 모양을 낸다** — 화면과 보고서가 솔버를
가리지 않고 같은 열쇠를 읽어야 하고, 두 솔버의 값을 그 자리에서 견줄 수 있어야 한다. 다른 것은
절점과 값을 어디서 얻느냐뿐이다(DPF 대 `.frd`).

점 그룹은 구속이나 하중을 걸 자리가 아니라 **값을 읽을 자리**다 — 실험에서 센서를 붙인 그
지점이고, 해석과 실측을 견주는 유일한 공통 좌표다. 전체 최대로는 그 비교를 못 한다: 최대는
모델 어디에서든 날 수 있고(구속 모서리의 수치적 첨두가 흔하다) 센서는 그 자리에 없다.

**가장 가까운 절점을 쓰고 거리도 적는다.** 메시 절점이 그 좌표에 정확히 있을 이유는 없다 —
멀면 그 값은 다른 자리의 값이므로 사람이 판단할 수 있게 거리를 남긴다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.probes import FAR_MM, row, wanted

logger = logging.getLogger(__name__)

__all__ = ["FAR_MM", "read", "scale_for", "topology_of", "wanted"]

TOPOLOGY_NAME = "topology.json"


def topology_of(workdir: Path) -> dict[str, Any]:
    """작업 폴더의 점 파일. **없거나 깨져도 해석은 끝난 것이다** — 빈 것을 준다."""
    path = workdir / TOPOLOGY_NAME
    if not path.is_file():
        return {}
    try:
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("%s 를 읽지 못했습니다 — 측정점 없이 갑니다", TOPOLOGY_NAME)
        return {}
    return loaded


def scale_for(unit: str) -> float:
    """결과 단위 → **CAD 의 점 좌표(mm)를 메시 좌표로 옮기는 곱수.**

    CAD 는 점을 늘 mm 로 보낸다(CompCore 계약). 해석이 SI 로 돌면 메시 좌표가 m 이므로, 같은
    자로 재지 않으면 **가장 가까운 절점이 엉뚱한 자리**로 잡힌다(1000배 차이다).
    """
    return 1000.0 if unit.strip().lower() in ("m", "meter", "metre") else 1.0


def read(
    topology: dict[str, Any],
    mesh: Any,
    values: Any,
    *,
    unit: str,
    scale: float = 1.0,
) -> list[dict[str, Any]]:
    """측정점마다 `{이름, 좌표, 값, 절점, 떨어진 거리}`. 점 그룹이 없으면 빈 목록.

    `values` 는 DPF 의 필드(변위 등)다 — 절점 번호로 값을 꺼낸다. `scale` 은 좌표의 단위를
    mm 로 옮기는 곱수다: **CAD 의 점 좌표는 늘 mm** 인데(CompCore 계약) 해석이 SI 로 돌면 메시
    좌표가 m 다. 그 둘을 같은 자로 재야 가장 가까운 절점이 맞는다.
    """
    asked = wanted(topology)
    if not asked:
        return []
    try:
        import numpy as np

        places = np.asarray(mesh.nodes.coordinates_field.data, dtype=float).reshape(-1, 3)
        ids = np.asarray(mesh.nodes.scoping.ids, dtype=int)
        data = np.asarray(values.data, dtype=float)
        value_ids = np.asarray(values.scoping.ids, dtype=int)
    except Exception:  # pragma: no cover - DPF 없이는 안 돈다
        logger.warning("측정점을 못 읽었습니다 — 없이 갑니다", exc_info=True)
        return []

    # 벡터장이면 크기, 스칼라장이면 절댓값 — 변위는 전자, 응력은 후자다.
    size = np.linalg.norm(data, axis=1) if data.ndim == 2 else np.abs(data)
    by_node = dict(zip(value_ids.tolist(), size.tolist(), strict=False))

    made: list[dict[str, Any]] = []
    for name, point in asked.items():
        target = np.asarray(point, dtype=float) / scale
        gaps = np.linalg.norm(places - target, axis=1)
        index = int(gaps.argmin())
        node = int(ids[index])
        if node not in by_node:
            logger.warning("측정점 %s: 절점 %s 에 값이 없습니다", name, node)
            continue
        distance = float(gaps[index]) * scale
        made.append(
            row(
                name=name,
                point=point,
                node=node,
                distance_mm=distance,
                value=by_node[node],
                unit=unit,
            )
        )
    return made
