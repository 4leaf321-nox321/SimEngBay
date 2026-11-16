"""본딩(`calculix/bonding.py`) — 도구 없이 보는 것. 진짜 gmsh · ccx 쪽은
`tests/opensolver/test_bonding.py` 다."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import conditions as condition_model
from app.core.calculix import bonding
from app.core.calculix.bonding import (
    _distance,
    _linearized,
    _reported_gaps,
    near_nodes,
    slide_rows,
)
from app.core.calculix.deck import Slide, Tie

A, B, C = (0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 10.0, 0.0)


def test_점과_삼각형의_거리는_가장_가까운_곳까지다() -> None:
    assert _distance((2.0, 2.0, 0.3), A, B, C) == pytest.approx(0.3)  # 면 위
    assert _distance((-3.0, -4.0, 0.0), A, B, C) == pytest.approx(5.0)  # 꼭짓점 A
    assert _distance((5.0, -2.0, 0.0), A, B, C) == pytest.approx(2.0)  # 모서리 AB
    assert _distance((6.0, 6.0, 0.0), A, B, C) == pytest.approx(2.0**0.5)  # 빗변 BC


def test_반경_안의_절점만_고른다() -> None:
    nodes = {
        1: A,
        2: B,
        3: C,
        10: (2.0, 2.0, 0.004),
        11: (2.0, 2.0, 0.2),
        12: (20.0, 20.0, 0.0),
    }
    assert near_nodes(nodes, {10, 11, 12}, [(1, 2, 3)], 0.01) == {10}
    assert near_nodes(nodes, set(), [(1, 2, 3)], 0.01) == set()


def test_본딩_방식은_기본이_TIE_이고_옛_방식을_고를_수_있다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(bonding.BONDING_ENV, raising=False)
    assert bonding.bonding_mode() == "tie"
    monkeypatch.setenv(bonding.BONDING_ENV, "shared")
    assert bonding.bonding_mode() == "shared"
    monkeypatch.setenv(bonding.BONDING_ENV, "아무거나")
    assert bonding.bonding_mode() == "tie"


def test_CompCore_가_알린_틈은_쌍마다_가장_작은_것이다() -> None:
    topology = {
        "quality": {
            "contacts": [
                {"kind": "gap", "a": "프레임", "b": "커버", "size": 0.2},
                {"kind": "gap", "a": "커버", "b": "프레임", "size": 0.08},
                {"kind": "overlap", "a": "판", "b": "블록", "size": 0.01},
            ]
        }
    }
    assert _reported_gaps(topology) == {frozenset({"프레임", "커버"}): 0.08}
    assert _reported_gaps({}) == {}


def _contact(kind: str) -> condition_model.Contact:
    return condition_model.Contact(name="쌍", kind=kind, source="가", target="나")


def test_본딩이_아닌_접촉을_묶으면_무엇이_다른지_말한다() -> None:
    assert _linearized(_contact("bonded"), modal=True) is None
    # 모달의 마찰은 붙여 푼다 — Ansys 는 벌칙 강성만큼 물러 조금 낮다(실측 5.3%).
    assert "5.3%" in str(_linearized(_contact("frictional"), modal=True))
    assert "정적" in str(_linearized(_contact("frictional"), modal=False))
    # 미끄러짐으로 푼 무마찰 · no separation 은 Ansys 와 같다 — 할 말이 없다.
    assert _linearized(_contact("frictionless"), modal=True, sliding=True) is None
    assert _linearized(_contact("no_separation"), modal=False, sliding=True) is None
    # 강체와의 접촉이라 강체에 붙였으면 미끄러지지 못한다.
    assert "강체" in str(_linearized(_contact("frictionless"), modal=True))


def test_쌍마다_몇_절점이_묶였나를_ccx_로그로_센다(tmp_path: Path) -> None:
    """ccx 는 반경 밖의 종 절점에 「no tied MPC generated for node N … too far away」 를 찍는다
    —
    그것을 묶음의 종 절점에서 빼면 쌍마다 실제로 묶인 수다. 하나도 안 묶인 쌍은 경고한다(그
    바디는
    떨어진 채 풀렸다)."""
    ties = [
        Tie(
            contact="기둥-판",
            name="BOND1",
            slave_nodes=frozenset({1, 2, 3, 4}),
            master_faces=[],
            tolerance=2.5,
        ),
        Tie(
            contact="머리-위판",
            name="BOND2",
            slave_nodes=frozenset({5, 6}),
            master_faces=[],
            tolerance=0.1,
        ),
    ]
    bonding.write_ties(tmp_path, ties, ["bonded:롤러↔시편"])
    log = (
        " *WARNING in gentiedmpc: no tied MPC\n          generated for node            4\n"
        "          opposite master face found but\n          too far away; distance: 3.0\n"
        " *WARNING in gentiedmpc: no tied MPC\n          generated for node 5\n"
        " *WARNING in gentiedmpc: no tied MPC\n          generated for node 6\n"
    )
    found = bonding.connection_report(tmp_path, log)
    assert "기둥-판 3/4 절점(반경 2.5 mm)" in found["bonded_pairs"]
    assert "머리-위판 0/2 절점" in found["bonded_pairs"]
    assert "롤러↔시편 → 강체에 넣음" in found["bonded_pairs"]
    assert "머리-위판" in found["bond_warning"] and "기둥-판" not in found["bond_warning"]
    assert bonding.connection_report(tmp_path / "없음", log) == {}


def test_법선_구속식은_법선이_큰_자유도를_종속으로_둔다() -> None:
    """종 변위의 법선 성분 = 주 면 변위의 법선 성분(`*EQUATION`) — 접선은 자유다. 첫 항(종속)은
    법선 성분이 가장 큰 자유도여야 계수가 0 에 가깝지 않다. 한 줄에 넷까지."""
    slide = Slide(
        contact="블록-판",
        name="SLIDE1",
        rows=((7, (0.0, 0.6, 0.8), ((1, 0.5), (2, 0.5))),),
        tolerance=1.0,
    )
    lines = slide.lines()
    assert lines[0] == "*EQUATION"
    assert lines[1] == "6"  # 종 둘(y · z) + 주 절점 둘 x (y · z)
    assert lines[2].startswith("7, 3, 0.8, 7, 2, 0.6, 1, 2, -0.3")
    assert lines[3] == "2, 2, -0.3, 2, 3, -0.4"
    assert slide.slave_nodes == frozenset({7})


def test_종_절점을_가장_가까운_주_면에_2차_형상함수로_투영한다() -> None:
    nodes = {
        1: (0.0, 0.0, 0.0),
        2: (2.0, 0.0, 0.0),
        3: (0.0, 2.0, 0.0),
        4: (1.0, 0.0, 0.0),
        5: (1.0, 1.0, 0.0),
        6: (0.0, 1.0, 0.0),
        10: (1.0, 0.0, 0.05),  # 모서리 (1-2) 가운데 위 — 중간 절점 4 의 몫이 1
        11: (5.0, 5.0, 0.0),  # 반경 밖
    }
    rows = slide_rows(nodes, {10, 11}, [[1, 2, 3, 4, 5, 6]], 0.1)
    assert [row[0] for row in rows] == [10]
    _, normal, masters = rows[0]
    assert normal == pytest.approx((0.0, 0.0, 1.0))
    weights = dict(masters)
    assert weights[4] == pytest.approx(1.0)
    assert sum(weights.values()) == pytest.approx(1.0)
