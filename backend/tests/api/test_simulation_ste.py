"""STE 에서 풀도록 건 작업 — **워커가 건 사람을 단계에 넘기고, 낸 잡을 기록 · 감사로 옮기나**.

솔브 단계 자체(가짜 STE)는 `tests/unit/test_calculix_ste.py` 가 본다. 여기서는 그 바깥 —
작업 만들기의 거절, `execute` 가 `requested_by` 의 이메일을 단계에 싣는 것, 자식이 작업 폴더
장부(`.ste-jobs.jsonl`)에 적은 잡이 `stages[solving].ste_jobs` 와 감사 `ste.submit` 으로 가는
것.
"""

from __future__ import annotations

import io
import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.calculix import ste
from app.core.stages import StageContext, StageFailure, StageResult
from app.modules.audit.models import AuditEntry
from app.modules.simulations import services
from app.modules.simulations.models import Simulation
from tests.api.conftest import Signed

STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
MATERIAL = {
    "name": "SS400",
    "youngs_modulus_gpa": 200,
    "poisson_ratio": 0.3,
    "density_kg_m3": 7850,
}
SPEC = {
    "recipe": "modal",
    "material": MATERIAL,
    "material_from": "spec",
    "mesh": {"element_size_mm": 5},
    "solve_on": "ste",
}


@pytest.fixture(autouse=True)
def queued(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", False)


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "ste_base_url", "http://ste.test/ste")
    monkeypatch.setattr(get_settings(), "ste_sso_secret", "ste-secret")


def _queue(client: TestClient, who: Signed, spec: dict[str, Any]) -> Any:
    return client.post(
        "/api/simulations",
        data={"spec": json.dumps(spec), "workspace_slug": who.workspace},
        files={"file": ("브래킷.step", io.BytesIO(STEP), "model/step")},
        headers=who.headers,
    )


def test_STE_가_설정되지_않은_서버는_STE_작업을_받지_않는다(
    client: TestClient, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "ste_sso_secret", "")
    refused = _queue(client, member, SPEC)
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"].endswith("SIMULATIONS-0041")


def test_풀_곳을_안_주면_스펙에_적지_않고_주면_적는다(
    client: TestClient, db: Session, member: Signed, configured: None
) -> None:
    local = _queue(client, member, {**SPEC, "solve_on": "local"})
    on_ste = _queue(client, member, SPEC)
    assert local.status_code == on_ste.status_code == 201, local.text + on_ste.text
    assert "solve_on" not in local.json()["spec"], "기본값이면 옛 워커도 읽게 적지 않는다"
    assert on_ste.json()["spec"]["solve_on"] == "ste"
    # 대기에 남기지 않는다 — 시험 DB 는 스위트가 함께 써서, 뒤 시험의 `claim_next` 가 집는다.
    for made in (local, on_ste):
        row = db.get(Simulation, uuid.UUID(made.json()["id"]))
        assert row is not None
        row.status = "canceled"
    db.commit()


class _Solver:
    """솔브 단계에서 **자식이 하는 일**만 흉내 낸다 — 건 사람을 받고, 장부에 잡을 적는다."""

    name = "ste-like"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.seen: dict[str, StageContext] = {}

    def run(self, ctx: StageContext, should_cancel: Any = None) -> StageResult:
        self.seen[ctx.stage] = ctx
        if ctx.stage == "solving":
            ledger = ctx.workdir / ste.LEDGER_NAME
            with ledger.open("a", encoding="utf-8") as out:
                for job in ("j0001", "j0002"):
                    out.write(json.dumps({"event": "submit", "ste_job_id": job}) + "\n")
                    out.write(
                        json.dumps(
                            {"event": "end", "ste_job_id": job, "ste_state": "COMPLETED"}
                        )
                        + "\n"
                    )
            if self.fail:
                raise StageFailure("solver_failed", "CalculiX 가 실패했습니다: *ERROR")
        return StageResult(detail=ctx.stage)


@pytest.mark.parametrize("fail", [False, True])
def test_건_사람을_단계에_넘기고_낸_잡을_기록과_감사로_옮긴다(
    client: TestClient, db: Session, member: Signed, configured: None, fail: bool
) -> None:
    created = _queue(client, member, SPEC)
    assert created.status_code == 201, created.text
    job_id = uuid.UUID(created.json()["id"])
    simulation = db.get(Simulation, job_id)
    assert simulation is not None
    solver = _Solver(fail=fail)

    services.execute(db, simulation, worker_id="me:1", executor=solver)

    assert solver.seen["solving"].requester_email == member.email
    assert solver.seen["modeling"].requester_email is None, "솔브 단계에만 싣는다"
    solving_env = dict(solver.seen["solving"].env)
    assert solving_env[ste.BASE_URL_ENV] == "http://ste.test/ste"
    assert ste.BASE_URL_ENV not in dict(solver.seen["modeling"].env), (
        "STE 연결은 솔브 단계에만"
    )
    assert dict(solver.seen["modeling"].env)["CALCULIX_BONDING"] == "lever", "고정한 기본값"
    db.expire_all()
    after = db.get(Simulation, job_id)
    assert after is not None
    solving = next(one for one in after.stages if one["name"] == "solving")
    assert [one["ste_job_id"] for one in solving["ste_jobs"]] == ["j0001", "j0002"]
    assert solving["status"] == ("failed" if fail else "done")
    rows = db.scalars(
        select(AuditEntry).where(
            AuditEntry.action == services.STE_SUBMIT, AuditEntry.target_id == job_id
        )
    ).all()
    assert sorted(str((one.changes or {}).get("ste_job_id")) for one in rows) == [
        "j0001",
        "j0002",
    ]
    assert {one.actor_label for one in rows} != {"시스템"}, "건 사람 명의로 남는다"


def test_로컬_작업은_건_사람을_싣지_않는다(
    client: TestClient, db: Session, member: Signed, configured: None
) -> None:
    created = _queue(client, member, {**SPEC, "solve_on": "local"})
    simulation = db.get(Simulation, uuid.UUID(created.json()["id"]))
    assert simulation is not None
    solver = _Solver()
    services.execute(db, simulation, worker_id="me:1", executor=solver)
    assert solver.seen["solving"].requester_email is None


def test_STE_비밀은_비밀이_있을_때만_자식에_가고_주소는_서버_설정에서(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "ste_sso_secret", "")
    assert services.ste_env(settings) == ()
    monkeypatch.setattr(settings, "ste_sso_secret", "ste-secret")
    env = dict(services.ste_env(settings))
    assert env[ste.SECRET_ENV] == "ste-secret"
    assert env[ste.CLIENT_ENV] == settings.app_slug, "비우면 app_slug"
    assert ste.BASE_URL_ENV not in env, "주소 · 앱 · 폴링은 서버 설정(작업 단계 환경)으로 간다"
