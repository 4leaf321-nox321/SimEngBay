"""DOE 폴더의 기준정보(`study.json` 의 `ontology`, CompCore 2026-10-26).

CompCore 가 대상 작업의 태그와 부품 · 지그의 기준정보 칸(「적용 모델」 …)을 폴더에 싣는다 —
해석 쪽이 「어느 모델의 부품 해석인가」 를 폴더만 보고 알게. 우리는 걸기 전(미리보기) · 목록 ·
비교 화면에 그대로 보이고, 우리 온톨로지 사본(SP 수신)에 같은 객체가 있으면 그 객체로 잇는다.
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modules.ontology.models import OntologyObject, OntologyRelation, OntologyType
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
ONTOLOGY = {
    "tags": [
        {
            "object_id": "11111111-1111-1111-1111-111111111111",
            "key": "",
            "label": "시제품",
            "type_slug": "cc_tag",
            "type_label": "일반 태그",
        }
    ],
    "links": [
        {
            "on": {"kind": "part", "id": "p-1", "name": "브래킷"},
            "relation": "applies_to",
            "relation_label": "적용 모델",
            "object_id": "22222222-2222-2222-2222-222222222222",
            "key": "VM-001",
            "label": "차종 X",
            "type_slug": "vehicle_model",
            "type_label": "차종",
        }
    ],
}


@pytest.fixture(autouse=True)
def inline_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", True)


@pytest.fixture
def vehicle(db: Session) -> Iterator[None]:
    """우리 사본에 「차종 X」 가 있다 — CompCore 가 이은 것과 같은 타입 · 식별자."""
    for table in (OntologyRelation, OntologyObject, OntologyType):
        db.execute(delete(table))
    db.add(OntologyType(slug="vehicle_model", label="차종"))
    db.flush()
    db.add(OntologyObject(type_slug="vehicle_model", key="VM-001", label="차종 X"))
    db.commit()
    yield
    for table in (OntologyObject, OntologyType):
        db.execute(delete(table))
    db.commit()


def _folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ontology: Any) -> Path:
    folder = tmp_path / DOE_FOLDER.name
    shutil.copytree(DOE_FOLDER, folder)
    study = json.loads((folder / "study.json").read_text(encoding="utf-8"))
    study["id"] = uuid.uuid4().hex
    if ontology is not None:
        study["ontology"] = ontology
    (folder / "study.json").write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "doe_roots", str(tmp_path))
    return folder


def test_기준정보를_미리보기_목록_비교에_싣고_우리_사본의_객체로_잇는다(
    client: TestClient,
    member: Signed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    vehicle: None,
) -> None:
    folder = _folder(tmp_path, monkeypatch, ONTOLOGY)

    preview = client.get(
        "/api/simulations/doe/preview", params={"path": str(folder)}, headers=member.headers
    )
    assert preview.status_code == 200, preview.text
    shown = preview.json()["ontology"]
    # 「일반 태그」 는 CompCore 에만 있다 — 잇지 않는다. 「차종 X」 는 우리 사본에 있다.
    assert [(one["label"], one["known"]) for one in shown["tags"]] == [("시제품", False)]
    [link] = shown["links"]
    assert link["on"] == {"kind": "part", "id": "p-1", "name": "브래킷"}
    assert link["relation_label"] == "적용 모델"
    assert (link["label"], link["key"]) == ("차종 X", "VM-001")
    assert link["known"] is True

    request = {"path": str(folder), "spec": MODAL, "workspace_slug": member.workspace}
    made = client.post("/api/simulations/doe/import", json=request, headers=member.headers)
    assert made.status_code == 201, made.text
    study_id = made.json()["study_id"]

    detail = client.get(f"/api/simulations/studies/{study_id}", headers=member.headers)
    assert detail.json()["ontology"] == shown
    listed = client.get("/api/simulations/studies", headers=member.headers).json()
    row = next(one for one in listed if one["study_id"] == study_id)
    assert row["ontology"] == shown


def test_기준정보가_없는_옛_폴더는_빈_두_목록이다(
    client: TestClient, member: Signed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(tmp_path, monkeypatch, None)
    request = {"path": str(folder), "spec": MODAL, "workspace_slug": member.workspace}
    made = client.post("/api/simulations/doe/import", json=request, headers=member.headers)
    assert made.status_code == 201, made.text
    detail = client.get(
        f"/api/simulations/studies/{made.json()['study_id']}", headers=member.headers
    )
    assert detail.json()["ontology"] == {"tags": [], "links": []}
