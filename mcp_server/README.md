# SimEngBay MCP 서버

AI(Claude Code · Claude Desktop · HWAX 포털의 Claude)가 해석 작업을 걸고, 결과를 읽고, 설계점끼리 ·
실측과 견주게 하는 도구. 결정과 까닭은 [ADR 0010](../docs/adr/0010-해석용-MCP.md).

- **별도 프로세스 · 별도 venv** — `mcp` 가 백엔드의 HTTP 스택(starlette)과 충돌한다. 백엔드와는 REST 로만.
- **사용자의 토큰으로** — 들어온 `Authorization` 을 그대로 백엔드에 넘긴다. 권한 · 범위 · 검증은 전부
  백엔드가 한다(MCP 에 규칙을 두지 않는다).
- **CompCore 에서 온 것을 id 로 찾는다** — CompCore 가 내보낸 스터디 폴더(`<이름>-<id 앞 8자리>`)를 그 스터디
  id 나 이름으로 찾는다(`folder_find`, 백엔드 `GET /simulations/doe/find`). 사용자는 공유 폴더 경로를 몰라도 된다.
  `jobs_create` · `folder_preview` 는 CompCore 의 `study_id` 를 그대로 받고, CompCore 가 준 Windows 경로(`F:\…\<이름>-<id8>`)를
  넘겨도 그 꼬리로 찾는다.
- **해석이 늘어도 그대로** — 입력 칸은 `recipe_schema`(백엔드의 `GET /simulations/recipes`), 결과는 서버가
  단위를 맞춘 견줄 값(`GET /simulations/{id}/values`, 늘 mm · MPa · N · Hz).

## 도구(27)

| 흐름 | 도구 |
| --- | --- |
| 안내 · 나 | `get_guide` · `whoami` · `recipe_schema` |
| CAD 폴더 | `folder_find`(CompCore 스터디 id · 이름으로 — 경로를 몰라도) · `folder_browse` · `folder_preview`(스터디 · 설계점 하나 — 조건이 어떻게 걸리나) |
| 걸기 · 보기 | `jobs_create` · `jobs_list` · `job_get`(기다리기) · `job_result` · `job_retry` · `job_cancel` · `study_cancel`(DOE 통째로) · `study_rerun`(DOE 를 모드 수만 바꿔 다시) |
| 견주기 | `studies_list` · `study_get` · `study_analyze`(민감도 · 주효과 · 조건을 건 최적점 — 서버가 셈한다) · `convergence_start` · `convergence_get` · `measurement_add` · `measurements_get` |
| 서버 · 정리 | `server_status`(솔버마다 워커 · 줄, 관리자는 워커까지) · `files_tidy`(중간 파일 — 사용자가 시킬 때만) · `jobs_folders` · `jobs_move`(사람이 나눈 정리 폴더 — CAD 공유 폴더와 다르다) |
| 게시 | `job_publish` · `study_publish`(사용자가 시킬 때만) |

안내서 본문은 `guide/GUIDE.md` — `get_guide` 가 `<!--@ 주제 -->` 로 갈라 준다. **서버가 쥔다**(고치면 재시작
없이 다음 호출부터).

위험 도구(`DESTRUCTIVE_TOOLS` — `job_cancel` · `study_cancel` · `files_tidy`)는 HWAX 게이트웨이의 범용 실행기가 막도록 요청서에 적는다.
목록을 바꾸면 `docs/[참고] HWAX포탈_연동_요청서.md` 의 7절도 — 시험이 둘을 견준다.

## 개발 PC 에서

```bash
cd mcp_server
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt pytest
PLATFORM_API_BASE=http://127.0.0.1:8071 ./venv/bin/python server.py     # 127.0.0.1:8072/mcp
```

Claude Code 에 붙이기(토큰은 화면 「내 정보」 에서 — 해석을 걸려면 `simulations:write` 범위도):

```bash
claude mcp add --transport http simengbay http://127.0.0.1:8072/mcp \
  --header "Authorization: Bearer simengbay_pat_…"
```

화면의 「내 정보 › AI 도구 연결」 이 이 설치의 주소와 토큰으로 채운 명령(Claude Code · Desktop · Gemini · Codex)을
준다.

## 시험

```bash
mcp_server/venv/bin/python -m pytest mcp_server/tests        # 진짜 mcp — 등록 · 헤더 · 401 신호 · 경로
cd backend && .venv/bin/pytest tests/api/test_mcp_tools.py    # 가짜 mcp + 진짜 앱 — 권한 · 범위 · 한 바퀴
```

환경을 가르는 까닭: `mcp` 를 백엔드 환경에 깔면 `starlette.testclient` 의 HTTP 스택이 바뀐다.

## 운영

`deploy.sh` 가 번들의 `mcp_server/`(동봉 휠로 오프라인 설치)를 `<설치 폴더>/mcp_server` 에 놓고 유닛
`<slug>-mcp` 를 띄운다(기본 `0.0.0.0:<앱 포트+2>` — 밖의 Claude · HWAX 게이트웨이가 부른다). 서버 안에서만
쓰려면 `MCP_HOST=127.0.0.1` —
운영 안내서 9절.

| env | 뜻 |
| --- | --- |
| `PLATFORM_API_BASE` | 백엔드 주소(유닛이 채운다 — `http://127.0.0.1:<앱 포트>`) |
| `MCP_HOST` · `MCP_PORT` | 여는 주소 · 포트 |
| `MCP_ALLOWED_HOSTS` | 외부에 열 때 받을 Host(쉼표, 포트까지) — 비우면 DNS rebinding 보호를 끈다 |
| `MCP_JSON_RESPONSE=1` | SSE 를 버퍼링하는 프록시 뒤에서 단발 JSON 응답으로 |
| `APP_SLUG` | 클라이언트에 보이는 서버 이름 |
