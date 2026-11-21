"""lever 본딩(`calculix/lever.py`) — 도구 없이 보는 식 · 덱 단계. 진짜 gmsh · ccx 쪽은
`tests/opensolver/test_bonding.py` 다.

볼 것: 형상함수(합 1 · 미분 합 0 · Σ x g = I), 곡면 위 최근접, **강체 운동 여섯을 그대로
만족하는 식**(병진만 묶는 식은 회전에서 어긋난다 — v0.28 의 `ADJUST=NO`), 덱 단계의 정리(고정
자유도 · 두 접합 · 대입)와 검사.
"""

from __future__ import annotations

import math
import random
import re
from types import SimpleNamespace

import pytest

from app.core.calculix import bonding, lever
from app.core.calculix.deck import Lever

Vector = tuple[float, float, float]

#: 꼭짓점 넷 — 바닥면(P1 = 절점 1 · 2 · 3)이 z = 0 에 눕고 4가 위에 있다.
CORNERS: list[Vector] = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 4.0, 0.0), (0.0, 0.0, 4.0)]


def _tet10(bend: float = 0.0) -> list[Vector]:
    """C3D10 — 중간 절점을 모서리 가운데서 `bend` 만큼 비켜 면을 굽힌다(따로 메시한 2차
    곡면)."""
    middles = []
    for a, b in lever.TET10_EDGES:
        mid = [(CORNERS[a][k] + CORNERS[b][k]) / 2 for k in range(3)]
        mid[2] -= bend if CORNERS[a][2] == 0 and CORNERS[b][2] == 0 else 0.0
        middles.append((mid[0], mid[1], mid[2]))
    return CORNERS + middles


@pytest.mark.parametrize("count", [4, 10])
def test_형상함수는_합이_1이고_미분의_합은_0이다(count: int) -> None:
    rng = random.Random(7)
    for _ in range(20):
        r, s = rng.random() * 0.5, rng.random() * 0.4
        t = rng.random() * (1 - r - s)
        values, natural = lever.shape(count, (r, s, t))
        assert sum(values) == pytest.approx(1.0)
        for axis in range(3):
            assert sum(one[axis] for one in natural) == pytest.approx(0.0, abs=1e-12)


def test_x_에_대한_미분은_좌표를_되살린다() -> None:
    """등매개 요소의 Σ x_a g_aᵀ = I — 강체 회전을 식이 만족하는 까닭이다."""
    points = _tet10(bend=0.3)
    _, natural = lever.shape(10, (0.2, 0.3, 0.0))
    grads = lever.gradients(points, natural)
    for i in range(3):
        for j in range(3):
            total = sum(points[n][i] * grads[n][j] for n in range(10))
            assert total == pytest.approx(1.0 if i == j else 0.0, abs=1e-12)


def test_곡면_위_가장_가까운_점을_찾는다() -> None:
    """2차 면은 꼭짓점 삼각형보다 처진다 — 평평한 삼각형에 투영하면 처짐만큼 틀린다."""
    points = _tet10(bend=0.25)
    target = (1.2, 1.1, -0.4)
    distance, here, xi = lever.locate(target, points, "P1")
    # 촘촘히 훑은 곡면의 가장 가까운 점과 같아야 한다.
    best = math.inf
    steps = 200
    for i in range(steps + 1):
        for j in range(steps + 1 - i):
            values, _ = lever.shape(10, (i / steps, j / steps, 0.0))
            point = tuple(
                sum(w * p[k] for w, p in zip(values, points, strict=True)) for k in range(3)
            )
            best = min(best, math.dist(target, point))
    assert distance == pytest.approx(best, abs=2e-4)
    assert distance < math.dist(target, (1.2, 1.1, 0.0))  # 평평한 면보다 가깝다(처짐)
    assert xi[2] == pytest.approx(0.0, abs=1e-12)  # P1 은 t = 0 인 면이다
    assert math.dist(here, target) == pytest.approx(distance)


def _motion(kind: int, x: Vector) -> Vector:
    """강체 운동 — 0 · 1 · 2 는 병진, 3 · 4 · 5 는 그 축 둘레의 회전."""
    if kind < 3:
        return tuple(1.0 if k == kind else 0.0 for k in range(3))  # type: ignore[return-value]
    omega = [0.0, 0.0, 0.0]
    omega[kind - 3] = 1.0
    return (
        omega[1] * x[2] - omega[2] * x[1],
        omega[2] * x[0] - omega[0] * x[2],
        omega[0] * x[1] - omega[1] * x[0],
    )


