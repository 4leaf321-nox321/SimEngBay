"""조건 읽기 — **걸 것 · 넘길 것 · 막을 것**으로 갈리는가.

여기서 지키는 것은 「조용히 버리지 않는다」 하나다. 조건을 넣었는데 결과가 같으면 사람은
그것이 **무시된 것인지 원래 그런 것인지** 알 수 없다. 그래서 넘긴 것은 넘겼다고, 못 거는 것은
못 건다고 말해야 한다.

폴더는 CompCore 의 내보내기 코드가 쓴 것이다(`tests/fixtures/doe/README-조건픽스처.md`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core import conditions

FOLDERS = Path(__file__).resolve().parents[1] / "fixtures" / "doe"


def _point(folder: str, number: int = 1) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (FOLDERS / folder / "points" / f"p{number:04d}.json").read_text(encoding="utf-8")
    )
    return loaded


def test_고정_지지와_접촉을_읽는다() -> None:
    """`조건_두바디_두재료` — 바닥 고정 · 본딩 접촉 · 압력."""
    found = conditions.read(_point("조건_두바디_두재료"))

    assert [(one.kind, one.region) for one in found.constraints] == [("fixed_support", "바닥")]
    assert [(one.kind, one.source, one.target) for one in found.contacts] == [
        ("bonded", "블록 아랫면", "판 윗면")
    ]
    # **압력은 모달에서 답을 바꾸지 않는다** — 버리지 않고 그 사실을 적어 둔다.
    assert any("압력" in one.what or "pressure" in one.what for one in found.skipped)
    assert found.refused == []


def test_원통_지지의_방향을_읽는다() -> None:
    """`조건_원통_SI` — 구멍면에 원통 지지, **접선만 자유**(핀에 끼운 채 돈다).

    셋 중 하나라도 놓치면 구속이 통째로 달라진다 — 접선을 고정하면 돌지 못한다.
    """
    found = conditions.read(_point("조건_원통_SI"))

    cylinder = next(one for one in found.constraints if one.kind == "cylindrical")
    assert cylinder.region == "구멍면"
    assert (cylinder.radial, cylinder.axial, cylinder.tangential) == ("fixed", "fixed", "free")
    # 힘 · 베어링 하중은 모달에서 넘긴다.
    assert len(found.skipped) >= 2
    assert found.refused == []
    # 해석 설정도 함께 온다 — 모드 수 · 주파수 범위.
    assert found.analysis.kind == "modal"
    assert found.analysis.modes == 8
    assert found.analysis.frequency_range == (0.0, 5000.0)


def test_접촉_종류가_점마다_바뀐다() -> None:
    """`조건_조건훑기` — 1 · 2번은 본딩, 3 · 4번은 마찰(계수 0.2).

    접촉이 바뀌면 고유진동수가 바뀐다 — 안 읽으면 네 점이 같은 답을 낸다.
    """
    bonded = conditions.read(_point("조건_조건훑기", 1))
    frictional = conditions.read(_point("조건_조건훑기", 3))

    assert [one.kind for one in bonded.contacts] == ["bonded"]
    assert [one.kind for one in frictional.contacts] == ["frictional"]
    assert frictional.contacts[0].friction == 0.2
    assert bonded.refused == [] and frictional.refused == []


def test_메시_힌트는_선언된_계로_온다() -> None:
    """`조건_원통_SI` 는 SI 로 내보낸 폴더다 — 2 mm 힌트가 **0.002 m** 로 실려 온다.

    숫자만 읽고 mm 로 넘기면 메시가 1000배 잘다.
    """
    found = conditions.read(_point("조건_원통_SI"))
    hint = next(one for one in found.mesh_hints if one.element_size is not None)
    assert hint.element_size == 0.002


def test_조건이_없으면_빈_것이다() -> None:
    """형상만 온 폴더 — 오류가 아니다. 그때는 사람이 준 스펙으로 돈다."""
    found = conditions.read(_point("브래킷_두께훑기-3f9a2177"))
    assert found.empty and not found.refused


def test_없는_자리를_가리키면_막는다() -> None:
    """CAD 가 못 푼 그룹을 가리키는 구속 — **그대로 두면 구속 없는 해석이 끝까지 돈다.**"""
    payload = _point("조건_두바디_두재료")
    payload["conditions"]["constraints"][0]["on"] = "없는면"
    found = conditions.read(payload)
    assert found.constraints == []
    assert any("없는면" in one.why for one in found.refused)


def test_모르는_구속은_막는다() -> None:
    """종류가 늘어도 **모르면 걸지 않는다**.

    짐작해서 비슷한 것을 걸면 답이 조용히 달라진다.
    """
    payload = _point("조건_두바디_두재료")
    payload["conditions"]["constraints"][0]["type"] = "spring_support"
    found = conditions.read(payload)
    assert any("spring_support" in one.why for one in found.refused)


def test_조건_줄에_면_수가_붙는다() -> None:
    """**면 수가 안 보이면 줄어든 것을 모른다.**

    CompCore v0.4.0(2026-10-02)부터 선택 규칙 `near` 가 「가장 가까운 **하나**」 로 바뀌었다.
    볼트 구멍 넷을 잡던 규칙이 하나만 잡아도 조건의 이름(`fixed_support · bolt_holes`)은
    똑같다 — 그러면 주파수만 조용히 달라진다. 그래서 화면 줄에 **몇 면으로 풀렸는지**를 적는다.
    """
    from app.modules.simulations.services import conditions_out

    out = conditions_out(_point("조건_두바디_두재료"), recipe="static")

    constraint = next(one for one in out.lines if one.kind == "constraint")
    assert constraint.detail == "fixed_support · 바닥 · 면 1"
    load = next(one for one in out.lines if one.kind == "load" and one.status == "applied")
    assert load.detail.endswith("· 면 1")
