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

from app.core.spec import HarmonicSpec
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

RESULT_NAME = "result.json"

#: 이보다 크면 「감쇠가 모자란 것 아닌가」 를 적어 둔다(선언된 계의 길이 단위).
SUSPICIOUS_DISPLACEMENT = 1e3


def extract(
    spec: HarmonicSpec, workdir: Path, *, result_name: str = "file.rst"
) -> StageResult:
    """주파수마다 최대 변위를 읽어 `result.json` 에 곡선으로 남긴다."""
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
        for index, value in enumerate(frequencies, start=1):
            peak = _amplitude(dpf, np, model, index)
            points.append({"frequency_hz": round(value, 4), "max_displacement": peak})
    except StageFailure:
        raise
    except Exception as failure:
        raise StageFailure("internal", f"결과 파일을 읽지 못했습니다: {failure}") from failure

    if not points:
        raise StageFailure("solver_failed", "결과 파일에 주파수 점이 없습니다.")

    worst = max(points, key=lambda one: one["max_displacement"])
    result: dict[str, Any] = {
        "recipe": "harmonic",
        "units": {"frequency": unit, "system": system},
        "mesh": {"nodes": int(mesh.nodes.n_nodes), "elements": int(mesh.elements.n_elements)},
        "damping_ratio": spec.damping_ratio,
        "points": points,
        "peak": worst,
        "material": spec.material.name,
    }
    if worst["max_displacement"] > SUSPICIOUS_DISPLACEMENT:
        # **큰 수는 그럴듯해 보인다** — 감쇠가 모자라면 공진에서 수가 치솟는다.
        result["warning"] = (
            f"공진 응답이 {worst['max_displacement']:.3g} 로 큽니다 — "
            f"감쇠비({spec.damping_ratio})가 실제보다 작지 않은지 보세요."
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


def _amplitude(dpf: Any, np: Any, model: Any, index: int) -> float:
    """주파수 한 점의 **진폭**(최대 변위).

    조화 응답의 결과는 **복소수**다 — 실수부만 읽으면 위상에 따라 작게 나오고 공진이 평평해
    보인다. 진폭 연산자를 먼저 쓰고, 없으면 실수부 크기로 물러선다.
    """
    fields = model.results.displacement.on_time_scoping([index]).eval()
    try:
        field = dpf.operators.math.amplitude_fc(fields_container=fields).eval()[0]
    except Exception:
        field = fields[0]
    data = np.asarray(field.data)
    if data.size == 0:
        return 0.0
    if data.ndim == 2:
        return float(np.max(np.linalg.norm(data, axis=1)))
    return float(np.max(np.abs(data)))
