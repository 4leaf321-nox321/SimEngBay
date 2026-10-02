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

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core import conditions as condition_model
from app.core import materials, units
from app.core.bodies import BodyRecord, match_bodies
from app.core.regions import FaceRecord, match_regions
from app.core.spec import RIGID_BODY_MODES, MaterialSpec, ModalSpec
from app.core.stages import ArtifactSpec, FailureCode, StageFailure, StageResult

logger = logging.getLogger(__name__)


#: 라이선스 실패로 볼 말. Mechanical 은 이것을 예외 메시지에 실어 준다.
_LICENSE_WORDS = ("license", "licence", "라이선스")


def _is_license_problem(failure: Exception) -> bool:
    text = str(failure).lower()
    return any(word in text for word in _LICENSE_WORDS)


#: CAD 플랫폼이 보낸 영역 지문. 구속이 있는 스펙은 이것이 있어야 돈다.
TOPOLOGY_NAME = "topology.json"

#: **이 작업이 자유-자유인가**를 뒤 단계에 넘기는 자리. 스펙만 보면 알 수 없다 — 구속이
#: CAD 조건에만 있을 수 있고(`conditions_from="cad"`), 그때 결과가 「자유-자유」 로 적히면
#: 강체 모드 수를 세는 경고까지 거짓이 된다(실측 2026-10-02).
BOUNDARY_NAME = "boundary.json"


