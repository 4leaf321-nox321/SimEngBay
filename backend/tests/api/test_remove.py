"""해석 작업 · DOE 를 **지운다**(2026-10-23).

전에는 지울 길이 없어 실패한 작업 · 시험 삼아 건 DOE 가 목록과 작업 폴더에 쌓였다. 지우면
목록 · DOE 비교에서 사라지고 작업 폴더도 지운다 — 행은 `deleted_at` 으로 남는다(감사 기록 ·
밖의 보고서가 그 id 를 가리킨다). 도는 작업은 먼저 멈춘다.
"""

from __future__ import annotations

import io
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modules.audit.models import AuditEntry
from app.modules.simulations import services
from app.modules.simulations.models import Simulation, SimulationMeasurement
from app.modules.workspaces.models import Workspace
from tests.api.conftest import Signed, _login, _make_user

STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
MODAL: dict[str, Any] = {
    "recipe": "modal",
    "material": {
        "name": "SS400",
        "youngs_modulus_gpa": 200,
        "poisson_ratio": 0.3,
        "density_kg_m3": 7850,
    },
    "modes": 5,
    "mesh": {"element_size_mm": 5},
}
MEASURED = "종류,주파수\n공진,300\n".encode()
DOE_FOLDER = (
    Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "브래킷_두께훑기-3f9a2177"
)


@pytest.fixture(autouse=True)
def inline_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", True)


@pytest.fixture
def other(client: TestClient, db: Session, workspace: Workspace) -> Signed:
    user = _make_user(db, workspace, label="other", is_system_admin=False, role="member")
    return Signed(email=user.email, token=_login(client, user.email), workspace=workspace.slug)


def _create(client: TestClient, who: Signed) -> dict[str, Any]:
    response = client.post(
        "/api/simulations",
        data={"spec": json.dumps(MODAL), "workspace_slug": who.workspace},
        files={"file": ("브래킷.step", io.BytesIO(STEP), "model/step")},
        headers=who.headers,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _folder(db: Session, job_id: str) -> Path:
    row = db.get(Simulation, uuid.UUID(job_id))
    assert row is not None and row.work_dir is not None
    return services.work_root() / row.work_dir


def _actions(db: Session, target: uuid.UUID | None = None) -> list[str]:
    query = select(AuditEntry.action).order_by(AuditEntry.seq)
    if target is not None:
        query = query.where(AuditEntry.target_id == target)
    return list(db.scalars(query))


def _import(
    client: TestClient, who: Signed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, dict[str, Any]]:
    folder = tmp_path / DOE_FOLDER.name
    shutil.copytree(DOE_FOLDER, folder)
    study = json.loads((folder / "study.json").read_text(encoding="utf-8"))
    study["id"] = uuid.uuid4().hex
    (folder / "study.json").write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "doe_roots", str(tmp_path))
    request = {"path": str(folder), "spec": MODAL, "workspace_slug": who.workspace}
    made = client.post("/api/simulations/doe/import", json=request, headers=who.headers)
    assert made.status_code == 201, made.text
    return str(made.json()["study_id"]), request


def test_지우면_목록에서_사라지고_작업_폴더와_실측도_내린다(
    client: TestClient, db: Session, member: Signed
) -> None:
    job = _create(client, member)
    path = f"/api/simulations/{job['id']}"
    measured = client.post(
        f"{path}/measurements",
        files={"file": ("실측.csv", io.BytesIO(MEASURED), "text/csv")},
        headers=member.headers,
    )
    assert measured.status_code == 201, measured.text
    folder = _folder(db, job["id"])
    assert folder.is_dir()

    removed = client.delete(path, headers=member.headers)
    assert removed.status_code == 200, removed.text
    assert removed.json()["jobs"] == 1
    assert removed.json()["bytes_freed"] > 0
    assert not folder.exists()
    assert client.get(path, headers=member.headers).status_code == 404
    listed = client.get("/api/simulations", params={"limit": "200"}, headers=member.headers)
    assert job["id"] not in {one["id"] for one in listed.json()["items"]}

    # **행은 남긴다** — 감사 기록과 밖의 보고서가 그 id 를 가리킨다.
    row = db.get(Simulation, uuid.UUID(job["id"]))
    assert row is not None and row.deleted_at is not None
    attached = db.get(SimulationMeasurement, uuid.UUID(measured.json()["id"]))
    assert attached is not None and attached.deleted_at is not None
    assert _actions(db, uuid.UUID(job["id"])) == ["simulation.deleted"]
    # 두 번 지우면 없는 것이다.
    assert client.delete(path, headers=member.headers).status_code == 404


def test_남의_작업은_게시돼도_못_지우고_시스템_관리자는_지운다(
    client: TestClient, member: Signed, other: Signed, admin: Signed
) -> None:
    job = _create(client, member)
    path = f"/api/simulations/{job['id']}"
    # 안 보이면 없는 것과 같게 답한다.
    assert client.delete(path, headers=other.headers).status_code == 404
    assert client.post(f"{path}/publish", headers=member.headers).status_code == 200
    assert client.delete(path, headers=other.headers).status_code == 403
    assert client.delete(path, headers=admin.headers).status_code == 200
    # 게시된 것도 남에게서 거둔다.
    assert client.get(path, headers=other.headers).status_code == 404


