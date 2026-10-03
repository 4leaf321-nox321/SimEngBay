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

from app.core.probes import FAR_MM, Spot, body_of, row, wanted

logger = logging.getLogger(__name__)

__all__ = ["FAR_MM", "Spot", "locate", "read", "rows", "scale_for", "topology_of", "wanted"]

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


def locate(topology: dict[str, Any], mesh: Any, *, scale: float = 1.0) -> list[Spot]:
    """측정점마다 **가장 가까운 절점** — 한 번 찾아 두고 값(모드 · 주파수)마다 다시 쓴다.

    `scale` 은 좌표의 단위를 mm 로 옮기는 곱수다: **CAD 의 점 좌표는 늘 mm** 인데(CompCore
    계약) 해석이 SI 로 돌면 메시 좌표가 m 다. 그 둘을 같은 자로 재야 가장 가까운 절점이 맞는다.

    지문에 `body` 가 있으면 **그 바디의 절점 안에서만** 찾는다 — 같은 자리에 두 바디의 꼭짓점이
    겹치는 이음 입구에서, 안 가르면 두 측정점이 같은 절점을 잡아 미끄럼이 늘 0 이 된다.
    """
    asked = wanted(topology)
    if not asked:
        return []
    try:
        import numpy as np

        places = np.asarray(mesh.nodes.coordinates_field.data, dtype=float).reshape(-1, 3)
        ids = np.asarray(mesh.nodes.scoping.ids, dtype=int)
    except Exception:  # pragma: no cover - DPF 없이는 안 돈다
        logger.warning("측정점을 못 찾았습니다 — 없이 갑니다", exc_info=True)
        return []
    owners = body_nodes(mesh, topology) if any(body_of(topology, one) for one in asked) else {}

    found: list[Spot] = []
    for name, point in asked.items():
        body = body_of(topology, name)
        mask = np.ones(len(ids), dtype=bool)
        if body is not None and body in owners:
            mask = np.isin(ids, np.fromiter(owners[body], dtype=int))
        if not mask.any():
            continue
        target = np.asarray(point, dtype=float) / scale
        gaps = np.where(mask, np.linalg.norm(places - target, axis=1), np.inf)
        index = int(gaps.argmin())
        found.append(
            Spot(
                name=name,
                point=point,
                node=int(ids[index]),
                distance_mm=float(gaps[index]) * scale,
                body=body if body in owners else None,
            )
        )
    return found


def rows(
    spots: list[Spot], values: Any, *, unit: str, strains: Any = None
) -> list[dict[str, Any]]:
    """잡아 둔 자리에서 DPF 필드의 값을 읽어 한 줄씩.

    벡터장이면 크기와 **성분**, 스칼라장이면 절댓값 — 변위는 전자, 응력은 후자다. 값이 없는
    절점이면 그 점을 건너뛴다(0 으로 적으면 「안 움직였다」 로 읽힌다).
    """
    if not spots:
        return []
    try:
        import numpy as np

        data = np.asarray(values.data, dtype=float)
        value_ids = np.asarray(values.scoping.ids, dtype=int)
    except Exception:  # pragma: no cover - DPF 없이는 안 돈다
        logger.warning("측정점을 못 읽었습니다 — 없이 갑니다", exc_info=True)
        return []
    size = np.linalg.norm(data, axis=1) if data.ndim == 2 else np.abs(data)
    index_of = {int(node): index for index, node in enumerate(value_ids.tolist())}
    # 변형률장(절점 평균, 성분 XX · YY · ZZ · XY · YZ · XZ) — **수직 셋만** 쓴다.
    normal: dict[int, list[float]] = {}
    if strains is not None:
        try:
            strain_ids = np.asarray(strains.scoping.ids, dtype=int).tolist()
            strain_data = np.asarray(strains.data, dtype=float).reshape(-1, 6)
            for node, one in zip(strain_ids, strain_data, strict=False):
                normal[int(node)] = one[:3].tolist()
        except Exception:  # pragma: no cover - DPF 없이는 안 돈다
            logger.warning("측정점 변형률을 못 읽었습니다 — 없이 갑니다", exc_info=True)

    made: list[dict[str, Any]] = []
    for spot in spots:
        index = index_of.get(spot.node)
        if index is None:
            logger.warning("측정점 %s: 절점 %s 에 값이 없습니다", spot.name, spot.node)
            continue
        made.append(
            row(
                name=spot.name,
                point=spot.point,
                node=spot.node,
                distance_mm=spot.distance_mm,
                value=float(size[index]),
                unit=unit,
                vector=data[index].tolist() if data.ndim == 2 else None,
                body=spot.body,
                strain=normal.get(spot.node),
            )
        )
    return made


