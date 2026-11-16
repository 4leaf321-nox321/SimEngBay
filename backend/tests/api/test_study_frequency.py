"""주파수 요구 API — 스터디에 목표 주파수 · 회피 대역을 저장하고 판정을 받는다(MCP
`study_frequency`, 화면 「주파수 요구」 탭).

판정 셈 자체는 `tests/unit/test_study_frequency.py` 가 본다. 여기서는 저장 · 미리보기 · 권한을
본다 — fake 실행기의 결과에는 모드 지문이 없어 차례로 센다.
"""

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
from tests.api.test_study_analysis import DOE_FOLDER, MODAL


@pytest.fixture(autouse=True)
def inline_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", True)


def _imported(
    client: TestClient, member: Signed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
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
    return str(made.json()["study_id"])


def _requirements(first_hz: float) -> dict[str, Any]:
    return {
        "requirements": [
            {
                "kind": "target",
                "label": "1차 맞춤",
                "mode": 1,
                "target_hz": first_hz,
                "tolerance_pct": 2,
            },
            {
                "kind": "band",
                "label": "모터 가진",
                "low_hz": first_hz * 1.5,
                "high_hz": first_hz * 1.8,
                "margin_pct": 5,
            },
        ]
    }


def test_요구_조건을_미리_보고_스터디에_저장한다(
    client: TestClient,
    member: Signed,
    manager: Signed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    study_id = _imported(client, member, tmp_path, monkeypatch)
    base = f"/api/simulations/studies/{study_id}"

    empty = client.get(f"{base}/frequency", headers=member.headers)
    assert empty.status_code == 200, empty.text
    body = empty.json()
    assert body["saved"] is False and body["requirements"] == []
    assert body["counts"]["pending"] == 3
    assert any("요구 조건이 없습니다" in one for one in body["notes"])
    # fake 결과에는 모드 지문이 없다 — 차례로 센다고 말한다.
    assert body["tracked"] is False and any("차례" in one for one in body["notes"])

    first = float(
        client.get(base, headers=member.headers).json()["points"][0]["frequencies"][0]
    )
    draft = _requirements(first)
    preview = client.post(f"{base}/frequency/check", json=draft, headers=member.headers)
    assert preview.status_code == 200, preview.text
    shown = preview.json()
    assert shown["saved"] is False
    assert shown["counts"]["conform"] == 3
    # 참여 정보가 없는 결과 — 모든 모드를 판정 대상으로 둔다고 말한다.
    assert any("참여 정보" in one for one in shown["notes"])
    # 미리보기는 저장하지 않는다.
    assert client.get(f"{base}/frequency", headers=member.headers).json()["requirements"] == []

    saved = client.put(f"{base}/frequency", json=draft, headers=member.headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["saved"] is True
    assert saved.json()["updated_by_name"] == "member"
    again = client.get(f"{base}/frequency", headers=member.headers).json()
    assert [one["kind"] for one in again["requirements"]] == ["target", "band"]
    assert again["requirements"][1]["mass_direction"] == "Z"
    assert again["counts"] == shown["counts"]

    # 고쳐 저장하면 덮어쓴다 — 한 스터디에 한 벌.
    draft["requirements"] = draft["requirements"][:1]
    assert (
        client.put(f"{base}/frequency", json=draft, headers=member.headers).status_code == 200
    )
    assert (
        len(client.get(f"{base}/frequency", headers=member.headers).json()["requirements"])
        == 1
    )

    # 게시하면 남도 읽는다 — 바꾸는 것은 건 사람(과 시스템 관리자)만.
    assert client.post(f"{base}/publish", headers=member.headers).status_code == 200
    seen = client.get(f"{base}/frequency", headers=manager.headers)
    assert seen.status_code == 200 and seen.json()["saved"] is True
    refused = client.put(f"{base}/frequency", json=draft, headers=manager.headers)
    assert refused.status_code == 403


def test_회피_대역의_상한이_하한보다_작으면_거절한다(
    client: TestClient, member: Signed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study_id = _imported(client, member, tmp_path, monkeypatch)
    bad = {"requirements": [{"kind": "band", "low_hz": 900, "high_hz": 700}]}
    got = client.post(
        f"/api/simulations/studies/{study_id}/frequency/check",
        json=bad,
        headers=member.headers,
    )
    assert got.status_code == 422
    missing = client.get(
        "/api/simulations/studies/없는-스터디/frequency", headers=member.headers
    )
    assert missing.status_code == 404
