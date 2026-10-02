"""해석 작업 워커 — `queued` 를 집어 네 단계를 돌린다.

    python -m app.worker            # 하나. 더 띄우면 그만큼 동시에 돈다(SKIP LOCKED)

**Ansys 워커 수 = Mechanical 라이선스 수.** 모델링 단계가 라이선스를 하나 물고 있으므로 그보다
많이 띄우면 나머지는 라이선스 오류로 실패한다. **CalculiX 는 라이선스가 없어 코어 수만큼** 띄울
수 있으므로, `SIMULATION_SOLVERS` 로 갈라 띄운다 —

    SIMULATION_SOLVERS=ansys     python -m app.worker   # 하나만
    SIMULATION_SOLVERS=calculix  python -m app.worker   # 여럿

비워 두면 전부 집는다(설정을 안 건드린 설치는 그대로 돈다). 개발에서는 `run.py` 가 하나를
자식으로 띄우고, 운영은 systemd 유닛(`<slug>-worker@N`)이 띄운다.

실행기(`SIMULATION_EXECUTOR`)는 기동할 때 한 번 고른다 — 설정 오타는 첫 작업을 집기 전에
여기서 죽는다. 작업을 집고 나서 죽으면 그 작업이 `failed` 로 남고, 사람은 오타를 작업 실패로
읽는다.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
from types import FrameType

from app.config import get_settings
from app.database import SessionLocal
from app.logging_setup import setup_logging
from app.modules.simulations import services

logger = logging.getLogger("app.worker")

POLL_SECONDS = 1.0
STALE_CHECK_EVERY = 60.0


def _solvers() -> tuple[str, ...] | None:
    """이 워커가 집을 솔버. 비면 `None`(전부) — 설정을 안 건드린 설치가 그대로 돌아야 한다."""
    raw = get_settings().simulation_solvers.strip()
    if not raw:
        return None
    return tuple(one.strip() for one in raw.split(",") if one.strip())


class Worker:
    def __init__(self) -> None:
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self.stopping = False

    def stop(self, signum: int, _frame: FrameType | None) -> None:
        logger.info("종료 신호 %s — 지금 작업을 끝내고 멈춥니다.", signum)
        self.stopping = True

    def run(self) -> None:
        executor = services.default_executor()
        solvers = _solvers()
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        logger.info(
            "워커 시작 (%s, 실행기 %s, 솔버 %s)",
            self.worker_id,
            executor.name,
            ",".join(solvers) if solvers else "전부",
        )

        last_stale = 0.0
        while not self.stopping:
            db = SessionLocal()
            try:
                if time.monotonic() - last_stale > STALE_CHECK_EVERY:
                    revived = services.requeue_stale(db)
                    if revived:
                        logger.warning("갇힌 해석 작업 %d 건을 되살렸습니다.", revived)
                    last_stale = time.monotonic()

                simulation = services.claim_next(db, self.worker_id, solvers=solvers)
                if simulation is None:
                    time.sleep(POLL_SECONDS)
                    continue
                logger.info("해석 작업 시작 %s (%s)", simulation.id, simulation.recipe)
                done = services.execute(
                    db, simulation, worker_id=self.worker_id, executor=executor
                )
                logger.info("해석 작업 %s → %s", done.id, done.status)
            except Exception:
                # DB 가 잠깐 끊긴 것 같은 일. 죽지 말고 잠시 뒤 다시.
                logger.exception(
                    "워커 루프 오류 — %.0f초 뒤 다시 시도합니다.", POLL_SECONDS * 5
                )
                time.sleep(POLL_SECONDS * 5)
            finally:
                db.close()
        logger.info("워커 종료")


def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    Worker().run()


if __name__ == "__main__":
    main()
