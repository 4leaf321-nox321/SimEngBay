"""표면 그림의 **파트 나누기** — 3D 뷰어가 파트마다 보이기 · 숨기기를 한다(2026-10-05).

그러려면 그림(VTP)의 면마다 **어느 파트인가**가 있어야 한다. 셀 배열 `part`(정수, 0 부터)에
적고, 그 번호의 이름은 결과의 `parts` 목록에 적는다. 화면은 배열이 없으면(이 기능 전에 만든
그림) 이어진 덩어리로 스스로 나눈다(`shared/viewer/MeshViewer.tsx`).

## 두 솔버가 다른 길로 안다

- **CalculiX** — 메시가 바디(기하 부피)마다 사면체를 안다. 표면 삼각형이 **어느 바디의 사면체
  면인가**로 정한다(`owners_by_solid`). 두 바디가 맞닿은 면은 둘 다의 것이다 — 한쪽을 숨기면
  다른 쪽의 겉면으로 보인다. 쉘 파트는 중간면의 기하 면 번호로 안다.
- **Ansys** — 표면만 온다. **서로 이어지지 않은 덩어리가 바디다**(접합해도 바디끼리 절점을
  나누지 않는다 — `components`). 덩어리마다 부피 · 무게중심을 재 CAD 의 바디 지문과 짝지어
  이름을 붙인다(`match_bodies` — 모델링이 물성을 붙일 때와 같은 규칙). 못 짝지으면
  「파트 N」 이다. 틀린 이름을 붙이느니 번호로 부른다.

**그림을 못 나눠도 해석은 끝난 것이다** — 부르는 쪽이 실패를 삼키고 나누지 않은 그림을 쓴다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.core.bodies import BodyRecord, match_bodies


def owners_by_solid(
    solids: dict[int, list[tuple[int, list[int]]]],
    triangles: Sequence[tuple[int, int, int]],
) -> list[list[int]]:
    """표면 삼각형마다 그 면을 가진 바디(기하 부피 번호)들. 없으면 빈 목록.

    사면체 면을 전부 사전에 넣지 않는다 — 50만 요소면 200만 개다. **표면 삼각형의 열쇠만**
    먼저 모으고, 사면체를 훑으며 그 열쇠에 닿는 면만 적는다.
    """
    keys = {tuple(sorted(one)) for one in triangles}
    found: dict[tuple[int, ...], list[int]] = {}
    for entity, rows in solids.items():
        for _, ids in rows:
            a, b, c, d = ids[:4]
            for face in ((a, b, c), (a, b, d), (a, c, d), (b, c, d)):
                key = tuple(sorted(face))
                if key in keys:
                    owners = found.setdefault(key, [])
                    if entity not in owners:
                        owners.append(entity)
    return [found.get(tuple(sorted(one)), []) for one in triangles]


def components(cells: Sequence[Sequence[int]], point_count: int) -> list[int]:
    """면마다 이어진 덩어리 번호. **큰 덩어리(면 수)부터 0, 1, …** — 같으면 먼저 나온 것부터.

    점을 나누는 면끼리 한 덩어리다(합집합-찾기).
    """
    parent = list(range(point_count))

    def root(one: int) -> int:
        while parent[one] != one:
            parent[one] = parent[parent[one]]
            one = parent[one]
        return one

    for cell in cells:
        if not cell:
            continue
        first = root(cell[0])
        for other in cell[1:]:
            top = root(other)
            if top != first:
                parent[top] = first
    raw = [root(cell[0]) if cell else -1 for cell in cells]
    sizes: dict[int, int] = {}
    seen: dict[int, int] = {}
    for index, label in enumerate(raw):
        sizes[label] = sizes.get(label, 0) + 1
        seen.setdefault(label, index)
    order = sorted(sizes, key=lambda label: (-sizes[label], seen[label]))
    renumber = {label: index for index, label in enumerate(order)}
    return [renumber[label] for label in raw]


def body_records(
    points: Sequence[Sequence[float]],
    cells: Sequence[Sequence[int]],
    labels: Sequence[int],
    *,
    to_mm: float,
) -> list[BodyRecord]:
    """덩어리마다 부피 · 무게중심(mm) — 닫힌 겉면이면 원점과 이은 사면체의 합이 부피다.

    다각형은 부채꼴로 쪼갠다. 열린 면(쉘)은 부피가 0 에 가까워 기록을 안 낸다 — 짝지을 수 없다.
    """
    volume: dict[int, float] = {}
    moment: dict[int, list[float]] = {}
    for cell, label in zip(cells, labels, strict=True):
        if len(cell) < 3:
            continue
        a = points[cell[0]]
        for index in range(1, len(cell) - 1):
            b = points[cell[index]]
            c = points[cell[index + 1]]
            signed = (
                a[0] * (b[1] * c[2] - b[2] * c[1])
                - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0])
            ) / 6.0
            volume[label] = volume.get(label, 0.0) + signed
            sums = moment.setdefault(label, [0.0, 0.0, 0.0])
            for axis in range(3):
                sums[axis] += signed * (a[axis] + b[axis] + c[axis]) / 4.0
    records: list[BodyRecord] = []
    for label, total in sorted(volume.items()):
        if abs(total) <= 0:
            continue
        center = tuple(one / total * to_mm for one in moment[label])
        records.append(
            BodyRecord(
                index=label,
                volume=abs(total) * to_mm**3,
                centroid=center,  # type: ignore[arg-type]
            )
        )
    return records


def names_for(
    count: int, records: list[BodyRecord], topology: dict[str, Any] | None
) -> list[str]:
    """덩어리 번호마다 이름 — CAD 바디 지문과 짝지은 것은 그 이름, 아니면 「파트 N」."""
    out = [f"파트 {index + 1}" for index in range(count)]
    if topology:
        for name, index in match_bodies(topology, records).bodies.items():
            if 0 <= index < count:
                out[index] = name
    return out
