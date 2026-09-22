"""실행기 — 단계를 **어디서** 돌리느냐. 코드는 한 벌, 자리만 갈린다(계획서 3.1).

    fake            sleep + 모양만 맞는 산출물. 시험 · CI · Ansys 없는 PC
    local           이 기계의 파이썬으로 `python -m app.core.run`. 운영 워커 · 리눅스 개발 PC
    windows-bridge  WSL 의 워커가 Windows 의 파이썬을 부른다 — Ansys 가 거기 있다

워커는 이름으로 하나를 고르고(`.env` `SIMULATION_EXECUTOR`), 그 뒤로는 `run(ctx)` 만 부른다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.core.executors.subprocess_executor import SubprocessExecutor, SubprocessOptions
from app.core.stages import StageContext, StageResult

#: 이 저장소가 아는 실행기 이름. 목록에 없는 이름은 오타다.
NAMES = ("fake", "local", "windows-bridge")


class Executor(Protocol):
    name: str

    def run(self, ctx: StageContext) -> StageResult:
        """한 단계를 돌린다. 실패는 `StageFailure` 로 — 다른 예외는 코어의 버그로 본다."""
        ...


def resolve(
    name: str,
    *,
    fake_stage_seconds: float = 0.0,
    python: Path | None = None,
    ansys_version: int = 252,
    ansys_root: Path | None = None,
    solver_processes: int = 2,
    visual_modes: int = 6,
) -> Executor:
    """이름 → 실행기.

    **모르는 이름은 여기서 죽는다** — 워커가 첫 작업을 집고 나서 죽으면 그 작업이 `failed` 로
    남고, 사람은 설정 오타를 작업 실패로 읽는다. `windows-bridge` 인데 파이썬을 안 준 것도
    같은 부류라 함께 막는다.
    """
    if name == "fake":
        from app.core.executors.fake import FakeExecutor

        return FakeExecutor(stage_seconds=fake_stage_seconds)

    options = SubprocessOptions(
        python=python,
        ansys_version=ansys_version,
        ansys_root=ansys_root,
        solver_processes=solver_processes,
        visual_modes=visual_modes,
    )
    if name == "local":
        return SubprocessExecutor("local", options)
    if name == "windows-bridge":
        if python is None:
            raise RuntimeError(
                "SIMULATION_EXECUTOR=windows-bridge 인데 WINDOWS_PYTHON 이 없습니다 — "
                "Ansys 가 깔린 Windows 쪽 파이썬 경로를 주세요"
                r" (예: /mnt/c/simengbay/venv/Scripts/python.exe)."
            )
        return SubprocessExecutor("windows-bridge", options, windows=True)
    raise RuntimeError(
        f"모르는 실행기입니다: SIMULATION_EXECUTOR={name!r} ({' · '.join(NAMES)})"
    )
