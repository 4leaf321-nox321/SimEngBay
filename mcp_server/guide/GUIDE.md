# SimEngBay MCP 안내서

GUIDE_VERSION: 2026-11-17

`get_guide` 가 이 파일을 `<!--@ 주제 -->` 로 갈라 준다. **서버가 쥔다** — 고치면 다음 호출부터
그대로 나간다(재시작 없이).

<!--@ overview -->
## SimEngBay 는 무엇을 하나

CAD(CompCore)가 공용 폴더에 내보낸 **설계점**(형상 STEP + 점 파일 — 영역 · 조건 · 물성 · 측정점)에
구조 해석을 걸고, 결과를 읽고, 설계점끼리 · 실측과 견준다.

| 해석(`recipe`) | 묻는 것 | 대표 결과 |
| --- | --- | --- |
| `modal` | 어느 주파수에서 떠는가 | 고유진동수 · 모드 방향 |
| `static` | 하중을 걸면 얼마나 휘고 응력이 얼마인가 | 최대 변위 · 최대 응력 · 반력 · 측정점 값 |
| `harmonic` | 주파수를 훑으며 흔들면 응답이 얼마나 큰가 | 봉우리 주파수 · 진폭 |
| `random` | 가속도 PSD 로 지지부를 흔들면 응답이 보통 얼마인가(1σ) | 측정점 가속도 1σ(Grms) · 최대 1σ 변위 |

솔버는 `calculix`(기본 — 바로 돌고 여러 점을 동시에 푼다)와 `ansys`(라이선스 — 조건을 더 많이
건다). **랜덤 진동은 두 솔버가 다르게 푼다** — `calculix`(기본)는 모드를 풀고 우리가 PSD 를
셈하고(잔여 벡터 · 상당응력 1σ 까지), `ansys` 는 Mechanical 의 Random Vibration 이 푼 1σ 를 읽는다(잔여
벡터 · 상당응력 1σ 없음, PSD 방향은 X · Y · Z 축만). 두 셈이 0.4 % 안에서 같다(조건_랜덤진동).

## CompCore 와 어떻게 이어지나

형상은 CompCore(CAD)에서 온다. CompCore 에서 DOE(설계점 여럿)나 설계 하나를 만들고 **내보내면**
(CompCore MCP 의 `doe_export`, 화면의 「해석으로 보내기」) 공유 폴더에 `<이름>-<스터디 id 앞
8자리>` 폴더가 생긴다. 여기서는 그 폴더를 읽어 해석을 건다.

- **두 플랫폼을 잇는 열쇠는 CompCore 스터디 id** 다 — 여기 `study_id` 와 같다.
- **사용자에게 공유 폴더 경로를 묻지 않는다.** CompCore 가 준 `study_id` 를 `folder_preview` ·
  `jobs_create` 에 **그대로** 넘기면 서버가 폴더를 찾아 건다(답의 `folder` 가 실제로 건 폴더).
  CompCore 가 주는 `folder`(`F:\…`)를 `path` 로 넘겨도 그 꼬리(`-<id 앞 8자리>`)로 찾는다. 이름만
  알면 `folder_find`.
- 못 찾으면: CompCore 에서 아직 내보내지 않았거나, 보관 기한(기본 30일)이 지나 치워졌다 — CompCore
  에서 다시 내보내면 같은 폴더가 다시 선다. 공유 폴더는 보관소가 아니라 **전달 큐**다.
- 두 MCP 가 함께 붙어 있으면 한 번에: CompCore `doe_run`(만들고 · 기다리고 · 내보내기까지) → 그
  답의 `study_id` 로 여기 `folder_preview(study_id=…)` → `jobs_create(spec, study_id=…)` →
  `job_get` → `study_get`.

## 흐름

1. 폴더 — CompCore 의 `study_id` 가 있으면 그것으로 2 · 4 를 바로 부른다. 이름만 알면
   `folder_find(이름)`, 무엇이 있는지 모르면 `folder_browse`(`is_study` 인 항목).
