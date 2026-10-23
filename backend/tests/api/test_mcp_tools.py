"""MCP 도구를 **진짜 앱에 붙여** 본다 — 붙여 보기 전에 도는지 아는 유일한 방법.

`mcp_server/server.py` 는 한 파일이고 `mcp` 패키지를 쓴다. 그 패키지를 백엔드 환경에 깔면
`starlette.testclient` 의 HTTP 스택이 바뀌어 다른 시험이 흔들리므로(Standard Platform 이
실측으로 겪었다), 여기서는 **가짜 `mcp` 를 끼워** 도구 함수만 꺼낸다. 도구는 백엔드에 `httpx`
로 말하고, 그 자리를 이 프로세스 안의 앱(ASGI)으로 돌린다 — **라우터 · 권한 · 범위 · 검증이
통째로 돈다**(서비스 함수를 직접 부르면 그것이 전부 빠진다).

**규칙이 두 벌이 아닌지도 여기서 본다.** 서버가 막는 것을 MCP 가 통과시키면 「MCP 로는 되는데
화면에서는 안 되는」 상태가 되고, 그때 어느 쪽이 맞는지 알 방법이 없다.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import sys
import types
import uuid
from collections.abc import Callable, Coroutine, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.main import app as fastapi_app
from app.modules.auth import security
from app.modules.workspaces.models import Workspace
from tests.api.conftest import Signed, _login, _make_user

SERVER_PY = Path(__file__).resolve().parents[3] / "mcp_server" / "server.py"
DOE_FOLDER = (
    Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "브래킷_두께훑기-3f9a2177"
)
MODAL: dict[str, Any] = {
    "recipe": "modal",
    "material": {
        "name": "SS400",
        "youngs_modulus_gpa": 200,
        "poisson_ratio": 0.3,
        "density_kg_m3": 7850,
    },
    "material_from": "spec",
    "modes": 5,
    "mesh": {"element_size_mm": 5},
}


class _FakeFastMCP:
    """`FastMCP` 의 자리 — 도구 등록을 **그냥 통과**시킨다. 여기서 보는 것은 등록이 아니라
    도구가 백엔드에 무엇을 보내고 무엇을 돌려주는가다."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.settings = SimpleNamespace()

    def tool(self) -> Callable[[Any], Any]:
        return lambda function: function


