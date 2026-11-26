"""취소를 STE 까지(요청서 E-4) — **워커가 언제 STE 잡을 멈추나**.

자식이 STE 에 잡을 낸 채 멈추는 길은 셋이다: 사람이 취소 · 단계 시간 초과 · 워커가 죽음. 앞의
둘은 `execute` 가 단계를 적기 전에, 마지막은 `requeue_stale` 이 되살리기 전에 닫는다. 닫기
자체(가짜 STE 가 정말 CANCELLED 가 되나)는 `tests/unit/test_ste_cancel.py` 가 본다.
"""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.calculix import ste
from app.core.stages import StageCanceled, StageContext, StageFailure, StageResult
from app.modules.audit.models import AuditEntry
from app.modules.simulations import services
from app.modules.simulations.models import Simulation
from tests.api.conftest import Signed
from tests.fake_ste import CLIENT, FakeSte, Outcome

STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
SPEC = {
    "recipe": "modal",
    "material": {
        "name": "SS400",
        "youngs_modulus_gpa": 200,
        "poisson_ratio": 0.3,
        "density_kg_m3": 7850,
    },
    "material_from": "spec",
    "mesh": {"element_size_mm": 5},
    "solve_on": "ste",
}


def _done(folder: Path, params: object) -> Outcome:
    return Outcome("COMPLETED", 0)


@pytest.fixture(autouse=True)
def fake(db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FakeSte]:
    made = FakeSte(secrets_by_client={CLIENT: "ste-secret"}, runner=_done, hold=True)
    monkeypatch.setattr(ste, "TRANSPORT", httpx.MockTransport(made.handle))
    settings = get_settings()
    monkeypatch.setattr(settings, "jobs_inline", False)
    monkeypatch.setattr(settings, "ste_base_url", "http://ste.test/ste")
    monkeypatch.setattr(settings, "ste_sso_secret", "ste-secret")
    monkeypatch.setattr(settings, "ste_token_dir", str(tmp_path / "tokens"))
    yield made
    db.rollback()
    for row in db.scalars(select(Simulation).where(Simulation.status == "queued")):
        row.status = "canceled"
    db.commit()


def _queue(client: TestClient, db: Session, who: Signed) -> Simulation:
    response = client.post(
        "/api/simulations",
        data={"spec": json.dumps(SPEC), "workspace_slug": who.workspace},
        files={"file": ("브래킷.step", io.BytesIO(STEP), "model/step")},
        headers=who.headers,
    )
    assert response.status_code == 201, response.text
    row = db.get(Simulation, uuid.UUID(response.json()["id"]))
    assert row is not None
    return row


def _submit_as(email: str, workdir: Path) -> str:
    """자식이 하는 일 — 그 사람 명의로 STE 에 내고 장부에 「냄」 을 적는다."""
    config = ste.SteConfig(
        base_url="http://ste.test/ste",
        secret="ste-secret",
        client=CLIENT,
        token_dir=Path(get_settings().ste_token_dir),
    )
    http = ste.http_client()
    session = ste.SteSession(config, email, http=http, tokens=ste.Tokens(config, http))
    upload = session.accepted(session.call("POST", ste.ENDPOINTS["uploads"], what="u"), "u")
    path = ste.ENDPOINTS["upload_file"].format(upload=upload["id"], name="model.inp")
    session.accepted(session.call("PUT", path, what="p", content=b"*NODE\n"), "p")
    form = ste._submit_form("calculix", upload["id"], {"deck": "model"})
    made = session.call("POST", ste.ENDPOINTS["jobs"], what="j", data=form)
    job = str(session.accepted(made, "j")["id"])
    session.call("GET", ste.ENDPOINTS["job"].format(job=job), what="s")  # → RUNNING
    http.close()
    ste.append_ledger(workdir, {"event": "submit", "ste_job_id": job, "at": 0})
    return job


class _Stopped:
    """솔브 단계에서 STE 에 잡을 낸 뒤 멈춘 자식 — `stop` 이 그 까닭이다."""

    name = "ste-like"

    def __init__(self, stop: Exception) -> None:
        self.stop = stop
        self.job: str | None = None

    def run(self, ctx: StageContext, should_cancel: Any = None) -> StageResult:
        if ctx.stage == "solving":
            assert ctx.requester_email
            self.job = _submit_as(ctx.requester_email, ctx.workdir)
            raise self.stop
        return StageResult(detail=ctx.stage)


def _audits(db: Session, simulation: Simulation, action: str) -> list[AuditEntry]:
    return list(
        db.scalars(
            select(AuditEntry).where(
                AuditEntry.action == action, AuditEntry.target_id == simulation.id
            )
        )
    )


