"""모드 형상 — 표면 메시(VTP)와 썸네일(PNG).

## 왜 추출 시점에 만들어 두나

브라우저가 `.rst` 를 읽을 수는 없고, 서버가 세션을 들고 그려 주는 방식(trame 같은)은 **사용자당
서버 상태**를 만든다. 그러면 사용자가 창을 닫은 것과 서버가 죽은 것을 구별할 수 없다. 한 번
만들어 정적으로 내려주면 그 상태가 아예 없다(로드맵의 결정).

## 무엇을 줄이나 (실측 2026-09-20)

- **표면만.** 속의 요소는 안 보이는데 절점 수의 대부분을 차지한다(503 → 458, 큰 모델일수록
  차이가 크다).
- **중간 절점을 뺀다.** 2차 요소의 중간 절점은 브라우저가 못 그린다 — 삼각형으로 바꾸며 버린다.
- **너무 촘촘하면 솎는다.** 작은 모델은 손대지 않는다 — 78점짜리를 더 줄이면 모양이 사라진다.

## PNG 는 왜 따로 만드나

목록에서 모드를 고르기 전에 **무엇이 있는지 보여야 한다.** 3D 뷰어를 열두 번 띄워 고르게 하면
아무도 안 고른다. 썸네일은 변위를 과장해 그린다 — 실제 크기로 그리면 아무것도 안 움직인 그림이
나온다(모달의 변위는 질량 정규화된 상대값이다).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 이보다 면이 많으면 솎는다. 작은 모델을 줄이면 모양이 사라지고, 큰 모델을 안 줄이면
#: 브라우저가 멈춘다 — 둘 다 「뷰어가 이상하다」 로 온다.
DECIMATE_ABOVE_CELLS = 20_000
#: 솎은 뒤 목표 면 수.
TARGET_CELLS = 20_000

#: 썸네일 크기. 목록에 여러 장이 깔리므로 크게 만들 이유가 없다.
THUMBNAIL_SIZE = (480, 360)

#: 썸네일에서 변위를 모델 크기의 몇 배로 과장하나.
WARP_RATIO = 0.15


def export_mode(
    model: Any,
    skin_mesh: Any,
    mode: int,
    workdir: Path,
    *,
    thumbnail: bool = True,
) -> dict[str, Any]:
    """모드 하나의 VTP(+PNG)를 만들고 파일 이름과 최대 변위를 돌려준다."""
    import numpy as np

    surface = _surface_with_displacement(model, skin_mesh, mode)
    magnitude = surface.point_data["magnitude"]
    max_displacement = float(np.max(magnitude)) if len(magnitude) else 0.0

    vtp = workdir / f"mode_{mode:02d}.vtp"
    # 바이너리로 쓴다. 화면(vtk.js)이 그대로 읽는다 — ASCII 는 두 배 크기다
    # (실측 7.8KB / 14.6KB).
    surface.save(str(vtp))

    made: dict[str, Any] = {
        "vtp": vtp.name,
        "max_displacement": max_displacement,
        "points": int(surface.n_points),
        "faces": int(surface.n_cells),
    }
    if thumbnail:
        png = _thumbnail(surface, workdir / f"mode_{mode:02d}.png", max_displacement)
        if png is not None:
            made["png"] = png.name
    return made


def skin_of(mesh: Any) -> Any:
    """겉면만 남긴 메시. 실패하면 원본 그대로 — **그림이 없는 것보다 무거운 그림이 낫다.**"""
    from ansys.dpf import core as dpf

    try:
        return dpf.operators.mesh.skin(mesh=mesh).outputs.mesh()
    except Exception:  # pragma: no cover - 형상에 따라 실패할 수 있다
        logger.warning("표면 추출 실패 — 전체 메시로 그립니다", exc_info=True)
        return mesh


def _surface_with_displacement(model: Any, skin_mesh: Any, mode: int) -> Any:
    import numpy as np

    displacement = model.results.displacement.on_time_scoping([mode]).eval()[0]

    # **절점 번호로 맞춘다.** 변위 필드의 순서는 메시의 절점 순서와 다르다(실측: 메시는
    # 1·2·3…, 필드는 1·137·129…). 순서대로 붙이면 모양이 뒤죽박죽인 그림이 나오는데,
    # 그것은 「이상한 모드 형상」 처럼 보일 뿐 오류로 드러나지 않는다.
    node_ids = np.asarray(skin_mesh.nodes.scoping.ids)
    field_ids = np.asarray(displacement.scoping.ids)
    values = np.asarray(displacement.data)
    lookup = np.full(int(max(field_ids.max(), node_ids.max())) + 1, -1, dtype=np.int64)
    lookup[field_ids] = np.arange(len(field_ids))
    picked = lookup[node_ids]
    vectors = np.zeros((len(node_ids), 3), dtype=float)
    found = picked >= 0
    vectors[found] = values[picked[found]]

    grid = skin_mesh.grid
    grid.point_data["displacement"] = vectors
    grid.point_data["magnitude"] = np.linalg.norm(vectors, axis=1)

    # 중간 절점을 버리고(브라우저가 못 그린다) 삼각형으로.
    linear = grid.linear_copy() if hasattr(grid, "linear_copy") else grid
    surface = linear.extract_surface(algorithm="dataset_surface").triangulate()
    if surface.n_cells > DECIMATE_ABOVE_CELLS:
        reduction = 1.0 - TARGET_CELLS / surface.n_cells
        surface = surface.decimate_pro(reduction)
    # 솎기가 남기는 보조 배열은 화면에 쓸모가 없다 — 파일만 키운다.
    surface.point_data.pop("vtkOriginalPointIds", None)
    surface.cell_data.pop("vtkOriginalCellIds", None)
    return surface


def _thumbnail(surface: Any, path: Path, max_displacement: float) -> Path | None:
    """변위를 과장해 그린 한 장. **실패해도 해석을 실패시키지 않는다** — 그림은 곁들이다."""
    try:
        import pyvista as pv

        if max_displacement <= 0:
            return None
        bounds = surface.bounds
        span = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4])
        scale = WARP_RATIO * span / max_displacement

        warped = surface.copy()
        warped.points = surface.points + surface.point_data["displacement"] * scale
        warped.point_data["magnitude"] = surface.point_data["magnitude"]

        plotter = pv.Plotter(off_screen=True, window_size=list(THUMBNAIL_SIZE))
        plotter.add_mesh(warped, scalars="magnitude", cmap="viridis", show_scalar_bar=False)
        # 원래 모양을 옅게 겹친다 — **무엇이 얼마나 움직였는지**는 견줄 것이 있어야 보인다.
        plotter.add_mesh(surface, color="lightgray", opacity=0.15)
        plotter.view_isometric()
        plotter.screenshot(str(path))
        plotter.close()
        return path
    except Exception:
        logger.warning("모드 썸네일 생성 실패 — 그림 없이 갑니다", exc_info=True)
        return None
