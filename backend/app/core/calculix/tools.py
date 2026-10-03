"""gmsh · CalculiX 를 **딴 프로세스로** 부른다.

## 왜 CLI 로만 부르나

둘 다 **GPL** 이다. 별 프로세스로 띄워 파일로만 주고받으면 두 프로그램이고, 같은 프로세스에
올리면(`import gmsh`) 한 프로그램으로 본다 — 그 차이가 우리 코드의 공개 의무를 가른다. 지금은
사내에서만 쓰므로 의무가 생기지 않지만, **나중에 사외로 나갈 때 아무것도 안 고치려면** 처음부터
경계를 파일에 두어야 한다. 한번 `import gmsh` 로 짜면 그 객체가 모델링 전체로 퍼져서, 떼어낼 때
모델링을 다시 쓰게 된다.

그리고 이것은 엔지니어링으로도 맞다. 우리는 이미 MAPDL 에 `.dat` 를 주고 `.rst` 를 받는다 —
그 파일들이 **재현의 단위**다. 감쇠가 덱에 안 실린 것도 덱을 grep 해서 잡았다(2026-10-02).
CalculiX 도 `.geo` · `.msh` · `.inp` · `.frd` 로 같은 수단을 쓴다.

**그래서 이 파일에 `import gmsh` 가 들어오면 안 된다.**

## 어디서 찾나

배포 이미지는 OS 패키지로 깔아 `PATH` 에 둔다. 개발 PC 는 손으로 받아 둔 자리를 쓸 수 있게
`GMSH_BIN` · `CCX_BIN` · `OPENSOLVER_LD_PATH` 를 본다 — 뒤의 것은 OS 패키지를 루트 없이 풀어
쓸 때 필요하다(실측 2026-10-02: ccx 는 spooles · arpack · openmpi 를 따라온다).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from app.core.stages import StageFailure

logger = logging.getLogger(__name__)

#: 환경 변수 이름 — 실행기 설정이 이 값을 워커에 넘긴다.
GMSH_ENV = "GMSH_BIN"
CCX_ENV = "CCX_BIN"
LD_ENV = "OPENSOLVER_LD_PATH"


def which(env: str, *names: str) -> Path | None:
    """환경 변수 → `PATH` 순으로 찾는다. **없으면 `None`** — 화면에 「깔렸나」 를 답할 때 쓴다.

    환경 변수가 있는데 그 자리에 파일이 없으면 `None` 이다(`PATH` 로 물러서지 않는다) — 사람이
    가리킨 자리가 틀린 것을 다른 자리의 것으로 덮으면 그 오타를 영영 모른다.
    """
    given = os.environ.get(env)
    if given:
        path = Path(given)
        return path if path.is_file() else None
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def _find(env: str, *names: str, what: str) -> Path:
    """환경 변수 → `PATH` 순으로 찾는다. **없으면 즉시 실패한다.**

    조용히 건너뛰면 그 작업은 「결과 파일이 없다」 로 끝나고, 사람은 설치 문제를 해석 실패로
    읽는다 — 무엇을 깔아야 하는지까지 말해 준다.
    """
    found = which(env, *names)
    if found is not None:
        return found
    given = os.environ.get(env)
    if given:
        raise StageFailure("internal", f"{env} 가 가리키는 {what} 가 없습니다: {given}")
    raise StageFailure(
        "internal",
        f"{what} 를 찾지 못했습니다 — 이미지에 `{names[0]}` 를 깔거나 `{env}` 로 "
        f"자리를 알려 주세요.",
    )


#: 찾을 실행 파일 이름 — 단계(`gmsh_bin` · `ccx_bin`)와 화면(`app/core/toolcheck.py`)이
#: 같이 쓴다.
GMSH_NAMES = ("gmsh",)
CCX_NAMES = ("ccx", "ccx_2.21")


def gmsh_bin() -> Path:
    return _find(GMSH_ENV, *GMSH_NAMES, what="gmsh")


def ccx_bin() -> Path:
    return _find(CCX_ENV, *CCX_NAMES, what="CalculiX(ccx)")


def run(
    binary: Path,
    args: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    what: str,
) -> subprocess.CompletedProcess[str]:
    """한 번 부르고 그대로 돌려준다 — **판정은 부른 쪽이 한다.**

    종료 코드만 보면 안 되는 도구들이다: CalculiX 는 수렴 실패에도 0 으로 끝나고 `.sta` ·
    출력에 `*ERROR` 를 적는다. 그래서 여기서는 「돌다 죽었나 · 시간이 넘었나」 만 본다.
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(cwd),
        # 스레드 수를 비워 두면 CalculiX 가 코어를 전부 쥔다 — DOE 를 여러 점 동시에 돌리는
        # 것이 이 솔버를 쓰는 이유이므로, 한 점이 기계를 독차지하면 안 된다.
        "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS", "2"),
    }
    extra = os.environ.get(LD_ENV)
    if extra:
        env["LD_LIBRARY_PATH"] = extra
    try:
        return subprocess.run(
            [str(binary), *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as failure:
        raise StageFailure(
            "timeout", f"{what} 가 {timeout_seconds}초 안에 끝나지 않았습니다."
        ) from failure
    except OSError as failure:
        raise StageFailure(
            "internal", f"{what} 를 실행하지 못했습니다: {failure}"
        ) from failure
