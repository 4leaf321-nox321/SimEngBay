"""Mechanical 이 쓴 솔버 입력 파일이 **끝까지 쓰였나** — Ansys 없이 보는 부분."""

from __future__ import annotations

from pathlib import Path

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
