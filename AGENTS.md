# 개발 지침

이 저장소에서 코드를 고칠 때 지키는 규칙.

**이 파일이 정본이다.** `CLAUDE.md` 는 이 파일을 가리키기만 한다 — 두 벌로 두면
한쪽만 고쳐지고, 그때부터 사람마다 다른 규칙을 따르게 된다.

## 이 저장소가 무엇인가

**SimEngBay — CAD 형상 · 물성 · 경계조건을 받아 Ansys Mechanical FE 모델을 자동으로
만들고, 솔버에 넘긴 뒤 결과를 추출해 돌려주는 플랫폼.**

[StandardPlatform](../StandardPlatform) 을 포크했다([ADR 0005](docs/adr/0005-StandardPlatform-을-포크한다.md)).
가져온 것은 도메인이 무엇이든 매번 다시 만들게 되는 것들이다:

    로그인 · 세션 · 가입 승인 · 계정 · 개인 액세스 토큰(PAT)
    부서(조직도) · 권한 두 축 · 사이드바 · 공지 · 알림 · 감사 · 접근 로그 · 첨부 · 서버 상태
    Apptainer 배포 · 백업 · 이중화 스크립트

**가져오지 않은 것**: 온톨로지 · 객체 · 지식 그래프 · RDF · 검색 · 웹훅 · 데이터 소스 · MCP
서버 · 정제 파이프라인. 이 플랫폼의 도메인은 「해석 작업(job)」 이고 그것은 정의를 데이터로
얹는 온톨로지 모델과 맞지 않는다.

공통 틀 위에 **해석 작업(job)의 뼈대**가 올라가 있다(로드맵 1단계) — 형상을 올려 작업을 걸면
워커가 네 단계(형상 준비 · 모델링 · 솔버 · 추출)를 돌리고 산출물을 남긴다. 단계를 **어디서**
돌리는지는 실행기(`SIMULATION_EXECUTOR`)가 정하고, 지금 있는 것은 `fake` 하나다 —
PyMechanical · DPF 는 1.5단계부터다. 무엇을 어떤 순서로 만드는지는
[docs/로드맵.md](docs/로드맵.md), 실행 단위는 [docs/해석-연동-계획.md](docs/해석-연동-계획.md) 에 있다.

## 층

    backend/app/modules    API. 모듈 하나가 표 · 스키마 · 서비스 · 라우트를 갖는다.
    backend/app/shared     인증 · 오류 · 권한 · 로그 · 파일 저장소 — 모듈이 함께 쓰는 것.
    backend/app/extensions 설치가 `.env` 의 EXTENSIONS 로 켜는 확장 모듈(본보기 `sample`).
    frontend/src/modules   화면. 모듈 이름은 백엔드와 같다.

    backend/app/core       해석 코어 — 스펙 · 단계 · 실행기. 웹 · DB 를 모른다.
    backend/app/worker.py  DB 큐에서 작업을 집어 core 를 돌리는 프로세스.

**`core` 는 `fastapi` · `sqlalchemy` · `app.modules` · `app.shared` 를 import 하지 않는다.**
그래야 스크립트와 단위 시험이 서버 없이 코어만 돌린다 — 모델링 스크립트를 고칠 때마다 DB 를
띄우면 아무도 안 고친다. AutoJigGenerator 의 `app/core` 가 같은 규칙으로 되어 있다.

## 도메인을 얹는 자리

공통 틀에는 도메인을 모르는 화면이 있고, 그것은 **레지스트리**로 채워진다. `shared` 가
도메인 모델을 import 하면 방향이 거꾸로 서고, 그때 import 순서 하나로 서버가 안 뜬다 —
그래서 **도메인이 등록하고 공통이 부른다.**

| 화면 | 등록 지점 |
| --- | --- |
| 홈의 「남은 일」 | `extensions.register_maintenance` |
| 서버 화면의 「쌓인 것」 | `extensions.register_stats` |
| 부서 삭제 확인 | `extensions.register_workspace_reference` |
| 부서 통폐합 때 옮길 자료 | `extensions.register_workspace_content` |
| 기계 자격(PAT)의 쓰기 경로 | `scopes.register_write_scope` |

첨부는 등록이 필요 없다 — `owner_table`·`owner_id` 로 **느슨하게 가리키므로** 도메인이
무엇이든 `AttachmentList` 를 한 줄 끼우면 된다. 그 자료의 소유 부서를 `workspace_slug` 로
함께 준다: 안 주면 전역이 되고, 전역은 시스템 관리자만 만진다.

