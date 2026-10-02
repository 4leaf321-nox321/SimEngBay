"""**오픈소스 솔버로 끝까지 도는 시험** — gmsh 로 메시, CalculiX 로 풀기.

Ansys 시험(`tests/ansys/`)과 다른 점은 **라이선스가 없다는 것**이다. 노드락도 없고 Windows 도
필요 없으므로, 도구만 깔려 있으면 CI 에서도 돈다 — 그래서 기본 실행에 들어간다. 도구가 없는 PC
에서는 **까닭을 적고 건너뛴다**(깔라고 말해 주는 것이 「알 수 없는 실패」 보다 낫다).

    sudo apt-get install -y gmsh calculix-ccx     # 또는 손으로 받아 GMSH_BIN · CCX_BIN 지정

여기서 지키는 것은 두 가지다. ① CompCore 가 보낸 **면 지문이 gmsh 메시에서도 풀리나** — 이것이
깨지면 구속을 걸 자리를 못 찾는다. ② **수가 Ansys 와 맞나** — 실측(2026-10-02, 요소 5 mm):
1차 굽힘이 Ansys 1,266.4 Hz · CalculiX 1,263.5 Hz(0.23% 차이).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.core.calculix import tools
from app.core.run import run_stage
from app.core.spec import parse_spec
from app.core.stages import STAGES, StageFailure

pytestmark = pytest.mark.opensolver

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
#: 강판 위 알루미늄 기둥 — 접합부가 굽힘을 떠맡아 솔버 차이가 드러나는 모델.
SIDE_SHAKE = FIXTURES / "doe" / "조건_측면가진"
SPEC: dict[str, Any] = {
    "recipe": "modal",
    "solver": "calculix",
    "material": {
        "name": "SS400",
        "youngs_modulus_gpa": 200,
        "poisson_ratio": 0.3,
        "density_kg_m3": 7850,
    },
    "mesh": {"element_size_mm": 5},
    "modes": 6,
}


@pytest.fixture
def ready() -> None:
    """도구가 없으면 **무엇을 깔아야 하는지 적고** 건너뛴다."""
    for find in (tools.gmsh_bin, tools.ccx_bin):
        try:
            find()
        except StageFailure as failure:
            pytest.skip(str(failure))


def _run(workdir: Path, spec: dict[str, Any]) -> dict[str, Any]:
    """네 단계를 그대로 돌린다 — 실행기를 안 끼운다(여기서는 같은 리눅스에서 다 돈다)."""
    summary: dict[str, Any] = {}
    for stage in STAGES:
        result = run_stage(
            stage,
            parse_spec(spec),
            workdir,
            input_name="input.step",
            version=252,
            ansys_root=None,
            solver_processes=2,
            timeout_seconds=1800,
            visual_modes=6,
        )
        summary.update(result.summary)
    return summary


def test_CAD_폴더를_오픈소스_솔버로_끝까지_푼다(ready: None, tmp_path: Path) -> None:
    """`조건_측면가진` p0001 — 바닥 고정 · 본딩 · 바디마다 다른 물성.

    **CAD 가 보낸 것을 그대로 쓴다**: 면 지문으로 바닥을 찾고, 바디 짝짓기로 물성을 바디마다
    붙인다. 그 코드는 Ansys 경로와 **같은 것**이라, 여기서 도는 것이 곧 그 중립성의 증거다.
    """
    shutil.copy(SIDE_SHAKE / "points" / "p0001.step", tmp_path / "input.step")
    shutil.copy(SIDE_SHAKE / "points" / "p0001.json", tmp_path / "topology.json")
    (tmp_path / "spec.json").write_text(json.dumps(SPEC, ensure_ascii=False), encoding="utf-8")

    summary = _run(tmp_path, SPEC)

    assert summary["solver"] == "calculix"
    assert summary["bodies"] == 2, "솔리드 둘이 들어와야 한다(받침판 · 기둥)"
    # **면 지문이 풀렸는가** — 이것이 깨지면 구속을 걸 자리를 못 찾는다.
    assert summary["constrained_regions"][:2] == ["material:받침판", "material:기둥"]
    assert "fixed_support:바닥" in summary["constrained_regions"]
    # CAD 물성이 바디마다 붙었다 — 강판과 알루미늄이 섞여 있어야 질량이 맞는다.
    assert summary["material_from"] == "cad"
    assert summary["mass_kg"] == pytest.approx(0.5238, rel=0.02)
    # 접촉은 절점 공유로 걸렸고 **그 사실을 적는다** — 조용히 두면 마찰이 들어갔다고 읽는다.
    assert "접촉" in summary["conditions_skipped"]

    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["solver"] == "calculix", "어느 솔버로 풀었는지 결과에 도장이 있어야 한다"
    assert result["boundary"] == "constrained"
    assert result["rigid_body_modes"] == 0, "바닥을 고정했으면 강체 모드가 없다"
    first = result["modes"][0]["frequency_hz"]
    # **Ansys 1,266.4 Hz 와 맞는가.** 메시가 같지 않으므로(gmsh 가 더 촘촘하다) 2% 로 본다.
    assert first == pytest.approx(1266.4, rel=0.02), f"1차 굽힘이 {first} Hz 로 나왔다"
    assert len(result["modes"]) == 6


def test_못_푸는_레시피는_까닭을_달아_거절한다(tmp_path: Path) -> None:
    """정적 · 조화는 아직 CalculiX 경로가 없다 — **조용히 모달로 풀지 않는다.**

    도구가 없어도 도는 시험이다(거절이 메시보다 먼저다). 솔버를 골라 두고 못 푸는 레시피를
    냈을 때, 사람이 「왜 안 되나」 를 바로 알아야 한다.
    """
    shutil.copy(SIDE_SHAKE / "points" / "p0001.step", tmp_path / "input.step")
    spec = {key: value for key, value in SPEC.items() if key != "modes"}
    spec["recipe"] = "static"

    with pytest.raises(StageFailure) as caught:
        _run(tmp_path, spec)

    assert "static" in str(caught.value)
    assert "ansys" in str(caught.value)


def test_점_그룹만_가리키는_구속은_거절한다(ready: None, tmp_path: Path) -> None:
    """점(vertex) 그룹에 고정 지지를 걸면 **면을 못 찾는다** — 그것을 말하고 멈춘다.

    `조건_측면가진` 의 `측정점` 은 꼭짓점 하나다(지문에 `centroid` 가 없다). 조용히 건너뛰면
    구속 없는 해석이 끝까지 돌고 0 Hz 여섯 개가 나오는데, 그 그림은 「해석이 됐다」 처럼
    보인다.
    """
    shutil.copy(SIDE_SHAKE / "points" / "p0001.step", tmp_path / "input.step")
    payload = json.loads((SIDE_SHAKE / "points" / "p0001.json").read_text(encoding="utf-8"))
    payload["conditions"]["constraints"][0]["on"] = "측정점"
    (tmp_path / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(StageFailure) as caught:
        _run(tmp_path, SPEC)

    assert "측정점" in str(caught.value)
    assert "점(vertex)" in str(caught.value)


@pytest.mark.ansys
def test_두_솔버가_같은_폴더에서_같은_수를_낸다(ready: None, tmp_path: Path) -> None:
    """**교차 검증** — Ansys 와 CalculiX 가 같은 설계점에서 몇 % 안에 있나.

    답이 둘이 되는 것이 이 구조의 유일한 위험이다. 메시가 다르고 요소가 다르니(SOLID187 대
    C3D10) 수가 갈리는 것은 정상인데, **얼마나 갈리는지를 아무도 안 보면** 「왜 어제와 값이
    다르냐」 가 영구 미해결로 남는다. 그래서 시험이 그 폭을 지킨다.

    실측(2026-10-02, 요소 5 mm · `조건_측면가진` p0001): 1차 굽힘 Ansys 1,266.4 Hz ·
    CalculiX 1,263.5 Hz(0.23%). 5번 모드만 1.3% 벌어졌다 — 메시 민감도가 큰 모드다.

    Ansys 쪽은 `tests/ansys/` 와 같은 환경 변수를 쓴다(`ANSYS_TEST_EXECUTOR` …).
    """
    import os

    from app.core import executors
    from app.core.stages import StageContext

    both: dict[str, list[float]] = {}
    for solver in ("calculix", "ansys"):
        work = tmp_path / solver
        work.mkdir()
        shutil.copy(SIDE_SHAKE / "points" / "p0001.step", work / "input.step")
        shutil.copy(SIDE_SHAKE / "points" / "p0001.json", work / "topology.json")
        spec = dict(SPEC)
        spec["solver"] = solver
        (work / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        if solver == "calculix":
            _run(work, spec)
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
        assert result["solver"] == solver if solver == "calculix" else True
        both[solver] = [
            one["frequency_hz"] for one in result["modes"] if not one["rigid_body"]
        ]

    assert len(both["ansys"]) >= 5 and len(both["calculix"]) >= 5
    gaps = [
        abs(open_hz - ansys_hz) / ansys_hz
        for ansys_hz, open_hz in zip(both["ansys"], both["calculix"], strict=False)
    ]
    # **1차는 좁게 본다** — 그 모드로 지그를 판정하기 때문이다.
    assert gaps[0] < 0.02, f"1차가 {both['ansys'][0]} 대 {both['calculix'][0]} Hz 로 갈렸다"
    # 나머지는 메시 민감도까지 감안해 3%.
    assert max(gaps[:5]) < 0.03, f"모드별 차이 {[round(one * 100, 2) for one in gaps]}%"