def test_메시_수렴_수준도_함께_지운다(client: TestClient, db: Session, member: Signed) -> None:
    job = _create(client, member)
    path = f"/api/simulations/{job['id']}"
    checked = client.post(
        f"{path}/convergence", json={"sizes_mm": [3.5]}, headers=member.headers
    )
    assert checked.status_code == 201, checked.text
    levels = [one["simulation_id"] for one in checked.json()["levels"]]
    assert len(levels) == 2

    removed = client.delete(path, headers=member.headers)
    assert removed.status_code == 200, removed.text
    assert removed.json()["jobs"] == 2
    for level in levels:
        found = client.get(f"/api/simulations/{level}", headers=member.headers)
        assert found.status_code == 404


def test_도는_작업은_지우지_않고_대기_중이면_취소로_닫고_지운다(
    client: TestClient, db: Session, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    job = _create(client, member)
    path = f"/api/simulations/{job['id']}"
    row = db.get(Simulation, uuid.UUID(job["id"]))
    assert row is not None and row.status == "queued"

    row.status = "solving"
    db.commit()
    refused = client.delete(path, headers=member.headers)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"].endswith("SIMULATIONS-0035")
    assert client.get(path, headers=member.headers).status_code == 200

    row.status = "queued"
    db.commit()
    assert client.delete(path, headers=member.headers).status_code == 200
    db.refresh(row)
    assert (row.status, row.deleted_at is not None) == ("canceled", True)
    # 워커가 집지 않는다.
    assert services.claim_next(db, "시험:1") is None


def test_DOE_를_지우면_내_점_전부와_스터디_실측을_내리고_다시_가져올_수_있다(
    client: TestClient,
    db: Session,
    member: Signed,
    other: Signed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    study_id, request = _import(client, member, tmp_path, monkeypatch)
    base = f"/api/simulations/studies/{study_id}"
    points = client.get(base, headers=member.headers).json()["points"]
    assert len(points) == 3
    folders = [_folder(db, one["simulation_id"]) for one in points]
    measured = client.post(
        f"{base}/measurements",
        files={"file": ("실측.csv", io.BytesIO(MEASURED), "text/csv")},
        headers=member.headers,
    )
    assert measured.status_code == 201, measured.text

    # 게시돼 보여도 남은 못 지운다.
    assert client.delete(base, headers=other.headers).status_code == 404
    assert client.post(f"{base}/publish", headers=member.headers).status_code == 200
    assert client.delete(base, headers=other.headers).status_code == 403

    removed = client.delete(base, headers=member.headers)
    assert removed.status_code == 200, removed.text
    assert (removed.json()["points"], removed.json()["jobs"]) == (3, 3)
    assert not any(folder.exists() for folder in folders)
    assert client.get(base, headers=member.headers).status_code == 404
    listed = client.get("/api/simulations/studies", headers=member.headers).json()
    assert study_id not in {one["study_id"] for one in listed}
    kept = db.get(SimulationMeasurement, uuid.UUID(measured.json()["id"]))
    assert kept is not None
    db.refresh(kept)
    assert kept.deleted_at is not None
    assert "study.deleted" in _actions(db)

    # **지운 점은 다시 가져올 수 있다** — 막혀 있으면 지운 뜻이 없다.
    again = client.post("/api/simulations/doe/import", json=request, headers=member.headers)
    assert again.status_code == 201, again.text
    assert len(again.json()["created"]) == 3
    assert client.delete(base, headers=member.headers).status_code == 200


def test_설계점_하나를_지우면_그_점의_앞선_시도도_함께(
    client: TestClient,
    db: Session,
    member: Signed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실패해 다시 가져온 점 — 새 작업만 지우면 옛 실패가 그 점 자리에 다시 올라온다."""
    study_id, request = _import(client, member, tmp_path, monkeypatch)
    base = f"/api/simulations/studies/{study_id}"
    first = client.get(base, headers=member.headers).json()["points"][0]
    old = db.get(Simulation, uuid.UUID(first["simulation_id"]))
    assert old is not None
    old.status = "failed"
    db.commit()
    again = client.post("/api/simulations/doe/import", json=request, headers=member.headers)
    assert again.status_code == 201, again.text
    assert len(again.json()["created"]) == 1
    newer = again.json()["created"][0]

    removed = client.delete(f"/api/simulations/{newer}", headers=member.headers)
    assert removed.status_code == 200, removed.text
    assert removed.json()["jobs"] == 2
    left = client.get(base, headers=member.headers).json()["points"]
    assert first["number"] not in {one["number"] for one in left}
    assert len(left) == 2
    assert client.delete(base, headers=member.headers).status_code == 200


def test_DOE_를_멈추면_끝나지_않은_점이_모두_멈추고_도는_점이_있으면_지우지_않는다(
    client: TestClient,
    db: Session,
    member: Signed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    study_id, _ = _import(client, member, tmp_path, monkeypatch)
    base = f"/api/simulations/studies/{study_id}"
    points = client.get(base, headers=member.headers).json()["points"]
    running = db.get(Simulation, uuid.UUID(points[0]["simulation_id"]))
    assert running is not None
    running.status = "solving"
    db.commit()

    refused = client.delete(base, headers=member.headers)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"].endswith("SIMULATIONS-0035")

    stopped = client.post(f"{base}/cancel", headers=member.headers)
    assert stopped.status_code == 200, stopped.text
    assert stopped.json() == {"points": 3}
    after = client.get(base, headers=member.headers).json()["points"]
    statuses = {one["status"] for one in after}
    # 대기는 곧바로 취소, 도는 점은 워커가 볼 때까지 그대로(멈춤 요청만 적힌다).
    assert statuses == {"canceled", "solving"}
    db.refresh(running)
    assert running.cancel_requested_at is not None

    # 워커가 멈춘 뒤에는 지운다.
    running.status = "canceled"
    db.commit()
    assert client.delete(base, headers=member.headers).status_code == 200