2. `folder_preview(study_id=… 또는 path=…)` — 설계점 몇 개 · 변수 · 권하는 해석. 설계점 하나는 `number` 를 주고
   **`conditions.lines` 의 `refused`** 를 본다.
3. `recipe_schema` — 스펙 칸. 대개 `{"recipe": …, "solver": …}` 만 주고 나머지(조건 · 물성 ·
   **메시 크기**)는 CAD 값. 요소 크기는 사람이 정해 달라고 할 때만 준다(CAD 의 「전체」 크기를 덮는다).
4. `jobs_create(spec, study_id=… 또는 path=…, numbers=[…])` — 점마다 작업 하나. 작업 id 가 바로
   온다.
5. `job_get(job_id, wait_seconds=25)` — 끝날 때까지 되묻는다. `failed` 면 까닭을 사람에게.
6. `job_result(job_id)` — 숫자(늘 mm · MPa · N · Hz). 여러 점이면 `study_get(study_id)`.
7. 필요하면 `convergence_start` (메시가 충분한가) · `measurement_add` (실측과 견준다).
8. 사용자가 시키면 `job_publish` · `study_publish` — 조직의 누구나 보게 된다.

## 기본 습관

- **숫자를 지어내지 않는다.** 결과가 아직 없으면 「아직 돈다」 고 말한다. 실측은 사람이 준 그대로.
- **서버의 말을 그대로 전한다.** 오류 문구에 무엇을 고칠지가 적혀 있다(`[SEB-SIMULATIONS-…]`).
- **보이는 것** — 내가 건 작업과 게시된 작업(시스템 관리자는 전부). 남의 게시 결과는 읽기만.
- 다른 주제: `run` · `conditions` · `results` · `compare` · `publish`.

<!--@ run -->
## 걸기

### 설계점 고르기

- `folder_find(query)` — CompCore 스터디 id(전체 또는 앞 8자리)나 이름으로 찾는다. id 로 맞은 것이
  먼저, 그다음 최근에 내보낸 것. 이름이 여럿 맞으면 사람에게 고르게 한다(첫 줄을 집지 않는다).
- `folder_browse(path)` — 둘러보기. 뿌리 아래만 보인다. `is_study: true` 가 걸 수 있는 폴더다(스터디 —
  설계점 여럿, 또는 설계 하나 — 인자 0개).
- `folder_preview(path)` — `points[]`(번호 · 바꾼 값 · `usable` · `skip_reason`), CAD 가 권하는
  `suggested_recipe` · `suggested_modes` · `suggested_element_size_mm` · `suggested_order` ·
  `suggested_large_deflection`. **권하는 값을 그대로 쓰는 것이 기본이다.** 요소 크기는
  `suggested_element_size_from` 이 출처다 — `cad` 사람이 「전체」 에 적은 값, `compcore` 형상으로
  셈한 제안(`suggested_element_size_basis` 가 까닭).
- `folder_preview(path, number=N)` — 그 점의 영역 · 파트(강체 · 쉘 · 제외) · 물성 · 조건 줄.

### 스펙

`recipe_schema` 가 정본이다. 자주 쓰는 칸:

