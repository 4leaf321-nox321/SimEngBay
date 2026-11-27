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

import hashlib
import re
import subprocess
from collections.abc import Mapping
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


def report(
    *,
    executor: str,
    ansys_root: Path | None,
    ansys_version: int,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """`{gmsh, ccx, ansys}` — 앞 둘은 경로나 `None`, Ansys 는 확인했는지와 그 까닭까지.

    `environ` 은 **단계 자식이 볼 환경**이다(워커가 `.env` 의 `GMSH_BIN` · `CCX_BIN` 을 더해
    준다) — 그 자리로 찾아야 「깔렸다」 는 답이 단계에서도 맞는다."""
    gmsh = tools.which(tools.GMSH_ENV, *tools.GMSH_NAMES, environ=environ)
    ccx = tools.which(tools.CCX_ENV, *tools.CCX_NAMES, environ=environ)
    return {
        "gmsh": str(gmsh) if gmsh else None,
        "ccx": str(ccx) if ccx else None,
        "ccx_sha256": sha256_of(ccx) if ccx else None,
        "ccx_version": ccx_version(ccx) if ccx else None,
        "ansys": _ansys(executor, ansys_root, ansys_version),
    }


#: `ccx -v` 의 판 — 「This is Version 2.21」.
_CCX_VERSION = re.compile(r"Version\s+(\d+(?:\.\d+)*)")


def ccx_version(path: Path) -> str | None:
    """**실제로 푸는 ccx 의 판**(`ccx -v`) — 능력표의 CalculiX `version` 이 이것을 모은다
    (`services._solver_version`). 워커가 기동할 때 한 번 잰다 — 요청마다 부르지 않는다(API
    프로세스에는 ccx 가 없을 수 있고, 있어도 워커의 것과 다를 수 있다). 못 읽으면 `None`."""
    try:
        done = subprocess.run(
            [str(path), "-v"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    found = _CCX_VERSION.search(f"{done.stdout}\n{done.stderr}")
    return found.group(1) if found else None


def sha256_of(path: Path) -> str | None:
    """실행 파일의 지문 — **STE 의 ccx 와 같은 빌드인가**를 견준다(요청서 E-5 · A-1). 링크는
    따라간다(`/usr/bin/ccx` → `ccx_2.21`). 감싼 스크립트(`CCX_BIN` 이 셸 스크립트)면 그
    스크립트의 지문이라 STE 와 다르게 나온다. 못 읽으면 `None`(모른다)."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()
