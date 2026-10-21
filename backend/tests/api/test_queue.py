"""해석 작업의 줄 — **사람마다 번갈아 집고, 대기 중이면 어디쯤인지 말한다**(ADR 0011).

먼저 건 순서로만 집으면 DOE 200점을 먼저 건 사람 뒤에서 한 건을 건 사람이 200건을 기다린다.
MCP 로 AI 가 DOE 를 통째로 걸기 쉬워져 그 일이 실제로 생긴다.

시험 DB 는 스위트 전체가 함께 쓴다 — 다른 시험이 남긴 대기 · 도는 작업이 섞이면 순서와 수를 볼
수 없으므로, 이 파일의 시험은 시작할 때 그것들을 멈춤으로 돌려 빈 줄에서 시작한다.
"""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modules.simulations import services
from app.modules.simulations.models import RUNNING_STATUSES, Simulation
from app.modules.workspaces.models import Workspace
from tests.api.conftest import Signed, _login, _make_user

STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
CALCULIX: dict[str, Any] = {
    "recipe": "modal",
    "solver": "calculix",
    "material": {
        "name": "SS400",
        "youngs_modulus_gpa": 200,
        "poisson_ratio": 0.3,
        "density_kg_m3": 7850,
    },
    "material_from": "spec",
    "mesh": {"element_size_mm": 5},
}


def _cancel_waiting(db: Session) -> None:
    db.execute(
        update(Simulation)
        .where(Simulation.status.in_(("queued", *RUNNING_STATUSES)))
        .values(status="canceled")
    )
    db.commit()


@pytest.fixture(autouse=True)
def empty_queue(db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """요청 안에서 돌리지 않고(작업이 대기에 남게), 남이 남긴 대기 · 도는 작업은 치운다 —
    **끝날 때도.** 여기서 남긴 대기 작업을 다음 파일의 시험(「워커는 제 솔버의 작업만
    집는다」)이 먼저 집었다(전체 시험에서만 드러났다)."""
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    _cancel_waiting(db)
    yield
    _cancel_waiting(db)


@pytest.fixture
def other(client: TestClient, db: Session, workspace: Workspace) -> Signed:
    user = _make_user(db, workspace, label="other", is_system_admin=False, role="member")
    return Signed(email=user.email, token=_login(client, user.email), workspace=workspace.slug)


def _queue(client: TestClient, who: Signed) -> str:
    response = client.post(
        "/api/simulations",
        data={"spec": json.dumps(CALCULIX), "workspace_slug": who.workspace},
        files={"file": ("브래킷.step", io.BytesIO(STEP), "model/step")},
        headers=who.headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _claim(db: Session, worker: str = "w1") -> str:
    picked = services.claim_next(db, worker, solvers=("calculix",))
    assert picked is not None
    return str(picked.id)


def _finish(db: Session, ident: str) -> None:
    db.execute(
        update(Simulation).where(Simulation.id == uuid.UUID(ident)).values(status="done")
    )
    db.commit()


def test_워커가_하나여도_사람마다_번갈아_집는다(
    client: TestClient, db: Session, member: Signed, other: Signed
) -> None:
    """먼저 많이 건 사람의 작업이 끝날 때마다 다음 차례는 아직 못 받은 사람에게 간다 — 같은
    사람의 작업끼리는 먼저 건 순서."""
    first = [_queue(client, member) for _ in range(3)]
    late = _queue(client, other)

    picked = _claim(db)
    assert picked == first[0]  # 둘 다 아직 못 받았다 — 먼저 건 것
    _finish(db, picked)
    picked = _claim(db)
    assert picked == late  # 방금 받은 사람 말고 — 먼저 건 200건 뒤에 서지 않는다
    _finish(db, picked)
    assert _claim(db) == first[1]


def test_워커가_여럿이면_도는_작업이_적은_사람부터(
    client: TestClient, db: Session, member: Signed, other: Signed
) -> None:
    first = [_queue(client, member) for _ in range(2)]
    late = _queue(client, other)
    assert _claim(db, "w1") == first[0]
    # 첫 사람의 작업이 돌고 있다 — 두 번째 워커는 다른 사람의 것을 집는다.
    assert _claim(db, "w2") == late
    assert _claim(db, "w3") == first[1]


def test_대기_중이면_줄의_어디쯤인지_말한다(
    client: TestClient, db: Session, member: Signed, other: Signed
) -> None:
    """「대기」 만 보이면 사람도 AI 도 얼마나 기다릴지 모른다 — 같은 솔버의 대기 · 내 앞의 내
    작업 · 줄을 나눠 쓰는 사람 수 · 도는 것."""
    mine = [_queue(client, member) for _ in range(3)]
    _queue(client, other)
    running = _claim(db)  # 첫 작업이 돈다

    got = client.get(f"/api/simulations/{mine[2]}", headers=member.headers).json()
    queue = got["queue"]
    assert queue["solver"] == "calculix"
    assert (queue["queued"], queue["mine_ahead"], queue["people"]) == (3, 1, 2)
    assert queue["running"] == 1
    # 돌기 시작하면 줄에 없다.
    assert (
        client.get(f"/api/simulations/{running}", headers=member.headers).json()["queue"]
        is None
    )
