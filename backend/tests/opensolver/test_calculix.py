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
    # **실제로 쓴 전역 요소 크기** — 메시 수렴 점검이 이것을 기준으로 줄인다.
    assert summary["element_size_mm"] == 5
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
    # **탄성 모드 전부에서 읽는다** — 실측 공진과 짝을 지을 때 「센서 자리에서 안 움직이는
    # 모드는 실측에 안 보인다」 가 첫 거름망이다. 성분도 싣는다(어느 방향으로 움직이나).
    elastic = {one["number"] for one in result["modes"] if not one["rigid_body"]}
    assert {one["mode"] for one in result["probes"]} == elastic
    assert all(len(one["vector"]) == 3 for one in result["probes"])

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
    # 측정점마다 **그 자리의 봉우리 한 줄** — 절점 거리 · 경고가 곡선 대신 여기 실린다.
    top = next(one for one in result["probes"] if one["name"] == "측정점")
    assert top["frequency_hz"] == spot_peak["frequency_hz"]
    assert top["value"] == spot_peak["probes"]["측정점"]
    assert top["distance_mm"] == 0.0 and top["unit"] == "mm"

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


def test_마찰_접촉은_정적에서_비선형으로_풀고_접착보다_무르다(
    ready: None, tmp_path: Path
) -> None:
    """같은 형상 · 같은 하중에서 마찰은 **접착보다 무르거나 같다** — 단단할 수는 없다.

    이 이음은 압축만 받지만, 눌린 블록이 옆으로 퍼지려 하므로(푸아송) 마찰이면 가장자리가 조금
    미끄러지고, 접촉면 자체도 유한 강성이다. 그래서 접착보다 더 밀린다.

    **얼마나 더 밀리나는 솔버가 정한다** — 실측 2026-10-03(요소 8 mm · 물성은 스펙):

        CalculiX   접착 1.932e-4 · 마찰 1.983e-4 mm   (+2.7%, 접촉 강성 10 x E / h)
        Ansys      접착 1.955e-4 · 마찰 2.297e-4 mm   (+17.5%, 프로그램 제어)

    그래서 두 수를 단정하지 않고 **방향과 자릿수만** 본다. 이 기록에는 거짓 숫자가 두 번
    끼었다: ① 접촉 강성을 1e4 N/mm³ 로 두어 면이 파고든 CalculiX 의 +73%. ② 그것을 「틀렸다」
    고 판정한 Ansys 의 +0.2% — 그 값은 Mechanical 의 **자동 접착 접촉**이 우리 마찰 접촉을
    덮어서 나온 것이었다. 기준이 틀리면 교차 검증이 틀린 결론을 확인해 준다.
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
    # 강성은 **끌어낸 값**이다 — 고정값이면 압력에 따라 면이 파고든다(+73% 의 원인).
    assert "250000" in deck.split("PRESSURE-OVERCLOSURE=LINEAR")[1].splitlines()[1]
    # 면 정의는 `S1` 로 적는다 — 압력의 `P1` 과 섞으면 ccx 가 못 읽는다(실측).
    assert "*SURFACE, NAME=C0S, TYPE=ELEMENT" in deck
    assert ", S" in deck.split("*SURFACE, NAME=C0S, TYPE=ELEMENT")[1].splitlines()[1]

    tight = json.loads((bonded / "result.json").read_text(encoding="utf-8"))
    loose = json.loads((rubbing / "result.json").read_text(encoding="utf-8"))
    # 마찰은 접착보다 **단단할 수 없다**.
    assert loose["max_displacement"] >= tight["max_displacement"]
    # 그리고 접촉 스프링이 파고드는 자릿수(+73%)는 아니다 — 끌어낸 강성의 증거다.
    assert loose["max_displacement"] < tight["max_displacement"] * 1.3
    # **마지막 증분**의 값이다 — 첫 증분을 읽으면 1e-5 자리가 나온다(실측 0.17배).
    assert loose["max_displacement"] > 1.5e-4


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


#: CompCore 의 전단 이음(2026-10-03) — 강판 위 알루미늄 판을 40 mm 겹쳐 놓고, 겹친 자리를
#: 클램프로 누른 채 위판 끝을 **변위**로 0.04 mm 당긴다. 마찰이 일을 하는지 보는 폴더다.
SHEAR_JOINT = FIXTURES / "doe" / "조건_전단이음"


def _shear(tmp_path: Path, point: int) -> dict[str, Any]:
    """전단 이음의 한 점을 풀고 결과를 돌려준다."""
    work = tmp_path / f"p{point:04d}"
    work.mkdir()
    shutil.copy(next(iter((SHEAR_JOINT / "shapes").glob("*.step"))), work / "input.step")
    shutil.copy(SHEAR_JOINT / "points" / f"p{point:04d}.json", work / "topology.json")
    spec = {key: value for key, value in SPEC.items() if key != "modes"}
    spec["recipe"] = "static"
    spec["mesh"] = {"element_size_mm": 2.5}
    (work / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    _run(work, spec)
    result: dict[str, Any] = json.loads((work / "result.json").read_text(encoding="utf-8"))
    return result


def _slip(result: dict[str, Any]) -> float:
    """미끄럼 = 이음 입구에서 위판과 아래판의 X 변위 차(같은 자리의 두 바디 꼭짓점)."""
    spots = {one["name"]: one for one in result["probes"]}
    upper, lower = spots["이음 입구 위판"], spots["이음 입구 아래판"]
    return float(upper["vector"][0] - lower["vector"][0])


def test_전단_이음에서_마찰이_일을_한다(ready: None, tmp_path: Path) -> None:
    """**마찰이 μN 에서 버티기를 멈춘다** — CompCore 가 우리를 시험하려고 만든 폴더다.

    클램프 12.5 MPa x 800 mm² = 10 kN, μ 0.15 → μN = **1,500 N**. 위판 끝을 0.04 mm 당기면
    접착은 축강성만큼 버티고(손셈 3.2~3.9 kN), 마찰은 1,500 N 에서 미끄러진다. 그쪽 말:
    「2 번에서 두 솔버가 차이 없음이면 그쪽이 틀린 것이다」.

    실측 2026-10-03(요소 2.5 mm): 접착 3,631 N · 미끄럼 0 / 마찰 **1,499.6 N** · 미끄럼
    0.0217 mm. Ansys 도 1,483 N · 0.0218 mm 로 맞다 — Ansys 쪽은 처음에 접착 반력 3,627 N 을
    냈는데, Mechanical 이 형상을 읽을 때 만든 **자동 접착 접촉**이 우리 마찰 접촉을 덮고
    있었다.

    미끄럼은 같은 자리(60, 12.5, 5)의 **두 바디 꼭짓점**의 X 차다 — 지문의 `body` 로 가르지
    않으면 둘이 같은 절점을 잡아 늘 0 이 된다.
    """
    bonded = _shear(tmp_path, 1)
    rubbing = _shear(tmp_path, 2)

    pull_bonded = bonded["reactions"]["당기는 끝"][0]
    pull_rubbing = rubbing["reactions"]["당기는 끝"][0]
    assert 3200 < pull_bonded < 3900, f"접착 반력이 손셈 밖이다: {pull_bonded} N"
    assert pull_rubbing == pytest.approx(1500, rel=0.05), (
        f"마찰이 μN(1,500 N)에서 멈춰야 한다: {pull_rubbing} N"
    )
    # 접착은 같은 절점을 공유하므로(메시를 쪼갰다) 미끄럼이 0 이다.
    assert _slip(bonded) == pytest.approx(0.0, abs=1e-9)
    assert 0.018 < _slip(rubbing) < 0.026, f"미끄럼 {_slip(rubbing)} mm"
    # 측정점이 바디를 갈랐다 — 같은 자리의 다른 바디 꼭짓점이다.
    spots = {one["name"]: one for one in rubbing["probes"]}
    assert spots["이음 입구 위판"]["body"] == "위판"
    assert spots["이음 입구 아래판"]["body"] == "아래판"
    assert spots["이음 입구 위판"]["node"] != spots["이음 입구 아래판"]["node"]
    # **변형률도 그 자리에서** — 스트레인 게이지와 견주는 값이다(수직 셋, 무차원). 당기는 방향
    # (X)으로 위판이 늘어난다. 크기는 응력/E 의 자릿수다(수백 마이크로).
    strain = spots["이음 입구 위판"]["strain"]
    assert len(strain) == 3
    assert 1e-6 < abs(strain[0]) < 1e-2, f"εxx {strain[0]}"


def test_메시를_줄이면_1차_주파수가_수렴하고_GCI_가_그만큼을_말한다(
    ready: None, tmp_path: Path
) -> None:
    """**진짜 메시로** 메시 수렴 판정을 돌린다 — `조건_측면가진`(바닥 고정 기둥)의 1차 굽힘을
    요소 크기 4 · 2.8 · 2.0 mm 로 푼다.

    2차 사면체라 1차 주파수는 빠르게 자리를 잡는다 — 관측 차수가 양수이고 GCI 가 1% 아래여야
    한다. 이것이 깨지면 판정 코드(`app/core/convergence.py`)나 메시 크기 전달 중 하나가 틀렸다.
    """
    from app.core.convergence import judge

    levels: list[tuple[int, float]] = []
    for size in (4.0, 2.8, 2.0):
        work = tmp_path / f"h{size}"
        work.mkdir()
        shutil.copy(SIDE_SHAKE / "points" / "p0001.step", work / "input.step")
        shutil.copy(SIDE_SHAKE / "points" / "p0001.json", work / "topology.json")
        spec = {**SPEC, "mesh": {"element_size_mm": size}, "modes": 2}
        summary = _run(work, spec)
        assert summary["element_size_mm"] == size
        result = json.loads((work / "result.json").read_text(encoding="utf-8"))
        first = next(one for one in result["modes"] if not one["rigid_body"])
        levels.append((int(summary["nodes"]), float(first["frequency_hz"])))

    nodes = [one[0] for one in levels]
    assert nodes == sorted(nodes), f"크기를 줄이면 절점이 늘어야 한다: {nodes}"
    verdict = judge(levels, tolerance=0.01)
    assert verdict.status == "converged", (levels, verdict)
    assert verdict.gci is not None and verdict.gci < 0.01
    assert verdict.extrapolated == pytest.approx(levels[-1][1], rel=0.01)


# --- 파트별 설정(CompCore body_settings, 2026-10-04) -----------------------------


def _side_shake_with(
    work: Path,
    settings: list[dict[str, Any]],
    *,
    free: bool = False,
    aluminum_plate: bool = False,
) -> None:
    """`조건_측면가진`(강판 위 알루미늄 기둥, 바닥 고정)에 파트별 설정을 얹는다."""
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(SIDE_SHAKE / "points" / "p0001.step", work / "input.step")
    payload = json.loads((SIDE_SHAKE / "points" / "p0001.json").read_text(encoding="utf-8"))
    payload["conditions"]["body_settings"] = settings
    if free:
        payload["conditions"]["constraints"] = []
    if aluminum_plate:
        # 재료를 맞바꾼다 — 판이 알루미늄, 기둥이 강. **강체 질량이 CAD 밀도를 따르나**를 본다.
        for row in payload["conditions"]["materials"]:
            row["apply_to"] = ["기둥"] if row["apply_to"] == ["받침판"] else ["받침판"]
    (work / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _first(work: Path) -> float:
    result = json.loads((work / "result.json").read_text(encoding="utf-8"))
    return float(next(one["frequency_hz"] for one in result["modes"] if not one["rigid_body"]))


def test_파트별_설정_강체_제외_파트_메시(ready: None, tmp_path: Path) -> None:
    """**강체 · 해석 제외 · 파트 메시가 물리대로 움직이나.**

    실측(2026-10-04, 요소 5 mm): 기본 1,263.5 Hz · 받침판 강체 1,289.0 Hz(받침이 굳어 오른다) ·
    기둥 제외 76 kHz(바닥이 고정된 판만 남는다, 질량은 판 0.5024 kg) · 기둥 1.5 mm 1,257.3 Hz
    (절점 6,401 → 28,217, 메시가 고와져 조금 내려간다).
    """
    base = tmp_path / "base"
    _side_shake_with(base, [])
    plain = _run(base, SPEC)
    plain_hz = _first(base)

    rigid = tmp_path / "rigid"
    _side_shake_with(rigid, [{"name": "받침판", "behavior": "rigid"}])
    stiff = _run(rigid, SPEC)
    assert stiff["rigid_bodies"] == "받침판"
    assert "rigid:받침판" in stiff["constrained_regions"]
    # 강체도 질량은 그대로다 — 요소를 남겨 둔다.
    assert stiff["mass_kg"] == pytest.approx(plain["mass_kg"], rel=1e-3)
    assert 1.005 < _first(rigid) / plain_hz < 1.05

    off = tmp_path / "off"
    _side_shake_with(off, [{"name": "기둥", "suppressed": True}])
    alone = _run(off, SPEC)
    assert alone["bodies"] == 1 and alone["suppressed_bodies"] == "기둥"
    assert alone["mass_kg"] == pytest.approx(0.5024, rel=0.01)
    assert _first(off) > 10 * plain_hz

    fine = tmp_path / "fine"
    _side_shake_with(fine, [{"name": "기둥", "mesh": {"element_size": 1.5}}])
    dense = _run(fine, SPEC)
    assert int(dense["nodes"]) > 2 * int(plain["nodes"])
    assert _first(fine) == pytest.approx(plain_hz, rel=0.02)


def test_중간면이_없는_쉘_파트는_멈춘다(ready: None, tmp_path: Path) -> None:
    """**솔리드로 풀지 않는다** — 점 파일에 그 파트의 중간면이 없으면 까닭을 달고 멈춘다."""
    _side_shake_with(tmp_path, [{"name": "기둥", "representation": "shell"}])
    with pytest.raises(StageFailure) as caught:
        _run(tmp_path, SPEC)
    assert "쉘" in str(caught.value) and "기둥" in str(caught.value)


@pytest.mark.ansys
def test_두_솔버가_강체를_같게_푼다(ready: None, tmp_path: Path) -> None:
    """**교차 검증 — 강체.** 알루미늄 받침판을 강체로, 구속 없이(자유-자유) 푼다.

    Ansys 는 강체를 `MASS21` 한 점으로 보내고 질량을 Engineering Data(강)로 계산한다 — 우리가
    밀도 비만큼 고친다(`mechanical/build.py` 의 `_rigid_mass`). 그 보정이 빠지면 판이 강의
    질량(약 3배)으로 풀려 1차가 크게 내려간다. CalculiX 는 요소를 남기므로 CAD 밀도 그대로다.
    """
    import os

    from app.core import executors
    from app.core.stages import StageContext

    found: dict[str, float] = {}
    for solver in ("calculix", "ansys"):
        work = tmp_path / solver
        _side_shake_with(
            work, [{"name": "받침판", "behavior": "rigid"}], free=True, aluminum_plate=True
        )
        spec = {**SPEC, "solver": solver}
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
        found[solver] = _first(work)
    assert found["calculix"] == pytest.approx(found["ansys"], rel=0.03), found


# --- 쉘(CompCore v0.8.1 「조건_강체지그_쉘브래킷」) --------------------------------

SHELL_BRACKET = FIXTURES / "doe" / "조건_강체지그_쉘브래킷"


def _shell_point(work: Path, number: int, *, solid: bool = False) -> None:
    """강체 지그블록 위 판금 브래킷(쉘) · 명판은 해석 제외. `solid` 면 브래킷을 솔리드로
    (두께 방향 2겹 — 요소 t/2) 바꿔 견줄 기준을 만든다."""
    work.mkdir(parents=True, exist_ok=True)
    points = SHELL_BRACKET / "points"
    shutil.copy(points / f"p{number:04d}.step", work / "input.step")
    shutil.copy(points / f"p{number:04d}_mid.step", work / "input_mid.step")
    payload = json.loads((points / f"p{number:04d}.json").read_text(encoding="utf-8"))
    if solid:
        for row in payload["conditions"]["body_settings"]:
            if row["name"] == "브래킷":
                row["representation"] = "solid"
                row["mesh"]["element_size"] = (
                    payload["midsurface"]["bodies"][0]["thickness"] / 2
                )
    (work / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_쉘_브래킷이_손셈과_솔리드에_맞는다(ready: None, tmp_path: Path) -> None:
    """**쉘이 제대로 들어갔나** — CompCore README 의 잣대 그대로.

    실측(2026-10-04, 전역 5 mm · 브래킷 요소 t): 끝 처짐 t2 0.3223 · t3 0.0959 mm(비 3.36 —
    손셈 3.4 ~ 3.7), 반력 66.0 · 64.5 N(= 0.05 MPa x 하중면 넓이), 솔리드(2겹) 0.3203 ·
    0.0954 mm 와 0.6% 차이. 최대 상당응력 91.1 · 39.1 MPa(겉면 — 쉘을 펼쳐 읽는다, 비 2.33 ·
    손셈 뿌리 응력 73 · 31 의 비 2.35).
    """
    spec = {"recipe": "static", "solver": "calculix", "mesh": {"element_size_mm": 5}}
    found: dict[str, dict[str, Any]] = {}
    for label, number, as_solid in (("t2", 1, False), ("t3", 2, False), ("t2_solid", 1, True)):
        work = tmp_path / label
        _shell_point(work, number, solid=as_solid)
        summary = _run(work, spec)
        result = json.loads((work / "result.json").read_text(encoding="utf-8"))
        found[label] = {**result, "summary": summary}

    t2, t3, solid = found["t2"], found["t3"], found["t2_solid"]
    assert t2["summary"]["shell_bodies"] == "브래킷 2 mm"
    assert t2["summary"]["rigid_bodies"] == "지그블록"
    assert t2["summary"]["suppressed_bodies"] == "명판"
    # 반력은 하중면 넓이 그대로 — 1% 안.
    assert t2["reactions"]["블록 바닥"][0] == pytest.approx(66.0, rel=0.01)
    assert t3["reactions"]["블록 바닥"][0] == pytest.approx(64.5, rel=0.01)
    # 질량은 쉘(넓이 x 두께)로 세도 솔리드와 같다.
    assert t2["summary"]["mass_kg"] == pytest.approx(solid["summary"]["mass_kg"], rel=0.01)
    # 처짐 — 솔리드와 2% 안, 두 두께의 비는 1/t³ 언저리.
    assert t2["max_displacement"] == pytest.approx(solid["max_displacement"], rel=0.02)
    assert 3.2 < t2["max_displacement"] / t3["max_displacement"] < 3.7
    # 응력은 **겉면**이다 — 중간면에서 읽으면 굽힘이 빠져 30 MPa 언저리로 나온다.
    assert t2["max_von_mises"] > 60
    assert 2.1 < t2["max_von_mises"] / t3["max_von_mises"] < 2.6


def test_쉘_브래킷의_고유진동수가_솔리드와_맞는다(ready: None, tmp_path: Path) -> None:
    """질량 · 강성이 함께 맞아야 맞는다. 실측: 1차 쉘 620.4 · 솔리드 622.7 Hz(0.4%)."""
    spec = {
        "recipe": "modal",
        "solver": "calculix",
        "mesh": {"element_size_mm": 5},
        "modes": 4,
    }
    first: dict[bool, float] = {}
    for solid in (False, True):
        work = tmp_path / ("solid" if solid else "shell")
        _shell_point(work, 1, solid=solid)
        _run(work, spec)
        first[solid] = _first(work)
    assert first[False] == pytest.approx(first[True], rel=0.02)
