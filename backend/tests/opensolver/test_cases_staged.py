"""**정적 다단**(판 2 — v1 으로 못 접는 사슬)을 CalculiX 로 끝까지 푼다(`deck._staged_steps`).

뒤 케이스는 앞 케이스의 끝 상태에서 시작하고 **하중은 이어지지 않는다** — 케이스의 첫 단계가
`*CLOAD, OP=NEW` · `*DLOAD, OP=NEW` 로 앞 하중을 거두고 그 케이스의 하중을 중력까지 다시 건다.
조인 볼트는 잠긴 채 이어진다. 결과는 케이스마다 끝 상태(`result.json` 의 `cases`).

「조건_외팔보_두케이스」(CompCore 2026-11-27): SECC 기둥 10 x 10 x 100, 바닥 고정, 끝 면에 「힘
A」
100 N +X → 「힘 B」 50 N +Y. I = 833.3 mm⁴ — A 끝 δx = F·L³/(3EI) = 0.195 mm · 바닥 굽힘 60
MPa,
B 끝 δy = 0.0976 mm · 30 MPa(전단 처짐을 더하면 약 0.098). B 끝에 X 처짐이 남으면 A 를 안 거둔
것이다.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.core import cases
from app.core.calculix import tools
from app.core.run import run_stage
from app.core.spec import parse_spec
from app.core.stages import STAGES, StageFailure

pytestmark = pytest.mark.opensolver

DOE = Path(__file__).resolve().parents[1] / "fixtures" / "doe"
BEAM = "조건_외팔보_두케이스"
BOLTED = "조건_볼트예압_두케이스_솔버없음"
#: SECC 기둥의 무게(N) — 10 x 10 x 100 mm³ x 7,850 kg/m³ x 9.80665.
WEIGHT = 1e-5 * 7850 * 9.80665


@pytest.fixture
def ready() -> None:
    for find in (tools.gmsh_bin, tools.ccx_bin):
        try:
            find()
        except StageFailure as failure:
            pytest.skip(str(failure))


def _point(folder: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (DOE / folder / "points" / "p0001.json").read_text(encoding="utf-8")
    )
    return loaded


def _solve(
    payload: dict[str, Any], folder: str, workdir: Path, recipe: str, size: float, **more: Any
) -> dict[str, Any]:
    """사슬(끝 케이스 하나)의 보기를 작업 폴더로 — 네 단계를 돌리고 `result.json`."""
    found, broken = cases.chains(payload)
    assert not broken
    [chain] = found
    assert cases.problem(chain) == ""
    shutil.copy(DOE / folder / "points" / "p0001.step", workdir / "input.step")
    (workdir / "topology.json").write_text(
        json.dumps(cases.view(payload, chain), ensure_ascii=False), "utf-8"
    )
    spec = parse_spec(
        {"recipe": recipe, "solver": "calculix", "mesh": {"element_size_mm": size}, **more}
    )
    for stage in STAGES:
        run_stage(
            stage,
            spec,
            workdir,
            input_name="input.step",
            version=252,
            ansys_root=None,
            solver_processes=2,
            timeout_seconds=1800,
            visual_modes=6,
        )
    result: dict[str, Any] = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
    return result


def test_외팔보_두_케이스는_하중이_이어지지_않는다(ready: None, tmp_path: Path) -> None:
    result = _solve(_point(BEAM), BEAM, tmp_path, "static", 2.5)
    first, second = result["cases"]
    assert (first["name"], second["name"]) == ("힘 A", "힘 B")
    # 「힘 A」 끝 — 손셈 0.195 mm · 60 MPa, 바닥이 X 로 100 N 을 버틴다.
    assert first["max_displacement"] == pytest.approx(0.195, rel=0.03)
    assert first["max_von_mises"] == pytest.approx(60, rel=0.05)
    assert first["reactions"]["바닥"][0] == pytest.approx(-100, rel=1e-3)
    # 「힘 B」 끝 — B 만 건 답이다(A 를 거뒀다): 0.0976 mm(전단 처짐 더해 약 0.098) · 30 MPa,
    # X 반력이 0 이고 처짐이 둘의 합(0.218)이 아니다.
    assert second["max_displacement"] == pytest.approx(0.098, rel=0.03)
    assert second["max_von_mises"] == pytest.approx(30, rel=0.05)
    fx, fy, _ = second["reactions"]["바닥"]
    assert fy == pytest.approx(-50, rel=1e-3) and abs(fx) < 1e-6
    # 맨 위의 값은 끝 케이스의 것이다.
    assert result["max_displacement"] == second["max_displacement"]
    deck = (tmp_path / "model.inp").read_text(encoding="utf-8")
    second_step = deck.split("*END STEP")[1]
    assert "*CLOAD, OP=NEW" in second_step and "*DLOAD, OP=NEW" in second_step


def test_중력이_든_정적_다단은_케이스마다_중력을_다시_건다(
    ready: None, tmp_path: Path
) -> None:
    """`*DLOAD, OP=NEW` 가 중력(GRAV)까지 거두므로 케이스마다 다시 써야 한다 — 두 케이스 모두
    바닥이 기둥의 무게를 받친다."""
    payload = copy.deepcopy(_point(BEAM))
    gravity = {
        "name": "중력",
        "type": "standard_earth_gravity",
        "on": "",
        "cs": "global",
        "direction": [0, 0, -1],
    }
    for row in payload["conditions"]["cases"]:
        row["loads"].append(dict(gravity))
    result = _solve(payload, BEAM, tmp_path, "static", 2.5)
    deck = (tmp_path / "model.inp").read_text(encoding="utf-8")
    steps = deck.split("*END STEP")[:2]
    assert all("GRAV" in step for step in steps), "케이스마다 중력"
    for case in result["cases"]:
        assert case["reactions"]["바닥"][2] == pytest.approx(WEIGHT, rel=0.02), case["name"]


#: 체결 모델(아래판 · 위판 · 볼트)의 무게(N) — 「조건_볼트예압_정적」 모델링 요약의 질량
#: 0.126257 kg.
ASSEMBLY = 0.126257 * 9.80665
GRAVITY = {
    "name": "중력",
    "type": "standard_earth_gravity",
    "on": "",
    "cs": "global",
    "direction": [0, 0, -1],
}


def _later_bolt() -> dict[str, Any]:
    """「예압」 에는 중력만, 「외력」 에 중력 + 볼트 예압 — **뒤 케이스에서 조이는 볼트**(v1 은
    모든 볼트를 ① 에서 조여 못 접는다). 앞 케이스에서 볼트는 아직 축으로 힘을 안 나르지만 판은
    제 무게로 얹혀 있어 기구가 아니다(끌어올림을 앞에 두면 위판을 잡을 것이 없어 풀리지
    않는다)."""
    payload = copy.deepcopy(_point(BOLTED))
    first, second = payload["conditions"]["cases"]
    bolt = next(one for one in first["loads"] if one["type"] == "bolt_pretension")
    first["loads"] = [dict(GRAVITY)]
    second["loads"] = [dict(GRAVITY), bolt]
    return payload


def test_뒤_케이스에서_조이는_볼트는_그_케이스에서_조인다(ready: None, tmp_path: Path) -> None:
    result = _solve(_later_bolt(), BOLTED, tmp_path, "static", 2.0)
    resting, tightened = result["cases"]
    assert tightened["bolts"]["볼트 예압"]["tightened_n"] == pytest.approx(1000, rel=1e-3)
    assert tightened["bolts"]["볼트 예압"]["force_n"] == pytest.approx(1000, rel=1e-2)
    # 앞 케이스에는 볼트를 조이지 않았다 — 단면이 축으로 힘을 안 나른다. 바닥은 무게를 받친다.
    assert abs(resting["bolts"]["볼트 예압"]["force_n"]) < 1.0
    for case in result["cases"]:
        assert case["reactions"]["바닥"][2] == pytest.approx(ASSEMBLY, rel=0.02), case["name"]


def test_정적_다단_뒤의_모달도_풀린다(ready: None, tmp_path: Path) -> None:
    """「중력」 → 「중력 + 볼트 예압」 → 「모달」 — 정적 둘을 차례로 풀고 그 끝 상태로 모드를
    뽑는다.
    조인 체결이라 v1 「조건_볼트예압_선응력모달」(1차 2235 Hz, Ansys)과 같은 대역이다."""
    payload = _later_bolt()
    second = payload["conditions"]["cases"][1]
    payload["conditions"]["cases"].append(
        {
            "name": "모달",
            "depends_on": second["name"],
            "target": {"solver": ""},
            "analysis": {"type": "modal", "modes": 6},
            "constraints": copy.deepcopy(second["constraints"]),
            "loads": [],
            "initial": [],
        }
    )
    result = _solve(payload, BOLTED, tmp_path, "modal", 2.0, modes=6)
    frequencies = [one["frequency_hz"] for one in result["modes"]]
    assert len(frequencies) >= 6 and all(one > 0 for one in frequencies)
    deck = (tmp_path / "model.inp").read_text(encoding="utf-8")
    assert deck.count("*STEP, NLGEOM") >= 3 and "*STEP, PERTURBATION" in deck
