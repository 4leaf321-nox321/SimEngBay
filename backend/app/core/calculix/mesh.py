"""STEP → 메시, 그리고 **그 메시에서 면 · 바디를 되찾기.**

Ansys 쪽은 Mechanical 이 형상을 들고 있어서 면을 물어보면 됐다. 여기서는 형상이 없고 메시만
있으므로, **표면 요소를 모아** 면마다 무게중심 · 면적 · 법선을 계산한다 — Mechanical 이 주던
것과 같은 종류의 값이다. 그래서 `app/core/regions` 의 매처를 **한 줄도 안 고치고** 쓴다
(실측 2026-10-02: `조건_측면가진` 의 바닥 · 기둥 끝 · 접합면이 그대로 풀렸다).

## 맞닿은 면을 쪼개 하나로 만든다

`BooleanFragments` 를 걸면 두 솔리드가 맞닿은 자리가 **한 면**이 되어 절점을 공유한다. 그것이
본딩 접촉의 상한이고, Ansys 의 bonded(MPC)와 1차에서 0.23% 차이였다(실측). 안 걸면 두 솔리드가
따로 메시되어 **붙어 있지 않은 모델**이 되고, 강체 모드가 바디마다 6개씩 나온다 — 값은
그럴듯한데 모델이 떨어져 있는 상태다.

## 파트를 메시 전에 안다

파트별 설정(해석 제외 · 파트 요소 크기)은 **메시를 만들기 전에** 걸려야 한다 — 빼려는
파트가 메시가 안 나오는 부품(나사산 붙은 나사)일 때가 많고, 크기는 메시가 시작할 때
정해진다. 그래서 gmsh 에게 형상만 읽혀(`-0`, 메시 없이) **부피마다 부피값 · 무게중심**을
묻는다(`probe_volumes`). `.geo` 의 `Mass` · `CenterOfMass` 가 답한다 — 실측 0.06초
(2026-10-04). 그 값으로 CAD 파트와 짝지은 뒤, 뺄 부피를 지우고(`Recursive Delete`) 파트
크기를 그 부피의 점에 준다.

## 단위

형상은 **늘 mm** 다(CompCore 계약). 그래서 메시도 mm 이고, 덱은 mm · tonne · N (MPa) 로 쓴다 —
Ansys 쪽 `ConsistentNMM` 과 같은 계라 주파수가 Hz, 변위가 mm 로 나온다.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app.core.bodies import BodyRecord
from app.core.calculix import tools
from app.core.regions import FaceRecord
from app.core.stages import StageFailure

logger = logging.getLogger(__name__)

#: 2차 사면체(gmsh 형 11) → CalculiX `C3D10`. **마지막 두 절점이 바뀐다** — 모서리 순서가
#: gmsh 는 (3-4) · (2-4), CalculiX 는 (2-4) · (3-4) 다. 틀리면 ccx 가 야코비안으로 죽는다.
TET10_ORDER = (0, 1, 2, 3, 4, 5, 6, 7, 9, 8)
#: 1차 사면체. 굽힘에 지나치게 단단해서 기본으로 쓰지 않는다.
TET4_ORDER = (0, 1, 2, 3)
#: gmsh 요소형 번호 — 삼각형(1차 · 2차), 사면체(1차 · 2차).
TRIANGLE_KINDS = (2, 9)
TET_KINDS = {4: TET4_ORDER, 11: TET10_ORDER}


@dataclass(frozen=True)
class Mesh:
    """메시 한 벌 — 절점, 사면체(솔리드별), 면(지문), 바디(부피 · 무게중심)."""

    nodes: dict[int, tuple[float, float, float]]
    #: 솔리드(기하 부피 번호) → [(요소 번호, 절점들)]
    solids: dict[int, list[tuple[int, list[int]]]]
    faces: list[FaceRecord]
    bodies: list[BodyRecord]
    #: 면 번호 → 그 면의 절점 전부(2차 요소의 중간 절점까지)
    face_nodes: dict[int, set[int]]
    #: 껍데기 삼각형(모서리 셋) — 모드 형상 파일이 이것만 쓴다(`vtp.py`).
    triangles: list[tuple[int, int, int]]
    #: 면 번호 → 그 면의 삼각형들(모서리 셋). 압력 하중이 요소면을 적을 때 쓴다.
    face_triangles: dict[int, list[tuple[int, int, int]]]
    #: 면 번호 → 그 면 요소의 **절점 전부**(2차면 여섯). 힘을 나눌 때 쓴다 — 중간 절점을
    #: 빼면 모서리만 하중을 받아, 2차 요소에서는 오히려 **거꾸로 된** 분포가 된다(일관 하중은
    #: 모서리에 0 을 준다). 실측 2026-10-03: 구멍면 절점 436 중 57 만 받았다.
    face_rings: dict[int, list[list[int]]]
    second_order: bool
    #: 쉘 면(중간면의 기하 면 번호) → [(요소 번호, 절점들)]. 삼각형 — 2차면 6절점(`S6`).
    shells: dict[int, list[tuple[int, list[int]]]] = field(default_factory=dict)

    @property
    def element_count(self) -> int:
        return sum(len(rows) for rows in self.solids.values()) + sum(
            len(rows) for rows in self.shells.values()
        )


#: `probe_volumes` 가 gmsh 에게 찍게 하는 줄의 머리. 다른 출력과 섞여도 이것으로 고른다.
PROBE_MARK = "SEB_VOLUME"
#: 쉘(중간면)의 면 하나 — 넓이 · 무게중심.
SURFACE_MARK = "SEB_SURFACE"


@dataclass(frozen=True)
class Probe:
    """메시 없이 잰 형상 — 부피와 중간면의 면들(`volume` 칸이 넓이다)."""

    volumes: list[BodyRecord]
    surfaces: list[BodyRecord] = field(default_factory=list)


def probe_volumes(
    step: Path,
    workdir: Path,
    *,
    fragment: bool = True,
    timeout_seconds: int = 300,
    shell_step: Path | None = None,
) -> Probe:
    """메시 없이 **gmsh 부피 번호마다 부피 · 무게중심**(mm)을 잰다 — 파트와 짝짓는 데 쓴다.
    중간면이 있으면 **면 번호마다 넓이 · 무게중심**도 잰다(쉘 파트에 나눠 준다).

    `build_mesh` 와 **같은 머리**(형상 읽기 · 쪼개기)를 지나야 번호가 같다.
    """
    geo = workdir / "probe.geo"
    geo.write_text(
        "\n".join(
            [
                # 쪼개기 없이 잰다 — 지우기는 쪼개기 전에 하므로 그때의 번호가 필요하다.
                *_head_lines(step, False, shell_step),
                "vols() = Volume{:};",
                "For i In {0:#vols()-1}",
                "  m = Mass Volume{vols(i)};",
                "  c() = CenterOfMass Volume{vols(i)};",
                f'  Printf("{PROBE_MARK} %g %.12g %.12g %.12g %.12g", vols(i), m, c(0), c(1), '
                "c(2));",
                "EndFor",
                *(
                    [
                        "For i In {0:#sh()-1}",
                        "  a = Mass Surface{sh(i)};",
                        "  c() = CenterOfMass Surface{sh(i)};",
                        f'  Printf("{SURFACE_MARK} %g %.12g %.12g %.12g %.12g", sh(i), a, '
                        "c(0), c(1), c(2));",
                        "EndFor",
                    ]
                    if shell_step is not None
                    else []
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    # `-v 3` 이어야 `Printf` 가 나온다(실측 — `-v 2` 면 아무것도 안 찍는다).
    done = tools.run(
        tools.gmsh_bin(),
        [str(geo), "-0", "-o", str(workdir / "probe.geo_unrolled"), "-nopopup", "-v", "3"],
        cwd=workdir,
        timeout_seconds=timeout_seconds,
        what="gmsh",
    )
    found = parse_probe(done.stdout or "")
    if not found:
        tail = (done.stdout or "")[-1500:] + (done.stderr or "")[-1500:]
        raise StageFailure("mesh_failed", f"gmsh 가 형상의 부피를 읽지 못했습니다:\n{tail}")
    return Probe(volumes=found, surfaces=parse_probe(done.stdout or "", mark=SURFACE_MARK))


def parse_probe(text: str, *, mark: str = PROBE_MARK) -> list[BodyRecord]:
    """`SEB_VOLUME 번호 부피 cx cy cz` 줄들 → 바디 기록(`SEB_SURFACE` 면 넓이)."""
    found: list[BodyRecord] = []
    for line in text.splitlines():
        parts = line.split()
        if mark not in parts:
            continue
        values = parts[parts.index(mark) + 1 :]
        if len(values) < 5:
            continue
        try:
            tag = int(float(values[0]))
            volume, x, y, z = (float(one) for one in values[1:5])
        except ValueError:
            continue
        found.append(BodyRecord(index=tag, volume=volume, centroid=(x, y, z)))
    return found


def build_mesh(
    step: Path,
    workdir: Path,
    *,
    element_size_mm: float,
    second_order: bool = True,
    timeout_seconds: int = 1800,
    local_sizes: dict[int, float] | None = None,
    surface_only: bool = False,
    fragment: bool = True,
    removed: frozenset[int] = frozenset(),
    volume_sizes: dict[int, float] | None = None,
    shell_step: Path | None = None,
    shell_sizes: dict[int, float] | None = None,
) -> Mesh:
    """gmsh 를 불러 메시를 만들고 읽는다. `.geo` 와 `.msh` 가 작업 폴더에 남는다.

    `local_sizes` 는 **면 번호 → 요소 크기(mm)** 다 — CAD 의 영역별 메시 힌트가 그렇게
    들어온다. `surface_only` 는 **면 번호를 먼저 알아내는 1차 통과**에 쓴다(2차원만 메시하므로
    빠르다): 힌트는 영역 **이름**으로 오고, 그 이름을 면 번호로 바꾸려면 면 지문이 필요한데
    그 지문이 메시에서 나온다(닭과 달걀). 그 순서는 `build.py` 가 쥔다.

    `removed` 는 **해석에서 뺄 부피 번호**, `volume_sizes` 는 **부피 번호 → 파트 요소
    크기(mm)** 다 — 둘 다 `probe_volumes` 로 파트와 짝지은 번호다.
    """
    geo = workdir / ("surface.geo" if surface_only else "model.geo")
    msh = workdir / ("surface.msh" if surface_only else "model.msh")
    geo.write_text(
        _geo(
            step,
            element_size_mm,
            second_order,
            local_sizes or {},
            fragment,
            removed=removed,
            volume_sizes=volume_sizes or {},
            shell_step=shell_step,
            shell_sizes=shell_sizes or {},
        ),
        encoding="utf-8",
    )
    done = tools.run(
        tools.gmsh_bin(),
        [str(geo), "-2" if surface_only else "-3", "-o", str(msh), "-nopopup", "-v", "2"],
        cwd=workdir,
        timeout_seconds=timeout_seconds,
        what="gmsh",
    )
    if not msh.is_file():
        tail = (done.stdout or "")[-1500:] + (done.stderr or "")[-1500:]
        raise StageFailure("mesh_failed", f"gmsh 가 메시를 못 만들었습니다:\n{tail}")
    # 1차 통과는 **면만** 만든다 — 사면체가 없는 것이 정상이다.
    return read_mesh(
        msh,
        require_solid=not surface_only,
        shell_surfaces=frozenset(shell_sizes or {}) if shell_step is not None else frozenset(),
    )


def _head_lines(
    step: Path,
    fragment: bool,
    shell_step: Path | None = None,
    removed: frozenset[int] = frozenset(),
) -> list[str]:
    """형상 읽기 · 지우기 · 쪼개기 — **부피 · 면 번호가 여기서 정해진다**(모든 통과가 같이
    지난다).

    중간면(쉘)은 **먼저** 읽는다 — 그래야 그 면 번호가 형상 쪽 지우기 · 쪼개기에 흔들리지
    않는다. 중간면은 솔리드와 쪼개지 않는다 — 두께의 절반만큼 떨어져 있어 닿지 않고, 잇는 것은
    접촉(`*TIE`)이다.

    **뺄 부피(해석 제외 · 쉘 파트의 솔리드)는 쪼개기 전에 지운다.** 쪼갠 뒤에 지우면 이웃 면에
    맞닿았던 자국이 남아 면이 둘로 갈라지고, 그 면을 가리키는 조건이 「중심이 떨어져 있다」 로
    멈춘다(실측 2026-10-04: 쉘 브래킷을 지운 강체 블록의 윗면). 쪼개기는 부피 번호를 바꾸지
    않으므로(실측) 쪼개기 없이 잰 번호(`probe_volumes`)로 지우고 크기를 준다.
    """
    return [
        'SetFactory("OpenCASCADE");',
        *([f'sh() = ShapeFromFile("{shell_step.resolve()}");'] if shell_step else []),
        # **절대경로로 적는다** — gmsh 는 `.geo` 가 있는 폴더를 기준으로 찾으므로
        # 상대경로를 주면 「파일을 못 읽는다」 로 끝난다(실측 2026-10-03).
        f'v() = ShapeFromFile("{step.resolve()}");',
        *(f"Recursive Delete {{ Volume{{{tag}}}; }}" for tag in sorted(removed)),
        # **맞닿은 면을 하나로 — 절점을 공유해야 붙은 모델이 된다.**
        #
        # 안 쪼개면(`fragment=False`) 두 솔리드가 따로 메시되어 접합면이 **두 장**으로
        # 남는다. 그때는 접촉 쌍을 써야 하고, 안 쓰면 바디가 떨어져 있어 강체 모드가
        # 바디마다 6개씩 나온다 — 값은 그럴듯한데 모델이 붙어 있지 않은 상태다.
        *(["BooleanFragments{ Volume{:}; Delete; }{}"] if fragment else []),
    ]


def _geo(
    step: Path,
    size: float,
    second_order: bool,
    local_sizes: dict[int, float],
    fragment: bool = True,
    *,
    removed: frozenset[int] = frozenset(),
    volume_sizes: dict[int, float] | None = None,
    shell_step: Path | None = None,
    shell_sizes: dict[int, float] | None = None,
) -> str:
    """gmsh 에게 줄 쪽지. **`.geo` 파일이 경계다** — 파이썬 API 를 안 쓴다(`tools` 참고)."""
    parts = dict(volume_sizes or {})
    sheets = dict(shell_sizes or {})
    # 파트 크기가 전역보다 크면 상한을, 작으면 하한을 그만큼 넓힌다 — 안 그러면 gmsh 가 그
    # 파트를 전역 범위 안으로 되돌린다.
    largest = max([size, *parts.values(), *sheets.values()])
    smallest = min([size, *parts.values(), *sheets.values()])
    return (
        "\n".join(
            [
                *_head_lines(step, fragment, shell_step, removed),
                f"Mesh.MeshSizeMax = {largest:g};",
                f"Mesh.MeshSizeMin = {smallest / 4:g};",
                f"Mesh.ElementOrder = {2 if second_order else 1};",
                # 물리 그룹을 안 만들어도 전부 저장한다 — 우리는 기하 번호로 찾는다.
                "Mesh.SaveAll = 1;",
                "Mesh.MshFileVersion = 2.2;",
                # **파트 크기는 그 부피의 점에 준다** — 먼저 모든 점에 전역 크기를 주고(상한을
                # 넓혔으므로 안 주면 다른 파트가 성겨진다), 큰 것부터 적어 **맞닿은 점에서는
                # 작은 쪽이 이긴다.** 면 힌트는 그 뒤에 와서 파트 크기를 이긴다(좁은 쪽이
                # 이긴다 — CompCore 의 순서: 「전체」 < 파트 < 선택 그룹).
                *([f"MeshSize{{ PointsOf{{ Volume{{:}}; }} }} = {size:g};"] if parts else []),
                *(
                    f"MeshSize{{ PointsOf{{ Volume{{{tag}}}; }} }} = {value:g};"
                    for tag, value in sorted(parts.items(), key=lambda pair: -pair[1])
                ),
                # 쉘 면은 그 파트의 크기(없으면 전역) — 중간면 점에 준다.
                *(
                    f"MeshSize{{ PointsOf{{ Surface{{{tag}}}; }} }} = {value:g};"
                    for tag, value in sorted(sheets.items(), key=lambda pair: -pair[1])
                ),
                # **영역별 힌트는 그 면의 점에 크기를 준다.** `MeshSize{ PointsOf{ … } }` 는
                # gmsh 의 고전적인 방법이고, 필드를 세우는 것보다 읽기 쉽다. 전역 크기보다 큰
                # 값을 줘도 gmsh 가 받아 준다 — 그것이 CAD 가 말한 것이면 그대로 쓴다.
                *(
                    f"MeshSize{{ PointsOf{{ Surface{{{face}}}; }} }} = {value:g};"
                    for face, value in sorted(local_sizes.items())
                ),
            ]
        )
        + "\n"
    )


def read_mesh(
    msh: Path, *, require_solid: bool = True, shell_surfaces: frozenset[int] = frozenset()
) -> Mesh:
    """`.msh`(2.2) 를 읽어 절점 · 요소 · 면 지문 · 바디 지문을 낸다.

    `require_solid` 를 끄면 **면만 있는 메시**도 받는다(면 번호를 알아내는 1차 통과). 켜 두면
    사면체가 없을 때 멈춘다 — 그대로 풀면 요소가 없는 해석이 끝까지 돌 수 있다.
    """
    nodes, elements = _parse(msh)
    if not nodes:
        raise StageFailure("mesh_failed", "메시에 절점이 없습니다.")
    solids: dict[int, list[tuple[int, list[int]]]] = defaultdict(list)
    second_order = False
    number = 0
    for kind, entity, ids in elements:
        order = TET_KINDS.get(kind)
        if order is None:
            continue
        number += 1
        second_order = second_order or kind == 11
        solids[entity].append((number, [ids[one] for one in order]))
    # **쉘 요소** — 중간면의 삼각형. 번호는 사면체 다음부터(덱에서 한 줄 번호다).
    shells: dict[int, list[tuple[int, list[int]]]] = defaultdict(list)
    for kind, entity, ids in elements:
        if kind in TRIANGLE_KINDS and entity in shell_surfaces:
            number += 1
            shells[entity].append((number, list(ids)))
    if not solids and require_solid:
        raise StageFailure(
            "mesh_failed", "메시에 사면체가 없습니다 — 형상이 솔리드인지 보세요."
        )
    faces, face_nodes = _faces(nodes, elements)
    by_face = _triangles(elements)
    rings = _rings(elements)
    return Mesh(
        nodes=nodes,
        solids=dict(solids),
        faces=faces,
        bodies=_bodies(nodes, solids),
        face_nodes=face_nodes,
        triangles=[one for rows in by_face.values() for one in rows],
        face_triangles=by_face,
        face_rings=rings,
        second_order=second_order,
        shells=dict(shells),
    )


def _parse(
    path: Path,
) -> tuple[dict[int, tuple[float, float, float]], list[tuple[int, int, list[int]]]]:
    """msh2 를 읽는다 — 절점과 (요소형, 기하 자리, 절점들).

    요소 줄은 `번호 형 꼬리표수 [꼬리표...] 절점...` 이고, 꼬리표 둘째가 **기하 자리**(면 ·
    부피 번호)다. 우리가 찾는 것이 그 번호다 — 물리 그룹이 아니다.
    """
    nodes: dict[int, tuple[float, float, float]] = {}
    elements: list[tuple[int, int, list[int]]] = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    index = 0
    while index < len(lines):
        head = lines[index].strip()
        if head == "$Nodes":
            count = int(lines[index + 1])
            for row in lines[index + 2 : index + 2 + count]:
                parts = row.split()
                nodes[int(parts[0])] = (float(parts[1]), float(parts[2]), float(parts[3]))
            index += 2 + count
            continue
        if head == "$Elements":
            count = int(lines[index + 1])
            for row in lines[index + 2 : index + 2 + count]:
                numbers = [int(one) for one in row.split()]
                kind, tags = numbers[1], numbers[2]
                entity = numbers[3 + tags - 1] if tags >= 2 else 0
                elements.append((kind, entity, numbers[3 + tags :]))
            index += 2 + count
            continue
        index += 1
    return nodes, elements


#: 법선이 이 안에서 모이면 **평면**으로 본다. 2차 요소의 곡면 삼각형도 모서리 셋으로 재면
#: 몇 도씩 흔들리므로 0 도로 못 박을 수 없다.
PLANE_DEGREES = 5.0
#: 축에서의 거리가 이만큼 고르면 **원통**으로 본다(평균 대비 표준편차).
CYLINDER_SPREAD = 0.05


@dataclass(frozen=True)
class Shape:
    """그 면이 무엇인가 — 종류 · 반지름 · 축, 그리고 **CAD 식 중심**.

    CompCore 는 곡면의 중심을 **bbox 중심**으로 보낸다(평면만 면적 중심이다 —
    `backend/app/core/recipe/topology.py`). 반쪽 원통처럼 잘린 면에서는 그 둘이 다르므로,
    곡면은 bbox 중심으로 맞춰야 지문이 풀린다.
    """

    kind: str = ""
    radius: float | None = None
    axis: tuple[float, float, float] | None = None
    centroid: tuple[float, float, float] | None = None


def _classify(
    nodes: dict[int, tuple[float, float, float]],
    triangles: list[tuple[int, int, int]],
    members: set[int],
) -> Shape:
    """그 면이 평면인가 원통인가 — **지문을 되맞추려면 반지름이 필요하다.**

    조건은 면 번호로 오지 않는다. 평면은 `무게중심 · 면적 · 법선`, 원통은 `반지름 · 축` 으로
    온다(CompCore 계약). Mechanical 은 형상을 들고 있어 그 둘을 바로 주지만, 우리는 메시만
    있으므로 **삼각형에서 되맞춘다.** 못 맞추면 원통 지문이 영구히 안 풀린다(실측 2026-10-03:
    `조건_원통_SI` 의 구멍면).

    판정 순서가 중요하다. **평면을 먼저 가린다** — 평면을 원통으로 잘못 보면 지금 잘 풀리는
    지문들이 「평면이 아닙니다」 로 깨진다. 법선이 한 방향으로 모이면 평면이고, 그렇지 않으면
    축을 찾아 반지름이 고른지 본다. 둘 다 아니면 **아무 말도 하지 않는다**(빈 글자) — 모르는
    것을 원통이라고 적으면 그 지문이 조용히 엉뚱한 면에 붙는다.
    """
    if len(triangles) < 4:
        return Shape()
    normals: list[tuple[float, float, float]] = []
    middles: list[tuple[float, float, float]] = []
    for triangle in triangles:
        a, b, c = (nodes[one] for one in triangle)
        u = [b[axis] - a[axis] for axis in range(3)]
        v = [c[axis] - a[axis] for axis in range(3)]
        cross = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        size = math.sqrt(sum(one * one for one in cross))
        if size == 0:
            continue
        normals.append(tuple(one / size for one in cross))  # type: ignore[arg-type]
        middles.append(tuple((a[axis] + b[axis] + c[axis]) / 3 for axis in range(3)))  # type: ignore[arg-type]
    if len(normals) < 4:
        return Shape()

    mean = [sum(one[axis] for one in normals) / len(normals) for axis in range(3)]
    mean_size = math.sqrt(sum(one * one for one in mean))
    if mean_size > 0:
        unit = [one / mean_size for one in mean]
        worst = max(_angle(one, unit) for one in normals)
        if worst <= PLANE_DEGREES:
            return Shape(kind="plane")

    box = _bbox_center(nodes, members)
    # **구가 먼저다** — 구는 법선이 모든 방향을 향하므로 「가장 안 퍼진 축」 이 뜻을 갖지 않고,
    # 원통으로 잘못 읽힐 수 있다. 중심에서의 거리가 고르면 구다.
    ball = _sphere(nodes, members)
    if ball is not None:
        return Shape(kind="sphere", radius=ball, centroid=box)

    # 원통 · 원뿔이면 법선이 **축에 수직**이다 — 그래서 축은 법선들이 가장 안 퍼진 방향이다.
    matrix = [[sum(one[i] * one[j] for one in normals) for j in range(3)] for i in range(3)]
    axis = _smallest_eigenvector(matrix)

    # **반지름은 절점으로 맞춘다.** 삼각형 무게중심은 원통 **안쪽**에 있어서(내접 다각형)
    # 반지름이 작게 나온다 — 실측 2026-10-03: 요소 4 mm 에서 5.0 이 4.75 로 읽혔고, 그 차이로
    # 지문이 안 풀렸다. 절점은 gmsh 가 면 위에 놓으므로 그것이 정본이다.
    #
    # 원을 맞추는 것은 **반쪽 원통**(구멍의 절반 등) 때문이다. 축의 방향만 알고 중심을 면의
    # 무게중심으로 두면, 잘린 면에서는 중심이 축에서 비켜 있어 반지름이 틀어진다.
    flat = _project(nodes, members, axis)
    if len(flat) < 4:
        return Shape()
    radius = _circle_radius(flat)
    if radius is not None and radius > 0:
        return Shape(
            kind="cylinder",
            radius=radius,
            axis=(axis[0], axis[1], axis[2]),
            centroid=box,
        )
    # **원뿔은 축을 따라 반지름이 변한다.** 그 기울기가 뚜렷하고 잔차가 작으면 원뿔이다.
    # 반지름은 적지 않는다 — CAD 가 보내는 원뿔의 `radius` 가 어느 자리의 것인지 계약에 없어서,
    # 맞춰 보는 척하면 **엉뚱한 면에 붙는다.** 종류만 적어 평면 지문이 붙는 것을 막는다.
    if _is_cone(nodes, members, axis):
        return Shape(kind="cone", axis=(axis[0], axis[1], axis[2]), centroid=box)
    return Shape()


def _angle(first: tuple[float, float, float], second: list[float]) -> float:
    dot = max(-1.0, min(1.0, sum(first[axis] * second[axis] for axis in range(3))))
    return math.degrees(math.acos(dot))


def _bbox_center(
    nodes: dict[int, tuple[float, float, float]], members: set[int]
) -> tuple[float, float, float] | None:
    """절점들의 **경계상자 중심** — CAD 가 곡면의 중심으로 쓰는 정의다."""
    points = [nodes[node] for node in members if node in nodes]
    if not points:
        return None
    return tuple(  # type: ignore[return-value]
        (min(one[axis] for one in points) + max(one[axis] for one in points)) / 2
        for axis in range(3)
    )


def _sphere(nodes: dict[int, tuple[float, float, float]], members: set[int]) -> float | None:
    """구면 맞춤 — 반지름. 고르지 않으면 `None`.

    대수적 맞춤: `x²+y²+z² + Dx + Ey + Fz + G = 0` 은 네 미지수에 선형이다. **구를 먼저 가리는
    이유**는 구의 법선이 모든 방향을 향해서, 원통을 찾는 「가장 안 퍼진 축」 이 뜻을 갖지 않기
    때문이다 — 그대로 두면 구가 원통으로 읽힌다.
    """
    points = [nodes[node] for node in sorted(members) if node in nodes]
    if len(points) < 8:
        return None
    rows: list[list[float]] = [[0.0] * 4 for _ in range(4)]
    right = [0.0] * 4
    for point in points:
        basis = [point[0], point[1], point[2], 1.0]
        value = -(point[0] ** 2 + point[1] ** 2 + point[2] ** 2)
        for i in range(4):
            for j in range(4):
                rows[i][j] += basis[i] * basis[j]
            right[i] += basis[i] * value
    solved = _solve4(rows, right)
    if solved is None:
        return None
    d, e, f, g = solved
    center = (-d / 2, -e / 2, -f / 2)
    inside = center[0] ** 2 + center[1] ** 2 + center[2] ** 2 - g
    if inside <= 0:
        return None
    radius = math.sqrt(inside)
    spread = (
        math.sqrt(sum((math.dist(one, center) - radius) ** 2 for one in points) / len(points))
        / radius
    )
    return radius if spread <= CYLINDER_SPREAD else None


def _is_cone(
    nodes: dict[int, tuple[float, float, float]], members: set[int], axis: list[float]
) -> bool:
    """원뿔인가 — **축을 따라 반지름이 곧게 변하면** 그렇다.

    반지름을 돌려주지 않는다: CAD 가 보내는 원뿔의 `radius` 가 어느 자리의 것인지 계약에
    없어서,
    맞춰 보는 척하면 엉뚱한 면에 붙는다. 종류만 알면 **평면 지문이 곡면에 붙는 것**은 막는다.
    """
    points = [nodes[node] for node in sorted(members) if node in nodes]
    if len(points) < 8:
        return False
    # **원점은 축 위에 있어야 한다** — 첫 절점을 쓰면 그 점이 축에서 비켜 있어서 반지름이
    # 고리를 따라 요동치고, 원뿔이 「모르는 면」 으로 떨어진다(실측 2026-10-03). 전체 평균은
    # 꽉 찬 원뿔 · 원통에서 축 위에 놓인다. 잘린 면에서는 안 맞아 판정이 실패하는데, 그쪽은
    # **모른다고 두는 편이** 엉뚱한 종류로 적는 것보다 낫다.
    origin = tuple(
        sum(one[axis_index] for one in points) / len(points) for axis_index in range(3)
    )
    pairs: list[tuple[float, float]] = []
    for point in points:
        offset = [point[index] - origin[index] for index in range(3)]
        along = sum(offset[index] * axis[index] for index in range(3))
        radial = [offset[index] - along * axis[index] for index in range(3)]
        pairs.append((along, math.sqrt(sum(one * one for one in radial))))
    span = max(one[0] for one in pairs) - min(one[0] for one in pairs)
    if span <= 0:
        return False
    # 최소제곱 직선 — 반지름이 축 위치의 1차 함수인가.
    count = len(pairs)
    mean_x = sum(one[0] for one in pairs) / count
    mean_y = sum(one[1] for one in pairs) / count
    top = sum((one[0] - mean_x) * (one[1] - mean_y) for one in pairs)
    bottom = sum((one[0] - mean_x) ** 2 for one in pairs)
    if bottom == 0:
        return False
    slope = top / bottom
    if abs(slope) * span < CYLINDER_SPREAD * max(mean_y, 1e-9):
        # 기울기가 거의 0 이면 원통인데, 그쪽은 앞에서 이미 걸렀다 — 여기 오면 모르는 면이다.
        return False
    residual = math.sqrt(
        sum((one[1] - (mean_y + slope * (one[0] - mean_x))) ** 2 for one in pairs) / count
    )
    return residual <= CYLINDER_SPREAD * max(mean_y, 1e-9)


def _solve4(matrix: list[list[float]], right: list[float]) -> tuple[float, ...] | None:
    """4x4 선형계 — 가우스 소거. 특이하면 `None`(짐작하지 않는다)."""
    rows = [[*row, right[index]] for index, row in enumerate(matrix)]
    for column in range(4):
        pivot = max(range(column, 4), key=lambda index: abs(rows[index][column]))
        if abs(rows[pivot][column]) < 1e-12:
            return None
        rows[column], rows[pivot] = rows[pivot], rows[column]
        for index in range(4):
            if index == column:
                continue
            factor = rows[index][column] / rows[column][column]
            for j in range(column, 5):
                rows[index][j] -= factor * rows[column][j]
    return tuple(rows[index][4] / rows[index][index] for index in range(4))


def _project(
    nodes: dict[int, tuple[float, float, float]], members: set[int], axis: list[float]
) -> list[tuple[float, float]]:
    """절점을 **축에 수직한 평면**으로 눕힌다 — 거기서는 원통이 원이다."""
    first = [1.0, 0.0, 0.0]
    if abs(axis[0]) > 0.9:
        first = [0.0, 1.0, 0.0]
    u = _cross(axis, first)
    size = math.sqrt(sum(one * one for one in u))
    if size == 0:
        return []
    u = [one / size for one in u]
    v = _cross(axis, u)
    return [
        (
            sum(nodes[node][index] * u[index] for index in range(3)),
            sum(nodes[node][index] * v[index] for index in range(3)),
        )
        for node in sorted(members)
        if node in nodes
    ]


def _circle_radius(points: list[tuple[float, float]]) -> float | None:
    """평면 위 점들에 원을 맞춘다 — 반지름만 돌려준다. **고르지 않으면 `None`.**

    대수적 원 맞춤(Kåsa): `x² + y² + Dx + Ey + F = 0` 은 D · E · F 에 선형이라 3x3 한 번으로
    풀린다. 원통이 아니면 잔차가 커지므로 거기서 가려낸다 — 모르는 것을 원통이라고 적으면
    그 지문이 조용히 엉뚱한 면에 붙는다.
    """
    count = len(points)
    sum_x = sum(one[0] for one in points)
    sum_y = sum(one[1] for one in points)
    sum_xx = sum(one[0] ** 2 for one in points)
    sum_yy = sum(one[1] ** 2 for one in points)
    sum_xy = sum(one[0] * one[1] for one in points)
    sum_xr = sum(one[0] * (one[0] ** 2 + one[1] ** 2) for one in points)
    sum_yr = sum(one[1] * (one[0] ** 2 + one[1] ** 2) for one in points)
    sum_r = sum(one[0] ** 2 + one[1] ** 2 for one in points)
    matrix = [
        [sum_xx, sum_xy, sum_x],
        [sum_xy, sum_yy, sum_y],
        [sum_x, sum_y, float(count)],
    ]
    right = [-sum_xr, -sum_yr, -sum_r]
    solved = _solve3(matrix, right)
    if solved is None:
        return None
    d, e, f = solved
    center = (-d / 2, -e / 2)
    inside = center[0] ** 2 + center[1] ** 2 - f
    if inside <= 0:
        return None
    radius = math.sqrt(inside)
    spread = (
        math.sqrt(sum((math.dist(one, center) - radius) ** 2 for one in points) / count)
        / radius
    )
    return radius if spread <= CYLINDER_SPREAD else None


def _cross(first: list[float], second: list[float]) -> list[float]:
    return [
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    ]


def _solve3(
    matrix: list[list[float]], right: list[float]
) -> tuple[float, float, float] | None:
    """3x3 선형계 — 크라메르. 특이하면 `None`(짐작하지 않는다)."""

    def determinant(rows: list[list[float]]) -> float:
        return (
            rows[0][0] * (rows[1][1] * rows[2][2] - rows[1][2] * rows[2][1])
            - rows[0][1] * (rows[1][0] * rows[2][2] - rows[1][2] * rows[2][0])
            + rows[0][2] * (rows[1][0] * rows[2][1] - rows[1][1] * rows[2][0])
        )

    base = determinant(matrix)
    if abs(base) < 1e-12:
        return None
    found: list[float] = []
    for column in range(3):
        swapped = [row[:] for row in matrix]
        for index in range(3):
            swapped[index][column] = right[index]
        found.append(determinant(swapped) / base)
    return found[0], found[1], found[2]


def _smallest_eigenvector(matrix: list[list[float]]) -> list[float]:
    """대칭 3x3 의 **가장 작은 고윳값**의 고유벡터 — 야코비 회전 몇 번으로 끝난다.

    numpy 를 쓰지 않는다: 리눅스 워커에 없고, 이 한 가지를 위해 넣을 만한 꾸러미가 아니다
    (`vtp.py` 와 같은 판단이다).
    """
    a = [row[:] for row in matrix]
    vectors = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    for _ in range(50):
        # 비대각 중 가장 큰 자리를 없앤다.
        pivot = max((abs(a[i][j]), i, j) for i in range(3) for j in range(3) if i < j)
        size, i, j = pivot
        if size < 1e-12:
            break
        if a[i][i] == a[j][j]:
            angle = math.pi / 4
        else:
            angle = 0.5 * math.atan2(2 * a[i][j], a[i][i] - a[j][j])
        cos, sin = math.cos(angle), math.sin(angle)
        for k in range(3):
            first, second = a[k][i], a[k][j]
            a[k][i] = cos * first + sin * second
            a[k][j] = -sin * first + cos * second
        for k in range(3):
            first, second = a[i][k], a[j][k]
            a[i][k] = cos * first + sin * second
            a[j][k] = -sin * first + cos * second
        for k in range(3):
            first, second = vectors[k][i], vectors[k][j]
            vectors[k][i] = cos * first + sin * second
            vectors[k][j] = -sin * first + cos * second
    diagonal = [a[index][index] for index in range(3)]
    least = diagonal.index(min(diagonal))
    column = [vectors[row][least] for row in range(3)]
    size = math.sqrt(sum(one * one for one in column))
    return [one / size for one in column] if size else [0.0, 0.0, 1.0]


def _faces(
    nodes: dict[int, tuple[float, float, float]],
    elements: list[tuple[int, int, list[int]]],
) -> tuple[list[FaceRecord], dict[int, set[int]]]:
    """표면 삼각형을 면마다 모아 **면적 · 무게중심 · 법선**을 낸다.

    면적으로 가중한다 — 삼각형 크기가 고르지 않으므로 단순 평균을 쓰면 촘촘한 구석으로 중심이
    끌려간다. 법선도 같은 이유로 면적 가중이다(평면이면 어차피 같다).
    """
    area_of: dict[int, float] = defaultdict(float)
    center: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    normal: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    members: dict[int, set[int]] = defaultdict(set)
    for kind, entity, ids in elements:
        if kind not in TRIANGLE_KINDS:
            continue
        members[entity].update(ids)
        a, b, c = (nodes[one] for one in ids[:3])
        u = [b[axis] - a[axis] for axis in range(3)]
        v = [c[axis] - a[axis] for axis in range(3)]
        cross = [
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        ]
        twice = math.sqrt(sum(one * one for one in cross))
        if twice == 0:
            continue
        area = twice / 2
        area_of[entity] += area
        for axis in range(3):
            center[entity][axis] += area * (a[axis] + b[axis] + c[axis]) / 3
            normal[entity][axis] += cross[axis] / twice * area
    records: list[FaceRecord] = []
    rows = _triangles(elements)
    for entity, area in sorted(area_of.items()):
        size = math.sqrt(sum(one * one for one in normal[entity]))
        middle: tuple[float, float, float] = tuple(  # type: ignore[assignment]
            one / area for one in center[entity]
        )
        # **곡면이면 되맞춘다** — 지문이 반지름 · 축으로 면을 가리킨다(`_classify`).
        shape = _classify(nodes, rows.get(entity, []), members.get(entity, set()))
        records.append(
            FaceRecord(
                id=entity,
                # 곡면은 **CAD 와 같은 정의**(bbox 중심)로 맞춘다 — 평면은 면적 중심 그대로.
                centroid=shape.centroid or middle,
                area=area,
                surface=shape.kind,
                normal=(
                    tuple(one / size for one in normal[entity])  # type: ignore[arg-type]
                    if size
                    else None
                ),
                radius=shape.radius,
                axis=shape.axis,
            )
        )
    return records, dict(members)


def element_faces(mesh: Mesh) -> dict[frozenset[int], tuple[int, str]]:
    """모서리 절점 셋 → (요소 번호, 면 이름). **압력을 요소면에 걸 때** 쓴다.

    CalculiX 는 압력을 `요소, P번호, 값` 으로 받는다 — 면을 절점으로 가리키지 않는다. 그래서
    표면 삼각형을 요소의 어느 면인지로 되돌려야 한다. 면 번호를 틀리면 압력이 **엉뚱한 면에**
    걸리고, 그 결과는 오류 없이 그럴듯하게 나온다.
    """
    from app.core.calculix.deck import TET_FACES

    found: dict[frozenset[int], tuple[int, str]] = {}
    for rows in mesh.solids.values():
        for number, ids in rows:
            for name, corners in TET_FACES.items():
                key = frozenset(ids[one] for one in corners)
                found.setdefault(key, (number, name))
    return found


def tributary_areas(mesh: Mesh, faces: list[int]) -> dict[int, float]:
    """그 면들의 절점마다 **분담 면적** — 힘을 나눌 때 쓴다.

    고르게 나누면 모서리 절점이 과하게 받는다(2차 요소에서는 더 심하다). 삼각형 면적을 그
    절점들에 나눠 더하면, 적어도 **합력과 분포가 함께** 맞는다. 하중면 바로 아래의 응력은
    근사이므로(2차 요소의 일관 하중은 모서리에 0 을 준다) 그 자리를 보려면 Ansys 로 돌린다.
    """
    shares: dict[int, float] = {}
    for face in faces:
        for ring in mesh.face_rings.get(face, []):
            a, b, c = (mesh.nodes[one] for one in ring[:3])
            u = [b[axis] - a[axis] for axis in range(3)]
            v = [c[axis] - a[axis] for axis in range(3)]
            cross = [
                u[1] * v[2] - u[2] * v[1],
                u[2] * v[0] - u[0] * v[2],
                u[0] * v[1] - u[1] * v[0],
            ]
            area = math.sqrt(sum(one * one for one in cross)) / 2
            if area <= 0:
                continue
            # **그 요소면의 절점 전부에 나눈다**(2차면 여섯) — 모서리만 주면 분포가 거꾸로다.
            for node in ring:
                shares[node] = shares.get(node, 0.0) + area / len(ring)
    return shares


def _triangles(
    elements: list[tuple[int, int, list[int]]],
) -> dict[int, list[tuple[int, int, int]]]:
    """면마다 **모서리 셋만** 남긴 삼각형. 2차 요소의 중간 절점은 그림에 필요 없다."""
    found: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    for kind, entity, ids in elements:
        if kind in TRIANGLE_KINDS and len(ids) >= 3:
            found[entity].append((ids[0], ids[1], ids[2]))
    return dict(found)


def _rings(elements: list[tuple[int, int, list[int]]]) -> dict[int, list[list[int]]]:
    """면마다 표면 요소의 **절점 전부** — 1차면 셋, 2차면 여섯."""
    found: dict[int, list[list[int]]] = defaultdict(list)
    for kind, entity, ids in elements:
        if kind in TRIANGLE_KINDS and len(ids) >= 3:
            found[entity].append(list(ids))
    return dict(found)


def _bodies(
    nodes: dict[int, tuple[float, float, float]],
    solids: dict[int, list[tuple[int, list[int]]]],
) -> list[BodyRecord]:
    """솔리드마다 부피 · 무게중심 — **CAD 의 바디 이름을 붙이는 데 쓴다**(`match_bodies`).

    STEP 이 한글 이름을 망치므로 이름으로는 못 짝짓는다. 부피와 무게중심이 정본이다.
    """
    records: list[BodyRecord] = []
    for entity, rows in sorted(solids.items()):
        total = 0.0
        center = [0.0, 0.0, 0.0]
        for _, ids in rows:
            a, b, c, d = (nodes[one] for one in ids[:4])
            volume = _tet_volume(a, b, c, d)
            total += volume
            for axis in range(3):
                center[axis] += volume * (a[axis] + b[axis] + c[axis] + d[axis]) / 4
        if total <= 0:
            continue
        records.append(
            BodyRecord(
                index=entity,
                volume=total,
                centroid=tuple(one / total for one in center),  # type: ignore[arg-type]
            )
        )
    return records


def _tet_volume(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
    d: tuple[float, float, float],
) -> float:
    ab = [b[axis] - a[axis] for axis in range(3)]
    ac = [c[axis] - a[axis] for axis in range(3)]
    ad = [d[axis] - a[axis] for axis in range(3)]
    return (
        abs(
            ab[0] * (ac[1] * ad[2] - ac[2] * ad[1])
            - ab[1] * (ac[0] * ad[2] - ac[2] * ad[0])
            + ab[2] * (ac[0] * ad[1] - ac[1] * ad[0])
        )
        / 6
    )