| 칸 | 기본 | 언제 바꾸나 |
| --- | --- | --- |
| `recipe` | (필수) | `modal` · `static` · `harmonic` · `random` |
| `solver` | `calculix` | 조건이 CalculiX 에서 거절되면 `ansys` |
| `mesh.element_size_mm` | CAD 값(「전체」 메시 힌트, 없으면 CompCore 의 제안값) | **비워 둔다** — 사람이 크기를 정해 달라고 할 때만. 주면 CAD 의 전역 크기를 덮는다(파트 · 면 크기는 CAD 그대로) |
| `mesh.order` | `quadratic` | 거의 안 바꾼다 |
| `modes` | CAD 값(없으면 10) | 모달 · 조화 · 랜덤 — 볼 탄성 모드 수(조화 · 랜덤은 모드 중첩에 쓸 수)(강체 6개는 따로 찾는다). DOE 는 **비교하는 6개보다 넉넉히**(10 권장) — 6개 이하면 치수에 따라 모드가 밀려나 비교 선이 끊긴다 |
| `large_deflection` | CAD 값 | 정적 — 변형이 커서 모양이 바뀔 때(느리다) |
| `frequency_range_hz` | CAD 값(없으면 비움) | **모달** — 찾을 주파수 범위 `[하한, 상한]`(Hz). 주면 그 범위 안의 모드만 `modes` 개까지 찾는다(낮은 모드에 밀려 보고 싶은 대역이 빠지지 않게). CAD 가 적었으면 그것이 먼저다 |
| `frequency_range_hz` · `intervals` · `damping_ratio` | 0~2000 · 10 · 0.02 | 조화 — 훑을 범위 · 점 수 · 감쇠비. 감쇠가 없으면 거절 |
| `frequency_range_hz` · `damping_ratio` | 비움 · 0.02 | 랜덤 — **모드를 찾을 범위**(모달과 같은 뜻 — 그 안의 모드만 중첩에 쓴다) · 감쇠비. **가진과 그 대역은 CAD 조건의 가속도 PSD 표**다 — 범위로 PSD 를 자르지 않는다. CAD 가 적은 범위 · 감쇠비가 먼저다 |

`material_from` · `conditions_from` 은 `cad`(기본)로 둔다 — 물성 · 조건은 CAD 가 파트마다 보낸다.
`spec` 으로 바꾸면 CAD 값을 일부러 무시한다(그때는 `material` · `constraints` 를 직접 준다).

### 걸고 기다리기

- `jobs_create(spec, study_id=…, numbers=[…])` — `created`(작업 id) · `skipped`(못 건 점과 까닭) ·
  `notes`(막지는 않지만 알아야 할 것 — 사람에게 그대로 전한다).
  `numbers` 를 비우면 걸 수 있는 전부. 이미 가져온 점은 다시 걸지 않는다(같은 해석을 두 번 안
  돌린다) — 거절 문구가 누구 작업인지 말한다.
- `job_get(job_id, wait_seconds=25)` — 상태: `queued` → `fetching` → `modeling` → `solving` →
  `extracting` → `done`(또는 `failed` · `canceled`). 솔브는 몇 분에서 몇 시간이다. 여러 점이면
  `jobs_list(status=…)` 나 `study_get` 으로 한 번에 본다.
- **`jobs_list` 는 화면의 「해석」 목록과 같다** — 단일 해석과 DOE 한 벌이 한 줄씩(`kind` · `key`).
  DOE 설계점은 줄로 서지 않으니 DOE 줄의 `study_id` 로 `study_get` 을 본다. `status` 를 주면
  설계점까지 낱개 작업으로 편다(대기 · 실패 중인 것 전부). 사람이 나눈 **정리 폴더**는
  `jobs_folders()` 로 보고 `jobs_list(folder=…)` 로 거르며, 옮기기는 `jobs_move(keys, folder)` —
  사용자가 정리해 달라고 할 때만. CAD 공유 폴더(`folder_*`)와는 다른 것이다.
- **줄은 사람마다 번갈아 선다.** 워커는 같은 솔버 안에서 도는 작업이 적은 사람 · 오래 못 받은
  사람부터 집는다 — DOE 수백 점을 걸어도 남의 한 건을 막지 않고, 남이 많이 걸어도 내 것이 끼어든다.
  대기 중이면 `job_get` 의 `queue` 가 어디쯤인지 말한다(그 솔버의 대기 · 내 앞의 내 작업 · 줄을 나눠
  쓰는 사람 수 · 도는 것 · 워커 수) — 사람에게 그대로 전한다.
