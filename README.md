# SimEngBay

CAD 형상 · 물성 · 경계조건을 받아 **Ansys Mechanical FE 모델을 자동으로 만들고**, 솔버에 넘긴 뒤
**결과를 추출해 웹에서 보는** 플랫폼.

    CAD 플랫폼(CompCore) ──폴더 한 벌──▶ 이 서버 ◀──STEP 하나──  화면 · PAT
      STEP · topology.json                  │
      conditions.json · manifest.csv        ▼
                          PyMechanical 워커 ── 임포트 · 물성 · 영역 매칭 · 구속 · 메시 ──▶ .dat (+ .mechdb)
                                 │
                          MAPDL(같은 기계 · 다음은 Slurm) ──▶ .rst
                                 │
                          DPF 추출 ── 고유진동수 · 참여계수 · 모드형상 ──▶ JSON · PNG · VTP
                                 │
                          웹 — 단계 타임라인 · 스펙트럼 · 3D 뷰어 · 설계점 비교

**결과는 여기서 본다 — CAD 로 돌려보내지 않는다.** CompCore 는 「CAD 를 DOE 로 만드는 일」 까지
하고, 설계점을 고르는 일(필터 · 파레토)은 이 플랫폼의 몫이다(2026-09-23 합의). 그래서 되물을
API 도, 콜백도 없다 — **폴더 한 벌이 계약이다.**

무엇이 어디까지 됐는지는 [docs/로드맵.md](docs/로드맵.md), 실측과 함정은
[docs/해석-연동-계획.md](docs/해석-연동-계획.md).

[StandardPlatform](../StandardPlatform) 을 포크했다. 개발 규칙은 [AGENTS.md](AGENTS.md) 가 정본이다.

## 기술 스택

| 층 | 도구 |
| --- | --- |
| 백엔드 | FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 · PyJWT · bcrypt |
| 프론트 | React 19 · TypeScript · Vite · Tailwind 4 · shadcn · recharts/plotly(`shared/charts`) |
| 해석 | PyMechanical(임베디드, 2025 R2 확인) · MAPDL 배치 · PyDPF · Apptainer 워커 |
| 검증 | ruff · mypy(strict) · pytest / oxlint · vitest |
| 배포 | 리눅스 · Apptainer 단일 이미지 · systemd · GitHub Actions |

## 지금 되는 것

| 영역 | 들어 있는 것 |
| --- | --- |
| **해석 작업** | 형상(STEP) 업로드 → 작업 큐 → 워커가 네 단계(형상 준비 · 모델링 · 솔버 · 추출) → 산출물. 단계 타임라인 · 실패 코드 · 재시도 · PAT(`simulations:write`) |
| **모달 해석** | PyMechanical 임베디드로 임포트 · 물성 · 메시 · `.dat`, MAPDL 이 풀고, DPF 가 고유진동수를 읽는다. 실행기 `fake` · `local` · `windows-bridge` |
| **DOE 가져오기** | CAD 가 내보낸 폴더 한 벌(`manifest.csv` · 점마다의 STEP · 지문)을 읽어 설계점마다 작업을 만든다. 걸 수 없는 점은 **이유와 함께** 건너뛴다 |
| **구속 조건** | CAD 가 보낸 영역 지문(`topology.json`)으로 형상에서 면을 다시 찾아 고정한다 — 볼트 구멍 넷을 고정한 브래킷이 1,519 Hz. 못 찾으면 **즉시 실패**한다 |
| **결과 보기** | 고유진동수 표(쪽 나누기) · 그림 셋(**스펙트럼** · 누적 유효질량 · 모드별 막대) · 모드 썸네일 · 3D 뷰어(vtk.js, 회전 · 컬러바 · 모드 형상 애니메이션). 뷰어는 결과 화면에서만 받는다 |
| 인증 | 로그인, 세션 회전(refresh httpOnly 쿠키), 강제 비밀번호 변경, 개인 액세스 토큰(PAT) — 스크립트 · AI 도구가 이것으로 붙는다 |
| 계정 | 셀프 가입 → 관리자 승인/거절, 정지·활성, 임시 비밀번호 발급, 시스템 관리자 지정 |
| 부서 | 트리형 조직도(상위/순서/보관), 멤버와 역할, 삭제 전 참조 확인, 통폐합, CSV 내보내기 |
| 권한 | 시스템 역할 × 부서 역할 두 축, 부서 소유 자산 판정 헬퍼 |
| 화면 | 사이드바·헤더·테마(라이트/다크)·부서 전환·shadcn 프리미티브·차트 층 |
| 첨부 | 파일 올리기·내려받기, 내용 해시로 중복 제거, 부서 단위 권한 |
| 운영 | 공지(팝업 포함), 알림, 감사 로그, 접근 로그, 서버 상태 화면 |
| 배포 | Apptainer 이미지·systemd 유닛·설치/갱신/롤백/백업/복구 스크립트, 이중화, GitHub Actions |
| 규약 | 오류 봉투 + 요청 ID, 로그, 페이지네이션(서버 상한 + 화면), 구조 시험 |

## 시작하기

### 준비물

