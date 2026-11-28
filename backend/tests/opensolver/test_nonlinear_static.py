"""**② 비선형 정적**(CompCore 해석-확장-설계 8장)을 CalculiX 로 끝까지 푼다 — 소성(이선형 ·
다선형) · 하중 단계 · 시간별 배율 · 적용 단계 · 볼트 단계.

픽스처는 CompCore v0.34.0(`f603f81`, `fixtures/simengbay` 트리 `cfa6766`)의 여덟이고 판정값은
그쪽 README 「② 비선형 정적 픽스처」 · 「② 소성 픽스처」 의 손셈이다.

- 봉(SECC 10 x 10 x 100, 세 직교면의 마찰 없는 지지, 대변형 끔 — 반력 = σ·A0): 이선형 σy 250 ·
  Et 2000 에 28000 N → δz 1.62195 mm · ε_p 0.0148537. 다선형 [[0, 250], [0.05, 350.985]] 도
  같다. 당겼다 풀면 잔류 δz 1.48537 mm · 반력 0. 표 끝 넘어 당기면(강제 변위 2.13 mm) 끝 뒤가
  평평해 27019.7 N.
- 「켜고끄기」 ① 끝 δx 0.195 mm · 반력 -100 N, ② 끝 0. 「회전봉_시간표」 끝 뿌리 반력
  -981.25 N(ω 에 배율). 「단계둘」 ① 끝 볼트 1000 N · ② 끝 1066.2 N · 바닥 -600 N.
"""

from __future__ import annotations

import copy
import json
import math
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
#: 봉의 단면적(mm²) · 길이(mm).
AREA = 100.0
LENGTH = 100.0


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
    folder: str,
    workdir: Path,
    size: float,
    payload: dict[str, Any] | None = None,
    timeout: int = 1800,
) -> dict[str, Any]:
    payload = payload if payload is not None else _point(folder)
    found, broken = cases.chains(payload)
    assert not broken
    [chain] = found
    assert cases.problem(chain, payload) == ""
    shutil.copy(DOE / folder / "points" / "p0001.step", workdir / "input.step")
    (workdir / "topology.json").write_text(
        json.dumps(cases.view(payload, chain), ensure_ascii=False), "utf-8"
    )
    spec = parse_spec(
        {"recipe": "static", "solver": "calculix", "mesh": {"element_size_mm": size}}
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
            timeout_seconds=timeout,
            visual_modes=6,
        )
    result: dict[str, Any] = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
    return result


@pytest.mark.parametrize("folder", ["조건_봉_항복_이선형", "조건_봉_항복_다선형"])
def test_봉의_항복은_손셈과_같다(ready: None, tmp_path: Path, folder: str) -> None:
    result = _solve(folder, tmp_path, 2.5)
    [step] = result["steps"]
    assert step["displacement_peak"][2] == pytest.approx(1.62195, rel=0.01)
    assert step["max_equivalent_plastic_strain"] == pytest.approx(0.0148537, rel=0.02)
    assert step["reactions"]["바닥"][2] == pytest.approx(-28000, rel=1e-3)
    deck = (tmp_path / "model.inp").read_text(encoding="utf-8")
    assert "*PLASTIC" in deck and "NLGEOM" not in deck, "대변형은 끈 채 소성만"


def test_항복하지_않은_소성_재료는_소성_변형률_0_을_적는다(
    ready: None, tmp_path: Path
) -> None:
    """10 kN(100 MPa < 항복 250 MPa) — 소성이면 PE 블록이 늘 있어 0 을 적는다(Ansys 쪽
    `test_항복하지_않은_소성_재료는_소성_변형률_0_을_적는다_Ansys` 와 같은 답)."""
    payload = _point("조건_봉_항복_이선형")
    payload["conditions"]["cases"][0]["loads"][0]["magnitude"] = 10000.0
    result = _solve("조건_봉_항복_이선형", tmp_path, 2.5, payload)
    [step] = result["steps"]
    assert result["max_von_mises"] == pytest.approx(100, rel=1e-2)
    assert result["max_equivalent_plastic_strain"] == 0.0
    assert step["max_equivalent_plastic_strain"] == 0.0


