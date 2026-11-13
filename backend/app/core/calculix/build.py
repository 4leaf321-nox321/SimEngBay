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
import math
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from app.core import conditions as condition_model
from app.core import materials as material_model
from app.core import units
from app.core.bodies import match_bodies, place_settings, without
from app.core.calculix import deck as deck_writer
from app.core.calculix.mesh import (
    Probe,
    boxes_meet,
    build_mesh,
    element_faces,
    fragment_owners,
    measure,
    overlaps,
    probe_volumes,
    tributary_areas,
)
from app.core.harmonic import harmonic_plan
from app.core.regions import match_regions
from app.core.regions.match import (
    AREA_TOLERANCE_RATIO,
    PLANE_TOLERANCE_MIN,
    PLANE_TOLERANCE_RATIO,
    RADIUS_TOLERANCE,
    axis_point,
    model_scale,
)
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
#: 형상 맞춤 허용오차의 기본(mm) — CompCore 형상 점검의 「바디 사이 틈」 기본값과 같다
#: (`checks.contact_gap`, 2026-11-13). 그 아래가 「CAD 가 남긴 틈」 이다(`_boolean_tolerance`).
BOOLEAN_TOLERANCE_MM = 0.001
#: 허용오차를 서버가 정할 때(mm). 0 이면 끈다 — 비우면 점 파일의 `checks.contact_gap`, 그것도
#: 없으면 위의 기본.
BOOLEAN_TOLERANCE_ENV = "CALCULIX_BOOLEAN_TOLERANCE_MM"


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
    loose = condition_model.sheet_gap(topology, given, from_cad=spec.conditions_from == "cad")
    if loose:
        raise StageFailure("region_unresolved", loose)

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
    # **맞닿은 마찰면은 메시를 나눈 채 그 면만 가른다**(2026-10-30, `_open_interfaces`). 본딩은
    # 절점 공유로 붙고 접촉 쌍은 마찰면 하나뿐이다 — 셋 다 접촉 쌍으로 걸던 볼트 조립(본딩 둘 +
    # 판 사이 마찰)은 첫 증분조차 12분에 못 넘었다. 강체 파트가 끼거나 면이 떨어져 있으면
    # 전처럼 쪼개지 않고 접촉 쌍으로 건다.
    opened = use_contact and _touching(topology, frictional, given)
    # **큰 변형은 사람이 적었으면 그것, 비웠으면 CAD 가 적은 것이다**(`statics.static_plan`).
    statics = static_plan(spec, given) if isinstance(spec, StaticSpec) else None
    large = statics.large_deflection if statics is not None else False
    fragment = not use_contact or opened
    # **형상 맞춤 허용오차** — 겹침 · 틈이 허용오차 안이면 쪼개기가 맞닿은 것으로 붙인다. 모든
    # 통과가 같은 값을 써야 번호가 같다(`mesh._head_lines`).
    tolerance = _boolean_tolerance(topology)
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
        fragment=fragment,
        size=size,
        tolerance=tolerance,
    )
    if fragment:
        layout.notes += _contact_notes(topology, tolerance)
    local = _local_sizes(
        step,
        workdir,
        topology,
        given,
        system,
        size,
        second_order,
        timeout_seconds,
        fragment=fragment,
        layout=layout,
        tolerance=tolerance,
    )
    mesh = build_mesh(
        step,
        workdir,
        element_size_mm=size,
        second_order=second_order,
        timeout_seconds=timeout_seconds,
        local_sizes=local,
        fragment=fragment,
        removed=layout.removed,
        volume_sizes=layout.sizes,
        shell_step=layout.shell_step,
        shell_sizes=layout.shell_sizes,
        sheets=layout.sheets,
        tolerance=tolerance,
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
    mesh = _with_face_parts(mesh, body_of, layout.shell_parts)
    rigid = _rigid(kept, given, mesh)
    # **강체 파트의 접촉면은 독립(master) 쪽에 둔다**(`deck.contact_block`).
    masters = (
        _rigid_contact_regions(topology, given, mesh, rigid)
        if rigid and use_contact and not opened
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
    # 탄성 · 압축 전용 지지의 법선 요소 · 볼트 예압의 단면 — 세 레시피가 같은 것을 쓴다(덱이
    # 고른다).
    springs = _support_springs(topology, given, mesh)
    stress_mpa = system.stress_pa / units.STRESS_UNITS["mpa"]
    # 볼트는 메시를 가른다 — 정적과 선응력 모달이 같은 갈라진 메시를 쓴다(조화는 볼트를 안
    # 건다 — 덱이 까닭을 단다).
    bolts, nodes, solids = (
        _cut_bolts(topology, given, mesh, shapes, body_of, system.length_mm)
        if not isinstance(spec, HarmonicSpec)
        else ({}, mesh.nodes, mesh.solids)
    )
    # 원격점 자리 — 세 레시피가 같은 것을 쓴다(`deck._holds`). 강제 변위는 선언된 단위계의
    # 길이로 오므로 `system.length_mm` 을 함께 준다.
    centers = _region_centers(topology)
    refused_loads: list[condition_model.Note] = []
    # 맞닿은 마찰면을 가르며 바꾼 절점 — 바디 → {원래: 새}(`_open_interfaces`).
    renamed: dict[str, dict[int, int]] = {}
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
            springs=springs,
            stress_mpa=stress_mpa,
            element_size_mm=size,
        )
    elif isinstance(spec, StaticSpec):
        places, areas, faces = _load_places(topology, given, mesh)
        touching: dict[str, list[tuple[int, str]]] | None = None
        if opened:
            nodes, solids, touching, renamed = _open_interfaces(
                topology, frictional, nodes, solids, body_of
            )
        plan = deck_writer.write_static(
            nodes=nodes,
            solids=solids,
            body_of=body_of,
            materials=materials,
            held_nodes=held,
            load_nodes=places,
            load_faces=faces,
            load_areas=areas,
            # 갈랐으면 접촉 쌍은 마찰면뿐이다 — 본딩은 절점 공유로 붙었다(아래에서 적는다).
            given=replace(given, contacts=frictional) if opened else given,
            shapes=shapes,
            contact_faces=(
                touching
                if opened
                else _contact_faces(topology, given, mesh)
                if use_contact
                else None
            ),
            pairing="NODE TO SURFACE" if opened else "SURFACE TO SURFACE",
            average_force=_average_force(given) if opened else None,
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
            springs=springs,
            stress_mpa=stress_mpa,
            bolts=bolts,
        )
        if opened:
            for pair in given.contacts:
                if pair.kind not in deck_writer.NONLINEAR_CONTACTS:
                    plan.skipped.append(
                        condition_model.Note(
                            f"접촉 「{pair.name}」({pair.kind})",
                            "맞닿은 면의 절점을 공유시켜 **붙은 것으로** 풀었습니다.",
                        )
                    )
    else:
        preload: list[str] | None = None
        bolt_stage: tuple[list[str], list[str], list[str]] | None = None
        contact_faces: dict[str, list[tuple[int, str]]] | None = None
        if use_contact or given.prestressed:
            # **선응력 모달** — 비선형 정적을 앞에 두고 그 상태에서 모드를 뽑는다. 하중 줄은
            # 정적 덱을 한 번 써서 얻는다(같은 하중을 두 벌로 적지 않는다).
            places, areas, faces = _load_places(topology, given, mesh)
            contact_faces = _contact_faces(topology, given, mesh) if use_contact else None
            ahead = deck_writer.write_static(
                nodes=nodes,
                solids=solids,
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
                springs=springs,
                stress_mpa=stress_mpa,
                bolts=bolts,
            )
            preload = ahead.load_rows or None
            if ahead.bolt_rows:
                bolt_stage = (ahead.bolt_model, ahead.bolt_rows, ahead.bolt_locks)
            # **앞 정적 단계가 못 건 하중은 이 해석의 답을 바꾼다** — 조이는 하중이 빠진 채
            # 선응력 모달이 돌면 그냥 모달과 같은 값이 그럴듯하게 나온다. 그래서 막는다.
            # 구속 · 접촉의 말은 모달 덱이 똑같이 하고, 「하중이 없다」 는 접촉만 있는
            # 모달에서는 뜻이 없다 — 하중의 말만 옮긴다.
            refused_loads = [one for one in ahead.refused if one.what.startswith("하중 「")]
        plan = deck_writer.write_modal(
            nodes=nodes,
            solids=solids,
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
            springs=springs,
            stress_mpa=stress_mpa,
            bolt_stage=bolt_stage,
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
    if plan.bolt_report:
        # **볼트 힘 · 조임량을 읽을 자리**(`static_read._bolts`).
        boundary["bolts"] = plan.bolt_report
    if plan.reaction_sets:
        # **반력을 읽을 자리** — 추출 단계가 `.dat` 의 합에서 영역 이름으로 되찾는다.
        boundary["reaction_sets"] = plan.reaction_sets
        if plan.reaction_offsets:
            # 관성 하중이 반력 절점에 얹은 몫 — 읽을 때 더한다(`deck._inertia_offsets`).
            boundary["reaction_offsets"] = plan.reaction_offsets
    # **측정점이 어느 바디의 것인가** — 같은 자리에 두 바디의 꼭짓점이 겹치면(이음 입구) 바디로
    # 갈라야 미끄럼을 잴 수 있다. 추출이 그 바디의 절점 안에서만 가장 가까운 것을 찾는다.
    boundary["bodies"] = {name: entity for name, entity in body_of.items()}
    if renamed:
        # 가른 마찰면 — 그 바디의 측정점은 새 번호를 읽는다(`probes.locate`). 추출은 가르기
        # 전 메시(`model.msh`)를 읽어 두 바디가 같은 절점을 쥔 것으로 본다.
        boundary["renamed"] = {
            name: {str(old): new for old, new in pairs.items()}
            for name, pairs in renamed.items()
        }
    if shells:
        # **결과를 읽을 때 쉘을 접는다**(`frd.read_folded`) — 펼친 절점은 두께의 절반 안이다.
        boundary["shells"] = {
            "surfaces": sorted(layout.shell_parts),
            # 그림의 파트 이름 — 화면이 쉘 파트를 이름으로 보이고 숨긴다(`vtp.parted`).
            "parts": {str(surface): name for surface, name in layout.shell_parts.items()},
            "reach": round(0.55 * max(one.thickness for one in shells), 6),
            # 파트마다 두께(mm) — 추출이 쉘의 부피(넓이 x 두께)로 모드 성격을 잰다.
            "thickness": {one.part: one.thickness for one in shells},
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
    by_body = _masses_kg(materials, body_of, mesh)
    if shells:
        by_body = {**(by_body or {}), **_shell_masses(shells, mesh.nodes)}
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
            # 형상 맞춤 허용오차(mm) — 이보다 작은 겹침 · 틈은 맞닿은 것으로 붙였다.
            **(
                {"boolean_tolerance_mm": round(tolerance, 6)} if tolerance and fragment else {}
            ),
            # **메시를 고친 것** — 곡률 크기로 다시 만들었다 · 뒤집힌 2차 요소를 폈다 · 겹침 ·
            # 틈을 붙였다. 사람이 준 크기 · 형상과 다르게 풀었으므로 숨기지 않는다.
            **(
                {"mesh_repairs": " · ".join([*layout.notes, *mesh.repairs])}
                if layout.notes or mesh.repairs
                else {}
            ),
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
            **material_model.mass_summary(by_body),
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
    """전역 요소 크기(mm). 스펙이 비면 **CAD 의 「전체」 힌트**, 그것도 없으면 **CompCore 의
    제안값**(`Conditions.global_size`).

    셋 다 없으면 멈춘다 — gmsh 는 크기를 안 주면 제 나름으로 잡고, 그러면 같은 형상이 실행마다
    다른 메시로 풀린다(설계점 비교가 무너진다).
    """
    if spec.mesh.element_size_mm is not None:
        return float(spec.mesh.element_size_mm)
    found = given.global_size(system.length_mm)
    if found is not None:
        size, source = found
        logger.info("메시 전체 크기 ← %s %s mm", source, size)
        return float(size)
    raise StageFailure(
        "mesh_failed",
        "요소 크기가 없습니다 — 스펙에 넣거나 CAD 가 「전체」 메시 힌트(또는 CompCore 의 "
        "제안값)를 보내야 합니다.",
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
    sheets: bool = False
    """본 형상에 시트 파트가 있다 — 메시 전에 지운다(`mesh._head_lines`)."""
    skipped: list[condition_model.Note] = field(default_factory=list)
    """CalculiX 가 못 따르는 파트 메시 칸 — 바람이므로 멈추지 않고 적는다."""
    notes: list[str] = field(default_factory=list)
    """메시를 사람이 준 것과 다르게 만든 것(겹침 · 틈 · 크기를 못 준 조각) — 결과에 적는다."""


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
    tolerance: float = 0.0,
) -> _Layout:
    """파트별 설정 → **뺄 부피 · 부피별 크기**. 메시 전에 gmsh 로 부피를 재서 짝짓는다
    (`probe_volumes`). 뺄 것도 크기도 없으면 그 통과를 건너뛴다."""
    made = _Layout(sheets=bool(condition_model.sheet_parts(topology)))
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
        sheets=made.sheets,
        tolerance=tolerance,
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
    if made.sizes and fragment:
        made.sizes = _sizes_after_fragment(
            step, workdir, made, probe, tolerance, min(timeout_seconds, 300)
        )
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


def _boolean_tolerance(topology: dict[str, Any]) -> float:
    """형상 맞춤 허용오차(mm) — 서버가 정했으면 그것, 아니면 **CompCore 형상 점검의 「바디
    사이 틈」**(점 파일의 `checks.contact_gap` — 가져올 때 `study.json` 에서 덧붙인다), 그것도
    없으면 0.001 mm.

    ⚠️ 없던 동안 0.01 mm 겹친 블록은 두께 0.01 조각 부피와 「ill-shaped tets」 를, 0.005 mm 뜬
       블록은 공유 절점 0개(떠 있는 블록)를 냈다(운영 보고, 2026-11-13).

    **설계 틈새를 닫으면 안 된다** — 대상이 핸드폰 부품이라 틈새가 0.05 ~ 0.2 mm 다. 처음에는
    모델 대각선 x 1e-4 로 셈했는데(판 100 mm 면 0.015) CompCore 가 「CAD 가 남긴 틈」 으로 보는
    0.001 과 어긋났다 — 두 쪽이 같은 값을 봐야 「CompCore 는 틈이라는데 해석은 붙였다」 가 안
    생긴다. 그보다 큰 겹침 · 틈은 CompCore 가 `quality.contacts` 로 알린다(`_contact_notes`).
    """
    given = os.environ.get(BOOLEAN_TOLERANCE_ENV, "").strip()
    if given:
        try:
            return max(0.0, float(given))
        except ValueError:
            logger.warning(
                "%s 가 수가 아닙니다(%r) — 점 파일의 기준을 씁니다",
                BOOLEAN_TOLERANCE_ENV,
                given,
            )
    checks = (topology or {}).get("checks")
    if isinstance(checks, dict):
        try:
            return max(0.0, float(checks["contact_gap"]))
        except (KeyError, TypeError, ValueError):
            pass
    return BOOLEAN_TOLERANCE_MM


def _contact_notes(topology: dict[str, Any], tolerance: float) -> list[str]:
    """CompCore 가 잰 바디끼리 겹침 · 틈(`quality.contacts`, f9a073c · c4fd87f) — 허용오차로
    붙였나 남겼나.

    붙인 것은 형상과 다르게 푼 것이다. 남긴 **틈**은 설계 틈새로 보고 떨어진 채 푼다(핸드폰
    부품의 틈새 0.05 ~ 0.2 mm). 남긴 **겹침**은 따로 떨어진 조각이 되므로 고칠 거리다 —
    CompCore 도 겹침은 크기와 상관없이 늘 알린다. 자리(`at`)는 말이 길어 바디 이름 · 크기만
    적는다.
    """
    rows = ((topology or {}).get("quality") or {}).get("contacts") or []
    closed: list[str] = []
    gaps: list[str] = []
    overlaps: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            size = float(row.get("size"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        overlap = row.get("kind") == "overlap"
        kind = "겹침" if overlap else "틈"
        shown = f"「{row.get('a')}」 · 「{row.get('b')}」 {kind} {size:g} mm"
        if size <= tolerance:
            closed.append(shown)
        else:
            (overlaps if overlap else gaps).append(shown)
    notes: list[str] = []
    if closed:
        notes.append(
            f"바디 사이 {', '.join(closed)} 는 형상 맞춤 허용오차({tolerance:g} mm) 안이라 "
            "맞닿은 것으로 붙여 메시했습니다."
        )
    if overlaps:
        notes.append(
            f"바디 사이 {', '.join(overlaps)} 는 허용오차({tolerance:g} mm)보다 커서 겹친 "
            "곳이 따로 떨어진 조각으로 메시됐습니다 — CAD 에서 고치세요."
        )
    if gaps:
        notes.append(
            f"바디 사이 {', '.join(gaps)} 는 허용오차({tolerance:g} mm)보다 커서 설계 틈새로 "
            "보고 떨어진 채 풀었습니다."
        )
    return notes


def _sizes_after_fragment(
    step: Path,
    workdir: Path,
    made: _Layout,
    probe: Probe,
    tolerance: float,
    timeout_seconds: int,
) -> dict[int, float]:
    """쪼개기 전 번호의 파트 크기 → **쪼갠 뒤 번호의 크기**(`mesh.fragment_owners`).

    겹친 조각은 두 바디의 것이라 작은 크기를 준다(맞닿은 점에서 작은 쪽이 이기는 것과 같다).
    겹침이 없으면 번호가 그대로라 한 번 재고 끝난다.
    """
    after = measure(
        step,
        workdir,
        fragment=True,
        removed=made.removed,
        shell_step=made.shell_step,
        sheets=made.sheets,
        tolerance=tolerance,
        timeout_seconds=timeout_seconds,
    ).volumes
    before = [one for one in probe.volumes if one.index not in made.removed]
    owners, unmatched = fragment_owners(before, after, boxes=probe.boxes)
    if unmatched:
        tags = sorted(one.index for one in before)
        pairs = [
            (first, second)
            for at, first in enumerate(tags)
            for second in tags[at + 1 :]
            if first in probe.boxes
            and second in probe.boxes
            and boxes_meet(probe.boxes[first], probe.boxes[second], tolerance)
        ]
        met = overlaps(
            step,
            workdir,
            pairs,
            removed=made.removed,
            shell_step=made.shell_step,
            sheets=made.sheets,
            tolerance=tolerance,
            timeout_seconds=timeout_seconds,
        )
        owners, unmatched = fragment_owners(before, after, met, probe.boxes)
        logger.info("쪼개며 겹친 곳 %s — 조각의 주인 %s", sorted(met), owners)
    sizes = {
        piece: min(made.sizes[one] for one in owner if one in made.sizes)
        for piece, owner in owners.items()
        if owner & made.sizes.keys()
    }
    if unmatched:
        made.notes.append(
            f"겹친 바디를 쪼갠 조각 {len(unmatched)}개는 어느 파트의 것인지 못 가려 전역 요소 "
            "크기로 메시했습니다."
        )
    return sizes


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


def _with_face_parts(
    mesh: Any, body_of: dict[str, int], shell_parts: dict[int, str] | None = None
) -> Any:
    """면마다 **그 면을 가진 파트 이름**을 단다(`FaceRecord.body`) — 짝짓기가 파트로 가른다.

    접촉을 쓰면 메시를 쪼개지 않아, 구멍에 같은 지름의 핀이 끼면 구멍면과 핀 옆면이 중심 ·
    반지름 · 축까지 같은 **두 면**으로 남는다. 파트를 안 보면 「구멍면」 자리에 핀 옆면을
    집는다(핀 베어링 D5961, 2026-10-08 — Ansys 경로가 먼저 밟았다). 두 파트가 나눠 가진
    면(쪼개 붙인 메시의 접합면)은 어느 쪽이라 할 수 없어 비워 둔다 — 그 면은 전처럼 모양으로만
    짝짓는다.

    **쉘 파트의 면에도 그 파트 이름을 단다**(`shell_parts` — 중간면의 면 번호 → 쉘 파트).
    시트 바디를 솔리드 위에 그대로 얹으면(CompCore 「시트 받침 조립」) 시트의 접착 띠와
    받침 윗면이 같은 자리 · 같은 넓이의 두 면이라, 파트를 안 보면 「받침 윗면」 자리에 시트
    면을 집어 「쉘끼리의 접촉」 으로 멈췄다(2026-10-16).
    """
    owners = {
        entity: {node for _, ids in rows for node in ids}
        for entity, rows in mesh.solids.items()
    }
    name_of = {entity: name for name, entity in body_of.items()}
    faces = []
    for face in mesh.faces:
        sheet = (shell_parts or {}).get(face.id)
        if sheet is not None:
            faces.append(replace(face, body=sheet))
            continue
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
    tolerance: float = 0.0,
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
            # 뺀 파트를 같이 지우고 중간면을 같이 읽어야 면 번호가 본 통과와 같다 — 중간면은
            # 먼저 읽혀 번호 앞자리를 차지한다. 빠뜨렸더니 쉘이 있는 모델에서 솔리드 면의
            # 힌트가 중간면 면 수만큼 밀린 다른 면에 걸렸다(2026-10-16, 「받침 바닥」 5 → 7).
            removed=layout.removed if layout else frozenset(),
            shell_step=layout.shell_step if layout else None,
            sheets=layout.sheets if layout else False,
            tolerance=tolerance,
        )
        if layout and layout.shell_parts:
            # 쉘 면에 그 파트 이름을 단다 — 같은 자리의 솔리드 면(시트를 얹은 받침 윗면)과
            # 가른다(`_with_face_parts`).
            rough = _with_face_parts(rough, {}, layout.shell_parts)
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


def _touching(
    topology: dict[str, Any] | None,
    pairs: list[condition_model.Contact],
    given: condition_model.Conditions,
) -> bool:
    """마찰 접촉이 모두 **같은 자리에 맞닿은 두 바디의 면**인가 — CAD 지문으로 본다.

    평면이면 중심이 같고(짝짓기의 평면 허용오차) 법선이 반대이고 넓이가 같다. 원통이면 반지름과
    중심이 같다. 그러면 메시를 나눌 때 두 면이 한 면(공유 절점)이 되고, 그 면만 가르면 짝 맞는
    접촉면이 된다(`_open_interfaces`). 강체 파트의 면은 아니다 — 강체 절점은 `*RIGID BODY` 가
    쥐어 독립 쪽에 둬야 해서 전처럼 접촉 쌍으로 건다(`deck.contact_block` 의 `masters`).
    """
    regions = (topology or {}).get("regions") or {}
    scale = model_scale(topology or {})
    near = max(PLANE_TOLERANCE_RATIO * scale, PLANE_TOLERANCE_MIN)

    def same(one: dict[str, Any], other: dict[str, Any]) -> bool:
        a, b = one.get("centroid"), other.get("centroid")
        if not (isinstance(a, list) and isinstance(b, list) and len(a) == len(b) == 3):
            return False
        if math.dist(a, b) > near:
            return False
        if one.get("radius") is not None or other.get("radius") is not None:
            # 원통은 축이 있어야 그 면 위의 절점을 고른다(`_on_surface`).
            return (
                one.get("radius") is not None
                and other.get("radius") is not None
                and abs(float(one["radius"]) - float(other["radius"])) <= RADIUS_TOLERANCE
                and bool(other.get("axis"))
            )
        normal, facing = one.get("normal"), other.get("normal")
        if not (isinstance(normal, list) and isinstance(facing, list)):
            return False
        if sum(float(x) * float(y) for x, y in zip(normal, facing, strict=True)) > -0.999:
            return False
        area, theirs = float(one.get("area") or 0), float(other.get("area") or 0)
        return area > 0 and abs(area - theirs) <= AREA_TOLERANCE_RATIO * area

    for pair in pairs:
        source = [one for one in regions.get(pair.source) or [] if isinstance(one, dict)]
        target = [one for one in regions.get(pair.target) or [] if isinstance(one, dict)]
        if not source or not target:
            return False
        sides = [{str(one.get("body") or "") for one in rows} for rows in (source, target)]
        if any(len(side) != 1 or "" in side for side in sides) or sides[0] == sides[1]:
            return False
        if (sides[0] | sides[1]) & set(given.rigid):
            return False
        if not all(any(same(one, other) for other in target) for one in source):
            return False
        if not all(any(same(other, one) for one in source) for other in target):
            return False
    return True


def _open_interfaces(
    topology: dict[str, Any],
    pairs: list[condition_model.Contact],
    nodes: Nodes,
    solids: Solids,
    body_of: dict[str, int],
) -> tuple[Nodes, Solids, dict[str, list[tuple[int, str]]], dict[str, dict[int, int]]]:
    """나눠 쪼갠 메시에서 **맞닿은 마찰면만 가른다** → (절점, 솔리드, 영역 → 요소면, 바디 →
    {원래 절점: 새 절점}).

    메시를 나누면(BooleanFragments) 맞닿은 두 면이 한 면이 되어 절점을 함께 쓴다 — 본딩은
    그대로 붙는다. 마찰면은 그 공유 면의 절점(꼭짓점 · 중간 절점)을 **원본 면 쪽 바디의
    요소에서만** 새 번호로 바꿔 떼어 낸다(볼트 단면을 가르는 `_split` 와 같은 방식). 두 면의
    요소면이 짝이 맞아 절점-면 접촉이 잘 수렴한다(실측 2026-10-30: 볼트 조립의 첫 증분 반복
    4번). 공유 면은 그 면의 지문(평면 · 원통) 위에 꼭짓점 셋이 다 놓이고 양쪽 바디가 다 가진
    사면체 면이다.

    그 면의 모서리 절점을 원본 면 바디의 다른 면에 건 하중 · 구속이 쓰면 그 절점은 대상 쪽에
    남는다 — 둘레 한 줄이라 답에는 거의 안 든다.
    """
    regions = topology.get("regions") or {}
    near = max(PLANE_TOLERANCE_RATIO * model_scale(topology), PLANE_TOLERANCE_MIN) * 1e-3
    out_nodes: Nodes = dict(nodes)
    out_solids: Solids = {key: list(rows) for key, rows in solids.items()}
    found: dict[str, list[tuple[int, str]]] = {}
    moved_by: dict[str, dict[int, int]] = {}

    def body_name(region: str) -> str:
        return str(((regions.get(region) or [{}])[0]).get("body") or "")

    def body_index(region: str) -> int:
        return body_of.get(body_name(region), -1)

    for pair in pairs:
        shape = (regions.get(pair.target) or [{}])[0]
        on = _on_surface(shape, near)
        sides: list[dict[frozenset[int], tuple[int, str, list[int]]]] = []
        for region in (pair.source, pair.target):
            seen: dict[frozenset[int], tuple[int, str, list[int]]] = {}
            for number, ids in out_solids.get(body_index(region), []):
                for label, corners in deck_writer.TET_FACES.items():
                    trio = [ids[one] for one in corners]
                    if all(on(out_nodes[one]) for one in trio):
                        seen.setdefault(frozenset(trio), (number, label, ids))
            sides.append(seen)
        shared = sorted(set(sides[0]) & set(sides[1]), key=sorted)
        if not shared:
            raise StageFailure(
                "internal",
                f"접촉 「{pair.name}」 의 두 면이 메시에서 맞닿지 않았습니다 — {MESH_LIMIT}",
            )
        moved: set[int] = set()
        for key in shared:
            _, label, ids = sides[0][key]
            corners = deck_writer.TET_FACES[label]
            moved |= {ids[one] for one in corners}
            if len(ids) >= 10:
                moved |= {
                    ids[deck_writer.TET_MIDDLES[(min(edge), max(edge))]]
                    for edge in deck_writer.face_edges(corners)
                }
        start = max(out_nodes) + 1
        renamed = {node: start + at for at, node in enumerate(sorted(moved))}
        out_nodes.update({new: out_nodes[old] for old, new in renamed.items()})
        source = body_index(pair.source)
        out_solids[source] = [
            (number, [renamed.get(one, one) for one in ids])
            for number, ids in out_solids[source]
        ]
        moved_by.setdefault(body_name(pair.source), {}).update(renamed)
        found[pair.source] = [(sides[0][key][0], sides[0][key][1]) for key in shared]
        found[pair.target] = [(sides[1][key][0], sides[1][key][1]) for key in shared]
        logger.info(
            "접촉 %s → 맞닿은 면 %s 개를 갈랐다(절점 %s)", pair.name, len(shared), len(moved)
        )
    return out_nodes, out_solids, found, moved_by


def _on_surface(shape: dict[str, Any], near: float) -> Any:
    """지문 한 장(평면 · 원통) 위에 놓였나를 보는 함수 — 절점 자리를 받는다."""
    center = [float(one) for one in shape.get("centroid") or [0.0, 0.0, 0.0]]
    if shape.get("radius") is not None:
        axis = [float(one) for one in shape.get("axis") or []]
        size = math.sqrt(sum(one * one for one in axis))
        if not size:
            raise StageFailure("internal", "원통 접촉면의 지문에 축이 없습니다.")
        unit = [one / size for one in axis]
        radius = float(shape["radius"])
        origin = axis_point(shape) or center

        def on_cylinder(point: tuple[float, float, float]) -> bool:
            offset = [point[at] - origin[at] for at in range(3)]
            along = sum(offset[at] * unit[at] for at in range(3))
            away = math.sqrt(max(sum(one * one for one in offset) - along * along, 0.0))
            return abs(away - radius) <= near + 1e-3 * radius

        return on_cylinder
    normal = [float(one) for one in shape.get("normal") or [0.0, 0.0, 1.0]]
    size = math.sqrt(sum(one * one for one in normal)) or 1.0

    def on_plane(point: tuple[float, float, float]) -> bool:
        return (
            abs(sum((point[at] - center[at]) * normal[at] for at in range(3)) / size) <= near
        )

    return on_plane


def _average_force(given: condition_model.Conditions) -> float | None:
    """수렴 판정의 **평균 힘**(N) — 가장 큰 힘 하중(볼트 예압의 힘 포함)의 1/100.

    ccx 는 「가장 큰 잔차 ≤ 0.005 x 평균 힘」 으로 본다. 평균 힘은 모든 요소 절점력의 평균이라
    볼트 근처만 힘을 받는 조립에서는 아주 작다(볼트 조립 첫 증분 0.009 N) — 접촉면의 붙음 ·
    미끄럼이 흔드는 0.01 ~ 0.08 N 을 끝내 못 넘어 반복 한계에 걸렸다. 이 값을 주면 한 절점의
    잔차를 하중의 5e-5 까지 받아 준다(1000 N 이면 0.05 N). 변위 쪽 기준(보정 ≤ 증분의 1 %)은
    그대로다. 힘 하중이 없으면(변위로만 당김) ccx 의 기본을 쓴다.
    """
    largest = 0.0
    for load in given.loads:
        if load.kind == "force" and load.magnitude:
            largest = max(largest, abs(load.magnitude))
        elif load.kind == "bolt_pretension" and load.preload:
            scale = condition_model.PRELOAD_FORCE_UNITS.get(condition_model.preload_unit(load))
            if scale is not None:
                largest = max(largest, abs(load.preload) * scale)
    return largest / 100 if largest > 0 else None


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
    # 볼트 예압은 면이 아니라 **단면**으로 건다(`_cut_bolts`) — 바디에 건 것도 거기서 푼다
    # (바디 그룹은 면이 아니라 여기서 짝지으면 멈춘다).
    wanted = [
        load.region for load in given.loads if load.region and load.kind != "bolt_pretension"
    ]
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


def _shell_masses(
    shells: list[deck_writer.ShellSection], nodes: dict[int, tuple[float, float, float]]
) -> dict[str, float]:
    """쉘 파트마다 질량(kg) — 요소 넓이 x 두께 x 밀도. 넓이는 모서리 셋으로 잰다(평면 요소)."""
    out: dict[str, float] = {}
    for sheet in shells:
        area = 0.0
        for _, ids in sheet.elements:
            x, y, z = _element_normal(nodes, ids)
            area += 0.5 * (x * x + y * y + z * z) ** 0.5
        # mm² x mm = mm³ → m³ 는 1e-9.
        mass = area * sheet.thickness * 1e-9 * sheet.material.density_kg_m3
        out[sheet.part] = out.get(sheet.part, 0.0) + mass
    return out


def _masses_kg(
    materials: list[material_model.Material], body_of: dict[str, int], mesh: Any
) -> dict[str, float] | None:
    """**바디마다** 부피 x 그 바디의 밀도 — 파트 이름 → kg. 하나라도 못 재면 `None`(틀린 질량은
    맞는 침묵보다 나쁘다)."""
    by_entity = {one.index: one.volume for one in mesh.bodies}
    out: dict[str, float] = {}
    for material in materials:
        for body in material.bodies:
            entity = body_of.get(body)
            if entity is None or entity not in by_entity:
                return None
            # 부피는 mm³ — SI 밀도와 곱하려면 m³ 로 옮긴다(1e-9).
            out[body] = out.get(body, 0.0) + by_entity[entity] * 1e-9 * material.density_kg_m3
    return out


def _mass_kg(
    materials: list[material_model.Material], body_of: dict[str, int], mesh: Any
) -> float | None:
    """전체 질량 — 바디마다의 합(설계점 비교의 두 번째 축)."""
    found: float | None = material_model.mass_summary(_masses_kg(materials, body_of, mesh))[
        "mass_kg"
    ]
    return found


def _support_springs(
    topology: dict[str, Any], given: condition_model.Conditions, mesh: Any
) -> deck_writer.Springs:
    """탄성 · 압축 전용 지지 영역 → 절점마다 (맡은 넓이 mm², 바깥 단위 법선) — 덱이 법선
    스프링 · 간극을 붙인다.

    넓이는 힘을 나눌 때와 같은 규칙이다(`tributary_areas` — 요소면의 절점 전부에 고르게).
    법선은 그 절점이 닿은 요소면 법선을 넓이로 더한 것이다. **바깥으로 세운다** — 그 면을
    가진 사면체의 남은 꼭짓점 반대쪽이다. 스프링은 부호와 상관없지만 압축 전용의 간극은 그
    쪽으로 밀 때만 닫힌다 — 감긴 방향(CAD 면의 매개변수 방향)을 믿으면 반대로 받친다.
    """
    wanted = [
        rule.region
        for rule in given.constraints
        if rule.kind in ("elastic_support", "compression_only")
    ]
    if not wanted or not topology:
        return {}
    found = match_regions(topology, mesh.faces, wanted_regions=wanted)
    owners = element_faces(mesh)
    elements = {number: ids for rows in mesh.solids.values() for number, ids in rows}
    springs: deck_writer.Springs = {}
    for name, ids in found.faces.items():
        area: dict[int, float] = {}
        normal: dict[int, list[float]] = {}
        for face in ids:
            for ring in mesh.face_rings.get(face, []):
                a, b, c = (mesh.nodes[one] for one in ring[:3])
                cross = deck_writer._cross(
                    [b[axis] - a[axis] for axis in range(3)],
                    [c[axis] - a[axis] for axis in range(3)],
                )
                size = sum(one * one for one in cross) ** 0.5 / 2
                if size <= 0:
                    continue
                owner = owners.get(frozenset(ring[:3]))
                if owner is not None:
                    rest = [one for one in elements[owner[0]][:4] if one not in ring[:3]]
                    inside = mesh.nodes[rest[0]] if rest else None
                    if inside is not None and (
                        sum(cross[axis] * (inside[axis] - a[axis]) for axis in range(3)) > 0
                    ):
                        cross = [-one for one in cross]
                for node in ring:
                    area[node] = area.get(node, 0.0) + size / len(ring)
                    mine = normal.setdefault(node, [0.0, 0.0, 0.0])
                    for axis in range(3):
                        mine[axis] += cross[axis]
        made: dict[int, tuple[float, tuple[float, float, float]]] = {}
        for node, share in area.items():
            vector = normal[node]
            length = sum(one * one for one in vector) ** 0.5
            if length > 0:
                made[node] = (
                    share,
                    (vector[0] / length, vector[1] / length, vector[2] / length),
                )
        springs[name] = made
        logger.info(
            "법선 지지 %s → 절점 %s · 넓이 %.4g mm²", name, len(made), sum(area.values())
        )
    return springs


Nodes = dict[int, tuple[float, float, float]]
Solids = dict[int, list[tuple[int, list[int]]]]


def _cut_bolts(
    topology: dict[str, Any],
    given: condition_model.Conditions,
    mesh: Any,
    shapes: dict[str, dict[str, Any]],
    body_of: dict[str, int],
    length_mm: float,
) -> tuple[dict[str, deck_writer.BoltSection | str], Nodes, Solids]:
    """볼트 예압 하중 → **볼트를 가른 단면**(못 세우면 까닭)과 **갈라진 메시**(절점 · 솔리드).

    - **원통면에 건 예압**: 축과 단면 자리는 CAD 가 잰 원통면 지문(`axis` · `axis_at`)이다 —
      원통면의 가운데를 지나 축에 수직인 평면. 기준점이 그 축 위에 선다. 그 원통면 절점을 가장
      많이 가진 솔리드가 볼트다.
    - **바디에 건 예압**(CompCore 2f402f2 — 우리가 고른 (가)): 바디 그룹의 지문은 그 바디의
      `bodies[]` 줄이고, 단면은 **하중의 좌표계**다 — Z 축이 볼트 축, 원점이 단면 자리(Ansys 의
      바디 예압과 같은 뜻). 원점은 선언된 계의 길이로 온다(`length_mm`).
    - 볼트의 요소를 **무게중심이 평면의 어느 쪽인가**로 둘로 가르고, 두 쪽이 함께 쓰는 절점을
      앞쪽에서만 새 번호로 바꾼다(`deck.BoltSection`). 정적과 그 뒤의 모달이 **같은 갈라진
      메시**를 써야 하므로 한 번만 가른다.
    """
    out: dict[str, deck_writer.BoltSection | str] = {}
    nodes: Nodes = dict(mesh.nodes)
    solids: Solids = {key: list(rows) for key, rows in mesh.solids.items()}
    for load in given.loads:
        if load.kind != "bolt_pretension":
            continue
        shape = shapes.get(load.region) or {}
        entity: int | None
        if shape.get("volume") is not None:
            name = str(shape.get("name") or load.region)
            frame = next((one for one in given.frames if one.name == load.cs), None)
            if frame is None:
                out[load.name] = (
                    f"바디에 건 볼트 예압은 좌표계가 있어야 합니다(「{load.cs}」 가 "
                    "없습니다) — Z 축이 볼트 축, 원점이 단면 자리입니다."
                )
                continue
            entity = body_of.get(name)
            if entity is None:
                out[load.name] = f"바디 「{name}」 를 메시에서 못 찾았습니다."
                continue
            point = [one * length_mm for one in frame.origin]
            axis = [float(one) for one in frame.z_axis]
        elif shape.get("axis") and shape.get("centroid"):
            found = match_regions(topology, mesh.faces, wanted_regions=[load.region])
            members: set[int] = set()
            for face in found.faces.get(load.region, []):
                members |= mesh.face_nodes.get(face, set())
            counts = {
                key: sum(1 for _, ids in rows for node in ids if node in members)
                for key, rows in solids.items()
            }
            entity = max(counts, key=lambda key: counts[key]) if members and counts else None
            if entity is None:
                out[load.name] = f"원통면 「{load.region}」 을 메시에서 못 찾았습니다."
                continue
            point = axis_point(shape) or [float(one) for one in shape["centroid"]]
            axis = [float(one) for one in shape["axis"]]
        else:
            out[load.name] = (
                "볼트 예압은 볼트 몸통의 원통면이나 볼트 바디에 겁니다 — "
                f"「{load.region}」 은 둘 다 아닙니다."
            )
            continue
        length = sum(one * one for one in axis) ** 0.5
        unit = [one / length for one in axis] if length else [0.0, 0.0, 1.0]
        rows, pairs = _split(nodes, solids[entity], point, unit)
        if not pairs:
            out[load.name] = "볼트를 가를 단면이 비었습니다 — 단면 자리가 볼트 밖입니다" + (
                f"(좌표계 「{load.cs}」 의 원점 · Z 축)." if shape.get("volume") else "."
            )
            continue
        solids[entity] = rows
        for behind, ahead in pairs:
            nodes[ahead] = nodes[behind]
        out[load.name] = deck_writer.BoltSection(
            pairs=tuple(pairs),
            point=(point[0], point[1], point[2]),
            axis=(unit[0], unit[1], unit[2]),
        )
        logger.info("볼트 %s → 솔리드 %s · 단면 절점 %s", load.name, entity, len(pairs))
    return out, nodes, solids


def _split(
    nodes: Nodes,
    rows: list[tuple[int, list[int]]],
    point: list[float],
    axis: list[float],
) -> tuple[list[tuple[int, list[int]]], list[tuple[int, int]]]:
    """솔리드 하나를 평면(점 · 법선)의 앞뒤로 가른다 — **앞쪽 요소의 경계 절점을 새 번호로**.

    경계 절점은 두 쪽 요소가 함께 쓰는 것 모두다 — 면으로 맞닿는 것뿐 아니라 모서리 ·
    꼭짓점으로만 닿는 것까지(그것을 남기면 예압이 그 길로 샌다). 새 번호는 지금 절점 끝 다음
    부터다. 돌려주는 것: 바뀐 요소 줄 · (원래 절점, 새 절점) 짝.
    """

    def ahead(ids: list[int]) -> bool:
        corners = [nodes[one] for one in ids[:4]]
        center = [sum(one[at] for one in corners) / 4 for at in range(3)]
        return sum((center[at] - point[at]) * axis[at] for at in range(3)) > 0

    sides = [ahead(ids) for _, ids in rows]
    front: set[int] = set()
    back: set[int] = set()
    for (_, ids), side in zip(rows, sides, strict=True):
        (front if side else back).update(ids)
    shared = sorted(front & back)
    if not shared:
        return rows, []
    start = max(nodes) + 1
    renamed = {node: start + at for at, node in enumerate(shared)}
    out = [
        (number, [renamed.get(node, node) for node in ids] if side else ids)
        for (number, ids), side in zip(rows, sides, strict=True)
    ]
    return out, [(node, renamed[node]) for node in shared]
