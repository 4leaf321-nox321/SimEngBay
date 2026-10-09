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
