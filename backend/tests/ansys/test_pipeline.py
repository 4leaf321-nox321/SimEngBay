"""**진짜 Ansys 로 도는 시험.** 기본으로는 안 돈다(`-m ansys`).

    ANSYS_TEST_EXECUTOR=windows-bridge \
      ANSYS_TEST_PYTHON=/mnt/c/simengbay/venv/Scripts/python.exe \
      ANSYS_TEST_WORK_DIR=/mnt/c/simengbay/pytest \
      .venv/bin/python -m pytest -m ansys

**`SIMULATION_EXECUTOR` 이 아니라 전용 이름을 쓴다.** `tests/conftest.py` 가 그 값을 `fake` 로
못 박기 때문이다(시험이 개발 `.env` 를 따라가면 안 된다) — 같은 이름을 쓰면 이 시험들이
조용히 가짜 실행기로 돌고, **가짜 결과를 진짜로 읽어** 통과하거나 엉뚱하게 실패한다(실측).

여기서 보는 것은 **로드맵의 리스크 1 · 3**이다 — CAD 플랫폼(build123d/OpenCascade)이 낸 STEP 이
임포트되고 면 순회 · 메시 · `.dat` 까지 가는가, 그리고 그 결과를 솔버와 DPF 가 받아 주는가.
형상은 `tests/fixtures/step/` 에 있고 AutoJigGenerator 와 같은 도구로 만들었다.

**실측(2026-09-20, 2025 R2 Student · Windows)**: 판 100x60x5 — 절점 836 · 1차 탄성 2583.1 Hz,
L 브래킷 — 절점 1,976 · 3315.2 Hz. 둘 다 강체 모드 6개.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.core import executors
from app.core.spec import RIGID_BODY_MODES, parse_spec
from app.core.stages import STAGES, StageContext, StageFailure

pytestmark = pytest.mark.ansys

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
STEPS = FIXTURES / "step"
TOPOLOGY = FIXTURES / "topology"
#: CompCore 가 낸 DOE 폴더 한 벌 — 형상을 **나눠 쓰는** 쪽(`shapes/`)을 일부러 고른다.
SHARED_DOE = FIXTURES / "doe" / "재료훑기-7c1d3a44"
SPEC = {
    "recipe": "modal",
    "material": {
        "name": "SS400",
        "youngs_modulus_gpa": 200,
        "poisson_ratio": 0.3,
        "density_kg_m3": 7850,
    },
    "mesh": {"element_size_mm": 10},
    "modes": 5,
}


def _executor() -> executors.Executor:
    """이 시험들만의 실행기 — **`SIMULATION_EXECUTOR` 과 다른 이름을 본다**(머리말 참고)."""
    name = os.environ.get("ANSYS_TEST_EXECUTOR", "local")
    python = os.environ.get("ANSYS_TEST_PYTHON")
    return executors.resolve(name, python=Path(python) if python else None)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """**Ansys 가 쓸 수 있는 폴더여야 한다.** windows-bridge 면 Windows 쪽 경로를 준다 —
    `\\\\wsl$` 에 쓰게 하면 느리고 잠금 문제가 난다(계획서 3.1)."""
    base = os.environ.get("ANSYS_TEST_WORK_DIR")
    if base is None:
        return tmp_path
    target = Path(base) / tmp_path.name
    target.mkdir(parents=True, exist_ok=True)
    return target


@pytest.mark.parametrize("name", ["plate.step", "bracket.step"])
def test_CAD_가_낸_STEP_이_끝까지_간다(name: str, workdir: Path) -> None:
    shutil.copy(STEPS / name, workdir / "input.step")
    spec = parse_spec(SPEC)
    (workdir / "spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")

    runner = _executor()
    summary: dict[str, Any] = {}
    for stage in STAGES:
        result = runner.run(StageContext(stage=stage, spec=SPEC, workdir=workdir))
        summary.update(result.summary)

    assert (workdir / "model.dat").is_file()
    assert (workdir / "result.json").is_file()

    result = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
    assert result["boundary"] == "free-free"
    # **강체 모드가 6개여야 한다.** 다중 바디에서 접촉이 안 잡히면 바디마다 6개가 나온다 —
    # 값은 그럴듯한데 모델이 붙어 있지 않은 상태다.
    assert result["rigid_body_modes"] == RIGID_BODY_MODES
    assert "warning" not in result
    assert len(result["modes"]) == 5 + RIGID_BODY_MODES
    assert result["units"]["frequency"] == "Hz"
    assert "MKS" in result["units"]["system"]

    elastic = [one for one in result["modes"] if not one["rigid_body"]]
    # 강체 모드는 0 근처, 첫 탄성 모드는 그것과 자릿수가 다르다.
    assert elastic[0]["frequency_hz"] > 100
    assert all(one["frequency_hz"] < 1.0 for one in result["modes"] if one["rigid_body"])
    assert int(summary["nodes"]) > 0

    # --- 모드 형상 (3단계) ---------------------------------------------------
    drawn = [one for one in elastic if one.get("vtp")]
    assert drawn, "탄성 모드에 형상 파일이 하나도 없습니다"
    for one in drawn:
        vtp = workdir / str(one["vtp"])
        assert vtp.is_file() and vtp.stat().st_size > 0
        # 썸네일은 곁들이라 없을 수 있다 — 있으면 빈 파일이면 안 된다.
        if one.get("png"):
            assert (workdir / str(one["png"])).stat().st_size > 0
        assert float(one["max_displacement"]) > 0

    # 참여계수 — 자유-자유는 강체 모드가 유효질량을 전부 가져간다.
    assert sorted(result["participation"]) == ["ROTX", "ROTY", "ROTZ", "X", "Y", "Z"]


def test_볼트_구멍을_고정하면_강체_모드가_사라진다(workdir: Path) -> None:
    """**4단계의 완료 기준.** CAD 가 보낸 영역 지문으로 볼트 구멍을 찾아 고정한다.

    자유-자유와 갈리는 것은 두 가지다 — 0 Hz 여섯 개가 없어지고, **유효질량비가 살아난다**
    (구속이 없으면 강체 모드가 전부 가져가서 탄성 모드는 0 이다).

    실측(2026-09-23, L 브래킷 120x80 · 벽 60 · 볼트 4): 1차 1,519 Hz · ROTY 유효질량 0.40.
    """
    shutil.copy(STEPS / "bracket_bolted.step", workdir / "input.step")
    shutil.copy(TOPOLOGY / "bracket_bolted.topology.json", workdir / "topology.json")
    spec = dict(SPEC)
    spec["mesh"] = {"element_size_mm": 6}
    spec["constraints"] = [{"region": "bolt_holes", "kind": "fixed"}]
    parse_spec(spec)
    (workdir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    runner = _executor()
    for stage in STAGES:
        result = runner.run(StageContext(stage=stage, spec=spec, workdir=workdir))
        if stage == "modeling":
            assert result.summary["constrained_regions"] == ["bolt_holes"]

    result = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
    assert result["boundary"] == "constrained"
    assert result["rigid_body_modes"] == 0
    assert all(one["frequency_hz"] > 1.0 for one in result["modes"])
    # 유효질량비가 실값을 갖는다 — 이것이 구속 해석의 값이다.
    assert any((one.get("effective_mass_ratio") or 0) > 0.1 for one in result["modes"])


def test_DOE_점_파일_한_장으로_구속까지_간다(workdir: Path) -> None:
    """**CompCore 2026-09-24 계약**을 진짜 Ansys 로 받아 본다.

    바뀐 것은 두 가지다 — 점마다의 정보가 `pNNNN.json` 한 장으로 합쳐졌고(영역 · 바디 · 조건),
    형상은 여러 점이 나눠 쓰면 `shapes/<지문>.step` 에 있다. 폴더 읽기만 시험하면 「합친 파일을
    Mechanical 이 받아 주는가」 는 아무도 안 본 채로 남는다 — 조건 뭉치가 늘어난 파일을
    모델링이 그대로 읽는지 여기서 본다.

    실측(2026-09-24, 2025 R2 Student · Windows): 1차 1,519 Hz · 강체 모드 0.
    """
    shutil.copy(SHARED_DOE / "shapes" / "8f3a1c92.step", workdir / "input.step")
    # **점 파일을 그대로 `topology.json` 자리에 둔다** — 가져오기가 하는 일과 같다.
    shutil.copy(SHARED_DOE / "points" / "p0001.json", workdir / "topology.json")
    spec = dict(SPEC)
    spec["mesh"] = {"element_size_mm": 6}
    spec["constraints"] = [{"region": "bolt_holes", "kind": "fixed"}]
    parse_spec(spec)
    (workdir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    runner = _executor()
    for stage in STAGES:
        result = runner.run(StageContext(stage=stage, spec=spec, workdir=workdir))
        if stage == "modeling":
            assert result.summary["constrained_regions"] == ["bolt_holes"]

    result = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
    assert result["boundary"] == "constrained"
    assert result["rigid_body_modes"] == 0
    assert all(one["frequency_hz"] > 1.0 for one in result["modes"])


def test_영역_이름이_없으면_모델링에서_즉시_실패한다(workdir: Path) -> None:
    """**조용히 자유-자유로 풀지 않는다.** 그 결과는 0 Hz 여섯 개를 달고 나오고, 사람은 그것을
    「해석이 됐다」 로 읽는다."""
    shutil.copy(STEPS / "bracket_bolted.step", workdir / "input.step")
    shutil.copy(TOPOLOGY / "bracket_bolted.topology.json", workdir / "topology.json")
    spec = dict(SPEC)
    spec["constraints"] = [{"region": "load_face", "kind": "fixed"}]
    (workdir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    runner = _executor()
    runner.run(StageContext(stage="fetching", spec=spec, workdir=workdir))
    with pytest.raises(StageFailure) as caught:
        runner.run(StageContext(stage="modeling", spec=spec, workdir=workdir))
    assert caught.value.code == "region_unresolved"
