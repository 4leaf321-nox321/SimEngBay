"""솔브 단계 — CalculiX 를 부른다.

**종료 코드만 보면 안 된다.** ccx 는 입력이 틀려도 0 으로 끝나면서 출력에 `*ERROR` 를 적는다 —
그것을 안 읽으면 다음 단계가 「결과 파일이 없다」 로 실패하고, 사람은 솔버 문제를 추출 문제로
읽는다. MAPDL 쪽에서 로그를 `*** ERROR ***` 블록으로만 훑기로 한 것과 같은 교훈이다
(실측 2026-10-02: 배너의 라이선스 글자를 오류로 읽어 엉뚱한 진단을 했다).
"""

from __future__ import annotations

import logging
import re
import time
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


def solve(workdir: Path, *, timeout_seconds: int = 3600, **_ignored: object) -> StageResult:
    """`model.inp` 를 푼다. 로그는 폴더에 남긴다 — 나중에 사람이 읽을 유일한 단서다."""
    deck = workdir / DECK_NAME
    if not deck.is_file():
        raise StageFailure("solver_failed", f"솔버 입력 파일이 없습니다: {DECK_NAME}")

    started = time.perf_counter()
    done = tools.run(
        tools.ccx_bin(),
        [deck.stem],
        cwd=workdir,
        timeout_seconds=timeout_seconds,
        what="CalculiX",
    )
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
    return StageResult(
        artifacts=artifacts,
        summary={"solver_seconds": round(seconds, 1), "solver": "calculix"},
        detail=f"CalculiX {seconds:.1f}초",
    )
