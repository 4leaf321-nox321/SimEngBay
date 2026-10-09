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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from app.core import conditions as condition_model
from app.core import materials as material_model
from app.core import units
from app.core.bodies import match_bodies, place_settings, without
from app.core.calculix import deck as deck_writer
from app.core.calculix.mesh import build_mesh, element_faces, probe_volumes, tributary_areas
from app.core.harmonic import harmonic_plan
from app.core.regions import match_regions
from app.core.spec import RIGID_BODY_MODES, HarmonicSpec, ModalSpec, StaticSpec
from app.core.stages import MIDSURFACE_NAME, ArtifactSpec, StageFailure, StageResult
from app.core.statics import static_plan

logger = logging.getLogger(__name__)

#: 받을 수 있는 스펙 — 레시피 판정은 아래 `build` 가 한다(지금은 모달뿐).
AnySpec = ModalSpec | StaticSpec | HarmonicSpec

BOUNDARY_NAME = "boundary.json"
#: 면을 못 찾았을 때 덧붙이는 말. 넓이 · 중심은 **형상에서** 재고(`mesh.measure`), 곡면의
#: 반지름 · 축은 메시에서 되맞춘다(`_classify`) — 그래도 못 찾으면 CAD 의 지문과 형상이 다른
#: 것이다. 전에는 「곡면 지문은 못 푼다」 고 적었는데, 곡면을 되맞춘 뒤로는 틀린 말이었고
#: 넓이로 막힌 평면에도 그렇게 적었다(2026-10-07 — 굽힘 시험의 지름 1 mm 대칭점).
MESH_LIMIT = (
    "CAD 가 보낸 면 지문과 형상의 면이 맞지 않습니다 — CAD 폴더를 지금 형상으로 다시 "
    "내보냈는지 보세요."
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
    #
    # **변위로 당기는 시험도 접촉을 쓴다**(`given.driven`) — 하중만 보던 때는 뽑힘 시험의 마찰
    # 접촉이 붙은 것으로 풀렸다(반력 22.3 kN — 마찰로 풀면 15.8 kN, 2026-10-08).
    #
    # **강체 파트에 닿는 마찰도 접촉으로 푼다**(2026-10-08). 전에는 붙여서 풀었는데, 시편이
    # 지지점에서 미끄러지지도 돌지도 못해 4점 굽힘(보드굽힘)의 반력이 손셈의 16배였다(9,966 N —
    # 손셈 약 600 N, 처짐 4.2 · 5.85 mm). 강체 면을 접촉의 독립(master) 쪽에 두면 풀린다 —
    # 요소 3 mm 에서 715 N · 6.0 mm(`_rigid_contact_regions`, `deck.contact_block`).
    static_driven = isinstance(spec, StaticSpec) and given.driven
    frictional = [one for one in given.contacts if one.kind in deck_writer.NONLINEAR_CONTACTS]
    use_contact = static_driven and bool(frictional)
    # **큰 변형은 사람이 적었으면 그것, 비웠으면 CAD 가 적은 것이다**(`statics.static_plan`).
    statics = static_plan(spec, given) if isinstance(spec, StaticSpec) else None
    large = statics.large_deflection if statics is not None else False
    # 1차 통과도 **같은 쪼개기 규칙**을 따른다 — 안 그러면 접합면 두 장이 하나로 합쳐져서 한쪽
    # 면에 걸린 메시 힌트가 「법선이 180도 틀어져 있다」 로 빠진다(실측 2026-10-03).
    # **파트별 설정** — 뺄 파트 · 파트 크기는 메시 전에 정한다(`mesh.py` 머리말).
    layout = _layout(
        step,
        workdir,
        topology,
        given,
        system,
        second_order,
        timeout_seconds,
        fragment=not use_contact,
        size=size,
    )
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
        layout=layout,
    )
    mesh = build_mesh(
        step,
        workdir,
        element_size_mm=size,
        second_order=second_order,
        timeout_seconds=timeout_seconds,
        local_sizes=local,
        fragment=not use_contact,
        removed=layout.removed,
        volume_sizes=layout.sizes,
        shell_step=layout.shell_step,
        shell_sizes=layout.shell_sizes,
    )
    logger.info(
        "메시: 절점 %s · 요소 %s · 면 %s · 솔리드 %s",
        len(mesh.nodes),
        mesh.element_count,
        len(mesh.faces),
        len(mesh.solids),
    )

    # 뺀 파트는 메시에 없다 — 짝짓기 · 물성은 **남은 파트로만** 본다.
    kept = without(topology, given.suppressed | set(given.shells))
    body_of, materials, material_from = _materials(spec, kept, system, mesh)
    mesh = _with_face_parts(mesh, body_of)
    rigid = _rigid(kept, given, mesh)
    # **강체 파트의 접촉면은 독립(master) 쪽에 둔다**(`deck.contact_block`).
    masters = (
        _rigid_contact_regions(topology, given, mesh, rigid)
        if rigid and use_contact
        else set()
    )
    # **쉘 파트의 영역은 중간면에서 찾는다**(지문의 `mid`) — 뒤의 짝짓기가 모두 이 판을 본다.
    topology = (
        condition_model.shell_view(topology, set(given.shells)) if topology else topology
    )
    shells = _shell_sections(spec, kept, system, given, layout, mesh)
    ties, rigid, tied = _ties(topology, given, mesh, shells, rigid)
    if tied:
        # 쉘을 잇는 접촉은 따로 건다(`*TIE` · 강체) — 덱의 「절점 공유로 붙였다」 줄에서 뺀다.
        given = replace(
            given, contacts=[one for one in given.contacts if one.name not in tied]
        )
    held = _held_nodes(topology, given, mesh)
    constrained = plan_constrained(given, spec)
    shapes = _region_shapes(topology)
    # 원격점 자리 — 세 레시피가 같은 것을 쓴다(`deck._holds`). 강제 변위는 선언된 단위계의
    # 길이로 오므로 `system.length_mm` 을 함께 준다.
    centers = _region_centers(topology)
    refused_loads: list[condition_model.Note] = []
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
            rigid=rigid,
            shells=shells,
            ties=ties,
            centers=centers,
            length_mm=system.length_mm,
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
            masters=masters,
            element_size_mm=size,
            large_deflection=large,
            substeps=statics.substeps if statics is not None else None,
            second_order=mesh.second_order,
            rigid=rigid,
            shells=shells,
            ties=ties,
            centers=centers,
            length_mm=system.length_mm,
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
                rigid=rigid,
                shells=shells,
                ties=ties,
                centers=centers,
                length_mm=system.length_mm,
            )
            preload = ahead.load_rows or None
            # **앞 정적 단계가 못 건 하중은 이 해석의 답을 바꾼다** — 조이는 하중이 빠진 채
            # 선응력 모달이 돌면 그냥 모달과 같은 값이 그럴듯하게 나온다. 그래서 막는다.
            # 구속 · 접촉의 말은 모달 덱이 똑같이 하고, 「하중이 없다」 는 접촉만 있는
            # 모달에서는 뜻이 없다 — 하중의 말만 옮긴다.
            refused_loads = [one for one in ahead.refused if one.what.startswith("하중 「")]
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
            rigid=rigid,
            shells=shells,
            ties=ties,
            centers=centers,
            length_mm=system.length_mm,
        )
    plan.skipped += layout.skipped
    plan.refused += refused_loads
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
        if plan.reaction_offsets:
            # 관성 하중이 반력 절점에 얹은 몫 — 읽을 때 더한다(`deck._inertia_offsets`).
            boundary["reaction_offsets"] = plan.reaction_offsets
    # **측정점이 어느 바디의 것인가** — 같은 자리에 두 바디의 꼭짓점이 겹치면(이음 입구) 바디로
    # 갈라야 미끄럼을 잴 수 있다. 추출이 그 바디의 절점 안에서만 가장 가까운 것을 찾는다.
    boundary["bodies"] = {name: entity for name, entity in body_of.items()}
    if shells:
        # **결과를 읽을 때 쉘을 접는다**(`frd.read_folded`) — 펼친 절점은 두께의 절반 안이다.
        boundary["shells"] = {
            "surfaces": sorted(layout.shell_parts),
            # 그림의 파트 이름 — 화면이 쉘 파트를 이름으로 보이고 숨긴다(`vtp.parted`).
            "parts": {str(surface): name for surface, name in layout.shell_parts.items()},
            "reach": round(0.55 * max(one.thickness for one in shells), 6),
        }
    # **실제로 붙인 물성 이름** — 결과에 스펙 이름을 적으면 CAD 물성으로 푼 것을 숨긴다.
    boundary["material"] = " · ".join(dict.fromkeys(one.name for one in materials))
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
    if shells:
        mass = round((mass or 0.0) + _shell_mass(shells, mesh.nodes), 4)
    return StageResult(
        artifacts=[ArtifactSpec("dat", path)],
        summary={
            "solver": "calculix",
            "bodies": len(mesh.solids),
            **(
                {"suppressed_bodies": " · ".join(sorted(given.suppressed))}
                if layout.removed
                else {}
            ),
            **({"rigid_bodies": " · ".join(one.part for one in rigid)} if rigid else {}),
            **(
                {
                    "shell_bodies": " · ".join(
                        f"{one.part} {one.thickness:g} mm" for one in shells
                    )
                }
                if shells
                else {}
            ),
            "nodes": len(mesh.nodes),
            "elements": mesh.element_count,
            **({"modes_requested": spec.modes} if isinstance(spec, ModalSpec) else {}),
            "mesh_order": "quadratic" if mesh.second_order else "linear",
            # **실제로 쓴 전역 요소 크기**(mm) — 메시 수렴 점검이 이것을 기준으로 줄인다.
            "element_size_mm": round(size, 6),
            # 비선형 접촉을 넣었나 — **그때 접촉 강성이 요소 크기를 따라간다**
            # (`contact_stiffness`). 크기를 바꾸면 메시와 접촉 모델이 함께 바뀐다 — 수렴
            # 점검이 그 사실을 적는다.
            **({"contact_pairs": True} if use_contact else {}),
            # 「큰 변형」 을 받아 기하 비선형으로 풀었나(`deck.write_static`).
            **(
                {"large_deflection": True, "large_deflection_from": statics.source}
                if large and statics is not None
                else {}
            ),
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
        found = condition_model.read(topology, recipe=spec.recipe)
    except ValueError as failure:
        raise StageFailure("internal", f"조건을 읽지 못했습니다: {failure}") from failure
    if found.refused:
        # **못 거는 조건이 있으면 멈춘다** — Ansys 경로와 같다. 전에는 여기서 안 봐서 모르는
        # 구속 · 점 파일에 없는 영역이 **조용히 빠진 채** 풀렸다(2026-10-04 에 들켰다).
        raise StageFailure(
            "region_unresolved",
            "CAD 가 보낸 조건 중 아직 걸 수 없는 것이 있습니다: "
            + " · ".join(f"{one.what} — {one.why}" for one in found.refused),
            details={"refused": [{"what": one.what, "why": one.why} for one in found.refused]},
        )
    # **비례 정련** — 메시 수렴 점검이 전체 크기와 같은 비율로 CAD 의 파트 · 면 크기를 줄인다.
    return condition_model.scaled(found, spec.mesh.local_scale)


def _materials(
    spec: AnySpec,
    topology: dict[str, Any],
    system: units.UnitSystem,
    mesh: Any,
) -> tuple[dict[str, int], list[material_model.Material], str]:
    """바디마다 물성 — **CAD 가 보낸 것이 먼저**고, 없으면 스펙의 한 벌을 전체에 건다.

    규칙은 Ansys 경로(`mechanical/build.py` 의 `_apply_material`)와 같다 — 같은 폴더를 두
    솔버로 풀면 같은 바디에 같은 물성이 붙어야 한다. **솔리드마다 물성이 꼭 하나 붙는다**:
    못 붙이면 멈춘다. 덱에서 빠진 솔리드는 오류 없이 사라지고, 그 결과는 그럴듯하게 틀린다.
    """
    found: list[material_model.Material] = []
    if topology and spec.material_from == "cad":
        try:
            found = material_model.read(topology, system)
        except material_model.MaterialProblem as failure:
            raise StageFailure("internal", str(failure)) from failure
    solids = sorted(mesh.solids)
    matched = match_bodies(topology, mesh.bodies) if topology else None
    # **짝지은 이름을 쓴다** — 측정점이 그 이름으로 바디를 가른다(`probes.locate`). 못 짝지은
    # 솔리드는 번호로 부른다.
    name_of = {entity: name for name, entity in (matched.bodies if matched else {}).items()}

    def key(entity: int) -> str:
        return name_of.get(entity) or f"solid{entity}"

    body_of = {key(entity): entity for entity in solids}
    if not found:
        if spec.material is None:
            raise StageFailure(
                "internal",
                "물성이 없습니다 — CAD 가 물성을 보내지 않았고 스펙에도 없습니다.",
            )
        # 스펙 물성 — 솔리드 전부에 같은 것을 건다.
        one = material_model.Material(
            name=spec.material.name,
            youngs_modulus_pa=spec.material.youngs_modulus_gpa * 1e9,
            poisson_ratio=spec.material.poisson_ratio,
            density_kg_m3=spec.material.density_kg_m3,
            bodies=tuple(body_of),
            source="spec",
        )
        return body_of, [one], "spec"

    if len(found) == 1 and (found[0].every_body or len(solids) == 1):
        # 한 벌이면 짝짓지 않아도 모두에 붙는다(Ansys 경로와 같다).
        return body_of, [replace(found[0], bodies=tuple(body_of))], "cad"

    # **파트마다 다른 물성** — 부피 · 무게중심으로 짝지은 이름으로 찾는다.
    if matched is None or matched.failures:
        raise StageFailure(
            "internal",
            "메시의 솔리드와 CAD 바디를 짝짓지 못했습니다: "
            + " · ".join(matched.failures if matched else ["점 파일이 없습니다"]),
        )
    members: dict[int, list[str]] = {}
    for entity in solids:
        name = name_of.get(entity, "")
        chosen = material_model.for_body(found, name) if name else None
        if chosen is None:
            raise StageFailure(
                "internal",
                f"솔리드 {entity}"
                + (f"({name})" if name else "")
                + " 에 붙일 물성이 없습니다 — CAD 가 이 파트에 재료를 지정하지 않았습니다.",
                details={
                    "bodies": list(matched.bodies),
                    "materials": [one.name for one in found],
                },
            )
        members.setdefault(found.index(chosen), []).append(key(entity))
    made = [
        replace(found[index], bodies=tuple(names)) for index, names in sorted(members.items())
    ]
    return body_of, made, "cad"


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


@dataclass
class _Layout:
    """파트별 설정을 메시에 옮긴 것 — gmsh 부피 번호로."""

    removed: frozenset[int] = frozenset()
    """해석에서 뺄 부피."""
    sizes: dict[int, float] = field(default_factory=dict)
    """부피 → 파트 요소 크기(mm)."""
    shell_step: Path | None = None
    """중간면 형상 — 쉘 파트가 있을 때만."""
    shell_sizes: dict[int, float] = field(default_factory=dict)
    """중간면의 면 번호 → 요소 크기(mm)."""
    shell_parts: dict[int, str] = field(default_factory=dict)
    """중간면의 면 번호 → 쉘 파트 이름."""
    skipped: list[condition_model.Note] = field(default_factory=list)
    """CalculiX 가 못 따르는 파트 메시 칸 — 바람이므로 멈추지 않고 적는다."""


def _layout(
    step: Path,
    workdir: Path,
    topology: dict[str, Any],
    given: condition_model.Conditions,
    system: units.UnitSystem,
    second_order: bool,
    timeout_seconds: int,
    *,
    fragment: bool = True,
    size: float = 5.0,
) -> _Layout:
    """파트별 설정 → **뺄 부피 · 부피별 크기**. 메시 전에 gmsh 로 부피를 재서 짝짓는다
    (`probe_volumes`). 뺄 것도 크기도 없으면 그 통과를 건너뛴다."""
    made = _Layout()
    global_order = "quadratic" if second_order else "linear"
    whole = given.whole_mesh
    if whole is not None and whole.method not in ("", "automatic", "tetrahedrons"):
        made.skipped.append(
            condition_model.Note(
                f"메시 「전체」 요소 형상({whole.method})",
                "CalculiX 경로(gmsh)는 사면체만 만듭니다 — 사면체로 풀었습니다.",
            )
        )
    order_note = condition_model.whole_order_note(given, global_order)
    if order_note is not None:
        made.skipped.append(order_note)
    for one in given.body_settings:
        if one.suppressed or one.rigid:
            continue
        if one.method not in ("automatic", "tetrahedrons"):
            made.skipped.append(
                condition_model.Note(
                    f"파트 「{one.name}」 요소 형상({one.method})",
                    "CalculiX 경로(gmsh)는 사면체만 만듭니다 — 사면체로 풀었습니다.",
                )
            )
        if one.order not in ("program_controlled", global_order):
            made.skipped.append(
                condition_model.Note(
                    f"파트 「{one.name}」 요소 차수({one.order})",
                    "CalculiX 경로는 파트마다 차수를 달리하지 못합니다 — 전체 차수"
                    f"({'2차' if second_order else '1차'})로 풀었습니다.",
                )
            )
    wanted = [
        one
        for one in given.body_settings
        if one.suppressed or one.shell or one.element_size is not None
    ]
    if not wanted:
        return made
    shells = given.shells
    if shells:
        made.shell_step = workdir / MIDSURFACE_NAME
        if not made.shell_step.is_file():
            raise StageFailure(
                "internal",
                f"쉘 파트({' · '.join(sorted(shells))})가 있는데 중간면 형상"
                f"({MIDSURFACE_NAME})이 작업에 없습니다 — CAD 폴더의 pNNNN_mid.step 을 함께 "
                "올려야 합니다.",
            )
    probe = probe_volumes(
        step,
        workdir,
        fragment=fragment,
        timeout_seconds=min(timeout_seconds, 300),
        shell_step=made.shell_step,
    )
    records = probe.volumes
    placed, failures = place_settings(wanted, topology, records)
    if failures:
        raise StageFailure(
            "internal",
            "파트별 설정의 파트를 형상에서 찾지 못했습니다: " + " · ".join(failures),
            details={"failures": failures},
        )
    # 쉘 파트의 솔리드도 지운다 — 그 자리는 중간면의 쉘이 맡는다.
    made.removed = frozenset(tag for tag, one in placed.items() if one.suppressed or one.shell)
    if made.removed and len(made.removed) == len(records) and not shells:
        raise StageFailure(
            "internal", "모든 파트가 해석에서 제외되었습니다 — 풀 것이 없습니다."
        )
    made.sizes = {
        tag: one.element_size * system.length_mm
        for tag, one in placed.items()
        if not (one.suppressed or one.shell) and one.element_size is not None
    }
    if shells:
        made.shell_parts = _shell_parts(probe.surfaces, topology, set(shells))
        wished = {
            one.name: one.element_size * system.length_mm
            for one in given.body_settings
            if one.element_size is not None
        }
        made.shell_sizes = {
            tag: wished.get(name, size) for tag, name in made.shell_parts.items()
        }
    for tag, one in sorted(placed.items()):
        logger.info("파트 %s → 부피 %s · %s", one.name, tag, one.describe())
    return made


def _shell_parts(
    surfaces: list[Any], topology: dict[str, Any], names: set[str]
) -> dict[int, str]:
    """중간면의 면 → 쉘 파트. **점 파일 `midsurface.bodies[]` 의 경계상자 · 무게중심으로**
    가른다(CompCore v0.8.1 — `_mid.step` 의 셸에는 이름이 없다). 파트마다 넓이를 맞춰 본다 —
    어긋나면 다른 판을 집은 것이다."""
    rows = [
        one
        for one in (topology.get("midsurface") or {}).get("bodies") or []
        if isinstance(one, dict) and str(one.get("name") or "") in names
    ]
    if not rows:
        raise StageFailure("internal", "점 파일에 중간면(midsurface.bodies)이 없습니다.")

    def inside(point: tuple[float, float, float], box: Any) -> bool:
        try:
            low, high = box
            return all(low[axis] - 0.5 <= point[axis] <= high[axis] + 0.5 for axis in range(3))
        except (TypeError, ValueError, IndexError):
            return False

    def gap(point: tuple[float, float, float], row: dict[str, Any]) -> float:
        centre = row.get("centroid") or [0.0, 0.0, 0.0]
        return sum((point[axis] - float(centre[axis])) ** 2 for axis in range(3))

    found: dict[int, str] = {}
    for surface in surfaces:
        holders = [one for one in rows if inside(surface.centroid, one.get("bbox"))]
        pick = min(holders or rows, key=lambda one: gap(surface.centroid, one))
        found[surface.index] = str(pick["name"])
    for row in rows:
        area = sum(one.volume for one in surfaces if found.get(one.index) == row["name"])
        wanted = float(row.get("area") or 0.0)
        if wanted and abs(area - wanted) / wanted > 0.02:
            raise StageFailure(
                "internal",
                f"쉘 파트 「{row['name']}」 의 중간면 넓이가 맞지 않습니다(형상 {area:.1f} · "
                f"점 파일 {wanted:.1f} mm²) — 다른 판을 집었을 수 있습니다.",
            )
        logger.info(
            "쉘 %s → 면 %s · 넓이 %.1f mm²",
            row["name"],
            sorted(tag for tag, name in found.items() if name == row["name"]),
            area,
        )
    return found


def _shell_sections(
    spec: AnySpec,
    topology: dict[str, Any],
    system: units.UnitSystem,
    given: condition_model.Conditions,
    layout: _Layout,
    mesh: Any,
) -> list[deck_writer.ShellSection]:
    """쉘 파트마다 요소 · 두께 · 물성. 물성은 솔리드와 같은 규칙(CAD 가 먼저)이다."""
    if not layout.shell_parts:
        return []
    found: list[material_model.Material] = []
    if topology and spec.material_from == "cad":
        try:
            found = material_model.read(topology, system)
        except material_model.MaterialProblem as failure:
            raise StageFailure("internal", str(failure)) from failure
    names = sorted(set(layout.shell_parts.values()))
    on_part = material_model.assigned(found, names) if found else {}
    made: list[deck_writer.ShellSection] = []
    for index, name in enumerate(names, start=1):
        material = on_part.get(name)
        if material is None and not found and spec.material is not None:
            material = material_model.Material(
                name=spec.material.name,
                youngs_modulus_pa=spec.material.youngs_modulus_gpa * 1e9,
                poisson_ratio=spec.material.poisson_ratio,
                density_kg_m3=spec.material.density_kg_m3,
                bodies=(name,),
                source="spec",
            )
        if material is None:
            raise StageFailure("internal", f"쉘 파트 「{name}」 에 붙일 물성이 없습니다.")
        elements = [
            row
            for tag, part in sorted(layout.shell_parts.items())
            if part == name
            for row in mesh.shells.get(tag, [])
        ]
        if not elements:
            raise StageFailure(
                "mesh_failed", f"쉘 파트 「{name}」 의 중간면에 요소가 없습니다."
            )
        made.append(
            deck_writer.ShellSection(
                part=name,
                name=f"SHELL{index}",
                elements=elements,
                thickness=given.shells[name],
                material=material,
            )
        )
    return made


def _ties(
    topology: dict[str, Any],
    given: condition_model.Conditions,
    mesh: Any,
    shells: list[deck_writer.ShellSection],
    rigid: list[deck_writer.RigidBody],
) -> tuple[list[deck_writer.Tie], list[deck_writer.RigidBody], set[str]]:
    """쉘이 낀 접촉 → `*TIE`. 쉘 쪽이 종(절점), 솔리드 쪽이 주(요소면)다. 쉘끼리 · 비선형
    접촉은 아직 못 건다(멈춘다). 돌려주는 것: 묶음 · 고친 강체 · 처리한 접촉 이름.

    **상대가 강체면 `*TIE` 를 쓰지 않고 쉘 절점을 그 강체에 넣는다** — 강체에 붙은 것은
    강체와 함께 움직이므로 같은 뜻이다. `*TIE` 로 강체 표면에 묶으면 구속이 사슬(쉘 → 강체
    표면 절점 → 기준점)이 되어, ccx 가 기준점 반력에 그 몫을 넣지 않았다(실측 2026-10-04:
    처짐은 맞는데 반력 0).
    """
    if not shells or not given.contacts:
        return [], rigid, set()
    shell_faces = set(mesh.shells)
    wanted = sorted(
        {one.source for one in given.contacts} | {one.target for one in given.contacts}
    )
    found = match_regions(topology, mesh.faces, wanted_regions=wanted)
    lookup = element_faces(mesh)
    thickest = max(one.thickness for one in shells)
    made: list[deck_writer.Tie] = []
    held = list(rigid)
    handled: set[str] = set()
    for index, pair in enumerate(given.contacts, start=1):
        ends = (found.faces.get(pair.source) or [], found.faces.get(pair.target) or [])
        on_shell = [bool(ids) and all(one in shell_faces for one in ids) for ids in ends]
        if not any(on_shell):
            continue
        if all(on_shell):
            raise StageFailure(
                "internal", f"접촉 「{pair.name}」: 쉘끼리의 접촉은 아직 못 겁니다."
            )
        if pair.kind != "bonded":
            raise StageFailure(
                "internal",
                f"접촉 「{pair.name}」({pair.kind}): 쉘이 낀 접촉은 본딩만 겁니다 — 솔버를 "
                "ansys 로 바꾸세요.",
            )
        sheet, solid = (ends[0], ends[1]) if on_shell[0] else (ends[1], ends[0])
        slaves: set[int] = set()
        for face in sheet:
            slaves |= mesh.face_nodes.get(face, set())
        masters: list[tuple[int, str]] = []
        for face in solid:
            for triangle in mesh.face_triangles.get(face, []):
                hit = lookup.get(frozenset(triangle))
                if hit is not None:
                    masters.append(hit)
        if not slaves or not masters:
            raise StageFailure(
                "internal", f"접촉 「{pair.name}」: 쉘과 솔리드의 맞닿은 면을 못 찾았습니다."
            )
        handled.add(pair.name)
        corners = {node for element, _ in masters for node in _corner_nodes(mesh, element)}
        owner = next(
            (index for index, one in enumerate(held) if corners and corners <= one.nodes), None
        )
        if owner is not None:
            held[owner] = replace(held[owner], nodes=held[owner].nodes | frozenset(slaves))
            logger.info(
                "접촉 %s → 쉘 절점 %s 를 강체 %s 에 넣었습니다",
                pair.name,
                len(slaves),
                held[owner].part,
            )
            continue
        made.append(
            deck_writer.Tie(
                contact=pair.name,
                name=f"TIE{index}",
                slave_nodes=frozenset(slaves),
                master_faces=masters,
                # 중간면은 두께의 절반만큼 떨어져 있다 — 넉넉히 두께만큼 본다.
                tolerance=thickest,
            )
        )
        logger.info(
            "접촉 %s → TIE 쉘 절점 %s · 솔리드 요소면 %s", pair.name, len(slaves), len(masters)
        )
    return made, held, handled


def _corner_nodes(mesh: Any, element: int) -> list[int]:
    """사면체 요소의 절점(그 번호의 요소를 솔리드에서 찾는다)."""
    for rows in mesh.solids.values():
        for number, ids in rows:
            if number == element:
                return list(ids)
    return []


def _rigid(
    topology: dict[str, Any], given: condition_model.Conditions, mesh: Any
) -> list[deck_writer.RigidBody]:
    """강체 파트 → 덱의 강체 묶음. **강체끼리 맞닿으면 멈춘다** — 한 절점이 두 강체에 묶이면
    ccx 가 거절하고, Ansys 도 강체끼리의 접촉을 받지 않는다."""
    wanted = [one for one in given.body_settings if one.rigid and not one.suppressed]
    if not wanted:
        return []
    placed, failures = place_settings(wanted, topology, mesh.bodies)
    if failures:
        raise StageFailure(
            "internal",
            "강체 파트를 메시에서 찾지 못했습니다: " + " · ".join(failures),
            details={"failures": failures},
        )
    # 단품(「전체」)이 솔리드 여럿에 붙으면 이름이 겹친다 — 번호를 덧붙인다.
    picked = {
        (one.name if len(placed) == 1 else f"{one.name}#{tag}")
        if one.name == condition_model.ALL_BODIES
        else one.name: tag
        for tag, one in placed.items()
    }
    centroids = {one.index: one.centroid for one in mesh.bodies}
    made = deck_writer.rigid_bodies(mesh.nodes, mesh.solids, picked, centroids)
    for index, first in enumerate(made):
        for second in made[index + 1 :]:
            if first.nodes & second.nodes:
                raise StageFailure(
                    "internal",
                    f"강체 파트 「{first.part}」 · 「{second.part}」 가 맞닿아 있습니다 — "
                    "강체끼리는 아직 잇지 못합니다. 한쪽을 변형체로 두세요.",
                )
    return made


def _with_face_parts(mesh: Any, body_of: dict[str, int]) -> Any:
    """면마다 **그 면을 가진 파트 이름**을 단다(`FaceRecord.body`) — 짝짓기가 파트로 가른다.

    접촉을 쓰면 메시를 쪼개지 않아, 구멍에 같은 지름의 핀이 끼면 구멍면과 핀 옆면이 중심 ·
    반지름 · 축까지 같은 **두 면**으로 남는다. 파트를 안 보면 「구멍면」 자리에 핀 옆면을
    집는다(핀 베어링 D5961, 2026-10-08 — Ansys 경로가 먼저 밟았다). 두 파트가 나눠 가진
    면(쪼개 붙인 메시의 접합면)은 어느 쪽이라 할 수 없어 비워 둔다 — 그 면은 전처럼 모양으로만
    짝짓는다.
    """
    owners = {
        entity: {node for _, ids in rows for node in ids}
        for entity, rows in mesh.solids.items()
    }
    name_of = {entity: name for name, entity in body_of.items()}
    faces = []
    for face in mesh.faces:
        members = mesh.face_nodes.get(face.id) or set()
        found = [entity for entity, nodes in owners.items() if members and members <= nodes]
        if len(found) == 1 and found[0] in name_of:
            face = replace(face, body=name_of[found[0]])
        faces.append(face)
    return replace(mesh, faces=faces)


def _rigid_contact_regions(
    topology: dict[str, Any],
    given: condition_model.Conditions,
    mesh: Any,
    rigid: list[deck_writer.RigidBody],
) -> set[str]:
    """접촉면 중 **강체 파트의 것** — 접촉 쌍의 독립(master) 쪽에 둔다(`deck.contact_block`).

    양쪽이 다 강체면 멈춘다 — 둘 다 변형하지 않으니 접촉이 풀 것이 없고, 둘 다 독립 면이 될 수
    없다.
    """
    regions = sorted(
        {one.source for one in given.contacts} | {one.target for one in given.contacts}
    )
    if not regions:
        return set()
    found = match_regions(topology, mesh.faces, wanted_regions=regions)
    on_rigid: set[str] = set()
    for name, ids in found.faces.items():
        members: set[int] = set()
        for face in ids:
            members |= mesh.face_nodes.get(face, set())
        if any(members and members <= one.nodes for one in rigid):
            on_rigid.add(name)
    for pair in given.contacts:
        if pair.source in on_rigid and pair.target in on_rigid:
            raise StageFailure(
                "internal",
                f"접촉 「{pair.name}」 의 양쪽이 다 강체 파트의 면입니다 — 둘 다 변형하지 "
                "않아 풀 것이 없습니다. 한쪽 파트를 변형체로 두세요.",
            )
    return on_rigid


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
    layout: _Layout | None = None,
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
            # 뺀 파트를 같이 지워야 면 번호가 본 통과와 같다.
            removed=layout.removed if layout else frozenset(),
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


def _region_centers(topology: dict[str, Any]) -> dict[str, tuple[float, float, float]]:
    """영역 이름 → **면적 중심**(Σ 면적 x 중심 / Σ 면적, mm) — 원격점 자리다.

    Ansys 의 원격점(「centroid」)이 거기 선다. 면이 여럿이면 면적으로 무게를 준다 — 지문이
    재 둔 값이라 메시가 고르지 않아도 비켜나지 않는다(`deck._remote_points`). 면적이 없는
    지문이 하나라도 있으면 그 영역은 빼서 절점 평균으로 미룬다.
    """
    found: dict[str, tuple[float, float, float]] = {}
    for name, rows in (topology.get("regions") or {}).items():
        if not isinstance(rows, list) or not rows:
            continue
        total = 0.0
        moment = [0.0, 0.0, 0.0]
        for row in rows:
            area = row.get("area") if isinstance(row, dict) else None
            center = row.get("centroid") if isinstance(row, dict) else None
            if not isinstance(area, (int, float)) or area <= 0:
                break
            if not isinstance(center, list) or len(center) != 3:
                break
            total += area
            for axis in range(3):
                moment[axis] += area * float(center[axis])
        else:
            found[name] = (moment[0] / total, moment[1] / total, moment[2] / total)
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
        outer = _outer_normal(topology, name)
        for face in ids:
            if face in mesh.shells:
                # **쉘 요소는 면 하나다** — 압력은 요소 전체에 건다. 미는 쪽은 원래 겉면의 바깥
                # 법선의 반대(안쪽)다 — 요소 법선이 바깥 법선과 같은 쪽이면 부호를 뒤집는다
                # (ccx 의 쉘 압력은 법선 쪽으로 민다 — 덱의 `SHELL_PRESSURE_FLIPPED`).
                for number, ids_ in mesh.shells[face]:
                    along = _dot(_element_normal(mesh.nodes, ids_), outer) >= 0
                    rows.append(
                        (
                            number,
                            deck_writer.SHELL_PRESSURE_FLIPPED
                            if along
                            else deck_writer.SHELL_PRESSURE,
                        )
                    )
                continue
            for triangle in mesh.face_triangles.get(face, []):
                hit = lookup.get(frozenset(triangle))
                if hit is not None:
                    rows.append(hit)
        faces[name] = rows
        logger.info(
            "하중 영역 %s → 면 %s · 절점 %s · 요소면 %s", name, ids, len(members), len(rows)
        )
    return places, areas, faces


def _outer_normal(topology: dict[str, Any], region: str) -> tuple[float, float, float]:
    """쉘 영역의 **원래 겉면 바깥 법선**(`shell_view` 가 남긴 `outer_normal`). 없으면 +Z."""
    for row in (topology.get("regions") or {}).get(region) or []:
        if isinstance(row, dict) and isinstance(row.get("outer_normal"), list):
            x, y, z = (float(one) for one in row["outer_normal"][:3])
            return (x, y, z)
    return (0.0, 0.0, 1.0)


def _element_normal(
    nodes: dict[int, tuple[float, float, float]], ids: list[int]
) -> tuple[float, float, float]:
    """삼각형 요소의 법선(모서리 셋 — 절점 순서가 정한다)."""
    a, b, c = (nodes[one] for one in ids[:3])
    u = [b[axis] - a[axis] for axis in range(3)]
    v = [c[axis] - a[axis] for axis in range(3)]
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def _dot(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    return sum(one * two for one, two in zip(first, second, strict=True))


def _shell_mass(
    shells: list[deck_writer.ShellSection], nodes: dict[int, tuple[float, float, float]]
) -> float:
    """쉘의 질량(kg) — 요소 넓이 x 두께 x 밀도. 넓이는 모서리 셋으로 잰다(평면 요소)."""
    total = 0.0
    for sheet in shells:
        area = 0.0
        for _, ids in sheet.elements:
            x, y, z = _element_normal(nodes, ids)
            area += 0.5 * (x * x + y * y + z * z) ** 0.5
        # mm² x mm = mm³ → m³ 는 1e-9.
        total += area * sheet.thickness * 1e-9 * sheet.material.density_kg_m3
    return total


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
