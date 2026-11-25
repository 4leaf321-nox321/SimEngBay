"""풀 곳 고르기(요청서 E-2) — **지금 이 사람이 STE 를 고를 수 있나**, 못 고르면 까닭.

`GET /simulations/solve-places` 는 STE 를 그 사람 명의로 물어 본다(가짜 STE —
`tests/fake_ste.py`). STE 가 안 돼 실패한 작업은 「이 서버에서 다시」(`retry` 의 `solve_on`)로
풀 곳을 바꿔 다시 건다.
"""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.calculix import ste
from app.modules.simulations import services
from app.modules.simulations.models import Simulation
from tests.api.conftest import Signed
from tests.fake_ste import CLIENT, FakeSte

STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
SPEC = {
    "recipe": "modal",
    "material": {
        "name": "SS400",
        "youngs_modulus_gpa": 200,
        "poisson_ratio": 0.3,
        "density_kg_m3": 7850,
    },
    "material_from": "spec",
    "mesh": {"element_size_mm": 5},
}


@pytest.fixture(autouse=True)
def clean(db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    monkeypatch.setattr(get_settings(), "ste_token_dir", str(tmp_path / "tokens"))
    services._probes.clear()
    yield
    services._probes.clear()
    db.rollback()
    for row in db.scalars(select(Simulation).where(Simulation.status == "queued")):
        row.status = "canceled"
    db.commit()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeSte:
    made = FakeSte(secrets_by_client={CLIENT: "ste-secret"})
    monkeypatch.setattr(ste, "TRANSPORT", httpx.MockTransport(made.handle))
    monkeypatch.setattr(get_settings(), "ste_base_url", "http://ste.test/ste")
    monkeypatch.setattr(get_settings(), "ste_sso_secret", "ste-secret")
    return made


def _places(client: TestClient, who: Signed) -> dict[str, dict[str, Any]]:
    response = client.get("/api/simulations/solve-places", headers=who.headers)
    assert response.status_code == 200, response.text
    return {row["place"]: row for row in response.json()}


def _queue(client: TestClient, who: Signed, spec: dict[str, Any]) -> uuid.UUID:
    response = client.post(
        "/api/simulations",
        data={"spec": json.dumps(spec), "workspace_slug": who.workspace},
        files={"file": ("브래킷.step", io.BytesIO(STEP), "model/step")},
        headers=who.headers,
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


def test_설정이_없으면_STE_는_까닭과_함께_못_고른다(
    client: TestClient, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "ste_sso_secret", "")
    places = _places(client, member)
    assert places["local"]["available"] is True
    assert places["ste"]["available"] is False
    assert "설정돼 있지 않습니다" in places["ste"]["reason"]


def test_그_사람_명의로_물어_대기열을_보인다(
    client: TestClient, member: Signed, fake: FakeSte
) -> None:
    ste_place = _places(client, member)["ste"]
    assert ste_place["available"] is True and ste_place["reason"] is None
    assert ste_place["queue"]["cpus_idle"] == 2944 - 2722, "남은 코어를 셈한다"
    assert ste_place["queue"]["partition"] == "alpha"
    assert ste_place["queue"]["mine_pending"] == 0
    assert fake.mints == [(member.email, CLIENT)], "그 사람 명의로"
    # 30초 안에는 다시 묻지 않는다.
    asked = len(fake.requests)
    _places(client, member)
    assert len(fake.requests) == asked


def test_STE_가_그_사람을_거절하면_그_문장을_보인다(
    client: TestClient, member: Signed, fake: FakeSte
) -> None:
    fake.denied[member.email] = "STE 사용 권한이 없습니다 — 포털에서 STE 권한을 청하세요"
    ste_place = _places(client, member)["ste"]
    assert ste_place["available"] is False
    assert "포털에서 STE 권한을 청하세요" in ste_place["reason"]


def test_STE_가_응답하지_않으면_못_고른다(
    client: TestClient, member: Signed, fake: FakeSte
) -> None:
    fake.fault("sso", 503)
    ste_place = _places(client, member)["ste"]
    assert ste_place["available"] is False
    assert "503" in ste_place["reason"]


def test_대기열_길이_없는_STE_도_고를_수는_있다(
    client: TestClient, member: Signed, fake: FakeSte
) -> None:
    fake.cluster = None
    ste_place = _places(client, member)["ste"]
    assert ste_place["available"] is True and ste_place["queue"] is None


def test_STE_가_안_되면_이_서버에서_다시_건다(
    client: TestClient, db: Session, member: Signed, fake: FakeSte
) -> None:
    job = _queue(client, member, {**SPEC, "solve_on": "ste"})
    row = db.get(Simulation, job)
    assert row is not None
    row.status = "failed"
    row.error_code = "ste_unavailable"
    db.commit()

    again = client.post(
        f"/api/simulations/{job}/retry", json={"solve_on": "local"}, headers=member.headers
    )
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["status"] == "queued"
    assert "solve_on" not in body["spec"]
    db.expire_all()
    row = db.get(Simulation, job)
    assert row is not None and row.work_dir is not None
    stored = json.loads(
        (services.work_root() / row.work_dir / "spec.json").read_text(encoding="utf-8")
    )
    assert "solve_on" not in stored, "자식이 읽는 spec.json 도 바뀐다"
    [change] = row.source_meta["solve_on_changes"]
    assert (change["from"], change["to"]) == ("ste", "local")


def test_몸통_없는_다시_걸기는_그대로다(
    client: TestClient, db: Session, member: Signed, fake: FakeSte
) -> None:
    job = _queue(client, member, {**SPEC, "solve_on": "ste"})
    row = db.get(Simulation, job)
    assert row is not None
    row.status = "failed"
    db.commit()
    again = client.post(f"/api/simulations/{job}/retry", headers=member.headers)
    assert again.status_code == 200, again.text
    assert again.json()["spec"]["solve_on"] == "ste"


def test_Ansys_작업은_STE_로_옮기지_못한다(
    client: TestClient, db: Session, member: Signed, fake: FakeSte
) -> None:
    job = _queue(client, member, {**SPEC, "solver": "ansys"})
    row = db.get(Simulation, job)
    assert row is not None
    row.status = "failed"
    db.commit()
    moved = client.post(
        f"/api/simulations/{job}/retry", json={"solve_on": "ste"}, headers=member.headers
    )
    assert moved.status_code == 400
    assert moved.json()["error"]["code"].endswith("SIMULATIONS-0042")
