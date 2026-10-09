"""FE 모델을 만든다 — 임포트 · 물성 · 메시 · 해석 설정 · `.dat`.

## 실측으로 정한 것 (2026-09-20, Ansys 2025 R2 · Student · Windows)

- **임포트**: `GeometryImportGroup.AddGeometryImport()` + `GeometryImportPreferences`.
  AutoJigGenerator(build123d/OpenCascade)가 낸 STEP 이 그대로 들어온다 — 판 · L 브래킷 확인.
- **물성은 명령 조각(command snippet)으로 준다.** MatML XML 을 만들어 Engineering Data 에
  넣는 길도 있지만, 그 형식은 길고 한 칸이 틀려도 「임포트는 됐는데 값이 안 들어간」 상태가
  된다 — 그 상태는 고유진동수가 틀린 뒤에야 드러난다. 바디에 붙인 명령 조각은 `/PREP7` 의
  기본 물성(Structural Steel) **뒤에** 들어가 덮어쓴다(실측: `MP,EX,1,…` 다음 줄에 우리 것).
- **단위계는 CAD 의 선언을 읽고 거기에 맞춰 세운다**(2026-09-24). 명령 조각의 숫자에는
  단위가 없어서, 어느 계로 세웠는지 모르면 `MP,EX,matid,206000` 이 206 GPa 인지 206 kPa 인지
  알 수 없다 — 그 차이는 아무 오류도 내지 않고 고유진동수만 10³ 배 어긋나게 한다. 계를
  **세운 뒤 솔버 단위계를 읽어 확인한다**(`app/core/units.py` 에 그 자리와 실측이 있다).
- **구속이 없으면 자유-자유**다. 강체 모드 6개가 0 Hz 로 나오므로 찾을 모드 수에 6을 더한다
  (`spec.modes_to_find`).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app.core import conditions as condition_model
from app.core import materials, units
from app.core.bodies import BodyRecord, match_bodies, place_settings, without
from app.core.harmonic import HarmonicPlan, harmonic_plan
from app.core.regions import FaceRecord, match_regions
from app.core.spec import (
    RIGID_BODY_MODES,
    HarmonicSpec,
    MaterialSpec,
    ModalSpec,
    StaticSpec,
)
from app.core.stages import (
    MIDSURFACE_NAME,
    ArtifactSpec,
    FailureCode,
    StageFailure,
    StageResult,
)
from app.core.statics import StaticPlan, static_plan

logger = logging.getLogger(__name__)

#: 모델링이 받는 스펙 — 레시피마다 거는 것이 다르다.
AnySpec = ModalSpec | StaticSpec | HarmonicSpec


#: 라이선스 실패로 볼 말. Mechanical 은 이것을 예외 메시지에 실어 준다.
_LICENSE_WORDS = ("license", "licence", "라이선스")


def _is_license_problem(failure: Exception) -> bool:
    text = str(failure).lower()
    return any(word in text for word in _LICENSE_WORDS)


#: CAD 플랫폼이 보낸 영역 지문. 구속이 있는 스펙은 이것이 있어야 돈다.
TOPOLOGY_NAME = "topology.json"

#: 앞선 해석의 덱 — 뒤 덱이 이것을 이어받는다(선응력 · 모드 중첩). 솔브가 먼저 푼다.
UPSTREAM_NAME = "upstream.dat"

#: **이 작업이 자유-자유인가**를 뒤 단계에 넘기는 자리. 스펙만 보면 알 수 없다 — 구속이
#: CAD 조건에만 있을 수 있고(`conditions_from="cad"`), 그때 결과가 「자유-자유」 로 적히면
#: 강체 모드 수를 세는 경고까지 거짓이 된다(실측 2026-10-02).
BOUNDARY_NAME = "boundary.json"


def build(
    spec: AnySpec,
    workdir: Path,
    *,
    input_name: str = "input.step",
    version: int = 252,
    cache_dir: Path | None = None,
) -> StageResult:
    """형상 하나로 FE 모델을 만들고 `model.dat` 을 남긴다.

    프로세스당 임베디드 App 은 하나다 — 워커가 한 번에 작업 하나만 돌리는 이유이기도 하다.
    """
    step = workdir / input_name
    if not step.is_file() or step.stat().st_size == 0:
        raise StageFailure("geometry_import", f"입력 형상이 없습니다: {input_name}")

    # **CAD 의 선언을 먼저 읽는다** — 세션을 그 계로 세우기 때문에 형상을 넣기 전에 알아야
    # 한다. 선언이 모르는 이름이면 여기서 멈춘다(Mechanical 을 띄우기 전에).
    topology = _topology(workdir)
    system = _declared_system(workdir)
    # **CAD 가 보낸 물성**. 읽을 수 없으면 여기서 멈춘다 — 빠진 물성은 Mechanical 이 기본값
    # (구조용 강)으로 풀고, 그 사실은 고유진동수가 틀린 뒤에야 드러난다.
    given = _declared_materials(spec, workdir, system)
    if not given and spec.material is None:
        raise StageFailure(
            "internal", "물성이 없습니다 — CAD 가 물성을 보내지 않았고 스펙에도 없습니다."
        )
    # **CAD 가 보낸 조건** — 못 거는 것이 하나라도 있으면 여기서 멈춘다(Mechanical 을 띄우기
    # 전에). 조용히 빼면 「조건을 넣었는데 왜 결과가 같지」 를 사람이 물을 자리가 없다.
    given_conditions = _declared_conditions(spec, topology)

    # **형상 캐시** — STEP 임포트가 모델링 시간의 거의 전부다(실측 2026-10-02: 임포트 18.9초 ·
    # 메시 1.7초 · 다시 열기 0.7초). 같은 형상 · 같은 메시면 한 번 만들어 두고 **연다.**
    cached = _cache_path(cache_dir, step, spec, given_conditions)

    app = _start_app(version)
    try:
        _use_unit_system(app, system)
        reused = _open_cached(app, cached)
        bodies = _bodies_of(app) if reused else _import_geometry(app, step)
        shells = given_conditions.shells
        if shells and not reused:
            # **쉘 파트는 중간면으로 푼다** — 두 번째 형상으로 들여온다(면 바디).
            bodies = _import_midsurface(app, workdir, shells)
        sheets = [body for body in bodies if _is_sheet(body)]
        bodies = [body for body in bodies if not _is_sheet(body)]
        # **파트별 설정** — 형상을 읽은 직후에 건다(메시 · 물성 · 조건이 모두 그 뒤다). 캐시는
        # 그 설정까지 담고(열쇠에 들어간다 — `_cache_path`), 다시 열면 이미 걸려 있다.
        placed = _place_body_settings(given_conditions, bodies, topology or {}, system)
        sheet_of = _place_sheets(sheets, topology or {}, shells) if shells else {}
        if not reused:
            _apply_body_settings(app, placed, bodies, system)
            _apply_whole_method(app, given_conditions, placed, bodies)
            _apply_sheet_settings(app, sheet_of, given_conditions, system)
        order_note = condition_model.whole_order_note(given_conditions, spec.mesh.order)
        if order_note is not None:
            given_conditions.skipped.append(order_note)
        # 뺀 파트 · 쉘 파트의 솔리드는 물성 · 조건 · 질량 · 메시 어디에도 안 나온다.
        active = [
            body
            for index, body in enumerate(bodies)
            if not (index in placed and (placed[index].suppressed or placed[index].shell))
        ]
        # 조건 · 메시는 면 바디(쉘)까지 본다.
        modelled = active + list(sheet_of.values())
        rigid_ids = {
            int(bodies[index].GetGeoBody().Id)
            for index, one in placed.items()
            if one.rigid and not one.suppressed
        }
        kept = (
            without(topology, given_conditions.suppressed | set(shells))
            if topology
            else topology
        )
        # **쉘 파트의 영역은 중간면에서 찾는다**(지문의 `mid`).
        view = (
            condition_model.shell_view(topology, set(shells))
            if topology and shells
            else topology
        )
        if cached is not None and not reused:
            # **깨끗할 때 남긴다 — 해석 · 조건을 걸기 전에.** 접촉 · 이름 선택 · 하중은 모델
            # 수준 객체라서, 다 건 뒤에 남기면 **다음 점이 앞 점의 것을 물려받는다** — 접촉
            # 종류를 훑는 DOE 에서 마찰 점이 앞 점의 접착에 덮여 조용히 접착으로 풀렸다
            # (2026-10-03, CompCore 전단 이음으로 들켰다). 캐시는 영역별 메시 힌트가 없을 때만
            # 쓰므로(`_cache_path`) 여기서 전역 크기로 메시해도 나중 메시와 같다.
            _mesh(app, spec, given_conditions, system, {}, view or {}, modelled)
            _save_cache(app, cached)
        used = _apply_material(spec, active, system, given, kept)
        sheet_materials = _apply_sheet_materials(spec, sheet_of, given, system)
        _rigid_mass(active, used, rigid_ids, system)
        constrained = bool(given_conditions.constraints or spec.constraints)
        plan: HarmonicPlan | None = None
        statics: StaticPlan | None = None
        if isinstance(spec, HarmonicSpec):
            # **조화 응답은 모달이 앞에 선다**(모드 중첩) — 그 모드로 응답을 쌓는다.
            upstream = _add_modal_for_harmonic(app, spec)
            plan = harmonic_plan(spec, given_conditions)
            analysis = _add_harmonic(app, spec, upstream, plan)
        elif isinstance(spec, StaticSpec):
            # **정적 해석은 하중이나 강제 변위가 답을 만든다.** 둘 다 없으면 전부 0 이 나오는데
            # 그 그림은 「해석이 됐다」 처럼 보인다 — 여기서 멈춘다. 변위로 당기는 시편 시험은
            # 하중이 없어도 답이 있다(`Conditions.drives`).
            if not given_conditions.driven:
                raise StageFailure(
                    "internal",
                    "정적 해석인데 하중도 강제 변위도 없습니다 — CAD 조건에 하중을 넣거나 "
                    "모달로 돌리세요.",
                )
            # **큰 변형은 사람이 적었으면 그것, 비웠으면 CAD 가 적은 것이다**
            # (`statics.static_plan`). 초기 부단계 수는 비선형일 때만 건다 — 선형 모델에
            # 걸면 같은 답을 그 수만큼 다시 푼다.
            statics = static_plan(spec, given_conditions)
            nonlinear = statics.large_deflection or any(
                one.kind in NONLINEAR_CONTACT_KINDS for one in given_conditions.contacts
            )
            analysis = _add_static(
                app,
                large_deflection=statics.large_deflection,
                substeps=statics.substeps if nonlinear else None,
            )
            upstream = analysis
        else:
            # **선응력이면 정적 해석이 먼저다** — 조여 놓은 상태의 공진을 보려면 그 응력을
            # 안고 풀어야 한다(CompCore 의 주 용도). 하중은 그 정적 해석에 걸린다.
            upstream = _add_static(app) if given_conditions.prestressed else None
            analysis = _add_modal(
                app, spec, constrained=constrained, given=given_conditions, upstream=upstream
            )
        _write_boundary(
            workdir, constrained=constrained, spec=spec, plan=plan, material=used.names
        )
        _guard_solver_units(analysis, system)
        places: dict[str, Any] = {}
        # **구속은 앞선 해석에 건다** — 모드 중첩의 모드는 모달에서 나오고, 선응력의 응력은
        # 정적에서 나온다. 뒤 해석에 걸면 앞이 자유-자유로 풀려 **엉뚱한 모드로 응답을
        # 쌓는다.**
        # CAD 조건이든 스펙 구속이든 같은 자리여야 한다.
        held = upstream if upstream is not None else analysis
        if given_conditions.constraints or given_conditions.contacts:
            regions, places, flipped = _apply_given_conditions(
                app, given_conditions, system, view or {}, modelled, held, rigid_ids
            )
        else:
            flipped = set()
            regions = _apply_constraints(app, spec, workdir, active, held)
        if isinstance(spec, HarmonicSpec):
            # **조화 응답의 하중은 흔드는 힘이다** — 앞선 모달이 아니라 조화 쪽에 건다.
            # (모달에 걸면 덱에 `sfedele,all` 만 남아 응답이 전부 0 으로 나온다 — 실측.)
            _apply_loads(app, given_conditions, system, places, analysis, flipped)
        elif upstream is not None:
            _apply_loads(app, given_conditions, system, places, upstream, flipped)
        mass = _mass_kg(used, active, system)
        if sheet_materials:
            mass = round(
                (mass or 0.0) + _sheet_mass(topology or {}, shells, sheet_materials), 4
            )
        nodes, elements = _mesh(
            app, spec, given_conditions, system, places, view or {}, modelled
        )
        # **변위로 당긴 자리의 절점을 남긴다** — 추출이 그 절점의 반력만 더한다.
        _write_reaction_nodes(app, workdir, given_conditions, places)
        size_mm = _global_size_mm(spec, given_conditions, system)

        dat = workdir / "model.dat"
        if upstream is not None and upstream is not analysis:
            # **앞선 해석의 덱을 따로 낸다.** 뒤 덱이 그것을 **이어받기** 때문이다 —
            # 선응력 모달은 재시작(`.rdb` · `.rnnn`), 조화 응답은 모달의 `file.db`
            # (`resume,file,db`). 없으면 MAPDL 이 그 자리에서 죽는다(둘 다 실측 2026-10-02).
            # 솔브 단계가 이 파일을 **먼저** 푼다.
            upstream_dat = workdir / UPSTREAM_NAME
            try:
                upstream.WriteInputFile(str(upstream_dat))
            except Exception as failure:  # pragma: no cover - Ansys 없이는 안 돈다
                raise _translated(
                    failure, "solver_failed", "앞선 해석의 입력 파일을 쓰지 못했습니다"
                ) from failure
            artifacts_extra = [ArtifactSpec("dat", upstream_dat)]
        else:
            artifacts_extra = []
        try:
            analysis.WriteInputFile(str(dat))
        except Exception as failure:  # pragma: no cover - Ansys 없이는 안 돈다
            raise _translated(
                failure, "solver_failed", "솔버 입력 파일을 쓰지 못했습니다"
            ) from failure
        if not dat.is_file():
            raise StageFailure("solver_failed", "솔버 입력 파일이 만들어지지 않았습니다.")

        artifacts = [ArtifactSpec("dat", dat), *artifacts_extra]
        # **`.mechdb` 는 디버깅용이다.** 리눅스에 GUI 는 없지만 파일은 OS 간
        # 호환이라,
        # 개발자 Windows PC 에서 열어 「모델이 어떻게 생겼나」 를 본다. 저장에 실패해도
        # 작업은 계속한다.
        mechdb = workdir / "model.mechdb"
        try:
            app.save_as(str(mechdb), overwrite=True)
            artifacts.append(ArtifactSpec("mechdb", mechdb))
        except Exception:  # pragma: no cover - 저장 실패가 모델링을 망치지는 않는다
            logger.warning("mechdb 저장 실패 — 모델은 그대로 씁니다", exc_info=True)
        # **두 덱이 끝까지 쓰였나** — mechdb 를 남긴 **뒤에** 본다(끊겼으면 그 파일을 열어
        # 메시지를 봐야 한다). 조화 · 선응력은 구속 · 접촉이 앞선 해석에 걸리므로 그 덱도 본다.
        if artifacts_extra:
            _check_input_complete(workdir / UPSTREAM_NAME)
        _check_input_complete(dat)

        return StageResult(
            artifacts=artifacts,
            summary={
                "bodies": len(active) + len(sheet_of),
                **(
                    {"suppressed_bodies": " · ".join(sorted(given_conditions.suppressed))}
                    if len(active) < len(bodies)
                    else {}
                ),
                **(
                    {"rigid_bodies": " · ".join(sorted(given_conditions.rigid))}
                    if rigid_ids
                    else {}
                ),
                **(
                    {
                        "shell_bodies": " · ".join(
                            f"{name} {shells[name]:g} mm" for name in sorted(sheet_of)
                        )
                    }
                    if sheet_of
                    else {}
                ),
                "nodes": nodes,
                "elements": elements,
                # **전역 요소 크기**(mm) — 메시 수렴 점검의 기준. 비면 Mechanical 기본값으로
                # 돌았다.
                **({"element_size_mm": size_mm} if size_mm is not None else {}),
                # **실제로 요청한 수**다 — 구속이 CAD 조건에만 있으면 스펙의 수와 다르다.
                **(
                    {"modes_requested": spec.modes + (0 if constrained else RIGID_BODY_MODES)}
                    if isinstance(spec, ModalSpec)
                    else {"recipe": "static"}
                ),
                "ansys_version": version,
                "constrained_regions": regions,
                "mass_kg": mass,
                "shape_reused": reused,
                "unit_system": system.key,
                "solver_unit_system": system.solver,
                # **무슨 물성으로 돌았나.** 적지 않으면 「CAD 가 보낸 재료로 돈 것인지」 를
                # 나중에 알 방법이 없다 — 재료를 훑는 DOE 에서 그것이 결과의 절반이다.
                "conditions_from": "cad" if given_conditions.constraints else "spec",
                # 큰 변형을 켰나 · 누가 정했나(`statics.static_plan`).
                **(
                    {"large_deflection": True, "large_deflection_from": statics.source}
                    if statics is not None and statics.large_deflection
                    else {}
                ),
                **(
                    {
                        "damping_ratio": plan.damping_ratio,
                        "frequency_points": plan.intervals,
                        "settings_from": plan.source,
                    }
                    if plan is not None
                    else {}
                ),
                **({"prestressed": True} if upstream is not None else {}),
                **(
                    {
                        "frequency_range_hz": "~".join(
                            f"{one:g}" for one in given_conditions.analysis.frequency_range
                        )
                    }
                    if given_conditions.analysis.frequency_range
                    else {}
                ),
                **(
                    {
                        "loads": " · ".join(
                            f"{one.kind}:{one.region or '전체'}"
                            for one in given_conditions.loads
                        )
                    }
                    if given_conditions.loads
                    else {}
                ),
                **(
                    {
                        "conditions_skipped": " · ".join(
                            one.what for one in given_conditions.skipped
                        )
                    }
                    if given_conditions.skipped
                    else {}
                ),
                "material": " · ".join(used.names),
                "material_from": used.source,
                **(
                    {
                        "youngs_modulus_gpa": round(used.single.youngs_modulus_gpa, 4),
                        "density_kg_m3": round(used.single.density_kg_m3, 4),
                    }
                    if used.single is not None
                    else {
                        # 파트마다 다르면 **어느 파트에 무엇을** 을 적는다 — 값 하나로 줄이면
                        # 뒤바뀐 것을 알아볼 수 없다.
                        "material_bodies": " · ".join(
                            f"{name or f'바디 {index + 1}'}={one.name}"
                            for index, name, one in used.per_body
                        )
                    }
                ),
            },
            detail=(
                f"바디 {len(bodies)} · 절점 {nodes:,} · 요소 {elements:,}"
                f" · 단위계 {system.key}"
                + (f" · 구속 {' · '.join(regions)}" if regions else " · 자유-자유")
            ),
        )
    finally:
        _close(app)


# --- 단계별 -------------------------------------------------------------------


def _cache_path(
    cache_dir: Path | None,
    step: Path,
    spec: AnySpec,
    given: condition_model.Conditions,
) -> Path | None:
    """이 작업이 쓸 형상 캐시 파일. 쓸 수 없으면 `None`.

    **열쇠에 들어가는 것**: 형상 바이트 · 레시피 · 요소 크기 · 차수. 메시가 그것들에 딸리기
    때문이다 — 하나라도 다르면 다른 모델이다.

    **영역마다의 메시 힌트가 있으면 캐시를 안 쓴다.** 그 사이징은 이름 붙은 선택(=조건)을
    가리키는데, 조건이 든 모델을 캐시에 넣으면 **다음 점이 앞 점의 조건을 물려받는다.**
    그 상태는 결과를 봐도 모른다.
    """
    if cache_dir is None or not step.is_file():
        return None
    if any(
        one.element_size is not None and one.region not in ("전체", "all")
        for one in given.mesh_hints
    ):
        return None
    digest = hashlib.sha256()
    digest.update(step.read_bytes())
    digest.update(spec.recipe.encode())
    digest.update(str(spec.mesh.element_size_mm).encode())
    digest.update(spec.mesh.order.encode())
    whole = given.whole_mesh
    if whole is not None and whole.method:
        # 「전체」 요소 형상도 캐시에 담긴다(`_apply_whole_method`).
        digest.update(f"method:{whole.method}".encode())
    if given.shells:
        # 쉘이면 중간면 형상도 모델이다.
        mid = step.with_name(MIDSURFACE_NAME)
        if mid.is_file():
            digest.update(mid.read_bytes())
    if given.body_settings:
        # **파트별 설정도 모델이다** — 강체 · 제외 · 파트 메시가 캐시에 같이 담긴다. 다르면
        # 다른 열쇠여야 다음 점이 앞 점의 설정을 물려받지 않는다.
        digest.update(repr(sorted(given.body_settings, key=lambda one: one.name)).encode())
    return cache_dir / f"{digest.hexdigest()[:16]}.mechdb"


def _open_cached(app: Any, cached: Path | None) -> bool:
    """캐시를 연다. 열었으면 참 — **실패는 실패가 아니다**(그냥 새로 만든다).

    실측(2026-10-02): 다시 열기 0.7초 · 임포트 18.9초. 그리고 **면 번호가 그대로다** —
    영역 매칭이 그것으로 돌기 때문에 이 확인이 없으면 캐시를 쓸 수 없었다.
    """
    if cached is None or not cached.is_file():
        return False
    try:
        app.open(str(cached))
    except Exception:  # pragma: no cover - Ansys 없이는 안 돈다
        logger.warning("형상 캐시를 열지 못했습니다 — 새로 만듭니다", exc_info=True)
        return False
    logger.info("형상 캐시를 썼습니다: %s", cached.name)
    return True


def _save_cache(app: Any, cached: Path) -> None:
    """임포트 · 메시를 마친 모델을 캐시로. **실패해도 작업은 계속한다** — 캐시는 덤이다."""
    try:
        cached.parent.mkdir(parents=True, exist_ok=True)
        app.save_as(str(cached), overwrite=True)
        logger.info("형상 캐시를 남겼습니다: %s", cached.name)
    except Exception:  # pragma: no cover - Ansys 없이는 안 돈다
        logger.warning("형상 캐시를 남기지 못했습니다 — 다음에도 새로 만듭니다", exc_info=True)


def _bodies_of(app: Any) -> list[Any]:
    """연 모델의 바디들 — 임포트한 뒤와 같은 모양으로."""
    enums = _global("Ansys").Mechanical.DataModel.Enums
    bodies = list(app.Model.Geometry.GetChildren(enums.DataModelObjectCategory.Body, True))
    if not bodies:
        raise StageFailure("geometry_import", "형상 캐시에 바디가 없습니다.")
    return bodies


def _start_app(version: int) -> Any:
    try:
        from ansys.mechanical.core import App
    except ImportError as failure:
        raise StageFailure(
            "internal",
            "PyMechanical 이 이 파이썬에 없습니다 — "
            "워커 환경(SIMULATION_EXECUTOR)을 확인하세요.",
        ) from failure
    try:
        app = App(version=version)
    except Exception as failure:
        if _is_license_problem(failure):
            raise StageFailure(
                "license", f"Mechanical 라이선스를 받지 못했습니다: {failure}"
            ) from failure
        raise StageFailure(
            "internal", f"Mechanical 을 시작하지 못했습니다: {failure}"
        ) from failure
    # **전역을 이 모듈에 심는다.** 임베디드 API 는 `Model` · `Quantity` · `Ansys` 를 전역으로
    # 주는 것을 전제로 쓰이고, 그것 없이 같은 일을 하려면 .NET 네임스페이스를 손으로
    # 들어야 한다.
    app.update_globals(globals())
    return app


def _close(app: Any) -> None:
    try:
        app.close()
    except Exception:  # pragma: no cover - 닫기 실패가 결과를 바꾸지 않는다
        logger.warning("Mechanical 종료 중 오류", exc_info=True)


def _global(name: str) -> Any:
    """임베디드가 심어 준 전역 하나.

    **없으면 여기서 말한다** — 뒤에서 NameError 로 터지면 그 트레이스백은 「무엇이 없다」 를
    안 알려 준다.
    """
    value = globals().get(name)
    if value is None:
        raise StageFailure("internal", f"Mechanical 전역 {name} 을 찾지 못했습니다.")
    return value


def _topology(workdir: Path) -> dict[str, Any] | None:
    """CAD 가 보낸 점 파일 한 장(`topology.json`). 없으면 `None` — 오류가 아니다.

    단위 선언 · 물성 · 영역 지문이 다 이 안에 있다(CompCore 가 2026-09-24 에 합쳤다). 한 번만
    읽어 세 자리가 나눠 쓴다.
    """
    path = workdir / TOPOLOGY_NAME
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as failure:
        raise StageFailure(
            "internal", f"{TOPOLOGY_NAME} 을 읽지 못했습니다: {failure}"
        ) from failure
    return loaded if isinstance(loaded, dict) else None


def _declared_materials(
    spec: AnySpec, workdir: Path, system: units.UnitSystem
) -> list[materials.Material]:
    """CAD 가 보낸 물성. 사람이 「내 값으로」 라고 했으면(`material_from="spec"`) 안 읽는다.

    **못 읽으면 실패한다.** 빠진 물성은 Mechanical 이 기본값(구조용 강)으로 풀어 버리고, 그
    결과는 값이 안 나오는 게 아니라 **그럴듯한 값이 나오고 틀린다.**
    """
    if spec.material_from == "spec":
        return []
    payload = _topology(workdir)
    if payload is None:
        return []
    try:
        return materials.read(payload, system)
    except materials.MaterialProblem as failure:
        raise StageFailure(
            "internal",
            f"{failure} — 사람이 넣은 물성으로 돌리려면 스펙의 물성 출처를 「스펙」 으로 "
            "바꾸세요.",
            details={"material": failure.material, "reason": failure.reason},
        ) from failure


def _declared_conditions(
    spec: AnySpec, topology: dict[str, Any] | None
) -> condition_model.Conditions:
    """CAD 가 보낸 조건 — 사람이 「내 스펙으로」 라고 했으면 안 읽는다
    (`conditions_from="spec"`).

    **못 거는 조건이 있으면 멈춘다.** 구속이 빠지면 모드가 통째로 달라지는데, 그 사실은
    고유진동수를 보고도 알 수 없다. 모달에서 답을 안 바꾸는 것(하중 · 환경 온도)은 멈추지 않고
    요약에 적는다 — 그래야 「압력을 줬는데 왜 같지」 를 사람이 읽을 수 있다.
    """
    if spec.conditions_from == "spec" or topology is None:
        return condition_model.Conditions()
    found = condition_model.read(topology, recipe=spec.recipe)
    if found.refused:
        raise StageFailure(
            "region_unresolved",
            "CAD 가 보낸 조건 중 아직 걸 수 없는 것이 있습니다: "
            + " · ".join(f"{one.what} — {one.why}" for one in found.refused),
            details={"refused": [{"what": one.what, "why": one.why} for one in found.refused]},
        )
    for note in found.skipped:
        logger.info("조건 건너뜀 %s — %s", note.what, note.why)
    if spec.mesh.local_scale != 1:
        # **비례 정련** — 메시 수렴 점검이 전체 크기와 같은 비율로 CAD 의 파트 · 면 크기를
        # 줄인다.
        logger.info("CAD 파트 · 면 요소 크기 배율 %g (비례 정련)", spec.mesh.local_scale)
        found = condition_model.scaled(found, spec.mesh.local_scale)
    return found


def _declared_system(workdir: Path) -> units.UnitSystem:
    """CAD 가 선언한 단위계. 점 파일이 없으면 기본(SI)이다.

    **모르는 이름이면 여기서 멈춘다.** 「아마 SI 겠지」 로 돌리면 틀렸을 때 나오는 것은 오류가
    아니라 그럴듯한 값이다(`app/core/units.py` 머리말).
    """
    payload = _topology(workdir)
    if payload is None:
        return units.DEFAULT
    try:
        return units.declared_in(payload)
    except units.UnknownUnitSystem as failure:
        raise StageFailure(
            "internal",
            f"{failure} — CAD 가 보낸 계를 세울 수 없으면 값을 넣지 않습니다.",
            details={"declared": failure.declared, "known": sorted(units.KNOWN)},
        ) from failure


def _use_unit_system(app: Any, system: units.UnitSystem) -> None:
    """**선언한 계로 세션을 세운다** — 검사만 하지 않는다.

    mm 로 만든 형상에 mm 계가 맞고, CAD 의 기본이 그것이다. 세우지 못하면 세션은 MKS 인데
    값은 mm 계라는 **가장 나쁜 짝**이 되므로 거기서 멈춘다.
    """
    try:
        enum = _global("MechanicalUnitSystem")
        wanted = getattr(enum, system.mechanical)
        app.ExtAPI.Application.ActiveUnitSystem = wanted
        active = str(app.ExtAPI.Application.ActiveUnitSystem)
    except Exception as failure:
        raise StageFailure(
            "internal",
            f"활성 단위계를 {system.mechanical} 로 세우지 못했습니다: {failure}",
            details={"unit_system": system.key},
        ) from failure
    if system.mechanical not in active:
        raise StageFailure(
            "internal",
            f"활성 단위계가 {active} 입니다 — {system.mechanical} 로 세웠는데 "
            "안 바뀌었습니다.",
            details={"unit_system": system.key, "active": active},
        )
    logger.info("단위계 %s ← 선언 %s", active, system.key)


def _guard_solver_units(analysis: Any, system: units.UnitSystem) -> None:
    """**`.dat` 의 숫자가 읽히는 계**를 확인한다 — 표시계가 아니라 이쪽이다.

    실측(2026-09-24): `SolverUnits` 기본값이 `ActiveSystem` 이고 그때 `SolverUnitSystem` 은
    표시계를 따라간다(`StandardNMMton` → `ConsistentNMM`). 누군가 그 자리를 손으로 바꿔 두면
    명령 조각의 숫자만 조용히 다른 계로 읽히므로 여기서 본다.
    """
    try:
        solver = str(analysis.AnalysisSettings.SolverUnitSystem)
    except Exception:  # pragma: no cover - 판에 따라 없을 수 있다
        logger.warning("솔버 단위계를 읽지 못했습니다 — 표시계를 믿습니다", exc_info=True)
        return
    if system.solver not in solver:
        raise StageFailure(
            "internal",
            f"솔버 단위계가 {solver} 입니다. 물성 명령의 숫자는 이 계로 읽히므로 "
            f"{system.solver} 여야 합니다(선언 {system.key}).",
            details={"unit_system": system.key, "solver_unit_system": solver},
        )


def _import_geometry(app: Any, step: Path) -> list[Any]:
    enums = _global("Ansys").Mechanical.DataModel.Enums
    utilities = _global("Ansys").ACT.Mechanical.Utilities
    model = app.Model
    importer = model.GeometryImportGroup.AddGeometryImport()
    preferences = utilities.GeometryImportPreferences()
    # CAD 가 이름 붙인 면을 그대로 받는다. 4단계의 centroid 매칭은 이것이 못 나르는
    # 경우의 대비다.
    preferences.ProcessNamedSelections = True
    try:
        importer.Import(
            str(step), enums.GeometryImportPreference.Format.Automatic, preferences
        )
    except Exception as failure:
        raise _translated(
            failure, "geometry_import", f"형상을 읽지 못했습니다 ({step.name})"
        ) from failure

    bodies = list(model.Geometry.GetChildren(enums.DataModelObjectCategory.Body, True))
    if not bodies:
        raise StageFailure(
            "geometry_import", "형상에 바디가 없습니다 — 빈 STEP 이거나 곡면만 있습니다."
        )
    return bodies


def material_commands(material: MaterialSpec, system: units.UnitSystem) -> str:
    """물성 명령 조각의 글. **숫자를 세션의 계로 환산해서 적는다.**

    스펙은 사람이 읽는 단위로 들어온다(`youngs_modulus_gpa` · `density_kg_m3`). 세션이 mm 계면
    그 값을 MPa · t/mm³ 로 적어야 하고, 그러지 않으면 10⁶ 배 틀린 값이 **오류 없이** 들어간다.
    """
    modulus = system.stress(material.youngs_modulus_gpa * 1e9)
    density = system.density(material.density_kg_m3)
    # 머리글은 **ASCII 로 적는다** — Mechanical 이 `.dat` 를 쓸 때 한글 주석이 깨져 나온다
    # (실측: 「?????」). 솔버는 주석을 읽지 않지만, 덱을 여는 사람은 읽는다.
    return (
        f"! SimEngBay material override: {material.name} [{system.key}]\n"
        f"MP,EX,matid,{modulus:.6g}\n"
        f"MP,PRXY,matid,{material.poisson_ratio:.6g}\n"
        f"MP,DENS,matid,{density:.6g}\n"
    )


@dataclass
class Applied:
    """어느 바디에 무슨 물성을 붙였나. 요약 · 질량이 이것으로 말한다."""

    per_body: list[tuple[int, str, MaterialSpec]]
    """(바디 번호, 파트 이름, 물성). 파트 이름은 CAD 가 준 것 — 없으면 빈 글자."""
    source: str
    """`cad` · `spec`."""

    @property
    def names(self) -> list[str]:
        return list(dict.fromkeys(one[2].name for one in self.per_body))

    @property
    def single(self) -> MaterialSpec | None:
        """한 벌로 돌았으면 그것 — 요약에 E · 밀도를 적을 수 있다."""
        specs = {one[2].name: one[2] for one in self.per_body}
        return next(iter(specs.values())) if len(specs) == 1 else None


def _apply_material(
    spec: AnySpec,
    bodies: list[Any],
    system: units.UnitSystem,
    given: list[materials.Material],
    topology: dict[str, Any] | None,
) -> Applied:
    """바디마다 명령 조각으로 물성을 덮어쓴다. **무엇을 붙였는지 돌려준다.**

    `matid` 는 Mechanical 이 조각에 심어 주는 값이다 — 바디마다 재료 번호가 다를 수 있어서,
    파트마다 다른 물성도 조각으로 나눠 붙일 수 있다.

    CAD 가 보낸 것이 있으면 그것이 먼저다. **파트를 짝짓는 것은 이름이 아니라 지문이다** —
    STEP 이 한글 이름을 못 나르기 때문이다(실측: Mechanical 이 「챘째혴…|Solid」 로 읽는다).
    """
    if not given:
        # 위(`build`)에서 이미 막았다 — 둘 다 없으면 Mechanical 을 띄우기 전에 멈춘다.
        assert spec.material is not None
        return _uniform(bodies, spec.material, system, source="spec")
    if len(given) == 1 and (given[0].every_body or len(bodies) == 1):
        picked = given[0]
        if picked.notes:
            logger.info("물성 %s — %s", picked.name, " · ".join(picked.notes))
        return _uniform(bodies, picked.spec(), system, source="cad")

    # **파트마다 다른 물성** — 부피 · 무게중심으로 짝짓는다.
    matched = match_bodies(topology or {}, _body_records(bodies, system))
    if not matched.ok:
        raise StageFailure(
            "internal",
            "CAD 의 파트를 형상에서 찾지 못해 물성을 붙일 수 없습니다: "
            + " · ".join(matched.failures),
            details={"failures": matched.failures},
        )
    by_index = {index: name for name, index in matched.bodies.items()}
    made: list[tuple[int, str, MaterialSpec]] = []
    for index, body in enumerate(bodies):
        name = by_index.get(index, "")
        chosen = materials.for_body(given, name) if name else None
        if chosen is None:
            raise StageFailure(
                "internal",
                f"바디 {index + 1}"
                + (f"({name})" if name else "")
                + " 에 붙일 물성이 없습니다 — 그대로 풀면 Mechanical 의 기본값(구조용 강)으로 "
                "풀립니다.",
                details={
                    "bodies": list(matched.bodies),
                    "materials": [one.name for one in given],
                },
            )
        snippet = body.AddCommandSnippet()
        snippet.AppendText(material_commands(chosen.spec(), system))
        made.append((index, name, chosen.spec()))
        logger.info("물성 %s ← 파트 %s (바디 %d)", chosen.name, name, index + 1)
    return Applied(per_body=made, source="cad")


def _uniform(
    bodies: list[Any], material: MaterialSpec, system: units.UnitSystem, *, source: str
) -> Applied:
    """한 물성을 모든 바디에."""
    text = material_commands(material, system)
    made: list[tuple[int, str, MaterialSpec]] = []
    for index, body in enumerate(bodies):
        snippet = body.AddCommandSnippet()
        snippet.AppendText(text)
        made.append((index, "", material))
    return Applied(per_body=made, source=source)


def _body_records(bodies: list[Any], system: units.UnitSystem) -> list[BodyRecord]:
    """Mechanical 의 바디를 **mm 로** 옮긴다 — CAD 의 지문이 mm 다.

    실측(2026-09-28): `body.Volume` · `body.CentroidX` 는 **활성 단위계**를 따른다(면 지문과
    다르다 — 그쪽은 늘 mm). 그래서 여기서 계를 알고 환산해야 짝이 맞는다.
    """
    scale = system.length_mm
    found: list[BodyRecord] = []
    for index, body in enumerate(bodies):
        try:
            volume = float(body.Volume.Value) * scale**3
            centroid = (
                float(body.CentroidX.Value) * scale,
                float(body.CentroidY.Value) * scale,
                float(body.CentroidZ.Value) * scale,
            )
        except Exception as failure:  # pragma: no cover - Ansys 없이는 안 돈다
            raise StageFailure(
                "internal", f"바디 {index + 1} 의 부피 · 무게중심을 읽지 못했습니다: {failure}"
            ) from failure
        found.append(
            BodyRecord(
                index=index, volume=volume, centroid=centroid, name=str(body.Name or "")
            )
        )
    return found


def _limit_range(analysis: Any, given: condition_model.Conditions) -> None:
    """CAD 가 **찾을 주파수 범위**를 적었으면 그대로 건다(`LimitSearchToRange`, 실측 자리).

    스펙에는 그 칸이 없다 — 범위는 「어디를 보고 싶은가」 라서 조건 쪽에 속한다. 안 걸면
    낮은 것부터 세어 올라가므로 **보고 싶은 대역이 모드 수 밖으로 밀려날 수 있다.**
    """
    span = given.analysis.frequency_range
    if span is None:
        return
    low, high = span
    if high <= low:
        return
    quantity = _global("Quantity")
    settings = analysis.AnalysisSettings
    try:
        settings.LimitSearchToRange = True
        settings.RangeMinimum = quantity(f"{low} [Hz]")
        settings.RangeMaximum = quantity(f"{high} [Hz]")
        logger.info("주파수 범위 %s ~ %s Hz ← CAD", low, high)
    except Exception:  # pragma: no cover - Ansys 없이는 안 돈다
        logger.warning("주파수 범위를 걸지 못했습니다 — 범위 없이 돕니다", exc_info=True)


def _add_modal_for_harmonic(app: Any, spec: HarmonicSpec) -> Any:
    """조화 응답이 쓸 모드를 먼저 푼다 — **모드 중첩**은 그 모드로 응답을 쌓는다.

    구속 · 접촉은 이 해석에 걸린다(모드가 거기서 나온다). 하중은 조화 쪽이다.
    """
    modal = app.Model.AddModalAnalysis()
    modal.AnalysisSettings.MaximumModesToFind = spec.modes
    return modal


def _add_harmonic(app: Any, spec: HarmonicSpec, modal: Any, plan: HarmonicPlan) -> Any:
    """조화 응답 — **주파수를 훑으며 흔든다.**

    칸 이름은 실측으로 쟀다(2026-10-02): `RangeMinimum/Maximum` · `SolutionIntervals` ·
    `SolutionMethod` · `DampingRatio` · `NumberOfModesToUse`, 그리고 앞선 모달은
    `InitialConditions[0].ModalICEnvironment` 로 문다.
    """
    low, high, intervals, damping = (
        plan.low,
        plan.high,
        plan.intervals,
        plan.damping_ratio,
    )
    harmonic = app.Model.AddHarmonicResponseAnalysis()
    quantity = _global("Quantity")
    settings = harmonic.AnalysisSettings
    try:
        settings.RangeMinimum = quantity(f"{low} [Hz]")
        settings.RangeMaximum = quantity(f"{high} [Hz]")
        settings.SolutionIntervals = intervals
        # **`NumberOfModesToUse` 는 건드리지 않는다** — 모드 중첩에서는 앞선 모달이 그 수를
        # 정하므로 읽기 전용이다(실측 2026-10-02: "This property is parameterized and is
        # read-only"). 그래서 `_add_modal_for_harmonic` 에서 모드 수를 정한다.
        settings.DampingRatio = damping
        initial = next(iter(harmonic.InitialConditions))
        initial.ModalICEnvironment = modal
        # **감쇠를 실제로 거는 자리는 명령 조각이다.** 위의 `DampingRatio` 는 화면에만 남고
        # **덱에는 한 줄도 안 적힌다** — 그 속성 · `ConstantDamping` ·
        # `StructuralDampingCoefficient` 셋 다 해 봤지만 `dmprat`/`mdamp`/`alphad` 가
        # 안 나왔다(실측 2026-10-02). 감쇠 없이 풀면 공진에서 응답이 끝없이 커지고, 그
        # 큰 수는 그럴듯해 보인다. 해석에 붙인 조각은 `/solu` 안 `solve` **앞에** 적힌다
        # (실측: 선응력 정적의 `RESCONTROL` 이 그 자리에 들어갔다).
        snippet = harmonic.AddCommandSnippet()
        snippet.AppendText(f"! SimEngBay: constant damping ratio\nDMPRAT,{damping:.6g}\n")
    except Exception as failure:  # pragma: no cover - Ansys 없이는 안 돈다
        raise _translated(
            failure, "internal", "조화 응답 설정을 세우지 못했습니다"
        ) from failure
    return harmonic


#: Mechanical 이 비선형으로 푸는 접촉 — 초기 부단계 수가 뜻을 가진다.
NONLINEAR_CONTACT_KINDS = ("frictional", "frictionless", "rough")


def _add_static(
    app: Any, *, large_deflection: bool | None = None, substeps: int | None = None
) -> Any:
    """정적 해석. 구속과 하중이 여기 걸린다.

    선응력의 디딤돌로 쓸 때는(모달이 뒤따를 때) **재시작 파일을 남기라고 이른다**
    (`RESCONTROL,LINEAR`). 그것이 없으면 모달의 재시작 덱이 「multiframe restart 파일이 없다」
    로 죽는다 — MAPDL 이 그렇게 시키라고 적어 준 그대로다. 정적 해석 자체로 풀 때는 필요
    없으므로 `large_deflection` 을 준 경우(=정적 레시피)에는 안 붙인다.

    `substeps`(CAD 의 「초기 부단계 수」)를 주면 자동 시간 단계를 부단계로 정하고 처음을 그
    수로 나눈다(`NSUBST`). 최대는 넉넉히(그 10배 · 적어도 1000) 둬 수렴이 어려우면 더 잘게
    나누게 한다 — 최대를 먼저 넣어야 처음 값이 범위를 넘지 않는다.
    """
    static = app.Model.AddStaticStructuralAnalysis()
    if large_deflection is None:
        snippet = static.AddCommandSnippet()
        snippet.AppendText(
            "! SimEngBay: keep restart files for the modal perturbation\nRESCONTROL,LINEAR\n"
        )
        return static
    settings = static.AnalysisSettings
    settings.LargeDeflection = bool(large_deflection)
    if substeps:
        enums = _global("Ansys").Mechanical.DataModel.Enums
        settings.AutomaticTimeStepping = enums.AutomaticTimeStepping.On
        settings.DefineBy = enums.TimeStepDefineByType.Substeps
        settings.MaximumSubsteps = max(substeps * 10, 1000)
        settings.InitialSubsteps = substeps
        settings.MinimumSubsteps = 1
        logger.info("초기 부단계 %s (CAD)", substeps)
    return static


def _add_modal(
    app: Any,
    spec: ModalSpec,
    *,
    constrained: bool,
    given: condition_model.Conditions,
    upstream: Any = None,
) -> Any:
    """모달 해석 하나. **찾을 모드 수는 구속 여부로 갈린다** — 자유-자유면 강체 6개를 얹는다.

    구속이 CAD 조건에만 있을 수 있으므로 스펙이 아니라 **실제로 건 것**으로 센다.

    `upstream` 이 있으면 **그 정적 해석의 응력을 안고 푼다**(실측 2026-10-02:
    `InitialConditions[0].PreStressICEnvironment`). 볼트를 조인 상태의 공진이 그 자리다.
    """
    analysis = app.Model.AddModalAnalysis()
    analysis.AnalysisSettings.MaximumModesToFind = spec.modes + (
        0 if constrained else RIGID_BODY_MODES
    )
    _limit_range(analysis, given)
    if upstream is None:
        return analysis
    try:
        initial = next(iter(analysis.InitialConditions))
        initial.PreStressICEnvironment = upstream
    except Exception as failure:  # pragma: no cover - Ansys 없이는 안 돈다
        raise _translated(failure, "internal", "선응력 링크를 걸지 못했습니다") from failure
    return analysis


#: 하중 종류 → Mechanical 의 만드는 자리(실측 2026-10-02).
_LOAD_MAKERS = {
    "pressure": "AddPressure",
    "force": "AddForce",
    "moment": "AddMoment",
    "bearing": "AddBearingLoad",
    "bolt_pretension": "AddBoltPretension",
    "standard_earth_gravity": "AddEarthGravity",
    "acceleration": "AddAcceleration",
    "rotational_velocity": "AddRotationalVelocity",
}


def _apply_loads(
    app: Any,
    given: condition_model.Conditions,
    system: units.UnitSystem,
    places: dict[str, Any],
    static: Any,
    flipped: set[str] | None = None,
) -> None:
    """하중을 **정적 해석에** 건다 — 그 응력을 모달이 안고 푼다.

    `flipped` 는 **면 법선이 원래 겉면의 바깥 법선과 반대로 선** 쉘 면의 영역이다 — 거기
    압력은 부호를 뒤집어야 같은 쪽(안쪽)으로 민다(`_flipped_pressures`).

    크기는 선언된 계의 값이라 단위를 붙여 준다. 방향은 성분 벡터이거나 면의 법선(압력)이다.
    """
    quantity = _global("Quantity")
    for load in given.loads:
        maker = _LOAD_MAKERS.get(load.kind)
        if maker is None:  # pragma: no cover - 조건 층이 먼저 막는다
            raise StageFailure("internal", f"못 거는 하중입니다: {load.kind}")
        try:
            made = getattr(static, maker)()
            if load.region:
                place = places.get(load.region)
                if place is None:
                    raise StageFailure(
                        "region_unresolved",
                        f"하중 「{load.name}」 의 자리 「{load.region}」 를 못 찾았습니다",
                    )
                made.Location = place
            _load_magnitude(made, load, system, quantity)
            if load.kind == "pressure" and load.region in (flipped or set()):
                made.Magnitude.Output.DiscreteValues = [
                    quantity(
                        f"{-(load.magnitude or 0.0)} [{load.unit or system.length_label}]"
                    )
                ]
            made.Name = load.name
            logger.info("하중 %s(%s) ← %s", load.name, load.kind, load.region or "전체")
        except StageFailure:
            raise
        except Exception as failure:  # pragma: no cover - Ansys 없이는 안 돈다
            raise _translated(
                failure, "internal", f"하중 「{load.name}」({load.kind})을 걸지 못했습니다"
            ) from failure


def _load_magnitude(
    made: Any, load: condition_model.Load, system: units.UnitSystem, quantity: Any
) -> None:
    """크기와 방향 — **단위를 값에서 떼지 않는다**(CAD 가 `unit` 을 함께 보낸다)."""
    unit = load.unit or system.length_label
    if load.kind == "bolt_pretension":
        if load.preload is None:
            raise StageFailure("internal", f"볼트 「{load.name}」 에 예압이 없습니다")
        made.Preload.Output.DiscreteValues = [quantity(f"{load.preload} [{unit}]")]
        return
    if load.direction is not None and load.kind in (
        "force",
        "moment",
        "bearing",
        "acceleration",
    ):
        # 성분으로 준다 — 크기를 방향 벡터에 실어 나눈다.
        size = load.magnitude or 0.0
        length = sum(one * one for one in load.direction) ** 0.5 or 1.0
        made.DefineBy = _global("Ansys").Mechanical.DataModel.Enums.LoadDefineBy.Components
        for axis, part in zip(
            ("XComponent", "YComponent", "ZComponent"), load.direction, strict=True
        ):
            getattr(made, axis).Output.DiscreteValues = [
                quantity(f"{size * part / length} [{unit}]")
            ]
        return
    if load.magnitude is not None and hasattr(made, "Magnitude"):
        made.Magnitude.Output.DiscreteValues = [quantity(f"{load.magnitude} [{unit}]")]


#: Mechanical 이 솔버 입력 파일 끝에 쓰는 표지. 이것이 없으면 중간에 끊긴 것이다.
INPUT_END_MARK = "/wb,file,end"


def _check_input_complete(dat: Path) -> None:
    """**Mechanical 이 입력 파일을 끝까지 썼나** — 끝 표지(`/wb,file,end`)를 본다.

    `WriteInputFile` 은 중간에 멈춰도 오류를 내지 않는다(실측 2026-10-08, CompCore 시험
    규격 「보드굽힘」: 강체 롤러 · 노즈의 접촉까지 쓰고 끊겨 구속 · 하중 · `solve` 가 없었다).
    그대로 솔브에 넘기면 MAPDL 이 「입력 끝」 으로 멈춰 종료 코드 8 만 남는다 — 까닭이 안
    보인다.
    """
    try:
        with dat.open("rb") as stream:
            stream.seek(max(0, dat.stat().st_size - 4096))
            tail = stream.read().decode("ascii", errors="replace")
    except OSError:  # pragma: no cover - 방금 쓴 파일이다
        return
    if INPUT_END_MARK in tail:
        return
    last = next(
        (
            line.removeprefix("/com,").strip(" *")
            for line in reversed(tail.splitlines())
            if line.lower().startswith("/com,***")
        ),
        "",
    )
    raise StageFailure(
        "solver_failed",
        "Mechanical 이 솔버 입력 파일을 끝까지 쓰지 못했습니다"
        + (f"(「{last}」 다음에서 끊겼습니다)" if last else "")
        + " — 그 뒤의 조건(구속 · 하중 · 원격점)을 Mechanical 이 만들지 못한 것입니다. "
        "model.mechdb 를 Mechanical 에서 열어 메시지를 보거나, 솔버를 calculix 로 바꾸세요.",
    )


#: 변위로 당긴 영역 → 메시 절점 번호. 추출이 그 절점의 반력을 더한다(`dpf/static.py`).
REACTION_NODES_NAME = "reaction_nodes.json"


def _write_reaction_nodes(
    app: Any, workdir: Path, given: condition_model.Conditions, places: dict[str, Any]
) -> None:
    """변위 구속 영역마다 **메시 절점 번호**를 남긴다 — 추출이 그 절점의 반력만 더한다.

    전에는 추출이 그 영역 **첫 면의 평면 위** 절점의 반력을 더했다. 같은 평면에 다른 구속이
    있으면 함께 더해지고(V 노치 전단의 두 물림은 같은 평면이라 서로 지워져 144 N — CalculiX
    37.7 kN), 면이 여럿이면 첫 면만 셌다(겹치기 이음 2.9 kN — CalculiX 3.8 kN). CompCore 시험
    규격으로 들켰다(2026-10-08). Mechanical 이 면마다 아는 메시 절점이 정본이다 — CalculiX
    쪽도 구속을 건 절점 집합의 반력을 더한다.
    """
    wanted = [
        one.region
        for one in given.constraints
        if one.kind == "displacement" and one.region in places
    ]
    if not wanted:
        return
    try:
        model = app.ExtAPI.DataModel
        data = model.MeshDataByName(model.MeshDataNames[0])
        found: dict[str, list[int]] = {}
        for region in wanted:
            ids: set[int] = set()
            for face in places[region].Location.Ids:
                ids.update(int(one) for one in data.MeshRegionById(int(face)).NodeIds)
            found[region] = sorted(ids)
        (workdir / REACTION_NODES_NAME).write_text(json.dumps(found), encoding="utf-8")
        logger.info("반력 절점 %s", {name: len(ids) for name, ids in found.items()})
    except Exception:  # pragma: no cover - Ansys 없이는 안 돈다
        logger.warning("반력 절점을 못 남겼습니다 — 추출이 평면으로 찾습니다", exc_info=True)


def _write_boundary(
    workdir: Path,
    *,
    constrained: bool,
    spec: AnySpec,
    plan: HarmonicPlan | None = None,
    material: list[str] | None = None,
) -> None:
    """뒤 단계(결과 추출)가 읽을 한 줄 — **무엇으로 돌았나.**

    조화면 **실제로 쓴 감쇠비**도 남긴다. CAD 가 적어 보낸 값이 스펙과 다를 수 있어서, 결과가
    스펙 값을 적으면 **화면이 거짓말을 한다**(봉우리 높이를 그 값으로 읽는 사람에게는 치명적).
    **실제로 붙인 물성 이름**도 같은 까닭이다 — CAD 가 파트마다 보내면 스펙의 것은 안 쓰인다.
    """
    payload: dict[str, Any] = {
        "constrained": constrained,
        "modes_requested": (
            spec.modes + (0 if constrained else RIGID_BODY_MODES)
            if isinstance(spec, ModalSpec)
            else 0
        ),
        "recipe": spec.recipe,
    }
    if material:
        payload["material"] = " · ".join(material)
    if plan is not None:
        payload["damping_ratio"] = plan.damping_ratio
        payload["frequency_range_hz"] = [plan.low, plan.high]
        payload["intervals"] = plan.intervals
        payload["settings_from"] = plan.source
    (workdir / BOUNDARY_NAME).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _mass_kg(used: Applied, bodies: list[Any], system: units.UnitSystem) -> float | None:
    """**바디마다** 부피 x 그 바디의 밀도. 설계점 비교의 두 번째 축이다 — 지그는 가볍고
    단단해야 한다.

    파트마다 물성이 다르면 한 밀도로 곱할 수 없다. 강판에 알루미늄 블록을 올린 조립에서
    그렇게 하면 질량이 3% 어긋나고, **그 3% 가 물성이 뒤바뀐 유일한 증거**다.

    부피는 **활성계의 길이³** 로 온다(실측: mm 계에서 113,395 mm³, MKS 로 같은 형상이
    1.134e-4 m³). 못 읽으면 `None` 이다 — **틀린 질량은 맞는 침묵보다 나쁘다.**
    """
    try:
        total = 0.0
        for index, _, material in used.per_body:
            volume = float(bodies[index].Volume.Value)
            total += system.volume_m3(volume) * material.density_kg_m3
    except Exception:  # pragma: no cover - 형상에 따라 못 읽을 수 있다
        logger.warning("부피를 읽지 못했습니다 — 질량을 내지 않습니다", exc_info=True)
        return None
    return round(total, 4) if total > 0 else None


def _part_names(
    bodies: list[Any], topology: dict[str, Any], system: units.UnitSystem
) -> dict[int, str]:
    """형상 바디 번호 → **CAD 파트 이름**(바디 짝짓기 — 물성을 붙일 때와 같은 규칙).

    면 짝짓기가 조립 지문의 `body` 를 보게 한다(`FaceRecord.body`). 못 짝지은 바디는 빠진다 —
    그 바디의 면은 자리로만 고른다.
    """
    if not topology or not topology.get("bodies"):
        return {}
    try:
        matched = match_bodies(topology, _body_records(bodies, system))
        return {
            int(bodies[index].GetGeoBody().Id): name for name, index in matched.bodies.items()
        }
    except Exception:  # pragma: no cover - 면 바디 등 부피가 없는 바디
        logger.warning("면 짝짓기에 쓸 파트 이름을 못 얻었습니다", exc_info=True)
        return {}


def _face_records(bodies: list[Any], names: dict[int, str] | None = None) -> list[FaceRecord]:
    """Mechanical 의 면들을 **코어가 아는 모양**으로 옮긴다(`app/core/regions`).

    법선은 `Normals` 의 첫 셋을 쓴다 — 평면이면 어디서 재도 같고, 굽은 면은 한 값으로 말할
    수 없어 매칭이 반지름 · 중심으로 간다. `names` 를 주면 면마다 그 파트 이름을 붙인다.
    """
    found: list[FaceRecord] = []
    for body in bodies:
        geo = body.GetGeoBody()
        part = (names or {}).get(int(geo.Id), "")
        for face in geo.Faces:
            radius = float(face.Radius)
            normal: tuple[float, float, float] | None = None
            try:
                values = [float(one) for one in list(face.Normals)[:3]]
                if len(values) == 3:
                    normal = (values[0], values[1], values[2])
            except Exception:  # pragma: no cover - 면에 따라 못 낼 수 있다
                normal = None
            centroid = [float(one) for one in face.Centroid]
            found.append(
                FaceRecord(
                    id=int(face.Id),
                    centroid=(centroid[0], centroid[1], centroid[2]),
                    area=float(face.Area),
                    surface=str(face.SurfaceType),
                    normal=normal,
                    radius=radius if radius > 0 else None,
                    body=part,
                )
            )
    return found


def _apply_constraints(
    app: Any, spec: AnySpec, workdir: Path, bodies: list[Any], analysis: Any
) -> list[str]:
    """구속을 건다.

    구속이 없으면 자유-자유 그대로 둔다. **이름이 안 풀리면 즉시 실패한다** — 조용히 빼면
    구속 없는 해석이 끝까지 돌고, 그 결과는 0 Hz 여섯 개를 달고 나온다.
    """
    if not spec.constraints:
        return []

    path = workdir / TOPOLOGY_NAME
    if not path.is_file():
        raise StageFailure(
            "region_unresolved",
            f"구속을 걸려면 CAD 가 보낸 {TOPOLOGY_NAME} 이 필요합니다. 형상과 함께 올리세요.",
            details={"regions": [one.region for one in spec.constraints]},
        )
    topology = json.loads(path.read_text(encoding="utf-8"))
    wanted = [one.region for one in spec.constraints]
    matched = match_regions(topology, _face_records(bodies), wanted_regions=wanted)
    if not matched.ok:
        raise StageFailure(
            "region_unresolved",
            "구속 영역을 형상에서 찾지 못했습니다: "
            + " · ".join(
                f"{one.region}[{one.index}] {one.reason}" for one in matched.failures
            ),
            details={
                "failures": [
                    {
                        "region": one.region,
                        "index": one.index,
                        "reason": one.reason,
                        "wanted": one.wanted,
                        "nearest": one.nearest,
                    }
                    for one in matched.failures
                ]
            },
        )

    applied: list[str] = []
    for constraint in spec.constraints:
        named = _named_selection(app, constraint.region, matched.faces[constraint.region])
        support = analysis.AddFixedSupport()
        support.Location = named
        applied.append(constraint.region)
        logger.info("구속 %s ← 면 %s", constraint.region, matched.faces[constraint.region])
    return applied


def _named_selection(app: Any, name: str, ids: list[int]) -> Any:
    """면 번호들을 이름 붙인 선택으로 — 구속 · 접촉이 이것을 가리킨다."""
    selection_type = _global("Ansys").ACT.Interfaces.Common.SelectionTypeEnum
    named = app.Model.AddNamedSelection()
    named.Name = name
    info = app.ExtAPI.SelectionManager.CreateSelectionInfo(selection_type.GeometryEntities)
    info.Ids = ids
    named.Location = info
    return named


def _apply_given_conditions(
    app: Any,
    given: condition_model.Conditions,
    system: units.UnitSystem,
    topology: dict[str, Any],
    bodies: list[Any],
    analysis: Any,
    rigid_ids: set[int] | None = None,
) -> tuple[list[str], dict[str, Any], set[str]]:
    """**CAD 가 보낸 구속 · 접촉을 건다** — 종류마다 Mechanical 의 짝으로.

    매핑표는 우리 것이다(CompCore 는 솔버를 모른다). 칸 이름은 **실측으로 쟀다**
    (2026-10-02, 2025 R2): `Radial` · `Axial` · `Tangential` · `XComponent` ·
    `FoundationStiffness` · `Behavior` · `ContactType`.
    """
    wanted = sorted(
        {one.region for one in given.constraints}
        | {one.source for one in given.contacts}
        | {one.target for one in given.contacts}
        # **하중의 자리도 여기서 함께 짝짓는다** — 빼 두면 선응력에서 「자리를 못 찾았다」 로
        # 늦게 죽는다(실측 2026-10-02).
        | {one.region for one in given.loads if one.region}
    )
    if not wanted:
        return [], {}, set()

    # 파트 이름은 **남은 파트로만** 짝짓는다 — 뺀 파트 · 쉘 파트도 CAD 바디 목록에 남아
    # 있어, 부피가 비슷하면 남은 파트의 바디를 가로채 제 면을 「다른 파트의 면」 으로 막는다
    # (물성과 같은 규칙 — `kept`).
    kept_parts = (
        without(topology, given.suppressed | set(given.shells)) if topology else topology
    )
    records = _face_records(bodies, _part_names(bodies, kept_parts, system))
    matched = match_regions(topology, records, wanted_regions=wanted)
    if not matched.ok:
        raise StageFailure(
            "region_unresolved",
            "CAD 가 보낸 조건의 자리를 형상에서 찾지 못했습니다: "
            + " · ".join(
                f"{one.region}[{one.index}] {one.reason}" for one in matched.failures
            ),
            details={"failures": [one.region for one in matched.failures]},
        )

    places = {name: _named_selection(app, name, matched.faces[name]) for name in wanted}
    frames = _build_frames(app, given, system)
    applied: list[str] = []
    rigid_of = _rigid_owner(bodies, matched.faces, rigid_ids or set())
    on_sheet = _sheet_regions(bodies, matched.faces)
    flipped = _flipped_pressures(given, topology, records, matched.faces, on_sheet)
    for load in given.loads:
        if load.region and load.region in rigid_of:
            # 실측(2026-10-04): 강체 면의 힘 · 압력은 `UnderDefined` — 솔브에서 늦게 죽는다.
            raise StageFailure(
                "internal",
                f"하중 「{load.name}」({load.kind}): 강체 파트의 면에 건 하중은 아직 못 "
                "겁니다 — 그 파트를 변형체로 두세요.",
            )
    owner = _face_owner(bodies)

    def pieces(region: str) -> list[Any]:
        """**강체 파트 여럿에 걸친 그룹은 파트마다 나눈다** — 굽힘 시험의 「지지 롤러」 ·
        「로딩 노즈」 는 롤러 · 노즈 둘의 면이다. 한 원격점 · 한 접촉에 강체 둘을 묶으면
        Mechanical 이 입력 파일을 접촉 정의에서 끊었다(2026-10-08, 보드굽힘 · 숏빔 —
        `_check_input_complete`).
        """
        if region not in rigid_of:
            return [places[region]]
        groups: dict[int | None, list[int]] = {}
        for face in matched.faces[region]:
            groups.setdefault(owner.get(int(face)), []).append(int(face))
        if len(groups) < 2:
            return [places[region]]
        return [
            _named_selection(app, f"{region} #{index}", ids)
            for index, ids in enumerate(groups.values(), start=1)
        ]

    for constraint in given.constraints:
        if constraint.region in rigid_of:
            constraint = _on_rigid(constraint)
        for place in pieces(constraint.region):
            _one_constraint(analysis, constraint, place, system, frames)
        applied.append(f"{constraint.kind}:{constraint.region}")
        logger.info("구속 %s(%s) ← %s", constraint.name, constraint.kind, constraint.region)
    if given.contacts:
        # **CAD 가 접촉을 선언했으면 Mechanical 의 자동 접촉을 지운다.** 형상을 읽을 때
        # Mechanical 이 맞닿은 면마다 **접착** 접촉(「Contact Region」)을 스스로 만든다. 그것을
        # 두고 우리 마찰 접촉을 같은 면에 더하면 **접착이 이긴다** — 마찰 μ 0.15 · 클램프 10 kN
        # 의 전단 이음이 μN = 1.5 kN 이 아니라 접착 반력 3,627 N 을 버텼다(실측 2026-10-03,
        # CompCore 전단 이음). 선언이 없으면 남긴다 — 그때는 그 자동 접착이 조립을 붙들고 있다.
        removed = _clear_automatic_contacts(app)
        if removed:
            applied.append(f"auto_contacts_removed:{removed}")
            logger.info("자동 접촉 %s 개를 지웠습니다 — CAD 가 접촉을 선언했습니다", removed)
    for contact in given.contacts:
        source_name, target_name = contact.source, contact.target
        if contact.source in rigid_of and contact.target in rigid_of:
            raise StageFailure(
                "internal",
                f"접촉 「{contact.name}」: 강체 파트끼리의 접촉은 아직 못 겁니다 — 한쪽을 "
                "변형체로 두세요.",
            )
        if contact.source in rigid_of:
            # **강체는 대상면(target)이어야 한다** — 실측(2026-10-04): 강체가 접촉면(source)
            # 이면 `UnderDefined`. 본딩 · 마찰은 두 면을 바꿔도 같은 접촉이다.
            source_name, target_name = target_name, source_name
            applied.append(f"contact_flipped:{contact.name}")
        # 강체 대상면이 파트 여럿이면 파트마다 접촉 하나(`pieces`).
        for target in pieces(target_name):
            region = _one_contact(app, contact, places[source_name], target)
            if contact.source in on_sheet or contact.target in on_sheet:
                # **쉘의 두께를 접촉에 넣는다** — 중간면은 맞닿은 솔리드 면에서 두께의
                # 절반만큼 떨어져 있다. 끄면 그 틈이 접촉 판정에 그대로 남는다.
                try:
                    region.ShellThicknessEffect = True
                except Exception:  # pragma: no cover - Ansys 없이는 안 돈다
                    logger.warning(
                        "접촉 %s 에 쉘 두께를 못 넣었습니다", contact.name, exc_info=True
                    )
        applied.append(f"contact:{contact.kind}")
        logger.info(
            "접촉 %s(%s) %s ↔ %s", contact.name, contact.kind, contact.source, contact.target
        )
    return applied, places, flipped


def _face_owner(bodies: list[Any]) -> dict[int, int]:
    """면 번호 → 그 면이 속한 형상 바디 번호."""
    owner: dict[int, int] = {}
    for body in bodies:
        geo = body.GetGeoBody()
        for face in geo.Faces:
            owner[int(face.Id)] = int(geo.Id)
    return owner


def _rigid_owner(
    bodies: list[Any], faces: dict[str, list[int]], rigid_ids: set[int]
) -> set[str]:
    """강체 파트 위에 있는 영역 이름들 — 면이 **모두** 강체의 것일 때."""
    if not rigid_ids:
        return set()
    owner: dict[int, int] = {}
    for body in bodies:
        geo = body.GetGeoBody()
        for face in geo.Faces:
            owner[int(face.Id)] = int(geo.Id)
    return {
        name
        for name, ids in faces.items()
        if ids and all(owner.get(int(one)) in rigid_ids for one in ids)
    }


def _on_rigid(constraint: condition_model.Constraint) -> condition_model.Constraint:
    """강체 면의 구속 — **고정 지지는 원격 변위(성분 전부 0)로** 건다.

    실측(2026-10-04, 2025 R2): 강체 면의 고정 지지는 `UnderDefined` 고 원격 변위는 받는다.
    강체에서 둘은 같은 구속이다(면이 변형하지 않으므로 「면 고정」 = 「강체 고정」).
    """
    if constraint.kind == "remote_displacement":
        return constraint
    if constraint.kind == "fixed_support":
        return replace(
            constraint,
            kind="remote_displacement",
            components=(0.0, 0.0, 0.0),
            rotations=(0.0, 0.0, 0.0),
        )
    raise StageFailure(
        "internal",
        f"구속 「{constraint.name}」({constraint.kind}): 강체 파트의 면에는 고정 지지 · 원격 "
        "변위만 걸 수 있습니다 — 그 파트를 변형체로 두세요.",
    )


#: 중립 이름 → Mechanical `MethodType`(실측 2026-10-04: `AllTriAllTet` 이 사면체다).
_MESH_METHODS = {
    "automatic": "Automatic",
    "tetrahedrons": "AllTriAllTet",
    "hex_dominant": "HexDominant",
    "sweep": "Sweep",
    "multizone": "MultiZone",
}


def _place_body_settings(
    given: condition_model.Conditions,
    bodies: list[Any],
    topology: dict[str, Any],
    system: units.UnitSystem,
) -> dict[int, condition_model.BodySetting]:
    """파트별 설정 → **바디 번호.** 못 짝지으면 멈춘다 — 설정이 엉뚱한 바디에 붙으면 강체 ·
    제외가 뒤바뀐 모델이 오류 없이 풀린다."""
    if not given.body_settings:
        return {}
    placed, failures = place_settings(
        given.body_settings, topology, _body_records(bodies, system)
    )
    if failures:
        raise StageFailure(
            "internal",
            "파트별 설정의 파트를 형상에서 찾지 못했습니다: " + " · ".join(failures),
            details={"failures": failures},
        )
    return placed


def _apply_body_settings(
    app: Any,
    placed: dict[int, condition_model.BodySetting],
    bodies: list[Any],
    system: units.UnitSystem,
) -> None:
    """파트마다 **제외 · 강체 · 파트 메시**(Body Sizing · Method)를 건다.

    실측(2026-10-04, 2025 R2): `Suppressed` 를 켜면 그 바디에 걸린 자동 접촉도 Mechanical
    이 스스로 끈다. 강체는 `StiffnessBehavior.Rigid` 이고 **메시 칸은 걸지 않는다** — 강체는
    부피를 메시하지 않는다(질량 한 점 · `MASS21`). 메시 칸은 바람이라 못 걸면 경고만 남긴다.
    """
    if not placed:
        return
    enums = _global("Ansys").Mechanical.DataModel.Enums
    quantity = _global("Quantity")
    selection_type = _global("Ansys").ACT.Interfaces.Common.SelectionTypeEnum
    rigid_ids: set[int] = set()
    for index, one in sorted(placed.items()):
        body = bodies[index]
        try:
            if one.suppressed or one.shell:
                # 쉘 파트의 솔리드도 끈다 — 그 자리는 중간면의 면 바디가 맡는다.
                body.Suppressed = True
                logger.info(
                    "파트 %s → %s", one.name, "쉘(솔리드 끔)" if one.shell else "해석 제외"
                )
                continue
            if one.rigid:
                body.StiffnessBehavior = enums.StiffnessBehavior.Rigid
                rigid_ids.add(int(body.GetGeoBody().Id))
                logger.info("파트 %s → 강체", one.name)
                continue
        except Exception as failure:  # pragma: no cover - Ansys 없이는 안 돈다
            raise _translated(
                failure, "internal", f"파트 「{one.name}」 의 설정을 걸지 못했습니다"
            ) from failure
        if not one.meshed:
            continue
        info = app.ExtAPI.SelectionManager.CreateSelectionInfo(selection_type.GeometryEntities)
        info.Ids = [body.GetGeoBody().Id]
        try:
            if one.element_size is not None:
                sizing = app.Model.Mesh.AddSizing()
                sizing.Location = info
                sizing.ElementSize = quantity(f"{one.element_size} [{system.length_label}]")
            if one.method != "automatic" or one.order != "program_controlled":
                method = app.Model.Mesh.AddAutomaticMethod()
                method.Location = info
                method.Method = getattr(enums.MethodType, _MESH_METHODS[one.method])
                if one.order != "program_controlled":
                    method.ElementOrder = (
                        enums.ElementOrder.Quadratic
                        if one.order == "quadratic"
                        else enums.ElementOrder.Linear
                    )
            logger.info("파트 %s → %s", one.name, one.describe())
        except Exception:  # pragma: no cover - Ansys 없이는 안 돈다
            logger.warning(
                "파트 %s 의 메시 설정을 못 걸었습니다 — 넘어갑니다", one.name, exc_info=True
            )
    if rigid_ids:
        _orient_contacts(app, bodies, rigid_ids)


def _apply_whole_method(
    app: Any,
    given: condition_model.Conditions,
    placed: dict[int, condition_model.BodySetting],
    bodies: list[Any],
) -> None:
    """「전체」 요소 형상 — 제 형상을 따로 정한 파트 · 강체 · 뺀 파트를 뺀 바디 전부에.

    좁은 쪽이 이긴다(CompCore 의 순서): 파트의 Method 가 따로 있으면 그것이다. 못 걸면 경고만
    남긴다 — 메시는 바람이다.
    """
    whole = given.whole_mesh
    if whole is None or not whole.method:
        return
    targets = [
        body
        for index, body in enumerate(bodies)
        if not (
            index in placed
            and (
                placed[index].suppressed
                or placed[index].rigid
                or placed[index].method != "automatic"
            )
        )
    ]
    if not targets:
        return
    enums = _global("Ansys").Mechanical.DataModel.Enums
    selection_type = _global("Ansys").ACT.Interfaces.Common.SelectionTypeEnum
    try:
        info = app.ExtAPI.SelectionManager.CreateSelectionInfo(selection_type.GeometryEntities)
        info.Ids = [body.GetGeoBody().Id for body in targets]
        method = app.Model.Mesh.AddAutomaticMethod()
        method.Location = info
        method.Method = getattr(enums.MethodType, _MESH_METHODS[whole.method])
        logger.info("메시 전체 요소 형상 ← CAD %s (바디 %s)", whole.method, len(targets))
    except Exception:  # pragma: no cover - Ansys 없이는 안 돈다
        logger.warning("메시 전체 요소 형상을 못 걸었습니다 — 넘어갑니다", exc_info=True)


def _is_sheet(body: Any) -> bool:
    """면 바디(쉘)인가 — 중간면 형상의 바디다(실측: `GeoBodySheet`, 부피 0)."""
    try:
        return "Sheet" in str(body.GetGeoBody().BodyType)
    except Exception:  # pragma: no cover - Ansys 없이는 안 돈다
        return False


def _import_midsurface(app: Any, workdir: Path, shells: dict[str, float]) -> list[Any]:
    """중간면 형상(`input_mid.step`)을 **두 번째 형상**으로 들여온다 — 바디 전부를 돌려준다."""
    mid = workdir / MIDSURFACE_NAME
    if not mid.is_file():
        raise StageFailure(
            "geometry_import",
            f"쉘 파트({' · '.join(sorted(shells))})가 있는데 중간면 형상({MIDSURFACE_NAME})이 "
            "작업에 없습니다 — CAD 폴더의 pNNNN_mid.step 을 함께 올려야 합니다.",
        )
    return _import_geometry(app, mid)


def _place_sheets(
    sheets: list[Any], topology: dict[str, Any], shells: dict[str, float]
) -> dict[str, Any]:
    """면 바디 → 쉘 파트. 점 파일 `midsurface.bodies[]` 의 **무게중심 · 넓이**로 짝짓는다
    (`_mid.step` 의 셸에는 이름이 없다 — CompCore v0.8.1 이 그 둘을 싣는다)."""
    rows = [
        one
        for one in (topology.get("midsurface") or {}).get("bodies") or []
        if isinstance(one, dict) and str(one.get("name") or "") in shells
    ]
    found: dict[str, Any] = {}
    left = list(sheets)
    for row in rows:
        centre = [float(one) for one in (row.get("centroid") or [0.0, 0.0, 0.0])]

        def gap(body: Any, centre: list[float] = centre) -> float:
            here = (
                float(body.CentroidX.Value),
                float(body.CentroidY.Value),
                float(body.CentroidZ.Value),
            )
            return sum((here[axis] - centre[axis]) ** 2 for axis in range(3))

        if not left:
            break
        pick = min(left, key=gap)
        area = float(pick.SurfaceArea.Value)
        wanted = float(row.get("area") or 0.0)
        if wanted and abs(area - wanted) / wanted > 0.02:
            raise StageFailure(
                "internal",
                f"쉘 파트 「{row['name']}」 의 중간면 넓이가 맞지 않습니다(형상 {area:.1f} · "
                f"점 파일 {wanted:.1f} mm²) — 다른 판을 집었을 수 있습니다.",
            )
        found[str(row["name"])] = pick
        left.remove(pick)
    missing = sorted(set(shells) - set(found))
    if missing:
        raise StageFailure(
            "internal", f"중간면 형상에서 쉘 파트를 찾지 못했습니다: {' · '.join(missing)}"
        )
    return found


def _apply_sheet_settings(
    app: Any,
    sheet_of: dict[str, Any],
    given: condition_model.Conditions,
    system: units.UnitSystem,
) -> None:
    """면 바디에 **두께**(mm)와 파트 요소 크기를 준다. 두께는 점 파일의 값이다."""
    if not sheet_of:
        return
    quantity = _global("Quantity")
    selection_type = _global("Ansys").ACT.Interfaces.Common.SelectionTypeEnum
    sizes = {
        one.name: one.element_size
        for one in given.body_settings
        if one.element_size is not None
    }
    for name, sheet in sheet_of.items():
        try:
            sheet.Thickness = quantity(f"{given.shells[name]} [mm]")
            if name in sizes:
                info = app.ExtAPI.SelectionManager.CreateSelectionInfo(
                    selection_type.GeometryEntities
                )
                info.Ids = [sheet.GetGeoBody().Id]
                sizing = app.Model.Mesh.AddSizing()
                sizing.Location = info
                sizing.ElementSize = quantity(f"{sizes[name]} [{system.length_label}]")
            logger.info("쉘 %s → 두께 %s mm", name, given.shells[name])
        except Exception as failure:  # pragma: no cover - Ansys 없이는 안 돈다
            raise _translated(
                failure, "internal", f"쉘 파트 「{name}」 의 두께를 넣지 못했습니다"
            ) from failure


def _apply_sheet_materials(
    spec: AnySpec,
    sheet_of: dict[str, Any],
    given: list[materials.Material],
    system: units.UnitSystem,
) -> dict[str, MaterialSpec]:
    """면 바디의 물성 — 솔리드와 같은 규칙(CAD 가 먼저, 이름으로). 물성 조각으로 덮는다."""
    if not sheet_of:
        return {}
    names = sorted(sheet_of)
    on_part = materials.assigned(given, names) if given else {}
    made: dict[str, MaterialSpec] = {}
    for name in names:
        chosen = on_part.get(name)
        material = chosen.spec() if chosen is not None else spec.material
        if material is None:
            raise StageFailure("internal", f"쉘 파트 「{name}」 에 붙일 물성이 없습니다.")
        snippet = sheet_of[name].AddCommandSnippet()
        snippet.AppendText(material_commands(material, system))
        made[name] = material
        logger.info("물성 %s ← 쉘 %s", material.name, name)
    return made


def _sheet_mass(
    topology: dict[str, Any], shells: dict[str, float], made: dict[str, MaterialSpec]
) -> float:
    """쉘의 질량(kg) — 점 파일의 중간면 넓이(mm²) x 두께(mm) x 밀도. 계를 타지 않는다."""
    total = 0.0
    for row in (topology.get("midsurface") or {}).get("bodies") or []:
        name = str(row.get("name") or "") if isinstance(row, dict) else ""
        if name in made and name in shells:
            total += (
                float(row.get("area") or 0.0) * shells[name] * 1e-9 * made[name].density_kg_m3
            )
    return total


def _sheet_regions(bodies: list[Any], faces: dict[str, list[int]]) -> set[str]:
    """면 바디(쉘) 위의 영역 이름 — 면이 **모두** 면 바디의 것일 때."""
    sheet_faces: set[int] = set()
    for body in bodies:
        if _is_sheet(body):
            sheet_faces |= {int(face.Id) for face in body.GetGeoBody().Faces}
    return {
        name
        for name, ids in faces.items()
        if ids and all(int(one) in sheet_faces for one in ids)
    }


def _flipped_pressures(
    given: condition_model.Conditions,
    topology: dict[str, Any],
    records: list[FaceRecord],
    faces: dict[str, list[int]],
    on_sheet: set[str],
) -> set[str]:
    """쉘 면의 압력 중 **부호를 뒤집을 것** — 면 법선이 원래 겉면의 바깥 법선과 반대로 섰다.

    Mechanical 의 양의 압력은 면 법선의 반대쪽(안쪽)으로 민다. CAD 가 「바깥 겉면을 누른다」 고
    했으니, 쉘 면의 법선이 그 바깥 법선과 같으면 그대로, 반대면 뒤집는다. 한 영역의 면들이
    서로 엇갈리면 한 부호로 못 건다 — 멈춘다.
    """
    by_id = {one.id: one for one in records}
    flipped: set[str] = set()
    for load in given.loads:
        if load.kind != "pressure" or load.region not in on_sheet:
            continue
        rows = (topology.get("regions") or {}).get(load.region) or []
        outer = next(
            (
                row["outer_normal"]
                for row in rows
                if isinstance(row, dict) and row.get("outer_normal")
            ),
            None,
        )
        if outer is None:
            continue
        signs = set()
        for face in faces.get(load.region) or []:
            normal = by_id[face].normal if face in by_id else None
            if normal is not None:
                signs.add(sum(a * float(b) for a, b in zip(normal, outer, strict=False)) >= 0)
        if len(signs) > 1:
            raise StageFailure(
                "internal",
                f"하중 「{load.name}」: 쉘 면의 법선이 면마다 엇갈려 압력을 한 쪽으로 걸 수 "
                "없습니다.",
            )
        if signs == {False}:
            flipped.add(load.region)
    return flipped


def _orient_contacts(app: Any, bodies: list[Any], rigid_ids: set[int]) -> None:
    """형상을 읽을 때 생긴 자동 접촉을 **강체가 대상면(target)이 되게** 돌린다.

    실측(2026-10-04): 강체가 접촉면(source)이면 `UnderDefined` 다. 강체끼리면 잇지 못한다 —
    그 사실을 말하고 멈춘다(떨어진 강체가 강체 모드로 나오면 이유를 찾을 수 없다).
    """
    enums = _global("Ansys").Mechanical.DataModel.Enums
    owner: dict[int, int] = {}
    for body in bodies:
        geo = body.GetGeoBody()
        for face in geo.Faces:
            owner[int(face.Id)] = int(geo.Id)

    def rigid(location: Any) -> bool:
        ids = [int(one) for one in getattr(location, "Ids", []) or []]
        return bool(ids) and all(owner.get(one) in rigid_ids for one in ids)

    for region in list(
        _global("DataModel").GetObjectsByType(enums.DataModelObjectCategory.ContactRegion)
    ):
        if region.Suppressed:
            continue
        source, target = region.SourceLocation, region.TargetLocation
        if rigid(source) and rigid(target):
            raise StageFailure(
                "internal",
                "강체 파트끼리 맞닿아 있습니다 — 강체끼리는 아직 잇지 못합니다. 한쪽을 "
                "변형체로 두세요.",
            )
        if rigid(source):
            region.SourceLocation = target
            region.TargetLocation = source
            logger.info("자동 접촉 %s — 강체를 대상면으로 돌렸습니다", region.Name)


def _rigid_mass(
    bodies: list[Any], used: Applied, rigid_ids: set[int], system: units.UnitSystem
) -> None:
    """강체의 질량 · 관성을 **CAD 밀도로** 고친다.

    Mechanical 은 강체를 `MASS21` 한 점으로 보내고 그 질량 · 관성을 **Engineering Data 의
    물성**(기본 구조용 강)으로 계산한다 — 우리 물성 조각(`MP,DENS`)은 거기에 닿지 않는다(실측
    2026-10-04: 알루미늄 판이 강의 질량 5.024e-4 t 로 나갔다). 그래서 조각에서 그 실상수를
    **밀도 비만큼** 고친다 — 밀도가 한결같으면 질량 · 관성이 같은 비로 바뀐다. 실상수 번호는
    그 바디의 요소형 번호(`typeids(1)`)와 같다(덱에서 `et,1,21` · `real,1`).
    """
    if not rigid_ids:
        return
    for index, name, material in used.per_body:
        body = bodies[index]
        if int(body.GetGeoBody().Id) not in rigid_ids:
            continue
        volume = float(body.Volume.Value)
        mass = system.density(material.density_kg_m3) * volume
        snippet = body.AddCommandSnippet()
        snippet.AppendText(
            "! SimEngBay rigid body mass from CAD density (MASS21 uses Engineering Data)\n"
            "*get,sebm0,rcon,typeids(1),const,1\n"
            "*if,sebm0,gt,0,then\n"
            f"sebk={mass:.9g}/sebm0\n"
            "*do,sebi,1,6\n"
            "*get,sebv,rcon,typeids(1),const,sebi\n"
            "rmodif,typeids(1),sebi,sebv*sebk\n"
            "*enddo\n"
            "*endif\n"
        )
        logger.info("강체 %s 질량 ← %s (CAD 밀도)", name or index + 1, mass)


def _build_frames(
    app: Any, given: condition_model.Conditions, system: units.UnitSystem
) -> dict[str, Any]:
    """CAD 가 보낸 좌표계를 Mechanical 에 세운다 — 이름 → 좌표계 객체.

    **원점은 선언된 계의 길이**로 온다(`length_units.coordinate_systems`). 축은 단위 벡터인데
    Mechanical 에는 벡터를 적는 칸이 없어 **회전으로 세운다**(실측 2026-10-02:
    `AddTransformation` + `SetTransformationValue(번호, 도)`). 그래서 축 → 각으로 바꾸고
    (`conditions.euler_xyz`, CompCore 와 같은 X → Y → Z 고정축 순서), **세운 뒤 되읽어 맞는지
    본다** — 틀린 좌표계는 성분을 딴 방향으로 걸고 그 사실은 결과를 봐도 모른다.
    """
    import math

    if not given.frames:
        return {}
    axis_type = _global("Ansys").Mechanical.DataModel.Enums.CoordinateSystemAxisType
    kind = _global("Ansys").Mechanical.DataModel.Enums.TransformationType
    quantity = _global("Quantity")
    made: dict[str, Any] = {}
    for frame in given.frames:
        try:
            cs = app.Model.CoordinateSystems.AddCoordinateSystem()
            cs.Name = frame.name
            for name, value in zip(
                ("OriginX", "OriginY", "OriginZ"), frame.origin, strict=True
            ):
                setattr(cs, name, quantity(f"{value} [{system.length_label}]"))
            angles = condition_model.euler_xyz(frame)
            axes = (axis_type.PositiveXAxis, axis_type.PositiveYAxis, axis_type.PositiveZAxis)
            index = 0
            for axis, angle in zip(axes, angles, strict=True):
                if abs(angle) < 1e-9:
                    continue
                cs.AddTransformation(kind.Rotation, axis)
                index += 1
                cs.SetTransformationValue(index, angle)
                # **되읽어 본다** — 돌려주는 값은 라디안이다(실측).
                back = math.degrees(float(cs.GetTransformationValue(index)))
                if abs(back - angle) > 1e-3:
                    raise StageFailure(
                        "internal",
                        f"좌표계 「{frame.name}」 의 회전이 안 들어갔습니다"
                        f"({angle:.4f}° 를 넣었는데 {back:.4f}° 입니다)",
                    )
            made[frame.name] = cs
            logger.info("좌표계 %s ← 원점 %s · 회전 %s", frame.name, frame.origin, angles)
        except StageFailure:
            raise
        except Exception as failure:  # pragma: no cover - Ansys 없이는 안 돈다
            raise _translated(
                failure, "internal", f"좌표계 「{frame.name}」 을 세우지 못했습니다"
            ) from failure
    return made


def _one_constraint(
    analysis: Any,
    constraint: condition_model.Constraint,
    place: Any,
    system: units.UnitSystem,
    frames: dict[str, Any],
) -> None:
    """구속 하나를 Mechanical 에. **못 거는 종류는 여기 오지 않는다**(조건 층이 막는다)."""
    kind = constraint.kind
    try:
        if kind == "fixed_support":
            support = analysis.AddFixedSupport()
        elif kind == "frictionless":
            support = analysis.AddFrictionlessSupport()
        elif kind == "compression_only":
            support = analysis.AddCompressionOnlySupport()
        elif kind == "cylindrical":
            support = analysis.AddCylindricalSupport()
        elif kind == "elastic_support":
            support = analysis.AddElasticSupport()
        elif kind == "displacement":
            support = analysis.AddDisplacement()
        elif kind == "remote_displacement":
            support = analysis.AddRemoteDisplacement()
        else:  # pragma: no cover - 조건 층이 먼저 막는다
            raise StageFailure("internal", f"못 거는 구속입니다: {kind}")
        support.Location = place

        if kind == "cylindrical":
            holds = _global("Ansys").Mechanical.DataModel.Enums.FixedOrFree
            support.Radial = holds.Fixed if constraint.radial == "fixed" else holds.Free
            support.Axial = holds.Fixed if constraint.axial == "fixed" else holds.Free
            support.Tangential = (
                holds.Fixed if constraint.tangential == "fixed" else holds.Free
            )
        elif kind == "elastic_support":
            if constraint.stiffness is None:
                raise StageFailure(
                    "internal", f"탄성 지지 「{constraint.name}」 에 기초 강성이 없습니다"
                )
            quantity = _global("Quantity")
            support.FoundationStiffness = quantity(
                f"{constraint.stiffness} [{system.foundation_label}]"
            )
        elif kind in ("displacement", "remote_displacement"):
            if constraint.cs not in condition_model.GLOBAL_FRAMES:
                found = frames.get(constraint.cs)
                if found is None:  # pragma: no cover - 조건 층이 먼저 막는다
                    raise StageFailure(
                        "internal",
                        f"구속 「{constraint.name}」 이 가리키는 좌표계 "
                        f"「{constraint.cs}」 가 없습니다",
                    )
                support.CoordinateSystem = found
            _components(support, constraint, system, rotations=kind == "remote_displacement")
    except StageFailure:
        raise
    except Exception as failure:  # pragma: no cover - Ansys 없이는 안 돈다
        raise _translated(
            failure, "internal", f"구속 「{constraint.name}」({kind})을 걸지 못했습니다"
        ) from failure


def _components(
    support: Any,
    constraint: condition_model.Constraint,
    system: units.UnitSystem,
    *,
    rotations: bool,
) -> None:
    """성분마다 **자유 · 고정 · 변위량**. `None` 은 건드리지 않는다(기본이 자유다).

    0 은 고정이고 그 밖은 그만큼 움직인다 — 둘을 헷갈리면 구속이 통째로 바뀐다.
    """
    quantity = _global("Quantity")
    axes = ("XComponent", "YComponent", "ZComponent")
    for name, value in zip(axes, constraint.components, strict=True):
        if value is None:
            continue
        getattr(support, name).Output.DiscreteValues = [
            quantity(f"{value} [{system.length_label}]")
        ]
    if not rotations:
        return
    for name, value in zip(
        ("RotationX", "RotationY", "RotationZ"), constraint.rotations, strict=True
    ):
        if value is None:
            continue
        getattr(support, name).Output.DiscreteValues = [quantity(f"{value} [deg]")]


def _clear_automatic_contacts(app: Any) -> int:
    """지금 모델에 있는 **접촉 영역을 전부** 지운다. 지운 수를 돌려준다.

    부르는 때가 정해져 있다 — CAD 의 접촉을 걸기 **바로 전**이다. 그 시점에 있는 접촉은 형상을
    읽을 때 Mechanical 이 만든 자동 접촉뿐이다(캐시는 조건을 걸기 전에 남긴다 — 위 `build`).
    """
    enums = _global("Ansys").Mechanical.DataModel.Enums
    found: list[Any] = []
    try:
        found = list(
            _global("DataModel").GetObjectsByType(enums.DataModelObjectCategory.ContactRegion)
        )
    except Exception:  # pragma: no cover - 전역 이름이 없는 판
        for group in list(app.Model.Connections.Children):
            found.extend(
                child
                for child in list(getattr(group, "Children", []))
                if "ContactRegion" in type(child).__name__
            )
    for one in found:
        one.Delete()
    return len(found)


def _one_contact(app: Any, contact: condition_model.Contact, source: Any, target: Any) -> Any:
    """접촉 한 쌍 — `ConnectionGroup` 아래 `ContactRegion`(실측한 자리)."""
    enums = _global("Ansys").Mechanical.DataModel.Enums
    try:
        group = app.Model.Connections.AddConnectionGroup()
        region = group.AddContactRegion()
        region.SourceLocation = source
        region.TargetLocation = target
        region.ContactType = getattr(enums.ContactType, _CONTACT_TYPES[contact.kind])
        if contact.kind == "frictional" and contact.friction is not None:
            region.FrictionCoefficient = contact.friction
        region.Name = contact.name
    except Exception as failure:  # pragma: no cover - Ansys 없이는 안 돈다
        raise _translated(
            failure, "internal", f"접촉 「{contact.name}」({contact.kind})을 걸지 못했습니다"
        ) from failure
    return region


#: 중립 이름 → Mechanical 의 `ContactType` 멤버(실측 2026-10-02).
_CONTACT_TYPES = {
    "bonded": "Bonded",
    "no_separation": "NoSeparation",
    "frictional": "Frictional",
    "frictionless": "Frictionless",
    "rough": "Rough",
}


def _global_size_mm(
    spec: AnySpec, given: condition_model.Conditions, system: units.UnitSystem
) -> float | None:
    """`_mesh` 가 준 전역 크기(mm) — 스펙 → CAD 「전체」 힌트 → 없으면 `None`(기본값)."""
    if spec.mesh.element_size_mm is not None:
        return float(spec.mesh.element_size_mm)
    for one in given.mesh_hints:
        if one.region in ("전체", "all") and one.element_size is not None:
            return round(one.element_size * system.length_mm, 6)
    return None


def _mesh(
    app: Any,
    spec: AnySpec,
    given: condition_model.Conditions,
    system: units.UnitSystem,
    places: dict[str, Any],
    topology: dict[str, Any],
    bodies: list[Any],
) -> tuple[int, int]:
    """메시를 만든다. **CAD 의 메시 힌트는 바람이다** — 영역마다 주는 것은 그대로 받고,
    전체 크기는 사람이 정한 것이 먼저다.

    전체를 CAD 가 덮게 두면 라이선스 절점 상한(Student)에 걸려 **아무 설계점도 안 돈다.**
    영역 사이징은 더하기만 하므로 그 위험이 없다.
    """
    enums = _global("Ansys").Mechanical.DataModel.Enums
    quantity = _global("Quantity")
    mesh = app.Model.Mesh
    whole = next(
        (
            one
            for one in given.mesh_hints
            if one.region in ("전체", "all") and one.element_size is not None
        ),
        None,
    )
    if spec.mesh.element_size_mm is not None:
        mesh.ElementSize = quantity(f"{spec.mesh.element_size_mm} [mm]")
    elif whole is not None:
        mesh.ElementSize = quantity(f"{whole.element_size} [{system.length_label}]")
        logger.info("메시 전체 크기 ← CAD %s %s", whole.element_size, system.length_label)
    _mesh_sizings(app, given, system, places, topology, bodies)
    wanted = (
        enums.ElementOrder.Quadratic
        if spec.mesh.order == "quadratic"
        else enums.ElementOrder.Linear
    )
    # **같은 값이면 쓰지 않는다.** `ElementOrder` 가 간헐적으로 「This property is
    # parameterized and is read-only」 로 거절된다(실측 2026-10-02: 같은 시험이 두 번은
    # 멀쩡했고 세 번째에 났다). 기본값은 `ProgramControlled` 이고 평소에는 쓰기가 된다.
    if mesh.ElementOrder != wanted:
        try:
            mesh.ElementOrder = wanted
        except Exception as failure:
            # 요청이 2차이고 지금이 `ProgramControlled` 면 **결과가 같다**(실측: 같은 형상 ·
            # 같은 요소 크기에서 절점 1328 · 요소 179 로 동일) — 경고만 남기고 간다.
            # 그 밖에는 멈춘다. 1차 요소로 조용히 풀면 강성이 과하게 나오는데, 그 수는
            # 그럴듯해 보인다.
            if spec.mesh.order != "quadratic" or str(mesh.ElementOrder) != "ProgramControlled":
                raise _translated(
                    failure, "mesh_failed", "요소 차수를 바꾸지 못했습니다"
                ) from failure
            logger.warning(
                "요소 차수를 못 바꿨습니다(읽기 전용) — ProgramControlled 로 갑니다"
                "(2차와 같은 메시다)",
            )
    try:
        mesh.GenerateMesh()
    except Exception as failure:
        raise _translated(failure, "mesh_failed", "메시를 만들지 못했습니다") from failure

    nodes, elements = int(mesh.Nodes), int(mesh.Elements)
    if nodes == 0 or elements == 0:
        raise StageFailure(
            "mesh_failed",
            "메시가 비었습니다 — 요소 크기를 형상에 견주어 다시 정하세요.",
            details={"element_size_mm": spec.mesh.element_size_mm},
        )
    return nodes, elements


def _mesh_sizings(
    app: Any,
    given: condition_model.Conditions,
    system: units.UnitSystem,
    places: dict[str, Any],
    topology: dict[str, Any],
    bodies: list[Any],
) -> None:
    """영역마다의 요소 크기 — `Mesh.AddSizing()`.

    조건이 쓰지 않은 영역에도 힌트가 올 수 있어, 그때는 **여기서 한 번 더 짝짓는다.**
    못 찾으면 **메시 힌트 때문에 해석을 막지는 않는다** — 바람이지 조건이 아니다.
    """
    local = [
        one
        for one in given.mesh_hints
        if one.element_size is not None and one.region not in ("전체", "all")
    ]
    if not local:
        return

    missing = [one.region for one in local if one.region not in places]
    if missing:
        kept_parts = (
            without(topology, given.suppressed | set(given.shells)) if topology else topology
        )
        matched = match_regions(
            topology,
            _face_records(bodies, _part_names(bodies, kept_parts, system)),
            wanted_regions=missing,
        )
        for name in missing:
            ids = matched.faces.get(name)
            if ids:
                places[name] = _named_selection(app, name, ids)
            else:
                logger.warning("메시 힌트의 영역 %s 를 못 찾았습니다 — 그냥 넘어갑니다", name)

    quantity = _global("Quantity")
    for hint in local:
        place = places.get(hint.region)
        if place is None:
            continue
        try:
            sizing = app.Model.Mesh.AddSizing()
            sizing.Location = place
            sizing.ElementSize = quantity(f"{hint.element_size} [{system.length_label}]")
            logger.info("메시 %s ← %s %s", hint.region, hint.element_size, system.length_label)
        except Exception:  # pragma: no cover - Ansys 없이는 안 돈다
            logger.warning(
                "메시 힌트 %s 를 걸지 못했습니다 — 넘어갑니다", hint.region, exc_info=True
            )


def _translated(failure: Exception, code: FailureCode, what: str) -> StageFailure:
    """Ansys 예외를 사람이 읽는 실패로.

    **라이선스는 따로 센다** — 그 실패는 고칠 곳이 다르다(워커 수 · 라이선스 서버).
    """
    if _is_license_problem(failure):
        return StageFailure("license", f"라이선스를 받지 못했습니다: {failure}")
    return StageFailure(code, f"{what}: {failure}")
