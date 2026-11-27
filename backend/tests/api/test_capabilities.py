"""능력표 API — CompCore 가 관리 화면에서 부르는 자리(CompCore 해석-확장-설계 5장). 신원을 보고
(PAT 읽기 범위로 된다), 솔버마다 한 장이다. 조화 응답의 선응력은 작업을 만들 때 막는다.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import capabilities, contract
from app.modules.simulations import services
from app.modules.simulations.models import SimulationWorker
from app.version import current
from tests.api.conftest import Signed

DOE = Path(__file__).resolve().parents[1] / "fixtures" / "doe"
SWEEP = DOE / "조건_사인스윕" / "points" / "p0001.json"
STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


@pytest.fixture(autouse=True)
def queued(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", False)


def test_솔버마다_한_장을_낸다(client: TestClient, member: Signed) -> None:
    got = client.get("/api/simulations/capabilities", headers=member.headers)
    assert got.status_code == 200, got.text
    tables = got.json()
    assert [one["solver"] for one in tables] == list(capabilities.SOLVERS)
    for one in tables:
        assert one["receiver"] == get_settings().app_slug
        assert one["receiver_version"] == current()
        assert one["contract"] == list(contract.VERSIONS)
        assert list(one["analyses"]) == list(capabilities.RECIPES)
        assert one["analyses"] == capabilities.analyses(one["solver"])
    ansys = next(one for one in tables if one["solver"] == "ansys")
    version = get_settings().ansys_version
    assert ansys["version"] == f"20{version // 10} R{version % 10}"
    assert next(one for one in tables if one["solver"] == "calculix")["version"] is None


def test_한_솔버만_고른다(client: TestClient, member: Signed) -> None:
    got = client.get(
        "/api/simulations/capabilities", params={"solver": "ansys"}, headers=member.headers
    )
    assert got.status_code == 200, got.text
    assert [one["solver"] for one in got.json()] == ["ansys"]
    wrong = client.get(
        "/api/simulations/capabilities", params={"solver": "abaqus"}, headers=member.headers
    )
    assert wrong.status_code == 200, "모르는 솔버도 꼴은 배열이다(빈 배열)"
    assert wrong.json() == []


def test_신원을_보고_읽기_범위_토큰으로_된다(client: TestClient, admin: Signed) -> None:
    assert client.get("/api/simulations/capabilities").status_code == 401
    made = client.post(
        "/api/auth/tokens", json={"name": "CompCore 능력표"}, headers=admin.headers
    )
    assert made.status_code == 201, made.text
    assert made.json()["pat"]["scopes"] == ["read"]
    with_pat = {"Authorization": f"Bearer {made.json()['token']}"}
    assert client.get("/api/simulations/capabilities", headers=with_pat).status_code == 200


def _prestressed_sweep() -> bytes:
    payload: dict[str, Any] = json.loads(SWEEP.read_text(encoding="utf-8"))
    payload["conditions"]["analysis"]["prestressed"] = True
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("solver", ["calculix", "ansys"])
def test_조화의_선응력은_작업을_만들_때_막는다(
    client: TestClient, member: Signed, solver: str
) -> None:
    refused = client.post(
        "/api/simulations",
        data={
            "spec": json.dumps({"recipe": "harmonic", "solver": solver}),
            "workspace_slug": member.workspace,
        },
        files={
            "file": ("p0001.step", io.BytesIO(STEP), "model/step"),
            "topology": ("p0001.json", io.BytesIO(_prestressed_sweep()), "application/json"),
        },
        headers=member.headers,
    )
    assert refused.status_code == 400, refused.text
    error = refused.json()["error"]
    assert error["code"].endswith("SIMULATIONS-0030"), error
    assert "조화 응답은 선응력을 받지 않습니다" in error["message"]


def test_CalculiX_판은_살아_있는_워커들이_잰_ccx_판이_하나일_때만(
    client: TestClient, db: Session, member: Signed
) -> None:
    """요청마다 ccx 를 부르지 않는다 — 워커가 기동 때 잰 판(`toolcheck.ccx_version`)을 모은다.
    워커가 여럿이고 판이 갈리면 모른다(비운다)."""
    names = ["cap-worker:1", "cap-worker:2"]
    try:
        services.beat(
            db, names[0], state="idle", solvers=["calculix"], tools={"ccx_version": "2.21"}
        )
        shown = client.get(
            "/api/simulations/capabilities",
            params={"solver": "calculix"},
            headers=member.headers,
        ).json()
        assert shown[0]["version"] == "2.21"
        services.beat(
            db, names[1], state="idle", solvers=["calculix"], tools={"ccx_version": "2.22"}
        )
        mixed = client.get(
            "/api/simulations/capabilities",
            params={"solver": "calculix"},
            headers=member.headers,
        ).json()
        assert mixed[0]["version"] is None
    finally:
        for name in names:
            row = db.get(SimulationWorker, name)
            if row is not None:
                db.delete(row)
        db.commit()
