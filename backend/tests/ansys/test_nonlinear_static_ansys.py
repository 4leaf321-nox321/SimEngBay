"""**② 비선형 정적**(CompCore 해석-확장-설계 8장)을 **Ansys 로** 푼다 — CalculiX 쪽
(`tests/opensolver/test_nonlinear_static.py`)과 같은 픽스처 · 같은 판정이다.

- 소성은 바디의 명령 조각에 `TB,BISO`(이선형) · `TB,PLAS,…,MISO`(다선형)로 건다
  (`mechanical.build.plastic_commands`). Mechanical 은 그 `TB` 를 모르므로 부단계를 우리가
  건다.
- 하중 단계는 단계마다 끝 시각 · 부단계, 시간별 배율 · 적용 단계는 크기의 Tabular Data(시각
  → 크기 x 배율), 볼트는 첫 단계 Load 뒤 Lock(`_apply_history`).
- 「띠_끝모멘트_대변형」 — Mechanical 의 면 모멘트는 큰 변형에서도 엘라스티카대로 돈다(끝 ux
  +63.662 · uz -36.338).
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
AREA = 100.0
LENGTH = 100.0


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


def _solve(folder: str, place: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if payload is not None else _point(folder)
    found, broken = cases.chains(payload)
    assert not broken
    [chain] = found
    assert cases.problem(chain, payload) == ""
    shutil.copy(DOE / folder / "points" / "p0001.step", place / "input.step")
    (place / "topology.json").write_text(
        json.dumps(cases.view(payload, chain), ensure_ascii=False), "utf-8"
    )
    spec: dict[str, Any] = {"recipe": "static", "solver": "ansys", "case": chain.name}
    parse_spec(spec)
    (place / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    runner = _executor()
    for stage in STAGES:
        runner.run(StageContext(stage=stage, spec=spec, workdir=place))
    result: dict[str, Any] = json.loads((place / "result.json").read_text(encoding="utf-8"))
    return result


@pytest.mark.parametrize("folder", ["조건_봉_항복_이선형", "조건_봉_항복_다선형"])
def test_봉의_항복은_손셈과_같다_Ansys(workdir: Path, folder: str) -> None:
    result = _solve(folder, workdir)
    [step] = result["steps"]
    assert step["displacement_peak"][2] == pytest.approx(1.62195, rel=0.01)
    assert step["max_equivalent_plastic_strain"] == pytest.approx(0.0148537, rel=0.02)
    assert step["reactions"]["바닥"][2] == pytest.approx(-28000, rel=1e-3)
    deck = (workdir / "model.dat").read_text(encoding="utf-8", errors="replace").lower()
    assert "tb,biso" in deck or "tb,plas" in deck


def test_당겼다_풀면_소성_변형이_남는다_Ansys(workdir: Path) -> None:
    result = _solve("조건_봉_당겼다풀기", workdir)
    pulled, released = result["steps"]
    assert pulled["displacement_peak"][2] == pytest.approx(1.62195, rel=0.01)
    assert released["displacement_peak"][2] == pytest.approx(0.0148537 * LENGTH, rel=0.01)
    assert abs(released["reactions"]["바닥"][2]) < 1.0


def test_표_끝_뒤는_평평하다_Ansys(workdir: Path) -> None:
    """`TB,PLAS,…,MISO` 의 마지막 점 뒤는 완전 소성이다(2026-11-28 실측 — CalculiX 도 같다)."""
    result = _solve("조건_봉_표끝넘어", workdir)
    [step] = result["steps"]
    assert step["reactions"]["바닥"][2] == pytest.approx(-270.197 * AREA, rel=1e-3)
    assert step["max_equivalent_plastic_strain"] == pytest.approx(0.019982, rel=1e-3)


def test_적용_단계는_켜고_끈다_Ansys(workdir: Path) -> None:
    result = _solve("조건_외팔보_켜고끄기", workdir)
    loaded, removed = result["steps"]
    assert loaded["max_displacement"] == pytest.approx(0.195, rel=0.05)
    assert loaded["reactions"]["바닥"][0] == pytest.approx(-100, rel=1e-2)
    assert removed["max_displacement"] < 1e-6


def test_회전_속도의_시간별_배율은_ω_에_곱한다_Ansys(workdir: Path) -> None:
    result = _solve("조건_회전봉_시간표", workdir)
    [step] = result["steps"]
    assert step["reactions"]["뿌리"][0] == pytest.approx(-981.25, rel=5e-3)


def test_끝_모멘트는_큰_변형에서도_엘라스티카대로_돈다_Ansys(workdir: Path) -> None:
    result = _solve("조건_띠_끝모멘트_대변형", workdir)
    [step] = result["steps"]
    # 성분마다 절댓값의 최대 — 끝 면(2 mm 폭)이 90° 돌아 면의 절점이 중심선에서 ±1 mm 갈린다.
    ux, _uy, uz = step["displacement_peak"]
    assert ux == pytest.approx(63.662, abs=1.2)
    assert uz == pytest.approx(-36.338, abs=1.2)


def test_볼트_단계는_사슬과_같은_답이다_Ansys(workdir: Path) -> None:
    result = _solve("조건_볼트예압_단계둘", workdir)
    tightened, loaded = result["steps"]
    assert tightened["bolts"]["볼트 예압"]["force_n"] == pytest.approx(1000, rel=1e-2)
    assert loaded["bolts"]["볼트 예압"]["force_n"] == pytest.approx(1066.2, rel=5e-3)
    assert loaded["reactions"]["바닥"][2] == pytest.approx(-600, rel=1e-2)


def test_소성_재료의_정적_사슬은_소성_변형을_잇는다_Ansys(workdir: Path) -> None:
    """「당기기」(28000 N) → 「풀기」 — 한 정적 해석의 단계들이라 ε_p 가 이어진다(2026-11-28
    실측: ① 280.0 MPa, ② 잔류 · 반력 0, 끝 ε_p 0.0148537)."""
    payload = _point("조건_봉_당겼다풀기")
    [case] = payload["conditions"]["cases"]
    case["analysis"].pop("load_steps")
    case["loads"][0].pop("time_table")
    pull = copy.deepcopy(case)
    pull["name"] = "당기기"
    release = copy.deepcopy(case)
    release.update(name="풀기", depends_on="당기기", loads=[])
    payload["conditions"]["cases"] = [pull, release]
    result = _solve("조건_봉_당겼다풀기", workdir, payload)
    pulled, released = result["cases"]
    assert pulled["max_von_mises"] == pytest.approx(280, rel=1e-3)
    assert released["displacement_peak"][2] == pytest.approx(0.0148537 * LENGTH, rel=1e-2)
    assert abs(released["reactions"]["바닥"][2]) < 1.0
    assert released["max_equivalent_plastic_strain"] == pytest.approx(0.0148537, rel=2e-3)
