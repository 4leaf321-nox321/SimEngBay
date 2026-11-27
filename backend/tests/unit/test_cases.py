"""해석 케이스(v2) → 작업 하나의 조건(`app/core/cases.py`).

- 케이스는 사슬로 갈리고 사슬 하나가 작업 하나다(끝 케이스의 해석 종류가 레시피).
- v1 으로 **정확히 접히는** 사슬은 보기 안에서 v1 길로 푼다 — 접은 보기를 읽은 조건이 같은
모델의
  v1 픽스처를 읽은 것과 같아야 한다(CompCore 의 「v2 사슬 픽스처」, 2026-11-27).
- 받는 쪽 첫 판의 사슬 규칙은 사슬마다 까닭을 달아 막는다.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.core import cases, conditions

DOE = Path(__file__).resolve().parents[1] / "fixtures" / "doe"


def _point(folder: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (DOE / folder / "points" / "p0001.json").read_text(encoding="utf-8")
    )
    return loaded


def _chains(folder: str) -> list[cases.Chain]:
    found, broken = cases.chains(_point(folder))
    assert not broken
    return found


def _chain(payload: dict[str, Any], name: str) -> cases.Chain:
    found, broken = cases.chains(payload)
    assert not broken, broken
    return next(one for one in found if one.name == name)


def _read(folder: str, name: str) -> conditions.Conditions:
    payload = _point(folder)
    chain = _chain(payload, name)
    assert cases.problem(chain) == ""
    return conditions.read(cases.view(payload, chain), recipe=chain.kind)


def _same(got: conditions.Conditions, want: conditions.Conditions) -> None:
    """작업이 실제로 거는 것 — 구속 · 접촉 · 하중 · 해석 설정 · 파트 설정 · 막은 것."""
    assert got.constraints == want.constraints
    assert got.contacts == want.contacts
    assert got.loads == want.loads
    assert got.analysis == want.analysis
    assert got.body_settings == want.body_settings
    assert got.mesh_hints == want.mesh_hints
    assert got.refused == want.refused == []


@pytest.mark.parametrize(
    ("folder", "shape"),
    [
        ("조건_볼트예압_사슬_정적모달", [(["정적", "모달"], "modal")]),
        ("조건_볼트예압_사슬_세케이스", [(["예압", "외력", "모달"], "modal")]),
        ("조건_볼트예압_사슬_둘", [(["모달 단독"], "modal"), (["예압", "외력"], "static")]),
        ("조건_외팔보_두케이스", [(["힘 A", "힘 B"], "static")]),
        ("조건_볼트예압_두케이스_솔버없음", [(["예압", "외력"], "static")]),
    ],
)
def test_케이스는_사슬로_갈리고_끝_케이스가_레시피다(
    folder: str, shape: list[tuple[list[str], str]]
) -> None:
    got = [([one.name for one in chain.cases], chain.kind) for chain in _chains(folder)]
    assert got == shape


@pytest.mark.parametrize(
    "folder", ["조건_볼트예압_사슬_정적모달", "조건_볼트예압_사슬_세케이스"]
)
def test_정적_뒤의_모달은_v1_선응력_모달과_같은_조건이다(folder: str) -> None:
    """「정적」(볼트 1000 N + 끌어올림 600 N) → 「모달」 = v1 「조건_볼트예압_선응력모달」
    점 1. 세 케이스(「예압」 → 「외력」 → 「모달」)도 같다 — 볼트만 조이는 「예압」 은 v1 의
    ① 이다."""
    got = _read(folder, "모달")
    want = conditions.read(_point("조건_볼트예압_선응력모달"), recipe="modal")
    assert got.analysis.prestressed and got.prestressed
    assert [one.kind for one in got.loads] == ["bolt_pretension", "force"]
    _same(got, want)


@pytest.mark.parametrize(
    "folder",
    ["조건_볼트예압_두케이스", "조건_볼트예압_두케이스_솔버없음", "조건_볼트예압_사슬_둘"],
)
def test_예압_뒤의_외력은_v1_볼트_정적과_같은_조건이다(folder: str) -> None:
    """「예압」 → 「외력」 = v1 「조건_볼트예압_정적」 점 1(하중 = 예압 + 외력, 정적 두
    단계)."""
    got = _read(folder, "외력")
    want = conditions.read(_point("조건_볼트예압_정적"), recipe="static")
    assert [one.kind for one in got.loads] == ["bolt_pretension", "force"]
    _same(got, want)


def test_무관한_케이스는_따로_선다() -> None:
    alone = _read("조건_볼트예압_사슬_둘", "모달 단독")
    assert not alone.loads and not alone.analysis.prestressed
    assert len(alone.constraints) == 1


def test_보기는_판_1_이고_어느_사슬인지_적는다() -> None:
    payload = _point("조건_볼트예압_사슬_세케이스")
    chain = _chain(payload, "모달")
    viewed = cases.view(payload, chain)
    block = viewed["conditions"]
    assert block["schema_version"] == 1 and "cases" not in block
    assert block["case"] == {"name": "모달", "chain": ["예압", "외력", "모달"], "solver": ""}
    assert cases.picked(viewed) == "모달" and cases.picked(payload) is None
    assert viewed["regions"] == payload["regions"] and viewed["bodies"] == payload["bodies"]
    assert not cases.is_cases(viewed)


def test_정적_다단은_앞_정적_케이스를_단계로_편다() -> None:
    """볼트가 아닌 앞 정적(외팔보 「힘 A」 → 「힘 B」) — v1 으로 접히지 않아 단계로 편다.
    하중은
    이어지지 않는다: 맨 위는 「힘 B」 의 하중뿐이고 「힘 A」 는 단계에 있다."""
    payload = _point("조건_외팔보_두케이스")
    [chain] = _chains("조건_외팔보_두케이스")
    assert cases.problem(chain) == ""
    viewed = cases.view(payload, chain)
    assert [one["name"] for one in viewed["conditions"]["stages"]] == ["힘 A"]
    given = conditions.read(viewed, recipe="static")
    assert [one.name for one in given.loads] == ["B"]
    assert [(one.name, [load.name for load in one.loads]) for one in given.stages] == [
        ("힘 A", ["A"])
    ]
    assert [(one.name, [load.name for load in one.loads]) for one in given.static_cases()] == [
        ("힘 A", ["A"]),
        ("힘 B", ["B"]),
    ]
    assert given.case == "힘 B" and not given.refused


def test_케이스마다_큰_변형이_다르면_막는다() -> None:
    payload = copy.deepcopy(_point("조건_외팔보_두케이스"))
    payload["conditions"]["cases"][1]["analysis"]["large_deflection"] = True
    [chain] = cases.chains(payload)[0]
    assert "큰 변형" in cases.problem(chain)


def _two(**change: Any) -> dict[str, Any]:
    """「예압」 → 「외력」(두케이스_솔버없음)을 고친 것."""
    payload = copy.deepcopy(_point("조건_볼트예압_두케이스_솔버없음"))
    first, second = payload["conditions"]["cases"]
    for key, value in change.items():
        where, field = key.split("__")
        target = first if where == "first" else second
        if callable(value):
            value(target[field])
        else:
            target[field] = value
    return payload


GRAVITY = {"name": "중력", "type": "standard_earth_gravity", "direction": [0, 0, -1], "cs": ""}


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (
            {"second__analysis": {"type": "modal", "prestressed": True}},
            "앞 케이스(정적)를 지정해",
        ),
        (
            {"second__initial": [{"type": "prestress"}]},
            "앞 케이스(정적)를 지정해",
        ),
        ({"first__analysis": {"type": "modal"}}, "앞 케이스는 정적 구조"),
        ({"second__analysis": {"type": "harmonic"}}, "정적 → 조화 응답"),
        ({"second__target": {"solver": "ansys"}}, "대상 솔버가 다릅니다"),
        ({"second__constraints": []}, "구속이 앞 케이스와 다릅니다"),
        (
            {
                "second__loads": lambda rows: rows.append(
                    dict(_point("조건_볼트예압_정적")["conditions"]["loads"][0])
                )
            },
            "예압을 다시 적었습니다",
        ),
        (
            {"first__loads": lambda rows: rows.append(dict(GRAVITY))},
            "중력이 앞 정적과 다릅니다",
        ),
        (
            {"second__initial": [{"type": "environment_temperature", "value": 80}]},
            "초기조건이 첫 케이스와 다릅니다",
        ),
    ],
    ids=[
        "케이스의 선응력 켬",
        "케이스의 초기조건 선응력",
        "앞이 정적이 아님",
        "정적 뒤의 조화",
        "대상 솔버가 다름",
        "구속이 다름",
        "볼트를 다시 조임",
        "정적끼리 중력이 다름",
        "뒤 케이스의 초기조건",
    ],
)
def test_사슬의_규칙은_까닭을_달아_막는다(change: dict[str, Any], said: str) -> None:
    payload = _two(**change)
    found, broken = cases.chains(payload)
    assert not broken
    assert said in cases.problem(found[-1])


def _with_modal(loads: list[dict[str, Any]]) -> dict[str, Any]:
    payload = copy.deepcopy(_point("조건_볼트예압_사슬_정적모달"))
    payload["conditions"]["cases"][1]["loads"] = loads
    return payload


def test_모달의_중력은_없거나_앞_정적과_같아야_한다() -> None:
    """모드 해석 케이스는 중력을 적지 않아도 된다(앞 정적의 끝 상태에 있다) — 적었으면
    같아야."""
    base = copy.deepcopy(_point("조건_볼트예압_사슬_정적모달"))
    for row in base["conditions"]["cases"]:
        row["loads"] = (
            [*row["loads"], dict(GRAVITY)] if row["name"] == "정적" else row["loads"]
        )
    assert cases.problem(_chain(base, "모달")) == ""
    same = copy.deepcopy(base)
    same["conditions"]["cases"][1]["loads"] = [dict(GRAVITY)]
    assert cases.problem(_chain(same, "모달")) == ""
    other = copy.deepcopy(base)
    other["conditions"]["cases"][1]["loads"] = [{**GRAVITY, "direction": [0, 0, 1]}]
    assert "중력이 앞 정적과 다릅니다" in cases.problem(_chain(other, "모달"))
    # 접으면 중력은 앞 정적의 것 한 번이다.
    folded = conditions.read(cases.view(same, _chain(same, "모달")), recipe="modal")
    assert [one.kind for one in folded.loads].count("standard_earth_gravity") == 1


def test_앞_정적_뒤의_모달에는_하중을_적지_않는다() -> None:
    payload = _with_modal([{"name": "누름", "type": "force", "on": "x", "magnitude": 1}])
    assert "하중을 적지 않습니다" in cases.problem(_chain(payload, "모달"))


def single(folder: str, name: str = "하나") -> dict[str, Any]:
    """v1 점 파일을 **케이스 하나인 v2** 로 — CompCore 가 ② 칸을 쓴 케이스는 하나여도 v2 로
    낸다."""
    payload = copy.deepcopy(_point(folder))
    block = payload["conditions"]
    case = {key: block.pop(key) for key in cases.CASE_KEYS if key in block}
    block["schema_version"] = 2
    block["cases"] = [{"name": name, "depends_on": "", "target": {"solver": ""}, **case}]
    return payload


@pytest.mark.parametrize(
    ("folder", "recipe"),
    [
        ("조건_볼트예압_정적", "static"),
        ("조건_사인스윕", "harmonic"),
        ("조건_랜덤진동", "random"),
    ],
)
def test_케이스가_하나뿐인_v2_는_v1_과_같은_조건이다(folder: str, recipe: str) -> None:
    payload = single(folder)
    [chain] = _chains_of(payload)
    assert chain.kind == recipe and cases.problem(chain) == ""
    got = conditions.read(cases.view(payload, chain), recipe=recipe)
    want = conditions.read(_point(folder), recipe=recipe)
    _same(got, want)
    assert got.psd == want.psd


def _chains_of(payload: dict[str, Any]) -> list[cases.Chain]:
    found, broken = cases.chains(payload)
    assert not broken
    return found
