"""조화 응답 결과 — `.frd` 에서 **주파수마다 진폭.**

CalculiX 는 주파수 하나에 블록을 **둘** 적는다(실측 2026-10-03): `DISP` 가 실수부,
`DISPI` 가 허수부다. 진폭은 성분마다 둘을 합쳐 크기를 낸다 —

    진폭 = √( Σ (실수부² + 허수부²) )

**실수부만 읽으면 안 된다.** 위상에 따라 작게 나오고 공진이 평평해 보인다 — Ansys 쪽에서
진폭 연산자를 쓰기로 한 것과 같은 이유다.

결과 모양은 Ansys 쪽과 같다(`app/core/dpf/harmonic.py`) — 화면(`HarmonicResult`)이 그 열쇠를
읽는다. **감쇠비는 모델링이 남긴 `boundary.json` 에서 읽는다**: CAD 가 적어 보낸 값이 스펙을
이길 수 있고, 그때 결과에 스펙 값을 적으면 화면이 거짓말을 한다(봉우리 높이는 1/2ζ 로 읽힌다).
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from app.core import probes as core_probes
from app.core.calculix import frd as frd_reader
from app.core.calculix import probes
from app.core.calculix.mesh import read_mesh
from app.core.spec import HarmonicSpec
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

RESULT_NAME = "result.json"
FRD_NAME = "model.frd"
BOUNDARY_NAME = "boundary.json"
MSH_NAME = "model.msh"
TOPOLOGY_NAME = "topology.json"

#: 이보다 크면 「감쇠가 모자란 것 아닌가」 를 적어 둔다(mm). Ansys 쪽과 같은 문턱.
SUSPICIOUS_DISPLACEMENT = 1e3


def extract(spec: HarmonicSpec, workdir: Path, **_ignored: object) -> StageResult:
    """`model.frd` → `result.json` (주파수 곡선)."""
    result_file = workdir / FRD_NAME
    if not result_file.is_file():
        raise StageFailure("solver_failed", f"결과 파일이 없습니다: {FRD_NAME}")

    real: dict[float, frd_reader.Block] = {}
    imaginary: dict[float, frd_reader.Block] = {}
    for block in frd_reader.read(result_file):
        if block.kind == "DISP":
            real[block.value] = block
        elif block.kind == "DISPI":
            imaginary[block.value] = block

    # **측정점은 그 자리의 곡선을 만든다.** 전체 최대의 곡선과 봉우리 주파수가 다를 수 있고
    # (최대가 나는 자리가 주파수마다 옮겨 다닌다), 센서는 한 자리에 붙어 있다 — 실측과 견줄
    # 수 있는 것은 그쪽이다.
    spots = _spots(workdir)
    points: list[dict[str, Any]] = []
    for value in sorted(real):
        other = imaginary.get(value)
        if other is None:
            # 짝이 없는 블록은 **버린다** — 실수부만으로 진폭을 지어내면 공진이 평평해진다.
            continue
        row: dict[str, Any] = {
            "frequency_hz": round(value, 4),
            "max_displacement": round(_amplitude(real[value], other), 10),
        }
        if spots:
            row["probes"] = {
                spot.name: round(_at_node(real[value], other, spot.node), 10) for spot in spots
            }
        points.append(row)
    if not points:
        raise StageFailure(
            "solver_failed",
            f"{FRD_NAME} 에 주파수 점이 없습니다 — 솔버 로그를 보세요.",
        )

    damping = _damping(spec, workdir)
    worst = max(points, key=lambda one: one["max_displacement"])
    result: dict[str, Any] = {
        "recipe": "harmonic",
        "solver": "calculix",
        # 덱을 mm · tonne · N 으로 쓴다(`calculix/deck.py`).
        "units": {"frequency": "Hz", "displacement": "mm", "system": "ConsistentNMM"},
        "damping_ratio": damping,
        "points": points,
        "peak": worst,
        "material": spec.material.name,
        **({"mesh": _mesh(workdir)} if _mesh(workdir) else {}),
    }
    # **측정점마다 그 자리의 봉우리 한 줄** — 절점 거리와 「멀다」 경고가 여기 실린다.
    tops = core_probes.peaks(spots, points, unit="mm")
    if tops:
        result["probes"] = tops
    if worst["max_displacement"] > SUSPICIOUS_DISPLACEMENT:
        result["warning"] = (
            f"공진 응답이 {worst['max_displacement']:.3g} 로 큽니다 — "
            f"감쇠비({damping})가 실제보다 작지 않은지 보세요."
        )

    path = workdir / RESULT_NAME
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return StageResult(
        artifacts=[ArtifactSpec("result_json", path)],
        summary={
            "solver": "calculix",
            "frequency_points": len(points),
            "peak_hz": worst["frequency_hz"],
            "peak_displacement": worst["max_displacement"],
            "damping_ratio": damping,
        },
        detail=(
            f"{len(points)}점 · 최대 {worst['max_displacement']:.4g} mm @ "
            f"{worst['frequency_hz']:.1f} Hz"
        ),
    )


def _spots(workdir: Path) -> list[probes.Spot]:
    """측정점마다 **가장 가까운 절점**. 점 그룹이 없으면 빈 것.

    절점을 한 번만 찾아 둔다 — 주파수마다 다시 찾으면 같은 일을 수백 번 한다.
    """
    topology = workdir / TOPOLOGY_NAME
    msh = workdir / MSH_NAME
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
    return probes.locate(
        payload, mesh.nodes, body_nodes=probes.body_nodes(workdir, mesh.solids)
    )


def _at_node(real: frd_reader.Block, imaginary: frd_reader.Block, node: int) -> float:
    """그 절점의 진폭 — 실수부 · 허수부를 성분마다 합쳐 크기를 낸다."""
    values = real.values.get(node)
    other = imaginary.values.get(node)
    if values is None or other is None or len(values) < 3 or len(other) < 3:
        return 0.0
    return math.sqrt(sum(values[axis] ** 2 + other[axis] ** 2 for axis in range(3)))


def _amplitude(real: frd_reader.Block, imaginary: frd_reader.Block) -> float:
    """그 주파수의 **최대 진폭** — 절점마다 복소 크기를 내고 가장 큰 것."""
    best = 0.0
    for node, values in real.values.items():
        other = imaginary.values.get(node)
        if other is None or len(values) < 3 or len(other) < 3:
            continue
        size = math.sqrt(sum(values[axis] ** 2 + other[axis] ** 2 for axis in range(3)))
        best = max(best, size)
    return best


def _damping(spec: HarmonicSpec, workdir: Path) -> float:
    """**실제로 덱에 실린 감쇠비.** 모델링이 남긴 파일이 정본이고, 없으면 스펙으로 본다."""
    path = workdir / BOUNDARY_NAME
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            value = loaded.get("damping_ratio")
            if isinstance(value, int | float):
                return float(value)
        except (OSError, ValueError):
            logger.warning("%s 를 읽지 못했습니다 — 스펙으로 봅니다", BOUNDARY_NAME)
    return spec.damping_ratio


def _mesh(workdir: Path) -> dict[str, int]:
    """메시 크기 — `.msh` 의 머리에서 센다. 없으면 비워 둔다(지어내지 않는다)."""
    import re

    msh = workdir / MSH_NAME
    if not msh.is_file():
        return {}
    text = msh.read_text(encoding="utf-8", errors="replace")
    found: dict[str, int] = {}
    nodes = re.search(r"\$Nodes\s*\n\s*(\d+)", text)
    elements = re.search(r"\$Elements\s*\n\s*(\d+)", text)
    if nodes:
        found["nodes"] = int(nodes.group(1))
    if elements:
        found["elements"] = int(elements.group(1))
    return found
