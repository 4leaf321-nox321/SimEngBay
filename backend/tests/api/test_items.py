"""「해석」 목록 — **단일 해석과 DOE 한 벌이 한 줄씩**(2026-10-23, ADR 0014).

전에는 해석 작업 목록에 DOE 설계점이 낱개로 섞여(200점이면 200줄) 「DOE 비교」 와 같은 것이 두
곳에 보였다. 이제 설계점 · 메시 수렴 수준은 줄로 서지 않고, 상태로 거를 때만 낱개로 편다(줄
보기).
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


@pytest.fixture
def made(
    client: TestClient, member: Signed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """단일 해석 하나(메시 수렴 수준 하나 딸림)와 DOE 한 벌(설계점 셋)."""
    single = client.post(
        "/api/simulations",
        data={"spec": json.dumps(MODAL), "workspace_slug": member.workspace},
        files={"file": ("브래킷.step", io.BytesIO(STEP), "model/step")},
        headers=member.headers,
    ).json()["id"]
    level = client.post(
        f"/api/simulations/{single}/convergence",
        json={"sizes_mm": [3.5]},
        headers=member.headers,
    ).json()["levels"][1]["simulation_id"]
    folder = tmp_path / DOE_FOLDER.name
    shutil.copytree(DOE_FOLDER, folder)
    study = json.loads((folder / "study.json").read_text(encoding="utf-8"))
    study["id"] = uuid.uuid4().hex
    (folder / "study.json").write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "doe_roots", str(tmp_path))
    imported = client.post(
        "/api/simulations/doe/import",
        json={"path": str(folder), "spec": MODAL, "workspace_slug": member.workspace},
        headers=member.headers,
    ).json()
    return {
        "single": single,
        "level": level,
        "study": imported["study_id"],
        "points": imported["created"],
    }


def _keys(client: TestClient, who: Signed, **params: str) -> list[str]:
    got = client.get(
        "/api/simulations/items",
        params={"scope": "mine", "limit": "200", **params},
        headers=who.headers,
    )
    assert got.status_code == 200, got.text
    return [one["key"] for one in got.json()["items"]]


def test_DOE_는_한_줄_설계점과_수렴_수준은_줄로_서지_않는다(
    client: TestClient, member: Signed, made: dict[str, Any]
) -> None:
    keys = _keys(client, member)
    assert f"job:{made['single']}" in keys
    assert keys.count(f"doe:{made['study']}") == 1
    hidden = {f"job:{one}" for one in [made["level"], *made["points"]]}
    assert not hidden & set(keys)
    # DOE 줄에는 그 DOE 의 요약(점 수 · 진행)이 실린다.
    got = client.get(
        "/api/simulations/items",
        params={"scope": "mine", "kind": "doe"},
        headers=member.headers,
    ).json()["items"]
    row = next(one for one in got if one["key"] == f"doe:{made['study']}")
    assert row["kind"] == "doe" and row["study"]["points"] == 3 and row["job"] is None
    assert all(one["kind"] == "doe" for one in got)
    assert all(
        one["kind"] == "job"
        for one in client.get(
            "/api/simulations/items",
            params={"scope": "mine", "kind": "job"},
            headers=member.headers,
        ).json()["items"]
    )


def test_상태로_거르면_설계점까지_낱개로_편다(
    client: TestClient, member: Signed, made: dict[str, Any]
) -> None:
    """「지금 끝난(대기 · 실패) 작업 전부」 는 설계점 하나하나가 답이다 — 줄 보기."""
    keys = _keys(client, member, status="done")
    assert {f"job:{one}" for one in made["points"]} <= set(keys)
    assert f"doe:{made['study']}" not in keys


def test_항목을_섞어_폴더로_옮기면_딸린_작업도_따라간다(
    client: TestClient, member: Signed, other: Signed, made: dict[str, Any]
) -> None:
    tag = uuid.uuid4().hex[:6]
    keys = [f"job:{made['single']}", f"doe:{made['study']}"]
    # 남은 못 옮긴다 — 하나라도 안 되면 아무것도 안 옮긴다.
    refused = client.post(
        "/api/simulations/items/move",
        json={"ids": keys, "folder": "남"},
        headers=other.headers,
    )
    assert refused.status_code == 404
    bad = client.post(
        "/api/simulations/items/move",
        json={"ids": ["x:1"], "folder": "a"},
        headers=member.headers,
    )
    assert bad.status_code == 400

    moved = client.post(
        "/api/simulations/items/move",
        json={"ids": keys, "folder": f"고객{tag}"},
        headers=member.headers,
    )
    assert moved.json() == {"moved": 2}
    assert set(_keys(client, member, folder=f"고객{tag}")) == set(keys)
    # 수렴 수준 · 설계점이 원래 작업 · DOE 를 따라갔다.
    for one in [made["level"], *made["points"]]:
        job = client.get(f"/api/simulations/{one}", headers=member.headers).json()
        assert job["folder"] == f"고객{tag}"
    tree = client.get(
        "/api/simulations/items/folders", params={"scope": "mine"}, headers=member.headers
    ).json()
    assert {one["path"]: one["count"] for one in tree}[f"고객{tag}"] == 2
