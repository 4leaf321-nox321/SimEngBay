"""STE 동시 제출 한도(요청서 2026-11-24 E-6) — **넘는 STE 작업은 이 서버 대기열에서 기다린다**.

한도는 둘이다: 이 서버 전체(`STE_SOLVE_MAX_INFLIGHT`) · 사람마다(`…_PER_USER`). 0 이면 없다.
서버 화면 「해석 설정」 에서 고친다(재시작 없이 — 워커가 작업을 집을 때 읽는다). 찬 STE 작업은
건너뛰고 **다른 작업은 집는다** — 한도가 이 서버의 줄을 막으면 안 된다.
"""

from __future__ import annotations

import io
import json
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.modules.server import runtime
from app.modules.simulations import services
from app.modules.simulations.models import RUNNING_STATUSES, Simulation
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


def _quiet(db: Session) -> None:
    """시험 DB 는 스위트가 함께 쓴다 — 대기 · 도는 작업이 남아 있으면 셈과 집기가 갈린다."""
    db.rollback()
    for row in db.scalars(
        select(Simulation).where(Simulation.status.in_(("queued", *RUNNING_STATUSES)))
    ):
        row.status = "canceled"
    db.commit()


@pytest.fixture(autouse=True)
def clean(db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    settings = get_settings()
    monkeypatch.setattr(settings, "jobs_inline", False)
    monkeypatch.setattr(settings, "ste_base_url", "http://ste.test/ste")
    monkeypatch.setattr(settings, "ste_sso_secret", "ste-secret")
    _quiet(db)
    yield
    _quiet(db)


def _limits(monkeypatch: pytest.MonkeyPatch, total: int = 0, per_user: int = 0) -> None:
    monkeypatch.setattr(get_settings(), "ste_solve_max_inflight", total)
    monkeypatch.setattr(get_settings(), "ste_solve_max_inflight_per_user", per_user)


def _queue(client: TestClient, who: Signed, *, on_ste: bool) -> uuid.UUID:
    spec: dict[str, Any] = {**SPEC, **({"solve_on": "ste"} if on_ste else {})}
    response = client.post(
        "/api/simulations",
        data={"spec": json.dumps(spec), "workspace_slug": who.workspace},
        files={"file": ("브래킷.step", io.BytesIO(STEP), "model/step")},
        headers=who.headers,
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


def _running(db: Session, job: uuid.UUID) -> None:
    row = db.get(Simulation, job)
    assert row is not None
    row.status = "solving"
    row.worker_id = "elsewhere:1"
    row.started_at = row.heartbeat_at = services._now()
    db.commit()


def _picked(db: Session) -> uuid.UUID | None:
    found = services.claim_next(db, "me:1", solvers=("calculix",))
    return found.id if found else None


def _queue_of(client: TestClient, who: Signed, job: uuid.UUID) -> dict[str, Any]:
    response = client.get(f"/api/simulations/{job}", headers=who.headers)
    assert response.status_code == 200, response.text
    queue = response.json()["queue"]
    assert queue is not None
    return dict(queue)


def test_한도가_없으면_STE_작업도_먼저_건_순서로_집는다(
    client: TestClient, db: Session, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    _limits(monkeypatch)
    first = _queue(client, member, on_ste=True)
    _running(db, _queue(client, member, on_ste=True))
    assert _picked(db) == first
    assert services.ste_limits(db) == (0, 0)


def test_전체_한도가_차면_STE_작업은_건너뛰고_이_서버_작업은_집는다(
    client: TestClient,
    db: Session,
    member: Signed,
    admin: Signed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _limits(monkeypatch, total=1)
    _running(db, _queue(client, admin, on_ste=True))
    waiting = _queue(client, member, on_ste=True)
    local = _queue(client, member, on_ste=False)

    held = _queue_of(client, member, waiting)["held"]
    assert "이 서버 전체 1개" in held
    assert _queue_of(client, member, local)["held"] is None, "이 서버 작업은 한도와 상관없다"

    assert _picked(db) == local, "먼저 건 STE 작업을 건너뛴다"
    assert _picked(db) is None, "찬 동안은 STE 작업을 안 집는다"


def test_도는_STE_작업이_끝나면_기다리던_것을_집는다(
    client: TestClient, db: Session, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    _limits(monkeypatch, total=1)
    busy = _queue(client, member, on_ste=True)
    _running(db, busy)
    waiting = _queue(client, member, on_ste=True)
    assert _picked(db) is None

    row = db.get(Simulation, busy)
    assert row is not None
    row.status = "done"
    db.commit()

    assert _queue_of(client, member, waiting)["held"] is None
    assert _picked(db) == waiting


def test_사람별_한도는_그_사람의_STE_작업만_세운다(
    client: TestClient,
    db: Session,
    member: Signed,
    admin: Signed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _limits(monkeypatch, per_user=1)
    _running(db, _queue(client, member, on_ste=True))
    mine = _queue(client, member, on_ste=True)
    theirs = _queue(client, admin, on_ste=True)

    assert "이 사람의 STE 동시 작업 한도(1개)" in _queue_of(client, member, mine)["held"]
    assert _queue_of(client, admin, theirs)["held"] is None
    assert _picked(db) == theirs, "한 사람의 DOE 가 남의 STE 작업을 막지 않는다"
    assert _picked(db) is None


def test_한도는_서버_화면에서_고치고_자식에는_안_간다(
    client: TestClient, db: Session, admin: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    _limits(monkeypatch)
    saved = client.put(
        "/api/server/settings/ste_solve_max_inflight",
        json={"value": "8"},
        headers=admin.headers,
    )
    try:
        assert saved.status_code == 200, saved.text
        assert services.ste_limits(db) == (8, 0)
        assert runtime.env_pairs({"ste_solve_max_inflight": "8"}) == (), "워커가 읽는 값"
        bad = client.put(
            "/api/server/settings/ste_solve_max_inflight_per_user",
            json={"value": "-1"},
            headers=admin.headers,
        )
        assert bad.status_code == 400
    finally:
        client.delete("/api/server/settings/ste_solve_max_inflight", headers=admin.headers)
    assert services.ste_limits(db) == (0, 0)


def test_두_워커가_같은_빈자리를_함께_보지_않는다(
    client: TestClient, db: Session, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """셈과 집기 사이에 다른 워커가 끼면 한도를 넘는다 — 집기를 한 줄로 세운다."""
    _limits(monkeypatch, total=1)
    first = _queue(client, member, on_ste=True)
    second = _queue(client, member, on_ste=True)

    holder = SessionLocal()
    holder.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": services.STE_CLAIM_LOCK}
    )
    found: list[uuid.UUID | None] = []

    def other_worker() -> None:
        session = SessionLocal()
        try:
            picked = services.claim_next(session, "other:1", solvers=("calculix",))
            found.append(picked.id if picked else None)
        finally:
            session.close()

    thread = threading.Thread(target=other_worker)
    thread.start()
    time.sleep(0.5)
    assert not found, "앞 워커가 집기를 마칠 때까지 기다린다"
    # 앞 워커가 첫 STE 작업을 집어 커밋한다 — 잠금이 풀린다.
    holder.execute(
        text("UPDATE simulations SET status = 'fetching', worker_id = 'me:1' WHERE id = :id"),
        {"id": first},
    )
    holder.commit()
    holder.close()
    thread.join(timeout=10)

    assert found == [None], "한도가 찼으니 두 번째 STE 작업을 집지 않는다"
    row = db.get(Simulation, second)
    assert row is not None
    db.refresh(row)
    assert row.status == "queued"
