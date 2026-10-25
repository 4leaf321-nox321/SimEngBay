"""끝난 DOE 를 **모드 수만 바꿔** 다시 건다(2026-10-25).

6개만 구한 DOE 에서 치수에 따라 모드가 위로 밀려나 비교가 끊겼다. 같은 폴더는 한 번만
가져오므로 전에는 DOE 를 지우고 다시 가져와야 했다 — 결과를 지워야 고칠 수 있었다. 이제 점마다
마지막 작업의 입력을 그대로 옮겨 새 작업을 만들고, 옛 작업은 기록으로 남긴다.
"""

from __future__ import annotations

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
from app.modules.simulations.models import Simulation
from app.modules.workspaces.models import Workspace
from tests.api.conftest import Signed, _login, _make_user

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


def _import(
    client: TestClient,
    who: Signed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spec: dict[str, Any] = MODAL,
) -> str:
    """같은 픽스처를 시험마다 **새 스터디**로 — 다른 시험이 이미 가져온 점과 섞이지 않게."""
    folder = tmp_path / DOE_FOLDER.name
    shutil.copytree(DOE_FOLDER, folder)
    study = json.loads((folder / "study.json").read_text(encoding="utf-8"))
    study["id"] = uuid.uuid4().hex
    (folder / "study.json").write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "doe_roots", str(tmp_path))
    request = {"path": str(folder), "spec": spec, "workspace_slug": who.workspace}
    made = client.post("/api/simulations/doe/import", json=request, headers=who.headers)
    assert made.status_code == 201, made.text
    return str(made.json()["study_id"])


def _rerun(study_id: str) -> str:
    return f"/api/simulations/studies/{study_id}/rerun"


def _first(client: TestClient, db: Session, who: Signed, study_id: str) -> Simulation:
    found = db.get(Simulation, uuid.UUID(_points(client, who, study_id)[0]["simulation_id"]))
    assert found is not None
    return found


def _points(client: TestClient, who: Signed, study_id: str) -> list[dict[str, Any]]:
    got = client.get(f"/api/simulations/studies/{study_id}", headers=who.headers)
    assert got.status_code == 200, got.text
    points: list[dict[str, Any]] = got.json()["points"]
    return points


