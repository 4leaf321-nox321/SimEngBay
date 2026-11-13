"""**메시 보정** — 겹침 · 틈(형상 맞춤 허용오차), 작은 곡면(곡률 크기), 뒤집힌 2차 요소.

운영에서 보고된 넷을 gmsh 4.12 · ccx 2.21 로 재현한 형상이다(2026-11-13). 형상은 여기서
gmsh 로 만든다 — 판 100 x 100 x 20 위 블록 20 x 20 x 20, R60 원통에 R4 구멍 셋.
"""

from __future__ import annotations

import itertools
import math
import sys
from pathlib import Path

import pytest

from app.core.calculix import mesh as mesh_module
from app.core.calculix import tools
from app.core.calculix.mesh import Mesh, build_mesh, probe_volumes
from app.core.stages import StageFailure

pytestmark = pytest.mark.opensolver

# 패키지가 `build` 라는 이름의 함수를 내보내 모듈 이름을 가린다 — 모듈을 직접 꺼낸다.
__import__("app.core.calculix.build")
build_module = sys.modules["app.core.calculix.build"]

#: 판 100 x 100 x 20 + 블록이면 모델 대각선 x 1e-4 가 이만큼이다(`_boolean_tolerance`).
TOLERANCE = 0.0147


@pytest.fixture
def ready() -> None:
    for find in (tools.gmsh_bin, tools.ccx_bin):
        try:
            find()
        except StageFailure as failure:
            pytest.skip(str(failure))


def _step(work: Path, name: str, body: str) -> Path:
    """gmsh 로 STEP 을 만든다 — `.geo` 의 OCC 형상을 그대로 내보낸다."""
    geo = work / f"{name}.geo"
    geo.write_text('SetFactory("OpenCASCADE");\n' + body, encoding="utf-8")
    step = work / f"{name}.step"
    tools.run(
        tools.gmsh_bin(),
        [str(geo), "-0", "-o", str(step), "-v", "1"],
        cwd=work,
        timeout_seconds=120,
        what="gmsh",
    )
    return step


def _blocks(work: Path, lift: float) -> Path:
    """판 위 블록 — `lift` 가 음이면 겹치고 양이면 뜬다."""
    return _step(
        work,
        f"blocks{lift:+g}",
        "Box(1) = {0, 0, 0, 100, 100, 20};\n"
        f"Box(2) = {{40, 40, {20 + lift}, 20, 20, 20}};\n",
    )


def _cylinder(work: Path) -> Path:
    return _step(
        work,
        "cylinder",
        "Cylinder(1) = {0, 0, 0, 0, 0, 40, 60};\n"
        "Cylinder(2) = {30, 0, -1, 0, 0, 42, 4};\n"
        "Cylinder(3) = {-15, 26, -1, 0, 0, 42, 4};\n"
        "Cylinder(4) = {-15, -26, -1, 0, 0, 42, 4};\n"
        "BooleanDifference{ Volume{1}; Delete; }{ Volume{2, 3, 4}; Delete; }\n",
    )


def _shared(mesh: Mesh) -> int:
    first, second = (
        {node for _, ids in rows for node in ids[:4]} for rows in mesh.solids.values()
    )
    return len(first & second)


def _mean_edge(mesh: Mesh, solid: int) -> float:
    lengths = [
        math.dist(mesh.nodes[a], mesh.nodes[b])
        for _, ids in mesh.solids[solid]
        for a, b in itertools.combinations(ids[:4], 2)
    ]
    return sum(lengths) / len(lengths)


def test_허용오차_안의_겹침과_틈은_맞닿은_것으로_붙는다(ready: None, tmp_path: Path) -> None:
    """0.01 mm 겹침은 두께 0.01 조각 부피를, 0.005 mm 틈은 떠 있는 블록(공유 절점 0)을 냈다.
    형상 맞춤 허용오차를 형상 읽기 전에 주면 둘 다 꼭 맞닿은 것처럼 부피 둘이 절점을 나눈다."""
    for lift in (-0.01, 0.005):
        work = tmp_path / f"lift{lift:+g}"
        work.mkdir()
        step = _blocks(work, lift)
        loose = build_mesh(step, work, element_size_mm=8, second_order=False)
        if lift < 0:
            assert len(loose.solids) == 3  # 겹친 곳이 따로 떨어진다
        else:
            assert _shared(loose) == 0  # 블록이 떠 있다
        fitted = build_mesh(
            step, work, element_size_mm=8, second_order=False, tolerance=TOLERANCE
        )
        assert len(fitted.solids) == 2
        assert _shared(fitted) > 0


def test_겹친_바디를_쪼개도_파트_크기는_그_바디에_간다(ready: None, tmp_path: Path) -> None:
    """허용오차보다 큰 겹침은 쪼개기가 따로 떼어 번호를 민다 — 블록에 준 2 mm 가 겹친 조각에
    붙고 블록은 3.6 mm 였다. 쪼갠 뒤 조각을 원래 바디와 짝지어 크기를 준다."""
    step = _blocks(tmp_path, -0.01)
    probe = probe_volumes(step, tmp_path)
    block = min(probe.volumes, key=lambda one: one.volume).index
    made = build_module._Layout(sizes={block: 2.0})
    sizes = build_module._sizes_after_fragment(step, tmp_path, made, probe, 0.0, 300)
    mesh = build_mesh(
        step, tmp_path, element_size_mm=8, second_order=False, volume_sizes=sizes
    )
    pieces = {body.index: body.volume for body in mesh.bodies}
    remainder = next(tag for tag, volume in pieces.items() if volume == pytest.approx(7996))
    sliver = next(tag for tag, volume in pieces.items() if volume == pytest.approx(4))
    assert sizes == {remainder: 2.0, sliver: 2.0}
    assert _mean_edge(mesh, remainder) == pytest.approx(2.6, abs=0.3)
    assert not made.notes


def test_작은_구멍보다_큰_요소는_곡률_크기로_다시_만든다(ready: None, tmp_path: Path) -> None:
    """크기 15 는 R4 구멍 둘레에서 「No elements in volume」 이었다 — 곡률 크기를 켜면 선다.
    처음부터 켜지 않는다(서는 모델의 밀도를 바꾸지 않으려고) — 그래서 다시 만든 것을 적는다."""
    mesh = build_mesh(_cylinder(tmp_path), tmp_path, element_size_mm=15, second_order=False)
    assert mesh.element_count > 0
    assert any("곡률 크기" in one for one in mesh.repairs)


def test_2차_요소가_뒤집히지_않는다(ready: None, tmp_path: Path) -> None:
    """크기 8 의 2차 사면체 27개가 det J ≤ 0 이었고 ccx 가 멈췄다. 휜 요소 바로잡기
    (`Mesh.HighOrderOptimize`)와 읽을 때 펴기가 0 으로 만든다 — 요소 수는 그대로다."""
    mesh = build_mesh(_cylinder(tmp_path), tmp_path, element_size_mm=8, second_order=True)
    assert mesh.second_order
    inverted = [
        number
        for rows in mesh.solids.values()
        for number, ids in rows
        if mesh_module._inverted([mesh.nodes[one] for one in ids])
    ]
    assert inverted == []
