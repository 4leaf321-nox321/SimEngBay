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


def test_허용오차는_CompCore_의_바디_사이_틈을_따르고_서버가_덮어쓸_수_있다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """핸드폰 부품의 설계 틈새(0.05 ~ 0.2 mm)를 닫으면 안 된다 — CompCore 가 「CAD 가 남긴 틈」
    으로 보는 값(`checks.contact_gap`, 기본 0.001)과 같게 둔다."""
    monkeypatch.delenv(build_module.BOOLEAN_TOLERANCE_ENV, raising=False)
    assert build_module._boolean_tolerance({"checks": {"contact_gap": 0.002}}) == 0.002
    # 옛 폴더(contact_gap 없음) · 점 파일 없는 작업은 CompCore 의 기본.
    assert build_module._boolean_tolerance({"checks": {"min_wall": 0.5}}) == 0.001
    assert build_module._boolean_tolerance({}) == 0.001
    monkeypatch.setenv(build_module.BOOLEAN_TOLERANCE_ENV, "0.05")
    assert build_module._boolean_tolerance({"checks": {"contact_gap": 0.002}}) == 0.05
    monkeypatch.setenv(build_module.BOOLEAN_TOLERANCE_ENV, "0")
    assert build_module._boolean_tolerance({}) == 0.0


def test_CompCore_가_잰_겹침_틈을_붙였는지_남겼는지_적는다() -> None:
    topology = {
        "quality": {
            "contacts": [
                {"kind": "gap", "a": "프레임", "b": "커버", "size": 0.0005, "at": [0, 0, 0]},
                {"kind": "overlap", "a": "판", "b": "블록", "size": 0.01, "at": [50, 50, 20]},
                {"kind": "gap", "a": "판", "b": "버튼", "size": 0.1, "at": [0, 0, 0]},
            ]
        }
    }
    closed, overlapped, gaps = build_module._contact_notes(topology, 0.001)
    assert "「프레임」 · 「커버」 틈 0.0005 mm" in closed and "붙여" in closed
    assert "「판」 · 「블록」 겹침 0.01 mm" in overlapped and "CAD 에서 고치세요" in overlapped
    assert "「판」 · 「버튼」 틈 0.1 mm" in gaps and "설계 틈새" in gaps
    assert build_module._contact_notes({}, 0.001) == []


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


def test_요소_품질은_정사면체가_1_이고_납작할수록_0_에_가깝다() -> None:
    from app.core.calculix.mesh import Mesh, quality

    h = (2 / 3) ** 0.5
    regular = {
        1: (0.0, 0.0, 0.0),
        2: (1.0, 0.0, 0.0),
        3: (0.5, 3**0.5 / 2, 0.0),
        4: (0.5, 3**0.5 / 6, h),
    }
    flat = {**regular, 4: (0.5, 3**0.5 / 6, 0.01)}
    for nodes, expected_poor in ((regular, 0), (flat, 1)):
        mesh = Mesh(
            nodes=nodes,
            solids={1: [(1, [1, 2, 3, 4])]},
            faces=[],
            bodies=[],
            face_nodes={},
            triangles=[],
            face_triangles={},
            face_rings={},
            second_order=False,
        )
        worst, poor, total = quality(mesh)
        assert total == 1 and poor == expected_poor
        if expected_poor == 0:
            assert worst == pytest.approx(1.0, abs=1e-9)


def test_작은_바디는_짧은_변에_요소_둘이_들어가게_크기를_준다() -> None:
    """한 변 0.24 mm 바디를 요소 0.3 mm 로 메시하면 2차로 올릴 때 뒤집혔다(운영 VOC). 가장 긴
    변도 전역 크기의 네 배 안인 바디만 — 얇고 넓은 판까지 줄이면 요소가 폭증한다."""
    from app.core.calculix.mesh import Probe

    probe = Probe(
        volumes=[
            BodyRecord(index=1, volume=40.0, centroid=(0.0, 0.0, 0.0)),
            BodyRecord(index=2, volume=0.0138, centroid=(3.0, 0.0, 0.0)),
            BodyRecord(index=3, volume=1.25, centroid=(9.0, 0.0, 0.0)),
            BodyRecord(index=4, volume=0.01, centroid=(20.0, 0.0, 0.0)),
        ],
        boxes={
            1: (0.0, 0.0, 0.0, 10.0, 4.0, 1.0),
            2: (2.9, 0.0, 0.0, 3.14, 0.24, 0.24),
            3: (4.0, 0.0, 0.0, 9.0, 5.0, 0.05),  # 얇고 넓은 판 — 그대로
            4: (19.9, 0.0, 0.0, 20.1, 0.2, 0.25),  # 사람이 크기를 줬다 — 그대로
        },
    )
    topology = {
        "bodies": [
            {"name": "판", "volume": 40.0, "centroid": [0.0, 0.0, 0.0]},
            {"name": "연결편", "volume": 0.014, "centroid": [3.0, 0.0, 0.0]},
        ]
    }
    made = build_module._Layout(sizes={4: 0.05})
    found = build_module._small_bodies(probe, topology, made, 0.3)
    assert found == {2: pytest.approx(0.12)}
    assert "「연결편」" in made.notes[0] and "0.12 mm" in made.notes[0]


