"""이 기계에 **어느 솔버가 깔렸나** — 워커가 기동할 때 한 번 보고 신호에 실어 보낸다.

단계 안의 찾기(`calculix/tools.py` · `solve/mapdl.py`)는 없으면 **실패한다** — 작업 하나를
붙들고 있으니 그것이 맞다. 여기는 서버 화면에 보여 줄 답이라 **없다고 말하고 끝난다**(예외를
던지지 않는다).

**워커가 본 것이 정본이다.** 워커마다 기계 · 이미지 · bind 가 다를 수 있다 — API 프로세스가 제
자리에서 `which` 로 본 답은 그 워커의 사실이 아니다.

windows-bridge 는 Ansys 가 Windows 쪽에 있다. WSL 의 워커가 그 자리를 단정할 수 없으므로
「확인하지 않음」 으로 적는다 — 짐작해서 「없다」 고 적으면 멀쩡한 설치를 고장으로 읽는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.calculix import tools
from app.core.solve import mapdl
from app.core.stages import StageFailure


def _ansys(executor: str, root: Path | None, version: int) -> dict[str, Any]:
    made: dict[str, Any] = {"version": version, "path": None, "checked": False, "note": ""}
    if executor == "fake":
        made["note"] = "모의 실행기 — 솔버를 부르지 않습니다."
        return made
    if executor == "windows-bridge":
        made["note"] = "Windows 쪽 파이썬이 실행합니다 — 이 워커에서는 확인하지 않습니다."
        return made
    try:
        binary = mapdl.executable(root, version)
    except StageFailure as failure:
        made["checked"] = True
        made["note"] = failure.message
        return made
    made["checked"] = True
    if binary.is_file():
        made["path"] = str(binary)
    else:
        made["note"] = f"실행 파일이 없습니다: {binary}"
    return made


def report(*, executor: str, ansys_root: Path | None, ansys_version: int) -> dict[str, Any]:
    """`{gmsh, ccx, ansys}` — 앞 둘은 경로나 `None`, Ansys 는 확인했는지와 그 까닭까지."""
    gmsh = tools.which(tools.GMSH_ENV, *tools.GMSH_NAMES)
    ccx = tools.which(tools.CCX_ENV, *tools.CCX_NAMES)
    return {
        "gmsh": str(gmsh) if gmsh else None,
        "ccx": str(ccx) if ccx else None,
        "ansys": _ansys(executor, ansys_root, ansys_version),
    }
