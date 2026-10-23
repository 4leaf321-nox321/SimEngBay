"""DOE 분석 — 화면의 「다변수」 탭과 같은 표에서 **서버가 셈한다**(MCP `study_analyze`).

AI 가 설계점 200개를 받아 평균 · 상관을 손으로 내면 문맥을 다 먹고 틀리기 쉽다. 여기서는 손으로
셈할 수 있는 작은 표로 셈이 맞는지 본다.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.simulations import analysis
from app.modules.simulations.schemas import ModeTrackOut, StudyOut, StudyPointOut


def _point(number: int, params: dict[str, float | str], **values: Any) -> StudyPointOut:
    return StudyPointOut(
        simulation_id=uuid.uuid4(),
        number=number,
        params=params,
        status=values.pop("status", "done"),
        recipe=values.pop("recipe", "static"),
        **values,
    )


def _study(points: list[StudyPointOut], **extra: Any) -> StudyOut:
    return StudyOut(
        study_id="s",
        name="브래킷",
        factors=extra.pop("factors", ["두께", "폭"]),
        recipe=extra.pop("recipe", "static"),
        points=points,
        **extra,
    )


#: 2 x 2 전 조합 — 두께가 변형을 크게(4 → 2), 폭은 작게(± 0.5) 움직인다.
FULL = [
    _point(
        1, {"두께": 2, "폭": 10}, max_displacement_mm=4.5, max_von_mises_mpa=150, mass_kg=0.2
    ),
    _point(
        2, {"두께": 3, "폭": 10}, max_displacement_mm=2.5, max_von_mises_mpa=110, mass_kg=0.3
    ),
    _point(
        3, {"두께": 2, "폭": 20}, max_displacement_mm=3.5, max_von_mises_mpa=120, mass_kg=0.4
    ),
    _point(
        4, {"두께": 3, "폭": 20}, max_displacement_mm=1.5, max_von_mises_mpa=90, mass_kg=0.6
    ),
    _point(5, {"두께": 4, "폭": 20}, status="failed"),
]


def test_주효과와_민감도_차례() -> None:
    found = analysis.analyze(_study(FULL), result="max_mm")
    assert (found.done, found.total) == (4, 5)
    thickness = next(one for one in found.effects if one.factor == "factor:두께")
    assert [(one.level, one.mean, one.count) for one in thickness.levels] == [
        (2, 4.0, 2),
        (3, 2.0, 2),
    ]
    assert thickness.spread == 2.0
    # 결과 평균 3 mm 에 견준 폭 — 2/3 = 66.67 %.
    assert thickness.spread_pct == pytest.approx(66.67, abs=0.01)
    assert thickness.correlation is not None and thickness.correlation < -0.8
    # **어느 변수가 가장 많이 움직이나** — 폭이 큰 차례.
    ranking = found.sensitivity[0].factors
    assert [one.factor for one in ranking] == ["factor:두께", "factor:폭"]
    assert found.ranges[0].min_point == 4 and found.ranges[0].max_point == 1


def test_조건을_만족하는_점_중_목표가_가장_좋은_점() -> None:
    found = analysis.analyze(
        _study(FULL), objective="mass_kg", goal="min", where=["max_mpa<=120", "max_mm<4"]
    )
    choice = found.choice
    assert choice is not None
    # 1번은 150 MPa, 나머지 셋이 120 이하 — 그중 4 mm 미만은 2 · 3 · 4번, 가장 가벼운 것은 2번.
    assert choice.feasible == 3
    assert choice.best is not None and choice.best.number == 2
    assert [one.number for one in choice.ranked] == [2, 3, 4]
    assert choice.best.values == {"max_mpa": 110, "max_mm": 2.5, "mass_kg": 0.3}


def test_모달은_순번이_아니라_추적한_모드로_센다() -> None:
    """2번 점에서는 기준의 1차 모드가 2번째로 내려앉았다(mode crossing)."""
    points = [
        _point(1, {"두께": 2, "폭": 1}, recipe="modal", frequencies=[100, 200]),
        _point(2, {"두께": 3, "폭": 1}, recipe="modal", frequencies=[150, 180]),
    ]
    track = ModeTrackOut(reference=1, numbers={1: 1, 2: 2}, confidence={1: 1, 2: 0.9})
    found = analysis.analyze(_study(points, recipe="modal", tracks=[track]), result="mode:1")
    assert found.ranges[0].min == 100 and found.ranges[0].max == 180


def test_수준이_많은_변수는_다섯_구간으로_묶는다() -> None:
    """LHS 처럼 점마다 값이 다르면 점 하나짜리 수준 20개의 평균은 효과가 아니라 잡음이다."""
    points = [
        _point(n, {"두께": 1 + n * 0.1, "폭": 1}, max_displacement_mm=10 - n * 0.3)
        for n in range(1, 21)
    ]
    found = analysis.analyze(_study(points), result="max_mm")
    thickness = next(one for one in found.effects if one.factor == "factor:두께")
    assert len(thickness.levels) == 5 and all(one.count == 4 for one in thickness.levels)
    # 화면(`studyTable.ts` 의 `mainEffect`)과 같은 구간 · 같은 글자다.
    assert thickness.levels[0].level == "1.1~1.4"
    assert any("구간" in one for one in found.notes)


def test_두_변수_격자는_빈_칸을_메우지_않는다() -> None:
    found = analysis.analyze(_study(FULL[:3]), result="max_mm", x="factor:두께", y="factor:폭")
    assert found.pair is not None
    assert found.pair.z == [[4.5, 2.5], [3.5, None]]
    assert found.pair.complete is False


def test_모르는_열과_못_읽는_조건은_쓸_수_있는_열을_말한다() -> None:
    with pytest.raises(ValueError, match="쓸 수 있는 열: factor:두께"):
        analysis.analyze(_study(FULL), objective="무게")
    with pytest.raises(ValueError, match="꼴입니다"):
        analysis.parse_condition("max_mpa")
    with pytest.raises(ValueError, match="숫자여야"):
        analysis.parse_condition("max_mpa<=많이")
    # 범주 변수는 같음으로 고른다.
    assert analysis.parse_condition("factor:재료=SS400").holds("SS400")