def test_펴고도_남은_뒤집힌_요소는_곧은_것까지_센다() -> None:
    """펴기는 휜 요소만 본다 — 꼭짓점 사면체가 뒤집힌 곧은 요소는 펴서 고쳐지지 않아,
    전에는 그대로 솔버로 가 「nonpositive jacobian」 이었다(운영 VOC, v0.25.1). 남은 것을 세어
    다시 만든다."""
    from app.core.calculix.mesh import _still_inverted

    good = _tet10(0.0)
    ids = list(range(1, 11))
    assert _still_inverted(good, {1: [(1, ids)]}) == 0
    # 꼭짓점 둘을 맞바꾸면 곧은 채로 뒤집힌다(중간 절점도 같이 바꾼다).
    flipped = [1, 3, 2, 4, 7, 6, 5, 8, 10, 9]
    assert _still_inverted(good, {1: [(1, flipped)]}) == 1
    assert _still_inverted(good, {1: [(1, [1, 2, 3, 4]), (2, [1, 3, 2, 4])]}) == 1


def test_뒤집혀_멈추면_어느_바디의_요소인지_말한다(tmp_path: Path) -> None:
    (tmp_path / "boundary.json").write_text(
        '{"element_owners": [[1, 100, "판"], [101, 130, "스프링"], [131, 140, "용접판"]]}',
        encoding="utf-8",
    )
    log = "".join(
        f" *ERROR in e_c3d: nonpositive jacobian\n         determinant in element {n}\n"
        for n in (105, 120, 133)
    )
    failure = solve_module._jacobian_failure(tmp_path, log)
    assert failure.code == "solver_failed"
    assert "요소 3개" in failure.message
    assert "「스프링」 2개" in failure.message and "「용접판」 1개" in failure.message
    assert failure.details["bodies"] == {"스프링": 2, "용접판": 1}


def test_정한_바디만_1차로_낮추고_그_면에서도_중간_절점을_뺀다() -> None:
    """바디별 요소 차수 — 2차로 메시하고 1차 바디의 중간 절점을 뺀다(`mesh.demote`)."""
    from app.core.calculix.mesh import Mesh, demote

    nodes = _tet10(0.0)
    other = {at + 20: (x + 5, y, z) for at, (x, y, z) in nodes.items()}
    mesh = Mesh(
        nodes={**nodes, **other},
        solids={1: [(1, list(range(1, 11)))], 2: [(2, list(range(21, 31)))]},
        faces=[],
        bodies=[],
        face_nodes={9: {1, 2, 3, 5, 6, 7}, 19: {21, 22, 23, 25, 26, 27}},
        triangles=[],
        face_triangles={9: [(1, 2, 3)], 19: [(21, 22, 23)]},
        face_rings={9: [[1, 2, 3, 5, 6, 7]], 19: [[21, 22, 23, 25, 26, 27]]},
        second_order=True,
    )
    low = demote(mesh, {1})
    assert low.solids[1] == [(1, [1, 2, 3, 4])]
    assert low.solids[2] == mesh.solids[2]
    assert set(range(5, 11)).isdisjoint(low.nodes) and 25 in low.nodes
    assert low.face_nodes[9] == {1, 2, 3} and low.face_rings[9] == [[1, 2, 3]]
    assert low.face_rings[19] == mesh.face_rings[19]
    assert low.second_order
    assert not demote(mesh, {1, 2}).second_order


def test_기울어진_면의_마찰_없는_지지는_절점마다_법선_구속식이다() -> None:
    from app.core import conditions as condition_model
    from app.core.calculix.deck import _frictionless

    rule = condition_model.Constraint(name="경사 받침", kind="frictionless", region="경사")
    lines, why, inclined = _frictionless(
        "HOLD0", rule, {1, 2, 3}, {"normal": [0.0, 0.6, -0.8]}, others={3}
    )
    assert why is None and inclined
    assert lines[0] == "*EQUATION"
    assert lines[1:] == ["2", "1, 3, -0.8, 1, 2, 0.6", "2", "2, 3, -0.8, 2, 2, 0.6"]
    flat, why, inclined = _frictionless("HOLD0", rule, {1, 2}, {"normal": [0.0, 0.0, -1.0]})
    assert not inclined and "HOLD0, 3, 3, 0.0" in flat
