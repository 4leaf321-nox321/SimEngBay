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

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def write(
    path: Path,
    *,
    nodes: dict[int, tuple[float, float, float]],
    triangles: list[tuple[int, int, int]],
    displacement: dict[int, list[float]],
    magnitude: dict[int, float],
) -> dict[str, int]:
    """표면 삼각형 + 변위를 `.vtp` 로 쓴다. 쓰인 점 · 면 수를 돌려준다."""
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
    connect = " ".join(
        f"{order[a]} {order[b]} {order[c]}" for a, b, c in triangles if _all_in(order, a, b, c)
    )
    offsets = " ".join(str(3 * (index + 1)) for index in range(len(triangles)))

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


def _all_in(order: dict[int, int], *nodes: int) -> bool:
    return all(node in order for node in nodes)
