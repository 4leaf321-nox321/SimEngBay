"""Mechanical 이 쓴 솔버 입력 파일이 **끝까지 쓰였나** — Ansys 없이 보는 부분."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.mechanical.build import _check_input_complete
from app.core.stages import StageFailure


def test_끝_표지가_있으면_지나간다(tmp_path: Path) -> None:
    dat = tmp_path / "model.dat"
    dat.write_text(
        "/prep7\n/solu\nsolve\n/wb,file,end               ! done\n", encoding="ascii"
    )
    _check_input_complete(dat)


def test_중간에_끊긴_입력은_마지막_자리를_말하고_멈춘다(tmp_path: Path) -> None:
    """`WriteInputFile` 은 끊겨도 오류를 안 낸다 — 그대로 풀면 MAPDL 이 종료 코드 8 만 남긴다
    (2026-10-08, CompCore 보드굽힘)."""
    dat = tmp_path / "model.dat"
    dat.write_text(
        '/prep7\n/com,*********** Create Contact "pin-hole" ***********\neblock,11\n/gopr\n',
        encoding="ascii",
    )
    with pytest.raises(StageFailure) as caught:
        _check_input_complete(dat)
    assert caught.value.code == "solver_failed"
    assert 'Create Contact "pin-hole"' in str(caught.value)


class _Settings:
    """`AnalysisSettings` 흉내 — 넣은 값과 차례를 적는다(최대를 먼저 넣어야 처음 값이 안
    넘친다)."""

    order: list[str]
    values: dict[str, object]

    def __init__(self) -> None:
        object.__setattr__(self, "order", [])
        object.__setattr__(self, "values", {})

    def __setattr__(self, name: str, value: object) -> None:
        self.order.append(name)
        self.values[name] = value


def test_CAD_의_초기_부단계_수를_자동_시간_단계로_건다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mechanical = importlib.import_module("app.core.mechanical.build")
    settings = _Settings()
    static = SimpleNamespace(AnalysisSettings=settings)
    app = SimpleNamespace(Model=SimpleNamespace(AddStaticStructuralAnalysis=lambda: static))
    enums = SimpleNamespace(
        AutomaticTimeStepping=SimpleNamespace(On="On"),
        TimeStepDefineByType=SimpleNamespace(Substeps="Substeps"),
    )
    ansys = SimpleNamespace(Mechanical=SimpleNamespace(DataModel=SimpleNamespace(Enums=enums)))
    monkeypatch.setitem(mechanical.__dict__, "Ansys", ansys)

    mechanical._add_static(app, large_deflection=True, substeps=20)
    assert settings.values["LargeDeflection"] is True
    assert settings.values["DefineBy"] == "Substeps"
    assert settings.values["InitialSubsteps"] == 20
    assert settings.values["MaximumSubsteps"] == 1000
    assert settings.order.index("MaximumSubsteps") < settings.order.index("InitialSubsteps")

    # 부단계 수가 없으면 자동 시간 단계를 건드리지 않는다.
    plain = _Settings()
    static.AnalysisSettings = plain
    mechanical._add_static(app, large_deflection=False)
    assert plain.order == ["LargeDeflection"]


#: 실제 입력 파일의 원격점 자리(핀 베어링, 2025 R2) — 강체 핀의 질량 절점 31808 에 원격점
#: 31809 가 묶이고, 변위는 원격점에 걸린다.
REMOTE_DECK = """\
/com,*********** Create Remote Point "Internal Remote Point" ***********
! -------- Remote Point Used by "SEB_RD_1" --------
! ********* Create Contact to Connect To Rigid Body Mass Node ***********
tshape,pilo
en,25551,31808
tshape
*set,_npilot,31809
_npilot52=_npilot
/com,*********** Create Remote Point "Internal Remote Point 2" ***********
! -------- Remote Point Used by "SEB_RD_2" --------
*set,_npilot,31811
/com,*********** Create Remote Point "Internal Remote Point 3" ***********
! -------- Remote Point Used by "SEB_RD_3" --------
*set,_npilot,31813
/com,*********** Create Remote Point "Internal Remote Point 4" ***********
! -------- Remote Point Used by "Remote Displacement" --------
*set,_npilot,31815
d,31809,ux,0.2
"""


def test_원격_변위마다_원격점_절점을_찾는다(tmp_path: Path) -> None:
    """원격 변위의 반력은 그 원격점 절점에 있다 — 면 위 절점에는 없다. 강체 파트 여럿에 걸친
    그룹(롤러 둘)은 원격점이 여럿이라 다 모은다. 우리가 이름 붙이지 않은 것은 안 집는다."""
    from app.core.mechanical.build import remote_pilots

    dat = tmp_path / "model.dat"
    dat.write_text(REMOTE_DECK, encoding="utf-8")
    tags = {"SEB_RD_1": "핀 끝면", "SEB_RD_2": "지지 롤러", "SEB_RD_3": "지지 롤러"}
    assert remote_pilots(dat, tags) == {"핀 끝면": [31809], "지지 롤러": [31811, 31813]}
