"""정적 해석 결과 — `.frd` 에서 **얼마나 밀리고 어디가 버거운가.**

**결과 모양은 Ansys 쪽과 같다**(`app/core/dpf/static.py`) — 화면이 그 열쇠를 읽는다. 변위는
`.frd` 의 `DISP` 블록, 상당응력은 `STRESS` 블록(성분 여섯)에서 낸다.

**0 인 결과는 「해석이 됐다」 처럼 보인다.** 그림도 표도 멀쩡하게 나오므로, 0 이면 그 사실을
경고로 적는다 — Ansys 쪽에서 쓴 것과 같은 말이다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.calculix import frd as frd_reader
from app.core.calculix import probes, vtp
from app.core.calculix.mesh import read_mesh
from app.core.spec import StaticSpec
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

RESULT_NAME = "result.json"
FRD_NAME = "model.frd"


def extract(spec: StaticSpec, workdir: Path, **_ignored: object) -> StageResult:
    """`model.frd` → `result.json` (+ 변형 그림)."""
    result_file = workdir / FRD_NAME
    if not result_file.is_file():
        raise StageFailure("solver_failed", f"결과 파일이 없습니다: {FRD_NAME}")

    blocks = frd_reader.read(result_file)
    # **마지막 증분을 읽는다.** 비선형 정적은 하중을 나눠 걸므로 `.frd` 에 증분마다 블록이
    # 쌓인다 — 첫 블록을 읽으면 **하중의 일부만** 걸린 상태가 나온다(실측 2026-10-03: 접착
    # 1.93e-4 대 마찰 3.35e-5, 비가 0.17 로 첫 증분이었다). 선형 정적은 블록이 하나라 같다.
    moved = next((one for one in reversed(blocks) if one.kind == "DISP"), None)
    if moved is None:
        raise StageFailure(
            "solver_failed", f"{FRD_NAME} 에 변위 블록이 없습니다 — 솔버 로그를 보세요."
        )
    magnitude = frd_reader.magnitudes(moved)
    max_displacement = round(max(magnitude.values(), default=0.0), 8)

    stressed = next((one for one in reversed(blocks) if one.kind == "STRESS"), None)
    # **못 읽으면 `None`** — 없는 값을 0 으로 적지 않는다(0 은 「응력이 없다」 로 읽힌다).
    max_von_mises: float | None = None
    if stressed is not None:
        values = frd_reader.von_mises(stressed)
        max_von_mises = round(max(values.values(), default=0.0), 6) or None

    result: dict[str, Any] = {
        "recipe": "static",
        "solver": "calculix",
        # 덱을 mm · tonne · N 으로 쓴다(`calculix/deck.py`) — 그래서 mm 와 MPa 다.
        "units": {"system": "ConsistentNMM", "displacement": "mm", "stress": "MPa"},
        "max_displacement": max_displacement,
        "max_von_mises": max_von_mises,
        "material": spec.material.name,
    }
    mesh_counts = _draw(workdir, moved, magnitude, result)
    # **측정점의 변위** — 전체 최대는 구속 모서리의 수치적 첨두일 수 있고, 센서는 그 자리에
    # 없다. 실측과 견줄 수 있는 값은 이쪽이다.
    spots = _probe(workdir, magnitude)
    if spots:
        result["probes"] = spots
    if mesh_counts:
        result["mesh"] = mesh_counts
    if max_displacement <= 0:
        result["warning"] = (
            "변형이 0 입니다 — 하중이 걸리지 않았거나 걸린 자리가 구속면과 같습니다."
        )

    path = workdir / RESULT_NAME
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts = [ArtifactSpec("result_json", path)]
    shape = workdir / "mode_01.vtp"
    if shape.is_file():
        artifacts.append(ArtifactSpec("mode_vtp", shape))
    return StageResult(
        artifacts=artifacts,
        summary={
            "solver": "calculix",
            "max_displacement": max_displacement,
            "max_von_mises": max_von_mises,
        },
        detail=(
            f"최대 변형 {max_displacement:.4g} mm"
            + (f" · 최대 응력 {max_von_mises:.4g} MPa" if max_von_mises else "")
        ),
    )


def _probe(workdir: Path, magnitude: dict[int, float]) -> list[dict[str, Any]]:
    """측정점의 변위(mm). 점 그룹이 없으면 빈 목록."""
    topology = workdir / "topology.json"
    msh = workdir / "model.msh"
    if not topology.is_file() or not msh.is_file():
        return []
    try:
        payload = json.loads(topology.read_text(encoding="utf-8"))
        if not probes.wanted(payload):
            return []
        mesh = read_mesh(msh)
    except Exception:  # pragma: no cover - 파일이 깨진 경우
        logger.warning("측정점을 못 읽었습니다 — 없이 갑니다", exc_info=True)
        return []
    return probes.read(payload, mesh.nodes, magnitude, unit="mm")


def _draw(
    workdir: Path,
    block: frd_reader.Block,
    magnitude: dict[int, float],
    result: dict[str, Any],
) -> dict[str, int]:
    """변형 그림 한 장(`mode_01.vtp`) — 모달의 모드 형상과 같은 길이라 화면이 그대로 읽는다.

    **못 그려도 해석은 끝난 것이다** — 그림이 없다고 결과를 버리지 않는다.
    """
    msh = workdir / "model.msh"
    if not msh.is_file():
        return {}
    try:
        mesh = read_mesh(msh)
        counts = vtp.write(
            workdir / "mode_01.vtp",
            nodes=mesh.nodes,
            triangles=mesh.triangles,
            displacement=block.values,
            magnitude=magnitude,
        )
    except Exception:  # pragma: no cover - 파일이 깨진 경우
        logger.warning("변형 그림을 못 만들었습니다 — 그림 없이 갑니다", exc_info=True)
        return {}
    result["shape"] = {"vtp": "mode_01.vtp", "points": counts["points"]}
    return {"nodes": len(mesh.nodes), "elements": mesh.element_count}
