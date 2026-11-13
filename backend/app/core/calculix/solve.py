"""솔브 단계 — CalculiX 를 부른다.

**종료 코드만 보면 안 된다.** ccx 는 입력이 틀려도 0 으로 끝나면서 출력에 `*ERROR` 를 적는다 —
그것을 안 읽으면 다음 단계가 「결과 파일이 없다」 로 실패하고, 사람은 솔버 문제를 추출 문제로
읽는다. MAPDL 쪽에서 로그를 `*** ERROR ***` 블록으로만 훑기로 한 것과 같은 교훈이다
(실측 2026-10-02: 배너의 라이선스 글자를 오류로 읽어 엉뚱한 진단을 했다).
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.calculix import tools
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

DECK_NAME = "model.inp"
#: ccx 가 남기는 것들 — `.dat`(고유진동수 · 출력 요청), `.frd`(절점 결과), `.sta`(단계 상태).
RESULT_NAME = "model.frd"
DATA_NAME = "model.dat"
LOG_NAME = "ccx.out"

#: 출력에서 이것이 보이면 실패다. ccx 는 대문자로 적는다.
ERROR_MARK = re.compile(r"\*ERROR|not converged|too many iterations", re.IGNORECASE)

#: 정적 해석의 선형 솔버 — `auto`(메모리를 어림해 고른다, 기본) · `spooles` · `iterative`.
LINEAR_SOLVER_ENV = "CALCULIX_LINEAR_SOLVER"
ITERATIVE_LINE = "*STATIC, SOLVER=ITERATIVE CHOLESKY"
#: SPOOLES(직접 솔버)의 최대 메모리 어림 — (자유도, MB, 지수). 2차 사면체 자유도 16.5만에서
#: 2,370 MB, 자유도의 1.4 제곱으로 는다(실측 2026-11-13, ccx 2.21: 11.0만 1,400 · 16.5만
#: 2,370 · 28.9만 5,213 MB — 셋 다 4% 안). 반복 솔버는 같은 모델에 138 · 209 · 373 MB 였고
#: 반력이 같았다.
SPOOLES_MB = (165_000, 2370.0, 1.4)
#: 남은 메모리의 이만큼을 넘을 것 같으면 반복 솔버로 푼다.
MEMORY_SHARE = 0.7
#: 반복 솔버를 못 쓰는 덱 — 고유치 · 조화 · 동해석은 직접 솔버뿐이고, 접촉 쌍은 마찰이 비대칭
#: 행렬을 만든다(ccx 의 반복 솔버는 대칭 양정치만 푼다).
#:
#: ⚠️ **구속 방정식(MPC)이 든 덱도 뺀다.** 「조건_반쪽구멍」(원격 변위의 `*RIGID BODY` · 원통
#:    지지의 `*TRANSFORM`)을 반복 솔버로 풀었더니 수렴했다고 끝났는데(106번, 오차 7.5e-3 <
#:    8.0e-3) 반력이 [553, 983, -307] N 이었다 — 직접 솔버는 [0, 1100, 0] N 으로 손셈과 같다.
#:    변위는 0.2% 안이라 그림만 보면 모른다(2026-11-13). 수렴 기준이 느슨해 구속 방정식에 걸린
#:    힘이 안 맞는다.
_DIRECT_ONLY = (
    "*FREQUENCY",
    "*STEADY STATE DYNAMICS",
    "*DYNAMIC",
    "*BUCKLE",
    "*CONTACT PAIR",
    "*RIGID BODY",
    "*EQUATION",
    "*TIE",
    "*TRANSFORM",
    "*MPC",
    "*COUPLING",
)


@dataclass(frozen=True)
class SolverPlan:
    """정적 해석을 무슨 선형 솔버로 풀까 — 메모리 어림과 함께."""

    dof: int
    estimate_mb: float
    available_mb: float | None
    can_iterate: bool
    iterative: bool
    static: bool = False

    @property
    def tight(self) -> bool:
        """어림이 남은 메모리의 `MEMORY_SHARE` 를 넘나."""
        return self.available_mb is not None and self.estimate_mb > (
            MEMORY_SHARE * self.available_mb
        )


def degrees_of_freedom(text: str) -> int:
    """덱의 절점 수 x 3 — `*NODE` 묶음의 줄을 센다(쉘 절점의 회전 자유도는 빼고 어림한다)."""
    count = 0
    inside = False
    for line in text.splitlines():
        head = line.lstrip()
        if head.startswith("*"):
            inside = head.upper().startswith("*NODE") and not head.upper().startswith(
                ("*NODE FILE", "*NODE PRINT", "*NODE OUTPUT")
            )
            continue
        if inside and head and not head.startswith("**"):
            count += 1
    return 3 * count


def spooles_mb(dof: int) -> float:
    """SPOOLES 의 최대 메모리 어림(MB)."""
    base, megabytes, power = SPOOLES_MB
    return float(megabytes * (max(dof, 1) / base) ** power)


def available_mb(
    cgroup_root: Path = Path("/sys/fs/cgroup"), proc: Path = Path("/proc")
) -> float | None:
    """지금 쓸 수 있는 메모리(MB) — 시스템의 MemAvailable 과 cgroup 의 남은 한도 중 가장 작은
    것. 못 읽으면 `None`(어림하지 않는다).

    **조상 cgroup 까지 본다** — 운영의 상한은 워커 하나가 아니라 워커 묶음
    (`<slug>-workers.slice`, `deploy.sh` 의 `WORKER_MEMORY_MAX`)에 걸린다. 워커 자신의
    `memory.max` 는 `max` 다.
    """
    found: list[float] = []
    try:
        for line in (proc / "meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                found.append(int(line.split()[1]) / 1024)
    except (OSError, ValueError, IndexError):
        pass
    try:
        group = next(
            line.split("::", 1)[1]
            for line in (proc / "self" / "cgroup").read_text().splitlines()
            if line.startswith("0::")
        )
    except (OSError, StopIteration):
        group = ""
    here = cgroup_root / group.strip().lstrip("/")
    while group and here != cgroup_root and cgroup_root in here.parents:
        try:
            limit = (here / "memory.max").read_text().strip()
            if limit != "max":
                used = int((here / "memory.current").read_text().strip())
                found.append((int(limit) - used) / 1024 / 1024)
        except (OSError, ValueError):
            pass
        here = here.parent
    return min(found) if found else None


def plan_solver(text: str, available: float | None) -> SolverPlan:
    """**정적이면 메모리를 어림해 솔버를 고른다** — 넘칠 것 같으면 반복 솔버.

    ⚠️ 전에는 직접 솔버(SPOOLES)만 써서 운영체제가 SIGKILL 로 끊은 뒤에야 알았다(운영 보고,
       2026-11-13). 자유도 16.7만 모델이 SPOOLES 로 2,337 MB, 반복 솔버로 221 MB 였다.
    """
    upper = text.upper()
    static = "*STATIC" in upper
    can_iterate = static and not any(mark in upper for mark in _DIRECT_ONLY)
    dof = degrees_of_freedom(text)
    estimate = spooles_mb(dof)
    mode = os.environ.get(LINEAR_SOLVER_ENV, "auto").strip().lower()
    if mode == "iterative":
        wanted = can_iterate
    elif mode == "spooles":
        wanted = False
    else:
        wanted = can_iterate and available is not None and estimate > MEMORY_SHARE * available
    return SolverPlan(dof, estimate, available, can_iterate, wanted, static)


def with_iterative(text: str) -> str:
    """정적 단계의 `*STATIC` 을 반복 솔버(`ITERATIVE CHOLESKY`)로."""
    return "\n".join(
        ITERATIVE_LINE if line.strip().upper() == "*STATIC" else line
        for line in text.splitlines()
    ) + ("\n" if text.endswith("\n") else "")


def solve(workdir: Path, *, timeout_seconds: int = 3600, **_ignored: object) -> StageResult:
    """`model.inp` 를 푼다. 로그는 폴더에 남긴다 — 나중에 사람이 읽을 유일한 단서다.

    **메모리를 먼저 어림한다**(`plan_solver`). 정적이면 넘칠 것 같을 때 반복 솔버로 풀고,
    그래도 운영체제가 끊으면 반복 솔버로 한 번 더 돌린다. 고유치 · 조화는 반복 솔버를 못 쓰므로
    어림을 결과에 적고(넘칠 것 같다고) 그대로 푼다 — 끊기면 실패 글에 어림이 함께 간다.
    """
    deck = workdir / DECK_NAME
    if not deck.is_file():
        raise StageFailure("solver_failed", f"솔버 입력 파일이 없습니다: {DECK_NAME}")

    text = deck.read_text(encoding="utf-8", errors="replace")
    plan = plan_solver(text, available_mb())
    iterative = plan.iterative
    if iterative:
        deck.write_text(with_iterative(text), encoding="utf-8")
    logger.info(
        "CalculiX 자유도 %s · SPOOLES 어림 %.0f MB · 남은 메모리 %s MB → %s",
        f"{plan.dof:,}",
        plan.estimate_mb,
        f"{plan.available_mb:.0f}" if plan.available_mb is not None else "?",
        "반복 솔버" if iterative else "직접 솔버",
    )
    retried = False
    started = time.perf_counter()
    try:
        done = tools.run(
            tools.ccx_bin(),
            [deck.stem],
            cwd=workdir,
            timeout_seconds=timeout_seconds,
            what="CalculiX",
        )
    except StageFailure as failure:
        forced = os.environ.get(LINEAR_SOLVER_ENV, "").strip().lower() == "spooles"
        if failure.code != "out_of_memory" or iterative or not plan.can_iterate or forced:
            raise _with_estimate(failure, plan) from failure
        # **끊기면 반복 솔버로 한 번 더** — 어림이 빗나갔거나 옆 작업이 메모리를 가져갔다.
        logger.warning("CalculiX 가 메모리로 끊겼습니다 — 반복 솔버로 다시 풉니다")
        deck.write_text(with_iterative(text), encoding="utf-8")
        iterative = retried = True
        try:
            done = tools.run(
                tools.ccx_bin(),
                [deck.stem],
                cwd=workdir,
                timeout_seconds=timeout_seconds,
                what="CalculiX",
            )
        except StageFailure as again:
            raise _with_estimate(again, plan) from again
    seconds = time.perf_counter() - started
    log = (done.stdout or "") + (done.stderr or "")
    (workdir / LOG_NAME).write_text(log, encoding="utf-8")

    found = ERROR_MARK.search(log)
    if found:
        line = next(
            (one.strip() for one in log.splitlines() if ERROR_MARK.search(one)),
            found.group(0),
        )
        raise StageFailure("solver_failed", f"CalculiX 가 실패했습니다: {line[:200]}")
    if done.returncode != 0:
        raise StageFailure(
            "solver_failed",
            f"CalculiX 가 {done.returncode} 로 끝났습니다 — {LOG_NAME} 를 보세요.",
        )
    if not (workdir / DATA_NAME).is_file():
        raise StageFailure(
            "solver_failed",
            f"결과 파일({DATA_NAME})이 안 나왔습니다 — {LOG_NAME} 를 보세요.",
        )
    artifacts = [ArtifactSpec("solve_out", workdir / LOG_NAME)]
    if (workdir / RESULT_NAME).is_file():
        artifacts.append(ArtifactSpec("frd", workdir / RESULT_NAME))
    logger.info("CalculiX %.1f초", seconds)
    summary: dict[str, object] = {
        "solver_seconds": round(seconds, 1),
        "solver": "calculix",
        "memory_estimate_mb": round(plan.estimate_mb),
    }
    if plan.static:
        summary["linear_solver"] = "iterative" if iterative else "spooles"
    if retried:
        summary["solver_retry"] = "직접 솔버가 메모리로 끊겨 반복 솔버로 다시 풀었습니다."
    elif plan.tight and not plan.can_iterate:
        summary["memory_warning"] = _tight_message(plan)
    return StageResult(
        artifacts=artifacts,
        summary=summary,
        detail=f"CalculiX {seconds:.1f}초" + (" · 반복 솔버" if iterative else ""),
    )


def _tight_message(plan: SolverPlan) -> str:
    return (
        f"메모리 어림 {plan.estimate_mb:,.0f} MB 가 남은 메모리 "
        f"{plan.available_mb or 0:,.0f} MB 의 {MEMORY_SHARE:.0%} 를 넘습니다(자유도 "
        f"{plan.dof:,}) — 고유치 · 조화 · 접촉 · 구속 방정식(원격점 · 강체 · 원통 지지)이 든 "
        "해석은 반복 솔버를 못 써 직접 솔버로 풉니다."
    )


def _with_estimate(failure: StageFailure, plan: SolverPlan) -> StageFailure:
    """메모리로 끊긴 실패에 어림을 붙인다 — 「얼마나 모자랐나」 를 알아야 크기를 고른다."""
    if failure.code != "out_of_memory":
        return failure
    shown = (
        f" 자유도 {plan.dof:,} · 직접 솔버 메모리 어림 {plan.estimate_mb:,.0f} MB"
        + (
            f" · 남은 메모리 {plan.available_mb:,.0f} MB"
            if plan.available_mb is not None
            else ""
        )
        + "."
    )
    return StageFailure("out_of_memory", failure.message + shown, details=failure.details)