def build(
    spec: ModalSpec,
    workdir: Path,
    *,
    input_name: str = "input.step",
    version: int = 252,
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
    # **CAD 가 보낸 조건** — 못 거는 것이 하나라도 있으면 여기서 멈춘다(Mechanical 을 띄우기
    # 전에). 조용히 빼면 「조건을 넣었는데 왜 결과가 같지」 를 사람이 물을 자리가 없다.
    given_conditions = _declared_conditions(spec, topology)

    app = _start_app(version)
    try:
        _use_unit_system(app, system)
        bodies = _import_geometry(app, step)
        used = _apply_material(spec, bodies, system, given, topology)
        constrained = bool(given_conditions.constraints or spec.constraints)
        # **선응력이면 정적 해석이 먼저다** — 조여 놓은 상태의 공진을 보려면 그 응력을 안고
        # 풀어야 한다(CompCore 의 주 용도). 하중은 그 정적 해석에 걸린다.
        upstream = _add_static(app) if given_conditions.prestressed else None
        analysis = _add_modal(
            app, spec, constrained=constrained, given=given_conditions, upstream=upstream
        )
        _write_boundary(workdir, constrained=constrained, spec=spec)
        _guard_solver_units(analysis, system)
        places: dict[str, Any] = {}
        if given_conditions.constraints or given_conditions.contacts:
            regions, places = _apply_given_conditions(
                app,
                given_conditions,
                system,
                topology or {},
                bodies,
                upstream if upstream is not None else analysis,
            )
        else:
            regions = _apply_constraints(app, spec, workdir, bodies, analysis)
        if upstream is not None:
            _apply_loads(app, given_conditions, system, places, upstream)
        mass = _mass_kg(used, bodies, system)
        nodes, elements = _mesh(
            app, spec, given_conditions, system, places, topology or {}, bodies
        )

        dat = workdir / "model.dat"
        if upstream is not None:
            # **정적 덱을 따로 낸다.** 모달의 덱은 재시작(linear perturbation)이라 앞선 정적
            # 해석의 `.rdb` · `.rnnn` 이 같은 폴더에 있어야 한다 — 없으면 MAPDL 이 그 자리에서
            # 죽는다(실측 2026-10-02). 솔브 단계가 이 파일을 먼저 푼다.
            static_dat = workdir / "static.dat"
            try:
                upstream.WriteInputFile(str(static_dat))
            except Exception as failure:  # pragma: no cover - Ansys 없이는 안 돈다
                raise _translated(
                    failure, "solver_failed", "정적 해석 입력 파일을 쓰지 못했습니다"
                ) from failure
            artifacts_extra = [ArtifactSpec("dat", static_dat)]
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

        return StageResult(
            artifacts=artifacts,
            summary={
                "bodies": len(bodies),
                "nodes": nodes,
                "elements": elements,
                # **실제로 요청한 수**다 — 구속이 CAD 조건에만 있으면 스펙의 수와 다르다.
                "modes_requested": spec.modes + (0 if constrained else RIGID_BODY_MODES),
                "ansys_version": version,
                "constrained_regions": regions,
                "mass_kg": mass,
                "unit_system": system.key,
                "solver_unit_system": system.solver,
                # **무슨 물성으로 돌았나.** 적지 않으면 「CAD 가 보낸 재료로 돈 것인지」 를
                # 나중에 알 방법이 없다 — 재료를 훑는 DOE 에서 그것이 결과의 절반이다.
                "conditions_from": "cad" if given_conditions.constraints else "spec",
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
    spec: ModalSpec, workdir: Path, system: units.UnitSystem
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
    spec: ModalSpec, topology: dict[str, Any] | None
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
    spec: ModalSpec,
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


def _add_static(app: Any) -> Any:
    """선응력을 만들 정적 해석. 구속과 하중이 여기 걸린다.

    **재시작 파일을 남기라고 이른다**(`RESCONTROL,LINEAR`). 그것이 없으면 모달의 재시작 덱이
    「multiframe restart 파일이 없다」 로 죽는다 — MAPDL 이 그렇게 시키라고 적어 준 그대로다.
    """
    static = app.Model.AddStaticStructuralAnalysis()
    snippet = static.AddCommandSnippet()
    snippet.AppendText(
        "! SimEngBay: keep restart files for the modal perturbation\nRESCONTROL,LINEAR\n"
    )
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
) -> None:
    """하중을 **정적 해석에** 건다 — 그 응력을 모달이 안고 푼다.

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


def _write_boundary(workdir: Path, *, constrained: bool, spec: ModalSpec) -> None:
    """뒤 단계(결과 추출)가 읽을 한 줄 — **무엇으로 돌았나.**"""
    (workdir / BOUNDARY_NAME).write_text(
        json.dumps(
            {
                "constrained": constrained,
                "modes_requested": spec.modes + (0 if constrained else RIGID_BODY_MODES),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
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


def _face_records(bodies: list[Any]) -> list[FaceRecord]:
    """Mechanical 의 면들을 **코어가 아는 모양**으로 옮긴다(`app/core/regions`).

    법선은 `Normals` 의 첫 셋을 쓴다 — 평면이면 어디서 재도 같고, 굽은 면은 한 값으로 말할
    수 없어 매칭이 반지름 · 중심으로 간다.
    """
    found: list[FaceRecord] = []
    for body in bodies:
        geo = body.GetGeoBody()
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
                )
            )
    return found


def _apply_constraints(
    app: Any, spec: ModalSpec, workdir: Path, bodies: list[Any], analysis: Any
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
) -> tuple[list[str], dict[str, Any]]:
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
        return [], {}

    matched = match_regions(topology, _face_records(bodies), wanted_regions=wanted)
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
    for constraint in given.constraints:
        _one_constraint(analysis, constraint, places[constraint.region], system, frames)
        applied.append(f"{constraint.kind}:{constraint.region}")
        logger.info("구속 %s(%s) ← %s", constraint.name, constraint.kind, constraint.region)
    for contact in given.contacts:
        _one_contact(app, contact, places[contact.source], places[contact.target])
        applied.append(f"contact:{contact.kind}")
        logger.info(
            "접촉 %s(%s) %s ↔ %s", contact.name, contact.kind, contact.source, contact.target
        )
    return applied, places


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


def _one_contact(app: Any, contact: condition_model.Contact, source: Any, target: Any) -> None:
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


#: 중립 이름 → Mechanical 의 `ContactType` 멤버(실측 2026-10-02).
_CONTACT_TYPES = {
    "bonded": "Bonded",
    "no_separation": "NoSeparation",
    "frictional": "Frictional",
    "frictionless": "Frictionless",
    "rough": "Rough",
}


def _mesh(
    app: Any,
    spec: ModalSpec,
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
    mesh.ElementOrder = (
        enums.ElementOrder.Quadratic
        if spec.mesh.order == "quadratic"
        else enums.ElementOrder.Linear
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
        matched = match_regions(topology, _face_records(bodies), wanted_regions=missing)
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
