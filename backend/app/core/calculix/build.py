"""모델링 단계 — CalculiX 경로. **Ansys 쪽과 같은 자리에서 같은 말을 한다.**

하는 일의 순서가 `app/core/mechanical/build.py` 와 같다: 형상을 읽고 · 바디에 물성을 붙이고 ·
CAD 가 보낸 조건을 영역 지문으로 풀어 걸고 · 메시를 만들고 · 덱을 쓴다. 다른 것은 **그 일을
누가 하느냐**뿐이다 — Mechanical 대신 gmsh 가 메시를 만들고, MAPDL 덱 대신 `.inp` 를 쓴다.

같은 중립 코드를 쓴다: `conditions`(무엇을 걸라고 했나) · `materials`(무슨 물성인가) ·
`bodies`(어느 솔리드가 어느 바디인가) · `regions`(어느 면인가). 그래서 두 솔버가 **같은 조건을
같은 자리에 건다** — 교차 검증이 뜻을 가지는 이유다(실측 2026-10-02: 1차가 Ansys 1,266.4 Hz ·
CalculiX 1,263.5 Hz).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core import conditions as condition_model
from app.core import materials as material_model
from app.core import units
from app.core.bodies import match_bodies
from app.core.calculix import deck as deck_writer
from app.core.calculix.mesh import build_mesh
from app.core.regions import match_regions
from app.core.spec import RIGID_BODY_MODES, HarmonicSpec, ModalSpec, StaticSpec
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

#: 받을 수 있는 스펙 — 레시피 판정은 아래 `build` 가 한다(지금은 모달뿐).
AnySpec = ModalSpec | StaticSpec | HarmonicSpec

BOUNDARY_NAME = "boundary.json"
TOPOLOGY_NAME = "topology.json"
DECK_NAME = "model.inp"


def build(
    spec: AnySpec,
    workdir: Path,
    *,
    input_name: str = "input.step",
    timeout_seconds: int = 1800,
    **_ignored: Any,
) -> StageResult:
    """STEP → 메시 → `.inp`. 뒤 단계(솔브 · 추출)가 이 폴더를 그대로 쓴다."""
    if spec.recipe not in deck_writer.SUPPORTED_RECIPES:
        raise StageFailure(
            "internal",
            f"CalculiX 경로는 아직 「{spec.recipe}」 를 못 풉니다 — 솔버를 ansys 로 "
            f"바꾸거나 모달로 돌리세요.",
        )
    if not isinstance(spec, ModalSpec):  # pragma: no cover - 위에서 이미 걸린다
        raise StageFailure("internal", "모달 스펙이 아닙니다.")

    step = workdir / input_name
    if not step.is_file():
        raise StageFailure("geometry_import", f"입력 형상이 없습니다: {input_name}")

    topology = _topology(workdir)
    system = units.declared_in(topology) if topology else units.DEFAULT
    given = _declared_conditions(spec, topology)

    size = spec.mesh.element_size_mm
    if size is None:
        raise StageFailure(
            "mesh_failed",
            "요소 크기가 없습니다 — CalculiX 경로는 gmsh 에게 크기를 줘야 합니다.",
        )
    mesh = build_mesh(
        step,
        workdir,
        element_size_mm=size,
        second_order=spec.mesh.order == "quadratic",
        timeout_seconds=timeout_seconds,
    )
    logger.info(
        "메시: 절점 %s · 요소 %s · 면 %s · 솔리드 %s",
        len(mesh.nodes),
        mesh.element_count,
        len(mesh.faces),
        len(mesh.solids),
    )

    body_of, materials, material_from = _materials(spec, topology, system, mesh)
    held = _held_nodes(topology, given, mesh)
    constrained = plan_constrained(given, spec)
    plan = deck_writer.write_modal(
        nodes=mesh.nodes,
        solids=mesh.solids,
        body_of=body_of,
        materials=materials,
        held_nodes=held,
        given=given,
        # **자유-자유면 강체 모드 여섯을 더 뽑는다** — 안 그러면 사람이 요청한 탄성 모드 수가
        # 모자라게 나온다(Ansys 쪽과 같은 규칙).
        modes=spec.modes + (0 if constrained else RIGID_BODY_MODES),
        second_order=mesh.second_order,
    )
    if plan.refused:
        # **못 거는 조건은 조용히 빼지 않는다.** 그대로 풀면 구속 없는 해석이 끝까지 돌고,
        # 그 결과는 0 Hz 여섯 개를 달고 나온다.
        first = plan.refused[0]
        raise StageFailure(
            "internal",
            f"{first.what}: {first.why}",
            details={"refused": [f"{one.what}: {one.why}" for one in plan.refused]},
        )

    path = workdir / DECK_NAME
    path.write_text(plan.text, encoding="utf-8")
    (workdir / BOUNDARY_NAME).write_text(
        json.dumps(
            {
                "constrained": constrained,
                "modes_requested": spec.modes,
                "recipe": spec.recipe,
                "solver": "calculix",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    mass = _mass_kg(materials, body_of, mesh)
    return StageResult(
        artifacts=[ArtifactSpec("dat", path)],
        summary={
            "solver": "calculix",
            "bodies": len(mesh.solids),
            "nodes": len(mesh.nodes),
            "elements": mesh.element_count,
            "modes_requested": spec.modes,
            "mesh_order": "quadratic" if mesh.second_order else "linear",
            "constrained_regions": plan.applied,
            "mass_kg": mass,
            "unit_system": system.key,
            # **덱은 늘 mm · tonne · N 으로 쓴다**(형상이 mm 라서) — 선언된 계가 무엇이든.
            "solver_unit_system": "ConsistentNMM",
            "material_from": material_from,
            "material": " · ".join(one.name for one in materials) if materials else None,
            **(
                {"conditions_from": "cad" if given.constraints else "spec"} if topology else {}
            ),
            **(
                {"conditions_skipped": " · ".join(one.what for one in plan.skipped)}
                if plan.skipped
                else {}
            ),
        },
        detail=(
            f"절점 {len(mesh.nodes):,} · 요소 {mesh.element_count:,} · "
            f"구속 {len(plan.applied)}개"
        ),
    )


def plan_constrained(given: condition_model.Conditions, spec: ModalSpec) -> bool:
    """구속이 하나라도 걸리나 — 자유-자유면 강체 모드 여섯을 더 뽑아야 한다."""
    return bool(given.constraints or spec.constraints)


def _topology(workdir: Path) -> dict[str, Any]:
    path = workdir / TOPOLOGY_NAME
    if not path.is_file():
        return {}
    try:
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as failure:
        raise StageFailure(
            "internal", f"{TOPOLOGY_NAME} 을 읽지 못했습니다: {failure}"
        ) from failure
    return loaded


def _declared_conditions(
    spec: ModalSpec, topology: dict[str, Any]
) -> condition_model.Conditions:
    """CAD 가 보낸 조건. `conditions_from == "spec"` 이면 일부러 안 읽는다."""
    if not topology or spec.conditions_from != "cad":
        return condition_model.Conditions()
    try:
        return condition_model.read(topology, recipe=spec.recipe)
    except ValueError as failure:
        raise StageFailure("internal", f"조건을 읽지 못했습니다: {failure}") from failure


def _materials(
    spec: ModalSpec,
    topology: dict[str, Any],
    system: units.UnitSystem,
    mesh: Any,
) -> tuple[dict[str, int], list[material_model.Material], str]:
    """바디마다 물성 — **CAD 가 보낸 것이 먼저**고, 없으면 스펙의 한 벌을 전체에 건다."""
    if topology and spec.material_from == "cad":
        try:
            found = material_model.read(topology, system)
        except material_model.MaterialProblem as failure:
            raise StageFailure("internal", str(failure)) from failure
        if found:
            matched = match_bodies(topology, mesh.bodies)
            if matched.failures:
                raise StageFailure(
                    "internal",
                    "메시의 솔리드와 CAD 바디를 짝짓지 못했습니다: "
                    + " · ".join(matched.failures),
                )
            return matched.bodies, found, "cad"

    # 스펙 물성 — 솔리드 전부에 같은 것을 건다. 이름은 짝짓지 않아도 된다.
    one = material_model.Material(
        name=spec.material.name,
        youngs_modulus_pa=spec.material.youngs_modulus_gpa * 1e9,
        poisson_ratio=spec.material.poisson_ratio,
        density_kg_m3=spec.material.density_kg_m3,
        bodies=tuple(f"solid{entity}" for entity in sorted(mesh.solids)),
        source="spec",
    )
    body_of = {f"solid{entity}": entity for entity in sorted(mesh.solids)}
    return body_of, [one], "spec"


def _held_nodes(
    topology: dict[str, Any], given: condition_model.Conditions, mesh: Any
) -> dict[str, set[int]]:
    """구속이 가리키는 영역을 **면 지문으로** 풀어 절점으로 바꾼다.

    매칭은 `app/core/regions` 가 한다 — 그 코드는 솔버를 모르고, Mechanical 이 주던 면 지문과
    gmsh 가 낸 면 지문이 같은 종류라서 그대로 돈다(실측 2026-10-02).
    """
    wanted = [rule.region for rule in given.constraints]
    if not wanted or not topology:
        return {}
    found = match_regions(topology, mesh.faces, wanted_regions=wanted)
    if found.failures:
        raise StageFailure(
            "internal",
            "구속을 걸 면을 못 찾았습니다: "
            + " · ".join(f"{one.region}({one.reason})" for one in found.failures),
        )
    held: dict[str, set[int]] = {}
    for name, ids in found.faces.items():
        members: set[int] = set()
        for face in ids:
            members |= mesh.face_nodes.get(face, set())
        held[name] = members
        logger.info("구속 영역 %s → 면 %s · 절점 %s", name, ids, len(members))
    return held


def _mass_kg(
    materials: list[material_model.Material], body_of: dict[str, int], mesh: Any
) -> float | None:
    """**바디마다** 부피 x 그 바디의 밀도. 설계점 비교의 두 번째 축이다."""
    by_entity = {one.index: one.volume for one in mesh.bodies}
    total = 0.0
    for material in materials:
        for body in material.bodies:
            entity = body_of.get(body)
            if entity is None or entity not in by_entity:
                return None
            # 부피는 mm³ — SI 밀도와 곱하려면 m³ 로 옮긴다(1e-9).
            total += by_entity[entity] * 1e-9 * material.density_kg_m3
    return round(total, 4) if total else None