등록은 **`app/main.py` 의 `_register_extensions()` 한 곳**에서 한다. 라우터도 같은 파일의
`_api_router()` 에서만 모은다. 조립 지점이 하나여야 "이게 왜 안 뜨지" 를 물을 자리가 생긴다.

**등록하지 않으면 안 뜬다.** 특히 부서 참조가 그렇다 — 안 걸면 부서를 지울 때 그 표는
목록에 안 나타나고, 사람은 아무것도 안 걸린 줄 안다.

## 화면 용어

화면에 쓰는 말은 [docs/용어.md](docs/용어.md) 가 정본이다 — **명사형 이름, 공식 동사**(수정 · 삭제 ·
추가 · 선택 · 클릭 · 업로드 · 다운로드 · 표시 · 게시 · 해제). 「고치다 · 지우다 · 넣다 · 누르다 · 걸다」 같은
구어는 화면 문구에 쓰지 않는다(코드 주석은 예외). 새 문구를 적을 때 표에 없는 개념이면 표에 먼저 더한다.

## 이름과 식별자

- 기본 이름은 `backend/app/branding.py` · `frontend/src/shared/branding.ts` 의 **한 쌍**이다
  (`SimEngBay` · `simengbay` · `SEB`). 설치는 `.env` 의 `APP_SLUG` · `APP_NAME` ·
  `APP_TAGLINE` · `EXTENSIONS` 로 덮을 수 있다. 코드는 `get_settings().app_name` 으로 읽고
  화면은 서버가 심는 `<meta name="app-*">` 로 받는다 — `branding` 에서 이름을 import 하지
  않는다(`config.py` 만 예외). 구조 시험이 막는다.
- **DB 이름·refresh 쿠키 이름·PAT 표식은 따로 적지 않는다.** 셋 다 `APP_SLUG` 에서
  나온다. 따로 적으면 언젠가 하나가 안 바뀌고, **안 바뀐 하나는 전부 조용한 사고로
  나타난다**: 같은 DB 를 보면 오류 없이 남의 `users` 표를 읽고, 같은 쿠키 이름이면
  번갈아 로그아웃되고, 같은 토큰 표식이면 「형식은 맞는데 인증이 안 되는」 상태가 오타와
  구별되지 않는다. **설치 뒤에는 바꾸지 않는다.**
- **포트는 8070 (개발 8071 · 8072 예약 · Vite 5240).** 플랫폼마다 10씩 벌린다 — MatNexus 8010,
  TestScope 8020, CrossAXTF 8030, StandardPlatform 8040, PartTrace(예약) 8050, AutoJigGenerator
  8060. 정본 표는 `StandardPlatform/docs/새-플랫폼-만들기.md` 3.6 이고 이 플랫폼도 거기 적혀
  있다. 겹치면 개발 백엔드를 내린 순간 프론트 프록시가 옆 플랫폼의 설치본에 붙고, 화면은
  그 사실을 아무 데도 말하지 않는다. Apptainer 는 호스트 네트워크라 포트 매핑으로 덮을 자리가 없다.
- 오류 코드는 `errors.code("MODULE", n)` 로만 만든다(`SEB-AUTH-0001`). 손으로 이으면 시험이 잡는다.

`tests/unit/test_branding.py` 가 위를 검사한다.

## 구조

- **모듈 이름은 백엔드와 프론트가 같다.** `app/modules/<name>` <-> `frontend/src/modules/<name>`.
  예외는 `tests/architecture/test_boundaries.py` 에 **사유와 함께** 적는다.
- **모듈끼리 라우터를 직접 부르지 않는다.** 조립 지점은 `app/main.py` 하나다.
  모델은 서로를 참조해도 된다(FK 는 본질적으로 그렇다). 로직 공유는 `shared` 를 거친다.
- **`shared` 는 도메인 라우터를 모른다.** 방향은 shared -> 모듈 한 쪽이다.
- **코어(`modules` · `shared`)는 확장(`app/extensions`)을 import 하지 않는다.** 끈 인스턴스에서
  코어가 안 뜨게 되고, 그것은 확장을 켠 개발 PC 에서는 안 드러난다.
