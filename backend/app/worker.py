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
import threading
import time
import uuid
from types import FrameType
from typing import Any

from app import version
from app.config import get_settings
from app.core import toolcheck
from app.database import SessionLocal
from app.logging_setup import setup_logging
from app.modules.simulations import services

logger = logging.getLogger("app.worker")

POLL_SECONDS = 1.0
STALE_CHECK_EVERY = 60.0


def solvers_for(
    setting: str, *, executor: str, tools: dict[str, Any]
) -> tuple[str, ...] | None:
    """이 워커가 집을 솔버. `None` 이면 전부, 빈 것이면 **아무것도 안 집는다.**

    설정(`SIMULATION_SOLVERS`)이 있으면 그것이다. 비면 **이 기계에서 돌릴 수 있는 것
    전부**를 깔린 도구(`toolcheck.report`)로 고른다 — 전에는 비면 무조건 전부 집어서, gmsh 가
    없는 개발 PC 의 워커가 CalculiX 작업을 집어 1초 만에 실패시켰다(2026-10-04). 못 돌리는
    작업은 대기열에 남겨야 다른 워커가 집고, 작업을 거는 화면이 「집을 워커가 없다」 고 미리
    말한다.

    모의 실행기는 솔버를 부르지 않으므로 전부 집는다. Ansys 는 확인했는데 없을 때만 뺀다 —
    `windows-bridge` 는 Windows 쪽이라 여기서 확인하지 못한다(모른다를 없다로 읽지 않는다).
    """
    raw = setting.strip()
    if raw:
        return tuple(one.strip() for one in raw.split(",") if one.strip())
    if executor == "fake":
        return None
    able: list[str] = []
    ansys = tools.get("ansys") or {}
    if not (ansys.get("checked") and not ansys.get("path")):
        able.append("ansys")
    if tools.get("gmsh") and tools.get("ccx"):
        able.append("calculix")
    return tuple(able)


class Worker:
    def __init__(self) -> None:
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self.stopping = False
        #: 신호 줄이 읽는 지금 상태 — 루프가 바꾸고 신호 줄이 적는다.
        self.state = "idle"
        self.current_simulation_id: uuid.UUID | None = None
        #: 기동 때 정한 것 — 첫 신호에 실려 워커 줄에 남는다.
        self.identity: dict[str, Any] = {}
        self._beating = threading.Event()

    def stop(self, signum: int, _frame: FrameType | None) -> None:
        logger.info("종료 신호 %s — 지금 작업을 끝내고 멈춥니다.", signum)
        self.stopping = True
        self.state = "stopping" if self.current_simulation_id else "stopped"

    def _beat(self) -> None:
        """**살아 있다는 신호**를 적는다 — 루프가 솔브 하나에 몇 시간 묶여 있어도 이 줄은 따로
        돈다. 신호가 끊기면 서버 화면이 「응답 없음」 으로 보이고, 잡고 있던 작업은 다른 워커가
        되살린다. 적다가 실패해도(DB 가 잠깐 끊김) 워커를 죽이지 않는다.

        **세션은 매번 새로 연다** — 메인 루프의 세션을 나눠 쓰면 두 줄이 한 연결에서 엉킨다."""
        while not self._beating.is_set():
            db = SessionLocal()
            try:
                services.beat(
                    db,
                    self.worker_id,
                    state=self.state,
                    current_simulation_id=self.current_simulation_id,
                    **self.identity,
                )
            except Exception:
                logger.warning("워커 신호를 적지 못했습니다 — 다음에 다시.", exc_info=True)
            finally:
                db.close()
            self._beating.wait(services.BEAT_EVERY)

    def run(self) -> None:
        executor = services.default_executor()
        settings = get_settings()
        tools = toolcheck.report(
            executor=executor.name,
            ansys_root=settings.ansys_root,
            ansys_version=settings.ansys_version,
        )
        solvers = solvers_for(settings.simulation_solvers, executor=executor.name, tools=tools)
        if solvers == ():
            # **아무것도 못 돌리는 워커는 띄우지 않는다** — 떠 있으면 서버 화면에 「살아
            # 있음」 으로 보이는데 아무 작업도 안 집는다. 까닭을 적고 끝낸다.
            raise SystemExit(
                "이 기계에서 돌릴 수 있는 솔버가 없습니다 — gmsh · ccx(CalculiX) 나 Ansys 를 "
                "깔고 다시 띄우세요."
            )
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        logger.info(
            "워커 시작 (%s, 실행기 %s, 솔버 %s)",
            self.worker_id,
            executor.name,
            "전부" if solvers is None else ",".join(solvers) or "없음",
        )
        if not settings.simulation_solvers.strip() and solvers is not None:
            missing = [name for name in services.SOLVERS if name not in solvers]
            if missing:
                logger.warning(
                    "%s 은 이 기계에 도구가 없어 집지 않습니다 — gmsh · ccx 를 깔거나 "
                    "GMSH_BIN · CCX_BIN 으로 자리를 알려 주세요(Ansys 는 ANSYS_ROOT).",
                    ",".join(missing),
                )
        # **무엇을 집고 무엇이 깔렸나는 워커가 적는다** — 워커마다 환경 파일 · 이미지가 다르다.
        self.identity = {
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "version": version.current(),
            "executor": executor.name,
            "solvers": list(solvers or []),
            "tools": tools,
        }
        beater = threading.Thread(target=self._beat, name="worker-beat", daemon=True)
        beater.start()

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
                self.current_simulation_id = simulation.id
                self.state = "busy"
                try:
                    done = services.execute(
                        db, simulation, worker_id=self.worker_id, executor=executor
                    )
                finally:
                    self.current_simulation_id = None
                    self.state = "stopping" if self.stopping else "idle"
                logger.info("해석 작업 %s → %s", done.id, done.status)
            except Exception:
                # DB 가 잠깐 끊긴 것 같은 일. 죽지 말고 잠시 뒤 다시.
                logger.exception(
                    "워커 루프 오류 — %.0f초 뒤 다시 시도합니다.", POLL_SECONDS * 5
                )
                time.sleep(POLL_SECONDS * 5)
            finally:
                db.close()
        # 멈췄다고 마지막으로 적는다 — 안 적으면 2분 뒤 「응답 없음」 으로 보인다.
        self._beating.set()
        db = SessionLocal()
        try:
            services.beat(db, self.worker_id, state="stopped", **self.identity)
        except Exception:
            logger.warning("멈춤을 적지 못했습니다.", exc_info=True)
        finally:
            db.close()
        logger.info("워커 종료")


def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    Worker().run()


if __name__ == "__main__":
    main()
