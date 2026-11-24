"""서버에서 고치는 해석 설정 — **재시작 없이**, 결과를 바꾸는 값은 **작업을 만들 때
고정**(2026-11-25).

`.env` 의 단계 설정은 앱을 다시 띄워야 들었다. 이제 서버 화면(`/server/settings`)에서 고치고,
결과를 바꾸는 값(본딩 · 선형 솔버 · 허용오차 · 스레드 · STE 메모리 상한)은 작업을 만들 때 그
작업에 적는다 — 고친 뒤에도 이미 건 작업 · 다시 돌리기는 옛 값, 새 작업은 새 값. STE 연결은
단계 시작 때 지금 값.
"""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.calculix import bonding, ste
from app.core.stages import StageContext, StageResult
from app.modules.accounts.models import User
from app.modules.audit.models import AuditEntry
from app.modules.server import runtime
from app.modules.server.models import RuntimeSetting
from app.modules.simulations import services
from app.modules.simulations.models import Simulation
from tests.api.conftest import Signed

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
}


@pytest.fixture(autouse=True)
def clean(db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """**시험 DB 는 스위트가 함께 쓴다** — 남긴 서버 설정은 뒤 시험의 작업에 고정된다."""
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    db.execute(delete(RuntimeSetting))
    db.commit()
    yield
    db.rollback()
    db.execute(delete(RuntimeSetting))
    for row in db.scalars(select(Simulation).where(Simulation.status == "queued")):
        row.status = "canceled"
    db.commit()


def _put(client: TestClient, who: Signed, key: str, value: str) -> Any:
    return client.put(
        f"/api/server/settings/{key}", json={"value": value}, headers=who.headers
    )


def _queue(client: TestClient, who: Signed, spec: dict[str, Any] | None = None) -> uuid.UUID:
    response = client.post(
        "/api/simulations",
        data={"spec": json.dumps(spec or SPEC), "workspace_slug": who.workspace},
        files={"file": ("브래킷.step", io.BytesIO(STEP), "model/step")},
        headers=who.headers,
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


class _Recorder:
    """단계마다 받은 환경을 적는다 — 자식이 볼 단계 설정."""

    name = "recorder"

    def __init__(self) -> None:
        self.env: dict[str, dict[str, str]] = {}

    def run(self, ctx: StageContext, should_cancel: Any = None) -> StageResult:
        self.env[ctx.stage] = dict(ctx.env)
        return StageResult(detail=ctx.stage)


def _env_of(db: Session, job: uuid.UUID) -> dict[str, dict[str, str]]:
    simulation = db.get(Simulation, job)
    assert simulation is not None
    recorder = _Recorder()
    services.execute(db, simulation, worker_id="me:1", executor=recorder)
    return recorder.env


def test_시스템_관리자만_보고_고친다(
    client: TestClient, admin: Signed, member: Signed
) -> None:
    listed = client.get("/api/server/settings", headers=admin.headers)
    assert listed.status_code == 200, listed.text
    rows = {row["key"]: row for row in listed.json()}
    assert set(rows) == set(runtime.BY_KEY)
    assert rows["calculix_bonding"]["value"] == "lever"
    assert rows["calculix_bonding"]["source"] == "default"
    assert rows["calculix_bonding"]["applies"] == "new_jobs"
    assert rows["ste_poll_seconds"]["applies"] == "next_stage"
    assert "ste_sso_secret" not in rows, "비밀은 화면에 두지 않는다"
    assert client.get("/api/server/settings", headers=member.headers).status_code == 403
    assert _put(client, member, "calculix_bonding", "tie").status_code == 403


def test_고치면_서버_설정이_이기고_되돌리면_환경_기본으로(
    client: TestClient, db: Session, admin: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "calculix_bonding", "shared")  # .env 에 적은 것
    before = {
        row["key"]: row
        for row in client.get("/api/server/settings", headers=admin.headers).json()
    }
    assert (before["calculix_bonding"]["value"], before["calculix_bonding"]["source"]) == (
        "shared",
        "env",
    )

    changed = _put(client, admin, "calculix_bonding", "TIE")
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert (body["value"], body["source"], body["env_value"]) == ("tie", "server", "shared")
    assert body["updated_by_name"]
    entry = db.scalars(
        select(AuditEntry)
        .where(AuditEntry.action == runtime.SETTING_UPDATED)
        .order_by(AuditEntry.created_at.desc())
    ).first()
    assert entry is not None and (entry.changes or {})["after"] == "tie"

    cleared = client.delete("/api/server/settings/calculix_bonding", headers=admin.headers)
    assert cleared.status_code == 200, cleared.text
    assert (cleared.json()["value"], cleared.json()["source"]) == ("shared", "env")


def test_틀린_값과_모르는_열쇠는_받지_않는다(client: TestClient, admin: Signed) -> None:
    wrong = _put(client, admin, "omp_num_threads", "0")
    assert wrong.status_code == 400
    assert wrong.json()["error"]["code"].endswith("SERVER-0002")
    unknown = _put(client, admin, "ste_sso_secret", "탈취")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"].endswith("SERVER-0001")


def test_틀린_env_값은_기본값을_쓰고_까닭을_보인다(
    client: TestClient, admin: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "calculix_linear_solver", "fast")
    rows = {
        row["key"]: row
        for row in client.get("/api/server/settings", headers=admin.headers).json()
    }
    row = rows["calculix_linear_solver"]
    assert (row["value"], row["source"]) == ("auto", "default")
    assert "CALCULIX_LINEAR_SOLVER" in (row["problem"] or "")


def test_결과를_바꾸는_값은_작업을_만들_때_고정한다(
    client: TestClient, db: Session, admin: Signed, member: Signed
) -> None:
    assert _put(client, admin, "calculix_bonding", "tie").status_code == 200
    assert _put(client, admin, "omp_num_threads", "4").status_code == 200
    first = _queue(client, member)

    assert _put(client, admin, "calculix_bonding", "shared").status_code == 200
    second = _queue(client, member)

    stored = db.get(Simulation, first)
    assert stored is not None
    assert stored.run_settings["calculix_bonding"] == "tie"
    assert set(stored.run_settings) == set(runtime.FROZEN)
    env = _env_of(db, first)
    assert env["modeling"][bonding.BONDING_ENV] == "tie", "고친 뒤에도 이미 건 작업은 옛 값"
    assert env["solving"]["OMP_NUM_THREADS"] == "4"
    assert _env_of(db, second)["modeling"][bonding.BONDING_ENV] == "shared", "새 작업은 새 값"

    # 다시 돌리기도 만들 때의 값으로.
    db.expire_all()
    again = db.get(Simulation, first)
    assert again is not None
    again.status = "canceled"
    db.commit()
    user = db.scalars(select(Simulation.requested_by_id).where(Simulation.id == first)).one()
    owner = db.get(User, user)
    assert owner is not None
    services.retry(db, user=owner, simulation_id=first)
    assert _env_of(db, first)["modeling"][bonding.BONDING_ENV] == "tie"


def test_고정하기_전의_옛_작업은_단계_시작_때_값을_쓴다(
    client: TestClient, db: Session, admin: Signed, member: Signed
) -> None:
    job = _queue(client, member)
    old = db.get(Simulation, job)
    assert old is not None
    old.run_settings = {}
    db.commit()
    assert _put(client, admin, "calculix_bonding", "tie").status_code == 200
    assert _env_of(db, job)["modeling"][bonding.BONDING_ENV] == "tie"


def test_STE_연결은_단계_시작_때_지금_값이다(
    client: TestClient,
    db: Session,
    admin: Signed,
    member: Signed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "ste_sso_secret", "ste-secret")
    assert (
        _put(client, admin, "ste_base_url", "https://ste-old.example/ste").status_code == 200
    )
    job = _queue(client, member, {**SPEC, "solve_on": "ste"})
    assert (
        _put(client, admin, "ste_base_url", "https://ste-new.example/ste/").status_code == 200
    )
    assert _put(client, admin, "ste_poll_seconds", "30").status_code == 200
    env = _env_of(db, job)
    assert env["solving"][ste.BASE_URL_ENV] == "https://ste-new.example/ste"
    assert env["solving"][ste.POLL_ENV] == "30"
    assert ste.BASE_URL_ENV not in env["modeling"]


def test_서버_설정으로_STE_주소를_주면_STE_작업을_받는다(
    client: TestClient, admin: Signed, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "ste_sso_secret", "ste-secret")
    response = client.post(
        "/api/simulations",
        data={
            "spec": json.dumps({**SPEC, "solve_on": "ste"}),
            "workspace_slug": member.workspace,
        },
        files={"file": ("브래킷.step", io.BytesIO(STEP), "model/step")},
        headers=member.headers,
    )
    assert response.status_code == 400, "주소가 없으면 STE 를 못 고른다"
    assert _put(client, admin, "ste_base_url", "https://hwax.example/ste").status_code == 200
    _queue(client, member, {**SPEC, "solve_on": "ste"})
