"""CalculiX 경로의 파트별 설정 — **메시 전에 빼고 · 크기를 주고, 덱에서 강체로 묶는다.**

gmsh · ccx 없이 도는 부분만 본다(쪽지 · 파싱 · 덱 글). 끝까지 푸는 것은 `tests/opensolver`.
"""

from __future__ import annotations

from pathlib import Path

from app.core import conditions as condition_model
from app.core.calculix import deck
from app.core.calculix.mesh import _geo, parse_probe
from app.core.materials import Material


def test_뺀_부피는_지우고_파트_크기는_그_부피의_점에_준다() -> None:
    text = _geo(
        Path("/data/input.step"),
        5.0,
        True,
        {12: 0.5},
        removed=frozenset({3}),
        volume_sizes={1: 8.0, 2: 1.5},
    )
    lines = text.splitlines()
    # 쪼개기 **전에** 지운다 — 뒤에 지우면 이웃 면에 맞닿았던 자국이 남아 면이 갈라진다.
    assert lines.index("Recursive Delete { Volume{3}; }") < next(
        index for index, line in enumerate(lines) if line.startswith("BooleanFragments")
    )
    # 파트 크기가 전역 범위를 넘으면 범위를 넓힌다 — 안 그러면 gmsh 가 되돌린다.
    assert "Mesh.MeshSizeMax = 8;" in lines
    assert "Mesh.MeshSizeMin = 0.375;" in lines
    # 전역 → 큰 파트 → 작은 파트 → 면 힌트 순서(뒤가 이긴다: 좁은 쪽 · 작은 쪽).
    order = [
        lines.index("MeshSize{ PointsOf{ Volume{:}; } } = 5;"),
        lines.index("MeshSize{ PointsOf{ Volume{1}; } } = 8;"),
        lines.index("MeshSize{ PointsOf{ Volume{2}; } } = 1.5;"),
        lines.index("MeshSize{ PointsOf{ Surface{12}; } } = 0.5;"),
    ]
    assert order == sorted(order)


def test_파트_설정이_없으면_쪽지가_그대로다() -> None:
    """설정이 없는 모델의 메시가 바뀌면 안 된다 — 전역 크기를 점마다 다시 주지 않는다."""
    text = _geo(Path("/data/input.step"), 5.0, True, {})
    assert "Volume{:}; } }" not in text
    assert "Mesh.MeshSizeMax = 5;" in text and "Recursive Delete" not in text


def test_gmsh_가_찍은_부피를_읽는다() -> None:
    out = (
        "Info    : Reading 'probe.geo'...\n"
        "SEB_VOLUME 1 30000 4.3e-16 4.0e-17 2.5\n"
        "Info    : something\n"
        "SEB_VOLUME 2 32000 0 0 15\n"
    )
    found = parse_probe(out)
    assert [(one.index, one.volume, one.centroid) for one in found] == [
        (1, 30000.0, (4.3e-16, 4.0e-17, 2.5)),
        (2, 32000.0, (0.0, 0.0, 15.0)),
    ]


def _material(name: str, bodies: tuple[str, ...]) -> Material:
    return Material(
        name=name,
        bodies=bodies,
        youngs_modulus_pa=200e9,
        poisson_ratio=0.3,
        density_kg_m3=7850,
        source="spec",
    )


def test_강체는_기준점에_묶고_그_면의_고정은_기준점에_건다() -> None:
    """사면체 둘(1 · 2)이 절점 2 · 3 · 4 를 나눠 쓴다 — 2 를 강체로.

    강체 면의 고정 지지는 **기준점 · 회전 절점**에 걸고, 변형체 면이 강체와 나눠 쓰는 절점은
    빼고 건다(두 번 묶이면 ccx 가 거절한다). 결과는 메시 절점(`NALL`)만 낸다.
    """
    nodes = {
        1: (0.0, 0.0, 0.0),
        2: (1.0, 0.0, 0.0),
        3: (0.0, 1.0, 0.0),
        4: (0.0, 0.0, 1.0),
        5: (1.0, 1.0, 1.0),
    }
    solids = {1: [(1, [1, 2, 3, 4])], 2: [(2, [2, 3, 4, 5])]}
    rigid = deck.rigid_bodies(nodes, solids, {"지그판": 2}, {2: (0.5, 0.5, 0.5)})
    assert [(one.part, one.ref, one.rot, sorted(one.nodes)) for one in rigid] == [
        ("지그판", 6, 7, [2, 3, 4, 5])
    ]
    given = condition_model.Conditions(
        constraints=[
            condition_model.Constraint(name="지그 바닥", kind="fixed_support", region="바닥"),
            condition_model.Constraint(name="부품 끝", kind="fixed_support", region="끝"),
        ]
    )
    plan = deck.write_modal(
        nodes=nodes,
        solids=solids,
        body_of={"부품": 1, "지그판": 2},
        materials=[_material("SS400", ("부품", "지그판"))],
        held_nodes={"바닥": {5}, "끝": {1, 2}},
        given=given,
        modes=4,
        second_order=False,
        rigid=rigid,
    )
    assert plan.refused == []
    text = plan.text
    assert "*RIGID BODY, NSET=RIGID1, REF NODE=6, ROT NODE=7" in text
    assert "6, 1, 1, 0" in text and "7, 3, 3, 0" in text
    # 반력은 강체 절점 전부의 합으로 읽는다(쉘이 붙으면 기준점에 안 모인다).
    assert plan.reaction_sets["바닥"] == "RIGID1"
    # 「부품 끝」 은 절점 1 만 — 2 는 강체가 쥔다.
    assert "*NSET, NSET=HOLD1\n1\n" in text
    assert "*NODE FILE, NSET=NALL" in text and "\n*NODE FILE\n" not in text
    assert "rigid:지그판" in plan.applied


def test_강체_면의_다른_구속과_하중은_막는다() -> None:
    nodes = {1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0), 3: (0.0, 1.0, 0.0), 4: (0.0, 0.0, 1.0)}
    solids = {1: [(1, [1, 2, 3, 4])]}
    rigid = deck.rigid_bodies(nodes, solids, {"지그판": 1}, {})
    given = condition_model.Conditions(
        constraints=[
            condition_model.Constraint(name="미끄럼", kind="frictionless", region="바닥")
        ],
        loads=[condition_model.Load(name="누름", kind="force", region="바닥", magnitude=10.0)],
    )
    plan = deck.write_static(
        nodes=nodes,
        solids=solids,
        body_of={"지그판": 1},
        materials=[_material("SS400", ("지그판",))],
        held_nodes={"바닥": {1, 2, 3}},
        load_nodes={"바닥": {1, 2, 3}},
        load_faces={},
        load_areas={},
        given=given,
        second_order=False,
        rigid=rigid,
    )
    reasons = " ".join(f"{one.what} {one.why}" for one in plan.refused)
    assert "고정 지지 · 원격 변위만" in reasons
    assert "강체 파트 「지그판」 의 면에 건 하중" in reasons
