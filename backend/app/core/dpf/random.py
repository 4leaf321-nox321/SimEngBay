"""Ansys 랜덤 진동 결과 — **Mechanical 의 Random Vibration(PSD)** 이 푼 1σ 를 읽는다
(2026-11-18).

CalculiX 경로(`calculix/random_read.py`)는 모드를 풀고 우리가 PSD 를 셈한다. 여기는 MAPDL 이
셈한 것을 읽는다 — **두 셈이 서로 독립이라 대조가 뜻을 가진다**(`조건_랜덤진동` 기둥 끝).

## 결과 파일

랜덤 덱은 앞 모달과 다른 실행 이름으로 푼다(`solve.mapdl.PSD_JOB`) — `psd.rst` 의 집합은
(실측 2026-11-18, 2025 R2):

| 집합 | 무엇 |
| --- | --- |
| 1 | 기저 단위 변위의 정적 해(크기 1) |
| 2 | **1σ 변위 — 지지부 기준**(`psdres,disp,rel`) |
| 3 | 1σ 속도 |
| 4 | **1σ 가속도 — 절대**(`psdres,acel,abs`) |

결과 열쇠는 CalculiX 와 같다 — 화면 · 비교 · MCP 가 솔버를 몰라도 된다. 다른 것:

- **상당응력 1σ 는 내지 않는다** — Mechanical 이 후처리에서 셈하는 값(Segalman)이라 결과
  파일에 없다. 성분 1σ 의 von Mises 는 다른 값이다(틀리게 크다).
- 응답 PSD 곡선 · 1σ 변위 그림은 없다(입력 PSD 곡선만).
- 잔여 벡터를 더하지 않는다 — 모드 수가 모자라면 준정적 부품의 응답이 작다(경고로 적는다).
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from app.core import boundary
from app.core import probes as core_probes
from app.core import random_vibration as random_model
from app.core.dpf import harmonic as dpf_harmonic
from app.core.dpf import participation, probes
from app.core.numbers import significant
from app.core.spec import RandomSpec
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

RESULT_NAME = "result.json"
PSD_RST = "psd.rst"
MODAL_RST = "file.rst"
MODAL_OUT = "upstream.out"
#: `psd.rst` 의 집합 번호 — 1σ 변위(상대) · 1σ 가속도(절대).
DISPLACEMENT_SET = 2
ACCELERATION_SET = 4
#: 그림에 싣는 입력 PSD 곡선의 점 수(로그 간격).
CURVE_POINTS = 200
#: g(mm/s²) — CompCore 의 g. 덱의 `PSDUNIT` 도 이것으로 고쳐 쓴다(`mechanical.build`).
G_MM_S2 = 9806.65


def extract(spec: RandomSpec, workdir: Path, **_ignored: object) -> StageResult:
    """`psd.rst`(1σ) · `file.rst`(모드) → `result.json`."""
    shaking = random_model.read(boundary.read(workdir))
    if shaking is None:
        raise StageFailure(
            "internal", "boundary.json 에 랜덤 진동 설정이 없습니다 — 모델링을 다시 돌리세요."
        )
    rst = workdir / PSD_RST
    if not rst.is_file():
        raise StageFailure("solver_failed", f"결과 파일이 없습니다: {PSD_RST}")
    try:
        import numpy as np
        from ansys.dpf import core as dpf
    except ImportError as failure:
        raise StageFailure(
            "internal", "PyDPF 가 이 파이썬에 없습니다 — 워커 환경을 확인하세요."
        ) from failure

    try:
        model = dpf.Model(str(rst))
        sets = int(model.metadata.time_freq_support.n_sets)
        if sets < ACCELERATION_SET:
            raise StageFailure(
                "solver_failed",
                f"{PSD_RST} 에 1σ 가속도가 없습니다(집합 {sets}개) — 덱의 psdres 를 보세요.",
            )
        mesh = model.metadata.meshed_region
        length = probes.scale_for(str(mesh.unit or ""))  # 메시 단위 → mm
        moved = _vectors(np, model.results.displacement.on_time_scoping([DISPLACEMENT_SET]))
        shaken = _vectors(np, model.results.displacement.on_time_scoping([ACCELERATION_SET]))
        spots = dpf_harmonic._spots(mesh, probes.topology_of(workdir))
        # 복사해서 받는다 — 임시 scoping · 좌표 필드가 풀리면 그 배열은 풀린 메모리를 본다.
        node_ids = np.array(mesh.nodes.scoping.ids, copy=True).tolist()
        points = np.array(mesh.nodes.coordinates_field.data, copy=True).tolist()
        coordinates = {
            int(node): [float(one) * length for one in xyz]
            for node, xyz in zip(node_ids, points, strict=False)
        }
    except StageFailure:
        raise
    except Exception as failure:
        raise StageFailure("internal", f"결과 파일을 읽지 못했습니다: {failure}") from failure

    naturals = _naturals(dpf, workdir)
    ratios = _ratios(workdir)
    warnings: list[str] = []
    if naturals and naturals[-1] < random_model.MODE_REACH * shaking.high:
        warnings.append(
            f"가장 높은 모드가 {naturals[-1]:,.0f} Hz 입니다 — 가진 대역 위끝"
            f"({shaking.high:,.0f} Hz)의 {random_model.MODE_REACH:g}배 넘게 풀어야 응답이"
            " 맞습니다. 모드 수를 늘리세요(Ansys 경로는 잔여 벡터를 더하지 않습니다)."
        )

    sizes = {
        node: math.sqrt(sum(c * c for c in vector)) * length for node, vector in moved.items()
    }
    worst = max(sizes, key=lambda node: sizes[node]) if sizes else None
    to_g = length / G_MM_S2
    probe_rows: list[dict[str, Any]] = []
    for spot in spots:
        axes = [abs(one) * to_g for one in (shaken.get(spot.node) or [0.0, 0.0, 0.0])[:3]]
        row = core_probes.row(
            name=spot.name,
            point=spot.point,
            node=spot.node,
            distance_mm=spot.distance_mm,
            value=math.sqrt(sum(one * one for one in axes)),
            unit="g",
            vector=axes,
        )
        row["displacement_1sigma_mm"] = significant(sizes.get(spot.node, 0.0))
        probe_rows.append(row)

    grid = [
        shaking.low * (shaking.high / shaking.low) ** (at / (CURVE_POINTS - 1))
        for at in range(CURVE_POINTS)
    ]
    searched = boundary.read(workdir).get("mode_search")
    result: dict[str, Any] = {
        "recipe": "random",
        "solver": "ansys",
        "units": {
            "frequency": "Hz",
            "displacement": "mm",
            "acceleration": "g",
            "psd": "g^2/Hz",
            "system": str(model.metadata.result_info.unit_system_name),
        },
        "sigma": 1,
        "damping_ratio": shaking.damping_ratio,
        "band_hz": [shaking.low, shaking.high],
        **(
            {
                "frequency_range_hz": [searched["low"], searched["high"]],
                "range_from": searched.get("source") or "spec",
            }
            if isinstance(searched, dict) and "low" in searched
            else {}
        ),
        "inputs": [
            {
                "name": one.name,
                "direction": [round(v, 6) for v in one.direction],
                "grms": significant(random_model.grms(one.table)),
                "table": [list(row) for row in one.table],
                **(
                    {"declared_grms": significant(one.declared_grms)}
                    if one.declared_grms is not None
                    else {}
                ),
            }
            for one in shaking.shakes
        ],
        "modes": [
            {
                "number": at,
                "frequency_hz": round(hz, 4),
                **(_shares(ratios, at, shaking) or {}),
            }
            for at, hz in enumerate(naturals, start=1)
        ],
        "acceleration": "absolute",
        "displacement": "relative",
        "residual": False,
        "curves": {
            "frequency_hz": [significant(hz) for hz in grid],
            "input_psd": {
                one.name: [significant(random_model.psd_at(one.table, hz)) for hz in grid]
                for one in shaking.shakes
            },
        },
        "mesh": {"nodes": int(mesh.nodes.n_nodes), "elements": int(mesh.elements.n_elements)},
        "material": boundary.used_material(workdir, spec),
    }
    if worst is not None:
        result["max_displacement"] = {
            "value_mm": significant(sizes[worst]),
            "node": worst,
            "point": [round(one, 6) for one in coordinates.get(worst, [])] or None,
        }
    if probe_rows:
        result["probes"] = probe_rows
    if warnings:
        result["warning"] = " ".join(warnings)

    path = workdir / RESULT_NAME
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    first = probe_rows[0] if probe_rows else None
    largest = result.get("max_displacement", {}).get("value_mm")
    return StageResult(
        artifacts=[ArtifactSpec("result_json", path)],
        summary={
            "solver": "ansys",
            "modes": len(naturals),
            "input_grms": " · ".join(
                f"{one['name']} {one['grms']:.4g}" for one in result["inputs"]
            ),
            **({"max_displacement_1sigma_mm": largest} if largest is not None else {}),
            **(
                {"probe_grms": f"{first['name']} {first['value']:.4g} g"}
                if first is not None
                else {}
            ),
            **({"result_warning": result["warning"]} if warnings else {}),
        },
        detail=f"모드 {len(naturals)}개"
        + (f" · 1σ 변위 최대 {largest:.4g} mm" if largest is not None else ""),
    )


def _vectors(np: Any, operator: Any) -> dict[int, list[float]]:
    """절점 → 성분 셋(결과 파일의 단위)."""
    field = operator.eval()[0]
    ids = np.array(field.scoping.ids, copy=True, dtype=int).tolist()
    data = np.asarray(field.data, dtype=float).tolist()
    return {int(node): list(row)[:3] for node, row in zip(ids, data, strict=False)}


def _naturals(dpf: Any, workdir: Path) -> list[float]:
    """앞 모달의 고유진동수(Hz) — `file.rst`. 못 읽으면 빈 것."""
    rst = workdir / MODAL_RST
    if not rst.is_file():
        return []
    try:
        support = dpf.Model(str(rst)).metadata.time_freq_support
        return [float(one) for one in support.time_frequencies.data]
    except Exception:  # pragma: no cover - 결과 파일이 깨진 경우
        logger.warning("모드를 못 읽었습니다", exc_info=True)
        return []


def _ratios(workdir: Path) -> dict[str, dict[int, float]]:
    """앞 모달의 유효질량비(방향 → 모드 → 비) — `upstream.out`."""
    out = workdir / MODAL_OUT
    if not out.is_file():
        return {}
    return participation.parse(out.read_text(encoding="utf-8", errors="replace"))


def _shares(
    ratios: dict[str, dict[int, float]], mode: int, shaking: random_model.RandomPlan
) -> dict[str, Any] | None:
    """가진마다 그 축의 유효질량 몫(화면의 모드 표)."""
    shares: dict[str, float] = {}
    for shake in shaking.shakes:
        axis = ("X", "Y", "Z")[max(range(3), key=lambda at: abs(shake.direction[at]))]
        value = (ratios.get(axis) or {}).get(mode)
        if value is not None:
            shares[shake.name] = round(value, 4)
    return {"mass_share": shares} if shares else None