- **집을 워커가 없는 솔버**(`recipe_schema` 의 `solvers`, `queue.workers_alive == 0`)로 걸면 대기에서
  움직이지 않는다. 「왜 안 도나」 · 「줄이 얼마나 긴가」 는 `server_status()` — 솔버마다 살아 있는 워커 ·
  대기 수(시스템 관리자면 워커마다 하는 일까지). 워커가 0 이면 서버 관리자에게 알리라고 말한다.
- **DOE 비교에서 모드가 끊기면**(`study_get` 표의 빈 자리 — 구한 모드 안에 닮은 모양이 없다) 모드 수를
  늘려 다시 건다: `study_rerun(study_id, modes=10)` — 점마다 같은 입력으로, 옛 결과는 기록으로 남는다
  (사용자가 시킬 때만). 같은 폴더는 `jobs_create` 로 다시 가져올 수 없다.
- **DOE 를 잘못 걸었으면** `study_cancel(study_id)` — 끝나지 않은 점을 모두 멈춘다(사용자가 시킬 때만).
  멈춘 점은 `job_retry` 로 다시 건다. 디스크를 비우려면 `files_tidy(job_id=… | study_id=…)` — 중간
  파일만 지운다(결과는 남는다, 사용자가 시킬 때만). 지우기(작업 · DOE 통째로)는 MCP 에 없다 — 사람이
  화면에서 한다.
- 실패: `job_get` 의 `error_message` · `stages[].error_message` 를 사람에게 전한다. 조건 거절이면
  다시 걸어도 같다 — 솔버를 바꾸거나 CAD 쪽에서 고친다. 일시적인 것이면 `job_retry`.

<!--@ conditions -->
## 조건 — CAD 가 보낸 것이 어떻게 걸리나

CAD 는 점 파일에 조건 한 벌을 보낸다(구속 7종 · 하중 8종 · 접촉 · 초기조건). 서버는 줄마다
셋 중 하나로 답한다(`folder_preview` · `job_get` 의 `conditions`):

| 갈래 | 뜻 | 할 일 |
| --- | --- | --- |
| `applied` | 걸었다 | — |
| `skipped` | 이 해석에서 **답을 바꾸지 않아** 넘겼다 | 그대로 둔다 — 까닭을 사람에게 전한다 |
| `refused` | 답을 바꾸는데 **아직 못 건다** | 모델링에서 멈춘다 — 솔버를 바꾸거나 CAD 를 고친다 |

**모달에서 하중은 `skipped` 다** — 선응력(`prestressed`) 모달이 아니면 하중은 고유진동수를
바꾸지 않는다. 버그가 아니라 해석의 성질이다.

### 솔버마다 걸 수 있는 것

| 종류 | ansys | calculix |
| --- | --- | --- |
| 고정 · 변위 · 원격 변위 · 마찰 없는 지지 · 원통 지지 | ✅ | ✅ (좌표계를 쓴 원격 변위 · 축에 비스듬한 마찰 없는 지지는 거절) |
| 압축만 · 탄성 지지 | ✅ | 거절 |
| 압력 · 힘 · 모멘트 · 베어링 · 가속도 · 중력 | ✅ | ✅ |
| 볼트 예하중 · 회전 속도 | ✅ | 거절 |
| 접촉(본딩 · 분리 없음 · 마찰 · 무마찰 · rough) | ✅ | 본딩은 절점 공유, 강체 면과의 마찰은 접촉으로 |
| 초기조건(환경 온도) | 넘김(열응력은 안 푼다) | 넘김 |

- 조건은 **면 그룹**에만 건다. 엣지 · 점 그룹에 건 조건은 거절이다(점 그룹은 측정점 — 값을 읽을
  자리).
- 강체 파트의 면에 건 하중 · 강체끼리의 접촉은 거절 — 그 파트를 변형체로 바꾸게 한다(CAD).
- 쉘 파트는 CAD 가 보낸 중간면으로 푼다. 중간면이 없으면 거절.
- 정적에 하중이 하나도 없으면 멈춘다 — 풀어도 전부 0 이다.

<!--@ results -->
## 결과 읽기

`job_result(job_id)` — **늘 mm · MPa · N · Hz**(서버가 솔버마다 다른 단위를 맞춘다).

