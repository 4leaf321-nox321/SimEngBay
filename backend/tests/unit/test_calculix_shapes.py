"""메시에서 **면의 종류를 되맞추는가** — 평면 · 원통 · 구 · 원뿔.

조건은 면 번호로 오지 않는다. 평면은 `무게중심 · 면적 · 법선`, 곡면은 `반지름 · 축` 으로 온다
(CompCore 계약). Mechanical 은 형상을 들고 있어 그 둘을 바로 주지만, CalculiX 경로에는 메시만
있으므로 삼각형에서 되맞춘다 — 그 판정을 여기서 지킨다.

**합성 절점으로 시험한다.** 진짜 STEP 과 gmsh 가 필요 없는 부분이라 빠르게 돌고, 모양마다
「이런 면이면 이렇게 읽혀야 한다」 를 콕 집어 둘 수 있다. 끝까지 도는 것은
`tests/opensolver` 가 본다.
"""

from __future__ import annotations

import math

from app.core.bodies import BodyRecord
from app.core.calculix.mesh import Mesh, Probe, _classify, with_geometry
from app.core.regions import FaceRecord

Point = tuple[float, float, float]


def _mesh(
    rings: list[list[Point]], *, closed: bool
) -> tuple[dict[int, Point], list[tuple[int, int, int]], set[int]]:
    """고리(한 줄의 점들) 사이를 삼각형으로 잇는다.

    **일직선 점 셋으로 삼각형을 만들면 법선이 0 이라 판정이 아예 안 된다** — 그래서 격자
    모양을 그대로 살려 사각형을 둘로 나눈다. `closed` 면 마지막 점과 첫 점도 잇는다(원통 · 구).
    """
    nodes: dict[int, Point] = {}
    for ring in rings:
        for point in ring:
            nodes[len(nodes) + 1] = point
    width = len(rings[0])
    triangles: list[tuple[int, int, int]] = []
    for row in range(len(rings) - 1):
        span = width if closed else width - 1
        for column in range(span):
            next_column = (column + 1) % width
            a = row * width + column + 1
            b = row * width + next_column + 1
            c = (row + 1) * width + column + 1
            d = (row + 1) * width + next_column + 1
            triangles.append((a, b, c))
            triangles.append((b, d, c))
    return nodes, triangles, set(nodes)


def test_평면은_평면으로_읽는다() -> None:
    """**평면을 먼저 가려야 한다** — 곡면으로 잘못 읽으면 잘 풀리던 지문이 전부 깨진다."""
    rings = [[(x * 1.0, y * 1.0, 0.0) for x in range(5)] for y in range(5)]
    nodes, triangles, members = _mesh(rings, closed=False)

    shape = _classify(nodes, triangles, members)

    assert shape.kind == "plane"
    assert shape.radius is None


def test_원통은_반지름과_축을_낸다() -> None:
    """반지름은 **절점**으로 맞춘다 — 삼각형 무게중심은 원통 안쪽이라 작게 나온다
    (실측 2026-10-03: 5.0 이 4.75 로 읽혀 지문이 안 풀렸다)."""
    radius = 7.5
    rings = [
        [
            (radius * math.cos(step * math.pi / 12), radius * math.sin(step * math.pi / 12), z)
            for step in range(24)
        ]
        for z in (0.0, 5.0, 10.0)
    ]
    nodes, triangles, members = _mesh(rings, closed=True)

    shape = _classify(nodes, triangles, members)

    assert shape.kind == "cylinder"
    assert shape.radius is not None
    assert abs(shape.radius - radius) < 0.01
    assert shape.axis is not None
    # 축은 z — 부호는 따지지 않는다(CAD 와 메시에서 뒤집힐 수 있다).
    assert abs(abs(shape.axis[2]) - 1.0) < 0.01


def test_구는_구로_읽는다() -> None:
    """**구를 원통보다 먼저 가린다** — 구의 법선은 모든 방향을 향해서 「가장 안 퍼진 축」 이
    뜻을 갖지 않는다. 그대로 두면 구가 원통으로 읽힌다."""
    radius = 4.0
    rings = [
        [
            (
                radius * math.sin(theta) * math.cos(step * math.pi / 6),
                radius * math.sin(theta) * math.sin(step * math.pi / 6),
                radius * math.cos(theta),
            )
            for step in range(12)
        ]
        for theta in (0.4, 0.9, 1.4, 1.9, 2.4)
    ]
    nodes, triangles, members = _mesh(rings, closed=True)

    shape = _classify(nodes, triangles, members)

    assert shape.kind == "sphere"
    assert shape.radius is not None
    assert abs(shape.radius - radius) < 0.05


def test_원뿔은_종류만_말하고_반지름은_안_적는다() -> None:
    """원뿔은 **축을 따라 반지름이 변한다.** 그 값을 적지 않는 이유는 CAD 가 보내는 원뿔의
    `radius` 가 어느 자리의 것인지 계약에 없어서다 — 맞춰 보는 척하면 엉뚱한 면에 붙는다.

    그래도 종류를 알면 **평면 지문이 곡면에 붙는 것**은 막는다.
    """
    rings = [
        [
            (
                (2.0 + z * 0.5) * math.cos(step * math.pi / 9),
                (2.0 + z * 0.5) * math.sin(step * math.pi / 9),
                z,
            )
            for step in range(18)
        ]
        for z in (0.0, 2.0, 4.0, 6.0)
    ]
    nodes, triangles, members = _mesh(rings, closed=True)

    shape = _classify(nodes, triangles, members)

    assert shape.kind == "cone"
    assert shape.radius is None


def test_곡면의_중심도_형상으로_잰_넓이_무게중심이다() -> None:
    """CompCore faeede1 부터 곡면 지문의 중심이 넓이 무게중심이라(Mechanical 과 같다) 우리도
    형상으로 잰 값으로 바꾼다 — 반쪽 원통면(r 6)이면 축에서 2r/π = 3.820. 전에는 곡면만
    경계상자 중심(r/2 = 3.0)을 흉내 냈다."""
    half = FaceRecord(
        id=1, centroid=(20.0, 3.7, 5.0), area=187.0, surface="cylinder", radius=6.0
    )
    mesh = Mesh(
        nodes={},
        solids={},
        faces=[half],
        bodies=[],
        face_nodes={},
        triangles=[],
        face_triangles={},
        face_rings={},
        second_order=True,
    )
    measured = Probe(
        volumes=[], surfaces=[BodyRecord(index=1, volume=188.5, centroid=(20.0, 3.82, 5.0))]
    )
    face = with_geometry(mesh, measured).faces[0]
    assert face.centroid == (20.0, 3.82, 5.0)
    assert face.area == 188.5
    assert face.radius == 6.0
