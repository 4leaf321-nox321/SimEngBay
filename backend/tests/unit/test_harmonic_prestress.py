"""조화 응답의 선응력은 **두 솔버 모두 받지 않는다** — 전에는 말없이 무시했다(CompCore 와 정함,
2026-11-27). 조화가 흔드는 하중이 아닌 것(볼트 · 회전 속도)도, Mechanical 의 조화가 받지 않는
중력도 작업을 만들 때 막는다. 랜덤 진동의 선응력은 CalculiX 만 받는다.
"""

from __future__ import annotations

from typing import Any

from app.core import conditions
from app.core.calculix import deck as calculix_deck
from app.core.mechanical.build import RANDOM_PRESTRESS
from app.core.mechanical.build import unsupported as ansys_unsupported

FIXED = {"name": "바닥", "type": "fixed_support", "on": "면A"}
FORCE = {"name": "끝 힘", "type": "force", "on": "면A", "magnitude": 1, "unit": "N"}
PSD = {
    "name": "랜덤 가진",
    "type": "psd_acceleration",
    "psd_table": [[10, 0.01], [100, 0.01]],
    "unit": "g^2/Hz",
    "direction": [0, 0, 1],
}


def _payload(
    kind: str,
    *,
    prestressed: bool = False,
    loads: tuple[dict[str, Any], ...] = (FORCE,),
    initial: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "regions": {"면A": {}},
        "conditions": {
            "analysis": {"type": kind, "prestressed": prestressed},
            "named_selections": [{"name": "면A", "entity": "face"}],
            "constraints": [FIXED],
            "loads": list(loads),
            "initial": list(initial),
        },
    }


def _why(given: conditions.Conditions) -> list[str]:
    return [f"{one.what} — {one.why}" for one in given.refused]


def test_조화의_선응력_켬은_까닭과_막는다() -> None:
    given = conditions.read(_payload("harmonic", prestressed=True), recipe="harmonic")
    assert _why(given) == [f"해석 설정 (선응력 반영) — {conditions.HARMONIC_PRESTRESS}"]


def test_모달로_적은_선응력_점을_조화로_돌려도_막는다() -> None:
    """선응력을 빼고 풀면 CAD 가 적은 것과 다른 해석이다."""
    given = conditions.read(_payload("modal", prestressed=True), recipe="harmonic")
    assert any("선응력 반영" in one for one in _why(given))


def test_조화의_초기조건_선응력도_막는다() -> None:
    given = conditions.read(
        _payload("harmonic", initial=({"type": "prestress"},)), recipe="harmonic"
    )
    assert _why(given) == [f"초기조건 (선응력) — {conditions.HARMONIC_PRESTRESS}"]


def test_선응력_칸이_빠진_조화는_끈_것으로_읽는다() -> None:
    """CompCore 는 조화에 `prestressed` 칸을 더는 내지 않는다(fe3eef3) — 빠지면 거짓."""
    payload = _payload("harmonic")
    del payload["conditions"]["analysis"]["prestressed"]
    given = conditions.read(payload, recipe="harmonic")
    assert given.analysis.prestressed is False
    assert not given.refused
    assert [one.kind for one in given.loads] == ["force"]


def test_조화는_볼트와_회전_속도를_가진으로_쓰지_않는다() -> None:
    bolt = {"name": "볼트", "type": "bolt_pretension", "on": "면A", "preload": 100}
    spin = {"name": "회전", "type": "rotational_velocity", "magnitude": 10, "unit": "rad/s"}
    given = conditions.read(_payload("harmonic", loads=(FORCE, bolt, spin)), recipe="harmonic")
    assert [one.kind for one in given.loads] == ["force"]
    assert [one.what for one in given.refused] == [
        "하중 「볼트」(bolt_pretension)",
        "하중 「회전」(rotational_velocity)",
    ]


def test_조화는_중력을_받지_않는다() -> None:
    """두 솔버 모두 — Mechanical 은 조화에 중력을 받지 않고(실측), CalculiX 는 1 g 가진으로
    흔들어 「중력이 걸린 채」 로 읽혔다(사용자 결정 2026-11-27). 1 g 는 가속도로 적는다."""
    gravity = {"name": "중력", "type": "standard_earth_gravity", "direction": [0, 0, -1]}
    given = conditions.read(_payload("harmonic", loads=(FORCE, gravity)), recipe="harmonic")
    assert [one.kind for one in given.loads] == ["force"]
    [note] = given.refused
    assert note.what == "하중 「중력」(standard_earth_gravity)"
    assert "가속도 하중으로" in note.why
    # 정적 · 선응력 모달에서는 그대로 건다.
    static = conditions.read(_payload("static", loads=(FORCE, gravity)), recipe="static")
    assert not static.refused and len(static.loads) == 2
    assert ansys_unsupported(static, "static") == []


def test_랜덤의_선응력은_CalculiX_만_받는다() -> None:
    payload = _payload(
        "random", prestressed=True, loads=(PSD, FORCE), initial=({"type": "prestress"},)
    )
    given = conditions.read(payload, recipe="random")
    assert not given.refused and not given.skipped
    assert given.prestressed
    assert calculix_deck.unsupported(given) == []
    assert ansys_unsupported(given, "random") == [RANDOM_PRESTRESS]
    # 선응력을 끄면 Ansys 도 받는다(하중은 쓰지 않는다고 알린다).
    quiet = conditions.read(_payload("random", loads=(PSD, FORCE)), recipe="random")
    assert ansys_unsupported(quiet, "random") == []
    assert any(one.what == "하중 「끝 힘」(force)" for one in quiet.skipped)
