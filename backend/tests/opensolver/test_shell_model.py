"""CompCore 「해석용 셸 모델(시트 바디)」(2026-10-15)을 **CalculiX 로 끝까지** 푼다.

시트 바디는 두께가 없는 면 파트다(`bodies[].kind: "sheet"`). 중간면이 곧 형상이고
(`midsurface.bodies[].source: "sheet"`), 두께는 파트 설정의 쉘 두께로 온다. 막던 것은 넷이었다
(2026-10-16):

- 부피가 없는 형상을 「gmsh 가 부피를 읽지 못했다」 로 막았다(`mesh.probe_volumes`).
- 본 형상의 시트와 중간면의 시트가 한 자리에 두 벌 메시됐다(`mesh._head_lines` 가 지운다).
- 쉘 삼각형을 S3 로 적으면서 6절점을 줬다 — 외팔보가 30% 단단했다(`mesh.read_mesh`).
- 시트의 접착 띠와 받침 윗면이 같은 자리라 「쉘끼리의 접촉」 으로 읽혔다
  (`build._with_face_parts`).

손셈은 CompCore 픽스처 설명서(`README-조건픽스처.md`) 그대로다 — SECC(E 205 GPa · 푸아송비
0.29), 요소 2 mm.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.core.calculix import tools
from app.core.calculix.mesh import read_mesh
from app.core.regions import match_regions
from app.core.run import run_stage
from app.core.spec import parse_spec
from app.core.stages import STAGES, StageFailure

pytestmark = pytest.mark.opensolver

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "doe"
CANTILEVER = FIXTURES / "셸모델_시트외팔보"
ASSEMBLY = FIXTURES / "셸모델_시트받침조립"
NO_THICKNESS = FIXTURES / "셸모델_두께없음"


@pytest.fixture
def ready() -> None:
    for find in (tools.gmsh_bin, tools.ccx_bin):
        try:
            find()
        except StageFailure as failure:
            pytest.skip(str(failure))


def _place(folder: Path, workdir: Path) -> None:
    points = folder / "points"
    workdir.mkdir(parents=True, exist_ok=True)
    shutil.copy(points / "p0001.step", workdir / "input.step")
    shutil.copy(points / "p0001.json", workdir / "topology.json")
    if (points / "p0001_mid.step").is_file():
        shutil.copy(points / "p0001_mid.step", workdir / "input_mid.step")


def _spec(**extra: Any) -> dict[str, Any]:
    return {"recipe": "static", "solver": "calculix", "mesh": {"element_size_mm": 2}, **extra}


def _solve(workdir: Path, spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
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


def test_시트_외팔보가_손셈에_맞는다(ready: None, tmp_path: Path) -> None:
    """100 x 20 x t1.2 시트 외팔보, 끝에 1.8 N. 손셈 끝 처짐 0.278 mm(보 이론 — 판 이론의
    아래 한계 0.254), 뿌리 응력 16.9 MPa. 실측(2026-10-16): 0.2766 mm · 17.18 MPa.

    부피가 하나도 없는 형상이다 — 고치기 전에는 메시 전에 멈췄고, 고친 뒤에도 S3 에 6절점을
    물려 0.185 mm 로 단단했다.
    """
    _place(CANTILEVER, tmp_path)
    result, summary = _solve(tmp_path, _spec())
    assert summary["shell_bodies"] == "전체 1.2 mm"
    deck = (tmp_path / "model.inp").read_text(encoding="utf-8")
    assert "TYPE=S6" in deck and "TYPE=S3," not in deck and "TYPE=C3D" not in deck
    assert result["max_displacement"] == pytest.approx(0.278, rel=0.03)
    # 응력은 겉면이다 — 손셈은 뿌리의 굽힘 응력이고, 뿌리 구석의 집중이 조금 얹힌다.
    assert result["max_von_mises"] == pytest.approx(16.9, rel=0.1)
    # 질량 = 넓이 x 두께 x 밀도(2000 mm² x 1.2 mm x 7850 kg/m³).
    assert summary["mass_kg"] == pytest.approx(0.0188, rel=0.01)
    # 솔리드가 없어도 그림이 나온다.
    assert (tmp_path / "mode_01.vtp").is_file()


def test_시트를_솔리드_받침에_접착해_푼다(ready: None, tmp_path: Path) -> None:
    """솔리드 받침(base) 위에 시트(skin)를 접착 띠로 붙였다. 손셈 끝 처짐 0.173 mm.
    실측(2026-10-16): 0.1767 mm · 12.54 MPa · *TIE 하나.

    접착 띠(시트)와 받침 윗면(솔리드)이 같은 자리에 있다 — 쉘 면에 파트 이름을 달기 전에는
    두 면을 한 파트로 읽어 「쉘끼리의 접촉」 으로 막았다.
    """
    _place(ASSEMBLY, tmp_path)
    result, summary = _solve(tmp_path, _spec())
    assert summary["shell_bodies"] == "skin 1.2 mm"
    deck = (tmp_path / "model.inp").read_text(encoding="utf-8")
    assert deck.count("*TIE") == 1 and "TYPE=S6" in deck and "TYPE=C3D10" in deck
    assert result["max_displacement"] == pytest.approx(0.173, rel=0.05)
    # 받침(4000 mm³) + 시트(2000 mm² x 1.2 mm) = 6400 mm³ x 7850 kg/m³.
    assert summary["mass_kg"] == pytest.approx(0.0502, rel=0.01)


def test_쉘이_있어도_솔리드_면의_메시_힌트가_그_면에_걸린다(
    ready: None, tmp_path: Path
) -> None:
    """면 힌트는 면만 먼저 메시해 번호를 찾는다(1차 통과). 중간면은 본 통과에서 **먼저** 읽혀
    번호 앞자리를 차지하는데 1차 통과는 그것을 안 읽어서, 쉘이 있는 모델의 솔리드 면 힌트가
    중간면 면 수만큼 밀린 다른 면에 걸렸다(2026-10-16 — 「받침 바닥」 이 5 로, 본 통과에서는
    7)."""
    _place(ASSEMBLY, tmp_path)
    topology = tmp_path / "topology.json"
    payload = json.loads(topology.read_text(encoding="utf-8"))
    payload["conditions"].setdefault("mesh_hints", []).append(
        {"name": "바닥 촘촘히", "on": "받침 바닥", "element_size": 0.7}
    )
    topology.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    run_stage(
        "modeling",
        parse_spec(_spec()),
        tmp_path,
        input_name="input.step",
        version=252,
        ansys_root=None,
        solver_processes=2,
        timeout_seconds=900,
        visual_modes=6,
    )
    geo = (tmp_path / "model.geo").read_text(encoding="utf-8")
    hinted = [int(one) for one in re.findall(r"Surface\{(\d+)\}; \} \} = 0\.7;", geo)]
    mesh = read_mesh(tmp_path / "model.msh", require_solid=False)
    found = match_regions(payload, mesh.faces, wanted_regions=["받침 바닥"])
    assert hinted and hinted == found.faces["받침 바닥"]


def test_두께_없는_시트는_까닭을_달고_멈춘다(ready: None, tmp_path: Path) -> None:
    """CompCore 가 두께를 못 받아 중간면을 못 만들었다 — 그 말을 그대로 전한다."""
    _place(NO_THICKNESS, tmp_path)
    with pytest.raises(StageFailure) as caught:
        _solve(tmp_path, _spec())
    assert "두께가 없습니다" in str(caught.value)


def test_CAD_조건을_끄면_시트를_풀_길이가_없다(ready: None, tmp_path: Path) -> None:
    """쉘 두께는 CAD 의 파트 설정으로만 온다. 끄고 돌리면 시트를 지운 채 풀 것이 아니라 멈춘다
    — 지운 채 풀면 그 파트 없이 그럴듯한 답이 나온다."""
    _place(ASSEMBLY, tmp_path)
    spec = _spec(
        conditions_from="spec",
        constraints=[{"region": "받침 바닥"}],
    )
    with pytest.raises(StageFailure) as caught:
        _solve(tmp_path, spec)
    message = str(caught.value)
    assert "skin" in message and "CAD 가 보낸 조건 사용" in message


@pytest.mark.ansys
def test_두_솔버가_시트_외팔보를_같게_푼다(ready: None, tmp_path: Path) -> None:
    """**교차 검증 — 시트.** Ansys 는 본 형상의 시트를 빼고 중간면의 시트를 쉘로 푼다.
    실측(2026-10-16): CalculiX 0.2766 · Ansys 0.2714 mm(1.9%).

    본 형상의 시트를 그대로 두면 두께 없는 면 바디가 남아 Mechanical 이 입력 파일을 「Send
    Sheet Properties」 에서 끊었다.
    """
    import os

    from app.core import executors
    from app.core.stages import StageContext

    found: dict[str, float] = {}
    for solver in ("calculix", "ansys"):
        work = tmp_path / solver
        _place(CANTILEVER, work)
        spec = _spec(solver=solver)
        (work / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        if solver == "calculix":
            _solve(work, spec)
        else:
            runner = executors.resolve(
                os.environ.get("ANSYS_TEST_EXECUTOR", "local"),
                python=(
                    Path(os.environ["ANSYS_TEST_PYTHON"])
                    if os.environ.get("ANSYS_TEST_PYTHON")
                    else None
                ),
            )
            for stage in STAGES:
                runner.run(StageContext(stage=stage, spec=spec, workdir=work))
        result = json.loads((work / "result.json").read_text(encoding="utf-8"))
        found[solver] = result["max_displacement"]
    assert found["calculix"] == pytest.approx(found["ansys"], rel=0.04), found
    assert found["ansys"] == pytest.approx(0.278, rel=0.05), found
