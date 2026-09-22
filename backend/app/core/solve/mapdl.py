"""MAPDL 배치 실행 — `ANSYS252 -b -i model.dat -o solve.out`.

## 실측으로 정한 것 (2026-09-20, 2025 R2 · Student · Windows)

- 잡 이름을 안 주면 결과가 `file.rst` 로 나온다. **이름을 우리 것으로 바꾸지 않는다** —
  `.dat` 안의 Workbench 생성 코드가 기본 잡 이름을 전제로 파일을 여닫는다.
- 라이선스 실패 · 수렴 실패가 **종료 코드로는 잘 안 드러난다.** `solve.out` 을 읽어 가른다 —
  「어느 코드로 실패했나」 를 세려면 메시지가 아니라 코드여야 한다.
- Student 판은 절점 수 상한이 있다. 넘기면 솔버가 `solve.out` 에 그 말을 적고 멈춘다.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from app.core.stages import ArtifactSpec, StageFailure, StageResult

#: 솔버가 남기는 결과 파일. `.dat` 가 기본 잡 이름(`file`)을 쓴다.
RESULT_NAME = "file.rst"
OUTPUT_NAME = "solve.out"

#: `solve.out` 에서 이것이 보이면 라이선스 문제다 — 고칠 곳이 다르므로 따로 센다.
_LICENSE_MARKS = (
    "license",
    "licence",
    "ANSYSLI",
    "not available",
)
#: 솔버가 스스로 적는 오류 표식.
_ERROR_MARKS = ("*** ERROR ***", "*** FATAL")


def executable(root: Path | None, version: int) -> Path:
    """이 기계의 MAPDL 실행 파일.

    `root` 를 안 주면 Ansys 가 설치될 때 심는 `AWP_ROOT<버전>` 을 본다 — 경로를 `.env` 에 또
    적으면 버전을 올린 날 한쪽만 바뀐다.
    """
    base = root or _root_from_env(version)
    if base is None:
        raise StageFailure(
            "solver_failed",
            f"Ansys 설치 경로를 모릅니다. ANSYS_ROOT 를 주거나 AWP_ROOT{version} 이 "
            f"설정된 환경에서 워커를 띄우세요.",
        )
    if platform.system() == "Windows":
        return base / "ansys" / "bin" / "winx64" / f"ANSYS{version}.exe"
    return base / "ansys" / "bin" / f"ansys{version}"


def _root_from_env(version: int) -> Path | None:
    value = os.environ.get(f"AWP_ROOT{version}")
    return Path(value) if value else None


def solve(
    workdir: Path,
    *,
    version: int = 252,
    root: Path | None = None,
    processes: int = 2,
    timeout_seconds: int = 10800,
) -> StageResult:
    """`model.dat` 를 풀고 `.rst` 를 남긴다."""
    dat = workdir / "model.dat"
    if not dat.is_file():
        raise StageFailure(
            "solver_failed", "model.dat 이 없습니다 — 모델링 단계가 남긴 것이 없습니다."
        )
    binary = executable(root, version)
    if not binary.is_file():
        raise StageFailure(
            "solver_failed",
            f"솔버 실행 파일이 없습니다: {binary}",
            details={"executable": str(binary)},
        )

    command = [str(binary), "-b", "-np", str(processes), "-i", dat.name, "-o", OUTPUT_NAME]
    try:
        finished = subprocess.run(
            command,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as failure:
        raise StageFailure(
            "timeout",
            f"솔버가 {timeout_seconds // 60}분 안에 끝나지 않았습니다.",
        ) from failure

    output = workdir / OUTPUT_NAME
    log = output.read_text(encoding="utf-8", errors="replace") if output.is_file() else ""
    artifacts: list[ArtifactSpec] = []
    if output.is_file():
        artifacts.append(ArtifactSpec("solve_out", output))

    result = workdir / RESULT_NAME
    if not result.is_file():
        raise _diagnose(log, finished.returncode, artifacts)
    artifacts.append(ArtifactSpec("rst", result))

    # **결과 파일이 있어도 오류를 흘려보내지 않는다.** 반쯤 풀린 `.rst` 는 모드 수가 모자란
    # 채로 그럴듯하게 읽히고, 그 사실은 아무 데도 안 적힌다.
    if _has(log, _ERROR_MARKS):
        raise _diagnose(log, finished.returncode, artifacts)

    return StageResult(
        artifacts=artifacts,
        summary={"solver_seconds": _elapsed(log)},
        detail=f"MAPDL {version} · {processes} 코어",
    )


def _has(log: str, marks: tuple[str, ...]) -> bool:
    lowered = log.lower()
    return any(mark.lower() in lowered for mark in marks)


def _diagnose(log: str, return_code: int, artifacts: list[ArtifactSpec]) -> StageFailure:
    """왜 결과가 없나. **라이선스를 따로 가른다** — 그것은 워커 수나 라이선스 서버의 일이다."""
    tail = "\n".join(line for line in log.splitlines()[-40:] if line.strip())
    if _has(log, _LICENSE_MARKS):
        return StageFailure(
            "license",
            "솔버가 라이선스를 받지 못했습니다. "
            "동시에 도는 작업 수와 라이선스 서버를 확인하세요.",
            details={"return_code": return_code, "tail": tail},
        )
    return StageFailure(
        "solver_failed",
        f"솔버가 결과를 내지 못했습니다(종료 코드 {return_code}). 솔버 로그를 확인하세요.",
        details={"return_code": return_code, "tail": tail, "artifacts": len(artifacts)},
    )


def _elapsed(log: str) -> float | None:
    """`solve.out` 의 경과 시간. 못 찾으면 None — 없는 값을 0 으로 적지 않는다."""
    for line in log.splitlines():
        if "ELAPSED TIME" in line.upper():
            for token in line.replace("=", " ").split():
                try:
                    return float(token)
                except ValueError:
                    continue
    return None