- 권한 판정은 `shared/permissions.py` 한 곳에서 한다. 각 쿼리에 흩뿌리면 "목록에는 보이는데
  상세는 403" 같은 어긋남이 생기고, 그때 어느 쪽이 맞는지 알 방법이 없다.

## 권한의 두 축

**시스템 역할과 부서 역할은 다른 축이다.** 섞으면 화면이 설명할 수 없게 된다.

    is_system_admin  전사. 계정·부서 자체를 만들고 지운다
    부서 manager     그 부서 안에서만. 멤버와 그 부서 소유 자료를 관리한다

부서가 소유하는 표에는 `owner_workspace_id`(nullable) 한 칸을 둔다. **NULL 은 전역**이고 —
여러 부서가 함께 쓰므로 고치는 것은 시스템 관리자뿐이다. 그러면 `visible_owner_clause` ·
`resolve_owner_workspace` · `require_owner_edit` 가 그대로 붙는다.

**보이는 것과 고칠 수 있는 것은 다른 축이다.** 해석 작업은 다른 부서 것도 보이는 편이
맞다(`open_owner_clause`) — 「우리 조직에 이 형상의 모달 해석이 있나」 에 답할 수 있어야
같은 해석을 두 번 안 돌린다. 쓰기는 그것과 무관하게 여전히 소유 부서의 관리자다.

## 데이터

- 새 ORM 모델을 만들면 **`app/all_models.py` 에 import 를 추가**한다. 빠뜨리면
  autogenerate 가 **기존 표를 지우는** 마이그레이션을 만든다. `tests/architecture` 가 검사한다.
- 지우지 않는다. 계정은 `deleted_at` 만 채우고, 부서는 `is_active=false` 로 보관한다.
  해석 작업과 결과 파일도 같은 규칙이다 — 그것으로 만든 보고서가 밖에 남아 있다.
- 삭제·이관 기능을 만들기 전에 **무엇이 그것을 가리키는지 보여 주는 자리**를 먼저
  둔다(`workspaces` 의 `references`). 누르기 전에 아는 것이 이 저장소의 무늬다.
- **행은 마이그레이션에 넣지 않는다.** 첫 부서·관리자는 설치 시드(`scripts/seed_install.py`)가
  심는다. 마이그레이션에 넣으면 모델로 표를 만드는 시험이 그 행을 못 받는다.
- 마이그레이션은 `0001_initial` 하나에서 시작한다 — StandardPlatform 의 사슬을 잇지 않았다.
  다음 것부터 `alembic revision --autogenerate` 로 만들고 **그 자리에서** `upgrade head` · `check`.

## API

- 성공 응답은 리소스 그대로, 오류만 봉투(`{"error": {code, message, request_id, details}}`).
- **오류 본문을 라우트에서 직접 만들지 않는다.** `AppError` 계열을 raise 한다 —
  응답을 만드는 경로가 곧 로그를 남기는 경로여야 한다.
- **부분 수정에서 "안 보낸 것" 과 "비운 것" 을 구별한다**(`model_dump(exclude_unset=True)`).
- 목록 엔드포인트에는 서버가 상한을 강제한다(`shared/pagination.py`).
- 스키마를 바꿨으면 `python scripts/export_openapi.py` 와 `npm run api:types` 를 함께 돌린다.
  **프론트 타입을 손으로 적지 않는다** — 어긋난 날 화면은 아무 말도 안 하고 undefined 를 그린다.
- **폴링 경로를 만들면 `shared/access_log.py` 의 `_SKIP` 에 더한다.** 작업 상태 폴링이
  곧 생긴다 — 안 더하면 접근 로그가 그 한 줄로 가득 찬다.
- **기계가 쓰는 경로는 `scopes.register_write_scope` 로 연다.** 스크립트 · AI 도구가 PAT 로
  붙는다. 안 열면 PAT 로는 못 고친다 — 「모르는 것은 막는다」 가 맞는 기본값이다.

## 프론트

- 스타일은 Tailwind 유틸리티로 컴포넌트에 붙인다. 전역 CSS 클래스를 새로 만들지 않는다.
- API 절대주소를 코드에 넣지 않는다. 항상 상대경로 `/api`.
- **사이드바(`shared/layout/navigation.ts`)가 화면 목록의 정본이다.** 아직 없는 화면은
  `pending` 으로 두면 라우터가 stub 을 만든다. `routes/router.test.tsx` 가 어긋남을 잡는다.
