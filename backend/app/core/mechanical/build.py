"""FE 모델을 만든다 — 임포트 · 물성 · 메시 · 해석 설정 · `.dat`.

## 실측으로 정한 것 (2026-09-20, Ansys 2025 R2 · Student · Windows)

- **임포트**: `GeometryImportGroup.AddGeometryImport()` + `GeometryImportPreferences`.
  AutoJigGenerator(build123d/OpenCascade)가 낸 STEP 이 그대로 들어온다 — 판 · L 브래킷 확인.
- **물성은 명령 조각(command snippet)으로 준다.** MatML XML 을 만들어 Engineering Data 에
  넣는 길도 있지만, 그 형식은 길고 한 칸이 틀려도 「임포트는 됐는데 값이 안 들어간」 상태가
  된다 — 그 상태는 고유진동수가 틀린 뒤에야 드러난다. 바디에 붙인 명령 조각은 `/PREP7` 의
  기본 물성(Structural Steel) **뒤에** 들어가 덮어쓴다(실측: `MP,EX,1,…` 다음 줄에 우리 것).
- **단위계는 확인하고 쓴다.** 명령 조각의 숫자에는 단위가 없다 — 활성 단위계가 MKS(m·kg·N·s)
  여야 `MP,EX,matid,2e11` 이 200 GPa 다. 아니면 **세우지 않는다**: 1000배 틀린 값은 아무 오류도
  내지 않고 고유진동수만 31.6배 어긋난다.
- **구속이 없으면 자유-자유**다. 강체 모드 6개가 0 Hz 로 나오므로 찾을 모드 수에 6을 더한다
  (`spec.modes_to_find`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.regions import FaceRecord, match_regions
from app.core.spec import ModalSpec
from app.core.stages import ArtifactSpec, FailureCode, StageFailure, StageResult

logger = logging.getLogger(__name__)

#: 이 단위계일 때만 명령 조각의 숫자가 Pa · kg/m³ 로 읽힌다.
EXPECTED_UNIT_SYSTEM = "StandardMKS"

#: 라이선스 실패로 볼 말. Mechanical 은 이것을 예외 메시지에 실어 준다.
_LICENSE_WORDS = ("license", "licence", "라이선스")


def _is_license_problem(failure: Exception) -> bool:
    text = str(failure).lower()
    return any(word in text for word in _LICENSE_WORDS)


#: CAD 플랫폼이 보낸 영역 지문. 구속이 있는 스펙은 이것이 있어야 돈다.
TOPOLOGY_NAME = "topology.json"


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

    app = _start_app(version)
    try:
        _guard_unit_system(app)
        bodies = _import_geometry(app, step)
        _apply_material(spec, bodies)
        analysis = _add_modal(app, spec)
        regions = _apply_constraints(app, spec, workdir, bodies, analysis)
        mass = _mass_kg(spec, bodies)
        nodes, elements = _mesh(app, spec)

        dat = workdir / "model.dat"
        try:
            analysis.WriteInputFile(str(dat))
        except Exception as failure:  # pragma: no cover - Ansys 없이는 안 돈다
            raise _translated(
                failure, "solver_failed", "솔버 입력 파일을 쓰지 못했습니다"
            ) from failure
        if not dat.is_file():
            raise StageFailure("solver_failed", "솔버 입력 파일이 만들어지지 않았습니다.")

        artifacts = [ArtifactSpec("dat", dat)]
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
                "modes_requested": spec.modes_to_find,
                "ansys_version": version,
                "constrained_regions": regions,
                "mass_kg": mass,
            },
            detail=(
                f"바디 {len(bodies)} · 절점 {nodes:,} · 요소 {elements:,}"
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


def _guard_unit_system(app: Any) -> None:
    """활성 단위계가 MKS 인가.

    **아니면 세우지 않는다** — 명령 조각의 숫자에는 단위가 없다.
    """
    try:
        active = str(app.ExtAPI.Application.ActiveUnitSystem)
    except Exception:  # pragma: no cover - 읽을 수 없으면 넘어간다(값 자체는 기본이 MKS)
        logger.warning("활성 단위계를 읽지 못했습니다 — MKS 로 가정합니다", exc_info=True)
        return
    if EXPECTED_UNIT_SYSTEM not in active:
        raise StageFailure(
            "internal",
            f"활성 단위계가 {active} 입니다. 물성 명령이 Pa · kg/m³ 로 읽히려면 "
            f"{EXPECTED_UNIT_SYSTEM}(m · kg · N · s)여야 합니다.",
            details={"unit_system": active},
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


def _apply_material(spec: ModalSpec, bodies: list[Any]) -> None:
    """바디마다 명령 조각으로 물성을 덮어쓴다.

    `matid` 는 Mechanical 이 조각에 심어 주는 값이다 — 바디마다 재료 번호가 다를 수 있다.
    """
    material = spec.material
    text = (
        f"! SimEngBay — 스펙의 물성으로 덮어쓴다 ({material.name})\n"
        f"MP,EX,matid,{material.youngs_modulus_gpa * 1e9:.6g}\n"
        f"MP,PRXY,matid,{material.poisson_ratio:.6g}\n"
        f"MP,DENS,matid,{material.density_kg_m3:.6g}\n"
    )
    for body in bodies:
        snippet = body.AddCommandSnippet()
        snippet.AppendText(text)


def _add_modal(app: Any, spec: ModalSpec) -> Any:
    analysis = app.Model.AddModalAnalysis()
    analysis.AnalysisSettings.MaximumModesToFind = spec.modes_to_find
    return analysis


def _mass_kg(spec: ModalSpec, bodies: list[Any]) -> float | None:
    """부피 x 밀도. **설계점 비교의 두 번째 축이다** — 지그는 가볍고 단단해야 한다.

    부피는 활성 단위계(MKS)에서 m³ 로 온다(`_guard_unit_system` 이 그것을 보장한다). 못 읽으면
    `None` — **틀린 질량은 맞는 침묵보다 나쁘다.**
    """
    try:
        volume = sum(float(body.Volume.Value) for body in bodies)
    except Exception:  # pragma: no cover - 형상에 따라 못 읽을 수 있다
        logger.warning("부피를 읽지 못했습니다 — 질량을 내지 않습니다", exc_info=True)
        return None
    if volume <= 0:
        return None
    return round(volume * spec.material.density_kg_m3, 4)


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

    selection_type = _global("Ansys").ACT.Interfaces.Common.SelectionTypeEnum
    applied: list[str] = []
    for constraint in spec.constraints:
        ids = matched.faces[constraint.region]
        named = app.Model.AddNamedSelection()
        named.Name = constraint.region
        info = app.ExtAPI.SelectionManager.CreateSelectionInfo(selection_type.GeometryEntities)
        info.Ids = ids
        named.Location = info
        # 지금 거는 것은 완전 고정 하나다. 원통 구속 · 볼트 예압은 조건 모델이 오면 붙는다.
        support = analysis.AddFixedSupport()
        support.Location = named
        applied.append(constraint.region)
        logger.info("구속 %s ← 면 %s", constraint.region, ids)
    return applied


def _mesh(app: Any, spec: ModalSpec) -> tuple[int, int]:
    enums = _global("Ansys").Mechanical.DataModel.Enums
    quantity = _global("Quantity")
    mesh = app.Model.Mesh
    if spec.mesh.element_size_mm is not None:
        mesh.ElementSize = quantity(f"{spec.mesh.element_size_mm} [mm]")
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


def _translated(failure: Exception, code: FailureCode, what: str) -> StageFailure:
    """Ansys 예외를 사람이 읽는 실패로.

    **라이선스는 따로 센다** — 그 실패는 고칠 곳이 다르다(워커 수 · 라이선스 서버).
    """
    if _is_license_problem(failure):
        return StageFailure("license", f"라이선스를 받지 못했습니다: {failure}")
    return StageFailure(code, f"{what}: {failure}")
