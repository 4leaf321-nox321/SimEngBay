"""어댑터가 서는가 — **`mcp` 가 API 를 바꾸면 여기서 걸린다.**

이 시험만 따로 도는 이유: `mcp` 를 백엔드 개발 환경에 깔면 `starlette.testclient` 가 쓰는 HTTP
스택이 바뀌어 그쪽 시험이 흔들린다(Standard Platform 이 실측으로 겪었다). 그래서 **환경을
가른다.**

    cd mcp_server && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt pytest
    cd .. && mcp_server/venv/bin/python -m pytest mcp_server/tests

진짜 앱에 붙여 보는 시험은 백엔드 쪽에 있다(`backend/tests/api/test_mcp_tools.py`). 여기서는
**헤더가 그대로 건너가는가, 오류가 서버의 말을 잃지 않는가, 401 이 게이트웨이의 다시 받기
신호 모양인가, 도구가 어느 경로로 무엇을 보내는가, 안내서가 읽히는가**를 본다 — 백엔드 없이
확인할 수 있는 전부다.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import server

TOOLS = {
    "get_guide",
    "whoami",
    "recipe_schema",
    "folder_find",
    "folder_browse",
    "folder_preview",
    "jobs_create",
    "jobs_list",
    "jobs_folders",
    "jobs_move",
    "job_get",
    "job_result",
    "job_retry",
    "job_cancel",
    "job_publish",
    "studies_list",
    "study_get",
    "study_publish",
    "study_analyze",
    "study_cancel",
    "study_rerun",
    "server_status",
    "files_tidy",
    "convergence_start",
    "convergence_get",
    "measurements_get",
    "measurement_add",
}

REQUEST_TEMPLATE = (
    Path(__file__).resolve().parents[2] / "docs" / "[참고] HWAX포탈_연동_요청서.md"
)


def _ctx(authorization: str | None) -> Any:
    """들어온 MCP HTTP 요청 흉내 — `_forward_headers` 가 보는 것은 헤더뿐이다."""
    headers = {"authorization": authorization} if authorization else {}
    request = SimpleNamespace(headers=headers)
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


def _serve(handler: Any) -> list[httpx.Request]:
    """가짜 백엔드. 받은 요청을 모아 두고 handler 의 응답을 돌려준다."""
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    server._TRANSPORT = httpx.MockTransport(respond)
    return seen


def _route(table: dict[tuple[str, str], Any]) -> list[httpx.Request]:
    """경로마다 다른 응답 — (메서드, 경로) → JSON. 없는 것은 404 봉투."""

    def respond(request: httpx.Request) -> httpx.Response:
        found = table.get((request.method, request.url.path))
        if found is None:
            return httpx.Response(404, json={"error": {"code": "X", "message": "없음"}})
        return httpx.Response(200, json=found)

    return _serve(respond)


def _run(tool: Any, *args: Any, **kwargs: Any) -> Any:
    return asyncio.run(tool(_ctx("Bearer t"), *args, **kwargs))


def test_도구가_그대로_선다() -> None:
    """도구 이름은 안내문 · 안내서 · 요청서가 함께 부르는 이름이다 — 하나 빠지면 안내가 없는
    도구를 가리킨다."""
    listed = asyncio.run(server.mcp.list_tools())
    assert {one.name for one in listed} == TOOLS


def test_안내문과_안내서가_가리키는_도구는_다_있다() -> None:
    """안내가 이름을 바꾼 도구를 가리키면 모델은 없는 도구를 부르려다 헤맨다."""
    # 「하려는 일 → 부를 것」 표의 줄(두 칸 들여 쓴 줄) — 도구가 아닌 밑줄 이름은 인자뿐이다.
    # 표 밖의 글은 CompCore 의 도구(`doe_export`)와 칸(`study_id`)도 말한다.
    rows = "\n".join(
        line for line in server.INSTRUCTIONS.splitlines() if line.startswith("  ")
    )
    in_table = set(re.findall(r"\b[a-z]+_[a-z_]+\b", rows))
    assert in_table - {"wait_seconds", "study_id"} <= TOOLS, in_table - TOOLS
    _version, sections = server._guide_sections()
    called = set(re.findall(r"\b([a-z]+_[a-z_]+)\(", "\n".join(sections.values())))
    assert called and called <= TOOLS, called - TOOLS


def test_토큰을_그대로_건넨다() -> None:
    """**만능 토큰이 없다.** 들어온 Authorization 을 그대로 백엔드에 넘기므로 같은 서버를
    여러 사람이 각자 권한으로 쓴다."""
    seen = _serve(lambda _r: httpx.Response(200, json={"email": "a@x"}))
    got = asyncio.run(server.whoami(_ctx("Bearer abc")))
    assert got == {"email": "a@x"}
    assert seen[0].headers["authorization"] == "Bearer abc"
    assert seen[0].url.path == "/api/auth/me"


def test_서버의_말을_그대로_전한다() -> None:
    """오류 문구에 무엇을 고쳐야 하는지가 적혀 있다 — 여기서 고쳐 쓰면 그것을 잃는다."""
    _serve(
        lambda _r: httpx.Response(
            400,
            json={
                "error": {
                    "code": "SEB-SIMULATIONS-0031",
                    "message": (
                        "CalculiX 로는 못 거는 조건이 있습니다: 구속 「바닥」(elastic_support)"
                    ),
                    "details": {"solver": "calculix"},
                }
            },
        )
    )
    got = _run(server.jobs_create, {"recipe": "modal"}, path="/data/doe/a")
    assert got == {
        "error": "[SEB-SIMULATIONS-0031] CalculiX 로는 못 거는 조건이 있습니다: "
        "구속 「바닥」(elastic_support)",
        "details": {"solver": "calculix"},
    }


def test_빈_성공은_확인_신호가_된다() -> None:
    _serve(lambda _r: httpx.Response(204))
    assert _run(server.study_publish, "s1")["ok"] is True


# --- HWAX 게이트웨이(Standard Platform ADR 0028 결정 12 · 13) -------------------------

GATEWAY_TOKEN_REJECTED = re.compile(
    r"^Error executing tool \S+: (?:GET|POST|PUT|PATCH|DELETE) \S+ → HTTP 401\b"
)


def _through_fastmcp(name: str, arguments: dict[str, Any], authorization: str) -> Any:
    """게이트웨이가 보는 그대로 — FastMCP 의 도구 호출 처리기(`tools/call`)를 거친 결과.
    도구에서 난 예외를 FastMCP 가 어떻게 감싸는지까지 이 길에서 돈다."""
    from mcp import types
    from mcp.server.lowlevel.server import request_ctx
    from mcp.shared.context import RequestContext

    handler = server.mcp._mcp_server.request_handlers[types.CallToolRequest]
    request = SimpleNamespace(headers={"authorization": authorization})
    held = request_ctx.set(
        RequestContext(
            request_id=1, meta=None, session=None, lifespan_context=None, request=request
        )
    )
    try:
        got = asyncio.run(
            handler(
                types.CallToolRequest(
                    method="tools/call",
                    params=types.CallToolRequestParams(name=name, arguments=arguments),
                )
            )
        )
    finally:
        request_ctx.reset(held)
    return got.root


def _text(result: Any) -> str:
    """게이트웨이가 읽는 글 — 내용 조각을 이어 붙여 앞뒤 공백을 뗀 것."""
    return "".join(getattr(one, "text", "") or "" for one in result.content).strip()


def test_백엔드가_토큰을_거절하면_게이트웨이가_다시_받는_모양으로_실패한다() -> None:
    """401 은 결과(`{"error": …}`)가 아니라 **오류**로 — 문구가 게이트웨이의 정규식에 맞아야
    게이트웨이가 위임 토큰을 새로 받아 한 번 다시 부른다."""
    seen = _serve(
        lambda _r: httpx.Response(
            401,
            json={"error": {"code": "SEB-AUTH-0101", "message": "토큰이 유효하지 않습니다."}},
        )
    )
    got = _through_fastmcp("jobs_list", {"status": "done"}, "Bearer old")
    assert got.isError is True
    text = _text(got)
    assert GATEWAY_TOKEN_REJECTED.match(text), text
    # 경로는 물음표 앞까지 — 서버의 말은 그대로다.
    assert text == (
        "Error executing tool jobs_list: GET /api/simulations/items → HTTP 401: "
        "[SEB-AUTH-0101] 토큰이 유효하지 않습니다."
    )
    assert seen[0].headers["authorization"] == "Bearer old"

    # 쓰는 도구도 같다(POST) · 본문이 JSON 이 아니어도 같다.
    _serve(lambda _r: httpx.Response(401, text="Unauthorized"))
    got = _through_fastmcp("job_retry", {"job_id": "j1"}, "Bearer t")
    assert got.isError is True and GATEWAY_TOKEN_REJECTED.match(_text(got)), _text(got)
    assert _text(got).startswith(
        "Error executing tool job_retry: POST /api/simulations/j1/retry"
    )


def test_401_이_아닌_오류는_결과로_전한다() -> None:
    """권한 없음(403) · 검증(422) 은 토큰 문제가 아니다 — 게이트웨이가 다시 받으면 같은 일이
    두 번 돈다. 결과로 그대로 전해 Claude 가 서버의 말을 읽는다."""
    for status in (403, 404, 409, 422, 500):
        _serve(
            lambda _r, status=status: httpx.Response(
                status, json={"error": {"code": "SEB-X-0001", "message": "안 됩니다"}}
            )
        )
        got = _through_fastmcp("job_get", {"job_id": "j1"}, "Bearer t")
        assert got.isError is False, status
        assert not GATEWAY_TOKEN_REJECTED.match(_text(got))
        assert "[SEB-X-0001] 안 됩니다" in _text(got)


#: 이름만 보고도 지움 · 되돌리기 · 멈춤인 도구 — 새로 생기면 위험 목록에 들어 있어야 한다.
_DESTRUCTIVE_WORDS = ("delete", "remove", "cancel", "undo", "merge", "restore", "tidy")


def test_위험_도구는_실제_도구이고_이름이_그런_것은_빠짐없다() -> None:
    """HWAX 게이트웨이에 범용 실행기 차단을 요청하는 목록 — 없는 이름을 적으면 요청이 헛돌고,
    새 지우기 도구를 빠뜨리면 그 도구는 게이트웨이의 이름 규칙(`delete_` 로 **시작**)에도 안
    걸린다."""
    assert server.DESTRUCTIVE_TOOLS <= TOOLS
    named = {one for one in TOOLS if any(word in one for word in _DESTRUCTIVE_WORDS)}
    assert named <= server.DESTRUCTIVE_TOOLS, named - server.DESTRUCTIVE_TOOLS


def test_요청서_틀의_위험_도구_목록이_서버와_같다() -> None:
    """요청서 틀(`deploy.sh hwax-request` 가 채운다)이 포털 담당에게 넘기는 목록은 코드의
    목록과 **같아야** 한다 — 두 벌이 갈리면 늘 느슨한 쪽이 게이트웨이에 들어간다."""
    text = REQUEST_TEMPLATE.read_text(encoding="utf-8")
    start = text.index("<!-- 위험 도구: 시작 -->")
    end = text.index("<!-- 위험 도구: 끝 -->")
    listed = set(re.findall(r'"([a-z_]+)"', text[start:end]))
    assert listed == set(server.DESTRUCTIVE_TOOLS)


# --- 안내서 -------------------------------------------------------------------------


def test_안내서는_서버가_쥐고_주제마다_나뉜다() -> None:
    overview = asyncio.run(server.get_guide(_ctx(None)))
    assert overview["topic"] == "overview"
    assert "folder_preview" in overview["content"] and "jobs_create" in overview["content"]
    assert set(overview["more_topics"]) == {
        "run",
        "conditions",
        "results",
        "compare",
        "publish",
    }

    # 거절을 읽는 법 · 단위 · 첨두응력 · 게시는 사람이 — **안내서에 있어야** AI 가 묻기 전에
    # 안다.
    conditions = asyncio.run(server.get_guide(_ctx(None), topic="conditions"))
    assert "refused" in conditions["content"] and "skipped" in conditions["content"]
    results = asyncio.run(server.get_guide(_ctx(None), topic="RESULTS"))
    assert "mm · MPa · N · Hz" in results["content"] and "첨두" in results["content"]
    publish = asyncio.run(server.get_guide(_ctx(None), topic="publish"))
    assert "사용자가" in publish["content"]

    missing = asyncio.run(server.get_guide(_ctx(None), topic="없는주제"))
    assert "error" in missing and "run" in missing["topics"]


# --- 도구가 무엇을 보내나 ---------------------------------------------------------------


def test_걸기는_폴더_가져오기로_스펙을_dict_그대로_보낸다() -> None:
    """스펙을 MCP 가 고쳐 쓰지 않는다 — 검증은 서버가 하고, 칸이 늘어도 이 파일은 그대로다.
    부서를 안 주면 **화면의 새 작업 창과 같은 기본**(대표 부서 → 첫 소속) — 비워 보내면 서버는
    전역 작업으로 읽고 시스템 관리자가 아니면 거절한다."""
    seen = _route(
        {
            ("GET", "/api/auth/me"): {
                "home_workspace_slug": None,
                "memberships": [{"slug": "cae"}],
            },
            ("POST", "/api/simulations/doe/import"): {"study_id": "s", "created": ["j1"]},
        }
    )
    spec = {"recipe": "static", "solver": "ansys", "mesh": {"element_size_mm": 3}}
    got = _run(server.jobs_create, spec, path="/data/doe/브래킷", numbers=[2, 5])
    assert got["created"] == ["j1"]
    assert (seen[1].method, seen[1].url.path) == ("POST", "/api/simulations/doe/import")
    body = json.loads(seen[1].content)
    assert body["spec"] == spec and body["numbers"] == [2, 5]
    assert (body["path"], body["workspace_slug"]) == ("/data/doe/브래킷", "cae")

    # 부서를 주면 묻지 않는다.
    seen.clear()
    _run(server.jobs_create, spec, path="/d", workspace_slug="qa")
    assert [one.url.path for one in seen] == ["/api/simulations/doe/import"]
    assert json.loads(seen[0].content)["workspace_slug"] == "qa"


def test_찾기는_스터디_id_나_이름을_보내고_못_찾으면_무엇을_할지_말한다() -> None:
    """사용자는 공유 폴더 경로를 모른다 — CompCore 의 스터디 id 나 이름으로 찾는다. 못 찾으면
    「CompCore 에서 내보내기」 를 말한다(0건을 「없다」 로만 전하지 않게)."""
    seen = _serve(
        lambda r: httpx.Response(
            200,
            json={
                "query": r.url.params["q"],
                "found": [{"name": "브래킷-3f9a2177", "path": "/data/doe/브래킷-3f9a2177"}]
                if r.url.params["q"] == "3f9a2177"
                else [],
            },
        )
    )
    got = _run(server.folder_find, "3f9a2177")
    assert got["found"][0]["path"] == "/data/doe/브래킷-3f9a2177" and "hint" not in got
    assert (seen[0].url.path, seen[0].url.params["q"]) == (
        "/api/simulations/doe/find",
        "3f9a2177",
    )
    missing = _run(server.folder_find, "없는 스터디")
    assert missing["found"] == [] and "doe_export" in missing["hint"]


FOUND = "/data/doe/솔버_덱_함께-51d7a12a"
COMPCORE_PATH = "F:\\data\\0_Program\\73_CompCore\\솔버_덱_함께-51d7a12a"


def _compcore_backend(
    *, import_error: dict[str, Any] | None = None, found: list[dict[str, Any]] | None = None
) -> list[httpx.Request]:
    """찾기 · 가져오기 · 미리 보기가 있는 가짜 백엔드 — 이 서버가 보는 경로만 받는다."""
    hits = (
        [{"path": FOUND, "matched_by": "id", "study_id": "51d7a12a-6804"}]
        if found is None
        else found
    )

    def respond(request: httpx.Request) -> httpx.Response:
        where = request.url.path
        if where == "/api/auth/me":
            return httpx.Response(200, json={"home_workspace_slug": "cae"})
        if where == "/api/simulations/doe/find":
            return httpx.Response(200, json={"found": hits, "roots": ["/data/doe"]})
        sent = (
            json.loads(request.content)["path"]
            if request.method == "POST"
            else request.url.params["path"]
        )
        if import_error is not None:
            return httpx.Response(422, json={"error": import_error})
        if sent != FOUND:
            refused = {
                "code": "SEB-SIMULATIONS-0020",
                "message": f"공용 폴더 밖입니다: {sent}",
            }
            return httpx.Response(400, json={"error": refused})
        if where == "/api/simulations/doe/import":
            return httpx.Response(201, json={"study_id": "51d7a12a-6804", "created": ["j1"]})
        return httpx.Response(200, json={"points": [], "path": sent})

    return _serve(respond)


def test_걸기는_CompCore_스터디_id_를_그대로_받는다() -> None:
    """CompCore 의 doe_run · doe_export 가 준 study_id 를 넘기면 서버가 폴더를 찾아 건다 — AI
    가 folder_find 를 끼워 부르는 것을 잊어도 된다(2026-10-23, 거기서 멈췄다)."""
    seen = _compcore_backend()
    got = _run(server.jobs_create, {"recipe": "modal"}, study_id="51d7a12a")
    assert got["created"] == ["j1"] and got["folder"] == FOUND
    asked = [(one.method, one.url.path) for one in seen]
    assert ("GET", "/api/simulations/doe/find") in asked
    assert json.loads(seen[-1].content)["path"] == FOUND

    preview = _run(server.folder_preview, study_id="51d7a12a")
    assert preview["path"] == FOUND and preview["folder"] == FOUND


def test_CompCore_가_준_경로를_넘겨도_꼬리의_id_로_찾아_건다() -> None:
    """`F:\\…\\<이름>-<id8>` 은 이 서버의 경로가 아니다 — 「공용 폴더 밖」 이면 꼬리의 id 로
    찾아 다시 건다(경로 탓인 거절일 때만)."""
    seen = _compcore_backend()
    got = _run(server.jobs_create, {"recipe": "modal"}, path=COMPCORE_PATH)
    assert got["created"] == ["j1"] and got["folder"] == FOUND
    finds = [one for one in seen if one.url.path == "/api/simulations/doe/find"]
    assert [one.url.params["q"] for one in finds] == ["51d7a12a"]


def test_경로_탓이_아닌_거절은_다시_찾지_않고_그대로_전한다() -> None:
    """스펙이 틀린 것을 다른 폴더로 다시 걸면 안 된다 — 서버의 말 그대로."""
    seen = _compcore_backend(import_error={"code": "SEB-SIMULATIONS-0001", "message": "스펙"})
    got = _run(server.jobs_create, {"recipe": "nope"}, path=COMPCORE_PATH)
    assert got["error"] == "[SEB-SIMULATIONS-0001] 스펙"
    assert all(one.url.path != "/api/simulations/doe/find" for one in seen)


def test_스터디_id_로_못_찾거나_여럿이면_무엇을_할지_말한다() -> None:
    _compcore_backend(found=[])
    missing = _run(server.jobs_create, {"recipe": "modal"}, study_id="deadbeef")
    assert "없습니다" in missing["error"] and "doe_export" in missing["hint"]
    assert missing["roots"] == ["/data/doe"]

    twin = [
        {"path": "/data/doe/a-51d7a12a", "matched_by": "id"},
        {"path": "/data/doe2/a-51d7a12a", "matched_by": "id"},
    ]
    _compcore_backend(found=twin)
    many = _run(server.jobs_create, {"recipe": "modal"}, study_id="51d7a12a")
    assert "여럿" in many["error"] and len(many["found"]) == 2

    assert "study_id" in _run(server.jobs_create, {"recipe": "modal"})["error"]


def test_미리_보기는_번호를_주면_설계점_하나로_간다() -> None:
    seen = _route(
        {
            ("GET", "/api/simulations/doe/preview"): {"points": []},
            ("GET", "/api/simulations/doe/point"): {"regions": []},
        }
    )
    _run(server.folder_preview, "/d/s")
    _run(server.folder_preview, "/d/s", number=3, recipe="static")
    assert seen[0].url.path == "/api/simulations/doe/preview"
    assert "recipe" not in seen[0].url.params  # 안 준 것은 안 보낸다(CAD 가 권한 것)
    assert seen[1].url.path == "/api/simulations/doe/point"
    assert dict(seen[1].url.params) == {"path": "/d/s", "number": "3", "recipe": "static"}


def test_목록은_줄여_보이고_전부는_scope_를_안_보낸다() -> None:
    """「해석」 목록 — 단일 해석과 DOE 한 벌이 한 줄씩(화면과 같다). 상태로 거르면 서버가
    설계점까지 낱개 작업으로 편다."""
    job = {
        "id": "j1",
        "name": "브래킷 p0002",
        "recipe": "modal",
        "solver": "calculix",
        "status": "done",
        "published_at": None,
        "folder": "고객A",
        "source_meta": {"study_id": "s1", "point": 2, "params": {"두께": 6}},
        "summary": {"first_elastic_hz": 812.4},
        "stages": [{"name": "solve"}],
        "artifacts": [{"kind": "frd"}],
    }
    study = {
        "study_id": "s1",
        "name": "브래킷",
        "recipe": "modal",
        "points": 3,
        "done": 2,
        "failed": 1,
        "running": 0,
        "published": 0,
        "folder": "",
        "owner_name": "나",
        "created_at": "2026-10-24T00:00:00Z",
    }
    rows = [
        {"kind": "job", "key": "job:j1", "job": job, "study": None},
        {"kind": "doe", "key": "doe:s1", "job": None, "study": study},
    ]
    seen = _serve(
        lambda _r: httpx.Response(200, json={"items": rows, "total": 2, "offset": 0})
    )
    got = _run(server.jobs_list, scope="all", limit=500, kind="doe", folder="고객A")
    assert seen[0].url.path == "/api/simulations/items"
    assert "scope" not in seen[0].url.params and seen[0].url.params["limit"] == "100"
    assert seen[0].url.params["kind"] == "doe" and seen[0].url.params["folder"] == "고객A"
    one, doe = got["items"]
    assert one["key"] == "job:j1" and one["kind"] == "job" and one["folder"] == "고객A"
    assert one["study_id"] == "s1" and one["params"] == {"두께": 6}
    assert one["published"] is False and "stages" not in one and "artifacts" not in one
    assert doe == {
        "kind": "doe",
        "key": "doe:s1",
        "study_id": "s1",
        "name": "브래킷",
        "recipe": "modal",
        "points": 3,
        "done": 2,
        "failed": 1,
        "running": 0,
        "published": 0,
        "folder": "",
        "owner": "나",
        "created_at": "2026-10-24T00:00:00Z",
    }

    _run(server.jobs_list)
    assert seen[1].url.params["scope"] == "mine"


def test_정리_폴더_나무와_옮기기는_제_경로로() -> None:
    """정리 폴더(사람이 나눈 것)는 CAD 공유 폴더와 다른 길이다 — 「해석」 목록의 항목
    열쇠로."""
    seen = _serve(lambda _r: httpx.Response(200, json=[{"path": "", "count": 2}]))
    assert _run(server.jobs_folders) == {"total": 1, "folders": [{"path": "", "count": 2}]}
    assert seen[0].url.path == "/api/simulations/items/folders"
    assert seen[0].url.params["scope"] == "mine"

    moved = _serve(lambda _r: httpx.Response(200, json={"moved": 2}))
    _run(server.jobs_move, ["job:j1", "doe:s1"], folder="고객A/2026")
    assert moved[0].method == "POST"
    assert moved[0].url.path == "/api/simulations/items/move"
    assert json.loads(moved[0].content) == {
        "ids": ["job:j1", "doe:s1"],
        "folder": "고객A/2026",
    }


def test_기다리면_끝날_때까지_묻고_안_끝났으면_도는_채로_말한다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**끝났다는 말을 지어내지 않는다** — 시간이 지나도 돌고 있으면 그 상태와 다음 할 일을
    준다."""
    monkeypatch.setattr(server, "_POLL_SECONDS", 0.0)
    states = iter(["solving", "extracting", "done"])
    seen = _serve(lambda _r: httpx.Response(200, json={"id": "j1", "status": next(states)}))
    got = _run(server.job_get, "j1", wait_seconds=25)
    assert got["status"] == "done" and "job_result" in got["next"]
    assert len(seen) == 3 and all(one.url.path.endswith("/status") for one in seen)

    _serve(lambda _r: httpx.Response(200, json={"id": "j1", "status": "solving"}))
    running = _run(server.job_get, "j1")
    assert running["status"] == "solving" and "job_get" in running["next"]


