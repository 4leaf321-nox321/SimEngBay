"""해석 케이스(판 2)를 **Ansys 로** 푼다 — 사슬의 보기(`app/core/cases.py`)를 작업 폴더에 담고
Mechanical 정적 단계로 푼다(`mechanical.build._apply_staged` · `dpf.static._cases`).

- 정적 다단: 하중은 자기 케이스의 단계에서만 켠다(이어지지 않는다). 볼트는 조이는 단계 앞에서
  Open, 그 단계에서 예압, 뒤로 Lock. 결과는 케이스마다(`result.json` 의 `cases`).
- v1 으로 접히는 사슬(「두케이스_솔버없음」)은 v1 볼트 정적과 같은 답 — 설계안 6 의 기준
  (예압 끝 1000 N · 외력 끝 볼트 1066.2 N · 바닥 -600 N, v1 실측 2026-10-27).
"""

from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.core import cases, executors
from app.core.spec import parse_spec
from app.core.stages import STAGES, StageContext

pytestmark = pytest.mark.ansys

DOE = Path(__file__).resolve().parents[1] / "fixtures" / "doe"
BEAM = "조건_외팔보_두케이스"
BOLTED = "조건_볼트예압_두케이스_솔버없음"


def _executor() -> executors.Executor:
    name = os.environ.get("ANSYS_TEST_EXECUTOR", "local")
    python = os.environ.get("ANSYS_TEST_PYTHON")
    return executors.resolve(name, python=Path(python) if python else None)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """Ansys 가 쓸 수 있는 폴더 — 매번 비운다(`test_pipeline.workdir` 과 같은 까닭)."""
    base = os.environ.get("ANSYS_TEST_WORK_DIR")
    if base is None:
        return tmp_path
    target = Path(base) / tmp_path.name
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _point(folder: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (DOE / folder / "points" / "p0001.json").read_text(encoding="utf-8")
    )
    return loaded


def _solve(payload: dict[str, Any], folder: str, place: Path, size: float) -> dict[str, Any]:
    found, broken = cases.chains(payload)
    assert not broken
    [chain] = found
    assert cases.problem(chain) == ""
    place.mkdir()
    shutil.copy(DOE / folder / "points" / "p0001.step", place / "input.step")
    (place / "topology.json").write_text(
        json.dumps(cases.view(payload, chain), ensure_ascii=False), "utf-8"
    )
    spec: dict[str, Any] = {
        "recipe": "static",
        "solver": "ansys",
        "case": chain.name,
        "mesh": {"element_size_mm": size},
    }
    parse_spec(spec)
    (place / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    runner = _executor()
    for stage in STAGES:
        runner.run(StageContext(stage=stage, spec=spec, workdir=place))
    result: dict[str, Any] = json.loads((place / "result.json").read_text(encoding="utf-8"))
    return result


def test_외팔보_두_케이스는_하중이_이어지지_않는다_Ansys(workdir: Path) -> None:
    """「힘 A」 100 N +X → 「힘 B」 50 N +Y — B 끝은 B 만 건 답(손셈 δy 0.0976 · 30 MPa)."""
    result = _solve(_point(BEAM), BEAM, workdir / "beam", 2.5)
    first, second = result["cases"]
    assert (first["name"], second["name"]) == ("힘 A", "힘 B")
    assert first["max_displacement"] == pytest.approx(0.195, rel=0.05)
    assert first["reactions"]["바닥"][0] == pytest.approx(-100, rel=1e-2)
    assert second["max_displacement"] == pytest.approx(0.098, rel=0.05)
    assert second["max_von_mises"] == pytest.approx(30, rel=0.1)
    fx, fy, _ = second["reactions"]["바닥"]
    assert fy == pytest.approx(-50, rel=1e-2) and abs(fx) < 1e-3


def test_뒤_케이스에서_조이는_볼트는_그_케이스에서_조인다_Ansys(workdir: Path) -> None:
    """「중력」 → 「중력 + 볼트 예압」 — 앞 케이스에서 볼트는 Open, 뒤 케이스에서 조인다.
    중력은
    Mechanical 이 단계마다 못 끄므로 하나만 건다(정적끼리 같다)."""
    payload = copy.deepcopy(_point(BOLTED))
    first, second = payload["conditions"]["cases"]
    bolt = next(one for one in first["loads"] if one["type"] == "bolt_pretension")
    gravity = {
        "name": "중력",
        "type": "standard_earth_gravity",
        "on": "",
        "cs": "global",
        "direction": [0, 0, -1],
    }
    first["loads"] = [dict(gravity)]
    second["loads"] = [dict(gravity), bolt]
    result = _solve(payload, BOLTED, workdir / "later", 2.0)
    resting, tightened = result["cases"]
    assert tightened["bolts"]["볼트 예압"]["force_n"] == pytest.approx(1000, rel=1e-2)
    assert abs(resting["bolts"]["볼트 예압"]["force_n"] or 0.0) < 1.0
    weight = 0.126257 * 9.80665
    for case in result["cases"]:
        assert case["reactions"]["바닥"][2] == pytest.approx(weight, rel=0.03), case["name"]


def test_예압_뒤_외력은_v1_볼트_정적과_같다_Ansys(workdir: Path) -> None:
    """설계안 6 의 기준 — 대상 솔버를 비운 「두케이스」(Ansys 로도 푼다). v1 으로 접혀 v1 볼트
    정적과 같은 덱이다."""
    result = _solve(_point(BOLTED), BOLTED, workdir / "folded", 2.0)
    bolt = result["bolts"]["볼트 예압"]
    assert bolt["tightened_n"] == pytest.approx(1000.0)
    assert bolt["force_n"] == pytest.approx(1066.2, rel=5e-3)
    assert result["reactions"]["바닥"][2] == pytest.approx(-600.0, rel=1e-2)