def test_당겼다_풀면_소성_변형이_남는다(ready: None, tmp_path: Path) -> None:
    result = _solve("조건_봉_당겼다풀기", tmp_path, 2.5)
    pulled, released = result["steps"]
    assert (pulled["end_time"], released["end_time"]) == (1.0, 2.0)
    assert pulled["displacement_peak"][2] == pytest.approx(1.62195, rel=0.01)
    # 잔류 δz = ε_p · L, 반력 0, 등가 소성 변형률은 그대로.
    assert released["displacement_peak"][2] == pytest.approx(0.0148537 * LENGTH, rel=0.01)
    assert abs(released["reactions"]["바닥"][2]) < 1.0
    assert released["max_equivalent_plastic_strain"] == pytest.approx(
        pulled["max_equivalent_plastic_strain"], rel=1e-3
    )


def test_표_끝_뒤는_평평하다(ready: None, tmp_path: Path) -> None:
    """두 솔버 모두 완전 소성이다(2026-11-28 실측 — Ansys `TB,PLAS,…,MISO` 도 27019.7 N)."""
    result = _solve("조건_봉_표끝넘어", tmp_path, 2.5)
    [step] = result["steps"]
    assert step["reactions"]["바닥"][2] == pytest.approx(-270.197 * AREA, rel=1e-3)
    assert step["max_equivalent_plastic_strain"] == pytest.approx(0.019982, rel=1e-3)


def test_적용_단계는_켜고_끈다(ready: None, tmp_path: Path) -> None:
    result = _solve("조건_외팔보_켜고끄기", tmp_path, 2.5)
    loaded, removed = result["steps"]
    assert loaded["max_displacement"] == pytest.approx(0.195, rel=0.03)
    assert loaded["reactions"]["바닥"][0] == pytest.approx(-100, rel=1e-3)
    assert removed["max_displacement"] < 1e-9
    assert all(abs(one) < 1e-6 for one in removed["reactions"]["바닥"])


def test_회전_속도의_시간별_배율은_ω_에_곱한다(ready: None, tmp_path: Path) -> None:
    result = _solve("조건_회전봉_시간표", tmp_path, 2.5)
    [step] = result["steps"]
    # 밀도 x A x ω² x L² / 2 — ω 500 rad/s(배율 0.5). 배율을 ω² 에 곱했으면 -1962.5 N 이다.
    assert step["reactions"]["뿌리"][0] == pytest.approx(-981.25, rel=2e-3)
    assert step["displacement_peak"][0] == pytest.approx(0.003191, rel=0.02)


def test_볼트_단계는_사슬과_같은_답이다(ready: None, tmp_path: Path) -> None:
    """「단계둘」 = 「두케이스_솔버없음」(사슬)을 케이스 하나 · 단계 둘로 — 같은 답. 마찰
    접촉이라 둘째 단계가 증분마다 몇 분씩 걸린다(이 판에서 가장 긴 시험)."""
    result = _solve("조건_볼트예압_단계둘", tmp_path, 2.0, timeout=9000)
    tightened, loaded = result["steps"]
    assert tightened["bolts"]["볼트 예압"]["force_n"] == pytest.approx(1000, rel=1e-2)
    assert loaded["bolts"]["볼트 예압"]["force_n"] == pytest.approx(1066.2, rel=5e-3)
    assert loaded["reactions"]["바닥"][2] == pytest.approx(-600, rel=1e-2)


STRIP = "조건_띠_끝모멘트_대변형"
#: 띠 2 x 2 의 굽힘 강성(N·mm²) · 길이(mm).
STRIP_EI = 205000 * 2**4 / 12


def _bent(degrees: float) -> dict[str, Any]:
    """끝 회전이 그 각도가 되는 끝 모멘트(θ = ML/EI)의 띠."""
    payload = _point(STRIP)
    load = payload["conditions"]["cases"][0]["loads"][0]
    load["magnitude"] = math.radians(degrees) * STRIP_EI / LENGTH
    return payload