@pytest.mark.parametrize("bend", [0.0, 0.3])
def test_lever_식은_강체_운동_여섯을_그대로_만족한다(bend: float) -> None:
    """간극 0.05 mm 를 둔 종 절점 — 식이 u종 = Σ N u주 + θ x d 이면 병진 · 회전 모두 맞는다."""
    points = _tet10(bend=bend)
    element = list(range(101, 111))
    slave = (1.3, 0.9, -0.05 - bend * 0.5)
    _, _, xi = lever.locate(slave, points, "P1")
    d, rows = lever.lever_terms(slave, element, points, xi)
    assert math.sqrt(sum(one * one for one in d)) == pytest.approx(
        lever.locate(slave, points, "P1")[0]
    )
    coordinates = {**dict(zip(element, points, strict=True)), 1: slave}
    for dof, row in rows.items():
        residual = lever.rigid_residual((1, dof), row, coordinates)
        assert residual is not None and residual < 1e-10
    # **병진만 묶으면**(v0.28 `ADJUST=NO`) 회전에서 ω x d 만큼 어긋난다.
    values, _ = lever.shape(10, xi)
    plain = {(node, 1): value for node, value in zip(element, values, strict=True)}
    misses = [
        abs(
            _motion(kind, slave)[0]
            - sum(c * _motion(kind, coordinates[node])[0] for (node, _), c in plain.items())
        )
        for kind in (3, 4, 5)
    ]
    assert max(misses) > 1e-3  # 간극이 z 쪽이면 y 축 둘레 회전에서 x 가 d 만큼 어긋난다


# --- 덱 단계 ---------------------------------------------------------------------


def _deck(nodes: dict[int, Vector], extra: str = "") -> str:
    node_lines = "\n".join(f"{n}, {x:.9g}, {y:.9g}, {z:.9g}" for n, (x, y, z) in nodes.items())
    return (
        "*NODE\n" + node_lines + "\n"
        "*ELEMENT, TYPE=C3D10, ELSET=E1\n101, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10\n"
        + extra
        + "*STEP\n*FREQUENCY\n6\n*END STEP\n"
    )


def _master() -> tuple[dict[int, Vector], dict[int, list[int]]]:
    points = _tet10(bend=0.1)
    nodes = {index + 1: point for index, point in enumerate(points)}
    return nodes, {101: list(range(1, 11))}


def _equations(text: str) -> dict[tuple[int, int], list[tuple[int, int, float]]]:
    found: dict[tuple[int, int], list[tuple[int, int, float]]] = {}
    for block in re.findall(r"\*EQUATION\n(.*?)(?=\n\*)", text, re.S):
        values = [
            one.strip() for line in block.split("\n") for one in line.split(",") if one.strip()
        ]
        k = 0
        while k < len(values):
            count = int(values[k])
            chunk = values[k + 1 : k + 1 + 3 * count]
            k += 1 + 3 * count
            terms = [
                (int(chunk[m]), int(chunk[m + 1]), float(chunk[m + 2]))
                for m in range(0, len(chunk), 3)
            ]
            found[(terms[0][0], terms[0][1])] = terms
    return found


def test_덱을_다_쓴_뒤_간극을_둔_채_식을_넣고_고정_자유도는_종속으로_안_쓴다() -> None:
    nodes, elements = _master()
    nodes[201] = (1.0, 1.0, -0.06)
    nodes[202] = (2.0, 0.5, -0.04)
    nodes[203] = (9.0, 9.0, -0.05)  # 반경 밖
    text = _deck(nodes, "*BOUNDARY\n202, 3, 3, 0.0\n")
    pair = Lever("기둥-판", "BOND1", frozenset({201, 202, 203}), [(101, "P1")], 0.1)
    made = lever.apply(text, nodes, elements, [pair])
    equations = _equations(made.text)
    assert set(equations) == {(201, 1), (201, 2), (201, 3), (202, 1), (202, 2)}
    assert made.text.index("*EQUATION") < made.text.index("*STEP")
    # 절점은 옮기지 않았다 — 덱의 좌표가 그대로다.
    assert "201, 1, 1, -0.06" in made.text
    [row] = made.rows
    assert (row["tied"], row["far"]) == (2, 1)
    # 간극은 **곡면까지**다 — 굽힌 면이 꼭짓점 평면 아래로 처져 202 가 더 멀다.
    points = [nodes[n] for n in range(1, 11)]
    gaps = [lever.locate(nodes[n], points, "P1")[0] for n in (201, 202)]
    assert row["max_gap_mm"] == pytest.approx(max(gaps), abs=1e-6)
    assert made.rigid_failed == 0 and made.rigid_residual < 1e-9 and made.overlaps == 0
    assert any("고정된 자유도 1개" in one for one in made.notes)


