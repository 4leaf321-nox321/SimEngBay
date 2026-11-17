"""솔브 단계 — CalculiX 를 부른다.

**종료 코드만 보면 안 된다.** ccx 는 입력이 틀려도 0 으로 끝나면서 출력에 `*ERROR` 를 적는다 —
그것을 안 읽으면 다음 단계가 「결과 파일이 없다」 로 실패하고, 사람은 솔버 문제를 추출 문제로
읽는다. MAPDL 쪽에서 로그를 `*** ERROR ***` 블록으로만 훑기로 한 것과 같은 교훈이다
(실측 2026-10-02: 배너의 라이선스 글자를 오류로 읽어 엉뚱한 진단을 했다).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.calculix import bonding, tables, tools
from app.core.modes import search as mode_search
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
#: ⚠️ **강체 묶음 · 국부 좌표계가 든 덱도 뺀다.** 「조건_반쪽구멍」(원격 변위의 `*RIGID BODY` ·
#:    원통 지지의 `*TRANSFORM`)을 반복 솔버로 풀었더니 수렴했다고 끝났는데(106번, 오차 7.5e-3 <
#:    8.0e-3) 반력이 [553, 983, -307] N 이었다 — 직접 솔버는 [0, 1100, 0] N 으로 손셈과 같다.
#:    변위는 0.2% 안이라 그림만 보면 모른다(2026-11-13).
#:    본딩의 `*TIE` · 볼트 예압의 `*EQUATION` 은 괜찮다 — 두바디 바닥 반력 2400.06 N(직접
#:    2400.0), 볼트 판본딩 -599.68 N · 볼트 힘 1011.27 N(직접 -600.0 · 1012.05, 2026-11-16).
#:    바디가 여럿인 정적은 모두 `*TIE` 로 묶이므로(`bonding.py`) 이것을 막으면 그런 모델은
#:    메모리가 모자랄 때 피할 길이 없다.
_DIRECT_ONLY = (
    "*FREQUENCY",
    "*STEADY STATE DYNAMICS",
    "*DYNAMIC",
    "*BUCKLE",
    "*CONTACT PAIR",
    "*RIGID BODY",
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


#: 고유치 덱(모달 · 선응력 모달 · 조화의 모드)은 **SPOOLES 를 한 스레드로** 푼다. 여러 스레드면
# 같은
#: 덱이 풀 때마다 다른 고유치를 낸다 — 외팔보 한 장을 4 스레드로 12번 풀었더니 6번이
# 어긋났다(최대
#: 3%, 한 번은 가짜 0 Hz 모드 · 1,421 Hz). SPOOLES 만 한 스레드로 두면 12번 모두 같았고(조립 ·
#: 응력 계산은 그대로 여러 스레드), 시간도 거의 같았다(실측 2026-11-17, ccx 2.21). 기본 2
# 스레드는
#: 12번 모두 맞았지만 그것이 늘 맞는다는 증거는 아니다 — 운영자가 스레드를 늘리면 판정이
# 흔들린다.
EIGEN_ENV = {"CCX_NPROC_EQUATION_SOLVER": "1"}
BOUNDARY_NAME = "boundary.json"
_FREQUENCY_HEAD = re.compile(r"^\*FREQUENCY\b", re.IGNORECASE)


def eigen_env(text: str) -> dict[str, str] | None:
    """고유치를 푸는 덱이면 SPOOLES 를 한 스레드로(`EIGEN_ENV`)."""
    return dict(EIGEN_ENV) if "*FREQUENCY" in text.upper() else None


#: 솔버가 셈한 질량이 모델링 셈과 이만큼 넘게 다르면 적는다 — 둘 다 같은 밀도인데 하나는
#: 형상 부피, 하나는 메시 부피라 곡면에서 조금 갈린다. 단위가 어긋나면 10³ 배씩 갈린다.
MASS_TOLERANCE = 0.05


def _mass_check(workdir: Path) -> dict[str, object]:
    """**솔버가 셈한 전체 질량**(`.dat` 의 EMAS, `deck._finish`)과 모델링이 셈한 질량(형상
    부피 x 밀도, `boundary.json` 의 `mass_kg`)을 견준다. 요약 칸 `solver_mass_kg` 와, 5 %
    넘게 다르면 `mass_warning` — 덱의 밀도 · 단위가 어긋난 것이다."""
    data = workdir / DATA_NAME
    if not data.is_file():
        return {}
    tonne = tables.model_mass(data.read_text(encoding="utf-8", errors="replace"))
    if tonne is None or tonne <= 0:
        return {}
    solver_kg = tonne * 1e3
    out: dict[str, object] = {"solver_mass_kg": float(f"{solver_kg:.6g}")}
    try:
        saved = json.loads((workdir / BOUNDARY_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    ours = saved.get("mass_kg") if isinstance(saved, dict) else None
    if not isinstance(ours, int | float) or ours <= 0:
        return out
    if abs(solver_kg / ours - 1) > MASS_TOLERANCE:
        out["mass_warning"] = (
            f"솔버가 셈한 질량({solver_kg:.4g} kg)이 형상 부피 x 밀도({ours:.4g} kg)와 "
            f"{solver_kg / ours:.3g} 배 다릅니다 — 덱의 밀도 · 단위를 보세요(요약의 「덱 "
            "물성」)."
        )
    return out


def asked_modes(text: str) -> int | None:
    """`*FREQUENCY` 다음 줄의 모드 수."""
    lines = text.splitlines()
    for at, line in enumerate(lines[:-1]):
        if _FREQUENCY_HEAD.match(line.strip()):
            head = lines[at + 1].split(",")[0].strip()
            return int(head) if head.isdigit() else None
    return None


def with_modes(text: str, count: int) -> str:
    """`*FREQUENCY` 다음 줄의 모드 수를 바꾼다(나머지 칸은 그대로)."""
    lines = text.splitlines()
    for at, line in enumerate(lines[:-1]):
        if _FREQUENCY_HEAD.match(line.strip()):
            rest = lines[at + 1].split(",")[1:]
            lines[at + 1] = ", ".join([str(count), *(one.strip() for one in rest)])
            break
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def solve(workdir: Path, *, timeout_seconds: int = 3600, **_ignored: object) -> StageResult:
    """`model.inp` 를 푼다. 로그는 폴더에 남긴다 — 나중에 사람이 읽을 유일한 단서다.

    **메모리를 먼저 어림한다**(`plan_solver`). 정적이면 넘칠 것 같을 때 반복 솔버로 풀고,
    그래도 운영체제가 끊으면 반복 솔버로 한 번 더 돌린다. 고유치 · 조화는 반복 솔버를 못 쓰므로
    어림을 결과에 적고(넘칠 것 같다고) 그대로 푼다 — 끊기면 실패 글에 어림이 함께 간다.

    모달에 **찾을 주파수 범위**가 있으면(`modes.search`) 범위 안이 모자랄 때 모드 수를 늘려
    다시 푼다 — 덱에 범위를 주지 않으므로 낮은 것부터 구한다.
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
    env_extra = eigen_env(text)
    retried = False
    started = time.perf_counter()
    try:
        done = tools.run(
            tools.ccx_bin(),
            [deck.stem],
            cwd=workdir,
            timeout_seconds=timeout_seconds,
            what="CalculiX",
            env_extra=env_extra,
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
                env_extra=env_extra,
            )
        except StageFailure as again:
            raise _with_estimate(again, plan) from again
    _judged(workdir, done)

    # **찾을 주파수 범위** — 범위 안이 모자라고 범위 위쪽에 못 닿았으면 모드를 늘려 다시 푼다.
    searched = mode_search.read(workdir / BOUNDARY_NAME)
    passes = 1
    solved: int | None = None
    if searched is not None:
        while passes < mode_search.MAX_PASSES:
            current = deck.read_text(encoding="utf-8", errors="replace")
            solved = asked_modes(current)
            if solved is None:
                break
            report = (workdir / DATA_NAME).read_text(encoding="utf-8", errors="replace")
            more = mode_search.next_count(tables.frequencies(report), solved, searched)
            if more is None:
                break
            logger.info(
                "범위 %s 안의 모드가 모자랍니다 — 모드 %d개로 다시 풉니다",
                searched.label,
                more,
            )
            deck.write_text(with_modes(current, more), encoding="utf-8")
            done = tools.run(
                tools.ccx_bin(),
                [deck.stem],
                cwd=workdir,
                timeout_seconds=timeout_seconds,
                what="CalculiX",
                env_extra=env_extra,
            )
            _judged(workdir, done)
            passes += 1
            solved = more

    seconds = time.perf_counter() - started
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
    summary.update(_mass_check(workdir))
    if searched is not None and solved is not None:
        # 범위를 채우려고 몇 번 · 몇 개까지 풀었나 — 큰 모델이면 시간이 그만큼 든다.
        summary["mode_search"] = f"{searched.label} · {passes}번 풀어 모드 {solved}개까지"
    # **쌍마다 연결 결과** — 몇 절점이 묶였나(반경 밖이라 ccx 가 안 묶은 절점을 뺀다).
    log = (workdir / LOG_NAME).read_text(encoding="utf-8", errors="replace")
    summary.update(bonding.connection_report(workdir, log))
    return StageResult(
        artifacts=artifacts,
        summary=summary,
        detail=f"CalculiX {seconds:.1f}초"
        + (" · 반복 솔버" if iterative else "")
        + (f" · 범위 찾기 {passes}번" if passes > 1 else ""),
    )


