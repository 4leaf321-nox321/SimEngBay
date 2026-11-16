"""**0 Hz 모드** — 구속이 있어도 강체 모드로 세고, 움직이는 바디와 까닭을 말한다
(`app/core/modes/rigid.py`, 2026-11-16 — CompCore 의 조립 점검).

전에는 바닥을 고정한 조립에서 덮개 하나가 떠 있으면 「강체 모드 0개 · 1차 탄성 0 Hz」 였다.
"""

from __future__ import annotations

from typing import Any

from app.core.modes import rigid


def _mode(number: int, hz: float, **extra: Any) -> dict[str, Any]:
    return {"number": number, "frequency_hz": hz, "rigid_body": rigid.is_rigid(hz), **extra}


def test_문턱_아래는_구속과_상관없이_강체_모드다() -> None:
    assert rigid.is_rigid(0.0) and rigid.is_rigid(0.0023) and rigid.is_rigid(-0.01)
    assert not rigid.is_rigid(1.0) and not rigid.is_rigid(1282.0)


def test_구속이_있는데_0_Hz_면_움직이는_바디와_빠진_접촉을_짚는다() -> None:
    modes = [
        _mode(1, 0.0, part_share={"판": 0.0, "받침": 0.01, "덮개": 0.99}),
        _mode(2, 0.0, part_share={"판": 0.0, "받침": 0.3, "덮개": 0.7}),
        _mode(3, 34738.0, part_share={"판": 0.2, "받침": 0.7, "덮개": 0.1}),
    ]
    assert rigid.moving_bodies(modes) == ["덮개", "받침"]
    connections = {
        "untied": [
            {"a": "받침", "b": "덮개", "nodes": 41, "at": [0, 0, 30]},
            {"a": "판", "b": "나사", "nodes": 3, "at": [0, 0, 0]},
        ],
        "sliding": [{"contact": "판-받침", "kind": "no_separation", "bodies": ["판", "받침"]}],
    }
    said = rigid.warning(modes, constrained=True, connections=connections)
    assert said is not None
    assert said.startswith("구속이 있는데 0 Hz 모드가 2개입니다")
    assert "움직이는 바디: 덮개, 받침." in said
    # 움직인 바디가 낀 것만 — 「판 ↔ 나사」 는 이 모드와 상관없다.
    assert "받침 ↔ 덮개" in said and "나사" not in said
    assert "「판-받침」" in said


def test_까닭을_모르면_열어_둔_방향부터_보라고_한다() -> None:
    said = rigid.warning([_mode(1, 0.0), _mode(2, 2165.2)], constrained=True)
    assert said is not None and "0 Hz 모드가 1개" in said and "원통 지지의 접선" in said
    assert rigid.warning([_mode(1, 2165.2)], constrained=True) is None


def test_자유_자유는_강체_모드가_6개가_아니면_말한다() -> None:
    six = [_mode(number, 0.0) for number in range(1, 7)] + [_mode(7, 2583.0)]
    assert rigid.warning(six, constrained=False) is None
    # 바디 둘이 떨어지면 12개 — 앞 6개만 세던 상한이 있으면 이 경고가 안 섰다.
    twelve = [_mode(number, 0.0) for number in range(1, 13)]
    said = rigid.warning(
        twelve,
        constrained=False,
        connections={"untied": [{"a": "판", "b": "덮개", "nodes": 9, "at": [0, 0, 0]}]},
    )
    assert said is not None and "12개" in said and "판 ↔ 덮개" in said