- **역할 판정은 `shared/auth/roles.ts` 한 곳에서.** 표시일 뿐 권한이 아니다 — 권한은 서버가 판정한다.
- **상태의 말과 색은 `StatusBadge` 가 정한다.** 작업 상태(대기 · 모델링 · 솔버 · 추출 · 완료 ·
  실패)도 여기서 정한다 — 화면마다 색을 고르면 같은 「실패」 가 목록과 상세에서 다른 색이 된다.
- **그림은 `shared/charts` 가 그린다.** recharts·plotly 를 화면에서 직접 import 하지 않는다.
  흔한 넷(막대 · 꺾은선 · 영역 · 원)은 `Chart`, 가로축이 **수치**인 줄기 그림은 `Spectrum`,
  무거운 것(히트맵 · 3차원)은 `LazyPlot` 이며 후자는 **쓰는 화면에서만 받는다.**
- **가로축에 무엇을 둘지가 그림의 물음을 정한다.** 모드 번호를 축에 두면 막대는 늘 단조 증가하는
  계단이고 그 물음에는 표가 더 잘 답한다 — 주파수를 축에 둬야 「어느 대역에 무엇이 있나」 를
  묻는 그림이 된다(`Spectrum`). 새 그림을 붙일 때 먼저 물음을 적어 본다.
- **3D 뷰어가 생기면 `shared/viewer` 에 두고 `lazy()` 로 받는다.** three · vtk.js 한 덩어리가
  수백 KB 다 — 결과를 안 보는 화면까지 매번 받을 이유가 없다(AutoJigGenerator 와 같은 규칙).
- **빈 목록은 이유를 말한다**(`EmptyState`). **되돌릴 수 없는 일은 무엇이 사라지는지 적는다**
  (`ConfirmDialog`). **`window.prompt` 를 쓰지 않는다.**
- **고를 것이 스물을 넘으면 `<Select>` 를 쓰지 않는다**(`SearchablePicker`).
- **목록에는 쪽 넘기기를 붙인다**(`Pagination`). 서버가 상한을 강제하므로 없으면 50건이
  넘는 순간 나머지를 볼 방법이 없다.
- **본문은 오류 경계 안에 있다**(`ErrorBoundary`, AppShell 이 두른다). 사이드바까지 감싸지
  않는 이유는 나갈 길은 살아 있어야 해서다.
- 내려받기는 `downloadFile` 로 — access 토큰이 메모리에만 있어서 `<a href>` 에는 안 실린다.

## 스크립트와 배포

배포는 리눅스 · Apptainer 단일 이미지다([ADR 0004](docs/adr/0004-리눅스-Apptainer-배포.md)).
`deploy/` 는 **산출물이 아니라 정본**이다 — `.gitignore` 로 덮지 않는다.

- 셸 스크립트는 `#!/usr/bin/env bash` + `set -euo pipefail` 로 시작한다.
- **실행 비트를 지킨다.** Windows 쪽(`\\wsl.localhost\...`)에서 고치면 모드가 644 로 떨어지고,
  **다음 배포에서** `Permission denied` 로 죽는다. `tests/architecture/test_deploy.py` 가 검사한다.
- **줄바꿈은 `.gitattributes` 가 정한다.** CRLF 셸 스크립트는 리눅스에서
  `bad interpreter: /usr/bin/env bash^M` 로 죽는데 눈으로 보면 멀쩡하다. 같은 시험이 검사한다.
- **릴리스는 태그에서 나온다**(`.github/workflows/release.yml`). 검증(`ci.yml`)을 통과해야 게시된다.
- **번들에 담기는 것은 `build_bundle.sh` 가 정본이다.** `README_OPERATOR.md` 가 번들 안에서
  시키는 명령은 번들 안에 있어야 한다.
- **배포 자산에 제품 이름을 박지 않는다.** 번들은 `branding.py` 의 기본값만 `BUILD_INFO` 에
  들고, 실제 이름 · 포트 · 확장은 설치가 `deploy.sh` 에 env 로 준다.
- `deploy.sh` 에는 MCP 서버 · 동기화 타이머 자리가 남아 있다 — 번들에 `mcp_server/` 나
  `sync.*.template` 이 없으면 **건너뛴다.** 나중에 AI 가 해석을 거는 MCP 서버를 두게 되면
  그 자리를 그대로 쓴다(StandardPlatform 의 `mcp_server/` 가 본보기).
