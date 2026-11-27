"""해석 케이스(v2)를 받는다 — **사슬 하나 = 작업 하나**(`services.case_view` · `import_doe`).

작업에는 사슬 하나의 v1 보기를 담고(`topology.json`), 스펙 · `source_meta` 에 끝 케이스를
적는다.
DOE 는 (점, 케이스)마다 작업이 하나다. 판 1 로 가져온 옛 작업은 케이스가 비어 있다 — 사슬이
하나뿐인
점이면 그것이 그 사슬이다.
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
from app.modules.simulations import services
from app.modules.simulations.models import Simulation
from tests.api.conftest import Signed

DOE = Path(__file__).resolve().parents[1] / "fixtures" / "doe"
STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
MESH = {"mesh": {"element_size_mm": 8}}


@pytest.fixture(autouse=True)
def queued(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", False)


def _upload(client: TestClient, who: Signed, folder: str, spec: dict[str, Any]) -> Any:
    point = DOE / folder / "points" / "p0001.json"
    return client.post(
        "/api/simulations",
        data={"spec": json.dumps({**MESH, **spec}), "workspace_slug": who.workspace},
        files={
            "file": ("p0001.step", io.BytesIO(STEP), "model/step"),
            "topology": ("p0001.json", io.BytesIO(point.read_bytes()), "application/json"),
        },
        headers=who.headers,
    )


def _cancel(db: Session, ids: list[str]) -> None:
    for one in ids:
        row = db.get(Simulation, uuid.UUID(one))
        assert row is not None
        row.status = "canceled"
    db.commit()


def test_사슬이_여럿이면_케이스를_골라야_한다(client: TestClient, member: Signed) -> None:
    refused = _upload(client, member, "조건_볼트예압_사슬_둘", {"recipe": "static"})
    assert refused.status_code == 400, refused.text
    error = refused.json()["error"]
    assert error["code"].endswith("SIMULATIONS-0046")
    assert error["details"]["cases"] == ["모달 단독", "외력"]


def test_고른_사슬의_v1_보기를_작업에_담는다(
    client: TestClient, db: Session, member: Signed
) -> None:
    made = _upload(
        client, member, "조건_볼트예압_사슬_둘", {"recipe": "static", "case": "외력"}
    )
    assert made.status_code == 201, made.text
    row = db.get(Simulation, uuid.UUID(made.json()["id"]))
    assert row is not None
    assert row.recipe == "static" and row.spec["case"] == "외력"
    assert row.source_meta["case"] == "외력"
    assert row.work_dir is not None
    stored = json.loads((services.work_root() / row.work_dir / "topology.json").read_text())
    block = stored["conditions"]
    assert block["schema_version"] == 1 and "cases" not in block
    assert block["case"]["chain"] == ["예압", "외력"]
    assert [one["type"] for one in block["loads"]] == ["bolt_pretension", "force"]
    _cancel(db, [made.json()["id"]])


@pytest.mark.parametrize(
    ("folder", "spec", "said"),
    [
        ("조건_볼트예압_사슬_둘", {"recipe": "modal", "case": "외력"}, "static 입니다"),
        (
            "조건_볼트예압_두케이스",
            {"recipe": "static", "solver": "ansys"},
            "대상 솔버는 calculix",
        ),
        ("조건_외팔보_두케이스", {"recipe": "static"}, "정적 다단"),
        ("조건_볼트예압_사슬_둘", {"recipe": "static", "case": "없는 것"}, "없습니다"),
    ],
    ids=["레시피가 다름", "대상 솔버가 다름", "정적 다단(다음 판)", "없는 케이스"],
)
def test_사슬과_맞지_않는_작업은_까닭과_막는다(
    client: TestClient, member: Signed, folder: str, spec: dict[str, Any], said: str
) -> None:
    refused = _upload(client, member, folder, spec)
    assert refused.status_code == 400, refused.text
    error = refused.json()["error"]
    assert error["code"].endswith("SIMULATIONS-0046"), error
    assert said in error["message"]


def test_판_1_점에_케이스를_고르면_막는다(client: TestClient, member: Signed) -> None:
    refused = _upload(
        client, member, "조건_볼트예압_정적", {"recipe": "static", "case": "외력"}
    )
    assert refused.status_code == 400
    assert refused.json()["error"]["code"].endswith("SIMULATIONS-0046")


def _study(tmp_path: Path, folder: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / folder
    shutil.copytree(DOE / folder, target)
    study = json.loads((target / "study.json").read_text(encoding="utf-8"))
    study["id"] = uuid.uuid4().hex
    (target / "study.json").write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "doe_roots", str(tmp_path))
    return target


def _import(client: TestClient, who: Signed, folder: Path, spec: dict[str, Any]) -> Any:
    made = client.post(
        "/api/simulations/doe/import",
        json={"path": str(folder), "spec": spec, "workspace_slug": who.workspace},
        headers=who.headers,
    )
    assert made.status_code == 201, made.text
    return made.json()


def test_DOE_는_사슬마다_작업을_걸고_다시_가져오면_겹치지_않는다(
    client: TestClient,
    db: Session,
    member: Signed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = _study(tmp_path, "조건_볼트예압_사슬_둘", monkeypatch)
    # 사람이 고른 레시피는 모달이어도 — 사슬마다 끝 케이스의 해석 종류로 건다.
    body = _import(client, member, folder, {"recipe": "modal", "modes": 8, **MESH})
    rows = [db.get(Simulation, uuid.UUID(one)) for one in body["created"]]
    got = sorted((row.source_meta["case"], row.recipe, row.name) for row in rows if row)
    assert [(case, recipe) for case, recipe, _ in got] == [
        ("모달 단독", "modal"),
        ("외력", "static"),
    ]
    assert all(name.endswith(f" · {case}") for case, _, name in got)
    assert body["skipped"] == []

    again = _import(client, member, folder, {"recipe": "modal", **MESH})
    assert again["created"] == []
    assert sorted(row["case"] for row in again["skipped"]) == ["모달 단독", "외력"]
    assert all("이미" in row["skip_reason"] for row in again["skipped"])
    _cancel(db, body["created"])


def test_못_거는_사슬만_까닭과_함께_빠진다(
    client: TestClient,
    db: Session,
    member: Signed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = _study(tmp_path, "조건_외팔보_두케이스", monkeypatch)
    body = _import(client, member, folder, {"recipe": "static", **MESH})
    assert body["created"] == []
    [skipped] = body["skipped"]
    assert skipped["case"] == "힘 B" and "정적 다단" in skipped["skip_reason"]


def test_판_1_로_가져온_점을_사슬_하나인_판_2_로_다시_가져와도_겹치지_않는다(
    client: TestClient,
    db: Session,
    member: Signed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """케이스가 비어 있는 옛 작업 — 사슬이 하나뿐인 점이면 그것이 그 사슬이다."""
    folder = _study(tmp_path, "조건_볼트예압_정적", monkeypatch)
    first = _import(client, member, folder, {"recipe": "static", **MESH})
    assert first["created"]
    points = sorted((folder / "points").glob("p*.json"))
    # CompCore 가 같은 스터디를 판 2(사슬 하나 「예압 → 외력」)로 다시 내보냈다.
    shutil.copyfile(
        DOE / "조건_볼트예압_두케이스_솔버없음" / "points" / "p0001.json", points[0]
    )
    again = _import(client, member, folder, {"recipe": "static", **MESH})
    assert again["created"] == []
    number = int(points[0].stem[1:])
    reasons = {row["number"]: row["skip_reason"] for row in again["skipped"]}
    assert "이미" in reasons[number]
    _cancel(db, first["created"])


def test_미리_보기는_사슬을_보이고_고른_사슬로_편다(
    client: TestClient, member: Signed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    point = DOE / "조건_볼트예압_사슬_둘" / "points" / "p0001.json"
    shown = client.post(
        "/api/simulations/conditions/preview",
        data={"case": "외력"},
        files={"file": ("p0001.json", io.BytesIO(point.read_bytes()), "application/json")},
        headers=member.headers,
    )
    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert [(one["name"], one["kind"], one["chain"]) for one in body["cases"]] == [
        ("모달 단독", "modal", ["모달 단독"]),
        ("외력", "static", ["예압", "외력"]),
    ]
    assert body["case"] == "외력" and body["recipe"] == "static"
    labels = [(one["label"], one["status"]) for one in body["conditions"]["lines"]]
    assert all(status != "refused" for _, status in labels), labels

    folder = _study(tmp_path, "조건_외팔보_두케이스", monkeypatch)
    preview = client.get(
        "/api/simulations/doe/preview", params={"path": str(folder)}, headers=member.headers
    )
    assert preview.status_code == 200, preview.text
    [case] = preview.json()["cases"]
    assert case["name"] == "힘 B" and "정적 다단" in case["problem"]


def test_케이스가_하나뿐인_v2_는_케이스를_안_골라도_건다(
    client: TestClient, db: Session, member: Signed
) -> None:
    from tests.unit.test_cases import single

    payload = single("조건_볼트예압_정적")
    made = client.post(
        "/api/simulations",
        data={
            "spec": json.dumps({**MESH, "recipe": "static"}),
            "workspace_slug": member.workspace,
        },
        files={
            "file": ("p0001.step", io.BytesIO(STEP), "model/step"),
            "topology": (
                "p0001.json",
                io.BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
                "application/json",
            ),
        },
        headers=member.headers,
    )
    assert made.status_code == 201, made.text
    row = db.get(Simulation, uuid.UUID(made.json()["id"]))
    assert row is not None and row.source_meta["case"] == "하나"
    _cancel(db, [made.json()["id"]])
