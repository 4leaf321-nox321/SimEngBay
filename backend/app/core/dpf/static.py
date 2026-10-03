"""정적 해석 결과 — `.rst` → `result.json` · 변형 그림.

모달은 「어느 주파수에서 어떻게 떠는가」 였다. 정적은 **얼마나 밀리고 어디가 버거운가**다.
그래서 싣는 것이 다르다:

| 무엇 | 왜 |
| --- | --- |
| 최대 변형(`max_displacement`) | 지그가 「얼마나 밀리나」 — 사람이 먼저 보는 수다 |
| 최대 상당응력(`max_von_mises`) | 어디가 버거운가. 항복과 견주는 수 |
| 변형 그림(VTP · PNG) | 어디가 밀리는지 — 수 하나로는 못 본다 |

## 단위를 함께 싣는다

**값만 보면 mm 와 m 가 구별되지 않는다.** 모달에서 겪은 그대로다 — DPF 가 결과 파일에서
읽어 주는 단위계를 그대로 적는다.

## 0 이 나오면 말한다

하중이 안 걸린 정적 해석은 **전부 0 인 결과**를 낸다. 그림은 멀쩡하고 표도 멀쩡해서 「해석이
됐다」 로 읽힌다 — 그래서 변형이 0 이면 경고를 단다(모델링이 하중 없는 스펙을 먼저 막지만,
하중이 자리를 못 찾아 0 이 되는 길도 있다).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.dpf import probes, shapes
from app.core.spec import StaticSpec
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

RESULT_NAME = "result.json"


def extract(
    spec: StaticSpec,
    workdir: Path,
    *,
    result_name: str = "file.rst",
) -> StageResult:
    """변형 · 응력을 읽어 `result.json` 과 그림을 남긴다."""
    rst = workdir / result_name
    if not rst.is_file():
        raise StageFailure("solver_failed", f"결과 파일이 없습니다: {result_name}")

    try:
        from ansys.dpf import core as dpf
    except ImportError as failure:
        raise StageFailure(
            "internal",
            "PyDPF 가 이 파이썬에 없습니다 — 워커 환경(SIMULATION_EXECUTOR)을 확인하세요.",
        ) from failure

    try:
        model = dpf.Model(str(rst))
        mesh = model.metadata.meshed_region
        nodes, elements = int(mesh.nodes.n_nodes), int(mesh.elements.n_elements)
        system = str(model.metadata.result_info.unit_system_name)
        displacement = model.results.displacement.eval()[0]
        max_displacement, displacement_unit = _peak(displacement)
        stress, stress_unit = _von_mises(model)
        # **측정점** — 전체 최대는 구속 모서리의 수치적 첨두일 수 있고 센서는 그 자리에 없다.
        # 실측과 견줄 수 있는 값은 이쪽이고, CalculiX 쪽과 **같은 모양**으로 적는다.
        topology = probes.topology_of(workdir)
        spots = probes.read(
            topology,
            mesh,
            displacement,
            unit=displacement_unit,
            scale=probes.scale_for(displacement_unit),
            strains=_strains(model) if probes.wanted(topology) else None,
        )
        # **반력** — 변위로 당긴 자리가 버틴 힘. 미끄러지는 이음이면 μN 에서 멈춘다.
        forces = _reactions(model, mesh, topology)
    except StageFailure:
        raise
    except Exception as failure:
        raise StageFailure("internal", f"결과 파일을 읽지 못했습니다: {failure}") from failure

    result: dict[str, Any] = {
        "recipe": "static",
        "units": {
            "system": system,
            "displacement": displacement_unit,
            "stress": stress_unit,
            # 반력의 단위 — 이 플랫폼이 쓰는 두 계(MKS · mm-t-s)의 힘은 모두 N 이다.
            "force": "N",
        },
        "mesh": {"nodes": nodes, "elements": elements},
        "max_displacement": max_displacement,
        **({"probes": spots} if spots else {}),
        **({"reactions": forces} if forces else {}),
        "max_von_mises": stress,
        "material": spec.material.name,
    }
    if max_displacement <= 0:
        # **0 인 결과는 「해석이 됐다」 처럼 보인다.** 그림도 표도 멀쩡하다.
        result["warning"] = (
            "변형이 0 입니다 — 하중이 걸리지 않았거나 걸린 자리가 구속면과 같습니다."
        )

    # **그림을 먼저 그린다** — 그려 보고 나서 그 사실까지 담아 한 번에 쓴다.
    artifacts = _draw(model, mesh, workdir, result)
    artifacts.insert(0, ArtifactSpec("result_json", _write(workdir, result)))
    return StageResult(
        artifacts=artifacts,
        summary={
            "nodes": nodes,
            "max_displacement": max_displacement,
            "max_von_mises": stress,
        },
        detail=(
            f"최대 변형 {max_displacement:.4g} {displacement_unit}"
            + (f" · 최대 응력 {stress:.4g} {stress_unit}" if stress is not None else "")
        ),
    )


def _peak(field: Any) -> tuple[float, str]:
    """벡터장의 최대 크기와 단위."""
    import numpy as np

    data = np.asarray(field.data)
    if data.size == 0:
        return 0.0, str(field.unit or "")
    if data.ndim == 2:
        return float(np.max(np.linalg.norm(data, axis=1))), str(field.unit or "")
    return float(np.max(np.abs(data))), str(field.unit or "")


def _strains(model: Any) -> Any:
    """탄성 변형률(절점 평균). **못 읽으면 `None`** — 측정점에 변형률이 빠질 뿐이다.

    Mechanical 의 기본 출력에 변형률이 들어 있다. 판마다 부르는 길이 달라 차례로 해 본다
    (`_von_mises` 와 같은 이유).
    """
    from ansys.dpf import core as dpf

    attempts: tuple[Any, ...] = (
        lambda: model.results.elastic_strain.on_location(dpf.locations.nodal).eval()[0],
        lambda: dpf.operators.result.elastic_strain(
            data_sources=model.metadata.data_sources, requested_location="Nodal"
        ).eval()[0],
    )
    for attempt in attempts:
        try:
            return attempt()
        except Exception:
            continue
    logger.warning("탄성 변형률을 못 읽었습니다 — 측정점에 변형률 없이 갑니다")
    return None


def _reactions(model: Any, mesh: Any, topology: dict[str, Any]) -> dict[str, list[float]]:
    """변위로 당긴 영역마다 **반력 합**(N). CalculiX 쪽과 같은 열쇠(`reactions`)로 낸다."""
    try:
        from app.core import conditions as condition_model

        given = condition_model.read(topology, recipe="static") if topology else None
    except ValueError:
        return {}
    if given is None:
        return {}
    regions = topology.get("regions") or {}
    found: dict[str, list[float]] = {}
    for rule in given.constraints:
        if rule.kind != "displacement":
            continue
        rows = regions.get(rule.region)
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            continue
        total = probes.reaction(model, mesh, rows[0])
        if total is not None:
            found[rule.region] = total
    return found


def _von_mises(model: Any) -> tuple[float | None, str]:
    """최대 상당응력(폰 미세스). **못 읽으면 `None`** — 없는 값을 0 으로 적지 않는다.

    DPF 는 같은 값을 부르는 길이 여럿이고 판마다 있는 것이 다르다. 그래서 **차례로 해 본다** —
    첫 길이 없다고 응력을 포기하면, 사람이 가장 보고 싶어 하는 수가 비어서 나간다.
    """
    from ansys.dpf import core as dpf

    attempts: tuple[Any, ...] = (
        lambda: dpf.operators.result.stress_von_mises(
            data_sources=model.metadata.data_sources
        ).eval()[0],
        lambda: model.results.stress().eqv().eval()[0],
        lambda: dpf.operators.invariant.von_mises_eqv_fc(
            fields_container=model.results.stress().eval()
        ).eval()[0],
    )
    for attempt in attempts:
        try:
            field: Any = attempt()
        except Exception:
            continue
        value, unit = _peak(field)
        if value > 0:
            return value, unit
    logger.warning("상당응력을 읽지 못했습니다 — 변형만 남깁니다")
    return None, ""


def _write(workdir: Path, result: dict[str, Any]) -> Path:
    path = workdir / RESULT_NAME
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _draw(model: Any, mesh: Any, workdir: Path, result: dict[str, Any]) -> list[ArtifactSpec]:
    """변형 그림 — 모달의 모드 형상과 **같은 길**을 쓴다(표면만 · 중간 절점 버림).

    그림이 실패해도 수는 남긴다 — 그림이 없는 것이 결과가 없는 것보다 낫다.
    """
    made: list[ArtifactSpec] = []
    try:
        skin = shapes.skin_of(mesh)
        drawn = shapes.export_mode(model, skin, 1, workdir)
        vtp = workdir / str(drawn["vtp"])
        made.append(ArtifactSpec("mode_vtp", vtp))
        result["shape"] = {"vtp": drawn["vtp"], "points": drawn.get("points")}
        if "png" in drawn:
            made.append(ArtifactSpec("mode_png", workdir / str(drawn["png"])))
            result["shape"]["png"] = drawn["png"]
    except Exception:
        logger.warning("변형 그림 생성 실패 — 수만 남깁니다", exc_info=True)
    return made