def _load_server() -> Any:
    fake = types.ModuleType("mcp.server.fastmcp")
    fake.FastMCP = _FakeFastMCP  # type: ignore[attr-defined]
    fake.Context = object  # type: ignore[attr-defined]
    for name in ("mcp", "mcp.server"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["mcp.server.fastmcp"] = fake
    spec = importlib.util.spec_from_file_location("mcp_server_under_test", SERVER_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = _load_server()


class ToolError(RuntimeError):
    """도구가 돌려준 `{"error": ...}` — 서버의 말 그대로."""


class Bot:
    """개인 토큰 하나로 도구를 부르는 손 — Claude 가 MCP 에 붙는 그 자격이다."""

    def __init__(self, token: str) -> None:
        request = SimpleNamespace(headers={"authorization": f"Bearer {token}"})
        self.ctx = SimpleNamespace(request_context=SimpleNamespace(request=request))

    def call(
        self, tool: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kw: Any
    ) -> Any:
        got = asyncio.run(tool(self.ctx, *args, **kw))
        if isinstance(got, dict) and "error" in got:
            raise ToolError(str(got["error"]))
        return got

    def refused(
        self, tool: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kw: Any
    ) -> str:
        got = asyncio.run(tool(self.ctx, *args, **kw))
        assert isinstance(got, dict) and "error" in got, got
        return str(got["error"])


def _bot(client: TestClient, who: Signed, scopes: list[str]) -> Bot:
    made = client.post(
        "/api/auth/tokens",
        json={"name": f"claude-{uuid.uuid4().hex[:8]}", "scopes": scopes},
        headers=who.headers,
    )
    assert made.status_code == 201, made.text
    return Bot(made.json()["token"])


@pytest.fixture(autouse=True)
def in_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # 도구의 httpx 를 이 프로세스 안의 앱으로 돌린다. 진짜 HTTP 스택을 타되 소켓은 없다.
    # 해석은 그 요청 안에서 끝까지 돈다(시험에는 워커 프로세스가 없다 — 모의 실행기).
    monkeypatch.setattr(get_settings(), "jobs_inline", True)
    server._TRANSPORT = httpx.ASGITransport(app=fastapi_app)
    try:
        yield
    finally:
        server._TRANSPORT = None


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """시험마다 새 스터디 — 같은 스터디를 두 번 가져오면 「이미 가져온 점」 으로 막힌다."""
    made = tmp_path / DOE_FOLDER.name
    shutil.copytree(DOE_FOLDER, made)
    study = json.loads((made / "study.json").read_text(encoding="utf-8"))
    study["id"] = uuid.uuid4().hex
    (made / "study.json").write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "doe_roots", str(tmp_path))
    return made


@pytest.fixture
def other(client: TestClient, db: Session, workspace: Workspace) -> Signed:
    user = _make_user(db, workspace, label="other", is_system_admin=False, role="member")
    return Signed(email=user.email, token=_login(client, user.email), workspace=workspace.slug)


def test_폴더를_훑고_걸고_결과를_읽고_견준다(
    client: TestClient, member: Signed, folder: Path
) -> None:
    """Claude 가 하는 한 바퀴 — 폴더 → 미리 보기 → 걸기 → 기다리기 → 결과 → 설계점 비교."""
    bot = _bot(client, member, ["read", "simulations:write"])

    listing = bot.call(server.folder_browse)
    assert any(one["name"] == folder.name and one["is_study"] for one in listing["entries"])
    # 사용자는 경로를 모른다 — CompCore 의 스터디 id 앞 8자리로 찾는다.
    study_id = json.loads((folder / "study.json").read_text(encoding="utf-8"))["id"]
    found = bot.call(server.folder_find, study_id[:8])["found"]
    assert [one["path"] for one in found] == [str(folder)]
    preview = bot.call(server.folder_preview, found[0]["path"])
    assert preview["usable"] == 3 and preview["skipped"] == 1
    point = bot.call(server.folder_preview, str(folder), number=1, recipe="modal")
    assert point["recipe"] == "modal" and "conditions" in point

    schema = bot.call(server.recipe_schema)
    assert {one["name"] for one in schema["recipes"]} == {"modal", "static", "harmonic"}

    made = bot.call(server.jobs_create, MODAL, path=str(folder), numbers=[1, 2])
    assert len(made["created"]) == 2
    job_id = made["created"][0]

    job = bot.call(server.job_get, job_id, wait_seconds=5)
    assert job["status"] == "done" and job["study_id"] == made["study_id"]
    assert "job_result" in job["next"] and "result_json" in job["artifacts"]

    result = bot.call(server.job_result, job_id)
    assert result["recipe"] == "modal" and len(result["frequencies"]) == 5
    assert [one["elastic_number"] for one in result["modes"]] == [1, 2, 3, 4, 5]
    assert result["modes"][0]["frequency_hz"] == result["first_elastic_hz"]

    # CompCore 의 doe_export 가 준 study_id 를 그대로 — 남은 점 하나를 그 길로 건다.
    by_id = bot.call(server.jobs_create, MODAL, study_id=study_id[:8], numbers=[3])
    assert by_id["folder"] == str(folder) and len(by_id["created"]) == 1

    mine = bot.call(server.jobs_list, scope="mine", status="done")
    assert {one["id"] for one in mine["items"]} >= set(made["created"])

    study = bot.call(server.study_get, made["study_id"])
    assert sorted(one["number"] for one in study["points"]) == [1, 2, 3]
    assert all(one["frequencies"] for one in study["points"])

    # **견주는 셈은 서버가 한다** — 민감도 · 조건을 건 최적점(화면 「다변수」 탭과 같은 표).
    analyzed = bot.call(
        server.study_analyze, made["study_id"], objective="mass_kg", where=["factor:두께>=0"]
    )
    assert analyzed["done"] == 3 and "effects" not in analyzed
    assert analyzed["choice"]["feasible"] == 3
    said = bot.refused(server.study_analyze, made["study_id"], result="무게")
    assert "쓸 수 있는 열" in said
    # 서버 상태 — 멤버는 솔버 요약만(워커 상세는 시스템 관리자).
    status = bot.call(server.server_status)
    assert "solvers" in status and "workers" not in status


def test_게시해야_남의_Claude_가_보고_고치지는_못한다(
    client: TestClient, member: Signed, other: Signed, folder: Path
) -> None:
    """MCP 가 권한을 따로 판단하지 않는다 — 건 사람의 것 · 게시해야 남이 본다(ADR 0008)가
    그대로."""
    mine = _bot(client, member, ["read", "simulations:write"])
    theirs = _bot(client, other, ["read", "simulations:write"])
    made = mine.call(server.jobs_create, MODAL, path=str(folder), numbers=[1])
    job_id = made["created"][0]

    assert "SIMULATIONS" in theirs.refused(server.job_get, job_id)
    assert theirs.call(server.jobs_list, scope="published")["items"] == [] or job_id not in {
        one["id"] for one in theirs.call(server.jobs_list, scope="published")["items"]
    }

    published = mine.call(server.job_publish, job_id)
    assert published["published"] is True
    assert theirs.call(server.job_result, job_id)["recipe"] == "modal"
    assert job_id in {
        one["id"] for one in theirs.call(server.jobs_list, scope="published")["items"]
    }
    # 남의 게시 결과는 읽기만 — 서버의 말이 그대로 온다.
    assert theirs.refused(server.job_retry, job_id)
    assert theirs.refused(server.job_publish, job_id, unpublish=True)
    assert theirs.refused(server.convergence_start, job_id)

    assert mine.call(server.job_publish, job_id, unpublish=True)["published"] is False
    assert theirs.refused(server.job_get, job_id)


def test_쓰기_범위가_없는_토큰은_읽기만_한다(
    client: TestClient, member: Signed, folder: Path
) -> None:
    """범위는 백엔드가 본다 — MCP 는 그 말을 그대로 전한다."""
    reader = _bot(client, member, ["read"])
    assert reader.call(server.folder_preview, str(folder))["usable"] == 3
    said = reader.refused(server.jobs_create, MODAL, path=str(folder), numbers=[1])
    assert "simulations:write" in said


def test_수렴_점검과_실측을_도구로_건다(
    client: TestClient, member: Signed, folder: Path
) -> None:
    bot = _bot(client, member, ["read", "simulations:write"])
    made = bot.call(server.jobs_create, MODAL, path=str(folder), numbers=[1, 2, 3])
    job_id = made["created"][0]

    started = bot.call(server.convergence_start, job_id)
    assert len(started["levels"]) >= 3
    assert bot.call(server.convergence_get, job_id)["levels"]

    frequency = bot.call(server.job_result, job_id)["first_elastic_hz"]
    table = f"측정점,종류,주파수\n,공진,{frequency * 1.02:.1f}\n"
    added = bot.call(
        server.measurement_add, table, study_id=made["study_id"], label="1차 시험"
    )
    assert added["label"] == "1차 시험"
    compared = bot.call(server.measurements_get, study_id=made["study_id"])
    assert compared["total"] == 1 and compared["measurements"][0]["best_point"] in {1, 2, 3}


def test_토큰이_거절되면_게이트웨이가_다시_받는_신호로_실패한다(client: TestClient) -> None:
    """회수된 위임 토큰 — 결과가 아니라 예외(`<METHOD> <경로> → HTTP 401`)라야 게이트웨이가
    새로 받아 한 번 다시 부른다."""
    stale = Bot(f"{security.pat_prefix()}revoked")
    with pytest.raises(server.BackendUnauthorized) as caught:
        asyncio.run(server.jobs_list(stale.ctx))
    assert str(caught.value).startswith("GET /api/simulations → HTTP 401: ")
