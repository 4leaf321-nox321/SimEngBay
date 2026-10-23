"""DOE 분석 API — 가져온 DOE 에서 비교 화면과 같은 표로 셈한다(MCP `study_analyze`)."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from tests.api.conftest import Signed

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


def test_가져온_DOE_를_분석하고_모르는_열은_쓸_수_있는_열과_함께_거절한다(
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
    base = f"/api/simulations/studies/{made.json()['study_id']}"

    got = client.get(
        f"{base}/analysis",
        params={"objective": "mass_kg", "goal": "min", "where": ["factor:두께>=0"]},
        headers=member.headers,
    )
    assert got.status_code == 200, got.text
    body = got.json()
    keys = [one["key"] for one in body["columns"]]
    assert keys[0] == "factor:두께" and "mass_kg" in keys
    assert body["done"] == 3
    assert {one["result"] for one in body["sensitivity"]} >= {"mass_kg"}
    assert body["choice"]["feasible"] == 3 and body["choice"]["best"] is not None

    refused = client.get(
        f"{base}/analysis", params={"objective": "무게"}, headers=member.headers
    )
    assert refused.status_code == 400
    assert refused.json()["error"]["code"].endswith("SIMULATIONS-0036")
    assert "쓸 수 있는 열" in refused.json()["error"]["message"]
    assert client.delete(base, headers=member.headers).status_code == 200
