"""단계를 **다른 프로세스에서** 돌리는 실행기 둘 — `local` 과 `windows-bridge`.

둘의 차이는 「어느 파이썬을 어떤 경로 표기로 부르나」 뿐이다. 코드는 한 벌이고 갈리는 것은
설정 세 줄이다(`docs/해석-연동-계획.md` 3.1).

    local           이 기계의 파이썬. 운영 워커(Apptainer, /ansys_inc bind)와 리눅스 개발 PC
    windows-bridge  WSL 의 워커가 Windows 의 파이썬을 부른다 — Ansys 가 거기 있다

## 왜 프로세스를 따로 띄우나

임베디드 Mechanical 은 **프로세스당 하나**고, 한 번 뜬 뒤로는 그 프로세스의 .NET 런타임을
붙들고 있다. 워커 프로세스 안에서 직접 띄우면 (1) 작업 하나가 남긴 상태가 다음 작업으로
새고, (2) Mechanical 이 죽을 때 워커가 함께 죽는다. 단계마다 프로세스를 새로 띄우면 그 둘이
없어진다 — 대신 기동 시간(몇 초)을 매번 낸다. 해석이 분 · 시간 단위라 그 값은 싸다.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app.core import run as stage_run
from app.core.stages import (
    CancelCheck,
    StageCanceled,
    StageContext,
    StageFailure,
    StageResult,
)

logger = logging.getLogger(__name__)

#: 저장소의 backend 폴더. 자식 프로세스가 `app.core.run` 을 찾을 자리다.
BACKEND_DIR = Path(__file__).resolve().parents[3]

#: 자식을 띄우는 한 줄. **PYTHONPATH 환경변수를 쓰지 않는다** — WSL 에서 Windows 실행 파일을
#: 부르면 환경변수가 건너가지 않는다(WSLENV 에 적은 것만 간다). 실측: `PYTHONPATH` 를 주고
#: 띄운 Windows 파이썬에서 그 값이 `None` 이었고, `python -m app.core.run` 은
#: `No module named 'app'` 로 죽었다. 경로를 **명령줄에 실어** 그 사정을 없앤다.
_BOOTSTRAP = (
    "import sys; sys.path.insert(0, {backend!r}); "
    "from app.core.run import main; sys.exit(main(sys.argv[1:]))"
)

#: 자식을 기다리는 동안 취소를 얼마나 자주 보나(초). 촘촘히 볼수록 DB 를 자주 읽는다.
CANCEL_POLL_SECONDS = 2.0
#: 멈추라고 한 뒤 기다리는 시간(초). 이 안에 안 죽으면 강제로 끝낸다.
STOP_GRACE_SECONDS = 15.0

#: 단계마다 다른 상한. 솔브만 유난히 길다 — 한 값으로 묶으면 모델링이 하루 종일 매달린다.
DEFAULT_TIMEOUTS: dict[str, int] = {
    "fetching": 300,
    "modeling": 3600,
    "solving": 10800,
    "extracting": 1800,
}


@dataclass(frozen=True)
class SubprocessOptions:
    """자식 프로세스를 띄우는 데 필요한 것.

    **설정을 코어가 읽지 않는다** — 앱(`app/config.py`)이 읽어서 준다.
    """

    python: Path | None = None
    """자식 파이썬. 비우면 이 프로세스의 것(`local`). `windows-bridge` 는 Windows 쪽 것."""
    ansys_version: int = 252
    ansys_root: Path | None = None
    solver_processes: int = 2
    wrapper: tuple[str, ...] = ()
    """자식 파이썬을 **감싸서** 띄울 명령.

    리눅스의 임베디드 Mechanical 은 `LD_LIBRARY_PATH` 같은 것이 맞아야 뜨고, 그것을 맞춰 주는
    것이 Ansys 가 함께 깔아 주는 `mechanical-env` 다(리눅스 전용). 비우면 맨 파이썬을 띄운다 —
    **Windows 는 그 스크립트가 없고 필요도 없다.**
    """
    visual_modes: int = 6
    """모드 형상(VTP · PNG)을 만들 **탄성 모드 수.** 모드마다 파일 둘이 생긴다."""
    timeouts: dict[str, int] | None = None

    def timeout_for(self, stage: str) -> int:
        return (self.timeouts or {}).get(stage) or DEFAULT_TIMEOUTS[stage]


def to_windows_path(path: Path) -> str:
    """WSL 경로 → Windows 경로. **`wslpath` 에게 묻는다.**

    직접 바꾸면(`/mnt/c` → `C:`) 저장소가 WSL 파일시스템에 있을 때가 틀린다 — 그때 답은
    `\\\\wsl.localhost\\<배포판>\\...` 이고, 그 모양은 배포판 이름과 WSL 버전에 따라 다르다.
    """
    try:
        finished = subprocess.run(
            ["wslpath", "-w", str(path)], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as failure:
        raise StageFailure(
            "internal",
            f"WSL 경로를 Windows 경로로 바꾸지 못했습니다: {path} ({failure}). "
            f"windows-bridge 실행기는 WSL 안에서만 됩니다.",
        ) from failure
    return finished.stdout.strip()


class SubprocessExecutor:
    """`python -m app.core.run <단계> <작업폴더>` 를 띄우고 결과 파일을 읽는다."""

    def __init__(
        self, name: str, options: SubprocessOptions, *, windows: bool = False
    ) -> None:
        self.name = name
        self.options = options
        self.windows = windows

    # --- 명령 만들기 --------------------------------------------------------

    def _python(self) -> str:
        if self.options.python is not None:
            return str(self.options.python)
        import sys

        return sys.executable

    def _paths(self, workdir: Path) -> tuple[str, str]:
        """(자식이 볼 작업 폴더, 자식이 볼 backend 폴더)."""
        if self.windows:
            return to_windows_path(workdir), to_windows_path(BACKEND_DIR)
        return str(workdir), str(BACKEND_DIR)

    def command(self, ctx: StageContext) -> list[str]:
        """띄울 명령. **시험이 이것만 본다** — Ansys 없이 확인할 수 있는 부분이다."""
        workdir, backend = self._paths(ctx.workdir)
        command = [
            *self.options.wrapper,
            self._python(),
            # **자식의 stdout 을 UTF-8 로 고정한다.** 한국어 Windows 의 파이썬은 콘솔
            # 코드페이지(cp949)로 찍는데, 그것을 UTF-8 로 읽으면 부르는 쪽이
            # `UnicodeDecodeError` 로 죽는다 — 실측: 단계가 성공했는데 워커가 터졌다.
            "-X",
            "utf8",
            "-c",
            _BOOTSTRAP.format(backend=backend),
            ctx.stage,
            workdir,
            "--input-name",
            ctx.input_name,
            "--ansys-version",
            str(self.options.ansys_version),
            "--solver-processes",
            str(self.options.solver_processes),
            "--timeout-seconds",
            str(self.options.timeout_for(ctx.stage)),
            "--visual-modes",
            str(self.options.visual_modes),
        ]
        if self.options.ansys_root is not None:
            root = (
                to_windows_path(self.options.ansys_root)
                if self.windows and str(self.options.ansys_root).startswith("/")
                else str(self.options.ansys_root)
            )
            command += ["--ansys-root", root]
        return command

    # --- 돌리기 -------------------------------------------------------------

    def child_env(self) -> dict[str, str]:
        """자식이 물려받을 환경.

        **임베디드 Mechanical 은 우리 명령줄 인자를 안 본다** — `App(version=…)` 은 스스로
        `AWP_ROOT<버전>` 을 찾는다. 그래서 설정에 적힌 설치 경로를 그 이름으로 심어 준다.
        안 그러면 `.env` 에 경로를 적어도 모델링 단계만 「Ansys 를 못 찾겠다」 고 한다.

        Windows 로 건너가는 다리에서는 **환경이 건너가지 않으므로**(WSLENV) 여기서 심은 값이
        무시된다 — 그쪽은 설치 프로그램이 이미 같은 이름으로 심어 두었다.
        """
        env = dict(os.environ)
        if self.options.ansys_root is not None and not self.windows:
            env[f"AWP_ROOT{self.options.ansys_version}"] = str(self.options.ansys_root)
        return env

    def run(self, ctx: StageContext, should_cancel: CancelCheck | None = None) -> StageResult:
        command = self.command(ctx)
        timeout = self.options.timeout_for(ctx.stage)
        try:
            child = subprocess.Popen(
                command,
                cwd=str(ctx.workdir),
                env=self.child_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                # 자식이 UTF-8 로 못 찍는 경우에도 **부르는 쪽은 죽지 않는다.** 로그가 조금
                # 깨지는 것과 작업이 실패하는 것은 다른 값이다.
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as failure:
            raise StageFailure(
                "internal",
                f"실행기 파이썬을 찾지 못했습니다: {command[0]}. "
                f"SIMULATION_EXECUTOR 와 WINDOWS_PYTHON 을 확인하세요.",
            ) from failure

        # **기다리면서 취소를 본다.** 그냥 `run()` 으로 막아 두면 솔브 세 시간 동안 취소를
        # 누를 수는 있어도 아무 일도 안 일어난다 — 그때 사람은 취소가 고장 났다고 읽는다.
        started = time.monotonic()
        while True:
            try:
                _, stderr = child.communicate(timeout=CANCEL_POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                if should_cancel is not None and should_cancel():
                    _stop(child)
                    raise StageCanceled(f"{ctx.stage} 단계에서 취소했습니다.") from None
                if time.monotonic() - started > timeout:
                    _stop(child)
                    raise StageFailure(
                        "timeout",
                        f"{ctx.stage} 단계가 {timeout // 60}분 안에 끝나지 않았습니다.",
                    ) from None

        if child.returncode != 0:
            logger.warning(
                "%s 단계 실행기가 %d 로 끝났습니다\n--- stderr ---\n%s",
                ctx.stage,
                child.returncode,
                _tail(stderr or ""),
            )
        # **종료 코드가 아니라 결과 파일을 믿는다.** 자식이 왜 죽었는지는 그 파일에만 있고,
        # 없으면 read_result 가 「도중에 죽었다」 고 말한다.
        return stage_run.read_result(ctx.workdir, ctx.stage)


def _stop(child: subprocess.Popen[str]) -> None:
    """자식을 멈춘다. **먼저 곱게, 안 되면 세게.** Mechanical 은 곧바로 안 죽는다."""
    child.terminate()
    try:
        child.wait(timeout=STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=STOP_GRACE_SECONDS)


def _tail(text: str, lines: int = 40) -> str:
    return "\n".join(text.splitlines()[-lines:])