def test_사람이_취소하면_STE_잡을_멈추고_본_뒤에_취소로_둔다(
    client: TestClient, db: Session, member: Signed, fake: FakeSte
) -> None:
    simulation = _queue(client, db, member)
    solver = _Stopped(StageCanceled("solving 단계에서 취소했습니다."))

    services.execute(db, simulation, worker_id="me:1", executor=solver)

    assert solver.job is not None
    assert fake.jobs[solver.job].state == "CANCELLED"
    db.expire_all()
    after = db.get(Simulation, simulation.id)
    assert after is not None and after.status == "canceled"
    solving = next(one for one in after.stages if one["name"] == "solving")
    assert solving["status"] == "canceled"
    assert "CANCELLED 확인" in solving["detail"]
    [job] = solving["ste_jobs"]
    assert (job["ste_job_id"], job["ste_state"]) == (solver.job, "CANCELLED")
    [audit] = _audits(db, simulation, services.STE_CANCEL)
    assert audit.actor_label != "시스템", "건 사람 명의로 남는다"
    assert (audit.changes or {})["ste_state"] == "CANCELLED"


def test_단계_시간_초과로_멈춘_자식의_STE_잡도_멈춘다(
    client: TestClient, db: Session, member: Signed, fake: FakeSte
) -> None:
    simulation = _queue(client, db, member)
    solver = _Stopped(StageFailure("timeout", "solving 단계가 240분 안에 끝나지 않았습니다."))

    services.execute(db, simulation, worker_id="me:1", executor=solver)

    assert solver.job is not None and fake.jobs[solver.job].state == "CANCELLED"
    db.expire_all()
    after = db.get(Simulation, simulation.id)
    assert after is not None and after.status == "failed" and after.error_code == "timeout"
    solving = next(one for one in after.stages if one["name"] == "solving")
    assert solving["ste_jobs"][0]["ste_state"] == "CANCELLED"


def test_STE_설정이_지워졌으면_못_멈춘_까닭을_남긴다(
    client: TestClient,
    db: Session,
    member: Signed,
    fake: FakeSte,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simulation = _queue(client, db, member)

    class _Gone(_Stopped):
        def run(self, ctx: StageContext, should_cancel: Any = None) -> StageResult:
            if ctx.stage == "solving":
                assert ctx.requester_email
                self.job = _submit_as(ctx.requester_email, ctx.workdir)
                monkeypatch.setattr(get_settings(), "ste_sso_secret", "")  # 그사이 지웠다
                raise self.stop
            return StageResult(detail=ctx.stage)

    solver = _Gone(StageCanceled("취소"))
    services.execute(db, simulation, worker_id="me:1", executor=solver)

    assert solver.job is not None and fake.jobs[solver.job].state == "RUNNING"
    db.expire_all()
    after = db.get(Simulation, simulation.id)
    assert after is not None
    solving = next(one for one in after.stages if one["name"] == "solving")
    assert "멈춘 것을 못 봤습니다" in solving["detail"]
    assert "STE 설정이 없어" in solving["ste_jobs"][0]["cancel_error"]


def test_끝까지_푼_STE_작업은_아무것도_취소하지_않는다(
    client: TestClient, db: Session, member: Signed, fake: FakeSte
) -> None:
    simulation = _queue(client, db, member)

    class _Finished:
        name = "ste-like"

        def run(self, ctx: StageContext, should_cancel: Any = None) -> StageResult:
            if ctx.stage == "solving":
                ste.append_ledger(
                    ctx.workdir,
                    {"event": "end", "ste_job_id": "j9999", "ste_state": "COMPLETED"},
                )
            return StageResult(detail=ctx.stage)

    services.execute(db, simulation, worker_id="me:1", executor=_Finished())

    assert not any(path.endswith("/cancel") for _, path, _ in fake.requests)
    assert _audits(db, simulation, services.STE_CANCEL) == []


def test_죽은_워커가_남긴_STE_잡은_되살리기_전에_멈춘다(
    client: TestClient, db: Session, member: Signed, fake: FakeSte
) -> None:
    simulation = _queue(client, db, member)
    simulation.work_dir = services.relative_to_root(services._new_work_dir(simulation.id))
    workdir = services.work_root() / simulation.work_dir
    job = _submit_as(member.email, workdir)
    simulation.status = "solving"
    simulation.worker_id = "gone:1"  # 신호를 남긴 적 없는 워커 — 단계가 오래 멈춘 것으로 본다
    simulation.attempts = 1
    simulation.heartbeat_at = services._now() - services.STALE_AFTER - timedelta(minutes=1)
    db.commit()

    services.requeue_stale(db)

    assert fake.jobs[job].state == "CANCELLED"
    db.expire_all()
    after = db.get(Simulation, simulation.id)
    assert after is not None and after.status == "queued", "되살리기는 그대로"
    assert ste.open_jobs(workdir) == []
    assert len(_audits(db, simulation, services.STE_CANCEL)) == 1
