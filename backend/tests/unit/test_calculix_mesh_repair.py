"""메시 보정 · 솔버 고르기 — 도구 없이 보는 것.

진짜 gmsh · ccx 로 도는 쪽은 `tests/opensolver/test_mesh_repair.py` · `test_calculix.py` 다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.core.bodies import BodyRecord
from app.core.calculix import tools
from app.core.calculix.mesh import _geo, _inverted, _straighten, fragment_owners
from app.core.calculix.solve import (
    ITERATIVE_LINE,
    degrees_of_freedom,
    plan_solver,
    spooles_mb,
    with_iterative,
)
from app.core.stages import StageFailure

# 패키지가 `build` · `solve` 라는 이름의 함수를 내보내 모듈 이름을 가린다 — 모듈을 직접 꺼낸다.
__import__("app.core.calculix.build")
build_module = sys.modules["app.core.calculix.build"]
solve_module = sys.modules["app.core.calculix.solve"]


def _lines(**options: object) -> list[str]:
    return _geo(Path("/data/input.step"), 5.0, True, {}, **options).splitlines()  # type: ignore[arg-type]


def test_허용오차는_형상을_읽기_전에_준다() -> None:
    lines = _lines(tolerance=0.0147)
    tolerance = lines.index("Geometry.ToleranceBoolean = 0.0147;")
    read = next(at for at, line in enumerate(lines) if "ShapeFromFile" in line)
    assert tolerance < read
    assert not any("ToleranceBoolean" in line for line in _lines())


def test_2차는_휜_요소를_바로잡고_곡률_크기는_다시_만들_때만_켠다() -> None:
    assert "Mesh.HighOrderOptimize = 2;" in _lines()
    assert not any(
        "HighOrderOptimize" in line
        for line in _geo(Path("/x.step"), 5.0, False, {}).splitlines()
    )
    assert not any("MeshSizeFromCurvature" in line for line in _lines())
    assert "Mesh.MeshSizeFromCurvature = 6;" in _lines(curvature=6)


#: 꼭짓점 사면체(양) — (0,0,0) (1,0,0) (0,1,0) (0,0,1).
CORNERS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
EDGES = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))


def _tet10(push: float) -> dict[int, tuple[float, float, float]]:
    """1 ~ 10 번 절점의 2차 사면체 — 모서리 (1-2) 의 중간 절점을 `push` 만큼 사면체 안으로
    민다."""
    nodes = {at + 1: point for at, point in enumerate(CORNERS)}
    for offset, (a, b) in enumerate(EDGES):
        nodes[5 + offset] = tuple(  # type: ignore[assignment]
            (CORNERS[a][axis] + CORNERS[b][axis]) / 2 for axis in range(3)
        )
    x, y, z = nodes[5]
    nodes[5] = (x, y + push, z + push)
    return nodes


def test_뒤집힌_2차_요소는_중간_절점을_편다() -> None:
    nodes = _tet10(0.6)
    ids = list(range(1, 11))
    assert _inverted([nodes[one] for one in ids])
    moved, fixed, everything = _straighten(nodes, {1: [(1, ids)]})
    assert (fixed, everything) == (1, False)
    assert moved[5] == pytest.approx((0.5, 0.0, 0.0))
    assert not _inverted([moved[one] for one in ids])
    # 조금 휜 것은 그대로 둔다 — 곡면을 따라 놓인 절점이다.
    gentle = _tet10(0.05)
    assert _straighten(gentle, {1: [(1, ids)]})[1] == 0


def _body(index: int, volume: float, z: float) -> BodyRecord:
    return BodyRecord(index=index, volume=volume, centroid=(50.0, 50.0, z))


def test_쪼갠_조각을_원래_바디와_짝짓는다() -> None:
    """판(0 ~ 20) 위 블록(19.99 ~ 39.99) — 0.01 mm 겹친 곳이 세 번째 조각이 된다."""
    before = [_body(1, 200_000.0, 10.0), _body(2, 8_000.0, 29.99)]
    # 맞닿기만 하면 번호가 그대로다.
    assert fragment_owners(before, before) == ({1: frozenset({1}), 2: frozenset({2})}, [])

    shared = BodyRecord(index=0, volume=4.0, centroid=(50.0, 50.0, 19.995))
    plate_z = (200_000.0 * 10.0 - 4.0 * 19.995) / 199_996.0
    block_z = (8_000.0 * 29.99 - 4.0 * 19.995) / 7_996.0
    after = [_body(1, 199_996.0, plate_z), _body(2, 4.0, 19.995), _body(3, 7_996.0, block_z)]
    owners, unmatched = fragment_owners(before, after, {(1, 2): shared})
    assert owners == {1: frozenset({1}), 2: frozenset({1, 2}), 3: frozenset({2})}
    assert unmatched == []
    # 겹친 곳을 몰라도 판 · 블록 조각은 원래 바디와 거의 같아(0.1% 안) 맞는다 — 얇은 조각만
    # 못 맞춘다(상자도 없으면 못 맞춘 채 돌려준다).
    assert fragment_owners(before, after) == ({1: frozenset({1}), 3: frozenset({2})}, [2])


def test_허용오차는_모델_크기에_비례하고_서버가_덮어쓸_수_있다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(build_module.BOOLEAN_TOLERANCE_ENV, raising=False)
    topology = {
        "bodies": [
            {"bbox": [[0, 0, 0], [100, 100, 20]]},
            {"bbox": [[40, 40, 20], [60, 60, 40]]},
        ]
    }
    assert build_module._boolean_tolerance(topology) == pytest.approx(0.014697, rel=1e-4)
    assert build_module._boolean_tolerance({}) == 0.0
    monkeypatch.setenv(build_module.BOOLEAN_TOLERANCE_ENV, "0.05")
    assert build_module._boolean_tolerance(topology) == 0.05
    monkeypatch.setenv(build_module.BOOLEAN_TOLERANCE_ENV, "0")
    assert build_module._boolean_tolerance(topology) == 0.0


def test_CompCore_가_잰_겹침_틈을_붙였는지_남겼는지_적는다() -> None:
    topology = {
        "quality": {
            "contacts": [
                {"kind": "overlap", "a": "판", "b": "블록", "size": 0.01, "at": [50, 50, 20]},
                {"kind": "gap", "a": "판", "b": "핀", "size": 0.2, "at": [0, 0, 0]},
            ]
        }
    }
    closed, kept = build_module._contact_notes(topology, 0.0147)
    assert "「판」 · 「블록」 겹침 0.01 mm" in closed and "붙여" in closed
    assert "「판」 · 「핀」 틈 0.2 mm" in kept and build_module.BOOLEAN_TOLERANCE_ENV in kept
    assert build_module._contact_notes({}, 0.0147) == []


STATIC_DECK = (
    "*NODE\n1, 0, 0, 0\n2, 1, 0, 0\n*ELEMENT, TYPE=C3D4\n1, 1, 2\n"
    "*STEP\n*STATIC\n*NODE FILE\nU\n*END STEP\n"
)


def test_자유도를_세고_정적_단계를_반복_솔버로_바꾼다() -> None:
    assert degrees_of_freedom(STATIC_DECK) == 6
    rewritten = with_iterative(STATIC_DECK)
    assert ITERATIVE_LINE in rewritten.splitlines()
    assert "*STATIC\n" not in rewritten


def test_메모리가_모자랄_것_같은_정적만_반복_솔버로_고른다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(solve_module.LINEAR_SOLVER_ENV, raising=False)
    # 자유도 16.5만 → SPOOLES 2,370 MB(실측) — 남은 3,000 MB 의 70% 를 넘는다.
    assert spooles_mb(165_000) == pytest.approx(2370.0)
    big = STATIC_DECK.replace(
        "2, 1, 0, 0\n", "".join(f"{n}, 0, 0, 0\n" for n in range(2, 55_001))
    )
    assert plan_solver(big, 3000.0).iterative
    assert not plan_solver(big, 10_000.0).iterative
    assert not plan_solver(big, None).iterative  # 남은 메모리를 모르면 어림하지 않는다
    # 고유치 · 구속 방정식(강체 묶음)은 반복 솔버를 못 쓴다.
    modal = big.replace("*STATIC", "*FREQUENCY, SOLVER=SPOOLES")
    assert not plan_solver(modal, 3000.0).can_iterate
    held = big.replace("*STEP", "*RIGID BODY, NSET=A, REF NODE=1, ROT NODE=2\n*STEP")
    assert not plan_solver(held, 3000.0).iterative
    monkeypatch.setenv(solve_module.LINEAR_SOLVER_ENV, "spooles")
    assert not plan_solver(big, 3000.0).iterative
    monkeypatch.setenv(solve_module.LINEAR_SOLVER_ENV, "iterative")
    assert plan_solver(STATIC_DECK, None).iterative


def test_메모리로_끊기면_반복_솔버로_한_번_더_푼다(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(solve_module.LINEAR_SOLVER_ENV, raising=False)
    (tmp_path / "model.inp").write_text(STATIC_DECK, encoding="utf-8")
    seen: list[str] = []

    def run(binary: Path, args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        deck = (tmp_path / "model.inp").read_text(encoding="utf-8")
        seen.append(deck)
        if ITERATIVE_LINE not in deck:
            raise StageFailure(
                "out_of_memory", "CalculiX 가 메모리가 모자라 강제로 멈췄습니다."
            )
        (tmp_path / "model.dat").write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="Job finished", stderr="")

    monkeypatch.setattr(tools, "run", run)
    monkeypatch.setattr(tools, "ccx_bin", lambda: Path("/usr/bin/ccx"))
    result = solve_module.solve(tmp_path)
    assert len(seen) == 2
    assert result.summary["linear_solver"] == "iterative"
    assert "반복 솔버로 다시" in str(result.summary["solver_retry"])


def test_반복_솔버를_못_쓰면_끊긴_글에_어림을_붙인다(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(solve_module.LINEAR_SOLVER_ENV, raising=False)
    (tmp_path / "model.inp").write_text(
        STATIC_DECK.replace("*STATIC", "*FREQUENCY, SOLVER=SPOOLES"), encoding="utf-8"
    )

    def run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        raise StageFailure("out_of_memory", "CalculiX 가 메모리가 모자라 강제로 멈췄습니다.")

    monkeypatch.setattr(tools, "run", run)
    monkeypatch.setattr(tools, "ccx_bin", lambda: Path("/usr/bin/ccx"))
    with pytest.raises(StageFailure) as caught:
        solve_module.solve(tmp_path)
    assert caught.value.code == "out_of_memory"
    assert "자유도 6" in caught.value.message and "메모리 어림" in caught.value.message


def test_남은_메모리는_워커_묶음의_상한까지_본다(tmp_path: Path) -> None:
    """운영의 상한은 워커 하나가 아니라 묶음(`<slug>-workers.slice`)에 걸린다 — 워커 자신의
    `memory.max` 는 `max` 다. 시스템의 MemAvailable 보다 묶음의 남은 한도가 작으면 그것이다."""
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "meminfo").write_text("MemTotal: 67108864 kB\nMemAvailable: 33554432 kB\n")
    (proc / "self" / "cgroup").write_text("0::/seb-workers.slice/seb-worker@2.service\n")
    root = tmp_path / "cgroup"
    slice_ = root / "seb-workers.slice"
    unit = slice_ / "seb-worker@2.service"
    unit.mkdir(parents=True)
    (unit / "memory.max").write_text("max\n")
    (slice_ / "memory.max").write_text(f"{8 * 1024**3}\n")
    (slice_ / "memory.current").write_text(f"{5 * 1024**3}\n")
    assert solve_module.available_mb(root, proc) == pytest.approx(3 * 1024)
    # 묶음이 없으면 시스템의 남은 메모리(32 GB)다.
    (slice_ / "memory.max").write_text("max\n")
    assert solve_module.available_mb(root, proc) == pytest.approx(32 * 1024)