def _judged(workdir: Path, done: Any) -> None:
    """ccx 한 번의 끝 — 로그를 남기고 **실패면 까닭을 달아 올린다**(종료 코드만 믿지
    않는다)."""
    log = (done.stdout or "") + (done.stderr or "")
    (workdir / LOG_NAME).write_text(log, encoding="utf-8")
    if "nonpositive jacobian" in log:
        raise _jacobian_failure(workdir, log)
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


#: ccx 가 뒤집힌 요소에 찍는 말 — `nonpositive jacobian` · `determinant in element N`.
_JACOBIAN = re.compile(r"nonpositive jacobian\s+determinant in element\s+(\d+)")


def _jacobian_failure(workdir: Path, log: str) -> StageFailure:
    """**뒤집힌 요소가 어느 바디의 것인가** — 모델링이 적은 요소 번호 구간(`boundary.json` 의
    `element_owners`)으로 센다. 「CalculiX 가 실패했습니다: nonpositive jacobian」 만으로는
    어느 파트에 크기를 줘야 할지 모른다(운영 VOC, 2026-11-16)."""
    elements = sorted({int(one) for one in _JACOBIAN.findall(log)})
    owners: list[list[Any]] = []
    with contextlib.suppress(OSError, ValueError):
        saved = json.loads((workdir / "boundary.json").read_text(encoding="utf-8"))
        owners = saved.get("element_owners") or []
    counts: dict[str, int] = {}
    for number in elements:
        name = next((row[2] for row in owners if row[0] <= number <= row[1]), "모르는 바디")
        counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda pair: -pair[1])
    shown = " · ".join(f"「{name}」 {count}개" for name, count in ranked)
    return StageFailure(
        "solver_failed",
        f"요소 {len(elements)}개가 뒤집혀 CalculiX 가 멈췄습니다(nonpositive jacobian)"
        + (f" — {shown}" if shown else "")
        + ". 그 바디에 파트 크기를 작게 주거나 전역 요소 크기를 줄이세요(얇은 벽 · 작은 "
        "바디보다 요소가 크면 2차로 올릴 때 뒤집힌다).",
        details={"elements": elements[:200], "bodies": counts},
    )


def _tight_message(plan: SolverPlan) -> str:
    return (
        f"메모리 어림 {plan.estimate_mb:,.0f} MB 가 남은 메모리 "
        f"{plan.available_mb or 0:,.0f} MB 의 {MEMORY_SHARE:.0%} 를 넘습니다(자유도 "
        f"{plan.dof:,}) — 고유치 · 조화 · 접촉 · 강체 묶음(원격점 · 강체) · 원통 지지가 든 "
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
