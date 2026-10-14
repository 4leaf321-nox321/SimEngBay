"""온톨로지 화면의 API — 읽기는 누구나, 「지금 받기」 · 「받나」 는 시스템 관리자.

받는 규칙 자체는 `tests/unit/test_ontology_sync.py` 가 본다. 여기서는 **길**을 본다: 설정이
없으면 무엇을 적어야 하는지 말하나, 「지금 받기」 가 같은 수신을 지나 기록을 남기나, 받은 것을
타입 · 객체 · 선으로 볼 수 있나, 겹치면 막나.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.modules.ontology import services
from app.modules.ontology.models import (
    OntologyObject,
    OntologyRelation,
    OntologySyncRun,
    OntologyType,
)
from tests.api.conftest import Signed
from tests.ontology_fake import FakeCore, materials_and_vendors


@pytest.fixture(autouse=True)
def clean(db: Session) -> Iterator[None]:
    for table in (OntologyRelation, OntologyObject, OntologySyncRun, OntologyType):
        db.execute(delete(table))
    db.commit()
    yield


@pytest.fixture
def core(monkeypatch: pytest.MonkeyPatch) -> FakeCore:
    """설정이 있는 설치 — 가짜 SP 에 붙고, 「지금 받기」 는 요청 안에서 끝까지 돈다."""
    fake = materials_and_vendors()
    monkeypatch.setattr(services, "configured", lambda settings=None: True)
    monkeypatch.setattr(services, "make_client", lambda settings=None: fake.client())

    def inline(work: Callable[[], None]) -> None:
        work()

    monkeypatch.setattr(services, "spawn", inline)
    return fake


def _sync(client: TestClient, who: Signed, **body: Any) -> Any:
    response = client.post("/api/ontology/sync", json=body, headers=who.headers)
    assert response.status_code == 202, response.text
    return response.json()


def test_설정이_없으면_무엇을_적어야_하는지_말한다(
    client: TestClient, admin: Signed, member: Signed
) -> None:
    status = client.get("/api/ontology/status", headers=member.headers).json()
    assert status["configured"] is False and status["next_due_at"] is None
    refused = client.post("/api/ontology/sync", json={}, headers=admin.headers)
    assert refused.status_code == 400
    assert refused.json()["error"]["code"].endswith("ONTOLOGY-0001")
    assert "ONTOLOGY_SOURCE_URL" in refused.json()["error"]["message"]


def test_지금_받기는_받은_것과_기록을_남긴다(
    client: TestClient, admin: Signed, core: FakeCore
) -> None:
    run = _sync(client, admin)
    assert run["trigger"] == "manual"
    status = client.get("/api/ontology/status", headers=admin.headers).json()
    last = status["last_run"]
    assert last["status"] == "ok" and last["actor_name"] == "admin"
    assert last["summary"]["types"]["material"]["created"] == 3
    assert (status["types"], status["objects"], status["relations"]) == (2, 5, 2)
    assert status["revision"] == "1-aaaa" and status["running"] is None

    runs = client.get("/api/ontology/runs", headers=admin.headers).json()
    assert [one["status"] for one in runs] == ["ok"]


def test_받은_타입_객체_선을_본다(
    client: TestClient, admin: Signed, member: Signed, core: FakeCore
) -> None:
    _sync(client, admin)
    types = {
        one["slug"]: one
        for one in client.get("/api/ontology/types", headers=member.headers).json()
    }
    material = types["material"]
    assert material["label"] == "재료" and material["source_count"] == 3
    assert (material["active_count"], material["relation_count"]) == (3, 2)
    assert [one["key"] for one in material["properties"]] == ["density", "supplier"]
    assert material["properties"][1]["ref_type_slug"] == "vendor"

    found = client.get(
        "/api/ontology/types/material/objects", params={"q": "스테인"}, headers=member.headers
    ).json()
    assert found["total"] == 1 and found["items"][0]["key"] == "SUS304"

    detail = client.get(
        "/api/ontology/types/material/object", params={"key": "SS400"}, headers=member.headers
    ).json()
    assert detail["properties"]["supplier"] == "ACME-001"
    assert [
        (one["relation"], one["dst_key"], one["dst_label"]) for one in detail["outgoing"]
    ] == [("supplied_by", "ACME-001", "ACME 정밀")]
    vendor = client.get(
        "/api/ontology/types/vendor/object", params={"key": "ACME-001"}, headers=member.headers
    ).json()
    assert [(one["src_key"], one["src_label"]) for one in vendor["incoming"]] == [
        ("SS400", "일반구조용강")
    ]
    missing = client.get(
        "/api/ontology/types/material/object", params={"key": "없음"}, headers=member.headers
    )
    assert missing.status_code == 404


def test_지운_것은_기본으로_숨기고_원하면_함께_본다(
    client: TestClient, admin: Signed, core: FakeCore
) -> None:
    _sync(client, admin)
    core.delete("material", "AL6061", merged_into="SS400")
    _sync(client, admin)
    shown = client.get("/api/ontology/types/material/objects", headers=admin.headers).json()
    assert {one["key"] for one in shown["items"]} == {"SS400", "SUS304"}
    every = client.get(
        "/api/ontology/types/material/objects",
        params={"include_inactive": True},
        headers=admin.headers,
    ).json()
    gone = next(one for one in every["items"] if one["key"] == "AL6061")
    assert (gone["active"], gone["removed_reason"], gone["merged_into"]) == (
        False,
        "merged",
        "SS400",
    )


def test_받나는_시스템_관리자만_끄고_켠다(
    client: TestClient, admin: Signed, member: Signed, core: FakeCore
) -> None:
    _sync(client, admin)
    blocked = client.patch(
        "/api/ontology/types/vendor", json={"enabled": False}, headers=member.headers
    )
    assert blocked.status_code == 403
    assert (
        client.post("/api/ontology/sync", json={}, headers=member.headers).status_code == 403
    )

    turned = client.patch(
        "/api/ontology/types/vendor", json={"enabled": False}, headers=admin.headers
    ).json()
    assert turned["enabled"] is False and turned["active_count"] == 2
    core.calls.clear()
    _sync(client, admin)
    assert not any(path.startswith("/api/core/vendor") for path, _ in core.calls)


def test_도는_중이면_하나_더_걸지_않는다(
    client: TestClient, admin: Signed, db: Session, core: FakeCore
) -> None:
    db.add(OntologySyncRun(trigger="timer", status="running"))
    db.commit()
    refused = client.post("/api/ontology/sync", json={}, headers=admin.headers)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"].endswith("ONTOLOGY-0002")


def test_참조_칸은_가리키는_객체의_이름을_함께_준다(
    client: TestClient, admin: Signed, core: FakeCore
) -> None:
    """참조 칸의 값은 상대의 `key` 다(재료의 공급사 = `ACME-001`). 그 타입도 받아 두었으면
    이름을 함께 준다. 상대의 식별자가 나중에 바뀌어도 이미 받은 값은 다시 오지 않으므로 옛
    식별자로 남는다 — 그것도 `previous_keys` 로 풀어 찾는다(지침서 §4.2 규칙 10)."""
    _sync(client, admin)
    listed = client.get("/api/ontology/types/material/objects", headers=admin.headers).json()
    steel = next(one for one in listed["items"] if one["key"] == "SS400")
    assert steel["ref_labels"] == {"ACME-001": "ACME 정밀"}

    core.rename("vendor", "ACME-001", "ACME-100")
    _sync(client, admin)
    detail = client.get(
        "/api/ontology/types/material/object", params={"key": "SS400"}, headers=admin.headers
    ).json()
    assert detail["properties"]["supplier"] == "ACME-001"
    assert detail["ref_labels"] == {"ACME-001": "ACME 정밀"}
