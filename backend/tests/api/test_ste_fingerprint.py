"""ccx 지문 확인(요청서 2026-11-24 E-5) — **STE 의 ccx 가 이 서버의 ccx 와 다른 빌드면 STE 를
못 고른다**.

이 서버 쪽 지문은 CalculiX 를 집는 워커가 기동 때 재서 신호에 싣는다(`toolcheck.report`).
STE 쪽은 앱 정보의 메타(요청서 A-2 — 길은 짐작, `ste.ENDPOINTS["app"]`)에서, 없으면 마지막으로
끝난 STE 잡이 알려 준 것에서. 앱 정보는 하루 한 번 묻는다. 어느 한쪽을 모르면 막지 않는다.
"""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.calculix import ste
from app.modules.simulations import services
from app.modules.simulations.models import Simulation, SimulationWorker
from tests.api.conftest import Signed
from tests.fake_ste import CLIENT, FakeSte

MINE = "6adaabf5bf0382fc2bfd692b984320ed375dba777f7dc8297562f818043faa1b"
OTHER = "0" * 63 + "1"
WORKER = "fingerprint-worker:1"
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


def _forget(db: Session) -> None:
    services._probes.clear()
    services._fingerprints.clear()
    db.rollback()
    for row in db.scalars(select(Simulation).where(Simulation.status == "queued")):
        row.status = "canceled"
    worker = db.get(SimulationWorker, WORKER)
    if worker is not None:
        worker.state = "stopped"
    db.commit()


@pytest.fixture(autouse=True)
def fake(db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FakeSte]:
    made = FakeSte(secrets_by_client={CLIENT: "ste-secret"})
    monkeypatch.setattr(ste, "TRANSPORT", httpx.MockTransport(made.handle))
    settings = get_settings()
    monkeypatch.setattr(settings, "jobs_inline", False)
    monkeypatch.setattr(settings, "ste_base_url", "http://ste.test/ste")
    monkeypatch.setattr(settings, "ste_sso_secret", "ste-secret")
    monkeypatch.setattr(settings, "ste_token_dir", str(tmp_path / "tokens"))
    _forget(db)
    yield made
    _forget(db)


def _worker(db: Session, sha: str | None = MINE) -> None:
    tools: dict[str, Any] = {"gmsh": "/usr/bin/gmsh", "ccx": "/usr/bin/ccx", "ccx_sha256": sha}
    services.beat(db, WORKER, state="idle", solvers=["calculix"], tools=tools)
    row = db.get(SimulationWorker, WORKER)
    assert row is not None
    row.tools = tools  # 처음 한 번만 적는다 — 시험마다 바꾼다
    row.state = "idle"
    db.commit()


def _ste(client: TestClient, who: Signed) -> dict[str, Any]:
    response = client.get("/api/simulations/solve-places", headers=who.headers)
    assert response.status_code == 200, response.text
    return next(dict(one) for one in response.json() if one["place"] == "ste")


def _create(client: TestClient, who: Signed, *, on_ste: bool) -> Any:
    spec = {**SPEC, **({"solve_on": "ste"} if on_ste else {})}
    return client.post(
        "/api/simulations",
        data={"spec": json.dumps(spec), "workspace_slug": who.workspace},
        files={"file": ("브래킷.step", io.BytesIO(STEP), "model/step")},
        headers=who.headers,
    )


def test_같은_빌드면_고를_수_있고_그렇다고_적는다(
    client: TestClient, db: Session, member: Signed, fake: FakeSte
) -> None:
    _worker(db)
    fake.app_info = {"meta": {"ccx_sha256": MINE}}
    found = _ste(client, member)
    assert found["available"] is True
    assert "같습니다(6adaabf5bf03…)" in found["note"]
    assert _create(client, member, on_ste=True).status_code == 201


def test_다른_빌드면_STE_를_못_고르고_까닭을_보인다(
    client: TestClient, db: Session, member: Signed, fake: FakeSte
) -> None:
    _worker(db)
    fake.app_info = {"ccx_sha256": OTHER}  # 맨 위에 실어도 읽는다
    found = _ste(client, member)
    assert found["available"] is False
    assert "다른 빌드입니다" in found["reason"] and "A-1" in found["reason"]

    refused = _create(client, member, on_ste=True)
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"].endswith("SIMULATIONS-0044")
    assert _create(client, member, on_ste=False).status_code == 201, "이 서버는 그대로"


def test_다른_빌드면_STE_로_옮겨_다시_걸지_못한다(
    client: TestClient, db: Session, member: Signed, fake: FakeSte
) -> None:
    _worker(db)
    made = _create(client, member, on_ste=False)
    assert made.status_code == 201, made.text
    row = db.get(Simulation, uuid.UUID(made.json()["id"]))
    assert row is not None
    row.status = "failed"
    row.spec = {**row.spec, "solver": "calculix"}
    db.commit()
    fake.app_info = {"metadata": {"ccx_sha256": OTHER}}

    moved = client.post(
        f"/api/simulations/{row.id}/retry", json={"solve_on": "ste"}, headers=member.headers
    )
    assert moved.status_code == 400, moved.text
    assert moved.json()["error"]["code"].endswith("SIMULATIONS-0044")


def test_앱_정보에_없으면_마지막_STE_잡의_지문으로_견준다(
    client: TestClient, db: Session, member: Signed, fake: FakeSte
) -> None:
    _worker(db)
    assert fake.app_info is None
    unknown = _ste(client, member)
    assert unknown["available"] is True and "아직 모릅니다" in unknown["note"]

    made = _create(client, member, on_ste=True)
    assert made.status_code == 201, made.text
    row = db.get(Simulation, uuid.UUID(made.json()["id"]))
    assert row is not None
    row.status = "done"
    row.finished_at = services._now()
    row.stages = [
        {**one, "ste_jobs": [{"ste_job_id": "j0001", "ccx_sha256": OTHER.upper()}]}
        if one["name"] == "solving"
        else one
        for one in row.stages
    ]
    db.commit()
    services._probes.clear()

    learned = _ste(client, member)
    assert learned["available"] is False and "다른 빌드" in learned["reason"]
    row.stages = [{**one, "ste_jobs": []} for one in row.stages]  # 뒤 시험에 남기지 않는다
    db.commit()


def test_이_서버_쪽을_모르면_막지_않는다(
    client: TestClient, db: Session, member: Signed, fake: FakeSte
) -> None:
    _worker(db, sha=None)
    fake.app_info = {"meta": {"ccx_sha256": OTHER}}
    found = _ste(client, member)
    assert found["available"] is True
    assert "이 서버 워커 쪽을 모릅니다" in found["note"]


def test_앱_정보는_하루_한_번_묻는다(
    client: TestClient,
    db: Session,
    member: Signed,
    fake: FakeSte,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _worker(db)
    fake.app_info = {"meta": {"ccx_sha256": MINE}}

    def asked() -> int:
        return sum(1 for _, path, _ in fake.requests if "/api/apps/" in path)

    assert _ste(client, member)["available"] is True
    fake.app_info = {"meta": {"ccx_sha256": OTHER}}  # STE 앱이 바뀌었다
    services._probes.clear()
    assert _ste(client, member)["available"] is True, "하루 동안은 앞의 답"
    assert asked() == 1

    monkeypatch.setattr(services, "FINGERPRINT_SECONDS", 0.0)  # 하루가 지났다
    services._probes.clear()
    assert _ste(client, member)["available"] is False
    assert asked() == 2
