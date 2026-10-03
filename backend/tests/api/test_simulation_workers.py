"""워커 · 솔버 · 라이선스 — **서버 화면이 「살아 있나 · 무엇을 집나」 를 답하는가.**

워커가 신호를 안 적던 때는 「대기에서 안 움직인다」 를 `journalctl` 로만 알 수 있었다. 특히
CalculiX 를 집는 워커가 하나도 없으면 그 솔버의 작업은 **영원히 대기**하고, 아무도 그 사실을
말해 주지 않는다. CompCore 의 `workers` 와 같은 계약이다(15초 신호 · 2분이면 응답 없음).

시험 DB 는 스위트 전체가 함께 쓴다 — 다른 시험이 남긴 작업 · 워커가 섞이므로 정확한 수 대신
「내 것이 있나」 와 차이로 본다.
"""

from __future__ import annotations

import io
import json
import threading
import time
import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.stages import StageCanceled, StageContext, StageResult
from app.database import SessionLocal
from app.modules.simulations import services
from app.modules.simulations.models import Simulation, SimulationWorker
from app.worker import Worker
from tests.api.conftest import Signed

STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
MATERIAL = {
    "name": "SS400",
    "youngs_modulus_gpa": 200,
    "poisson_ratio": 0.3,
    "density_kg_m3": 7850,
}