def test_대기_중이면_줄의_어디쯤인지와_워커가_없는지를_말한다() -> None:
    """「대기」 만 전하면 사람은 얼마나 기다릴지 모른다 — 서버가 준 줄을 그대로 싣고, 집을
    워커가 없으면 「끝날 때까지 기다리자」 가 아니라 사람에게 알리게 한다(ADR 0011)."""
    line = {"solver": "calculix", "queued": 7, "mine_ahead": 2, "people": 3, "running": 4}
    _serve(
        lambda _r: httpx.Response(
            200, json={"id": "j1", "status": "queued", "queue": {**line, "workers_alive": 4}}
        )
    )
    waiting = _run(server.job_get, "j1")
    assert waiting["queue"]["mine_ahead"] == 2
    assert "7건" in waiting["next"] and "3명" in waiting["next"]

    _serve(
        lambda _r: httpx.Response(
            200, json={"id": "j1", "status": "queued", "queue": {**line, "workers_alive": 0}}
        )
    )
    assert "워커가 없다" in _run(server.job_get, "j1")["next"]


def test_실패한_작업은_단계의_오류와_조건_줄을_싣는다() -> None:
    _serve(
        lambda _r: httpx.Response(
            200,
            json={
                "id": "j1",
                "status": "failed",
                "error_message": "못 거는 조건",
                "stages": [
                    {"name": "modeling", "status": "failed", "error_message": "못 거는 조건"}
                ],
                "conditions": {
                    "lines": [
                        {
                            "kind": "constraint",
                            "label": "바닥",
                            "status": "refused",
                            "why": "x",
                        }
                    ]
                },
            },
        )
    )
    got = _run(server.job_get, "j1")
    assert got["stages"][0]["error_message"] == "못 거는 조건"
    assert got["conditions"][0]["status"] == "refused"
    assert "job_retry" in got["next"]


