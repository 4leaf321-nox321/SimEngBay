"""CompCore 가 잘못 걸렸다고 판정한 접촉이 든 점은 **작업을 만들 때** 막는다(CompCore 의 부탁,
2026-11-26). 「CAD 가 보낸 조건 사용」 을 끄면 그 접촉을 안 쓰므로 막지 않는다.
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
from app.modules.simulations.models import Simulation
from tests.api.conftest import Signed

DOE = Path(__file__).resolve().parents[1] / "fixtures" / "doe"
SWEEP = DOE / "조건_재료훑기"
STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
MODAL = {"recipe": "modal", "mesh": {"element_size_mm": 8}}
FLAG = {
    "name": "블록-판",
    "type": "bonded",
    "source": "블록 아랫면",
    "target": "판 윗면",
    "problem": "same_face",
}


def _flagged(path: Path) -> bytes:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("quality", {})["misplaced_contacts"] = [FLAG]
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


@pytest.fixture(autouse=True)
def queued(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", False)


def _upload(client: TestClient, who: Signed, conditions_from: str) -> Any:
    point = sorted((SWEEP / "points").glob("p*.json"))[0]
    return client.post(
        "/api/simulations",
        data={
            "spec": json.dumps({**MODAL, "conditions_from": conditions_from}),
            "workspace_slug": who.workspace,
        },
        files={
            "file": ("p0001.step", io.BytesIO(STEP), "model/step"),
            "topology": ("p0001.json", io.BytesIO(_flagged(point)), "application/json"),
        },
        headers=who.headers,
    )


def test_판정된_접촉이_든_점은_작업을_만들지_않는다(
    client: TestClient, member: Signed
) -> None:
    refused = _upload(client, member, "cad")
    assert refused.status_code == 400, refused.text
    error = refused.json()["error"]
    assert error["code"].endswith("SIMULATIONS-0030"), error
    assert "접촉 「블록-판」" in error["message"] and "같은 면" in error["message"]


def test_CAD_조건을_끄면_그_접촉을_안_쓰므로_건다(
    client: TestClient, db: Session, member: Signed
) -> None:
    made = _upload(client, member, "spec")
    assert made.status_code == 201, made.text
    row = db.get(Simulation, uuid.UUID(made.json()["id"]))
    assert row is not None
    row.status = "canceled"
    db.commit()


def test_DOE_는_판정된_점만_까닭과_함께_뺀다(
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
    points[0].write_bytes(_flagged(points[0]))
    number = int(points[0].stem[1:])
    monkeypatch.setattr(get_settings(), "doe_roots", str(tmp_path))

    made = client.post(
        "/api/simulations/doe/import",
        json={"path": str(folder), "spec": MODAL, "workspace_slug": member.workspace},
        headers=member.headers,
    )
    assert made.status_code == 201, made.text
    body = made.json()
    skipped = {row["number"]: row["skip_reason"] for row in body["skipped"]}
    assert "접촉 「블록-판」" in skipped[number]
    assert len(body["created"]) == len(points) - 1
    for job in body["created"]:
        row = db.get(Simulation, uuid.UUID(job))
        assert row is not None
        row.status = "canceled"
    db.commit()