def _queue(client: TestClient, who: Signed, spec: dict[str, Any]) -> str:
    response = client.post(
        "/api/simulations",
        data={"spec": json.dumps(spec), "workspace_slug": who.workspace},
        files={"file": ("브래킷.step", io.BytesIO(STEP), "model/step")},
        headers=who.headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _tools() -> dict[str, Any]:
    return {"gmsh": None, "ccx": "/usr/bin/ccx", "ansys": {"version": 252, "checked": False}}


@pytest.fixture(autouse=True)
def queued_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """요청 안에서 돌리지 않는다 — 작업이 대기에 남아야 줄이 보인다."""
    monkeypatch.setattr(get_settings(), "jobs_inline", False)


def test_워커가_적은_솔버와_도구를_서버_화면이_보여_준다(
    client: TestClient, db: Session, admin: Signed, member: Signed
) -> None:
    worker_id = f"host-a:{uuid.uuid4().hex[:6]}"
    services.beat(
        db,
        worker_id,
        state="idle",
        hostname="host-a",
        pid=101,
        version="0.3.0",
        executor="local",
        solvers=["ansys"],
        tools=_tools(),
    )

    got = client.get("/api/simulations/workers", headers=admin.headers)
    assert got.status_code == 200, got.text
    body = got.json()
    mine = next(one for one in body["workers"] if one["id"] == worker_id)
    assert mine["state"] == "idle"
    # **집는 솔버는 워커가 적은 값이다** — API 의 설정이 아니다(워커마다 환경 파일이 다르다).
    assert mine["solvers"] == ["ansys"]
    assert mine["tools"]["ccx"] == "/usr/bin/ccx"
    assert mine["executor"] == "local"
    assert {one["solver"] for one in body["queues"]} >= {"ansys", "calculix"}
    assert body["alive"] >= 1

    # 호스트 · 설치 경로가 실린다 — 멤버는 못 본다.
    assert client.get("/api/simulations/workers", headers=member.headers).status_code == 403


def test_집을_워커가_없는_솔버의_대기를_센다(
    client: TestClient, db: Session, admin: Signed, member: Signed
) -> None:
    """**CalculiX 작업이 있는데 CalculiX 를 집는 워커가 없으면** 그 줄이 0 을 말한다."""
    # 다른 시험이 남긴 살아 있는 워커를 치운다 — 이 시험은 「아무도 없다」 에서 출발한다.
    for row in db.query(SimulationWorker).all():
        row.state = "stopped"
    db.commit()
    services.beat(db, f"ansys-only:{uuid.uuid4().hex[:6]}", state="idle", solvers=["ansys"])
    before = next(
        one
        for one in client.get("/api/simulations/workers", headers=admin.headers).json()[
            "queues"
        ]
        if one["solver"] == "calculix"
    )["queued"]
    _queue(client, member, {"recipe": "modal", "solver": "calculix", "material": MATERIAL})

    body = client.get("/api/simulations/workers", headers=admin.headers).json()
    line = next(one for one in body["queues"] if one["solver"] == "calculix")
    assert line["queued"] == before + 1
    assert line["workers_alive"] == 0
    assert line["oldest_queued_seconds"] is not None
    assert (
        next(one for one in body["queues"] if one["solver"] == "ansys")["workers_alive"] >= 1
    )

    # 작업을 거는 화면도 같은 답을 받는다(관리자가 아니어도).
    seen = client.get("/api/simulations/solvers", headers=member.headers).json()
    calculix = next(one for one in seen if one["solver"] == "calculix")
    assert calculix["workers_alive"] == 0
    assert calculix["queued"] >= 1


def test_신호가_끊긴_워커의_작업은_곧바로_되살린다(
    client: TestClient, db: Session, admin: Signed, member: Signed
) -> None:
    """**3시간을 기다리지 않는다.** 신호를 적는 워커가 2분 조용하면 죽은 것이다."""
    worker_id = f"dying:{uuid.uuid4().hex[:6]}"
    job_id = _queue(client, member, {"recipe": "modal", "material": MATERIAL})
    services.beat(db, worker_id, state="idle", solvers=[])
    picked = None
    # 다른 시험이 남긴 대기 작업이 먼저 집힐 수 있다 — 내 것이 나올 때까지.
    for _ in range(200):
        picked = services.claim_next(db, worker_id)
        if picked is None or str(picked.id) == job_id:
            break
    assert picked is not None and str(picked.id) == job_id
    services.beat(db, worker_id, state="busy", current_simulation_id=picked.id)

    row = db.get(SimulationWorker, worker_id)
    assert row is not None
    row.last_seen_at = row.last_seen_at - timedelta(minutes=3)
    db.commit()

    body = client.get("/api/simulations/workers", headers=admin.headers).json()
    assert next(one for one in body["workers"] if one["id"] == worker_id)["state"] == "lost"

    assert services.requeue_stale(db) >= 1
    revived = db.get(Simulation, uuid.UUID(job_id))
    assert revived is not None
    db.refresh(revived)
    assert revived.status == "queued"
    assert revived.worker_id is None


def test_취소를_요청받은_채_죽었으면_되살리지_않고_취소로_끝낸다(
    client: TestClient, db: Session, member: Signed
) -> None:
    worker_id = f"dying:{uuid.uuid4().hex[:6]}"
    job_id = _queue(client, member, {"recipe": "modal", "material": MATERIAL})
    services.beat(db, worker_id, state="idle")
    for _ in range(200):
        picked = services.claim_next(db, worker_id)
        if picked is None or str(picked.id) == job_id:
            break
    assert (
        client.post(f"/api/simulations/{job_id}/cancel", headers=member.headers).status_code
        == 200
    )
    row = db.get(SimulationWorker, worker_id)
    assert row is not None
    row.last_seen_at = row.last_seen_at - timedelta(minutes=3)
    db.commit()

    services.requeue_stale(db)
    ended = db.get(Simulation, uuid.UUID(job_id))
    assert ended is not None
    db.refresh(ended)
    # 되살리면 사람이 멈춘 작업이 다시 돈다.
    assert ended.status == "canceled"


def test_돌고_있는_Ansys_작업이_라이선스를_쥔_것으로_보인다(
    client: TestClient, db: Session, admin: Signed, member: Signed
) -> None:
    """**모델링(Mechanical) · 솔버 단계가 라이선스를 쥔다** — 추론이지만 지금 누가 쥐었나를
    아는 유일한 자리다(사람이 따로 연 Mechanical 은 못 본다)."""
    job_id = _queue(client, member, {"recipe": "modal", "material": MATERIAL})
    job = db.get(Simulation, uuid.UUID(job_id))
    assert job is not None
    job.status = "solving"
    job.worker_id = "licensed:1"
    db.commit()

    holders = client.get("/api/simulations/workers", headers=admin.headers).json()[
        "license_holders"
    ]
    assert any(one["simulation_id"] == job_id for one in holders)

    # CalculiX 작업은 라이선스를 쥐지 않는다.
    open_id = _queue(
        client, member, {"recipe": "modal", "solver": "calculix", "material": MATERIAL}
    )
    other = db.get(Simulation, uuid.UUID(open_id))
    assert other is not None
    other.status = "solving"
    db.commit()
    holders = client.get("/api/simulations/workers", headers=admin.headers).json()[
        "license_holders"
    ]
    assert not any(one["simulation_id"] == open_id for one in holders)
    # 시험 DB 를 함께 쓰므로 끝낸 것으로 돌려 둔다 — 다음 시험의 줄 셈에 섞이지 않게.
    job.status = other.status = "failed"
    db.commit()


def test_워커는_따로_도는_줄에서_신호를_적는다(db: Session) -> None:
    """**솔브 하나가 몇 시간이어도 신호는 따로 돈다** — 메인 루프에서 적으면 그동안 「응답
    없음」 으로 보인다."""
    worker = Worker()
    worker.identity = {"executor": "fake", "solvers": ["calculix"], "tools": _tools()}
    beater = threading.Thread(target=worker._beat, daemon=True)
    beater.start()
    try:
        for _ in range(50):
            db.expire_all()
            row = db.get(SimulationWorker, worker.worker_id)
            if row is not None:
                break
            time.sleep(0.05)
        assert row is not None, "신호 줄이 워커 행을 적지 않았다"
        assert row.solvers == ["calculix"]
        assert row.executor == "fake"
    finally:
        worker._beating.set()
        beater.join(timeout=5)


class _Hijacked:
    """단계 도중에 **다른 워커가 작업을 되살려 집어 간다** — DB 가 몇 분 끊겼다 돌아온 때다."""

    name = "hijacked"

    def __init__(self, simulation_id: uuid.UUID) -> None:
        self.simulation_id = simulation_id

    def run(self, ctx: StageContext, should_cancel: Any = None) -> StageResult:
        other = SessionLocal()
        try:
            row = other.get(Simulation, self.simulation_id)
            assert row is not None
            row.worker_id = "thief:1"
            row.status = "fetching"
            other.commit()
        finally:
            other.close()
        if should_cancel is not None and should_cancel():
            raise StageCanceled("다른 워커")
        return StageResult(detail="끝")


def test_다른_워커가_집어_간_작업에는_결과를_덮어쓰지_않는다(
    client: TestClient, db: Session, member: Signed
) -> None:
    """**두 워커가 같은 작업에 쓰지 않는다.** 신호가 끊긴 사이 되살려진 작업을 원래 워커가
    끝까지 돌면, 집어 간 워커의 기록을 덮어 「취소됨」 이나 「완료」 로 바꿔 놓는다."""
    job_id = uuid.UUID(_queue(client, member, {"recipe": "modal", "material": MATERIAL}))
    simulation = db.get(Simulation, job_id)
    assert simulation is not None
    simulation.worker_id = "me:1"
    simulation.status = "fetching"
    db.commit()

    services.execute(db, simulation, worker_id="me:1", executor=_Hijacked(job_id))

    db.expire_all()
    after = db.get(Simulation, job_id)
    assert after is not None
    assert after.worker_id == "thief:1"
    assert after.status == "fetching", "집어 간 워커의 상태를 덮었다"
