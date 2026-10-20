"""해석 작업은 **건 사람의 것**이고, 게시해야 남이 본다(2026-10-20).

전에는 부서 단위로 열려 있어(전역 + 열린 부서 + 내 부서) 실패한 작업 · 메시만 바꿔 본 작업까지
모두에게 보였다. 이제 보는 것은 건 사람 · 시스템 관리자, 그리고 게시한 것은 누구나 — 남의 게시
결과는 읽기만 한다. CompCore 의 「내 작업 · 등록」 과 같은 꼴이다.
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
DOE_FOLDER = (
    Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "브래킷_두께훑기-3f9a2177"
)


@pytest.fixture(autouse=True)
def inline_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", True)


@pytest.fixture
def other(client: TestClient, db: Session, workspace: Workspace) -> Signed:
    """**같은 부서**의 다른 멤버 — 부서가 같아도 게시 전의 남의 작업은 안 보인다."""
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


def _ids(client: TestClient, who: Signed, **params: str) -> set[str]:
    listed = client.get(
        "/api/simulations", params={**params, "limit": "200"}, headers=who.headers
    )
    assert listed.status_code == 200, listed.text
    return {one["id"] for one in listed.json()["items"]}


def test_게시_전에는_건_사람과_시스템_관리자만_본다(
    client: TestClient, member: Signed, other: Signed, admin: Signed, manager: Signed
) -> None:
    job = _create(client, member)
    assert job["status"] == "done" and job["published_at"] is None
    path = f"/api/simulations/{job['id']}"
    # 같은 부서의 멤버도, 부서 관리자도 못 본다 — 없는 것과 같게 답한다.
    assert client.get(path, headers=other.headers).status_code == 404
    assert client.get(path, headers=manager.headers).status_code == 404
    assert job["id"] not in _ids(client, other)
    assert client.get(path, headers=admin.headers).status_code == 200
    assert job["id"] in _ids(client, member, scope="mine")
    assert job["id"] not in _ids(client, member, scope="published")


def test_게시하면_누구나_보고_읽기만_한다(
    client: TestClient, db: Session, member: Signed, other: Signed
) -> None:
    job = _create(client, member)
    path = f"/api/simulations/{job['id']}"
    # 못 보는 것은 게시할 수도 없다.
    assert client.post(f"{path}/publish", headers=other.headers).status_code == 404

    published = client.post(f"{path}/publish", headers=member.headers)
    assert published.status_code == 200, published.text
    assert published.json()["published_at"] is not None
    assert published.json()["published_by_name"] == "member"
    assert client.get(path, headers=other.headers).status_code == 200
    assert client.get(f"{path}/result", headers=other.headers).status_code == 200
    assert job["id"] in _ids(client, other, scope="published")
    assert job["id"] not in _ids(client, other, scope="mine")

    # **읽기만 한다** — 바꾸는 일은 건 사람이나 시스템 관리자.
    for action in ("unpublish", "publish", "tidy", "cancel", "retry"):
        refused = client.post(f"{path}/{action}", headers=other.headers)
        assert refused.status_code == 403, (action, refused.text)
    measured = client.post(
        f"{path}/measurements",
        files={
            "file": ("실측.csv", io.BytesIO("종류,주파수\n공진,300\n".encode()), "text/csv")
        },
        headers=other.headers,
    )
    assert measured.status_code == 403
    checked = client.post(
        f"{path}/convergence", json={"sizes_mm": [3.5]}, headers=other.headers
    )
    assert checked.status_code == 403

    # 해제하면 다시 건 사람의 것이다.
    assert client.post(f"{path}/unpublish", headers=member.headers).status_code == 200
    assert client.get(path, headers=other.headers).status_code == 404
    done = [
        one.action
        for one in db.scalars(
            select(AuditEntry).where(AuditEntry.target_id == uuid.UUID(job["id"]))
        )
    ]
    assert done == ["simulation.published", "simulation.unpublished"]


def test_끝나지_않은_작업은_게시하지_않는다(
    client: TestClient, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    job = _create(client, member)
    refused = client.post(f"/api/simulations/{job['id']}/publish", headers=member.headers)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"].endswith("SIMULATIONS-0034")


def test_메시_수렴_수준은_원래_작업을_따라_게시된다(
    client: TestClient, member: Signed, other: Signed
) -> None:
    """수렴 판정은 원래 작업의 것이다 — 게시하면 수준도 함께, 게시 뒤에 건 수준은 끝날 때
    따라 게시된다. 수준 하나를 눌러 열었을 때 남에게 404 가 나면 안 된다."""
    job = _create(client, member)
    path = f"/api/simulations/{job['id']}"
    first = client.post(
        f"{path}/convergence", json={"sizes_mm": [3.5]}, headers=member.headers
    )
    assert first.status_code == 201, first.text
    assert client.post(f"{path}/publish", headers=member.headers).status_code == 200
    later = client.post(
        f"{path}/convergence", json={"sizes_mm": [2.5]}, headers=member.headers
    )
    assert later.status_code == 201, later.text
    seen = client.get(f"{path}/convergence", headers=other.headers)
    assert seen.status_code == 200, seen.text
    levels = [one["simulation_id"] for one in seen.json()["levels"]]
    assert len(levels) == 3
    for level in levels:
        assert (
            client.get(f"/api/simulations/{level}", headers=other.headers).status_code == 200
        )


def test_DOE_를_게시하면_남이_보고_가져오기는_누구_것인지_말한다(
    client: TestClient,
    member: Signed,
    other: Signed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / DOE_FOLDER.name
    shutil.copytree(DOE_FOLDER, folder)
    study = json.loads((folder / "study.json").read_text(encoding="utf-8"))
    study["id"] = uuid.uuid4().hex
    (folder / "study.json").write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "doe_roots", str(tmp_path))
    request = {"path": str(folder), "spec": MODAL}

    made = client.post(
        "/api/simulations/doe/import",
        json={**request, "workspace_slug": member.workspace},
        headers=member.headers,
    )
    assert made.status_code == 201, made.text
    study_id = made.json()["study_id"]

    def studies(who: Signed) -> dict[str, Any]:
        listed = client.get("/api/simulations/studies", headers=who.headers).json()
        return {one["study_id"]: one for one in listed}

    assert study_id not in studies(other)
    # **같은 해석을 두 번 돌리지 않는다** — 다만 보이지 않는 작업 때문에 막히면 누구 것인지
    # 말한다.
    again = client.post(
        "/api/simulations/doe/import",
        json={**request, "workspace_slug": other.workspace},
        headers=other.headers,
    ).json()
    assert again["created"] == []
    reasons = {one["number"]: one["skip_reason"] for one in again["skipped"]}
    # 4번은 형상을 못 만든 점이라(CompCore 가 적은 까닭) 처음부터 안 걸렸다.
    assert all("member 님이 이미 가져온 점" in reasons[number] for number in (1, 2, 3))

    base = f"/api/simulations/studies/{study_id}"
    assert client.post(f"{base}/publish", headers=other.headers).status_code == 404
    published = client.post(f"{base}/publish", headers=member.headers)
    assert published.status_code == 200, published.text
    assert published.json() == {"points": 3, "jobs": 3}

    seen = studies(other)[study_id]
    assert (seen["published"], seen["owner_name"]) == (3, "member")

    # 개인 · 공용 작업공간으로 가른다 — 남의 게시 DOE 는 「공용」 에만, 내 것은 둘 다.
    def scoped(who: Signed, scope: str) -> set[str]:
        listed = client.get(
            "/api/simulations/studies", params={"scope": scope}, headers=who.headers
        ).json()
        return {one["study_id"] for one in listed}

    assert study_id in scoped(other, "published") and study_id not in scoped(other, "mine")
    assert study_id in scoped(member, "published") and study_id in scoped(member, "mine")
    detail = client.get(base, headers=other.headers).json()
    assert all(one["published"] for one in detail["points"])
    for action in ("publish", "unpublish", "tidy"):
        assert client.post(f"{base}/{action}", headers=other.headers).status_code == 403
    after = client.post(
        "/api/simulations/doe/import",
        json={**request, "workspace_slug": other.workspace},
        headers=other.headers,
    ).json()
    reasons = {one["number"]: one["skip_reason"] for one in after["skipped"]}
    assert all(reasons[number].startswith("이미 가져온 점입니다") for number in (1, 2, 3))

    assert client.post(f"{base}/unpublish", headers=member.headers).json()["jobs"] == 3
    assert study_id not in studies(other)
