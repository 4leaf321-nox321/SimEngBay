"""모드 형상 파일(`.vtp`)을 **손으로 쓴다.**

## 왜 손으로

Ansys 쪽은 pyvista 가 그린다(`app/core/dpf/shapes.py`). 리눅스 워커에는 그 꾸러미가 없고,
넣으면
vtk 까지 따라와 배포 이미지가 백 메가 단위로 커진다 — **쓰는 것은 XML 한 장**이라 그 값을 치를
이유가 없다. 화면(vtk.js)이 보는 것은 세 가지뿐이다: 점 좌표, 삼각형, 그리고 점마다의
`displacement`(3성분) · `magnitude`(1성분). 그 이름이 계약이다(`shared/viewer/MeshViewer.tsx`).

ASCII 로 쓴다. 바이너리가 절반 크기지만(실측 7.8KB 대 14.6KB) 메시가 작고, 사람이 열어 볼 수
있는 편이 낫다 — 값이 수상할 때 그 파일이 증거가 된다.

## 껍데기만 쓴다

솔리드 내부 절점은 화면에 안 보이므로 **표면 삼각형만** 쓴다. 그 삼각형은 gmsh 가 이미 냈다
(`mesh.py` 가 면마다 모아 둔 것과 같은 요소들) — 2차 요소의 중간 절점은 버리고 모서리 셋만
쓴다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from app.core import surface_parts

if TYPE_CHECKING:
    from app.core.calculix.mesh import Mesh

logger = logging.getLogger(__name__)

#: 모델링이 추출에 넘기는 파일 — 바디 이름 → 기하 부피 번호, 쉘 면 → 파트 이름(`build.py`).
BOUNDARY_NAME = "boundary.json"


def write(
    path: Path,
    *,
    nodes: dict[int, tuple[float, float, float]],
    triangles: list[tuple[int, int, int]],
    displacement: dict[int, list[float]],
    magnitude: dict[int, float],
    parts: list[int] | None = None,
) -> dict[str, int]:
    """표면 삼각형 + 변위를 `.vtp` 로 쓴다. 쓰인 점 · 면 수를 돌려준다.

    `parts` 가 있으면(삼각형마다 파트 번호) 셀 배열 `part` 로 적는다 — 화면이 파트마다
    보이기 · 숨기기를 한다(`surface_parts`).
    """
    known = set(nodes)
    kept = [
        index
        for index, (a, b, c) in enumerate(triangles)
        if a in known and b in known and c in known
    ]
    triangles = [triangles[index] for index in kept]
    if parts is not None:
        parts = [parts[index] for index in kept]
    used = sorted({node for triangle in triangles for node in triangle})
    order = {node: index for index, node in enumerate(used)}

    points = " ".join(
        f"{nodes[node][0]:.6g} {nodes[node][1]:.6g} {nodes[node][2]:.6g}" for node in used
    )
    vectors = " ".join(
        "{:.6g} {:.6g} {:.6g}".format(*(displacement.get(node) or (0.0, 0.0, 0.0))[:3])
        for node in used
    )
    scalars = " ".join(f"{magnitude.get(node, 0.0):.6g}" for node in used)
    connect = " ".join(f"{order[a]} {order[b]} {order[c]}" for a, b, c in triangles)
    offsets = " ".join(str(3 * (index + 1)) for index in range(len(triangles)))
    cell_data = (
        [
            "      <CellData>",
            '        <DataArray type="Int32" Name="part" format="ascii">',
            "          " + " ".join(str(one) for one in parts),
            "        </DataArray>",
            "      </CellData>",
        ]
        if parts is not None
        else []
    )

    path.write_text(
        "\n".join(
            [
                '<?xml version="1.0"?>',
                '<VTKFile type="PolyData" version="0.1" byte_order="LittleEndian">',
                "  <PolyData>",
                f'    <Piece NumberOfPoints="{len(used)}" NumberOfPolys="{len(triangles)}">',
                "      <Points>",
                '        <DataArray type="Float32" NumberOfComponents="3" format="ascii">',
                f"          {points}",
                "        </DataArray>",
                "      </Points>",
                "      <PointData>",
                '        <DataArray type="Float32" Name="displacement" '
                'NumberOfComponents="3" format="ascii">',
                f"          {vectors}",
                "        </DataArray>",
                '        <DataArray type="Float32" Name="magnitude" format="ascii">',
                f"          {scalars}",
                "        </DataArray>",
                "      </PointData>",
                *cell_data,
                "      <Polys>",
                '        <DataArray type="Int32" Name="connectivity" format="ascii">',
                f"          {connect}",
                "        </DataArray>",
                '        <DataArray type="Int32" Name="offsets" format="ascii">',
                f"          {offsets}",
                "        </DataArray>",
                "      </Polys>",
                "    </Piece>",
                "  </PolyData>",
                "</VTKFile>",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {"points": len(used), "faces": len(triangles)}


def parted(
    mesh: Mesh, workdir: Path
) -> tuple[list[tuple[int, int, int]], list[int] | None, list[str]]:
    """표면 삼각형을 파트마다 — (삼각형들, 삼각형마다 파트 번호, 파트 이름들).

    파트는 바디(기하 부피) 순서, 그다음 쉘 파트다. 이름은 모델링이 짝지은 것(`boundary.json`
    의 `bodies` · `shells.parts`) — 없으면 `solidN` · `쉘 N`. 두 바디가 맞닿은 삼각형은 둘 다에
    한 번씩 쓴다. 파트가 하나뿐이면 나누지 않는다(`None`) — 고를 것이 없다.
    """
    path = workdir / BOUNDARY_NAME
    boundary: dict[str, object] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            boundary = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            logger.warning("%s 를 읽지 못했습니다 — 파트 이름 없이 나눕니다", BOUNDARY_NAME)
    bodies = boundary.get("bodies")
    name_of = {
        int(entity): str(name)
        for name, entity in (bodies.items() if isinstance(bodies, dict) else [])
        if isinstance(entity, int)
    }
    order = sorted(mesh.solids)
    names = [name_of.get(entity, f"solid{entity}") for entity in order]
    index_of = {entity: index for index, entity in enumerate(order)}

    shells = boundary.get("shells")
    shells = shells if isinstance(shells, dict) else {}
    shell_names = {int(key): str(value) for key, value in (shells.get("parts") or {}).items()}
    shell_of: dict[tuple[int, ...], int] = {}
    for surface in sorted(int(one) for one in shells.get("surfaces") or []):
        # 쉘 파트 하나가 중간면 여럿(꺾인 판)이다 — 같은 이름은 한 파트로 묶는다.
        name = shell_names.get(surface, f"쉘 {surface}")
        if name not in names:
            names.append(name)
        for triangle in mesh.face_triangles.get(surface, []):
            shell_of[tuple(sorted(triangle))] = names.index(name)

    owners = surface_parts.owners_by_solid(mesh.solids, mesh.triangles)
    out: list[tuple[int, int, int]] = []
    parts: list[int] = []
    other: int | None = None
    for triangle, found in zip(mesh.triangles, owners, strict=True):
        ids = [index_of[entity] for entity in found if entity in index_of]
        if not ids and (shell := shell_of.get(tuple(sorted(triangle)))) is not None:
            ids = [shell]
        if not ids:
            if other is None:
                names.append("기타")
                other = len(names) - 1
            ids = [other]
        for one in ids:
            out.append(triangle)
            parts.append(one)
    if len(names) < 2:
        return list(mesh.triangles), None, []
    return out, parts, names