def test_모달_결과는_견줄_값에_모드_방향을_붙인다() -> None:
    seen = _route(
        {
            ("GET", "/api/simulations/j1/values"): {"recipe": "modal", "frequencies": [100.0]},
            ("GET", "/api/simulations/j1/result"): {
                "modes": [
                    {"number": 1, "rigid_body": True, "frequency_hz": 0.0},
                    {
                        "number": 7,
                        "elastic_number": 1,
                        "rigid_body": False,
                        "frequency_hz": 100.0,
                        "dominant_direction": "Z",
                        "effective_mass_ratio": 0.61,
                    },
                ]
            },
        }
    )
    got = _run(server.job_result, "j1")
    assert got["modes"] == [
        {
            "elastic_number": 1,
            "frequency_hz": 100.0,
            "dominant_direction": "Z",
            "effective_mass_ratio": 0.61,
        }
    ]
    assert "result" not in got and len(seen) == 2


def test_정적_결과는_견줄_값만_원본은_달라고_할_때만() -> None:
    seen = _route(
        {
            ("GET", "/api/simulations/j1/values"): {
                "recipe": "static",
                "max_von_mises_mpa": 120.0,
            },
            ("GET", "/api/simulations/j1/result"): {"points": [1, 2]},
        }
    )
    assert _run(server.job_result, "j1") == {"recipe": "static", "max_von_mises_mpa": 120.0}
    assert len(seen) == 1
    assert _run(server.job_result, "j1", detail=True)["result"] == {"points": [1, 2]}