**결과 화면이 함께 뜬다.** HWAX 챗 · Claude 데스크톱 · 웹에서는 `job_result` · `study_get` ·
`study_analyze` · `study_frequency` · `convergence_get` · `measurements_get` 의 결과 아래에 웹 화면과
같은 표 · 그림(모드 표 · 주파수 곡선 · 모드 지도 · 등고선 · 판정도 …)이 패널로 뜬다(3D 형상은 웹에서).
그 표를 글로 다시 옮겨 그리지 말고 **물음에 답하는 숫자와 판단**만 말한다. `panel_data` 는 그 화면이
자료를 읽는 길이다 — 부르지 않는다.

### 모달

- `frequencies` — 탄성 모드 주파수(강체 6개는 뺐다). `first_elastic_hz` 가 1차.
- `modes[]` — `elastic_number` · `frequency_hz` · `dominant_direction`(`X` · `Y` · `Z` · `ROTX` ·
  `ROTY` · `ROTZ` — 유효질량이 가장 큰 방향, 전부 작으면 없다) · `effective_mass_ratio`. 「1차는
  Z 방향으로 떠는 모드」 처럼 말할 근거다.
- 구속이 없으면 자유-자유 — 앞 6개가 0 Hz 근처(강체)로 나오는 것이 정상이다.
- **찾을 범위로 풀었으면**(`frequency_range_hz` 가 결과에 있다) 모드는 그 범위 안뿐이고 `elastic_number`
  도 그 안에서 1 부터다 — 「1차」 가 전체의 1차가 아니다. `modes_below_range` 는 범위 아래에서 뺀
  탄성 모드 수(CalculiX), `range_note` 는 범위 안에 모드가 없거나 끝까지 못 훑었을 때의 말이다.

### 정적

- `max_displacement_mm` · `max_von_mises_mpa`.
- `reactions_n` — 영역 → `[Fx, Fy, Fz]`(N). 하중과 반력의 합이 맞는지 볼 수 있다.
- 측정점(CAD 의 점 그룹 — 센서 자리): `probes_mm`(변위 크기) · `probe_vectors_mm`(성분) ·
  `probe_strains`(`[εxx, εyy, εzz]`, 무차원) · `relative_mm`(같은 자리 두 바디의 차 — 전단 이음의
  미끄럼).
- **최대 응력은 믿지 마라** — 구속 모서리 · 날카로운 모서리의 수치적 첨두가 흔하다. 판단에 쓰려면
  메시 수렴(`compare`)을 먼저.

### 조화

- `peak_hz` · `peak_displacement_mm` — 모델 전체의 봉우리.
- `max_von_mises_mpa` — **봉우리 주파수의 최대 상당응력**(위상을 돌린 최대, CalculiX). 자리는
  `result.stress`.
- `probes_mm` · `probe_peaks_hz` — 측정점마다 곡선의 봉우리 진폭 · 주파수.
- 주파수별 곡선 전체는 `job_result(job_id, detail=true)` 의 `result.points`(크다).
- CalculiX 는 **빠진 높은 모드의 정적 몫(잔여 벡터)을 더한다**(`result.residual`) — 고유진동수가
  범위보다 훨씬 높은 부품(준정적)도 모드 수와 상관없이 맞는다.

### 랜덤 진동

- 값은 모두 **1σ**(실효값 — 시간의 68.3 % 가 그 아래). 설계는 흔히 **3σ(세 배)** 로 본다 —
  사람에게 전할 때 둘을 함께 말한다.
- `probe_grms` — 측정점 → **절대 가속도 1σ**(g, 가속도계가 재는 값). `probes_mm` — 측정점 1σ
  변위(지지부 기준). `max_displacement_mm` — 모든 절점의 1σ 변위 최대(지지부 기준).
- `max_von_mises_mpa` — **최대 상당응력 1σ**(Segalman — Ansys 랜덤 진동의 상당응력과 같은 정의).
  자리는 `result.stress`.
