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

## 단위

형상은 **늘 mm** 다(CompCore 계약). 그래서 메시도 mm 이고, 덱은 mm · tonne · N (MPa) 로 쓴다 —
Ansys 쪽 `ConsistentNMM` 과 같은 계라 주파수가 Hz, 변위가 mm 로 나온다.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
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
    #: 면 번호 → 그 면의 삼각형들. 압력 하중이 면마다 요소면을 적을 때 쓴다.
    face_triangles: dict[int, list[tuple[int, int, int]]]
    second_order: bool

    @property
    def element_count(self) -> int:
        return sum(len(rows) for rows in self.solids.values())


def build_mesh(
    step: Path,
    workdir: Path,
    *,
    element_size_mm: float,
    second_order: bool = True,
    timeout_seconds: int = 1800,
) -> Mesh:
    """gmsh 를 불러 메시를 만들고 읽는다. `.geo` 와 `.msh` 가 작업 폴더에 남는다."""
    geo = workdir / "model.geo"
    msh = workdir / "model.msh"
    geo.write_text(_geo(step, element_size_mm, second_order), encoding="utf-8")
    done = tools.run(
        tools.gmsh_bin(),
        [str(geo), "-3", "-o", str(msh), "-nopopup", "-v", "2"],
        cwd=workdir,
        timeout_seconds=timeout_seconds,
        what="gmsh",
    )
    if not msh.is_file():
        tail = (done.stdout or "")[-1500:] + (done.stderr or "")[-1500:]
        raise StageFailure("mesh_failed", f"gmsh 가 메시를 못 만들었습니다:\n{tail}")
    return read_mesh(msh)


def _geo(step: Path, size: float, second_order: bool) -> str:
    """gmsh 에게 줄 쪽지. **`.geo` 파일이 경계다** — 파이썬 API 를 안 쓴다(`tools` 참고)."""
    return (
        "\n".join(
            [
                'SetFactory("OpenCASCADE");',
                f'v() = ShapeFromFile("{step}");',
                # 맞닿은 면을 하나로 — 절점을 공유해야 붙은 모델이 된다.
                "BooleanFragments{ Volume{:}; Delete; }{}",
                f"Mesh.MeshSizeMax = {size:g};",
                f"Mesh.MeshSizeMin = {size / 4:g};",
                f"Mesh.ElementOrder = {2 if second_order else 1};",
                # 물리 그룹을 안 만들어도 전부 저장한다 — 우리는 기하 번호로 찾는다.
                "Mesh.SaveAll = 1;",
                "Mesh.MshFileVersion = 2.2;",
            ]
        )
        + "\n"
    )


def read_mesh(msh: Path) -> Mesh:
    """`.msh`(2.2) 를 읽어 절점 · 요소 · 면 지문 · 바디 지문을 낸다."""
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
    if not solids:
        raise StageFailure(
            "mesh_failed", "메시에 사면체가 없습니다 — 형상이 솔리드인지 보세요."
        )
    faces, face_nodes = _faces(nodes, elements)
    by_face = _triangles(elements)
    return Mesh(
        nodes=nodes,
        solids=dict(solids),
        faces=faces,
        bodies=_bodies(nodes, solids),
        face_nodes=face_nodes,
        triangles=[one for rows in by_face.values() for one in rows],
        face_triangles=by_face,
        second_order=second_order,
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
    for entity, area in sorted(area_of.items()):
        size = math.sqrt(sum(one * one for one in normal[entity]))
        records.append(
            FaceRecord(
                id=entity,
                centroid=tuple(one / area for one in center[entity]),  # type: ignore[arg-type]
                area=area,
                surface="",
                normal=(
                    tuple(one / size for one in normal[entity])  # type: ignore[arg-type]
                    if size
                    else None
                ),
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
        for triangle in mesh.face_triangles.get(face, []):
            a, b, c = (mesh.nodes[one] for one in triangle)
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
            members = [one for one in triangle]
            for node in members:
                shares[node] = shares.get(node, 0.0) + area / len(members)
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