def test_목록은_객체_하나로_싸고_결과의_빈칸은_뺀다() -> None:
    """FastMCP 는 리스트의 항목마다 내용 조각을 따로 내 받는 쪽에 `}{` 로 이어 붙는다 —
    객체 하나로 싼다. 견줄 값 · 설계점 비교는 세 레시피의 칸을 다 실어 모달에 정적 · 조화의
    빈칸이 붙는다 — 뺀다(0 은 값이라 남긴다)."""
    _route(
        {
            ("GET", "/api/simulations/studies"): [{"study_id": "a"}, {"study_id": "b"}],
            ("GET", "/api/simulations/j1/measurements"): [],
            ("GET", "/api/simulations/studies/s1"): {
                "study_id": "s1",
                "points": [{"number": 1, "peak_hz": None, "reactions_n": {}, "nodes": 0}],
            },
            ("GET", "/api/simulations/j2/values"): {
                "recipe": "static",
                "max_displacement_mm": 0.0,
                "frequencies": [],
                "peak_hz": None,
            },
        }
    )
    assert _run(server.studies_list) == {
        "total": 2,
        "studies": [{"study_id": "a"}, {"study_id": "b"}],
    }
    assert _run(server.measurements_get, job_id="j1") == {"total": 0, "measurements": []}
    assert _run(server.study_get, "s1")["points"] == [{"number": 1, "nodes": 0}]
    assert _run(server.job_result, "j2") == {"recipe": "static", "max_displacement_mm": 0.0}