- Python 3.12 (`.python-version`) — 배포 이미지가 ubuntu:24.04 의 `python3.12` 를 쓴다
- Node 20 (`.node-version`)
- PostgreSQL
- Apptainer — 배포 이미지를 만들 때만

### 백엔드

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt

# DB 두 개 — 이름은 APP_SLUG(simengbay). 시험용(_test)까지.
createdb -U postgres simengbay
createdb -U postgres simengbay_test

# .env — 접속 정보만 자기 것으로. **BOM 없이 UTF-8.**
cp .env.example .env

.venv/bin/alembic upgrade head
.venv/bin/python scripts/seed_install.py --email admin --name 관리자
```

시드가 **임시 비밀번호를 화면에 한 번만** 찍는다. 그 계정은 첫 로그인에서 비밀번호 변경이
강제된다. 이걸 안 돌리면 **아무도 로그인할 수 없다** — 가입은 승인이 필요하고 승인할 사람이 없다.

```bash
.venv/bin/python run.py                  # 8071 (개발). 운영은 8070
                                         # 해석 작업 워커(python -m app.worker)도 자식으로 함께 뜬다
```

워커 없이 요청 안에서 돌리려면 `.env` 에 `JOBS_INLINE=1`. 운영에서는 systemd 가 워커를 따로
띄운다(`<slug>-worker@N`, 개수는 `WORKER_COUNT`).

### 진짜 해석을 돌리려면 (Ansys)

기본 실행기는 `fake` 다 — 모양만 맞는 산출물을 내고 Ansys 를 안 부른다. 진짜로 돌리려면 워커의
파이썬에 PyMechanical · DPF 가 있어야 한다. 개발 PC 의 Ansys 가 Windows 에만 있으면 WSL 의 워커가
Windows 파이썬을 부른다([계획서 3.1](docs/해석-연동-계획.md)):

```bash
"/mnt/c/Python312/python.exe" -m venv 'C:\simengbay\venv'
/mnt/c/simengbay/venv/Scripts/python.exe -m pip install -r backend/requirements-worker.txt
```

그 뒤 `backend/.env` 에:

```
SIMULATION_EXECUTOR=windows-bridge
WINDOWS_PYTHON=/mnt/c/simengbay/venv/Scripts/python.exe
WORK_DIR=/mnt/c/simengbay/work
ANSYS_VERSION=252
```

리눅스 워커(운영)는 `SIMULATION_EXECUTOR=local` 이고, Ansys 는 이미지에 굽지 않고 호스트의
`/ansys_inc` 를 bind 한다(`ANSYS_HOST_DIR`).

### 프론트엔드

```bash
cd frontend
npm install
npm run api:types                        # backend/openapi.json → src/shared/api/schema.d.ts
npm run dev                              # 5240 — /api 는 8071 로 프록시
```

API 문서: <http://127.0.0.1:8071/api/docs>

## 검증

```bash
cd backend
.venv/bin/ruff format . --config pyproject.toml
.venv/bin/ruff check . --config pyproject.toml
.venv/bin/mypy
.venv/bin/python -m pytest
.venv/bin/python -m alembic check
cd ../frontend && npm run build && npm test && npm run lint
```

## 포트

플랫폼마다 10씩 벌린다. **SimEngBay 8070** (개발 8071 · 8072 예약 · Vite 5240).
정본 표는 `StandardPlatform/docs/새-플랫폼-만들기.md` 3.6.

## 배포

운영자가 읽는 정본은 [deploy/README_OPERATOR.md](deploy/README_OPERATOR.md).
리눅스 · Apptainer 단일 이미지, 태그를 밀면 Actions 가 검증 뒤 번들을 만든다.

```bash
tar xzf simengbay-v0.1.0.tar.gz && cd simengbay-v0.1.0
APP_SLUG=simengbay APP_NAME=SimEngBay APP_PORT=8070 sudo ./deploy.sh prepare   # 최초 1회
APP_SLUG=simengbay sudo ./deploy.sh install                                         # 첫 설치
sudo ./deploy.sh update                                                            # 그다음부터
```

## 구조

```
backend/
  app/
    branding.py        제품 이름·오류 접두사 — 기본값. 설치는 .env 가 덮는다
    config.py          DB행 -> 환경변수 -> 기본값 3단 fallback
    main.py            **조립 지점.** 라우터·확장·PAT 범위가 전부 여기를 거친다
    all_models.py      Alembic 이 보는 모델 목록. 빠뜨리면 표가 지워진다
    shared/            auth · errors · permissions · extensions · scopes · audit · filestore …
    modules/           accounts · auth · workspaces · notices · notifications · files · audit · server
    extensions/sample  확장 모듈 본보기
  migrations/versions/0001_initial.py
  scripts/             export_openapi · seed_install · set_admin
  tests/               api · unit · architecture(규칙을 시험으로)
frontend/src/
  shared/              branding · api/client · auth/roles · layout/navigation(화면 목록의 정본) · charts · components/ui
  modules/             백엔드와 같은 이름
  routes/router.tsx
deploy/                apptainer.def · deploy.sh · build_bundle.sh · backup/restore · README_OPERATOR.md
docs/
  로드맵.md            해석 도메인을 얹는 순서와 아키텍처 결정
  adr/                 판단이 갈렸던 결정
```
