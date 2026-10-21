"""SimEngBay MCP 서버 — AI 가 해석 작업을 걸고, 결과를 읽고, 설계점을 견주게 하는 도구.

플랫폼이 AI 를 부르지 않는다. AI(Claude Code · Claude Desktop · HWAX 포털의 Claude)가 이 서버를
도구로 물고, 사용자의 **개인 토큰(PAT)** 으로 백엔드에 붙는다 — 검증도 권한도 백엔드가 한다.
여기에 규칙을 두면 「MCP 로는 되는데 화면에서는 안 되는」 상태가 생기고, 그때 어느 쪽이 맞는지
알 방법이 없다. 백엔드(FastAPI)와 의존성이 충돌(mcp ↔ starlette)하므로 **별도 프로세스 · 별도
venv** 로 돌고, 백엔드와는 REST 로만 말한다.

## 해석이 늘어도 이 파일은 그대로

- **무엇을 걸 수 있나**(해석 종류 · 칸)는 도구가 아니라 스키마다 — `recipe_schema` 가 백엔드의
  `GET /simulations/recipes`(스펙 정의에서 뽑은 JSON 스키마)를 그대로 준다. 스펙은 dict 그대로
  넘기고 검증은 백엔드가 한다.
- **결과**는 백엔드가 단위를 맞춘 「견줄 값」(`GET /simulations/{id}/values`, 늘 mm · MPa · N ·
  Hz)으로 읽는다. 결과 파일은 레시피 · 솔버마다 칸과 단위가 달라서 여기서 맞추면 두 벌이 된다.
- 도구는 **작업 흐름 단위로** 고정한다 — 도구 목록이 길수록 모델은 엉뚱한 것을 고른다.

실행:
    PLATFORM_API_BASE=http://127.0.0.1:8071 ./venv/bin/python server.py
    # streamable-http, 기본 127.0.0.1:8072/mcp

Claude Code 등록(사용자별 토큰 — 화면의 「내 정보」 에서 발급):
    claude mcp add --transport http simengbay http://<host>:8072/mcp \\
      --header "Authorization: Bearer simengbay_pat_…"
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP

API_BASE = os.environ.get("PLATFORM_API_BASE", "http://127.0.0.1:8070").rstrip("/")

# SSE 를 버퍼링하는 프록시 · 보안장비 뒤에서는 단발 JSON 응답으로(Standard Platform 에서 실측한
# 함정 — initialize 응답이 클라이언트에 안 닿아 타임아웃). 이 서버는 스트리밍 메시지를 안 쓴다.
_JSON_RESPONSE = os.environ.get("MCP_JSON_RESPONSE") == "1"

INSTRUCTIONS = (
    "구조 해석(모달 · 정적 · 조화 응답)을 CAD 가 내보낸 설계점에 걸고, 결과를 읽고, "
    "설계점끼리 · 실측과 견주는 플랫폼. **`get_guide` 를 먼저 부른다** — 작업 순서와 "
    "조건 · 단위 규칙이 거기 있다.\n"
    "\n"
    "**형상은 CompCore(CAD)에서 온다.** CompCore 에서 DOE · 설계를 만들고 내보내면"
    "(CompCore MCP 의 `doe_export`, 화면의 「해석으로 보내기」) 공유 폴더에 스터디 폴더가 "
    "생기고, 여기서 그것을 읽어 푼다. 두 플랫폼을 잇는 열쇠는 **CompCore 스터디 id** 다(여기 "
    "`study_id` 와 같다). **사용자에게 공유 폴더 경로를 묻지 않는다** — 스터디 id 나 이름으로 "
    "`folder_find` 를 부른다. 못 찾으면 CompCore 에서 아직 내보내지 않았거나(그쪽 "
    "`doe_export`) 보관 기한(기본 30일)이 지나 치워진 것이다.\n"
    "\n"
    "하려는 일 → 부를 것:\n"
    "  CompCore 에서 만든 스터디를 찾는다 folder_find  (스터디 id · 이름으로)\n"
    "  무엇을 걸 수 있나(칸 · 기본값)   recipe_schema\n"
    "  공유 폴더를 둘러본다              folder_browse  (무엇이 있는지 모를 때)\n"
    "  걸기 전에 조건이 어떻게 걸리나   folder_preview  (설계점 하나는 number 를 준다)\n"
    "  해석을 건다                       jobs_create     (설계점 하나 · 여럿 · 폴더 통째로)\n"
    "  내 작업 · 게시된 작업             jobs_list\n"
    "  진행 상황 · 실패 까닭             job_get         (wait_seconds 로 기다린다)\n"
    "  결과 숫자                         job_result      (늘 mm · MPa · N · Hz)\n"
    "  설계점끼리 견준다                 studies_list → study_get\n"
    "  메시가 충분한가                   convergence_start → convergence_get\n"
    "  실측과 견준다                     measurement_add → measurements_get\n"
    "  실패를 다시 · 멈춘다              job_retry · job_cancel\n"
    "  남에게 보이게 한다                job_publish · study_publish  (사용자가 시킬 때만)\n"
    "\n"
    "지켜야 할 셋:\n"
    "1. **걸기 전에 미리 본다.** `folder_preview` 의 `conditions.lines` 에 `refused` 가 "
    "있으면 그 작업은 모델링에서 멈춘다 — 까닭(`why`)을 사람에게 말하고 솔버를 바꾸거나 "
    "CAD 쪽을 고치게 한다. 우회하지 않는다.\n"
    "2. **해석은 몇 분에서 몇 시간 걸린다.** 걸면 작업 번호가 바로 돌아온다 — 끝났다고 "
    "지어내지 말고 `job_get` 으로 확인한다.\n"
    "3. **게시는 사람이 판단할 일이다.** 게시하면 조직의 누구나 그 결과를 본다 — 사용자가 "
    "시킬 때만 `job_publish` · `study_publish` 를 부른다."
)

mcp = FastMCP(
    # 번들 하나로 여러 인스턴스를 띄울 수 있어 이름은 설치(유닛의 APP_SLUG)에서 온다.
    os.environ.get("APP_SLUG", "simengbay"),
    json_response=_JSON_RESPONSE,
    instructions=INSTRUCTIONS,
)

#: 시험이 갈아 끼우는 자리 — 진짜 앱(ASGI)이나 가짜 응답을 여기로 붙인다. 운영에서는 None.
_TRANSPORT: httpx.AsyncBaseTransport | None = None

#: **위험 도구** — HWAX 게이트웨이의 범용 실행기(`invoke_tool`)가 막아 달라고 요청서에
#: 적는 목록이다. 게이트웨이는 이름이 `delete_` · `remove_` · `cancel_` 로 **시작**하는
#: 도구만 막아서 우리 이름(`job_cancel`)은 안 걸린다. 더하거나 빼면 요청서 틀
#: (`docs/[참고] HWAX포탈_연동_요청서.md`)도 같이 — 시험이 둘을 견준다. 더하는 기준은
#: 「미리 보기 없이 바로 바꾸거나, 한 번에 여러 줄을 바꾸거나, 사라진 것을 되살릴 수
#: 없는가」.
DESTRUCTIVE_TOOLS = frozenset(
    {
        "job_cancel",  # 도는 해석을 멈춘다 — 그때까지 쓴 솔버 시간은 되살릴 수 없다
    }
)


def _forward_headers(ctx: Context) -> dict[str, str]:
    """들어온 MCP HTTP 요청의 인증 헤더를 백엔드로 — **사용자의 토큰으로** 동작한다.

    **`Authorization` 만 넘긴다.** HWAX 게이트웨이가 사람별 호출에 함께 싣는 소속
    (`X-Heax-User-Affiliation` · `X-Heax-Aff-Proof`)은 버린다 — 무엇을 볼 수 있나는 건 사람 ·
    게시가 정한다. 받아 넘기면 언젠가 누가 그 머리를 믿는 코드를 쓰고, 그 머리는 게이트웨이
    밖에서 아무나 적을 수 있다."""
    headers: dict[str, str] = {}
    req = getattr(getattr(ctx, "request_context", None), "request", None)
    if req is not None:
        value = req.headers.get("authorization")
        if value:
            headers["Authorization"] = value
    return headers


class BackendUnauthorized(Exception):
    """백엔드가 **이 토큰을 거절했다**(401) — 도구 결과가 아니라 예외로 올린다.

    HWAX 게이트웨이는 사람마다 그 사람의 위임 토큰(우리 `POST /api/auth/sso` 가 하루짜리로
    낸다)을 들고 있다가, 도구 결과가 이 꼴일 때만 **새로 받아 한 번 다시 부른다**:

        ^Error executing tool \\S+: (GET|POST|PUT|PATCH|DELETE) \\S+ → HTTP 401

    FastMCP 는 도구에서 난 예외를 `Error executing tool <이름>: <예외 문구>` 로 감싸므로 문구를
    `<METHOD> <경로> → HTTP 401: <서버의 말>` 로 지으면 그 정규식에 맞는다(Standard Platform
    ADR 0028 결정 12). 401 은 인증에서 끊긴 것이라 도구는 아무것도 안 했다 — 다시 불러도
    두 번 걸리지 않는다. 자기 토큰으로 직접 붙은 사람에게도 같은 문구가 간다(토큰을 새로
    만들면 된다).
    """


def _rejected(response: httpx.Response) -> BackendUnauthorized:
    """`<METHOD> <경로> → HTTP 401: <서버의 말>` — 경로는 물음표 앞까지(게이트웨이의
    `\\S+`)."""
    try:
        method = response.request.method
        path = response.request.url.raw_path.decode("ascii", "replace").split("?", 1)[0]
    except RuntimeError:  # 요청 없이 만든 응답(시험) — 실제 호출에는 늘 있다
        method, path = "GET", "/"
    said = "토큰이 없거나 유효하지 않습니다"
    try:
        body = response.json()
    except ValueError:
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        said = f"[{error.get('code') or 401}] {error.get('message') or said}"
    return BackendUnauthorized(f"{method} {path} → HTTP 401: {said}")


def _unwrap(response: httpx.Response) -> Any:
    """백엔드 응답을 푼다. 오류 봉투 `{error: {code, message, details}}` 면 `{"error": …}`.

    **401 만은 예외로 올린다**(`BackendUnauthorized`) — 게이트웨이가 토큰을 다시 받는
    신호다."""
    if response.status_code == 401:
        raise _rejected(response)
    if response.status_code < 400 and not response.content:
        # 돌려줄 게 없는 성공. 그대로 흘리면 도구 결과가 빈 문자열이라 모델은 성공했는지
        # 모른다.
        return {"ok": True, "message": "완료"}
    try:
        body = response.json()
    except ValueError:
        return {
            "error": f"HTTP {response.status_code} (JSON 이 아닌 응답)",
            "status": response.status_code,
        }
    if response.status_code >= 400:
        # **서버의 말을 그대로 전한다.** 오류 문구에 무엇을 고쳐야 하는지가 적혀 있다.
        error = body.get("error") if isinstance(body, dict) else None
        if not isinstance(error, dict):
            return {"error": f"HTTP {response.status_code}", "status": response.status_code}
        tag = error.get("code") or response.status_code
        out: dict[str, Any] = {"error": f"[{tag}] {error.get('message') or ''}"}
        if error.get("details"):
            out["details"] = error["details"]
        return out
    return body


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=API_BASE, timeout=timeout, transport=_TRANSPORT)


async def _get(ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
    clean = {key: value for key, value in (params or {}).items() if value is not None}
    async with _client(90) as client:
        return _unwrap(await client.get(path, params=clean, headers=_forward_headers(ctx)))


async def _post(ctx: Context, path: str, json_body: Any = None) -> Any:
    async with _client(120) as client:
        return _unwrap(await client.post(path, json=json_body, headers=_forward_headers(ctx)))


async def _post_file(
    ctx: Context, path: str, file: tuple[str, bytes, str], fields: dict[str, Any]
) -> Any:
    data = {key: value for key, value in fields.items() if value is not None}
    async with _client(120) as client:
        return _unwrap(
            await client.post(
                path, data=data, files={"file": file}, headers=_forward_headers(ctx)
            )
        )


def _failed(got: Any) -> bool:
    return isinstance(got, dict) and "error" in got


def _listed(got: Any, key: str) -> Any:
    """목록 응답은 **객체 하나로** 싸서 돌려준다 — FastMCP 는 리스트의 항목마다 내용 조각을
    따로 내서, 받는 쪽에는 `}{` 로 이어 붙은 글이 된다(개발 서버에 붙여 보고 알았다)."""
    if isinstance(got, list):
        return {"total": len(got), key: got}
    return got


def _compact(row: dict[str, Any]) -> dict[str, Any]:
    """그 해석 종류에 없는 칸(`None` · 빈 `{}` · `[]`)을 뺀다 — 견줄 값은 세 레시피의 칸을 다
    실어서, 모달 결과에 정적 · 조화의 빈칸이 열 줄 넘게 붙는다. 0 · False 는 값이라 남긴다."""
    return {key: value for key, value in row.items() if value not in (None, {}, [])}


# --------------------------------------------------------------------------- #
# 작업을 줄여 보인다 — 상세 응답은 산출물 · 단계 · 조건까지 실어 크다
# --------------------------------------------------------------------------- #

#: 끝난 상태 — 이 밖이면 아직 돈다(`queued` · `fetching` · `modeling` · `solving` ·
#: `extracting`).
FINISHED = frozenset({"done", "failed", "canceled"})

#: 한 도구 호출이 작업을 기다리는 최대 초. 클라이언트의 도구 시간 한도(대개 60초)보다 넉넉히
#: 짧게 — 그 안에 안 끝나면 `job_get` 으로 다시 묻는다.
JOB_WAIT_MAX = 25.0
_POLL_SECONDS = 2.0


def _slim_job(job: dict[str, Any]) -> dict[str, Any]:
    """목록 한 줄 — 무엇을 · 어디서 · 어떤 상태인가."""
    meta = job.get("source_meta") or {}
    out: dict[str, Any] = {
        "id": job.get("id"),
        "name": job.get("name"),
        "recipe": job.get("recipe"),
        "solver": job.get("solver"),
        "status": job.get("status"),
        "published": job.get("published_at") is not None,
        "requested_by": job.get("requested_by_name"),
        "created_at": job.get("created_at"),
        "finished_at": job.get("finished_at"),
    }
    if meta.get("study_id"):
        out["study_id"] = meta["study_id"]
        out["point"] = meta.get("point")
        out["params"] = meta.get("params")
    if job.get("error_code"):
        out["error_code"] = job["error_code"]
    if job.get("summary"):
        out["summary"] = job["summary"]
    return out


def _next_step(job: dict[str, Any]) -> str:
    status = job.get("status")
    if status == "done":
        return "job_result(job_id) 로 결과 숫자를 읽는다."
    if status == "failed":
        return (
            "error_message 와 stages 의 오류를 사람에게 전한다. 조건 거절이면 고쳐서 다시 "
            "걸고, 일시적인 것(워커 · 라이선스)이면 job_retry(job_id)."
        )
    if status == "canceled":
        return "멈춘 작업이다 — 다시 돌리려면 job_retry(job_id)."
    queue = job.get("queue")
    if status == "queued" and isinstance(queue, dict):
        if queue.get("workers_alive") == 0:
            return (
                f"대기 중인데 이 솔버({queue.get('solver')})를 집는 워커가 없다 — 워커가 뜰 "
                "때까지 움직이지 않는다. 사람에게 알리고(관리자가 워커를 띄우거나 솔버를 "
                "바꾼다) 끝났다고 말하지 않는다."
            )
        return (
            f"대기 중 — 이 솔버의 줄에 {queue.get('queued')}건, 그중 내 앞의 내 작업 "
            f"{queue.get('mine_ahead')}건, {queue.get('people')}명이 번갈아 쓴다(지금 도는 것 "
            f"{queue.get('running')}건). 사람에게 이 줄을 그대로 전하고, job_get(job_id, "
            "wait_seconds=25) 로 다시 묻는다."
        )
    return (
        "아직 돈다 — 끝났다고 말하지 말고 job_get(job_id, wait_seconds=25) 로 다시 묻는다. "
        "솔브는 모델 크기에 따라 몇 분에서 몇 시간 걸린다."
    )


def _job_view(job: dict[str, Any]) -> dict[str, Any]:
    """상세 — 목록 한 줄에 단계 · 조건(어떻게 걸렸나) · 실패 까닭 · 스펙을 더한다."""
    out = _slim_job(job)
    out["spec"] = job.get("spec")
    out["stages"] = [
        {
            key: stage.get(key)
            for key in ("name", "status", "detail", "error_code", "error_message")
            if stage.get(key)
        }
        for stage in job.get("stages") or []
    ]
    if job.get("error_message"):
        out["error_message"] = job["error_message"]
    conditions = job.get("conditions") or {}
    lines = conditions.get("lines") or []
    if lines:
        out["conditions"] = [
            {key: line.get(key) for key in ("kind", "label", "status", "why") if line.get(key)}
            for line in lines
        ]
    out["artifacts"] = sorted({one.get("kind") for one in job.get("artifacts") or []})
    if job.get("queue"):
        # 대기 중일 때만 온다 — 줄의 어디쯤인가(ADR 0011).
        out["queue"] = job["queue"]
    out["next"] = _next_step(job)
    return out


# --------------------------------------------------------------------------- #
# 안내 · 나
# --------------------------------------------------------------------------- #

_GUIDE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guide", "GUIDE.md")
_GUIDE_TOPICS = ("overview", "run", "conditions", "results", "compare", "publish")


def _guide_sections() -> tuple[str, dict[str, str]]:
    """GUIDE.md 를 `<!--@ 주제 -->` 로 갈라 {주제: 본문}. 매 호출마다 읽는다 — 서버 재시작
    없이 안내서를 고칠 수 있다."""
    try:
        with open(_GUIDE_PATH, encoding="utf-8") as handle:
            raw = handle.read()
    except OSError:
        return "?", {}
    version = "?"
    for line in raw.split("\n")[:20]:
        if line.startswith("GUIDE_VERSION:"):
            version = line.split(":", 1)[1].strip()
            break
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in raw.split("\n"):
        found = re.match(r"<!--@\s*(\w+)\s*-->", line.strip())
        if found:
            current = found.group(1)
            out[current] = []
        elif current:
            out[current].append(line)
    return version, {key: "\n".join(lines).strip() for key, lines in out.items()}


@mcp.tool()
async def get_guide(ctx: Context, topic: str | None = None) -> dict[str, Any]:
    """**해석 일을 시작하기 전에 먼저 부른다.** 무엇을 어떤 순서로 쓸지, 조건 · 단위에서 무엇을
    조심할지 이 안내서가 정한다(서버가 최신본을 쥔다).

    `topic` 없이 부르면 **overview** — 흐름과 기본 습관. 세부가 필요하면 그때 주제를 준다:
      - `run` 설계점 고르기 · 스펙 채우기 · 걸기 · 기다리기
      - `conditions` CAD 조건이 어떻게 걸리나 — 걸림 · 건너뜀 · 거절, 솔버마다 다른 것
      - `results` 결과 숫자 읽기 — 레시피마다 무엇이 나오나, 단위
      - `compare` 설계점 비교 · 메시 수렴 · 실측 맞추기
      - `publish` 게시 — 누가 무엇을 보나"""
    version, sections = _guide_sections()
    if not sections:
        return {
            "error": "안내서를 읽을 수 없습니다(서버 설치 문제). "
            "도구 설명만으로 진행하되 사용자에게 알리세요."
        }
    if topic:
        key = topic.strip().lower()
        if key not in sections:
            return {"error": f"그런 주제가 없습니다: {topic}", "topics": sorted(sections)}
        return {"guide_version": version, "topic": key, "content": sections[key]}
    return {
        "guide_version": version,
        "topic": "overview",
        "content": sections.get("overview", ""),
        "more_topics": [one for one in _GUIDE_TOPICS if one in sections and one != "overview"]
        + sorted(one for one in sections if one not in _GUIDE_TOPICS),
        "note": "세부가 필요하면 get_guide(topic=...) 로 그 주제만 받아라.",
    }


@mcp.tool()
async def whoami(ctx: Context) -> Any:
    """지금 토큰의 주인 — 이름 · 대표 부서 · 소속 부서 · 시스템 관리자인가. 작업은 이 사람의
    것으로 걸린다(`jobs_create` 의 `workspace_slug` 를 비우면 대표 부서)."""
    return await _get(ctx, "/api/auth/me")


@mcp.tool()
async def recipe_schema(ctx: Context) -> Any:
    """**무엇을 걸 수 있나** — 해석 종류(레시피)마다 스펙의 JSON 스키마(칸 · 기본값 · 범위 ·
    설명)와, 솔버마다 지금 집을 워커가 있나.

    스펙은 이 스키마대로 채워 `jobs_create` 에 dict 로 넘긴다. 칸 이름에 단위가 있다
    (`element_size_mm` · `youngs_modulus_gpa`). 대개 `recipe` · `solver` ·
    `mesh.element_size_mm` 정도만 주고 나머지(조건 · 물성 · 해석 설정)는 CAD 가 보낸 값을
    쓴다(`*_from: "cad"`).
    집을 워커가 없는 솔버로 걸면 작업이 대기에서 움직이지 않는다."""
    recipes = await _get(ctx, "/api/simulations/recipes")
    if _failed(recipes):
        return recipes
    solvers = await _get(ctx, "/api/simulations/solvers")
    return {"recipes": recipes, "solvers": solvers}


# --------------------------------------------------------------------------- #
# CAD 폴더 — 걸기 전에
# --------------------------------------------------------------------------- #


@mcp.tool()
async def folder_find(ctx: Context, query: str) -> Any:
    """CompCore 에서 만든 스터디(DOE · 설계 하나)의 폴더를 **CompCore 스터디 id(전체 또는 앞
    8자리)나 이름으로** 찾는다 — 공유 폴더 경로를 몰라도 된다. **사용자에게 경로를 묻지 말고
    이것부터.**

    CompCore 는 내보낼 때 `<이름>-<스터디 id 앞 8자리>` 폴더를 만든다. CompCore MCP 의
    `doe_export` 가 주는 `folder` 는 Windows 경로(`F:\\…`)라 여기서 그대로 못 쓴다 — 그 답의
    `study_id` 로 찾는다. 찾은 `path` 를 `folder_preview` · `jobs_create` 에 그대로 넘긴다.
    id 로 맞은 것이 먼저, 그다음 최근에 내보낸 것부터. 이름이 여럿 맞으면 사람에게 고르게
    한다(첫 줄을 집지 않는다)."""
    got = await _get(ctx, "/api/simulations/doe/find", {"q": query})
    if isinstance(got, dict) and got.get("found") == []:
        got["hint"] = (
            "공유 폴더에 없다. CompCore 에서 아직 내보내지 않았거나(그쪽 MCP 의 doe_export · "
            "화면의 「해석으로 보내기」) 보관 기한(기본 30일)이 지나 치워졌다 — CompCore 에서 "
            "다시 내보내면 같은 폴더가 다시 선다. 이름이면 다른 말로도 찾아본다."
        )
    return got


@mcp.tool()
async def folder_browse(ctx: Context, path: str | None = None) -> Any:
    """CAD(CompCore)가 DOE · 설계를 내보낸 **공용 폴더**를 훑는다 — 서버가 보는 경로, 설정된
    뿌리 아래만. `path` 를 비우면 첫 뿌리. `is_study` 인 항목이 걸 수 있는 폴더다(스터디 하나 ·
    설계 하나). 찾을 스터디를 알면 `folder_find` 가 빠르다 — 이것은 무엇이 있는지 둘러볼 때.
    파일을 올리는 길은 없다 — 해석은 이 폴더에서 건다."""
    return await _get(ctx, "/api/simulations/doe/browse", {"path": path})


@mcp.tool()
async def folder_preview(
    ctx: Context, path: str, number: int | None = None, recipe: str | None = None
) -> Any:
    """**걸기 전에** 폴더를 읽어 본다. 저장하지 않는다.

    - `number` 없이: 스터디 전체 — 설계점 몇 개 · 바꾼 변수 · 걸 수 있는 것 · 건너뛸 것(까닭) ·
      CAD 가 권하는 해석 종류 · 모드 수 · 요소 크기 · 큰 변형.
    - `number` 를 주면: 그 설계점 하나 — 영역 · 파트 · 물성 · 권하는 설정, 그리고
      **`conditions.lines`**: CAD 조건이 이 해석 종류에서 어떻게 걸리나(`applied` 걸림 ·
      `skipped` 답을 안 바꿔 넘김 · `refused` 아직 못 건다 — 모델링에서 멈춘다).

    `recipe` 를 주면 그 해석 종류로 읽는다(비우면 CAD 가 권한 것). `refused` 가 있으면 걸기
    전에 사람에게 까닭을 말한다."""
    if number is None:
        return await _get(
            ctx, "/api/simulations/doe/preview", {"path": path, "recipe": recipe}
        )
    return await _get(
        ctx, "/api/simulations/doe/point", {"path": path, "number": number, "recipe": recipe}
    )


# --------------------------------------------------------------------------- #
# 걸기 · 보기
# --------------------------------------------------------------------------- #


async def _home_workspace(ctx: Context) -> str | None:
    """화면의 새 작업 창과 같은 기본 — 대표 부서, 없으면 첫 소속. 둘 다 없으면 비운다(전역 작업
    — 시스템 관리자만 걸 수 있고, 아니면 서버가 「부서를 선택하세요」 로 거절한다)."""
    me = await _get(ctx, "/api/auth/me")
    if not isinstance(me, dict) or _failed(me):
        return None
    if me.get("home_workspace_slug"):
        return str(me["home_workspace_slug"])
    memberships = me.get("memberships") or []
    return str(memberships[0]["slug"]) if memberships else None


@mcp.tool()
async def jobs_create(
    ctx: Context,
    path: str,
    spec: dict[str, Any],
    numbers: list[int] | None = None,
    name: str | None = None,
    workspace_slug: str | None = None,
) -> Any:
    """CAD 폴더의 설계점에 해석을 건다 — **점마다 작업 하나.**

    - `path`: `folder_find` · `folder_browse` 가 준 폴더(스터디 · 설계 하나).
    - `spec`: `recipe_schema` 대로의 스펙(dict). 모든 점에 같은 스펙이다.
    - `numbers`: 고른 설계점 번호. 비우면 걸 수 있는 전부(설계 하나면 그 하나).
    - `name`: 작업 이름 — 비우면 폴더 이름 · 「폴더 pNNNN (변수 값)」.
    - `workspace_slug`: 작업의 부서 꼬리표 — 비우면 화면처럼 내 대표 부서(없으면 첫 소속).

    돌려주는 것: `study_id` · 만든 작업 id(`created`) · 걸지 못한 점과 까닭(`skipped`). 해석은
    워커가 돌린다 — 끝났다고 말하지 말고 `job_get(job_id, wait_seconds=…)` 로 확인한다. 이미
    가져온 점을 다시 걸면 거절된다(같은 해석을 두 번 돌리지 않는다)."""
    if not workspace_slug:
        workspace_slug = await _home_workspace(ctx)
    return await _post(
        ctx,
        "/api/simulations/doe/import",
        {
            "path": path,
            "spec": spec,
            "numbers": numbers,
            "name": name,
            "workspace_slug": workspace_slug,
        },
    )


@mcp.tool()
async def jobs_list(
    ctx: Context,
    scope: str = "mine",
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> Any:
    """해석 작업 목록 — 최근 것부터.

    - `scope`: `mine` 내가 건 것(기본) · `published` 게시된 것(누구나 읽는다) · `all` 볼 수
      있는 전부(시스템 관리자는 모든 작업).
    - `status`: `queued` · `modeling` · `solving` · `done` · `failed` · `canceled` 등으로
      좁힌다.

    한 줄은 줄인 모양이다 — 단계 · 조건 · 실패 까닭은 `job_get`, 결과 숫자는 `job_result`."""
    got = await _get(
        ctx,
        "/api/simulations",
        {
            "scope": None if scope == "all" else scope,
            "status": status,
            "limit": max(1, min(limit, 100)),
            "offset": max(0, offset),
        },
    )
    if _failed(got) or not isinstance(got, dict):
        return got
    return {
        "total": got.get("total"),
        "offset": got.get("offset"),
        "items": [_slim_job(one) for one in got.get("items") or []],
    }


@mcp.tool()
async def job_get(ctx: Context, job_id: str, wait_seconds: int = 0) -> Any:
    """작업 하나의 상태 · 단계 · 조건(어떻게 걸렸나) · 실패 까닭 · 스펙.

    `wait_seconds`(최대 25)를 주면 그동안 끝나기를 기다린다 — 안 끝났으면 도는 상태 그대로
    돌려준다(`next` 가 다음 할 일을 말한다). 끝난 상태는 `done` · `failed` · `canceled`."""
    deadline = time.monotonic() + max(0.0, min(float(wait_seconds), JOB_WAIT_MAX))
    while True:
        got = await _get(ctx, f"/api/simulations/{job_id}/status")
        if _failed(got) or not isinstance(got, dict):
            return got
        if got.get("status") in FINISHED or time.monotonic() >= deadline:
            return _job_view(got)
        await asyncio.sleep(_POLL_SECONDS)


@mcp.tool()
async def job_result(ctx: Context, job_id: str, detail: bool = False) -> Any:
    """끝난 작업의 **결과 숫자** — 늘 mm · MPa · N · Hz(서버가 솔버마다 다른 단위를 맞춘다).

    - 모달: `frequencies`(탄성 모드, 강체 뺌) · `first_elastic_hz` · `modes`(모드마다 지배
      방향과 유효질량비 — 어느 방향으로 떠는 모드인가).
    - 정적: `max_displacement_mm` · `max_von_mises_mpa` · `reactions_n`(영역 → [Fx, Fy, Fz]) ·
      측정점 `probes_mm` · `probe_vectors_mm` · `probe_strains` · `relative_mm`(같은 자리 두
      바디의 미끄럼).
    - 조화: `peak_hz` · `peak_displacement_mm` · 측정점별 봉우리(`probes_mm` ·
      `probe_peaks_hz`).

    **최대 응력은 구속 모서리의 수치적 첨두일 수 있다** — 판단에 쓰기 전에 메시 수렴
    (`convergence_start`)을 권한다. `detail=true` 면 결과 파일(`result.json`) 원본도 싣는다
    (조화의 주파수별 곡선 등 — 크다). 아직 안 끝났으면 왜 없는지가 오류로 온다."""
    got = await _get(ctx, f"/api/simulations/{job_id}/values")
    if _failed(got) or not isinstance(got, dict):
        return got
    values = _compact(got)
    if values.get("recipe") != "modal" and not detail:
        return values
    raw = await _get(ctx, f"/api/simulations/{job_id}/result")
    if _failed(raw) or not isinstance(raw, dict):
        return values
    if values.get("recipe") == "modal":
        values["modes"] = [
            {
                key: mode.get(key)
                for key in (
                    "elastic_number",
                    "frequency_hz",
                    "dominant_direction",
                    "effective_mass_ratio",
                )
                if mode.get(key) is not None
            }
            for mode in raw.get("modes") or []
            if not mode.get("rigid_body")
        ]
    if detail:
        values["result"] = raw
    return values


@mcp.tool()
async def job_retry(ctx: Context, job_id: str) -> Any:
    """실패하거나 멈춘 작업을 **같은 스펙으로 다시** 건다(처음 단계부터). 조건 거절로 실패한
    작업은 다시 걸어도 같은 곳에서 멈춘다 — 까닭부터 고친다. 건 사람이나 시스템 관리자만."""
    got = await _post(ctx, f"/api/simulations/{job_id}/retry")
    return _job_view(got) if isinstance(got, dict) and not _failed(got) else got


@mcp.tool()
async def job_cancel(ctx: Context, job_id: str) -> Any:
    """작업을 멈춘다 — 대기 중이면 곧바로, 돌고 있으면 워커가 몇 초 안에 본다. **그때까지 쓴
    솔버 시간은 되살릴 수 없다** — 사용자가 시킬 때만. 건 사람이나 시스템 관리자만."""
    got = await _post(ctx, f"/api/simulations/{job_id}/cancel")
    return _job_view(got) if isinstance(got, dict) and not _failed(got) else got


@mcp.tool()
async def job_publish(ctx: Context, job_id: str, unpublish: bool = False) -> Any:
    """끝난 작업을 **게시**한다 — 조직의 누구나 그 결과를 읽는다(고치지는 못한다). 메시 수렴
    수준도 함께. `unpublish=true` 면 게시를 해제한다(다시 건 사람과 시스템 관리자만 본다).

    **사람이 판단할 일이다** — 사용자가 시킬 때만 부른다. 건 사람이나 시스템 관리자만."""
    action = "unpublish" if unpublish else "publish"
    got = await _post(ctx, f"/api/simulations/{job_id}/{action}")
    return _job_view(got) if isinstance(got, dict) and not _failed(got) else got


# --------------------------------------------------------------------------- #
# 견주기 — 설계점 · 메시 수렴 · 실측
# --------------------------------------------------------------------------- #


@mcp.tool()
async def studies_list(ctx: Context, scope: str | None = None) -> Any:
    """가져온 DOE(스터디) 목록 — 점 몇 개 · 끝난 것 · 실패한 것. `scope`: `mine` 내가 건 점이
    있는 것 · `published` 게시된 점이 있는 것 · 비우면 볼 수 있는 전부."""
    return _listed(await _get(ctx, "/api/simulations/studies", {"scope": scope}), "studies")


@mcp.tool()
async def study_get(ctx: Context, study_id: str) -> Any:
    """스터디 하나의 **설계점 비교** — 점마다 바꾼 값(`params`)과 그 결과(1차 공진 · 질량 ·
    최대 변위 · 최대 응력 · 반력 · 측정점, 늘 mm · MPa · N · Hz), 그리고 모드 추적(치수가
    바뀌어 모드 순서가 뒤바뀌어도 같은 모드끼리 잇는다). 「두께가 늘면 1차 공진이 어떻게
    되나」 같은 물음에 답하는 자리다."""
    got = await _get(ctx, f"/api/simulations/studies/{study_id}")
    if isinstance(got, dict) and isinstance(got.get("points"), list):
        got["points"] = [_compact(one) for one in got["points"]]
    return got


@mcp.tool()
async def study_publish(ctx: Context, study_id: str, unpublish: bool = False) -> Any:
    """스터디의 끝난 설계점을 한꺼번에 **게시**한다(내가 건 점만) — 조직의 누구나 읽는다.
    `unpublish=true` 면 해제한다. **사람이 판단할 일이다** — 사용자가 시킬 때만 부른다."""
    action = "unpublish" if unpublish else "publish"
    return await _post(ctx, f"/api/simulations/studies/{study_id}/{action}")


@mcp.tool()
async def convergence_start(
    ctx: Context,
    job_id: str,
    ratios: list[float] | None = None,
    solver: str | None = None,
) -> Any:
    """끝난 작업을 **요소 크기만 바꿔** 다시 건다 — 수준마다 작업 하나(메시 수렴 점검).

    `ratios`: 원래 대비 비율 1~4개(0.1~2, 1 보다 작으면 촘촘하게). 비우면 [0.7, 0.5].
    CAD 가 정한 파트 · 면 크기도 같은 비율로 줄인다. `solver` 를 비우면 원래 작업의 솔버 —
    솔버를 바꾸면 솔버 차이(몇 %)가 메시 차이로 읽히므로 판정은 한 솔버끼리만 한다. 수준
    작업이 끝나면 `convergence_get` 으로 판정을 읽는다."""
    body: dict[str, Any] = {"ratios": ratios or [0.7, 0.5]}
    if solver:
        body["solver"] = solver
    return await _post(ctx, f"/api/simulations/{job_id}/convergence", body)


@mcp.tool()
async def convergence_get(ctx: Context, job_id: str) -> Any:
    """메시 수렴 판정 — 크기마다 값과 값마다 판정(수렴 · 미수렴 · 판정 보류 · 발산 · 수준 부족,
    GCI). 원래 작업이나 수준 작업 어느 쪽 id 로 물어도 같다. **발산은 고장이 아니라** 그 값
    (대개 구속 모서리의 첨두응력)으로 판단하지 말라는 뜻이다."""
    return await _get(ctx, f"/api/simulations/{job_id}/convergence")


@mcp.tool()
async def measurements_get(
    ctx: Context, job_id: str | None = None, study_id: str | None = None
) -> Any:
    """작업(또는 스터디)에 붙은 실측과 **이 결과와 견준 것** — 측정점마다 실측 대 해석, 공진
    짝(센서 자리에서 안 움직이는 모드는 뺀다), 차이를 설명하는 영률 · 감쇠비 제안. 스터디면
    설계점마다 점수와 **실측에 가장 가까운 설계점**. 둘 중 하나만 준다."""
    if (job_id is None) == (study_id is None):
        return {"error": "job_id 와 study_id 중 하나만 줍니다."}
    path = (
        f"/api/simulations/{job_id}/measurements"
        if job_id is not None
        else f"/api/simulations/studies/{study_id}/measurements"
    )
    return _listed(await _get(ctx, path), "measurements")


@mcp.tool()
async def measurement_add(
    ctx: Context,
    table: str,
    job_id: str | None = None,
    study_id: str | None = None,
    label: str | None = None,
) -> Any:
    """실측 표를 작업(또는 스터디)에 붙인다 — 붙이면 곧바로 견준다(`measurements_get`).

    `table` 은 표 한 장(CSV · 탭으로 가른 줄 · JSON 배열). 열: 측정점(CAD 점 그룹 이름) ·
    종류(공진 · FRF · 변위 · 변형률) · 주파수(Hz) · 값 · 단위(변위 m · mm · um, 가속도
    m/s2 · g, 변형률 비움 · ue) · 성분(x · y · z · 크기). 사람이 준 숫자를 **지어내지
    않는다** — 받은 그대로 옮긴다. 둘 중 하나만 준다."""
    if (job_id is None) == (study_id is None):
        return {"error": "job_id 와 study_id 중 하나만 줍니다."}
    path = (
        f"/api/simulations/{job_id}/measurements"
        if job_id is not None
        else f"/api/simulations/studies/{study_id}/measurements"
    )
    stripped = table.lstrip()
    name = "실측.json" if stripped.startswith(("[", "{")) else "실측.csv"
    return await _post_file(
        ctx, path, (name, table.encode("utf-8"), "text/plain"), {"label": label}
    )


if __name__ == "__main__":
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    mcp.settings.host = host
    mcp.settings.port = int(os.environ.get("MCP_PORT", "8072"))
    if host not in ("127.0.0.1", "localhost", "::1"):
        # FastMCP 는 localhost 로 고정된 DNS rebinding 보호를 켠다 — 다른 주소로 열면 421
        # 이 난다. 허용 Host 를 주거나(권장 — HWAX 게이트웨이가 부르는 `<주소>:<포트>`
        # 까지) 보호를 끈다(사내망 · 방화벽 뒤, 인증은 백엔드가 토큰으로 한다).
        from mcp.server.transport_security import TransportSecuritySettings

        allowed = [
            one.strip()
            for one in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",")
            if one.strip()
        ]
        mcp.settings.transport_security = (
            TransportSecuritySettings(
                enable_dns_rebinding_protection=True, allowed_hosts=allowed, allowed_origins=[]
            )
            if allowed
            else TransportSecuritySettings(enable_dns_rebinding_protection=False)
        )
    mcp.run(transport="streamable-http")