- `.env` 는 **BOM 없이** 저장한다. BOM 이 붙으면 **첫 줄 키만 조용히 무시된다.**
- **`.env` 를 이미지에 굽지 않는다.** bind-mount 로 넣는다.
- **이미지 루트는 읽기 전용이다.** 앱이 쓰는 곳은 `/data/filestore` 와 `/data/logs` 뿐이다.
  해석 작업 폴더(`.mechdb` · `.dat` · `.rst` · 추출 결과)도 `settings.filestore_dir` 아래에 둔다 —
  이미지 안 절대경로를 잡으면 `[Errno 30] Read-only file system` 이 나는데 **그 메시지는
  무엇을 고쳐야 하는지 말해 주지 않는다.**
- **Ansys 는 이미지에 넣지 않는다.** 모델링 워커는 호스트(또는 공유 파일시스템)의
  `/ansys_inc` 를 bind 해서 쓴다([로드맵](docs/로드맵.md)). 이미지에 구우면 수십 GB 가 되고
  버전을 올릴 때마다 다시 굽는다.
- **`pkill -f` 는 자기 명령줄에도 걸린다.** `pkill -f '[u]vicorn'` 처럼 패턴을 비껴 쓴다.

## 해석 작업

- **DB 가 큐다.** `queued` 행을 워커(`python -m app.worker`)가 `FOR UPDATE SKIP LOCKED` 로 집어
  간다. 큐 서버를 두지 않는 이유는 설치 · 백업 · 장애 지점이 하나 더 생기기 때문이다.
  **워커 수 = Mechanical 라이선스 수**(1.5단계부터). 개발은 `run.py` 가 하나를 자식으로 띄우고,
  `JOBS_INLINE=1` 이면 요청 안에서 돈다 — **두 길이 같은 `services.execute` 를 지난다.**
- **단계를 어디서 돌리는지는 실행기가 정한다**(`app/core/executors`, `SIMULATION_EXECUTOR`).
  셋이다: `fake`(시험 · CI — 모양만 맞는 산출물) · `local`(이 기계의 파이썬) ·
  `windows-bridge`(WSL 의 워커가 Windows 파이썬을 부른다 — 개발 PC 의 Ansys 가 거기 있다.
  [계획서 3.1](docs/해석-연동-계획.md)). **실행기는 워커가 기동할 때 한 번 고른다** — 작업을
  집고 나서 죽으면 사람은 설정 오타를 작업 실패로 읽는다.
- **단계는 자식 프로세스에서 돈다**(`app/core/run.py`). 임베디드 Mechanical 은 프로세스당
  하나고 그 프로세스의 .NET 런타임을 붙들기 때문이다 — 워커 안에서 직접 띄우면 작업 하나의
  상태가 다음으로 새고, Mechanical 이 죽을 때 워커가 함께 죽는다. 주고받는 것은 **파일 하나**
  (`.stage-<단계>.json`)다: 자식은 다른 OS 의 다른 파이썬일 수 있고 stdout 은 Ansys 가 제 로그로
  채운다. **부모는 종료 코드가 아니라 그 파일을 믿는다.**
- **Ansys 가 필요한 시험은 표시를 단다**(`@pytest.mark.ansys`, `tests/ansys/`). 기본 실행에서
  빠진다 — 없는 것을 이유로 빨간 줄이 서면 사람은 곧 전체 결과를 안 읽는다. 돌리려면
  `SIMULATION_EXECUTOR=windows-bridge WINDOWS_PYTHON=… .venv/bin/python -m pytest -m ansys`.
- **워커의 파이썬 의존성은 `requirements-worker.txt` 다.** API 이미지에 PyMechanical · DPF 를
  넣지 않는다 — 수백 MB 가 늘고, Ansys 없는 기계(프론트 개발 · CI)에서 설치가 실패한다.
- **실패는 코드로 적는다**(`app/core/stages.py` 의 `FailureCode`). 메시지로만 남기면 워커마다
  다른 문장이 되고, 그때 「라이선스로 몇 건 실패했나」 를 셀 수 없다. **코드를 더하면 화면의
  이름표도 더한다** — `tests/architecture/test_simulation_labels.py` 가 빠진 것을 잡는다.
- **작업 폴더는 `WORK_DIR` 아래고 DB 에는 상대 경로만 둔다.** 절대경로를 넣으면 서버를 옮기는
  날 전부 틀린 값이 된다(첨부와 같은 규칙).