- 입력 Grms · 응답 PSD 곡선 · 모드별 유효질량 몫은 `job_result(job_id, detail=true)` 의
  `result.inputs` · `result.curves` · `result.modes`.
- 풀이는 모달 하나 + 모드 중첩이다(가진 방향 참여계수 · 모드 형상 · PSD). 가진이 여럿이면 서로
  무관한 것으로 더한다. **빠진 높은 모드의 정적 몫(잔여 벡터)을 더한다** — 고유진동수가 대역보다
  훨씬 높은 부품(준정적)도 모드 수와 상관없이 맞는다(`result.residual`).
- 적분한 대역은 `result.band_hz`(PSD 표), 모드를 찾은 범위는 `result.frequency_range_hz`(있을 때만).

### 그 밖

- `mass_kg` · `nodes`(절점 수), 결과에 찍힌 `solver`.
- 두 솔버의 수는 몇 % 갈린다 — 견줄 때는 같은 솔버끼리.
- **값이 10³ 배씩 이상하면 단위부터** — `job_get` 의 `summary` 에서(CalculiX) `deck_materials`(덱에 실제로
  쓴 탄성계수 GPa · 밀도 kg/m³), `solver_mass_kg`(솔버가 덱으로 셈한 질량 — `mass_kg` 와 같아야 한다),
  `size_warning`(STEP 을 읽어 잰 부피가 CAD 와 1 % 넘게 다름 — 길이 단위면 그렇게 적는다), `mass_warning`.
  고유진동수는 √(E/ρ) / 길이라 길이가 1000배 작거나 E 가 10⁶ 배 크면 1000배로 나온다. 질량이 정상이면
  탄성계수, 10⁻⁶ 배면 밀도, 10⁻⁹ 배면 형상이다.

<!--@ compare -->
## 견주기

### 설계점끼리 — `study_get(study_id)`

- `points[]` — 점마다 `params`(바꾼 값) · 상태 · 결과(1차 공진 · 질량 · 최대 변위 · 최대 응력 ·
  반력 · 측정점).
- `tracks[]` — **모드 추적.** 치수가 바뀌면 모드 순서가 뒤바뀐다(mode crossing) — 「2차 대 두께」
  를 순번으로 이으면 서로 다른 모드를 잇는다. 같은 모드끼리 이은 것이 여기 있다.
- `studies_list(scope="mine")` 로 스터디 id 를 찾는다.

### 분석 — `study_analyze(study_id, …)`

**점들을 받아 손으로 셈하지 않는다** — 서버가 셈한다(화면 「다변수」 탭과 같은 표). 차례:

1. 인자 없이 — `columns`(열 key) · `sensitivity`(결과마다 어느 변수가 가장 많이 움직이나 — 주효과 폭 %
   와 상관계수) · `ranges`(결과마다 최소 · 최대 점).
2. 궁금한 결과 하나 — `result="mode:1"` 이면 `effects`(변수의 수준마다 평균 · 최소 · 최대).
3. 조건을 건 최적 — `objective="mass_kg", goal="min", where=["mode:1>=300", "max_mpa<=200"]` →
   `choice.best` 와 앞의 다섯.
4. 두 변수의 함께 영향 — `x="factor:두께", y="factor:폭", result="max_mm"` → `pair`(빈 칸은 null).

질량: `mass_kg` 는 **모델 전체**다 — 해석에서 지그와 부품은 같은 바디라 강체 지그(롤러 · 노즈 ·
받침)까지 든다. 바디가 둘 이상이면 `mass:<파트>` 열(작업 결과에는 `mass_by_body`)로 그 파트만 본다.

말할 때: 민감도는 **다른 변수가 섞인 평균**이다 — 전 조합 설계가 아니면 「두께가 원인」 이라 단정하지
말고 상관계수와 함께 말한다. 수준이 많은 변수(LHS)는 다섯 구간으로 묶였다(`notes`). 실패한 점은 빠진다
(`done` / `total`).