def test_모드_수만_바꿔_다시_걸면_점마다_새_작업이_되고_옛_작업은_기록으로_남는다(
    client: TestClient,
    db: Session,
    member: Signed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    study_id = _import(client, member, tmp_path, monkeypatch)
    before = _points(client, member, study_id)
    old_ids = [one["simulation_id"] for one in before]
    assert all(one["status"] == "done" for one in before)
    # 사람이 나눠 둔 정리 폴더는 그대로 따라간다.
    moved = client.post(
        "/api/simulations/items/move",
        json={"ids": [f"doe:{study_id}"], "folder": "보관/외팔보"},
        headers=member.headers,
    )
    assert moved.status_code == 200, moved.text

    made = client.post(_rerun(study_id), json={"modes": 10}, headers=member.headers)
    assert made.status_code == 201, made.text
    body = made.json()
    assert len(body["created"]) == 3 and body["skipped"] == []
    assert body["notes"] == []  # 10 > 비교하는 6 — 알릴 것이 없다

    # **스터디는 점마다 마지막 작업으로 견준다** — 세 점이 그대로 셋, 새 작업으로.
    after = _points(client, member, study_id)
    assert [one["number"] for one in after] == [one["number"] for one in before]
    assert {one["simulation_id"] for one in after} == set(body["created"])
    for old_id, new_id in zip(old_ids, (one["simulation_id"] for one in after), strict=True):
        new = db.get(Simulation, uuid.UUID(new_id))
        old = db.get(Simulation, uuid.UUID(old_id))
        assert new is not None and old is not None
        db.refresh(old)
        assert new.spec["modes"] == 10
        assert new.source_meta["previous"] == [old_id]
        assert new.source_meta["rerun"] == {"modes": 10, "from_modes": 5}
        assert new.folder == "보관/외팔보"
        assert new.name == old.name
        # 옛 작업은 지우지 않는다 — 대신한 작업을 적어 기록으로 남긴다.
        assert old.deleted_at is None
        assert old.source_meta["superseded_by"] == new_id
        assert old.source_meta["rerun_to"] == 10
        assert (services.work_root() / str(old.work_dir)).is_dir()
    actions = list(db.scalars(select(AuditEntry.action).order_by(AuditEntry.seq)))
    assert "study.rerun" in actions

    # 같은 폴더를 다시 가져오는 길은 여전히 막혀 있다 — 두 벌이 돌지 않는다.
    listing = client.get("/api/simulations/studies", headers=member.headers).json()
    (row,) = [one for one in listing if one["study_id"] == study_id]
    assert row["points"] == 3

    # 비교하는 수(6) 이하로 다시 걸면 알린다 — 막지는 않는다.
    low = client.post(_rerun(study_id), json={"modes": 6}, headers=member.headers)
    assert low.status_code == 201, low.text
    assert "모드를 6개만 구합니다" in low.json()["notes"][0]


def test_같은_수_정적_도는_점_남의_DOE_는_거절한다(
    client: TestClient,
    db: Session,
    member: Signed,
    other: Signed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    study_id = _import(client, member, tmp_path, monkeypatch)
    path = _rerun(study_id)

    same = client.post(path, json={"modes": 5}, headers=member.headers)
    assert same.status_code == 400
    assert "이미 모드 5개로" in same.json()["error"]["message"]

    # 남의 DOE — 게시 전에는 보이지도 않고(404), 게시돼 보여도 바꾸지 못한다(403).
    assert client.post(path, json={"modes": 10}, headers=other.headers).status_code == 404
    published = client.post(
        f"/api/simulations/studies/{study_id}/publish", headers=member.headers
    )
    assert published.status_code == 200, published.text
    assert client.post(path, json={"modes": 10}, headers=other.headers).status_code == 403
    assert client.post(path, json={"modes": 0}, headers=member.headers).status_code == 422

    # 도는 점이 있으면 — 옛 결과와 새 결과가 섞인다.
    first = _first(client, db, member, study_id)
    first.status = "solving"
    db.commit()
    busy = client.post(path, json={"modes": 10}, headers=member.headers)
    assert busy.status_code == 409
    assert "도는 설계점" in busy.json()["error"]["message"]


def test_입력_파일이_없는_점은_걸지_않고_까닭을_돌려준다(
    client: TestClient,
    db: Session,
    member: Signed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    study_id = _import(client, member, tmp_path, monkeypatch)
    first = _first(client, db, member, study_id)
    (services.work_root() / str(first.work_dir) / services.INPUT_NAME).unlink()

    made = client.post(_rerun(study_id), json={"modes": 10}, headers=member.headers)
    assert made.status_code == 201, made.text
    body = made.json()
    assert len(body["created"]) == 2
    (skipped,) = body["skipped"]
    assert skipped["number"] == 1
    assert "입력 형상 파일이 없습니다" in skipped["skip_reason"]
    db.refresh(first)
    assert "superseded_by" not in first.source_meta  # 대신한 작업이 없다


def test_정적_DOE_에는_모드_수가_없다(
    client: TestClient, member: Signed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    static = {key: value for key, value in MODAL.items() if key != "modes"}
    static["recipe"] = "static"
    # 정적 픽스처가 아니어도 된다 — 모델링 전에 거절하므로 가져오기만 되면 된다.
    study_id = _import(client, member, tmp_path, monkeypatch, spec=static)
    refused = client.post(_rerun(study_id), json={"modes": 10}, headers=member.headers)
    assert refused.status_code == 400
    assert "모달 · 조화" in refused.json()["error"]["message"]
