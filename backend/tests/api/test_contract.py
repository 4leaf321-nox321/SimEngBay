"""모르는 조건 판은 **작업을 만들 때** 거절한다(`app/core/contract.py`, SIMULATIONS-0043).

v2(케이스 여럿)가 오면 구속 0 · 하중 0 · modal 로 조용히 읽혔다. 걸어 두면 DOE 200점이
자유-자유 모달로 끝까지 돈다. v2 를 받게 된 뒤로는(`app/core/cases.py`) 그 자리를 판 3 이
잇는다 —
읽는 판(1 · 2)이 아니면 막는다.
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
from app.modules.simulations.models import Simulation
from tests.api.conftest import Signed

SWEEP = Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "조건_재료훑기"
STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
MODAL = {"recipe": "modal", "mesh": {"element_size_mm": 8}}


def _to_unknown(path: Path) -> bytes:
    """읽지 못하는 판(3) — 모양도 케이스로 나눴다."""
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    block = payload["conditions"]
    block["schema_version"] = 3
    case = {
        key: block.pop(key)
        for key in ("analysis", "loads", "constraints", "initial")
        if key in block
    }
    block["cases"] = [{"name": "예압", **case}, {"name": "외력", "depends_on": "예압", **case}]
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


@pytest.fixture(autouse=True)
def queued(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", False)


@pytest.mark.parametrize("conditions_from", ["cad", "spec"])
def test_올린_점_파일의_판을_모르면_CAD_조건을_꺼도_거절한다(
    client: TestClient, db: Session, member: Signed, conditions_from: str
) -> None:
    point = next(iter(sorted((SWEEP / "points").glob("p*.json"))))
    before = len(db.scalars(select(Simulation.id)).all())
    refused = client.post(
        "/api/simulations",
        data={
            "spec": json.dumps({**MODAL, "conditions_from": conditions_from}),
            "workspace_slug": member.workspace,
        },
        files={
            "file": ("p0001.step", io.BytesIO(STEP), "model/step"),
            "topology": ("p0001.json", io.BytesIO(_to_unknown(point)), "application/json"),
        },
        headers=member.headers,
    )
    assert refused.status_code == 400, refused.text
    error = refused.json()["error"]
    assert error["code"].endswith("SIMULATIONS-0043"), error
    assert "schema_version = 3" in error["message"] and "읽는 판: 1 · 2" in error["message"]
    assert len(db.scalars(select(Simulation.id)).all()) == before


def test_미리_보기는_판을_막힌_조건으로_보인다(client: TestClient, member: Signed) -> None:
    point = next(iter(sorted((SWEEP / "points").glob("p*.json"))))
    shown = client.post(
        "/api/simulations/conditions/preview",
        files={"file": ("p0001.json", io.BytesIO(_to_unknown(point)), "application/json")},
        headers=member.headers,
    )
    assert shown.status_code == 200, shown.text
    lines = shown.json()["conditions"]["lines"]
    assert [(one["label"], one["status"]) for one in lines] == [("조건의 판", "refused")], (
        lines
    )


def test_DOE_는_모르는_판의_점만_까닭과_함께_뺀다(
    client: TestClient,
    db: Session,
    member: Signed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "재료훑기"
    shutil.copytree(SWEEP, folder)
    study = json.loads((folder / "study.json").read_text(encoding="utf-8"))
    study["id"] = uuid.uuid4().hex
    (folder / "study.json").write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
    points = sorted((folder / "points").glob("p*.json"))
    points[0].write_bytes(_to_unknown(points[0]))
    number = int(points[0].stem[1:])
    monkeypatch.setattr(get_settings(), "doe_roots", str(tmp_path))

    preview = client.get(
        "/api/simulations/doe/preview", params={"path": str(folder)}, headers=member.headers
    )
    assert preview.status_code == 200, preview.text
    rows = {row["number"]: row for row in preview.json()["points"]}
    assert rows[number]["usable"] is False and "조건의 판" in rows[number]["skip_reason"]

    made = client.post(
        "/api/simulations/doe/import",
        json={"path": str(folder), "spec": MODAL, "workspace_slug": member.workspace},
        headers=member.headers,
    )
    assert made.status_code == 201, made.text
    body = made.json()
    skipped = {row["number"]: row["skip_reason"] for row in body["skipped"]}
    assert "조건의 판(schema_version = 3)" in skipped[number]
    assert len(body["created"]) == len([one for one in rows.values() if one["usable"]])
    for job in body["created"]:
        row = db.get(Simulation, uuid.UUID(job))
        assert row is not None
        row.status = "canceled"
    db.commit()