### 주파수 요구 — `study_frequency(study_id)`

모달 DOE 를 **목표 주파수**(이 모드를 이 주파수에) · **회피 대역**(들뜨는 모드가 가진 대역 밖에)으로
판정한다. 요구 조건은 사람이 화면(스터디 「주파수 요구」 탭)에서 정해 스터디에 저장한다 — 서버가 그
요구로 셈한다.

- 판정: `conform` 적합 · `band_violation` 대역 침범(목표는 충족) · `target_deviation` 목표 이탈(대역은
  회피) · `nonconform` 부적합 · `pending` 판정 보류(끝나지 않음 · 그 모드를 형상으로 잇지 못함).
- 회피 대역의 **판정 대상**은 실제로 들뜨는 모드다 — 가진 방향 유효질량 또는 측정점 움직임(그 측정점이
  가장 크게 움직인 모드 대비)이 문턱 이상. 참여 정보가 없는 모드는 대상으로 둔다.
- `estimate` 는 DOE 에 없는 자리의 **보간 추정**이다 — 이웃 설계점 사이를 곧게 이은 값이다. 「여기가
  답」 이라 하지 말고 CompCore 에서 그 값으로 설계점을 더해 확인하라고 말한다.
- `detail=true` 면 점마다 모드별 역할과 까닭, 공차 민감도(맞출 모드가 변수 한 단위에 몇 Hz 움직이나 ·
  목표 허용 폭에 해당하는 변수 폭)까지 온다.

### 메시 수렴 — `convergence_start` → `convergence_get`

- 끝난 작업을 요소 크기만 바꿔 다시 건다(원래 대비 비율, 기본 ×0.7 · ×0.5). 수준마다 작업 하나.
- 판정(GCI): `converged` 수렴 · `not_converged` 미수렴 · `oscillating` 판정 보류 · `diverging`
  발산 · `insufficient` 수준 부족. **발산은 고장이 아니다** — 그 값(대개 첨두응력)으로 판단하지
  말라는 뜻이다.
- 솔버를 섞지 않는다(솔버 차이가 메시 차이로 읽힌다).

### 실측 — `measurement_add` → `measurements_get`

- 표 한 장(CSV · 탭 · JSON). 열: 측정점 · 종류(공진 · FRF · 변위 · 변형률) · 주파수 · 값 · 단위 ·
  성분. 측정점 이름은 CAD 의 점 그룹 이름(센서 자리)이다. 공진은 측정점을 비워도 된다.
- 견주기: 센서 자리에서 거의 안 움직이는 모드는 짝에서 뺀다, 가장 가까운 주파수를 한 모드에 한
  번만(±25% 밖이면 짝을 안 짓는다), 가까운 후보가 둘이면 「불확실」.
- 차이를 설명하는 제안 — 모든 모드가 같은 비율로 어긋나면 영률, 봉우리 높이는 감쇠비. 모드마다
  비율이 다르면 물성 하나로 설명되지 않는다(경계조건 · 접촉 · 형상을 본다).
- 스터디에 붙이면 **실측에 가장 가까운 설계점**을 고른다.

<!--@ publish -->
## 게시 — 누가 무엇을 보나

- 해석 작업은 **건 사람의 것**이다. 보는 것은 건 사람과 시스템 관리자, 그리고 **게시한 끝난
  작업은 조직의 누구나**(읽기만).
- `job_publish(job_id)` — 끝난 작업 하나(메시 수렴 수준도 함께). `study_publish(study_id)` — 스터디의
  내가 건 끝난 점 전부. `unpublish=true` 로 해제.
- **사람이 판단할 일이다.** 사용자가 「게시해」 라고 할 때만 부른다. 결과를 보고 스스로 게시하지
  않는다.
- 재시도 · 멈춤 · 게시 · 실측 붙이기 · 수렴 점검은 건 사람이나 시스템 관리자만 — 남의 게시 결과에
  부르면 서버가 거절한다(그 문구를 그대로 전한다).