- **결과를 지우지 않는다.** 그것으로 만든 보고서가 밖에 남아 있다 — `deleted_at` 만 채운다.
  중간 파일(`.mechdb` · `.rst` · 솔버 scratch)은 사람이 누르면 지운다(`core/cleanup.py`) —
  그때 **그 파일의 행도 함께 지운다.** 「DB 에는 있는데 파일이 없는」 상태는 내려받기에서 403 으로
  나타나고, 그것은 백업이 잘못된 것과 구별되지 않는다.
- **설계점을 견줄 때 모드를 순번으로 잇지 않는다.** 치수가 바뀌면 모드 순서가 뒤바뀐다
  (mode crossing — 실측: 2차와 4차가 자리를 바꿨다). 모드를 잇는 정본은 주파수가 아니라
  **형상**이고, 그 열쇠가 `result.json` 의 `signature` 다(`core/modes`). **못 이으면 잇지
  않는다** — 억지로 이은 선은 없는 그림보다 나쁘다.
- **`result.json` 이 결과의 정본이다.** 모드 목록 · 단위계 · 참여계수를 표로 옮겨 담지 않는다 —
  두 벌이 되면 언젠가 갈리고, **갈린 쪽을 화면이 그린다.** DB 에는 요약 몇 칸만 둔다(목록에서
  거르고 정렬하는 데 필요한 것). 화면은 `GET /simulations/{id}/result` 로 파일을 읽는다.
- **모드 형상(VTP)의 배열 이름은 두 언어에 걸친 계약이다**(`displacement` · `magnitude`).
  PyVista 가 쓰고 vtk.js 가 읽는데, 한쪽이 바꾸면 화면은 **빈 상자**를 그리고 오류는 안 난다 —
  `frontend/src/shared/viewer/MeshViewer.test.ts` 가 진짜 산출물 한 장으로 그것을 지킨다.

## 검증

고치고 나서 이것을 돌린다.

**마이그레이션을 만들었으면 그 자리에서 개발 DB 에 올린다**(`alembic upgrade head`).
**명령 사슬에 끼워 두지 말 것** — 앞 단계가 실패하면 조용히 안 돈다.

```bash
cd backend
.venv/bin/ruff format . --config pyproject.toml
.venv/bin/ruff check . --config pyproject.toml
.venv/bin/mypy
.venv/bin/python -m pytest
.venv/bin/python -m alembic check
cd ../frontend && npm run build && npm test && npm run lint
```

`alembic check` 가 여기 있는 이유: **시험은 모델로 표를 만들기 때문에** 마이그레이션이
모델과 어긋난 것을 못 잡는다 — 그 어긋남은 배포하고 나서 500 으로 드러난다.

테스트는 개발 `.env` 의 접속 정보에서 `<이름>_test` 를 파생해 쓴다.
**개발 DB 를 건드리는 테스트는 쓰지 않는다.**

**시험이 도는 조건은 그 기계의 `.env` 가 아니라 `tests/conftest.py` 가 정한다.** 실행기도
같다 — 개발 `.env` 에 `SIMULATION_EXECUTOR=windows-bridge` 를 적어 두면(진짜 Ansys 로 돌리려고
그렇게 한다) 시험이 그것을 따라가 **작업 하나에 1분씩 걸리거나 Ansys 없는 기계에서 통째로
빨개진다.** 실측으로 겪었다. 새 설정을 더할 때 「시험이 이걸 따라가면 곤란한가」 를 묻는다.

**시험 DB 는 스위트 하나를 통째로 함께 쓴다.** 필요한 상태를 그 시험이 직접 만든다.

## 문서

- 판단이 갈렸던 결정은 `docs/adr/NNNN-제목.md` 에 남긴다 — 결정·배경·대안·결과.
- 실측으로 드러난 함정은 **근거와 함께** 적는다. "이렇게 하세요" 보다 "이렇게 안
  하면 이런 일이 났다" 가 다음 사람에게 유용하다.
- StandardPlatform 에서 물려받은 문서(`docs/이중화-배포-설계.md` 등)에 MCP · 웹훅 · 데이터
  소스가 나오면 그 부분은 이 플랫폼에 없는 것이다 — 그 문서는 결정의 기록이라 고쳐 쓰지 않는다.
