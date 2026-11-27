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


def _solve(
    payload: dict[str, Any],
    folder: str,
    place: Path,
    size: float | None,
    recipe: str = "static",
    end: str | None = None,
) -> dict[str, Any]:
    """사슬(끝 케이스 `end`, 비면 하나뿐인 사슬)의 보기를 작업 폴더로 — 네 단계를 돈다.
    `size` 가 비면 CAD 의 메시 힌트 그대로다."""
    found, broken = cases.chains(payload)
    assert not broken
    if end is None:
        [chain] = found
    else:
        chain = next(one for one in found if one.name == end)
    assert cases.problem(chain) == ""
    place.mkdir()
    shutil.copy(DOE / folder / "points" / "p0001.step", place / "input.step")
    (place / "topology.json").write_text(
        json.dumps(cases.view(payload, chain), ensure_ascii=False), "utf-8"
    )
    spec: dict[str, Any] = {"recipe": recipe, "solver": "ansys", "case": chain.name}
    if size is not None:
        spec["mesh"] = {"element_size_mm": size}
    if recipe == "modal":
        spec["modes"] = 6
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


MODAL_CHAIN = "조건_볼트예압_사슬_정적모달"


def _first(result: dict[str, Any]) -> float:
    return float(result["modes"][0]["frequency_hz"])


def test_큰_변형_정적_뒤의_모달은_앞_정적의_하중을_큰_변형으로_건다_Ansys(
    workdir: Path,
) -> None:
    """「정적」(볼트 예압 + 끌어올림, 큰 변형) → 「모달」 — 설정이 기본값이 아니라 v1 으로 못
    접혀 앞 정적 하나가 단계로 온다. 전에는 끝 케이스(모달)의 하중만 걸어 선응력 없이 풀렸다.
    v1 「조건_볼트예압_선응력모달」 점 1(1차 2235.1 Hz, 2026-10-27)과 같은 대역이다."""
    payload = copy.deepcopy(_point(MODAL_CHAIN))
    payload["conditions"]["cases"][0]["analysis"]["large_deflection"] = True
    place = workdir / "bent"
    result = _solve(payload, MODAL_CHAIN, place, None, "modal", "모달")
    deck = (place / "upstream.dat").read_text(encoding="utf-8", errors="replace").lower()
    assert "nlgeom,on" in deck, "앞 정적이 큰 변형이다"
    assert "rescontrol,linear" in deck
    assert _first(result) == pytest.approx(2235.1, rel=0.03)


def test_정적_둘_뒤의_모달은_접은_선응력_모달과_같다_Ansys(workdir: Path) -> None:
    """「중력」 → 「중력 + 볼트 예압」 → 「모달」(다단 — 볼트를 뒤 케이스에서 조인다)과
    「중력 + 볼트 예압」 → 「모달」(v1 선응력으로 접힌다)은 끝 상태가 같다 — 1차가 같아야 한다.
    전에는 모달 끝의 다단에서 앞 정적의 하중 자리를 짝짓지 않아 「자리를 못 찾았다」 로
    멈췄다."""
    payload = copy.deepcopy(_point(MODAL_CHAIN))
    first, modal = payload["conditions"]["cases"]
    bolt = next(one for one in first["loads"] if one["type"] == "bolt_pretension")
    gravity = {
        "name": "중력",
        "type": "standard_earth_gravity",
        "on": "",
        "cs": "global",
        "direction": [0, 0, -1],
    }
    folded = copy.deepcopy(payload)
    folded["conditions"]["cases"][0]["loads"] = [dict(gravity), copy.deepcopy(bolt)]
    resting = {**copy.deepcopy(first), "name": "중력", "loads": [dict(gravity)]}
    first["name"], first["depends_on"] = "조임", "중력"
    first["loads"] = [dict(gravity), bolt]
    modal["depends_on"] = "조임"
    payload["conditions"]["cases"] = [resting, first, modal]
    staged = _solve(payload, MODAL_CHAIN, workdir / "staged", None, "modal", "모달")
    once = _solve(folded, MODAL_CHAIN, workdir / "folded", None, "modal", "모달")
    assert _first(staged) == pytest.approx(_first(once), rel=0.02)
