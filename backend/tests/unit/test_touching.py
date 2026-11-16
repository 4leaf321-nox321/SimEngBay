"""**맞닿은 바디 쌍**(`app/core/touching.py`) — CompCore 의 `quality.touching` 으로 접촉 없이
맞닿은 쌍을 고른다(CompCore `411247f`, 2026-11-16). 두 쪽이 같은 쌍을 말해야 한다."""

from __future__ import annotations

from typing import Any

from app.core import conditions as condition_model
from app.core import touching


def _contact(name: str, source: str, target: str, kind: str = "bonded") -> Any:
    return condition_model.Contact(name=name, kind=kind, source=source, target=target)


TOPOLOGY: dict[str, Any] = {
    "regions": {
        "판 윗면": [{"centroid": [0, 0, 3], "body": "판"}],
        "받침 바닥": [{"centroid": [0, 0, 3], "body": "받침"}],
        "받침 윗면": [{"centroid": [0, 0, 13], "body": "받침"}],
        "덮개 바닥": [{"centroid": [0, 0, 13], "body": "덮개"}, {"body": "덮개"}],
    },
    "quality": {
        "touching": [
            {"a": "판", "b": "받침", "area": 400.0, "at": [0.0, 0.0, 3.0]},
            {"a": "받침", "b": "덮개", "area": 400.0, "at": [0.0, 0.0, 13.0]},
            {"a": "판", "b": "나사", "area": None, "at": [5.0, 5.0, 0.0]},
        ]
    },
}


def _given(*contacts: Any, suppressed: frozenset[str] = frozenset()) -> Any:
    return condition_model.Conditions(
        contacts=list(contacts),
        body_settings=[
            condition_model.BodySetting(name=name, suppressed=True) for name in suppressed
        ],
    )


def test_접촉을_건_점에서_접촉_없이_맞닿은_쌍을_고른다() -> None:
    given = _given(_contact("판-받침", "판 윗면", "받침 바닥"))
    found = touching.uncovered(TOPOLOGY, given)
    assert found == [
        {"a": "받침", "b": "덮개", "area": 400.0, "at": [0.0, 0.0, 13.0]},
        {"a": "판", "b": "나사", "area": None, "at": [5.0, 5.0, 0.0]},
    ]
    # 해석 제외 파트가 낀 쌍은 뺀다(CompCore 와 같다).
    left = touching.uncovered(
        TOPOLOGY, _given(*given.contacts, suppressed=frozenset({"나사"}))
    )
    assert [(one["a"], one["b"]) for one in left or []] == [("받침", "덮개")]
    # 접촉 종류와 상관없이 선언한 쌍은 덮인다.
    both = _given(
        *given.contacts, _contact("받침-덮개", "덮개 바닥", "받침 윗면", "frictionless")
    )
    assert [(one["a"], one["b"]) for one in touching.uncovered(TOPOLOGY, both) or []] == [
        ("판", "나사")
    ]


def test_접촉을_안_걸었거나_목록이_없으면() -> None:
    # 접촉이 없으면 말하지 않는다 — CalculiX 는 맞닿은 바디를 묶고 Mechanical 은 자동 접촉이다.
    assert touching.uncovered(TOPOLOGY, _given()) == []
    # 목록이 없는 옛 점 파일 — None(CalculiX 는 메시에서 잰다).
    plain = {"regions": TOPOLOGY["regions"], "quality": {"contacts": []}}
    assert (
        touching.uncovered(plain, _given(_contact("판-받침", "판 윗면", "받침 바닥"))) is None
    )


def test_미끄럼으로_푸는_접촉과_그_바디() -> None:
    contacts = [
        _contact("판-받침", "판 윗면", "받침 바닥"),
        _contact("받침-덮개", "덮개 바닥", "받침 윗면", "no_separation"),
        _contact("판-덮개", "판 윗면", "덮개 바닥", "frictionless"),
    ]
    modal = touching.sliding(TOPOLOGY, contacts, modal=True)
    assert [(one["contact"], one["bodies"]) for one in modal] == [
        ("받침-덮개", ["덮개", "받침"]),
        ("판-덮개", ["판", "덮개"]),
    ]
    # 정적의 마찰 없음은 진짜 접촉이다 — 미끄럼 구속이 아니다.
    assert [one["contact"] for one in touching.sliding(TOPOLOGY, contacts, modal=False)] == [
        "받침-덮개"
    ]
    # 단품(지문에 `body` 가 없다)은 바디 없이.
    assert touching.contact_bodies({}, contacts[1]) == []


def test_요약_한_줄() -> None:
    line = touching.line(
        [
            {"a": "받침", "b": "덮개", "area": 400.0, "at": [0.0, 12.5, 30.0]},
            {"a": "판", "b": "나사", "nodes": 3, "at": [1.25, -2.0, 0.5]},
            {"a": "판", "b": "핀", "area": None, "at": None},
        ]
    )
    assert line == (
        "받침 ↔ 덮개 (넓이 400 mm² · 자리 (0, 12.5, 30) mm) · 판 ↔ 나사 (절점 3 · 자리 "
        "(1.25, -2, 0.5) mm) · 판 ↔ 핀"
    )
