"""DOE 를 가져올 때의 **모드 수** — 안 줬으면 CAD 값, 비교하는 수 이하면 알린다(2026-10-25).

전에는 MCP 가 스펙에 모드 수를 비워 보내면 10 이 들어가 CAD 가 적은 6 과 갈렸다(화면은 CAD
값을 칸에 미리 채워 보내므로 몰랐다). 그리고 6개만 구한 2변수 20점 DOE 에서 폭 방향 2차 굽힘이
14점에서 6번째 위로 밀려나 비교 선이 끊겼다 — 구한 수가 비교하는 수(6)와 같으면 여유가 없다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.doe import read_folder
from app.core.spec import ModalSpec
from app.modules.simulations.services import _import_notes, _with_cad_modes

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "doe"
#: CAD 가 모달 6 을 적은 두 점 DOE.
SIX = read_folder(FIXTURES / "재료훑기-7c1d3a44")
#: CAD 가 모달 8 을 적은 두 점 DOE.
EIGHT = read_folder(FIXTURES / "조건_원통_SI")
#: 해석 설정을 적지 않은 DOE.
SILENT = read_folder(FIXTURES / "브래킷_두께훑기-3f9a2177")
#: 설계 하나(점 하나) — 비교할 것이 없다.
SINGLE = read_folder(FIXTURES / "설계하나_측면가진")


def _modes(doe: Any, raw: dict[str, Any]) -> int:
    sent, spec = _with_cad_modes(doe, raw)
    assert isinstance(spec, ModalSpec)
    # 점마다 `create` 로 넘기는 글자에도 실린다 — 거기서 다시 읽는다.
    assert sent.get("modes", spec.modes) == spec.modes
    return spec.modes


def test_모드_수를_비우면_CAD_가_적은_값() -> None:
    assert _modes(SIX, {"recipe": "modal"}) == 6
    assert _modes(EIGHT, {"recipe": "modal"}) == 8


def test_CAD_도_안_적었으면_스펙_기본_10() -> None:
    assert _modes(SILENT, {"recipe": "modal"}) == 10


def test_일부러_준_값은_CAD_보다_앞선다_10_도_마찬가지() -> None:
    """10 을 일부러 준 것과 안 준 것은 다르다 — 받은 글자에 있었나로 가른다."""
    assert _modes(SIX, {"recipe": "modal", "modes": 12}) == 12
    assert _modes(SIX, {"recipe": "modal", "modes": 10}) == 10


def test_비교하는_수_이하로만_구하면_알린다() -> None:
    _, six = _with_cad_modes(SIX, {"recipe": "modal"})
    (note,) = _import_notes(SIX, six)
    assert "모드를 6개만 구합니다" in note
    assert "10개를 권합니다" in note

    _, eight = _with_cad_modes(EIGHT, {"recipe": "modal"})
    assert _import_notes(EIGHT, eight) == []
    # 설계 하나는 견줄 점이 없다 · 정적은 모드가 없다.
    _, single = _with_cad_modes(SINGLE, {"recipe": "modal", "modes": 4})
    assert _import_notes(SINGLE, single) == []
    _, static = _with_cad_modes(SIX, {"recipe": "static"})
    assert _import_notes(SIX, static) == []