def read(
    topology: dict[str, Any],
    mesh: Any,
    values: Any,
    *,
    unit: str,
    scale: float = 1.0,
    strains: Any = None,
) -> list[dict[str, Any]]:
    """측정점마다 `{이름, 좌표, 값, 성분, 절점, 떨어진 거리, 바디}` — `locate` 와
    `rows` 를 한 번에. 점 그룹이 없으면 빈 목록."""
    return rows(locate(topology, mesh, scale=scale), values, unit=unit, strains=strains)


def body_nodes(mesh: Any, topology: dict[str, Any]) -> dict[str, set[int]]:
    """바디 이름 → **그 바디의 절점** — DPF 메시에서 되찾는다.

    Mechanical 은 바디마다 재료 번호를 따로 매긴다(덱의 `MAT,1` · `MAT,2` …). 그래서 요소를
    재료 번호로 묶으면 바디가 갈리고, 각 묶음의 절점 중심을 CAD 의 바디 중심
    (`bodies[].centroid`)과 견주면 이름이 붙는다 — CalculiX 쪽은 모델링이 남긴 짝을 쓰지만
    여기는 그것이 없다.

    접촉 요소도 제 재료 번호를 가지는데, 그 중심은 **이음면 위**라 어느 바디 중심과도 멀다 —
    바디마다 가장 가까운 묶음을 고르면 저절로 빠진다. 무엇이든 실패하면 빈 것을 준다(그때는
    전체에서 찾는다 — 바디를 못 가른다는 사실은 측정점 줄의 `body` 가 없는 것으로 드러난다).
    """
    bodies = [
        one
        for one in (topology.get("bodies") or [])
        if isinstance(one, dict) and isinstance(one.get("centroid"), list)
    ]
    if len(bodies) < 2:
        return {}
    try:
        import numpy as np

        materials = mesh.elements.materials_field
        element_ids = np.asarray(materials.scoping.ids, dtype=int)
        material_of = np.asarray(materials.data, dtype=int)
        places = np.asarray(mesh.nodes.coordinates_field.data, dtype=float).reshape(-1, 3)
        node_ids = np.asarray(mesh.nodes.scoping.ids, dtype=int)
        index_of = {int(node): index for index, node in enumerate(node_ids)}
        groups: dict[int, set[int]] = {}
        for element, material in zip(element_ids.tolist(), material_of.tolist(), strict=False):
            ids = mesh.elements.element_by_id(int(element)).node_ids
            groups.setdefault(int(material), set()).update(int(one) for one in ids)
        scale = scale_for(str(mesh.unit or ""))
    except Exception:  # pragma: no cover - DPF 없이는 안 돈다
        logger.warning(
            "바디별 절점을 못 갈랐습니다 — 측정점을 전체에서 찾습니다", exc_info=True
        )
        return {}

    centers = {
        material: places[[index_of[node] for node in members if node in index_of]].mean(axis=0)
        * scale
        for material, members in groups.items()
        if members
    }
    found: dict[str, set[int]] = {}
    for body in bodies:
        target = np.asarray(body["centroid"], dtype=float)
        best = min(centers, key=lambda one: float(np.linalg.norm(centers[one] - target)))
        found[str(body.get("name") or "")] = groups[best]
    return found


def reaction(
    model: Any, mesh: Any, region: dict[str, Any], *, tolerance_mm: float = 1e-3
) -> list[float] | None:
    """그 면의 **반력 합** `[Fx, Fy, Fz]`. 면은 CAD 지문(`centroid` · `normal`)으로 찾는다.

    반력은 구속된 절점에만 있으므로, 그 **평면 위에 있는 절점**의 반력을 더하면 그 구속이 버틴
    힘이다. 같은 평면에 다른 구속이 있으면 함께 더해진다 — 그때는 요소 크기만큼 넓은 면을
    따로 가르거나, 그 사실을 적어야 한다(지금 폴더들에는 그런 자리가 없다).
    """
    centroid, normal = region.get("centroid"), region.get("normal")
    if not (isinstance(centroid, list) and isinstance(normal, list)):
        return None
    try:
        import numpy as np

        field = model.results.reaction_force.eval()[0]
        places = np.asarray(mesh.nodes.coordinates_field.data, dtype=float).reshape(-1, 3)
        node_ids = np.asarray(mesh.nodes.scoping.ids, dtype=int)
        scale = scale_for(str(mesh.unit or ""))
        unit = np.asarray(normal, dtype=float)
        unit = unit / np.linalg.norm(unit)
        offsets = (places * scale - np.asarray(centroid, dtype=float)) @ unit
        on_plane = set(node_ids[np.abs(offsets) < tolerance_mm].tolist())
        ids = np.asarray(field.scoping.ids, dtype=int)
        data = np.asarray(field.data, dtype=float).reshape(-1, 3)
    except Exception:  # pragma: no cover - DPF 없이는 안 돈다
        logger.warning("반력을 못 읽었습니다", exc_info=True)
        return None
    total = np.zeros(3)
    for node, force in zip(ids.tolist(), data, strict=False):
        if node in on_plane:
            total += force
    return [round(float(one), 6) for one in total]