def _tip(workdir: Path) -> tuple[float, float]:
    """끝 면(z 100) 절점의 평균 ux · uz — 마지막 증분."""
    from app.core.calculix import frd

    lines = (workdir / "model.inp").read_text(encoding="utf-8").splitlines()
    nodes: dict[int, float] = {}
    for line in lines[2:]:
        if line.startswith("*"):
            break
        parts = line.split(",")
        nodes[int(parts[0])] = float(parts[3])
    tip = [node for node, z in nodes.items() if abs(z - LENGTH) < 1e-6]
    moved = [one for one in frd.read(workdir / "model.frd") if one.kind == "DISP"][-1]
    return (
        sum(moved.values[node][0] for node in tip) / len(tip),
        sum(moved.values[node][2] for node in tip) / len(tip),
    )


def test_큰_변형의_면_모멘트는_강체_면으로_엘라스티카대로_돈다(
    ready: None, tmp_path: Path
) -> None:
    """30° — 고정 방향 힘 짝이면 M·cos θ 로 줄어 13 % 모자랐다(2026-11-28 사용자 결정: 강체
    면). 10° · 30° · 40° 에서 0.15 % 안(실측)."""
    _solve(STRIP, tmp_path, 1.0, _bent(30))
    deck = (tmp_path / "model.inp").read_text(encoding="utf-8")
    assert "*RIGID BODY, NSET=MOMENT1" in deck
    theta = math.radians(30)
    radius = STRIP_EI / (theta * STRIP_EI / LENGTH)
    ux, uz = _tip(tmp_path)
    assert ux == pytest.approx(radius * (1 - math.cos(theta)), rel=5e-3)
    assert uz == pytest.approx(radius * math.sin(theta) - LENGTH, rel=1e-2)


def test_면이_40도_넘게_돌면_까닭을_달고_멈춘다(ready: None, tmp_path: Path) -> None:
    """「띠_끝모멘트_대변형」(90°) — ccx 2.21 의 강체 구속식은 약 42° 를 못 넘는다. 조용히
    틀리는 대신 멈추고, Ansys 를 대상 솔버로 고르라고 말한다(판정은 Ansys — CompCore
    README)."""
    with pytest.raises(StageFailure, match="40°"):
        _solve(STRIP, tmp_path, 1.0)


def _pulled_chain() -> dict[str, Any]:
    """「조건_봉_당겼다풀기」 를 사슬로 — 「당기기」(28000 N) → 「풀기」(하중 없음), ② 칸 없이.
    재료(이선형)는 공유 칸이라 두 케이스 다 소성이다."""
    payload = _point("조건_봉_당겼다풀기")
    [case] = payload["conditions"]["cases"]
    case["analysis"].pop("load_steps")
    case["loads"][0].pop("time_table")
    pull = copy.deepcopy(case)
    pull["name"] = "당기기"
    release = copy.deepcopy(case)
    release.update(name="풀기", depends_on="당기기", loads=[])
    payload["conditions"]["cases"] = [pull, release]
    return payload


def test_소성_재료의_정적_사슬은_소성_변형을_잇는다(ready: None, tmp_path: Path) -> None:
    """정적 다단은 한 덱의 `*STEP` 들이라 ε_p 가 이어진다. 소성만으로는 NLGEOM 을 켜지
    않는다 — 켰을 때 대변형을 끈 봉이 현재 단면으로 풀려 ① 끝 응력이 285 MPa · ε_p 0.0174
    였다(2026-11-28)."""
    result = _solve("조건_봉_당겼다풀기", tmp_path, 2.5, _pulled_chain())
    pulled, released = result["cases"]
    assert pulled["max_von_mises"] == pytest.approx(280, rel=1e-3)
    assert pulled["max_equivalent_plastic_strain"] == pytest.approx(0.0148537, rel=2e-3)
    assert released["displacement_peak"][2] == pytest.approx(0.0148537 * LENGTH, rel=1e-2)
    assert abs(released["reactions"]["바닥"][2]) < 1.0
    assert released["max_equivalent_plastic_strain"] == pytest.approx(
        pulled["max_equivalent_plastic_strain"], rel=1e-3
    )
    deck = (tmp_path / "model.inp").read_text(encoding="utf-8")
    assert "NLGEOM" not in deck
