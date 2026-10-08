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
    spec = {"recipe": recipe, "solver": "calculix", "mesh": {"element_size_mm": size}}
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


def test_강체_마찰을_붙여_풀면서_큰_변형은_막는다(ready: None, tmp_path: Path) -> None:
    """보드굽힘은 롤러 · 노즈(강체)와의 마찰을 아직 붙여서 푼다. 그 채로 큰 변형을 켜면 판이
    양 끝에 묶여 막처럼 버텨 반력이 15배로 나왔다(19.2 → 296.7 kN, 2026-10-08)."""
    folder = STANDARDS / "시험_보드굽힘_JESD22" / "points"
    shutil.copy(folder / "p0001.step", tmp_path / "input.step")
    shutil.copy(folder / "p0001.json", tmp_path / "topology.json")
    spec = parse_spec(
        {
            "recipe": "static",
            "solver": "calculix",
            "mesh": {"element_size_mm": 1},
            "large_deflection": True,
        }
    )
    with pytest.raises(StageFailure) as failure:
        build(spec, tmp_path, input_name="input.step", timeout_seconds=600)
    assert "큰 변형" in str(failure.value)