def test_게시와_해제는_제_경로로() -> None:
    seen = _serve(lambda _r: httpx.Response(200, json={"id": "j1", "status": "done"}))
    _run(server.job_publish, "j1")
    _run(server.job_publish, "j1", unpublish=True)
    _run(server.study_publish, "s1", unpublish=True)
    assert [one.url.path for one in seen] == [
        "/api/simulations/j1/publish",
        "/api/simulations/j1/unpublish",
        "/api/simulations/studies/s1/unpublish",
    ]


def test_분석은_조건을_여럿_보내고_결과를_안_고르면_주효과를_뺀다() -> None:
    """설계점 200개를 AI 가 손으로 셈하지 않게 서버가 셈한다 — 주효과(변수 x 결과 x 수준)는
    결과를 고를 때만 싣는다."""
    body = {"columns": [], "sensitivity": [], "effects": [{"factor": "factor:두께"}]}
    seen = _serve(lambda _r: httpx.Response(200, json=body))
    got = _run(
        server.study_analyze,
        "s1",
        objective="mass_kg",
        where=["mode:1>=300", "max_mpa<=200"],
    )
    assert seen[0].url.path == "/api/simulations/studies/s1/analysis"
    assert seen[0].url.params.get_list("where") == ["mode:1>=300", "max_mpa<=200"]
    assert seen[0].url.params["objective"] == "mass_kg"
    assert "result" not in seen[0].url.params
    assert "effects" not in got
    assert "effects" in _run(server.study_analyze, "s1", result="max_mm")


