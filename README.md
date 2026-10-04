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
| **정적 · 선응력 · 조화** | 정적은 변형 · 상당응력(실측 5.204e-4 mm · 2.523 MPa), 선응력 모달은 조여 놓은 상태의 공진, 조화는 주파수를 훑으며 흔든 곡선(60 kHz 에서 18배로 솟고, 감쇠 2%→5% 로 봉우리가 2.46배 낮아진다). 앞선 해석의 덱(`upstream.dat`)을 먼저 푼다 |
| **솔버 둘 · 고를 수 있다** | `ansys`(기본) 또는 `calculix`. CalculiX 는 **라이선스 없이 리눅스 서버에서 바로** 돈다(gmsh 로 메시 · `ccx` 로 풀기 — 모달 · 정적 · 조화). 같은 설계점에서 1차 굽힘이 Ansys 1,266.4 Hz · CalculiX 1,263.5 Hz(0.23% 차이, 실측) — 교차 검증 시험이 그 폭을 지킨다. 못 거는 조건은 **까닭과 함께 거절**한다 |
| **설계점 비교** | 스터디마다 바꾼 변수 대 고유진동수 · 질량. **모드를 형상(MAC)으로 이어** 견준다 — 치수가 바뀌면 모드 순서가 뒤바뀌므로 순번으로 이으면 다른 모드를 잇는다. 정적 · 조화 스터디는 최대 변형 · 상당응력 · 반력 · 측정점 · 상대 변위(미끄럼) · 봉우리를 견주고(봉우리 주파수는 잇지 않는다), **CSV 로 내보낸다**(늘 mm · MPa · N · Hz) |
| **측정점 · 반력** | CAD 가 점 그룹으로 보낸 자리(센서 자리)의 값 — 모달은 「그 자리에서 어느 모드가 보이나」, 정적은 변위 성분 · 수직 변형률과 같은 자리 두 바디의 상대 변위, 조화는 그 자리의 곡선과 봉우리. 절점이 1 mm 넘게 떨어지면 그 사실을 적는다 |
| **메시 수렴 점검** | 끝난 작업을 요소 크기만 바꿔 다시 풀고(크기마다 작업 하나 — CalculiX 워커가 동시에 푼다) 값마다 **관측 차수 · 외삽값 · GCI** 로 판정한다. 첨두응력의 「발산」 은 특이점이라고 적는다 |
| **실측과 맞추기** | 공진 · FRF · 변위 · 변형률을 한 표로 올려 **측정점 이름으로** 견준다. 센서 자리에서 안 움직이는 모드와는 짝을 짓지 않고, 차이를 영률(f ∝ √E) · 감쇠(봉우리 ∝ 1/2ζ, 반전력 대역)로 설명한다. 스터디에 붙이면 실측에 가장 가까운 설계점을 고른다 |
| **워커 · 솔버 상태** | 서버 화면에서 워커가 살아 있나(15초 신호 · 2분이면 응답 없음) · 무엇을 집나 · 깔린 도구 · Ansys 라이선스를 쥔 작업. 집을 워커가 없는 솔버의 대기를 빨갛게 적고, 작업을 거는 창도 미리 말한다 |
| **취소 · 정리** | 돌던 작업을 멈춘다(워커가 2초 안에 본다). 끝난 작업의 중간 파일(`.mechdb` · `.rst` · 솔버 scratch)을 지우고 결과는 남긴다 |
| **DOE 가져오기** | CAD 가 내보낸 폴더 한 벌(`manifest.csv` · 점마다의 STEP · 지문)을 읽어 설계점마다 작업을 만든다. **솔버 · 해석 종류**를 고르고(해석 종류는 CAD 가 적은 것을 미리 고른다), **설계점을 골라** 걸 수 있다. 첫 점의 조건이 고른 해석 종류에서 어떻게 다뤄지나(반영 · 넘김 · 막음)를 먼저 보여 주고, 걸 수 없는 점은 **이유와 함께** 건너뛴다. 물성은 점마다 CompCore 가 파트에 정한 것을 쓴다 — 물성을 안 보낸 폴더는 실행하지 않는다 |
| **새 해석 작업** | 기본은 **CAD 폴더에서 설계점 하나 선택** — DOE 창과 같은 탐색기로 공용 폴더를 열고, CompCore 가 낸 설계 하나(v0.9.0 「해석용으로 내보내기」, 인자 0개)나 DOE 의 설계점 하나를 고른다. STEP · 점 파일 · 중간면이 폴더에서 짝이 맞게 따라오고, 서버가 그 점 파일을 읽어 해석 종류 · 요소 크기 · 조건과 **파트마다 붙을 재료**를 보여 준다. 공용 폴더에 없는 파일은 「파일 직접 업로드」. 물성은 CompCore 가 정하므로 창에 물성 칸이 없다 — 물성이 없거나 재료가 빠진 파트가 있으면 실행하지 않는다 |
| **파트별 설정** | CompCore 의 `body_settings` — 파트마다 **강체 · 해석 제외 · 파트 메시**(요소 크기 · 형상 · 차수). 두 솔버 모두: Ansys 는 `StiffnessBehavior.Rigid` · `Suppressed` · Body Sizing, CalculiX 는 메시 전에 gmsh 로 부피를 재 짝지은 뒤 빼고(`Recursive Delete`) 크기를 주고 `*RIGID BODY` 로 묶는다. 강체 받침판 1차 Ansys 1,289.3 · CalculiX 1,289.0 Hz(실측). 강체 면에는 고정 지지 · 원격 변위만, 강체 면의 하중은 막는다. **쉘**은 CAD 의 중간면(`pNNNN_mid.step`)과 두께로 푼다 — Ansys 는 면 바디 + `Thickness`, CalculiX 는 `S6` + `*SHELL SECTION`(결과는 펼친 겉면에서 접어 읽는다). 판금 브래킷 t2 끝 처짐 Ansys 0.3236 · CalculiX 0.3223 · 솔리드 0.3203 mm, 반력 66.0 N(손셈 66) |
| **구속 조건** | CAD 가 보낸 영역 지문(`topology.json`)으로 형상에서 면을 다시 찾아 고정한다 — 볼트 구멍 넷을 고정한 브래킷이 1,519 Hz. 못 찾으면 **즉시 실패**한다 |
| **결과 보기** | 고유진동수 표(쪽 나누기) · 그림 셋(**스펙트럼** · 누적 유효질량 · 모드별 막대) · 모드 썸네일 · 3D 뷰어(vtk.js, 회전 · 컬러바 · 모드 형상 애니메이션). 조화는 응답 곡선 · 봉우리 · 감쇠비를 함께 보여 준다 — 봉우리가 훑은 범위의 끝에 붙으면 범위를 넓히라고 말한다. 뷰어는 결과 화면에서만 받는다 |
| 인증 | 로그인, 세션 회전(refresh httpOnly 쿠키), 강제 비밀번호 변경, 개인 액세스 토큰(PAT) — 스크립트 · AI 도구가 이것으로 붙는다 |
| 계정 | 셀프 가입 → 관리자 승인/거절, 정지·활성, 임시 비밀번호 발급, 시스템 관리자 지정 |
| 부서 | 트리형 조직도(상위/순서/보관), 멤버와 역할, 삭제 전 참조 확인, 통폐합, CSV 내보내기 |
| 권한 | 시스템 역할 × 부서 역할 두 축, 부서 소유 자산 판정 헬퍼 |
| 화면 | 사이드바·헤더·테마(라이트/다크)·부서 전환·shadcn 프리미티브·차트 층 |
| 첨부 | 파일 올리기·내려받기, 내용 해시로 중복 제거, 부서 단위 권한 |
| 운영 | 공지(팝업 포함), 알림(하나씩 읽음), 감사 로그(한 일 · 대상 표로 거르기), 접근 로그(시스템 관리자), 서버 상태 화면 |
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

### 오픈소스 솔버 (CalculiX)

CalculiX 경로는 WSL(리눅스) 쪽에서 돈다 — `windows-bridge` 여도 Windows 로 넘기지 않는다. 개발
PC 에는 직접 깐다(운영 이미지에는 `deploy/apptainer.def` 가 넣는다):

```bash
sudo apt-get install -y --no-install-recommends gmsh calculix-ccx
```

깐 뒤 워커를 다시 띄운다 — **워커는 기동할 때 깔린 도구를 보고 집을 솔버를 정한다**
(`SIMULATION_SOLVERS` 가 비었을 때). 없으면 CalculiX 작업을 집지 않고 대기열에 남기며, 작업을
거는 화면이 「집을 워커가 없다」 고 경고한다. `tests/opensolver` 도 이 둘이 있어야 돈다.

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
sudo APP_SLUG=simengbay APP_NAME=SimEngBay APP_PORT=8070 ./deploy.sh prepare   # 최초 1회
sudo APP_SLUG=simengbay ./deploy.sh install                                         # 첫 설치
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
