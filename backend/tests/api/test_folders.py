"""해석 작업 · DOE 를 **폴더로 나눠 본다**(2026-10-23, ADR 0013).

폴더는 표가 따로 없다 — 작업 행이 들고 있는 경로(`고객A/2026`)에서 나무를 세운다(CompCore 와
같은 규칙). DOE 의 폴더는 그 설계점 작업들의 폴더라, 두 목록이 한 폴더 공간을 나눠 쓴다.
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
from sqlalchemy.orm import Session

from app.config import get_settings
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
    user = _make_user(db, workspace, label="other", is_system_admin=False, role="member")
    return Signed(email=user.email, token=_login(client, user.email), workspace=workspace.slug)


def _create(client: TestClient, who: Signed, name: str) -> str:
    response = client.post(
        "/api/simulations",
        data={"spec": json.dumps(MODAL), "workspace_slug": who.workspace, "name": name},
        files={"file": ("브래킷.step", io.BytesIO(STEP), "model/step")},
        headers=who.headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _names(client: TestClient, who: Signed, **params: str) -> set[str]:
    listed = client.get(
        "/api/simulations",
        params={"scope": "mine", "limit": "200", **params},
        headers=who.headers,
    )
    assert listed.status_code == 200, listed.text
    return {one["name"] for one in listed.json()["items"]}


def _tree(
    client: TestClient, who: Signed, path: str = "/api/simulations/folders"
) -> dict[str, int]:
    got = client.get(path, params={"scope": "mine"}, headers=who.headers)
    assert got.status_code == 200, got.text
    return {one["path"]: one["count"] for one in got.json()}


def test_작업을_폴더로_옮기고_폴더로_거른다(client: TestClient, member: Signed) -> None:
    tag = uuid.uuid4().hex[:6]
    a = _create(client, member, f"가-{tag}")
    b = _create(client, member, f"나-{tag}")
    _create(client, member, f"다-{tag}")
    moved = client.post(
        "/api/simulations/move",
        json={"ids": [a], "folder": f"/고객{tag}//2026/ "},
        headers=member.headers,
    )
    assert moved.json() == {"moved": 1}
    client.post(
        "/api/simulations/move",
        json={"ids": [b], "folder": f"고객{tag}"},
        headers=member.headers,
    )

    # 고른 폴더는 그 아래까지 · 빈 것은 폴더에 넣지 않은 것만.
    assert {f"가-{tag}", f"나-{tag}"} <= _names(client, member, folder=f"고객{tag}")
    assert _names(client, member, folder=f"고객{tag}/2026") >= {f"가-{tag}"}
    assert f"나-{tag}" not in _names(client, member, folder=f"고객{tag}/2026")
    loose = _names(client, member, folder="")
    assert f"다-{tag}" in loose and f"가-{tag}" not in loose
    # 나무 — 바로 그 폴더에 있는 수, 위 폴더도 빠짐없이.
    tree = _tree(client, member)
    assert tree[f"고객{tag}"] == 1 and tree[f"고객{tag}/2026"] == 1 and "" in tree
    one = client.get(f"/api/simulations/{a}", headers=member.headers).json()
    assert one["folder"] == f"고객{tag}/2026"


def test_폴더_이름_바꾸기는_하위까지_함께_가고_지우기는_위로_합친다(
    client: TestClient, member: Signed
) -> None:
    tag = uuid.uuid4().hex[:6]
    a = _create(client, member, f"가-{tag}")
    b = _create(client, member, f"나-{tag}")
    client.post(
        "/api/simulations/move",
        json={"ids": [a], "folder": f"옛{tag}/안"},
        headers=member.headers,
    )
    client.post(
        "/api/simulations/move",
        json={"ids": [b], "folder": f"옛{tag}"},
        headers=member.headers,
    )
    renamed = client.post(
        "/api/simulations/folders/rename",
        json={"path": f"옛{tag}", "to": f"새{tag}"},
        headers=member.headers,
    )
    assert renamed.json() == {"moved": 2}
    tree = _tree(client, member)
    assert f"새{tag}/안" in tree and f"옛{tag}" not in tree

    # 지우기 = 위 폴더로 합치기 — 작업은 지우지 않는다.
    client.post(
        "/api/simulations/folders/rename",
        json={"path": f"새{tag}/안", "to": f"새{tag}"},
        headers=member.headers,
    )
    assert _tree(client, member)[f"새{tag}"] == 2
    root = client.post(
        "/api/simulations/folders/rename", json={"path": "", "to": "x"}, headers=member.headers
    )
    assert root.status_code == 422 or root.json()["error"]["code"].endswith("SIMULATIONS-0038")
    inside = client.post(
        "/api/simulations/folders/rename",
        json={"path": f"새{tag}", "to": f"새{tag}/더"},
        headers=member.headers,
    )
    assert inside.json()["error"]["code"].endswith("SIMULATIONS-0038")


def test_남의_작업은_못_옮기고_틀린_경로는_말한다(
    client: TestClient, member: Signed, other: Signed
) -> None:
    mine = _create(client, member, f"내것-{uuid.uuid4().hex[:6]}")
    # 안 보이면 없는 것 — 하나라도 못 옮기면 아무것도 안 옮긴다.
    theirs = client.post(
        "/api/simulations/move", json={"ids": [mine], "folder": "남"}, headers=other.headers
    )
    assert theirs.status_code == 404
    assert (
        client.post(f"/api/simulations/{mine}/publish", headers=member.headers).status_code
        == 200
    )
    refused = client.post(
        "/api/simulations/move", json={"ids": [mine], "folder": "남"}, headers=other.headers
    )
    assert refused.status_code == 403
    deep = client.post(
        "/api/simulations/move",
        json={"ids": [mine], "folder": "/".join("abcdefghi")},
        headers=member.headers,
    )
    assert deep.json()["error"]["code"].endswith("SIMULATIONS-0037")
    # 남이 같은 이름의 폴더를 바꿔도 내 작업은 그대로다(폴더는 제 것을 나누는 자리).
    client.post(
        "/api/simulations/move", json={"ids": [mine], "folder": "같은"}, headers=member.headers
    )
    client.post(
        "/api/simulations/folders/rename",
        json={"path": "같은", "to": "바뀐"},
        headers=other.headers,
    )
    assert (
        client.get(f"/api/simulations/{mine}", headers=member.headers).json()["folder"]
        == "같은"
    )


def test_DOE_를_폴더로_옮기면_설계점_작업도_그_폴더에_선다(
    client: TestClient, member: Signed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / DOE_FOLDER.name
    shutil.copytree(DOE_FOLDER, folder)
    study = json.loads((folder / "study.json").read_text(encoding="utf-8"))
    study["id"] = uuid.uuid4().hex
    (folder / "study.json").write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "doe_roots", str(tmp_path))
    made = client.post(
        "/api/simulations/doe/import",
        json={"path": str(folder), "spec": MODAL, "workspace_slug": member.workspace},
        headers=member.headers,
    )
    assert made.status_code == 201, made.text
    study_id = made.json()["study_id"]
    tag = uuid.uuid4().hex[:6]

    moved = client.post(
        "/api/simulations/studies/move",
        json={"ids": [study_id], "folder": f"프로젝트{tag}"},
        headers=member.headers,
    )
    assert moved.json() == {"moved": 1}

    def studies(**params: str) -> dict[str, Any]:
        got = client.get(
            "/api/simulations/studies",
            params={"scope": "mine", **params},
            headers=member.headers,
        )
        return {one["study_id"]: one for one in got.json()}

    assert studies()[study_id]["folder"] == f"프로젝트{tag}"
    assert study_id in studies(folder=f"프로젝트{tag}")
    assert study_id not in studies(folder="")
    tree = _tree(client, member, "/api/simulations/studies/folders")
    assert tree[f"프로젝트{tag}"] == 1
    # 한 폴더 공간 — 해석 작업 목록에서도 그 설계점 작업들이 그 폴더에 있다.
    points = client.get(
        "/api/simulations",
        params={"folder": f"프로젝트{tag}", "limit": "200"},
        headers=member.headers,
    ).json()["items"]
    assert len(points) == 3 and all(one["source_kind"] == "doe_point" for one in points)
    assert client.delete(f"/api/simulations/studies/{study_id}", headers=member.headers)
