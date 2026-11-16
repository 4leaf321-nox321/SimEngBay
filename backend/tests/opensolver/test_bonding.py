"""**본딩을 `*TIE` 로** — 바디를 따로 메시하고 묶는다(`calculix/bonding.py`, 2026-11-16).

운영에서 막힌 넷: ① CAD 의 본딩 접촉 쌍이 쓰이지 않았다(맞닿은 면은 전부 붙었다) ② 형상이
정확히
맞닿아야 했다(미세 간극이면 바디가 떨어졌다) ③ 접합면 양쪽 메시가 묶여 파트별 메시를 따로 못
정했다 ④ 정식 본딩(MPC)은 Ansys 에만 있었다. 「조건_측면가진」(강판 위 알루미늄 기둥, 바닥 고정
·
본딩 「기둥-판」)으로 본다 — 기둥을 띄운 형상은 gmsh 로 만든다.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.core.calculix import tools
from app.core.calculix.mesh import read_mesh
from app.core.stages import StageFailure
from tests.opensolver.test_calculix import SIDE_SHAKE, SPEC, _run

pytestmark = pytest.mark.opensolver


@pytest.fixture
def ready() -> None:
    for find in (tools.gmsh_bin, tools.ccx_bin):
        try:
            find()
        except StageFailure as failure:
            pytest.skip(str(failure))


def _lifted(
    work: Path, gap: float, *, contact: dict[str, Any] | None = None, **extra: Any
) -> None:
    """기둥을 `gap` mm 띄운 측면가진 — 형상과 점 파일의 기둥 쪽 지문을 함께 옮긴다.
    `contact` 를 주면 「기둥-판」 에 덧씌우고, `None` 이면 그대로, `extra` 는 점 파일 위에
    얹는다."""
    work.mkdir(parents=True)
    geo = work / "lifted.geo"
    # 판 윗면에 기둥 자리를 새긴다 — CompCore 의 STEP 이 그렇다(「접합 판쪽」 은 넓이 100 의
    # 면).
    geo.write_text(
        'SetFactory("OpenCASCADE");\n'
        "Box(1) = {-40, -40, 0, 80, 80, 10};\n"
        "Rectangle(10) = {-5, -5, 10, 10, 10};\n"
        "BooleanFragments{ Volume{1}; Delete; }{ Surface{10}; Delete; }\n"
        f"Box(2) = {{-5, -5, {10 + gap}, 10, 10, 80}};\n",
        encoding="utf-8",
    )
    tools.run(
        tools.gmsh_bin(),
        [str(geo), "-0", "-o", str(work / "input.step"), "-v", "1"],
        cwd=work,
        timeout_seconds=120,
        what="gmsh",
    )
    payload = json.loads((SIDE_SHAKE / "points" / "p0001.json").read_text(encoding="utf-8"))
    for rows in payload["regions"].values():
        for one in rows:
            if isinstance(one, dict) and one.get("body") == "기둥" and "centroid" in one:
                one["centroid"][2] += gap
    for body in payload["bodies"]:
        if body["name"] == "기둥":
            body["centroid"][2] += gap
            body["bbox"][0][2] += gap
            body["bbox"][1][2] += gap
    if contact is not None:
        payload["conditions"]["contacts"] = [
            {**payload["conditions"]["contacts"][0], **contact}
        ]
    payload.update(extra)
    (work / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _floating(work: Path) -> bool:
    """기둥이 떴나 — 바닥을 고정한 모델이라 강체 모드 칸은 0 이고, 0 Hz 모드가 나온다."""
    return float(_result(work)["modes"][0]["frequency_hz"]) < 1.0


def _result(work: Path) -> dict[str, Any]:
    found: dict[str, Any] = json.loads((work / "result.json").read_text(encoding="utf-8"))
    return found


def test_선언한_본딩은_pinball_안의_간극만_묶는다(ready: None, tmp_path: Path) -> None:
    """기둥이 0.3 mm 떠 있다. pinball 0.5 mm 면 묶여 맞닿은 모델과 같은 1차가 나오고, 0.1 mm 면
    안 묶여 기둥이 떠서 0 Hz 모드가 나온다. pinball 이 없으면 요소 크기의 절반(2.5 mm)이라
    묶인다. 「Adjust to Touch」 는 종 절점을 주 면에 붙인다(`ADJUST=YES`)."""
    touching = tmp_path / "touching"
    _lifted(touching, 0.0)
    _run(touching, SPEC)
    base = next(one for one in _result(touching)["modes"] if not one["rigid_body"])

    for pinball, tied in ((0.5, True), (0.1, False), (None, True)):
        work = tmp_path / f"pinball-{pinball}"
        _lifted(work, 0.3, contact={"pinball": pinball})
        summary = _run(work, SPEC)
        result = _result(work)
        if tied:
            assert not _floating(work), pinball
            first = next(one for one in result["modes"] if not one["rigid_body"])
            assert first["frequency_hz"] == pytest.approx(base["frequency_hz"], rel=0.01)
        else:
            assert _floating(work), pinball
        assert "tie:기둥-판" in summary["constrained_regions"]

    adjusted = tmp_path / "adjusted"
    _lifted(adjusted, 0.3, contact={"interface_treatment": "adjust_to_touch"})
    _run(adjusted, SPEC)
    assert "ADJUST=YES" in (adjusted / "model.inp").read_text(encoding="utf-8")


def test_선언이_없으면_미세_간극은_묶고_CompCore_가_알린_틈새는_남긴다(
    ready: None, tmp_path: Path
) -> None:
    """접촉을 선언하지 않은 조립은 맞닿은 바디를 찾아 묶는다(Mechanical 의 자동 접촉) —
    0.005 mm 뜬 기둥도 묶인다. CompCore 가 그 두 바디 사이의 틈으로 알렸으면
    (`quality.contacts`) 설계한 틈새라 묶지 않는다."""
    loose = tmp_path / "loose"
    _lifted(loose, 0.005)
    payload = json.loads((loose / "topology.json").read_text(encoding="utf-8"))
    payload["conditions"]["contacts"] = []
    (loose / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    summary = _run(loose, SPEC)
    assert any(one.startswith("tie:auto:") for one in summary["constrained_regions"])
    assert not _floating(loose)

    designed = tmp_path / "designed"
    shutil.copytree(loose, designed, ignore=shutil.ignore_patterns("*.msh", "*.frd", "*.dat"))
    payload["quality"]["contacts"] = [
        {"kind": "gap", "a": "받침판", "b": "기둥", "size": 0.005, "at": [0, 0, 10]}
    ]
    (designed / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    summary = _run(designed, SPEC)
    assert not any(one.startswith("tie:auto:") for one in summary["constrained_regions"])
    assert _floating(designed)


def _plate_elements(work: Path) -> int:
    mesh = read_mesh(work / "model.msh")
    plate = max(mesh.bodies, key=lambda one: one.volume).index
    return len(mesh.solids[plate])


def test_파트_메시는_이웃_바디로_번지지_않는다(
    ready: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기둥만 1.5 mm 로 줄인다. `*TIE` 로 묶으면 받침판 메시가 그대로다 — 절점을 공유하던 옛
    방식(`CALCULIX_BONDING=shared`)은 접합부가 기둥을 따라 촘촘해져 받침판 요소가 는다."""
    counts: dict[str, tuple[int, int]] = {}
    for mode in ("tie", "shared"):
        monkeypatch.setenv("CALCULIX_BONDING", mode)
        sizes = []
        for fine in (False, True):
            work = tmp_path / f"{mode}-{fine}"
            _lifted(work, 0.0)
            if fine:
                payload = json.loads((work / "topology.json").read_text(encoding="utf-8"))
                payload["conditions"]["body_settings"] = [
                    {"name": "기둥", "mesh": {"element_size": 1.5}}
                ]
                (work / "topology.json").write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                )
            _run(work, SPEC)
            sizes.append(_plate_elements(work))
        counts[mode] = (sizes[0], sizes[1])
    tie, shared = counts["tie"], counts["shared"]
    assert tie[1] == pytest.approx(tie[0], rel=0.1), counts
    assert shared[1] > 1.3 * shared[0], counts


