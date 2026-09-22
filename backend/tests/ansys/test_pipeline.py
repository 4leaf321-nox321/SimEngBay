"""**진짜 Ansys 로 도는 시험.** 기본으로는 안 돈다(`-m ansys`).

    SIMENGBAY_ANSYS=1 SIMULATION_EXECUTOR=windows-bridge \
      WINDOWS_PYTHON=/mnt/c/simengbay/venv/Scripts/python.exe \
      .venv/bin/python -m pytest -m ansys

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
from app.core.stages import STAGES, StageContext

pytestmark = pytest.mark.ansys

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "step"
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
    """`.env` 가 아니라 **환경변수로** 고른다 — 시험이 개발 설정을 건드리지 않는다."""
    name = os.environ.get("SIMULATION_EXECUTOR", "local")
    python = os.environ.get("WINDOWS_PYTHON")
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
    shutil.copy(FIXTURES / name, workdir / "input.step")
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