def test_서버_상태는_누구나_솔버_요약_관리자는_워커까지() -> None:
    solvers = [{"solver": "calculix", "workers_alive": 0, "queued": 3}]
    _route({("GET", "/api/simulations/solvers"): solvers})
    # 관리자가 아니면 /workers 가 404·403 — 요약만 준다.
    assert _run(server.server_status) == {"solvers": solvers}

    detail = {
        "queues": [{"solver": "calculix", "queued": 3, "running": 1}],
        "workers": [{"id": "h:1", "state": "busy", "hostname": "h", "tools": {"ccx": "/x"}}],
        "license_holders": [],
        "alive": 1,
    }
    _route(
        {
            ("GET", "/api/simulations/solvers"): solvers,
            ("GET", "/api/simulations/workers"): detail,
        }
    )
    got = _run(server.server_status)
    assert got["queues"] == detail["queues"]
    # 설치 경로(도구) · 호스트는 싣지 않는다 — 판단에 필요한 것만.
    assert got["workers"] == [
        {"id": "h:1", "state": "busy", "solvers": None, "silent_seconds": None, "job": None}
    ]


def test_DOE_모드_수_바꿔_다시_걸기는_제_경로로_모드_수를_싣는다() -> None:
    answer = {"created": [], "skipped": [], "notes": []}
    seen = _serve(lambda _r: httpx.Response(201, json=answer))
    _run(server.study_rerun, "s1", 10)
    assert [(one.method, one.url.path) for one in seen] == [
        ("POST", "/api/simulations/studies/s1/rerun")
    ]
    assert json.loads(seen[0].content) == {"modes": 10}