def _with_settings(work: Path, settings: list[dict[str, Any]]) -> None:
    payload = json.loads((work / "topology.json").read_text(encoding="utf-8"))
    payload["conditions"]["body_settings"] = settings
    (work / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _first_hz(work: Path) -> float:
    return float(
        next(one for one in _result(work)["modes"] if not one["rigid_body"])["frequency_hz"]
    )


def test_바디마다_요소_차수를_달리한다(ready: None, tmp_path: Path) -> None:
    """2차로 메시하고 1차 바디의 중간 절점을 뺀다(`mesh.demote`) — 바디를 따로 메시해 `*TIE` 로
    묶으므로 접합부의 중간 절점을 따로 묶지 않아도 된다. 1차 사면체는 굽힘에 단단해 기둥을
    1차로
    내리면 1차 굽힘이 오른다. 전체를 1차로 두고 판만 2차로 올리는 것도 된다."""
    base = tmp_path / "base"
    _lifted(base, 0.0)
    plain = _run(base, SPEC)

    mixed = tmp_path / "mixed"
    _lifted(mixed, 0.0)
    _with_settings(mixed, [{"name": "기둥", "mesh": {"order": "linear"}}])
    summary = _run(mixed, SPEC)
    deck = (mixed / "model.inp").read_text(encoding="utf-8")
    assert "TYPE=C3D4" in deck and "TYPE=C3D10" in deck
    assert summary["mesh_order"] == "mixed"
    assert "기둥 1차" in summary["mesh_order_by_body"]
    assert "받침판 2차" in summary["mesh_order_by_body"]
    assert "conditions_skipped" not in summary or "차수" not in summary["conditions_skipped"]
    assert int(summary["nodes"]) < int(plain["nodes"])
    assert 1.0 < _first_hz(mixed) / _first_hz(base) < 1.3

    raised = tmp_path / "raised"
    _lifted(raised, 0.0)
    _with_settings(raised, [{"name": "받침판", "mesh": {"order": "quadratic"}}])
    summary = _run(raised, {**SPEC, "mesh": {**SPEC["mesh"], "order": "linear"}})
    assert summary["mesh_order"] == "mixed"
    assert (
        "받침판 2차" in summary["mesh_order_by_body"]
        and "기둥 1차" in summary["mesh_order_by_body"]
    )
