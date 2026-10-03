"""조화 응답 결과 — `.rst` → 주파수별 응답.

모달은 「어느 주파수에서 떠는가」, 정적은 「얼마나 밀리나」 였다. 조화 응답은 **그 사이**다:
주파수를 훑으며 **각 주파수에서 얼마나 크게 흔들리는가.**

그래서 결과가 **곡선**이다 — 주파수 하나하나에 최대 변위가 붙는다. 화면이 그것을 그려야
공진이 어디서 얼마나 뾰족한지 보인다.

## 감쇠가 없으면 무한대가 나온다

감쇠비가 0 이면 공진점에서 응답이 끝없이 커진다. 스펙이 그것을 막지만(0 을 안 받는다),
값이 터무니없이 크면 여기서도 적어 둔다 — **큰 수는 그럴듯해 보인다.**
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core import probes as core_probes
from app.core.dpf import probes
from app.core.spec import HarmonicSpec
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

RESULT_NAME = "result.json"
#: 모델링이 남긴 한 줄 — **실제로 쓴 감쇠비**가 거기 있다.
BOUNDARY_NAME = "boundary.json"


def _damping(spec: HarmonicSpec, workdir: Path) -> float:
    """실제로 덱에 실린 감쇠비. **모델링이 남긴 파일이 정본이다.**

    CAD 가 해석 설정에 감쇠비를 적어 보내면 그것이 스펙을 이긴다 — 그때 결과에 스펙 값을
    적으면 화면이 거짓말을 한다. 봉우리 높이를 그 값으로 읽는 사람에게는 치명적이다
    (봉우리는 1/2ζ 에 비례한다). 파일이 없으면(옛 작업) 스펙으로 본다.
    """
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


#: 이보다 크면 「감쇠가 모자란 것 아닌가」 를 적어 둔다(선언된 계의 길이 단위).
SUSPICIOUS_DISPLACEMENT = 1e3


def extract(
    spec: HarmonicSpec, workdir: Path, *, result_name: str = "file.rst"
) -> StageResult:
    """주파수마다 최대 변위를 읽어 `result.json` 에 곡선으로 남긴다."""
    damping = _damping(spec, workdir)
    rst = workdir / result_name
    if not rst.is_file():
        raise StageFailure("solver_failed", f"결과 파일이 없습니다: {result_name}")

    try:
        import numpy as np
        from ansys.dpf import core as dpf
    except ImportError as failure:
        raise StageFailure(
            "internal",
            "PyDPF 가 이 파이썬에 없습니다 — 워커 환경(SIMULATION_EXECUTOR)을 확인하세요.",
        ) from failure

    try:
        model = dpf.Model(str(rst))
        support = model.metadata.time_freq_support
        frequencies = [float(one) for one in support.time_frequencies.data]
        mesh = model.metadata.meshed_region
        system = str(model.metadata.result_info.unit_system_name)
        unit = str(support.time_frequencies.unit or "Hz")

        points: list[dict[str, Any]] = []
        spots = _spots(mesh, probes.topology_of(workdir))
        # **변위에 단위를 달아 둔다** — 값만 보면 mm 와 m 가 구별되지 않는다(정적에서 겪었다).
        displacement_unit = ""
        for index, value in enumerate(frequencies, start=1):
            peak, displacement_unit = _amplitude(dpf, np, model, index)
            row: dict[str, Any] = {
                "frequency_hz": round(value, 4),
                "max_displacement": peak,
            }
            if spots:
                # **측정점의 곡선** — 주파수마다 그 자리의 응답. 전체 최대는 자리가 주파수마다
                # 옮겨 다닐 수 있고, 센서는 한 자리에 붙어 있다.
                row["probes"] = _at_spots(
                    dpf, np, model, index, {spot.name: spot.node for spot in spots}
                )
            points.append(row)
    except StageFailure:
        raise
    except Exception as failure:
        raise StageFailure("internal", f"결과 파일을 읽지 못했습니다: {failure}") from failure

    if not points:
        raise StageFailure("solver_failed", "결과 파일에 주파수 점이 없습니다.")

    worst = max(points, key=lambda one: one["max_displacement"])
    result: dict[str, Any] = {
        "recipe": "harmonic",
        "units": {"frequency": unit, "displacement": displacement_unit, "system": system},
        "mesh": {"nodes": int(mesh.nodes.n_nodes), "elements": int(mesh.elements.n_elements)},
        "damping_ratio": damping,
        "points": points,
        "peak": worst,
        "material": spec.material.name,
    }
    # **측정점마다 그 자리의 봉우리 한 줄** — 절점 거리와 「멀다」 경고가 여기 실린다.
    tops = core_probes.peaks(spots, points, unit=displacement_unit)
    if tops:
        result["probes"] = tops
    if worst["max_displacement"] > SUSPICIOUS_DISPLACEMENT:
        # **큰 수는 그럴듯해 보인다** — 감쇠가 모자라면 공진에서 수가 치솟는다.
        result["warning"] = (
            f"공진 응답이 {worst['max_displacement']:.3g} 로 큽니다 — "
            f"감쇠비({damping})가 실제보다 작지 않은지 보세요."
        )

    path = workdir / RESULT_NAME
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return StageResult(
        artifacts=[ArtifactSpec("result_json", path)],
        summary={
            "frequency_points": len(points),
            "peak_hz": worst["frequency_hz"],
            "peak_displacement": worst["max_displacement"],
        },
        detail=(
            f"{len(points)}점 · 최대 {worst['max_displacement']:.4g} @ "
            f"{worst['frequency_hz']:.1f} {unit}"
        ),
    )


def _spots(mesh: Any, topology: dict[str, Any]) -> list[probes.Spot]:
    """측정점마다 **가장 가까운 절점**. 주파수마다 다시 찾으면 같은 일을 수백 번 한다."""
    try:
        scale = probes.scale_for(str(mesh.unit or ""))
    except Exception:  # pragma: no cover - DPF 없이는 안 돈다
        scale = 1.0
    found = probes.locate(topology, mesh, scale=scale)
    for spot in found:
        if spot.distance_mm > probes.FAR_MM:
            logger.warning(
                "측정점 %s: 가장 가까운 절점이 %.2f mm 떨어져 있습니다",
                spot.name,
                spot.distance_mm,
            )
    return found


def _at_spots(
    dpf: Any, np: Any, model: Any, index: int, spots: dict[str, int]
) -> dict[str, float]:
    """그 주파수에서 측정점마다 진폭. 복소 결과라 **진폭 연산자**를 쓴다(실수부만 읽으면
    위상에 따라 작게 나온다 — `_amplitude` 와 같은 이유다)."""
    fields = model.results.displacement.on_time_scoping([index]).eval()
    try:
        field = dpf.operators.math.amplitude_fc(fields_container=fields).eval()[0]
    except Exception:
        field = fields[0]
    ids = np.asarray(field.scoping.ids, dtype=int)
    data = np.asarray(field.data, dtype=float)
    size = np.linalg.norm(data, axis=1) if data.ndim == 2 else np.abs(data)
    by_node = dict(zip(ids.tolist(), size.tolist(), strict=False))
    return {name: round(float(by_node.get(node, 0.0)), 10) for name, node in spots.items()}


def _amplitude(dpf: Any, np: Any, model: Any, index: int) -> tuple[float, str]:
    """주파수 한 점의 **진폭**(최대 변위)과 그 단위.

    조화 응답의 결과는 **복소수**다 — 실수부만 읽으면 위상에 따라 작게 나오고 공진이 평평해
    보인다. 진폭 연산자를 먼저 쓰고, 없으면 실수부 크기로 물러선다.
    """
    fields = model.results.displacement.on_time_scoping([index]).eval()
    try:
        field = dpf.operators.math.amplitude_fc(fields_container=fields).eval()[0]
    except Exception:
        field = fields[0]
    unit = str(field.unit or "")
    data = np.asarray(field.data)
    if data.size == 0:
        return 0.0, unit
    if data.ndim == 2:
        return float(np.max(np.linalg.norm(data, axis=1))), unit
    return float(np.max(np.abs(data))), unit
