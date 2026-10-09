"""정적 해석의 큰 변형 · 초기 부단계 수 — **사람이 적었으면 그것, 비웠으면 CAD 가 적은 것**.

전에는 CAD 의 `analysis.large_deflection` 을 두 솔버 모두 읽지 않아, CompCore 시험 규격 20개 중
6개가 「큰 변형」 이라 적었는데도 선형으로 풀렸다(2026-10-08).
"""

from __future__ import annotations

from typing import Any

from app.core import conditions as condition_model
from app.core.calculix import deck
from app.core.materials import Material
from app.core.spec import StaticSpec, parse_spec
from app.core.statics import static_plan
from app.modules.simulations import services


def _declared(analysis: dict[str, Any]) -> condition_model.Conditions:
    return condition_model.read({"conditions": {"analysis": analysis}}, recipe="static")


def test_CAD_가_적은_큰_변형과_초기_부단계_수를_읽는다() -> None:
    given = _declared({"type": "static", "large_deflection": True, "substeps": 20})
    assert given.analysis.large_deflection is True
    assert given.analysis.substeps == 20
    # 비운 부단계 · 안 적은 큰 변형은 「모른다」 다 — 거짓 · 0 으로 바꾸지 않는다.
    bare = _declared({"type": "static", "substeps": None})
    assert bare.analysis.large_deflection is None and bare.analysis.substeps is None


def test_사람이_적었으면_그것_비웠으면_CAD_것이다() -> None:
    cad_on = _declared({"type": "static", "large_deflection": True, "substeps": 20})
    spec = parse_spec({"recipe": "static", "mesh": {"element_size_mm": 2}})
    assert isinstance(spec, StaticSpec) and spec.large_deflection is None
    plan = static_plan(spec, cad_on)
    assert (plan.large_deflection, plan.substeps, plan.source) == (True, 20, "cad")

    off = parse_spec({"recipe": "static", "large_deflection": False})
    assert isinstance(off, StaticSpec)
    plan = static_plan(off, cad_on)
    assert (plan.large_deflection, plan.source) == (False, "spec")

    nothing = static_plan(spec, condition_model.Conditions())
    assert (nothing.large_deflection, nothing.source) == (False, "default")


def test_비운_큰_변형은_저장하지_않는다() -> None:
    """옛 워커는 `null` 을 참 · 거짓으로 못 읽는다 — 칸이 없으면 끈 것으로 읽는다."""
    blank = parse_spec({"recipe": "static", "mesh": {"element_size_mm": 2}})
    assert "large_deflection" not in services._stored_spec(blank)
    chosen = parse_spec({"recipe": "static", "large_deflection": True})
    assert services._stored_spec(chosen)["large_deflection"] is True


def test_초기_부단계_수가_비선형_단계의_첫_증분이다() -> None:
    nodes = {
        1: (0.0, 0.0, 0.0),
        2: (10.0, 0.0, 0.0),
        3: (0.0, 10.0, 0.0),
        4: (0.0, 0.0, 10.0),
    }
    steel = Material(
        name="SS400",
        bodies=("부품",),
        youngs_modulus_pa=200e9,
        poisson_ratio=0.3,
        density_kg_m3=7850,
        source="spec",
    )
    push = condition_model.Load(
        name="누름", kind="force", region="끝", magnitude=10.0, direction=(0, 0, -1)
    )
    given = condition_model.Conditions(
        constraints=[
            condition_model.Constraint(name="바닥", kind="fixed_support", region="바닥")
        ],
        loads=[push],
    )
    plan = deck.write_static(
        nodes=nodes,
        solids={1: [(1, [1, 2, 3, 4])]},
        body_of={"부품": 1},
        materials=[steel],
        held_nodes={"바닥": {1, 2, 3}},
        load_nodes={"끝": {4}},
        load_faces={},
        load_areas={"끝": {4: 1.0}},
        given=given,
        second_order=False,
        large_deflection=True,
        substeps=20,
    )
    assert "*STEP, NLGEOM\n*STATIC\n0.05, 1.0\n" in plan.text
