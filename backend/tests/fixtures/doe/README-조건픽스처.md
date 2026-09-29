# SimEngBay 에 건네는 조건 픽스처

CompCore 의 **실제 내보내기 코드**가 쓴 DOE 폴더 두 벌이다(손으로 짠 JSON 이 아니다). 만드는 곳은
`backend/tests/api/test_fixture_export.py` — 평소에는 내용만 검사하고, 다시 만들려면:

```
cd backend
COMPCORE_FIXTURE_OUT=../fixtures/simengbay .venv/bin/pytest tests/api/test_fixture_export.py
```

물성은 MatNexus 의 실제 줄(`backend/tests/fixtures/matnexus/*.json`, 2026-09-28 스냅샷)을 화면이
싣는 모양 그대로 실었다. 폴더 이름의 스터디 id 는 떼었다(돌릴 때마다 바뀐다).

## 조건_두바디_두재료 — 파트마다 다른 물성

강판 위에 알루미늄 블록을 본딩한 조립. 판 두께를 5 · 8 로 훑는다.

| 바디(`bodies[].name`) | STEP product | 부피(두께 5 / 8) | 무게중심(두께 5) | 재료 |
| --- | --- | --- | --- | --- |
| 받침판 | `body_1` | 30000 / 48000 mm³ | (0, 0, 2.5) | SECC(M-000138) |
| 블록 | `body_2` | 32000 / 32000 mm³ | (0, 0, 15) | Al5052-H32(M-000158) |

- `conditions.materials[i].apply_to` 가 바디 이름 목록 — `["받침판"]` · `["블록"]`.
- 짝짓기에 쓸 것: 점 파일 `bodies[]` 의 `volume` · `centroid` · `bbox`(mm), 그리고 STEP 의 product
  이름(`step_product`). 두께를 바꾸면 판의 부피 · 무게중심만 바뀐다 — 짝이 설계점마다 풀려야 한다.
- 조건: 바닥 고정 지지, 블록 윗면 압력 1.5 MPa(법선), 블록 아랫면 ↔ 판 윗면 **본딩 접촉**,
  메시 요소 4 mm · 2 차, 정적 구조. 내보내기 계 `mm_n_tonne`.

## 조건_원통_SI — 원통면 · SI 로 내보내기

구멍 뚫린 판 하나(바디 `전체`). 구멍 지름을 10 · 12 로 훑는다.

- 구멍면(`kind: cylinder`)에 **원통 지지** — 반지름 · 축 고정, 접선 자유(`tangential: "free"`).
- 끝면에 힘 200 N(-Z), 구멍면에 **베어링 하중** 500 N(+X).
- 메시 힌트: 구멍면 요소 2 mm → 점 파일에는 **0.002 m**(내보내기 계 `si`).
- 모달: 모드 8 개, 0 ~ 5000 Hz. `analysis` 에는 모달이 쓰는 칸만 실린다.
- `length_units`: 형상 · 영역 mm, 좌표계 m.

## 조건_재료훑기 — 재료만 바꿔 끼우는 DOE

「조건_두바디_두재료」 와 같은 조립·조건에 **재료 인자** 하나를 걸었다: 블록의 재료를
Al5052-H32 ↔ SECC 로(`study.json` 의 `factors` — `{"mode": "material", "bodies": ["블록"],
"values": [이름…]}`).

- 형상은 그대로라 두 점이 `shapes/<지문>.step` 하나를 나눠 쓴다.
- 점마다 다른 것은 `conditions.materials` 의 `apply_to` 뿐이다 — 고른 재료가 `["블록"]`, 나머지는
  블록이 빠진다. 받침판은 늘 SECC.
- `manifest.csv` 의 `블록 재료` 열과 점 파일 `point.params` 에 그 점의 재료 이름이 있다.

## 읽을 때 알아 둘 것

- 점 파일의 값은 **`conditions.units` 에 선언된 계**다. 사람은 늘 mm · N · t 로 적고, 내보낼 때만
  옮긴다.
- 조건은 선택 그룹 이름으로만 가리키고, 그 자리는 점 파일 `regions` 에 설계점마다 풀려 있다.
- 칸의 뜻 · 기본값은 `GET /api/cad/conditions/schema` 와 CompCore `docs/해석-조건-설계.md`.
