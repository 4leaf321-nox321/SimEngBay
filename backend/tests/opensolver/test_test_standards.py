"""CompCore 시험 규격(v0.11.0) 의 대표 폴더를 **CalculiX 로 끝까지** 푼다(2026-10-08).

CalculiX 를 기본 솔버로 쓰려면 시편 · 제품 시험이 다 풀려야 한다. CompCore 가 v0.6.0 으로
20개를 풀어 보니 4개만 풀렸다(커밋 6500479 의 픽스처 설명서) — 막은 것은 셋이었다:

- 변위로만 당기는 시험을 「하중이 없다」 로 막았다(`Conditions.drives`).
- 작은 면 · 작은 강체를 **메시로** 재서 짝을 못 찾았다 — 굽힘 시험의 지름 1 mm 대칭점 · 롤러
  (`mesh.measure` — 이제 형상으로 잰다).
- 가속도 · 모멘트 · 변형체 면의 원격 변위를 못 걸었다(`calculix/deck.py`).

여기서는 그 셋을 하나씩 대표하는 폴더를 빨리 도는 크기로 푼다. 20개 전부와 Ansys 와의 대조는
`docs/해석-연동-계획.md` 의 「시험 규격 20개」 절에 적었다(픽스처 설명서는 CompCore 의 것
그대로 — v0.6.0 으로 풀어 본 그쪽 기록이다).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.core.calculix import frd as frd_reader
from app.core.calculix import tools
from app.core.calculix.build import build
from app.core.calculix.mesh import read_mesh
from app.core.run import run_stage
from app.core.spec import parse_spec
from app.core.stages import STAGES, StageFailure

pytestmark = pytest.mark.opensolver

STANDARDS = Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "시험규격"


@pytest.fixture
def ready() -> None:
    for find in (tools.gmsh_bin, tools.ccx_bin):
        try:
            find()
        except StageFailure as failure:
            pytest.skip(str(failure))


def _solve(name: str, size: float, workdir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """폴더의 점 파일 · STEP 을 그대로 작업 폴더로 — 네 단계를 돌리고 (결과, 요약)."""
    folder = STANDARDS / name / "points"
    shutil.copy(folder / "p0001.step", workdir / "input.step")
    shutil.copy(folder / "p0001.json", workdir / "topology.json")
    point = json.loads((folder / "p0001.json").read_text(encoding="utf-8"))
    recipe = point["conditions"]["analysis"]["type"]
    spec: dict[str, Any] = {
        "recipe": recipe,
        "solver": "calculix",
        "mesh": {"element_size_mm": size},
    }
    if recipe == "static":
        # 여기서는 **막던 셋**을 본다 — CAD 가 적은 큰 변형(비틀림 등)을 따르면 같은 답을
        # 열 배 넘게 오래 푼다(비틀림 2 mm 30 → 535 초). 큰 변형은 아래 따로 본다.
        spec["large_deflection"] = False
    summary: dict[str, Any] = {}
    for stage in STAGES:
        done = run_stage(
            stage,
            parse_spec(spec),
            workdir,
            input_name="input.step",
            version=252,
            ansys_root=None,
            solver_processes=2,
            timeout_seconds=900,
            visual_modes=6,
        )
        summary.update(done.summary)
    result = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
    return result, summary


def test_변위로만_당기는_인장_시편이_풀린다(ready: None, tmp_path: Path) -> None:
    """ASTM E8 — 한쪽 그립 고정, 다른 쪽 그립을 X 로 1 mm. 하중은 없다."""
    result, _ = _solve("시험_인장_E8", 1.0, tmp_path)
    assert result["max_displacement"] == pytest.approx(1.0, rel=1e-3)
    pull = result["reactions"]["당김 그립"]
    # 당긴 쪽으로 버틴다 — 강판 시편이면 수십 kN 이다(실측 57.0 kN).
    assert pull[0] > 1000
    assert abs(pull[1]) < 0.01 * pull[0] and abs(pull[2]) < 0.01 * pull[0]


def test_굽힘_시험의_대칭점과_강체_롤러를_형상으로_짝짓는다(
    ready: None, tmp_path: Path
) -> None:
    """ASTM D2344 숏빔 — 강체 롤러 둘 · 노즈(원격 변위), 시편 중앙의 지름 1 mm 대칭점.

    메시로 재면 대칭점(0.79 mm²)이 13% · 롤러(127 mm³)가 11% 작게 나와 짝을 못 찾았다. 그룹
    「지지 롤러」 는 롤러 둘의 면이다 — 한 강체에 다 들지 않아도 강체 면이다.
    """
    result, _ = _solve("시험_숏빔전단_D2344", 1.0, tmp_path)
    reactions = result["reactions"]
    assert {"지지 롤러", "로딩 노즈", "시편 중앙"} <= set(reactions)
    # 롤러가 받친 만큼 노즈가 누른다(평형).
    assert reactions["지지 롤러"][2] == pytest.approx(-reactions["로딩 노즈"][2], rel=1e-3)
    assert reactions["로딩 노즈"][2] < 0


def test_가속도는_관성으로_받아_바닥을_고정한_판이_아래로_눌린다(
    ready: None, tmp_path: Path
) -> None:
    """15g(+Z) — 바닥(z 0)을 고정한 판(높이 12)은 윗면이 **-Z 로** 내려간다. 크기는
    밀도 x 가속도 x 높이² / 2E 어림(2.8e-7 mm)과 자릿수가 같다(Ansys 4.21e-7 mm 와 같다)."""
    result, _ = _solve("시험_가속도_15g", 3.0, tmp_path)
    assert 1e-7 < result["max_displacement"] < 1e-6
    mesh = read_mesh(tmp_path / "model.msh")
    block = next(one for one in frd_reader.read(tmp_path / "model.frd") if one.kind == "DISP")
    top = [node for node, (_, _, z) in mesh.nodes.items() if abs(z - 12.0) < 1e-6]
    assert top
    assert sum(block.values[node][2] for node in top) / len(top) < 0


def test_모멘트와_원격_회전과_가속도_가진이_걸린다(ready: None, tmp_path: Path) -> None:
    """방향 하중(힘 + 모멘트) · 비틀림(끝면을 6도) · 진동(가속도 가진, 조화) — 전에는 셋 다
    「CalculiX 경로가 아직 못 거는」 조건이었다."""
    for name, size in (("시험_방향하중", 3.0), ("시험_비틀림", 3.0), ("시험_진동_150Hz", 3.0)):
        work = tmp_path / name
        work.mkdir()
        result, summary = _solve(name, size, work)
        assert "conditions_refused" not in summary, name
        if result["recipe"] == "harmonic":
            assert result["peak"]["max_displacement"] > 0
        else:
            assert result["max_displacement"] > 0
    torsion = json.loads(
        (tmp_path / "시험_비틀림" / "result.json").read_text(encoding="utf-8")
    )
    # 끝면을 **면적 중심**을 지나는 축으로 돌린다 — 절점 평균에 원격점을 두면 축이 0.05 mm
    # 비켜나 옆 반력이 408 N 나왔다(2026-10-08). 순수 비틀림이라 0 언저리여야 한다 — 면적
    # 중심이면 4 N(요소 3 mm) · 0.9 N(2 mm).
    _, fy, fz = torsion["reactions"]["시험 비트는 끝"]
    assert abs(fy) < 50 and abs(fz) < 50


def test_선응력_모달의_앞_정적이_못_건_하중은_막는다(ready: None, tmp_path: Path) -> None:
    """조이는 하중이 빠진 채 선응력 모달이 돌면 그냥 모달과 같은 값이 그럴듯하게 나온다 —
    전에는 앞 정적 단계의 거절을 버리고 그렇게 풀었다. 모르는 단위의 가속도를 하나 더해
    선응력 모달로 돌리면 모델링에서 멈춘다."""
    folder = STANDARDS / "시험_손잡이" / "points"
    shutil.copy(folder / "p0001.step", tmp_path / "input.step")
    point = json.loads((folder / "p0001.json").read_text(encoding="utf-8"))
    point["conditions"]["analysis"]["type"] = "modal"
    point["conditions"]["analysis"]["prestressed"] = True
    point["conditions"]["loads"].append(
        {
            "name": "이상한 가속",
            "type": "acceleration",
            "on": "",
            "cs": "global",
            "magnitude": 1.0,
            "unit": "furlong/s^2",
            "direction": [1, 0, 0],
        }
    )
    (tmp_path / "topology.json").write_text(
        json.dumps(point, ensure_ascii=False), encoding="utf-8"
    )
    spec = parse_spec(
        {"recipe": "modal", "solver": "calculix", "mesh": {"element_size_mm": 4}}
    )
    with pytest.raises(StageFailure) as failure:
        build(spec, tmp_path, input_name="input.step", timeout_seconds=600)
    assert "이상한 가속" in str(failure.value)


def test_강체_지지점과의_마찰을_접촉으로_푼다(ready: None, tmp_path: Path) -> None:
    """보드굽힘의 롤러 · 노즈(강체)와 판 사이는 마찰 접촉이다. 전에는 붙여서 풀어 판이
    지지점에서 미끄러지지도 돌지도 못했다 — 반력이 손셈의 16배(9,966 N — 약 600 N). 이제
    접촉 쌍으로 풀고 **강체 면을 독립(master) 쪽에** 둔다: 강체 절점은 `*RIGID BODY` 가 이미
    쥐어, 종속 면이 되면 같은 자유도를 두 번 묶는다. CAD 가 적은 큰 변형 · 초기 부단계 수(20)도
    그대로 받는다."""
    folder = STANDARDS / "시험_보드굽힘_JESD22" / "points"
    shutil.copy(folder / "p0001.step", tmp_path / "input.step")
    shutil.copy(folder / "p0001.json", tmp_path / "topology.json")
    spec = parse_spec(
        {"recipe": "static", "solver": "calculix", "mesh": {"element_size_mm": 3}}
    )
    done = build(spec, tmp_path, input_name="input.step", timeout_seconds=600)
    assert done.summary["contact_pairs"] is True
    assert "붙은 것으로" not in done.summary.get("conditions_skipped", "")
    assert done.summary["large_deflection"] is True
    deck = (tmp_path / "model.inp").read_text(encoding="utf-8")
    assert "*STEP, NLGEOM\n*STATIC\n0.05, 1.0\n" in deck
    # 접촉 쌍 둘 — 둘째 줄의 둘째가 독립 면이다. 강체(롤러 · 노즈) 쪽 면이 그 자리에 선다.
    pairs = deck.count("*CONTACT PAIR")
    assert pairs == 2
    assert "*FRICTION\n0.1," in deck


def test_핀과_구멍을_파트로_갈라_접촉으로_푼다(ready: None, tmp_path: Path) -> None:
    """핀 베어링(D5961) — 같은 지름의 핀이 구멍에 끼어 구멍면 · 핀 옆면이 같은 자리의 두
    면이다. 메시를 쪼개지 않으면(접촉) 둘이 따로 남아, 파트를 안 보면 「구멍면」 자리에 핀
    옆면을 집고 「양쪽이 다 강체」 로 멈췄다. 면마다 가진 파트를 달아 가른다
    (`_with_face_parts`)."""
    folder = STANDARDS / "시험_핀베어링_D5961" / "points"
    shutil.copy(folder / "p0001.step", tmp_path / "input.step")
    shutil.copy(folder / "p0001.json", tmp_path / "topology.json")
    spec = parse_spec(
        {"recipe": "static", "solver": "calculix", "mesh": {"element_size_mm": 3}}
    )
    done = build(spec, tmp_path, input_name="input.step", timeout_seconds=600)
    assert done.summary["contact_pairs"] is True
    assert "*CONTACT PAIR" in (tmp_path / "model.inp").read_text(encoding="utf-8")


def test_CAD_가_적은_큰_변형으로_푼다(ready: None, tmp_path: Path) -> None:
    """겹치기 이음(D1002)은 CAD 가 큰 변형을 적었다 — 스펙을 비우면 그대로 기하 비선형으로
    푼다(요약에 출처). 한 겹 이음은 하중 경로가 펴지며 굳는다: 반력 3,781 N(선형) → 4,529 N."""
    folder = STANDARDS / "시험_겹치기이음_D1002" / "points"
    shutil.copy(folder / "p0001.step", tmp_path / "input.step")
    shutil.copy(folder / "p0001.json", tmp_path / "topology.json")
    spec = parse_spec(
        {"recipe": "static", "solver": "calculix", "mesh": {"element_size_mm": 2}}
    )
    done = build(spec, tmp_path, input_name="input.step", timeout_seconds=600)
    assert done.summary["large_deflection"] is True
    assert done.summary["large_deflection_from"] == "cad"
    assert "*STEP, NLGEOM" in (tmp_path / "model.inp").read_text(encoding="utf-8")