def test_두_접합에_걸린_종_절점은_가까운_쪽_하나에만_묶는다() -> None:
    """같은 종 면이 두 접촉에 걸렸다 — 절점마다 가까운 주 면의 접촉에."""
    nodes, elements = _master()
    shift = {n: (x + 10.0, y, z) for n, (x, y, z) in list(nodes.items())}
    for n, point in shift.items():
        nodes[n + 100] = point
    elements[102] = [n + 100 for n in range(1, 11)]
    nodes[301] = (1.0, 1.0, -0.02)  # 첫 주 면 아래
    nodes[302] = (11.0, 1.0, -0.03)  # 둘째 주 면 아래
    first = Lever("A", "BOND1", frozenset({301, 302}), [(101, "P1")], 0.5)
    second = Lever("B", "BOND2", frozenset({301, 302}), [(102, "P1")], 0.5)
    made = lever.apply(_deck(nodes), nodes, elements, [first, second])
    assert [row["tied"] for row in made.rows] == [1, 1]
    equations = _equations(made.text)
    assert {node for node, _, _ in equations[(301, 1)][1:]} <= set(range(1, 11))
    assert {node for node, _, _ in equations[(302, 1)][1:]} <= set(range(101, 111))


def test_종속_자유도가_우변에_나오면_대입해_없앤다() -> None:
    """덱에 이미 있는 구속식(볼트 · 기울어진 지지)이 lever 의 종 절점을 우변에 두면 그 식을
    대입해 고치고 덱의 구속식을 한 덩이로 다시 쓴다."""
    nodes, elements = _master()
    nodes[201] = (1.0, 1.0, -0.06)
    nodes[500] = (5.0, 5.0, 5.0)
    existing = "*EQUATION\n2\n500, 1, 1.0, 201, 1, -1.0\n"
    pair = Lever("기둥-판", "BOND1", frozenset({201}), [(101, "P1")], 0.1)
    made = lever.apply(_deck(nodes, existing), nodes, elements, [pair])
    assert made.text.count("*EQUATION") == 1
    equations = _equations(made.text)
    rewritten = equations[(500, 1)]
    assert all(node != 201 for node, _, _ in rewritten[1:])
    assert {node for node, _, _ in rewritten[1:]} <= set(range(1, 11))
    assert made.overlaps == 0


def test_다른_구속식의_종속은_lever_종속으로_안_쓴다() -> None:
    nodes, elements = _master()
    nodes[201] = (1.0, 1.0, -0.06)
    existing = "*EQUATION\n2\n201, 2, 1.0, 5, 2, -1.0\n"
    pair = Lever("기둥-판", "BOND1", frozenset({201}), [(101, "P1")], 0.1)
    made = lever.apply(_deck(nodes, existing), nodes, elements, [pair])
    equations = _equations(made.text)
    assert equations[(201, 2)] == [(201, 2, 1.0), (5, 2, -1.0)]
    assert (201, 1) in equations and (201, 3) in equations
    assert any("다른 구속" in one for one in made.notes)


def test_한_종_면이_두_접촉에_걸리면_절점마다_가까운_주_면의_접촉에_준다() -> None:
    """**앞 접촉이 종 면의 절점을 다 가져가던 것**(뒤 접촉 0개인데 「적용」, r2 의 질량이
    떴다)을 막는다 — `bonding._share_slaves`."""
    nodes = {
        1: (0.0, 0.0, 0.0),
        2: (10.0, 0.0, 0.0),
        3: (0.0, 10.0, 0.0),
        4: (20.0, 0.0, 0.0),
        5: (30.0, 0.0, 0.0),
        6: (20.0, 10.0, 0.0),
        11: (1.0, 1.0, -0.01),
        12: (21.0, 1.0, -0.01),
        13: (50.0, 50.0, -0.01),
    }
    mesh = SimpleNamespace(
        nodes=nodes,
        face_nodes={100: {11, 12, 13}},
        face_triangles={200: [(1, 2, 3)], 300: [(4, 5, 6)]},
    )

    def plan(index: int, master: int) -> bonding._Pairing:
        pair = SimpleNamespace(name=f"접촉{index}")
        return bonding._Pairing(index, pair, "", [100], [master], None, 0.5)  # type: ignore[arg-type]

    shared = bonding._share_slaves(mesh, [plan(1, 200), plan(2, 300)], set())
    # 반경 안에 아무 주 면도 없는 절점(13)은 먼저 선언한 접촉이 「반경 밖」 으로 센다.
    assert shared == {1: {11, 13}, 2: {12}}
    assert bonding._share_slaves(mesh, [plan(1, 200)], {11}) == {1: {12, 13}}
