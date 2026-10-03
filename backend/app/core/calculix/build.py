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
from app.core.calculix.mesh import build_mesh, element_faces, tributary_areas
from app.core.harmonic import harmonic_plan
from app.core.regions import match_regions
from app.core.spec import RIGID_BODY_MODES, HarmonicSpec, ModalSpec, StaticSpec
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

#: 받을 수 있는 스펙 — 레시피 판정은 아래 `build` 가 한다(지금은 모달뿐).
AnySpec = ModalSpec | StaticSpec | HarmonicSpec

BOUNDARY_NAME = "boundary.json"
#: 면을 못 찾았을 때 덧붙이는 말. **메시에서 되찾는 길의 한계**다 — 삼각형에는 「이 면이
#: 원통인가」 가 없다. 평면 · 넓이 · 법선으로 찾는 지문은 풀리고, 곡면 지문(원통 반지름 등)은
#: 아직 못 푼다(실측 2026-10-03: `조건_원통_SI` 의 구멍면). 그것까지 하려면 메시에 원통을
#: 맞춰 보는 일이 필요하다.
MESH_LIMIT = (
    "CalculiX 경로는 **메시에서** 면을 되찾으므로 곡면 지문(원통 반지름 등)은 아직 못 풉니다 "
    "— 그 조건이 필요하면 솔버를 ansys 로 돌리세요."
)
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
            f"바꾸거나 {' · '.join(deck_writer.SUPPORTED_RECIPES)} 로 돌리세요.",
        )

    step = workdir / input_name
    if not step.is_file():
        raise StageFailure("geometry_import", f"입력 형상이 없습니다: {input_name}")

    topology = _topology(workdir)
    system = units.declared_in(topology) if topology else units.DEFAULT
    given = _declared_conditions(spec, topology)

    size = _global_size(spec, given, system)
    second_order = spec.mesh.order == "quadratic"
    # **접촉 쌍은 정적에서만 쓴다 — CalculiX 는 고유치에 접촉을 넣지 않는다.**
    #
    # 실측 2026-10-03: TIED 접촉 쌍을 넣고 `*FREQUENCY` 를 풀었더니 강체 모드 6개(0 · 0 ·
    # 0.0014 · 0.0016 · 0.002 · 0.0022 Hz)가 나왔다 — 블록이 떠 있었다. `*STEP, PERTURBATION`
    # 으로 비선형 정적 뒤에 붙여도 같았다(8개 모드 전부 0 Hz). 접촉 요소는 비선형 단계에서만
    # 만들어진다.
    #
    # 그래서 모달 · 조화는 **맞닿은 면의 절점을 공유시켜**(메시를 쪼개) 붙은 것으로 푼다 —
    # Ansys 의 bonded 와 1차에서 0.23% 차이였다. 접촉이 중요한 선응력 모달이 필요하면 Ansys 로
    # 돌린다(그쪽은 선형 섭동에 접촉 상태를 물고 간다).
    use_contact = (
        isinstance(spec, StaticSpec)
        and bool(given.loads)
        and any(one.kind in deck_writer.NONLINEAR_CONTACTS for one in given.contacts)
    )
    # 1차 통과도 **같은 쪼개기 규칙**을 따른다 — 안 그러면 접합면 두 장이 하나로 합쳐져서 한쪽
    # 면에 걸린 메시 힌트가 「법선이 180도 틀어져 있다」 로 빠진다(실측 2026-10-03).
    local = _local_sizes(
        step,
        workdir,
        topology,
        given,
        system,
        size,
        second_order,
        timeout_seconds,
        fragment=not use_contact,
    )
    mesh = build_mesh(
        step,
        workdir,
        element_size_mm=size,
        second_order=second_order,
        timeout_seconds=timeout_seconds,
        local_sizes=local,
        fragment=not use_contact,
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
    shapes = _region_shapes(topology)
    if isinstance(spec, HarmonicSpec):
        places, areas, faces = _load_places(topology, given, mesh)
        shake = harmonic_plan(spec, given)
        plan = deck_writer.write_harmonic(
            nodes=mesh.nodes,
            solids=mesh.solids,
            body_of=body_of,
            materials=materials,
            held_nodes=held,
            load_nodes=places,
            load_faces=faces,
            load_areas=areas,
            given=given,
            shapes=shapes,
            plan_of=shake,
            modes=spec.modes,
            second_order=mesh.second_order,
        )
    elif isinstance(spec, StaticSpec):
        places, areas, faces = _load_places(topology, given, mesh)
        plan = deck_writer.write_static(
            nodes=mesh.nodes,
            solids=mesh.solids,
            body_of=body_of,
            materials=materials,
            held_nodes=held,
            load_nodes=places,
            load_faces=faces,
            load_areas=areas,
            given=given,
            shapes=shapes,
            contact_faces=_contact_faces(topology, given, mesh) if use_contact else None,
            element_size_mm=size,
            second_order=mesh.second_order,
        )
    else:
        preload: list[str] | None = None
        contact_faces: dict[str, list[tuple[int, str]]] | None = None
        if use_contact or given.prestressed:
            # **선응력 모달** — 비선형 정적을 앞에 두고 그 상태에서 모드를 뽑는다. 하중 줄은
            # 정적 덱을 한 번 써서 얻는다(같은 하중을 두 벌로 적지 않는다).
            places, areas, faces = _load_places(topology, given, mesh)
            contact_faces = _contact_faces(topology, given, mesh) if use_contact else None
            ahead = deck_writer.write_static(
                nodes=mesh.nodes,
                solids=mesh.solids,
                body_of=body_of,
                materials=materials,
                held_nodes=held,
                load_nodes=places,
                load_faces=faces,
                load_areas=areas,
                given=given,
                shapes=shapes,
                contact_faces=contact_faces,
                element_size_mm=size,
                second_order=mesh.second_order,
            )
            preload = ahead.load_rows or None
        plan = deck_writer.write_modal(
            nodes=mesh.nodes,
            solids=mesh.solids,
            body_of=body_of,
            materials=materials,
            held_nodes=held,
            given=given,
            shapes=shapes,
            contact_faces=contact_faces,
            preload=preload,
            element_size_mm=size,
            # **자유-자유면 강체 모드 여섯을 더 뽑는다** — 안 그러면 사람이 요청한 탄성 모드
            # 수가 모자라게 나온다(Ansys 쪽과 같은 규칙).
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
    boundary: dict[str, Any] = {
        "constrained": constrained,
        "modes_requested": spec.modes if isinstance(spec, ModalSpec) else 0,
        "recipe": spec.recipe,
        "solver": "calculix",
    }
    if plan.reaction_sets:
        # **반력을 읽을 자리** — 추출 단계가 `.dat` 의 합에서 영역 이름으로 되찾는다.
        boundary["reaction_sets"] = plan.reaction_sets
    # **측정점이 어느 바디의 것인가** — 같은 자리에 두 바디의 꼭짓점이 겹치면(이음 입구) 바디로
    # 갈라야 미끄럼을 잴 수 있다. 추출이 그 바디의 절점 안에서만 가장 가까운 것을 찾는다.
    boundary["bodies"] = {name: entity for name, entity in body_of.items()}
    if isinstance(spec, HarmonicSpec):
        # **실제로 쓴 감쇠비 · 범위 · 점 수.** 결과가 스펙 값을 적으면 화면이 거짓말을 한다 —
        # 봉우리 높이는 1/2ζ 로 읽히기 때문이다(Ansys 쪽과 같은 규칙).
        shake_plan = harmonic_plan(spec, given)
        boundary["damping_ratio"] = shake_plan.damping_ratio
        boundary["frequency_range_hz"] = [shake_plan.low, shake_plan.high]
        boundary["intervals"] = shake_plan.intervals
        boundary["settings_from"] = shake_plan.source
    (workdir / BOUNDARY_NAME).write_text(
        json.dumps(boundary, ensure_ascii=False), encoding="utf-8"
    )
    mass = _mass_kg(materials, body_of, mesh)
    return StageResult(
        artifacts=[ArtifactSpec("dat", path)],
        summary={
            "solver": "calculix",
            "bodies": len(mesh.solids),
            "nodes": len(mesh.nodes),
            "elements": mesh.element_count,
            **({"modes_requested": spec.modes} if isinstance(spec, ModalSpec) else {}),
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
            # **까닭까지 싣는다.** 이름만 적으면 「마찰을 넘겼다」 까지만 보이고, 그래서
            # 어떻게 하라는 것인지(정적으로 돌려라 · 솔버를 바꿔라)가 아무 데도 안 남는다.
            **(
                {
                    "conditions_skipped": " · ".join(
                        f"{one.what}: {one.why}" for one in plan.skipped
                    )
                }
                if plan.skipped
                else {}
            ),
        },
        detail=(
            f"절점 {len(mesh.nodes):,} · 요소 {mesh.element_count:,} · "
            f"구속 {len(plan.applied)}개"
        ),
    )


def plan_constrained(given: condition_model.Conditions, spec: AnySpec) -> bool:
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
    spec: AnySpec, topology: dict[str, Any]
) -> condition_model.Conditions:
    """CAD 가 보낸 조건. `conditions_from == "spec"` 이면 일부러 안 읽는다."""
    if not topology or spec.conditions_from != "cad":
        return condition_model.Conditions()
    try:
        return condition_model.read(topology, recipe=spec.recipe)
    except ValueError as failure:
        raise StageFailure("internal", f"조건을 읽지 못했습니다: {failure}") from failure


def _materials(
    spec: AnySpec,
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
            + " · ".join(f"{one.region}({one.reason})" for one in found.failures)
            + f". {MESH_LIMIT}",
        )
    held: dict[str, set[int]] = {}
    for name, ids in found.faces.items():
        members: set[int] = set()
        for face in ids:
            members |= mesh.face_nodes.get(face, set())
        held[name] = members
        logger.info("구속 영역 %s → 면 %s · 절점 %s", name, ids, len(members))
    return held


def _global_size(
    spec: AnySpec, given: condition_model.Conditions, system: units.UnitSystem
) -> float:
    """전역 요소 크기(mm). 스펙이 비면 **CAD 의 「전체」 힌트**를 쓴다.

    둘 다 없으면 멈춘다 — gmsh 는 크기를 안 주면 제 나름으로 잡고, 그러면 같은 형상이 실행마다
    다른 메시로 풀린다(설계점 비교가 무너진다).
    """
    if spec.mesh.element_size_mm is not None:
        return float(spec.mesh.element_size_mm)
    whole = next(
        (
            one
            for one in given.mesh_hints
            if one.region in ("전체", "all") and one.element_size is not None
        ),
        None,
    )
    if whole is not None and whole.element_size is not None:
        # 힌트는 **선언된 계의 길이**다(SI 면 m) — 형상은 늘 mm 이므로 옮긴다.
        size = whole.element_size * system.length_mm
        logger.info(
            "메시 전체 크기 ← CAD %s %s (%s mm)", whole.element_size, system.length_label, size
        )
        return float(size)
    raise StageFailure(
        "mesh_failed",
        "요소 크기가 없습니다 — 스펙에 넣거나 CAD 가 「전체」 메시 힌트를 보내야 합니다.",
    )


def _local_sizes(
    step: Path,
    workdir: Path,
    topology: dict[str, Any],
    given: condition_model.Conditions,
    system: units.UnitSystem,
    size: float,
    second_order: bool,
    timeout_seconds: int,
    *,
    fragment: bool = True,
) -> dict[int, float]:
    """영역별 메시 힌트 → **면 번호 → 크기(mm)**.

    힌트는 영역 **이름**으로 오고 gmsh 는 면 **번호**로 받는다. 그 번호는 메시를 만들어 봐야
    아는 면 지문에서 나오므로, **면만 먼저 한 번 메시한다**(2차원, 빠르다). 힌트가 없으면 이
    통과를 건너뛴다 — 공짜가 아니기 때문이다.
    """
    wanted = {
        hint.region: hint.element_size * system.length_mm
        for hint in given.mesh_hints
        if hint.element_size is not None and hint.region not in ("전체", "all")
    }
    if not wanted or not topology:
        return {}
    try:
        rough = build_mesh(
            step,
            workdir,
            element_size_mm=size,
            second_order=second_order,
            timeout_seconds=timeout_seconds,
            surface_only=True,
            fragment=fragment,
        )
        found = match_regions(topology, rough.faces, wanted_regions=list(wanted))
    except StageFailure:
        # **힌트를 못 걸어도 해석은 한다** — 전역 크기로 풀린다. 다만 조용히 넘기지 않는다.
        logger.warning("영역별 메시 힌트를 못 걸었습니다 — 전역 크기로 갑니다", exc_info=True)
        return {}
    sizes: dict[int, float] = {}
    for name, ids in found.faces.items():
        for face in ids:
            sizes[face] = wanted[name]
        logger.info("메시 힌트 %s → 면 %s · %s mm", name, ids, wanted[name])
    for failure in found.failures:
        logger.warning("메시 힌트 %s 를 못 걸었습니다: %s", failure.region, failure.reason)
    return sizes


def _contact_faces(
    topology: dict[str, Any], given: condition_model.Conditions, mesh: Any
) -> dict[str, list[tuple[int, str]]]:
    """접촉 쌍이 가리키는 영역 → **요소면**. CalculiX 가 접촉면을 그렇게 받는다.

    접합면은 **양쪽이 다 와야 한다**(판쪽 · 기둥쪽). 메시를 쪼개면 둘이 한 면으로 합쳐져 한쪽이
    안 풀리는데, 접촉을 쓸 때는 쪼개지 않으므로 둘 다 풀린다.
    """
    wanted = sorted(
        {one.source for one in given.contacts} | {one.target for one in given.contacts}
    )
    if not wanted or not topology:
        return {}
    found = match_regions(topology, mesh.faces, wanted_regions=wanted)
    if found.failures:
        raise StageFailure(
            "internal",
            "접촉면을 못 찾았습니다: "
            + " · ".join(f"{one.region}({one.reason})" for one in found.failures)
            + f". {MESH_LIMIT}",
        )
    lookup = element_faces(mesh)
    rows: dict[str, list[tuple[int, str]]] = {}
    for name, ids in found.faces.items():
        members: list[tuple[int, str]] = []
        for face in ids:
            for triangle in mesh.face_triangles.get(face, []):
                hit = lookup.get(frozenset(triangle))
                if hit is not None:
                    members.append(hit)
        rows[name] = members
        logger.info("접촉면 %s → 면 %s · 요소면 %s", name, ids, len(members))
    return rows


def _region_shapes(topology: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """영역 이름 → **CAD 가 보낸 지문 한 장**(첫 항목).

    원통 지지의 축 · 베어링 하중의 축이 거기 있다. 메시에서 되맞출 수도 있지만 **선언이
    정본이다** — 사람이 의도한 축이 그쪽이고, 되맞춘 축은 부호가 뒤집힐 수 있다.
    """
    found: dict[str, dict[str, Any]] = {}
    for name, rows in (topology.get("regions") or {}).items():
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            found[name] = rows[0]
    return found


def _load_places(
    topology: dict[str, Any], given: condition_model.Conditions, mesh: Any
) -> tuple[dict[str, set[int]], dict[str, dict[int, float]], dict[str, list[tuple[int, str]]]]:
    """하중이 가리키는 영역을 절점 · 분담 면적 · **요소면**으로 바꾼다.

    압력은 요소면에 걸고(`*DLOAD`), 힘은 절점에 나눠 건다(`*CLOAD`) — CalculiX 가 그렇게
    받는다.
    면을 찾는 일은 구속과 똑같이 `app/core/regions` 가 한다.
    """
    wanted = [load.region for load in given.loads if load.region]
    if not wanted or not topology:
        return {}, {}, {}
    found = match_regions(topology, mesh.faces, wanted_regions=wanted)
    if found.failures:
        raise StageFailure(
            "internal",
            "하중을 걸 면을 못 찾았습니다: "
            + " · ".join(f"{one.region}({one.reason})" for one in found.failures)
            + f". {MESH_LIMIT}",
        )
    lookup = element_faces(mesh)
    places: dict[str, set[int]] = {}
    areas: dict[str, dict[int, float]] = {}
    faces: dict[str, list[tuple[int, str]]] = {}
    for name, ids in found.faces.items():
        members: set[int] = set()
        for face in ids:
            members |= mesh.face_nodes.get(face, set())
        places[name] = members
        areas[name] = tributary_areas(mesh, ids)
        rows: list[tuple[int, str]] = []
        for face in ids:
            for triangle in mesh.face_triangles.get(face, []):
                hit = lookup.get(frozenset(triangle))
                if hit is not None:
                    rows.append(hit)
        faces[name] = rows
        logger.info(
            "하중 영역 %s → 면 %s · 절점 %s · 요소면 %s", name, ids, len(members), len(rows)
        )
    return places, areas, faces


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
