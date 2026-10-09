"""CalculiX 덱의 하중 · 구속 — **시험 규격이 쓰는 것들**(CompCore 시험 규격 20개, 2026-10-07).

CalculiX 를 기본 솔버로 쓰려면(2026-10-08) 시편 시험 · 제품 시험이 쓰는 조건을 다 걸 수 있어야
한다: 변위로만 당기는 시험, 가속도 · 중력, 면에 거는 모멘트, 변형체 면의 원격 변위(회전
포함), 강체 파트 여럿에 걸친 그룹. 끝까지 푸는 것은 `tests/opensolver` 가 본다 — 여기서는 덱의
글을 본다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.core import conditions as condition_model
from app.core.calculix import deck
from app.core.materials import Material

#: 사면체 둘이 면 2-3-4 를 나눠 쓴다. 바닥 면 1-2-3, 끝 면 2-3-5 · 3-4-5 …
NODES = {
    1: (0.0, 0.0, 0.0),
    2: (10.0, 0.0, 0.0),
    3: (0.0, 10.0, 0.0),
    4: (0.0, 0.0, 10.0),
    5: (10.0, 10.0, 10.0),
}
SOLIDS = {1: [(1, [1, 2, 3, 4])], 2: [(2, [2, 3, 4, 5])]}


def _material(*bodies: str) -> Material:
    return Material(
        name="SS400",
        bodies=bodies,
        youngs_modulus_pa=200e9,
        poisson_ratio=0.3,
        density_kg_m3=7850,
        source="spec",
    )


def _static(
    given: condition_model.Conditions,
    *,
    held: dict[str, set[int]] | None = None,
    loads: dict[str, set[int]] | None = None,
    rigid: list[deck.RigidBody] | None = None,
) -> deck.Plan:
    return deck.write_static(
        nodes=NODES,
        solids=SOLIDS,
        body_of={"부품": 1, "지그": 2},
        materials=[_material("부품", "지그")],
        held_nodes=held or {"바닥": {1, 2, 3}},
        load_nodes=loads or {},
        load_faces={},
        load_areas={},
        given=given,
        second_order=False,
        rigid=rigid or [],
    )


FIXED = condition_model.Constraint(name="바닥 고정", kind="fixed_support", region="바닥")


def test_변위로만_당기는_정적_해석은_하중이_없어도_푼다() -> None:
    """시편 시험은 그립을 변위로 당긴다 — 「하중이 하나도 없다」 로 막으면 안 된다."""
    pull = condition_model.Constraint(
        name="그립 당김", kind="displacement", region="끝", components=(1.0, None, None)
    )
    plan = _static(
        condition_model.Conditions(constraints=[FIXED, pull]),
        held={"바닥": {1, 2, 3}, "끝": {5}},
    )
    assert plan.refused == []
    # 0 만 적힌 변위(고정)는 당기는 것이 아니다 — 하중도 없으면 막는다.
    still = condition_model.Constraint(
        name="그립", kind="displacement", region="끝", components=(0.0, 0.0, 0.0)
    )
    plan = _static(
        condition_model.Conditions(constraints=[FIXED, still]),
        held={"바닥": {1, 2, 3}, "끝": {5}},
    )
    assert any("하중도 강제 변위도 없습니다" in one.why for one in plan.refused)


def test_가속도는_관성으로_받고_중력은_그_방향으로_당긴다() -> None:
    """+Z 가속도 4g(「손잡이」 의 무게 4배)는 몸을 -Z 로 누른다 — GRAV 방향을 뒤집는다."""
    lift = condition_model.Load(
        name="무게 4배",
        kind="acceleration",
        magnitude=39226.6,
        unit="mm/s^2",
        direction=(0.0, 0.0, 1.0),
    )
    plan = _static(condition_model.Conditions(constraints=[FIXED], loads=[lift]))
    assert plan.refused == []
    assert "E1, GRAV, 39226.6, -0, -0, -1" in plan.text
    assert "E2, GRAV, 39226.6, -0, -0, -1" in plan.text
    # SI 로 적힌 가속도(m/s^2)는 mm/s^2 로, 중력은 표준 중력으로 그 방향을 당긴다.
    si = condition_model.Load(
        name="가속", kind="acceleration", magnitude=9.80665, unit="m/s^2", direction=(1, 0, 0)
    )
    earth = condition_model.Load(name="중력", kind="standard_earth_gravity")
    plan = _static(condition_model.Conditions(constraints=[FIXED], loads=[si, earth]))
    assert "E1, GRAV, 9806.65, -1, 0, 0" in plan.text
    assert "E1, GRAV, 9806.65, 0, 0, -1" in plan.text


def test_모멘트는_면_절점에_합력_없이_나눈다() -> None:
    """절점마다 F = Ω x r — 힘의 합은 0, 절점 중심에 대한 모멘트의 합은 준 값이다."""
    face = {2, 3, 5}
    twist = condition_model.Load(
        name="모멘트",
        kind="moment",
        region="끝",
        magnitude=0.1,
        unit="N*m",
        direction=(0.0, 0.0, 2.0),
    )
    plan = _static(
        condition_model.Conditions(constraints=[FIXED], loads=[twist]), loads={"끝": face}
    )
    assert plan.refused == []
    forces: dict[int, list[float]] = {node: [0.0, 0.0, 0.0] for node in face}
    rows = plan.text.split("*CLOAD\n", 1)[1].split("*NODE")[0].strip().splitlines()
    for row in rows:
        number, axis, value = row.split(", ")
        forces[int(number)][int(axis) - 1] += float(value)
    center = [sum(NODES[node][axis] for node in face) / 3 for axis in range(3)]
    total = [sum(force[axis] for force in forces.values()) for axis in range(3)]
    moment = [0.0, 0.0, 0.0]
    for node, force in forces.items():
        r = [NODES[node][axis] - center[axis] for axis in range(3)]
        moment[0] += r[1] * force[2] - r[2] * force[1]
        moment[1] += r[2] * force[0] - r[0] * force[2]
        moment[2] += r[0] * force[1] - r[1] * force[0]
    assert total == pytest.approx([0, 0, 0], abs=1e-9)
    # 0.1 N·m = 100 N·mm, 회전축 +Z(크기는 방향 벡터의 길이와 무관).
    assert moment == pytest.approx([0, 0, 100.0], abs=1e-6)


def test_변형체_면의_원격_변위는_면을_원격점에_묶고_회전을_라디안으로_준다() -> None:
    """비틀림 시험 — 끝면을 X 축으로 6도 돌린다. 면적 중심(지문)이 없으면 원격점은 그 면
    절점의 중심이다."""
    twist = condition_model.Constraint(
        name="끝 비틀기",
        kind="remote_displacement",
        region="끝",
        components=(None, 0.0, 0.0),
        rotations=(6.0, 0.0, 0.0),
        behavior="rigid",
    )
    plan = _static(
        condition_model.Conditions(constraints=[FIXED, twist]),
        held={"바닥": {1, 2, 3}, "끝": {4, 5}},
    )
    assert plan.refused == []
    # 기준점 · 회전 절점은 메시 절점 다음 번호이고 결과에서 뺀다.
    assert "*RIGID BODY, NSET=REMOTE1, REF NODE=6, ROT NODE=7" in plan.text
    assert "6, 5.000000, 5.000000, 10.000000" in plan.text
    assert f"7, 1, 1, {math.radians(6.0):.8g}" in plan.text
    assert "6, 2, 2, 0" in plan.text and "6, 1, 1" not in plan.text
    assert "*NODE FILE, NSET=NALL" in plan.text
    assert plan.reaction_sets["끝"] == "REMOTE1"
    # 강제로 돌리므로 하중이 없어도 답이 있다.
    assert not any("하중도 강제 변위도" in one.why for one in plan.refused)


def test_변형체로_적힌_원격_변위는_강체로_묶었다고_말한다() -> None:
    push = condition_model.Constraint(
        name="누름",
        kind="remote_displacement",
        region="끝",
        components=(0.0, 0.0, -0.2),
        behavior="deformable",
    )
    plan = _static(
        condition_model.Conditions(constraints=[FIXED, push]),
        held={"바닥": {1, 2, 3}, "끝": {4, 5}},
    )
    assert plan.refused == []
    assert any("강체로" in one.why for one in plan.skipped)


def test_강체_파트_여럿에_걸친_그룹은_파트마다_기준점을_묶는다() -> None:
    """굽힘 시험의 「로딩 노즈」 는 노즈 둘의 면이다 — 한 파트에 다 들지 않아도 강체 면이다."""
    nodes = {**NODES, 6: (20.0, 0.0, 0.0), 7: (20.0, 10.0, 0.0), 8: (20.0, 0.0, 10.0)}
    solids = {**SOLIDS, 3: [(3, [6, 7, 8, 5])]}
    rigid = deck.rigid_bodies(nodes, solids, {"노즈1": 2, "노즈2": 3}, {})
    press = condition_model.Constraint(
        name="노즈 가압",
        kind="remote_displacement",
        region="노즈",
        components=(0.0, 0.0, -5.0),
        rotations=(0.0, 0.0, 0.0),
        behavior="rigid",
    )
    plan = deck.write_static(
        nodes=nodes,
        solids=solids,
        body_of={"부품": 1, "노즈1": 2, "노즈2": 3},
        materials=[_material("부품", "노즈1", "노즈2")],
        held_nodes={"바닥": {1}, "노즈": {4, 5, 8}},
        load_nodes={},
        load_faces={},
        load_areas={},
        given=condition_model.Conditions(constraints=[FIXED, press]),
        second_order=False,
        rigid=rigid,
    )
    assert plan.refused == []
    refs = {one.part: one.ref for one in rigid}
    assert f"{refs['노즈1']}, 3, 3, -5" in plan.text
    assert f"{refs['노즈2']}, 3, 3, -5" in plan.text
    # 반력은 두 강체 절점 전부의 합으로 읽는다.
    assert plan.reaction_sets["노즈"] == "HOLD1A"


def test_원격점은_CAD_가_잰_면적_중심에_선다() -> None:
    """절점 평균은 메시가 고르지 않은 만큼 비켜난다 — 비틀림 시험에서 축이 0.05 mm 비켜나
    옆 반력이 408 N 나왔다(순수 비틀림이라 0 언저리여야 한다 — 면적 중심에 두면 4 N). 지문의
    면적 중심이 있으면 그 자리다."""
    twist = condition_model.Constraint(
        name="끝 비틀기",
        kind="remote_displacement",
        region="끝",
        components=(None, 0.0, 0.0),
        rotations=(6.0, 0.0, 0.0),
        behavior="rigid",
    )
    plan = deck.write_static(
        nodes=NODES,
        solids=SOLIDS,
        body_of={"부품": 1, "지그": 2},
        materials=[_material("부품", "지그")],
        held_nodes={"바닥": {1, 2, 3}, "끝": {4, 5}},
        load_nodes={},
        load_faces={},
        load_areas={},
        given=condition_model.Conditions(constraints=[FIXED, twist]),
        second_order=False,
        centers={"끝": (4.0, 6.0, 9.0)},
    )
    assert plan.refused == []
    assert "6, 4.000000, 6.000000, 9.000000" in plan.text


def test_영역의_면적_중심은_면적으로_무게를_준다() -> None:
    from app.core.calculix.build import _region_centers

    topology = {
        "regions": {
            "두 면": [
                {"centroid": [0, 0, 0], "area": 1.0},
                {"centroid": [4, 0, 0], "area": 3.0},
            ],
            # 면적이 없는 지문이 섞이면 절점 평균으로 미룬다.
            "모름": [{"centroid": [1, 1, 1]}],
        }
    }
    assert _region_centers(topology) == {"두 면": (3.0, 0.0, 0.0)}


def test_강제_변위는_선언된_단위계의_길이로_온다() -> None:
    """SI 폴더의 0.001 은 1 mm 다 — 덱은 mm 라 옮겨 적는다(Ansys 는 `[m]` 을 붙여 준다).
    원격 변위의 회전(도)은 단위계와 상관없다."""
    pull = condition_model.Constraint(
        name="그립 당김", kind="displacement", region="끝", components=(0.001, None, 0.0)
    )
    plan = deck.write_static(
        nodes=NODES,
        solids=SOLIDS,
        body_of={"부품": 1, "지그": 2},
        materials=[_material("부품", "지그")],
        held_nodes={"바닥": {1, 2, 3}, "끝": {5}},
        load_nodes={},
        load_faces={},
        load_areas={},
        given=condition_model.Conditions(constraints=[FIXED, pull]),
        second_order=False,
        length_mm=1000.0,
    )
    assert plan.refused == []
    assert "HOLD1, 1, 1, 1\n" in plan.text
    assert "HOLD1, 3, 3, 0\n" in plan.text

    turn = condition_model.Constraint(
        name="끝 비틀기",
        kind="remote_displacement",
        region="끝",
        components=(0.002, 0.0, 0.0),
        rotations=(6.0, 0.0, 0.0),
        behavior="rigid",
    )
    plan = deck.write_static(
        nodes=NODES,
        solids=SOLIDS,
        body_of={"부품": 1, "지그": 2},
        materials=[_material("부품", "지그")],
        held_nodes={"바닥": {1, 2, 3}, "끝": {4, 5}},
        load_nodes={},
        load_faces={},
        load_areas={},
        given=condition_model.Conditions(constraints=[FIXED, turn]),
        second_order=False,
        length_mm=1000.0,
    )
    assert "6, 1, 1, 2\n" in plan.text
    assert f"7, 1, 1, {math.radians(6.0):.8g}\n" in plan.text


def test_붙은_것으로_풀었다는_말은_절점을_공유했을_때만_한_번() -> None:
    """접촉 쌍으로 마찰을 걸었으면 「붙은 것으로」 는 거짓말이다 — 전에는 정적 덱이 끝에서
    접촉마다 그 말을 한 번 더 붙였다(쌍을 쓴 때도)."""
    rub = condition_model.Contact(
        name="머리-판", kind="frictional", source="머리", target="판", friction=0.2
    )
    pull = condition_model.Constraint(
        name="그립 당김", kind="displacement", region="끝", components=(1.0, None, None)
    )
    given = condition_model.Conditions(constraints=[FIXED, pull], contacts=[rub])
    shared = _static(given, held={"바닥": {1, 2, 3}, "끝": {5}})
    notes = [one for one in shared.skipped if "머리-판" in one.what]
    assert len(notes) == 1 and "붙은 것으로" in notes[0].why

    paired = deck.write_static(
        nodes=NODES,
        solids=SOLIDS,
        body_of={"부품": 1, "지그": 2},
        materials=[_material("부품", "지그")],
        held_nodes={"바닥": {1, 2, 3}, "끝": {5}},
        load_nodes={},
        load_faces={},
        load_areas={},
        given=given,
        contact_faces={"머리": [(1, "P4")], "판": [(2, "P1")]},
        second_order=False,
    )
    assert paired.refused == []
    assert not any("붙은 것으로" in one.why for one in paired.skipped)
    assert "*FRICTION" in paired.text

    odd = condition_model.Contact(name="모름", kind="glue", source="머리", target="판")
    plan = _static(
        condition_model.Conditions(constraints=[FIXED, pull], contacts=[odd]),
        held={"바닥": {1, 2, 3}, "끝": {5}},
    )
    assert [one.why for one in plan.refused] == ["모르는 접촉입니다."]


def test_선응력_모달에서는_하중이_답을_바꾼다고_본다() -> None:
    """앞 정적 단계에 하중을 걸었으면 「모달에서는 하중이 답을 바꾸지 않습니다」 는
    거짓이다."""
    push = condition_model.Load(
        name="누름", kind="force", region="끝", magnitude=10.0, direction=(0, 0, -1)
    )
    given = condition_model.Conditions(constraints=[FIXED], loads=[push])
    common: dict[str, object] = {
        "nodes": NODES,
        "solids": SOLIDS,
        "body_of": {"부품": 1, "지그": 2},
        "materials": [_material("부품", "지그")],
        "held_nodes": {"바닥": {1, 2, 3}},
        "given": given,
        "modes": 6,
        "second_order": False,
    }
    plain = deck.write_modal(**common)  # type: ignore[arg-type]
    assert any("바꾸지 않습니다" in one.why for one in plain.skipped)
    tight = deck.write_modal(**common, preload=["*CLOAD", "5, 3, -10"])  # type: ignore[arg-type]
    assert not any("바꾸지 않습니다" in one.why for one in tight.skipped)
    assert "*STEP, PERTURBATION" in tight.text


def test_강체를_고정하고_중력을_걸면_그_무게를_반력에_되돌린다() -> None:
    """ccx 의 RF 는 그 절점에 직접 걸린 외력을 빼고 낸다 — 강체를 고정하고 중력을 걸면 그
    무게가 전부 자기 절점에 얹혀 반력이 0 으로 나온다(실측 2026-10-08: 0.238 N, 참값 5.3 N).
    덱이 그 몫을 셈해 둔다: 지그(사면체 2, 333.3 mm³) 전부 + 부품(사면체 1, 166.7 mm³)이
    지그와 나눈 꼭짓점 셋의 몫(3/4)."""
    rigid = deck.rigid_bodies(NODES, SOLIDS, {"지그": 2}, {})
    hold = condition_model.Constraint(name="지그 고정", kind="fixed_support", region="지그 면")
    pull_down = condition_model.Load(name="중력", kind="standard_earth_gravity")
    push = condition_model.Load(
        name="누름", kind="force", region="끝", magnitude=1.0, direction=(1, 0, 0)
    )
    plan = deck.write_static(
        nodes=NODES,
        solids=SOLIDS,
        body_of={"부품": 1, "지그": 2},
        materials=[_material("부품", "지그")],
        held_nodes={"지그 면": {2, 3, 4}},
        load_nodes={"끝": {1}},
        load_faces={},
        load_areas={"끝": {1: 1.0}},
        given=condition_model.Conditions(constraints=[hold], loads=[pull_down, push]),
        second_order=False,
        rigid=rigid,
    )
    assert plan.refused == []
    mass = 7850 / 1e12 * (1000 / 3 + 0.75 * 1000 / 6)
    assert plan.reaction_offsets["지그 면"] == pytest.approx([0, 0, mass * 9806.65])
    # 이차 사면체는 꼭짓점 -1/20 · 중간점 1/5 로 나눈다 — 요소 전부가 집합에 들면 합은
    # 질량이다.
    offsets = deck._inertia_offsets(
        {"전부": frozenset(range(1, 11))},
        [0.0, 0.0, -1.0],
        {**NODES, **{n: (0.0, 0.0, 0.0) for n in range(6, 11)}},
        {1: [(1, [1, 2, 3, 4, 6, 7, 8, 9, 10, 5])]},
        {"부품": 1},
        [_material("부품")],
    )
    assert offsets["전부"] == pytest.approx([0, 0, 7850 / 1e12 * 1000 / 6])


def test_반력을_읽을_때_관성_몫을_더한다(tmp_path: Path) -> None:
    from app.core.calculix.static_read import _reactions

    (tmp_path / "boundary.json").write_text(
        json.dumps(
            {
                "reaction_sets": {"지그 면": "RIGID1"},
                "reaction_offsets": {"지그 면": [0.0, 0.0, 5.0]},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "model.dat").write_text(
        " total force (fx,fy,fz) for set RIGID1 and time  0.1000000E+01\n\n"
        "  1.000000E+00  0.000000E+00  2.500000E-01\n",
        encoding="utf-8",
    )
    assert _reactions(tmp_path) == {"지그 면": [1.0, 0.0, 5.25]}


def test_큰_변형이면_기하_비선형으로_증분을_밟는다() -> None:
    push = condition_model.Load(
        name="누름", kind="force", region="끝", magnitude=10.0, direction=(0, 0, -1)
    )
    given = condition_model.Conditions(constraints=[FIXED], loads=[push])
    small = _static(given, loads={"끝": {5}})
    assert "*STEP\n*STATIC\n" in small.text
    big = deck.write_static(
        nodes=NODES,
        solids=SOLIDS,
        body_of={"부품": 1, "지그": 2},
        materials=[_material("부품", "지그")],
        held_nodes={"바닥": {1, 2, 3}},
        load_nodes={"끝": {5}},
        load_faces={},
        load_areas={"끝": {5: 1.0}},
        given=given,
        second_order=False,
        large_deflection=True,
    )
    assert "*STEP, NLGEOM\n*STATIC\n0.1, 1.0\n" in big.text


def test_강체_면은_접촉_쌍의_독립_쪽에_선다() -> None:
    """`*CONTACT PAIR` 둘째 줄은 종속 · 독립 차례다. 강체 파트의 면은 늘 독립(master) 쪽 —
    강체 절점은 `*RIGID BODY` 가 이미 쥐어, 종속 면이 되면 같은 자유도를 두 번 묶는다."""
    rub = condition_model.Contact(
        name="판-롤러", kind="frictional", source="판", target="롤러", friction=0.1
    )
    faces = {"판": [(1, "P4")], "롤러": [(2, "P1")]}

    def pair_line(masters: set[str]) -> str:
        lines = deck.contact_block(
            [rub], faces, deck.Plan(), nonlinear=True, stiffness=1000.0, masters=masters
        )
        return lines[lines.index(next(one for one in lines if one.startswith("*CONTACT"))) + 1]

    # 지금까지의 차례(대상면이 종속) — 강체가 없으면 그대로다.
    assert pair_line(set()) == "C0T, C0S"
    # 대상면이 강체면 뒤집어 강체 면을 독립 쪽에 둔다.
    assert pair_line({"롤러"}) == "C0S, C0T"
    # 원천면이 강체면 지금 차례가 이미 그렇다.
    assert pair_line({"판"}) == "C0T, C0S"