def test_DOE_멈추기와_중간_파일_정리는_제_경로로() -> None:
    seen = _serve(lambda _r: httpx.Response(200, json={"points": 3}))
    _run(server.study_cancel, "s1")
    _run(server.files_tidy, job_id="j1")
    _run(server.files_tidy, study_id="s1")
    assert [(one.method, one.url.path) for one in seen] == [
        ("POST", "/api/simulations/studies/s1/cancel"),
        ("POST", "/api/simulations/j1/tidy"),
        ("POST", "/api/simulations/studies/s1/tidy"),
    ]
    assert "error" in _run(server.files_tidy)


def test_수렴_점검은_비율을_안_주면_화면과_같은_제안으로() -> None:
    seen = _serve(lambda _r: httpx.Response(201, json={"levels": []}))
    _run(server.convergence_start, "j1")
    _run(server.convergence_start, "j1", ratios=[0.5], solver="ansys")
    assert json.loads(seen[0].content) == {"ratios": [0.7, 0.5]}
    assert json.loads(seen[1].content) == {"ratios": [0.5], "solver": "ansys"}


def test_실측은_표를_파일로_붙이고_대상은_하나만() -> None:
    seen = _serve(lambda _r: httpx.Response(201, json={"id": "m1"}))
    table = "측정점,종류,주파수\n,공진,812\n"
    _run(server.measurement_add, table, study_id="s1", label="1차 시험")
    assert seen[0].url.path == "/api/simulations/studies/s1/measurements"
    sent = seen[0].content
    assert table.encode() in sent and "1차 시험".encode() in sent

    assert "error" in _run(server.measurement_add, table)
    assert "error" in _run(server.measurements_get, job_id="j1", study_id="s1")
