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
    # **측정점** — CAD 가 점 그룹으로 보낸 자리(기둥 끝 꼭짓점)의 값. 전체 최대만 보면 센서를
    # 붙인 자리와 견줄 수 없다(최대는 구속 모서리의 수치적 첨두일 수 있다).
    spot = next(one for one in result["probes"] if one["name"] == "측정점")
    assert spot["point"] == [5.0, 5.0, 90.0]
    # 형상의 꼭짓점에는 gmsh 가 절점을 놓으므로 **딱 맞는다** — 멀면 결과가 그 사실을 적는다.
    assert spot["distance_mm"] == 0.0
    assert "warning" not in spot
    assert spot["value"] > 0

    first = result["modes"][0]["frequency_hz"]
    # **Ansys 1,266.4 Hz 와 맞는가.** 메시가 같지 않으므로(gmsh 가 더 촘촘하다) 2% 로 본다.
    assert first == pytest.approx(1266.4, rel=0.02), f"1차 굽힘이 {first} Hz 로 나왔다"
    assert len(result["modes"]) == 6


def test_능력표에_없는_구속은_까닭을_달아_거절한다(ready: None, tmp_path: Path) -> None:
    """탄성 지지는 아직 못 건다 — **조용히 완전 고정으로 바꾸지 않는다.**

    고정으로 바꿔 풀면 더 단단한 모델이 되어 주파수가 올라가는데, 결과만 보면 알 수 없다.
    능력표(`calculix/deck.py` 의 `SUPPORTED_CONSTRAINTS`)에 없으면 멈추고, **어떻게 하면
    되는지**까지 말한다.
    """
    shutil.copy(SIDE_SHAKE / "points" / "p0001.step", tmp_path / "input.step")
    payload = json.loads((SIDE_SHAKE / "points" / "p0001.json").read_text(encoding="utf-8"))
    payload["conditions"]["constraints"][0]["type"] = "elastic_support"
    payload["conditions"]["constraints"][0]["stiffness"] = 1000.0
    (tmp_path / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(StageFailure) as caught:
        _run(tmp_path, SPEC)

    assert "elastic_support" in str(caught.value)
    assert "ansys" in str(caught.value).lower(), "어떻게 하면 되는지까지 말해야 한다"


#: `조건_원통_SI` 를 Ansys 로 돌린 값(실측 2026-10-03 · 요소 4 mm · 물성은 스펙).
#: 1차는 **0 Hz** 다 — 접선이 자유라 핀을 축으로 돈다. 그 뒤가 탄성 모드다.
CYLINDER_ANSYS_HZ = (2165.2, 4746.0, 11051.5, 11640.5, 13943.9)


def test_원통면을_메시에서_되맞춰_구속을_건다(ready: None, tmp_path: Path) -> None:
    """**곡면 지문을 메시에서 되살린다** — 그러면 원통 지지가 걸린다.

    조건은 면 번호로 오지 않는다. 평면은 `무게중심 · 면적 · 법선`, 원통은 `반지름 · 축` 으로
    온다. Mechanical 은 형상을 들고 있어 그 둘을 바로 주지만 우리는 메시만 있다 — 그래서
    삼각형에서 **되맞춘다**(법선이 수직인 축을 찾고, 절점에 원을 맞춘다).

    삼각형 무게중심으로 반지름을 재면 **내접 다각형이라 작게 나온다**(실측: 5.0 이 4.75) —
    그래서 면 위에 있는 **절점**으로 맞춘다.

    원통 지지는 국부 좌표계로 건다(`*TRANSFORM, TYPE=C`): 자유도 1 반경 · 2 접선 · 3 축.
    이 폴더는 **접선만 자유**라 핀에 끼운 채 돈다 — 그래서 0 Hz 모드가 하나 나오고, 결과가
    그 사실을 경고로 말한다. 영역별 메시 힌트(구멍면 2 mm)도 함께 걸린다.
    """
    cylinder = FIXTURES / "doe" / "조건_원통_SI"
    shutil.copy(cylinder / "points" / "p0001.step", tmp_path / "input.step")
    shutil.copy(cylinder / "points" / "p0001.json", tmp_path / "topology.json")
    spec = dict(SPEC)
    spec["material_from"] = "spec"  # 이 폴더의 물성에는 탄성계수가 없다.
    spec["mesh"] = {"element_size_mm": 6}

    summary = _run(tmp_path, spec)

    assert "cylindrical:구멍면" in summary["constrained_regions"]
    deck = (tmp_path / "model.inp").read_text(encoding="utf-8")
    assert "*TRANSFORM, NSET=HOLD0, TYPE=C" in deck
    held = [
        one.strip()
        for one in deck.split("*TRANSFORM")[1].split("*BOUNDARY")[1].splitlines()
        if one.startswith("HOLD0")
    ]
    # 반경(1) · 축(3) 고정, **접선(2) 자유** — 그것이 「핀에 끼운 채 돈다」 다.
    assert held == ["HOLD0, 1, 1, 0.0", "HOLD0, 3, 3, 0.0"]
    # 영역별 메시 힌트가 gmsh 에게 갔다 — 구멍면만 2 mm(선언은 0.002 m).
    geo = (tmp_path / "model.geo").read_text(encoding="utf-8")
    assert "MeshSize{ PointsOf{ Surface{" in geo
    assert "= 2;" in geo

    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    # **0 Hz 모드를 말해 준다** — 자유로 둔 방향이 있다는 뜻이다. 구속을 잘못 걸어 통째로
    # 떠 있는 경우도 똑같이 보이므로 값만으로 가르지 않는다.
    assert "0 Hz" in result.get("warning", "")
    elastic = [one["frequency_hz"] for one in result["modes"]][1:]
    gaps = [
        abs(open_hz - ansys_hz) / ansys_hz
        for ansys_hz, open_hz in zip(CYLINDER_ANSYS_HZ, elastic, strict=False)
    ]
    assert max(gaps) < 0.02, f"Ansys 와 {[round(one * 100, 2) for one in gaps]}% 갈렸다"


def test_베어링_하중은_구멍의_반쪽에_국부_성분으로_걸린다(ready: None, tmp_path: Path) -> None:
    """핀이 밀면 구멍은 **그 방향 쪽 반쪽만** 눌린다.

    면 전체에 고르게 걸면 합력은 같아도 반대쪽을 당기는 모델이 되어, 구멍 주변 변형이 달라진다.
    그래서 분담 면적에 반경 방향과 하중 방향의 겹침(cos)을 곱한다.

    그리고 **국부 좌표계가 걸린 절점에서는 `*CLOAD` 의 방향도 국부로 읽힌다** — CalculiX 가
    `*TRANSFORM` 을 구속과 하중에 함께 적용한다. 전역 성분을 그대로 적으면 힘이 반경 · 접선 ·
    축으로 뒤바뀌고, 그 결과는 오류 없이 그럴듯하게 나온다(실측 2026-10-03에 그 자리를 밟았다).
    """
    cylinder = FIXTURES / "doe" / "조건_원통_SI"
    shutil.copy(cylinder / "points" / "p0001.step", tmp_path / "input.step")
    shutil.copy(cylinder / "points" / "p0001.json", tmp_path / "topology.json")
    spec = {key: value for key, value in SPEC.items() if key != "modes"}
    spec["recipe"] = "static"
    spec["material_from"] = "spec"
    spec["mesh"] = {"element_size_mm": 6}

    summary = _run(tmp_path, spec)

    assert "bearing:구멍면" in summary["constrained_regions"]
    deck = (tmp_path / "model.inp").read_text(encoding="utf-8")
    hole = {
        int(one.strip())
        for line in deck.split("*NSET, NSET=HOLD0")[1].split("*TRANSFORM")[0].splitlines()
        for one in line.split(",")
        if one.strip().isdigit()
    }
    loaded: set[int] = set()
    local = 0
    for block in deck.split("*CLOAD")[1:]:
        for line in block.splitlines():
            if not line.strip():
                # `*CLOAD` 바로 뒤의 빈 줄 — 여기서 멈추면 한 줄도 못 읽는다.
                continue
            parts = [one.strip() for one in line.split(",")]
            if len(parts) != 3 or not parts[0].isdigit():
                break
            node, dof = int(parts[0]), parts[1]
            if node in hole:
                loaded.add(node)
                if dof in ("1", "2"):
                    local += 1
    assert hole and loaded, "구멍면에 하중이 걸려야 한다"
    # **반쪽만** 받는다 — 전부 받으면 분포가 아니라 평균이다.
    assert 0.3 < len(loaded) / len(hole) < 0.7, (
        f"구멍 절점 {len(hole)} 중 {len(loaded)} 이 받았다"
    )
    # 그 절점의 성분은 **국부**(반경 · 접선)다 — 전역 X 로 적혀 있으면 안 된다.
    assert local >= len(loaded), "국부 성분으로 적혀야 한다"

    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["max_displacement"] > 0


def test_정적_해석이_변형과_응력을_낸다(ready: None, tmp_path: Path) -> None:
    """`조건_두바디_두재료` — 바닥 고정 · 블록 윗면 압력 1.5 MPa.

    **Ansys 와 견준다**(실측 2026-10-02: 변형 5.204e-4 mm · 응력 2.523 MPa). 변형은 0.4% 안에서
    맞는다. **첨두응력은 그만큼 못 맞는다** — 요소에서 절점으로 외삽한 값이라 메시와 외삽
    방식에
    크게 흔들린다(실측 1.959 MPa, 22% 낮다). 그래서 응력은 **자릿수와 범위**만 지킨다: 그 폭을
    좁게 잡으면 메시를 조금 바꿀 때마다 깨지고, 아무도 안 보는 시험이 된다.
    """
    two_bodies = FIXTURES / "doe" / "조건_두바디_두재료"
    shutil.copy(two_bodies / "points" / "p0001.step", tmp_path / "input.step")
    shutil.copy(two_bodies / "points" / "p0001.json", tmp_path / "topology.json")
    spec = {key: value for key, value in SPEC.items() if key != "modes"}
    spec["recipe"] = "static"
    spec["mesh"] = {"element_size_mm": 8}

    summary = _run(tmp_path, spec)

    assert summary["mass_kg"] == pytest.approx(0.3213, rel=0.02)
    assert "pressure:블록 윗면" in summary["constrained_regions"]
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["recipe"] == "static"
    assert result["solver"] == "calculix"
    assert result["units"]["displacement"] == "mm"
    # **0 인 결과는 「해석이 됐다」 처럼 보인다** — 그래서 경고가 없어야 한다.
    assert "warning" not in result
    assert result["max_displacement"] == pytest.approx(5.204e-4, rel=0.05)
    assert 1.0 < result["max_von_mises"] < 4.0
    # 변형 그림도 남는다 — 모달의 모드 형상과 같은 길이라 화면이 그대로 읽는다.
    assert (tmp_path / "mode_01.vtp").is_file()


def test_조화_응답이_공진에서_솟고_CAD_감쇠를_쓴다(ready: None, tmp_path: Path) -> None:
    """`조건_측면가진` — 기둥 끝에 X 10 N, CAD 가 200~2000 Hz · 감쇠 0.02 를 적어 보낸다.

    **Ansys 와 견준다**(실측 2026-10-02: 봉우리 1,260 Hz · 0.703 mm). CalculiX 는 1,263.5 Hz ·
    0.728 mm 다 — 주파수 0.3% · 진폭 3.6% 차이.

    **스펙은 일부러 다른 값을 들고 있다**(10~100 Hz · 감쇠 0.05) — CAD 가 이기는지 보려는
    것이다. 조용히 스펙으로 풀면 봉우리가 창 밖이고 결과는 오류 없이 평평하게 나온다.

    그리고 **점이 요청보다 많다**: CalculiX 는 점 수를 고유진동수 **사이마다** 쓴다(실측 90 →
    268점). 그 덕에 봉우리가 점 사이로 빠져나갈 수 없다.
    """
    shutil.copy(SIDE_SHAKE / "points" / "p0001.step", tmp_path / "input.step")
    shutil.copy(SIDE_SHAKE / "points" / "p0001.json", tmp_path / "topology.json")
    spec = {key: value for key, value in SPEC.items()}
    spec["recipe"] = "harmonic"
    spec["frequency_range_hz"] = [10, 100]
    spec["intervals"] = 5
    spec["damping_ratio"] = 0.05

    _run(tmp_path, spec)

    deck = (tmp_path / "model.inp").read_text(encoding="utf-8")
    # 감쇠는 `*MODAL DAMPING` 한 줄이다 — Ansys 에서는 명령 조각이 필요했다.
    assert "*MODAL DAMPING" in deck
    assert "0.02" in deck.split("*MODAL DAMPING")[1].splitlines()[1]
    # CAD 의 범위가 이겼다 — 스펙은 10~100 Hz 였다.
    assert "*STEADY STATE DYNAMICS" in deck
    assert deck.split("*STEADY STATE DYNAMICS")[1].splitlines()[1].startswith("200")

    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["recipe"] == "harmonic"
    assert result["damping_ratio"] == 0.02, "CAD 가 적어 보낸 감쇠비를 써야 한다"
    assert len(result["points"]) > 90, "고유진동수 사이마다 점이 들어가므로 더 촘촘하다"
    # **측정점의 곡선** — 주파수마다 그 자리의 응답이 붙는다. 전체 최대는 자리가 주파수마다
    # 옮겨 다닐 수 있고, 센서는 한 자리에 붙어 있다.
    assert all("측정점" in one["probes"] for one in result["points"])
    spot_peak = max(result["points"], key=lambda one: one["probes"]["측정점"])
    assert spot_peak["frequency_hz"] == pytest.approx(1263.5, rel=0.02)

    peak = result["peak"]
    assert peak["frequency_hz"] == pytest.approx(1263.5, rel=0.02)
    assert peak["max_displacement"] == pytest.approx(0.703, rel=0.1)
    # 공진에서 솟았다 — 창에서 가장 조용한 자리의 열 배를 넘는다.
    floor = min(one["max_displacement"] for one in result["points"])
    assert peak["max_displacement"] > 10 * floor


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
    spots: dict[str, float] = {}
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
        # **측정점도 견준다** — 같은 자리의 값이라야 실측과 맞춰 볼 수 있다. 모드 형상은 질량
        # 정규화된 값이라 크기가 솔버 구현에 달려 있어 폭을 넓게 둔다(실측 2026-10-03:
        # Ansys 430.96 · CalculiX 427.73 — 0.76% 차이).
        spots[solver] = next(
            one["value"] for one in result["probes"] if one["name"] == "측정점"
        )

    assert len(both["ansys"]) >= 5 and len(both["calculix"]) >= 5
    gaps = [
        abs(open_hz - ansys_hz) / ansys_hz
        for ansys_hz, open_hz in zip(both["ansys"], both["calculix"], strict=False)
    ]
    # **1차는 좁게 본다** — 그 모드로 지그를 판정하기 때문이다.
    assert gaps[0] < 0.02, f"1차가 {both['ansys'][0]} 대 {both['calculix'][0]} Hz 로 갈렸다"
    # 나머지는 메시 민감도까지 감안해 3%.
    assert max(gaps[:5]) < 0.03, f"모드별 차이 {[round(one * 100, 2) for one in gaps]}%"
    assert spots["calculix"] == pytest.approx(spots["ansys"], rel=0.05), (
        f"측정점 값이 갈렸다: Ansys {spots['ansys']} · CalculiX {spots['calculix']}"
    )


#: 조건 · 물성 배율을 훑는 폴더 — p0001 은 **접착**, p0003 은 **마찰**이다(같은 형상).
CONDITION_SWEEP = FIXTURES / "doe" / "조건_조건훑기"
SWEEP_SHAPE = CONDITION_SWEEP / "shapes" / "c3aed82c2d74.step"


def _sweep(tmp_path: Path, point: int, *, prestressed: bool | None = None) -> Path:
    """`조건_조건훑기` 의 한 점을 작업 폴더에 깐다."""
    work = tmp_path / f"p{point:04d}"
    work.mkdir()
    shutil.copy(SWEEP_SHAPE, work / "input.step")
    payload = json.loads(
        (CONDITION_SWEEP / "points" / f"p{point:04d}.json").read_text(encoding="utf-8")
    )
    if prestressed is not None:
        payload["conditions"]["analysis"]["prestressed"] = prestressed
    (work / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return work


def test_마찰_접촉은_정적에서_비선형으로_풀고_접착과_거의_같다(
    ready: None, tmp_path: Path
) -> None:
    """같은 형상 · 같은 하중에서 **접착과 마찰이 거의 같아야 한다** — 이 이음은 압축만 받는다.

    블록을 위에서 누르므로 접합면에 전단이 없다. 그러면 마찰이 붙잡을 것이 없고, 접착과 같은
    답이 나오는 것이 **맞다.** Ansys 로 같은 점을 돌려 확인했다(실측 2026-10-03: 접착
    1.9545e-4 · 마찰 1.9501e-4 mm — 0.2% 차이).

    **이 시험이 한 번 거짓을 지켰다.** 접촉 강성을 1e4 N/mm³ 고정값으로 두었을 때 마찰이
    3.350e-4 mm(73% 더 무름)로 나왔고, 나는 그것을 「마찰이 더 밀린다」 로 단정했다. 실은 압력
    1.5 MPa ÷ 1e4 = 1.5e-4 mm 만큼 **면이 파고든 것**이었다 — 물리가 아니라 접촉 스프링의
    무름이다. 이제 강성을 `10 x E / h` 로 끌어내고(요소 8 mm · E 200 GPa → 250,000 N/mm³)
    차이가 2.7% 로 줄었다.

    교훈은 하나다: **한 솔버의 수만 보면 그 수가 가짜인지 모른다.**
    """
    spec = {key: value for key, value in SPEC.items() if key != "modes"}
    spec["recipe"] = "static"
    spec["material_from"] = "spec"
    spec["mesh"] = {"element_size_mm": 8}

    bonded = _sweep(tmp_path, 1)
    (bonded / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    _run(bonded, spec)
    rubbing = _sweep(tmp_path, 3)
    (rubbing / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    summary = _run(rubbing, spec)

    assert any("frictional" in one for one in summary["constrained_regions"])
    deck = (rubbing / "model.inp").read_text(encoding="utf-8")
    assert "*CONTACT PAIR" in deck
    assert "PRESSURE-OVERCLOSURE=LINEAR" in deck
    assert "*FRICTION" in deck
    # 강성은 **끌어낸 값**이다 — 고정값이면 압력에 따라 면이 파고든다.
    assert "250000" in deck.split("PRESSURE-OVERCLOSURE=LINEAR")[1].splitlines()[1]
    # 면 정의는 `S1` 로 적는다 — 압력의 `P1` 과 섞으면 ccx 가 못 읽는다(실측).
    assert "*SURFACE, NAME=C0S, TYPE=ELEMENT" in deck
    assert ", S" in deck.split("*SURFACE, NAME=C0S, TYPE=ELEMENT")[1].splitlines()[1]

    tight = json.loads((bonded / "result.json").read_text(encoding="utf-8"))
    loose = json.loads((rubbing / "result.json").read_text(encoding="utf-8"))
    gap = (
        abs(loose["max_displacement"] - tight["max_displacement"]) / tight["max_displacement"]
    )
    assert gap < 0.1, (
        f"압축만 받는 이음이라 접착과 비슷해야 한다: {loose['max_displacement']} 대 "
        f"{tight['max_displacement']} ({gap * 100:.1f}%)"
    )
    # **마지막 증분**의 값이다 — 첫 증분을 읽으면 1e-5 자리가 나온다(실측 0.17배).
    assert loose["max_displacement"] > 1.5e-4
    # Ansys 와도 견준다(실측 1.9501e-4) — 두 솔버가 같은 자리에 있어야 수를 믿을 수 있다.
    assert loose["max_displacement"] == pytest.approx(1.95e-4, rel=0.05)


def test_고유치에는_접촉을_넣지_않고_그렇게_말한다(ready: None, tmp_path: Path) -> None:
    """**CalculiX 는 고유치 해석에 접촉을 넣지 않는다** — 실측으로 가린 사실이다.

    TIED 접촉 쌍을 넣고 `*FREQUENCY` 를 풀었더니 강체 모드 6개(0 · 0 · 0.0014 · 0.0016 ·
    0.002 · 0.0022 Hz)가 나왔다 — 블록이 떠 있었다. `*STEP, PERTURBATION` 으로 비선형 정적
    뒤에 붙여도 여덟 모드가 전부 0 Hz 였다. 접촉 요소는 비선형 단계에서만 만들어진다.

    그래서 모달은 **절점을 공유시켜** 붙은 것으로 풀고, 그 사실과 「마찰을 비선형으로 보려면
    어떻게 하라」 를 요약에 적는다. 조용히 두면 사람은 마찰이 모델에 들어갔다고 읽는다.
    """
    spec = dict(SPEC)
    spec["material_from"] = "spec"
    spec["mesh"] = {"element_size_mm": 8}
    work = _sweep(tmp_path, 3)
    (work / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    summary = _run(work, spec)

    deck = (work / "model.inp").read_text(encoding="utf-8")
    assert "*CONTACT PAIR" not in deck, "고유치 덱에 접촉을 넣으면 바디가 뜬다"
    assert "고유치" in summary["conditions_skipped"]
    assert "ansys" in summary["conditions_skipped"].lower()
    result = json.loads((work / "result.json").read_text(encoding="utf-8"))
    # 절점을 공유했으니 떠 있는 모드가 없다 — 있으면 붙지 않은 것이다.
    assert all(one["frequency_hz"] > 1.0 for one in result["modes"])
    assert "warning" not in result


def test_선응력_모달은_응력_강화를_물고_간다(ready: None, tmp_path: Path) -> None:
    """조여 놓은 상태의 공진 — **비선형 정적 뒤에 선형화해서** 모드를 뽑는다.

    누르는 하중은 구조를 무르게 하므로 주파수가 **내려간다.** 실측 2026-10-03:
    31,604.72 → 31,603.95 Hz(0.77 Hz 내려간다). Ansys 쪽도 같은 방향이었다
    (30,090.3497 → 30,090.1351).

    차이가 작지만 **방향이 정해져 있다** — 같은 값이 나오면 선응력이 안 걸린 것이고, 그때는
    두 단계를 쓴 뜻이 없다.
    """
    two_bodies = FIXTURES / "doe" / "조건_두바디_두재료"
    spec = dict(SPEC)
    spec["mesh"] = {"element_size_mm": 8}
    seen: dict[bool, float] = {}
    for prestressed in (False, True):
        work = tmp_path / ("선응력" if prestressed else "그냥")
        work.mkdir()
        shutil.copy(two_bodies / "points" / "p0001.step", work / "input.step")
        payload = json.loads(
            (two_bodies / "points" / "p0001.json").read_text(encoding="utf-8")
        )
        payload["conditions"]["analysis"]["prestressed"] = prestressed
        (work / "topology.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        (work / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        _run(work, spec)
        result = json.loads((work / "result.json").read_text(encoding="utf-8"))
        seen[prestressed] = result["modes"][0]["frequency_hz"]
        if prestressed:
            deck = (work / "model.inp").read_text(encoding="utf-8")
            # 두 단계다 — 비선형 정적, 그리고 그 상태의 고유치.
            assert "*STEP, NLGEOM" in deck
            assert "*STEP, PERTURBATION" in deck

    assert seen[True] < seen[False], f"선응력이 안 걸렸다: {seen}"
    # 너무 많이 내려가면 하중이 과한 것이다 — 0.1% 안에 있어야 한다(실측 0.0024%).
    assert (seen[False] - seen[True]) / seen[False] < 0.001
