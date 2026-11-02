"""맞닿은 마찰면 — 메시를 나눈 채 **그 면만 가른다**(`build._open_interfaces`).

본딩은 절점 공유로 붙고 접촉 쌍은 마찰면 하나다. 셋 다 접촉 쌍으로 걸던 볼트 조립(본딩 둘 + 판
사이 마찰)은 첫 증분조차 12분에 못 넘었다(2026-10-29). 끝까지 푸는 것은 `tests/opensolver` 가
본다.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core import conditions as condition_model
from app.core.calculix import deck
from app.core.calculix.build import _average_force, _on_surface, _open_interfaces, _touching

#: 사면체 둘이 z=0 의 면 1-2-3 을 나눠 쓴다 — 위(4)는 「위」, 아래(5)는 「아래」 바디.
NODES = {
    1: (0.0, 0.0, 0.0),
    2: (10.0, 0.0, 0.0),
    3: (0.0, 10.0, 0.0),
    4: (0.0, 0.0, 10.0),
    5: (0.0, 0.0, -10.0),
}
SOLIDS = {1: [(1, [1, 2, 3, 4])], 2: [(2, [1, 3, 2, 5])]}
BODY_OF = {"위": 1, "아래": 2}
FACE = {"centroid": [10 / 3, 10 / 3, 0.0], "area": 50.0}
TOPOLOGY: dict[str, Any] = {
    "regions": {
        "위 밑": [{**FACE, "normal": [0, 0, -1], "body": "위"}],
        "아래 위": [{**FACE, "normal": [0, 0, 1], "body": "아래"}],
    },
    "bodies": [{"name": "위", "bbox": [[0, 0, 0], [10, 10, 10]]}],
}
SLIDE = condition_model.Contact(
    name="판-판", kind="frictional", source="위 밑", target="아래 위", friction=0.2
)


def test_맞닿은_마찰면만_원본_쪽_바디에서_새_절점으로_가른다() -> None:
    nodes, solids, faces, renamed = _open_interfaces(TOPOLOGY, [SLIDE], NODES, SOLIDS, BODY_OF)
    # 면의 절점 셋이 같은 자리에 새 번호(6 · 7 · 8)로 생기고, 「위」 의 요소만 그것을 쓴다.
    assert {number: nodes[number] for number in (6, 7, 8)} == {
        6: NODES[1],
        7: NODES[2],
        8: NODES[3],
    }
    assert solids[1] == [(1, [6, 7, 8, 4])]
    assert solids[2] == SOLIDS[2]
    # 두 쪽의 요소면이 짝 맞는 접촉면이 된다.
    assert faces == {"위 밑": [(1, "P1")], "아래 위": [(2, "P1")]}
    # 측정점이 「위」 의 새 절점을 읽도록 바꾼 번호를 돌려준다(`probes.locate`).
    assert renamed == {"위": {1: 6, 2: 7, 3: 8}}


def test_맞닿지_않거나_강체거나_한_바디면_가르지_않는다() -> None:
    given = condition_model.Conditions(contacts=[SLIDE])
    assert _touching(TOPOLOGY, [SLIDE], given)
    # 넓이가 다르면 다른 면이다(한쪽이 더 넓게 걸친 접촉).
    wider = {
        "regions": {
            **TOPOLOGY["regions"],
            "아래 위": [{**FACE, "area": 80.0, "normal": [0, 0, 1], "body": "아래"}],
        }
    }
    assert not _touching(wider, [SLIDE], given)
    # 강체 파트의 면은 전처럼 접촉 쌍으로 건다(강체 절점은 독립 쪽).
    held = condition_model.Conditions(
        contacts=[SLIDE], body_settings=[condition_model.BodySetting(name="아래", rigid=True)]
    )
    assert not _touching(TOPOLOGY, [SLIDE], held)


def test_수렴_판정의_평균_힘은_가장_큰_힘_하중의_백분의_일() -> None:
    """ccx 가 셈하는 평균 힘은 볼트 근처만 힘을 받는 조립에서 아주 작다(0.009 N) — 그대로 두면
    접촉면이 흔드는 잔차를 못 넘는다. 볼트 예압의 힘도 센다."""
    bolt = condition_model.Load(
        name="볼트", kind="bolt_pretension", region="몸통", preload=1.0, unit="kN"
    )
    lift = condition_model.Load(
        name="끌어올림", kind="force", region="윗면", magnitude=600.0, direction=(0, 0, 1)
    )
    given = condition_model.Conditions(loads=[bolt, lift])
    assert _average_force(given) == pytest.approx(10.0)
    tightened = condition_model.Load(
        name="볼트", kind="bolt_pretension", region="몸통", preload=0.0025, unit="mm"
    )
    assert _average_force(
        condition_model.Conditions(loads=[tightened, lift])
    ) == pytest.approx(6.0)
    assert _average_force(condition_model.Conditions(loads=[tightened])) is None


def test_평균_힘을_주면_비선형_단계마다_그_값으로_판정한다() -> None:
    plan = deck.write_static(
        nodes=NODES,
        solids=SOLIDS,
        body_of=BODY_OF,
        materials=[],
        held_nodes={"아래 위": {5}},
        load_nodes={},
        load_faces={},
        load_areas={},
        given=condition_model.Conditions(
            constraints=[
                condition_model.Constraint(name="고정", kind="fixed_support", region="아래 위")
            ],
            contacts=[SLIDE],
            loads=[
                condition_model.Load(
                    name="밂", kind="force", region="위", magnitude=1.0, direction=(0, 0, -1)
                )
            ],
        ),
        contact_faces={"위 밑": [(1, "P1")], "아래 위": [(2, "P1")]},
        second_order=False,
        pairing="NODE TO SURFACE",
        average_force=10.0,
    )
    assert "*CONTACT PAIR, INTERACTION=C0I, TYPE=NODE TO SURFACE" in plan.text
    # 절점-면은 떨어진 뒤의 인장을 작게 준다(강성 x 1e-9 mm) — 비우면 ccx 가 큰 값을 써 면이
    # 본딩처럼 붙는다(실측: 볼트 힘 +10.6 N, Ansys 마찰 +66.2 N).
    assert (
        "*SURFACE BEHAVIOR, PRESSURE-OVERCLOSURE=LINEAR\n2e+06, 0.002\n*FRICTION" in plan.text
    )
    assert (
        "*STEP, NLGEOM\n*CONTROLS, PARAMETERS=FIELD\n"
        "0.005, 0.01, , 10, 0.02, 1e-5, 1e-3, 1e-8\n*STATIC\n0.1, 1.0"
    ) in plan.text


def test_반쪽_원통_접촉면은_축_위의_점에서_반지름을_잰다() -> None:
    """원통 접촉면의 절점은 축까지의 거리가 반지름인 것이다. 반쪽 원통면의 경계상자 중심은
    축에서 r/2 비켜 있어, 거기서 재면 면 위의 절점이 하나도 안 잡힌다(`axis_at`)."""
    shape = {"centroid": [0.0, 2.5, 0.0], "radius": 5.0, "axis": [0.0, 0.0, 1.0]}
    on = _on_surface({**shape, "axis_at": [0.0, 0.0, 0.0]}, 0.01)
    assert on((5.0, 0.0, 3.0)) and on((0.0, 5.0, -2.0))
    assert not on((0.0, 2.5, 0.0))
    assert not _on_surface(shape, 0.01)((5.0, 0.0, 3.0))
