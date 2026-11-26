"""CompCore 가 **잘못 걸렸다고 판정한 접촉**은 걸지 않는다(`quality.misplaced_contacts`).

CompCore 의 접촉 자동 찾기가 면의 중심으로 규칙을 지어(v0.26.0 ~ v0.31.0) 본딩 면이 딴 면에
걸렸다. 면 지문은 그 딴 면과 맞아 우리 짝짓기는 성공한다 — CompCore v0.31.1 이 판정을 실어
보내고(2026-11-26), 우리는 그 접촉을 「막음」 으로 올린다(작업 만들기 · DOE 가져오기 · 두
솔버의 모델링이 그 말로 멈춘다).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.core import conditions
from app.core.calculix import build as calculix_build
from app.core.spec import parse_spec
from app.core.stages import StageFailure

BOLT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "doe"
    / "조건_볼트예압_정적"
    / "points"
    / "p0001.json"
)


def _flagged(*rows: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(BOLT.read_text(encoding="utf-8"))
    payload["quality"]["misplaced_contacts"] = list(rows)
    return payload


SCREW = {
    "name": "나사 물림",
    "type": "bonded",
    "source": "물린 몸통",
    "target": "물린 구멍",
    "problem": "same_face",
}


def test_판정이_없으면_지금처럼_건다() -> None:
    plain = conditions.read(json.loads(BOLT.read_text(encoding="utf-8")), recipe="static")
    assert not plain.refused and len(plain.contacts) == 3
    assert not conditions.read(_flagged(), recipe="static").refused, "빈 목록"


@pytest.mark.parametrize(
    ("problem", "said"), [("same_face", "같은 면"), ("apart", "맞닿아 있지 않습니다")]
)
def test_판정된_접촉만_막고_나머지는_읽는다(problem: str, said: str) -> None:
    found = conditions.read(_flagged({**SCREW, "problem": problem}), recipe="static")
    assert [one.what for one in found.refused] == ["접촉 「나사 물림」"]
    why = found.refused[0].why
    assert said in why and "물린 몸통" in why and "CompCore 에서" in why
    assert [one.name for one in found.contacts] == ["머리-위판", "판-판"]
    assert len(found.constraints) == 1 and len(found.loads) == 2


def test_조건에_없는_접촉의_판정도_막는다() -> None:
    """두 목록이 어긋났다(이름이 다르다) — 모르는 채로 풀지 않는다."""
    found = conditions.read(_flagged({**SCREW, "name": "옛 이름"}), recipe="static")
    assert [one.what for one in found.refused] == ["접촉 「옛 이름」"]
    assert len(found.contacts) == 3


def test_모르는_판정도_막는다() -> None:
    found = conditions.read(_flagged({**SCREW, "problem": "twisted"}), recipe="static")
    assert "twisted" in found.refused[0].why


@pytest.mark.parametrize("conditions_from", ["cad", "spec"])
def test_모델링은_CAD_조건을_쓸_때만_멈춘다(tmp_path: Path, conditions_from: str) -> None:
    """CAD 조건을 끄면 그 접촉을 안 쓴다 — 선언이 없으니 맞닿은 바디를 메시에서 찾아 묶는다
    (`bonding.py`)."""
    (tmp_path / "input.step").write_text("ISO-10303-21;", encoding="utf-8")
    (tmp_path / "topology.json").write_text(json.dumps(_flagged(SCREW)), encoding="utf-8")
    spec = parse_spec(
        {
            "recipe": "static",
            "conditions_from": conditions_from,
            "mesh": {"element_size_mm": 5},
        }
    )
    with pytest.raises(StageFailure) as caught:
        calculix_build(spec, tmp_path)
    if conditions_from == "cad":
        assert caught.value.code == "region_unresolved"
        assert "접촉 「나사 물림」" in caught.value.message
    else:
        assert "나사 물림" not in caught.value.message, "판정 때문에 멈춘 것이 아니다"
