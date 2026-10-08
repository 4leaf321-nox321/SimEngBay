"""가짜 실행기 — 단계마다 잠깐 쉬고 **모양만 맞는** 산출물을 남긴다.

시험과 Ansys 없는 PC 가 쓴다. 상태 기계 · 산출물 등록 · 화면 타임라인 · PAT 경로가 전부 이것
검증되고, 1.5단계는 실행기만 진짜로 갈아끼운다. 그래서 파일 이름과 `result.json` 의 모양은
진짜 실행기와 **같아야 한다** — 화면이 이 모양을 보고 만들어지기 때문이다.

고유진동수는 지어낸 값이다. 스펙의 물성으로 그럴듯하게(강성/밀도 제곱근에 비례) 만들어, 화면이
「값이 바뀌는 것」 을 볼 수 있게만 한다. 자유-자유면 앞 6개를 0 근처로 둔다.

## 세 레시피 · 요소 크기

정적 · 조화도 **진짜와 같은 모양**으로 낸다(`dpf/static.py` · `dpf/harmonic.py`) — 측정점 ·
반력 · 곡선까지. 스터디 비교 · 실측 맞추기를 API 시험으로 끝까지 밟으려면 그 모양이 있어야
한다. 요소 크기를 주면 **절점 수와 값이 따라 움직인다**(성긴 메시는 뻣뻣하다 — 주파수는 높게,
변형은 작게 나온다). 메시 수렴 점검이 그것으로 시험된다. 값은 여전히 지어낸 것이다.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from app.core import conditions as condition_model
from app.core import probes as core_probes
from app.core.harmonic import harmonic_plan
from app.core.spec import (
    RIGID_BODY_MODES,
    HarmonicSpec,
    MaterialSpec,
    ModalSpec,
    StaticSpec,
    parse_stored_spec,
)
from app.core.stages import (
    ArtifactSpec,
    CancelCheck,
    StageCanceled,
    StageContext,
    StageFailure,
    StageResult,
)


class FakeExecutor:
    name = "fake"

    def __init__(self, *, stage_seconds: float = 0.0) -> None:
        self.stage_seconds = stage_seconds

    def run(self, ctx: StageContext, should_cancel: CancelCheck | None = None) -> StageResult:
        # 쉬는 동안에도 취소를 본다 — 진짜 실행기와 같은 규약이라야 시험이 뜻을 갖는다.
        waited = 0.0
        while waited < self.stage_seconds:
            if should_cancel is not None and should_cancel():
                raise StageCanceled(f"{ctx.stage} 단계에서 취소했습니다.")
            time.sleep(min(0.2, self.stage_seconds - waited))
            waited += 0.2
        if should_cancel is not None and should_cancel():
            raise StageCanceled(f"{ctx.stage} 단계에서 취소했습니다.")
        spec = parse_stored_spec(ctx.spec)
        handler = getattr(self, f"_{ctx.stage}")
        result: StageResult = handler(ctx, spec)
        return result

    # --- 단계 -----------------------------------------------------------------

    def _fetching(self, ctx: StageContext, spec: AnySpec) -> StageResult:
        source = ctx.workdir / ctx.input_name
        if not source.is_file():
            raise StageFailure("geometry_import", f"입력 형상이 없습니다: {ctx.input_name}")
        if source.stat().st_size == 0:
            raise StageFailure("geometry_import", "입력 형상이 빈 파일입니다.")
        return StageResult(
            summary={"input_bytes": source.stat().st_size},
            detail=f"{ctx.input_name} ({source.stat().st_size:,} B)",
        )

    def _modeling(self, ctx: StageContext, spec: AnySpec) -> StageResult:
        dat = ctx.workdir / "model.dat"
        kind = {"modal": "MODAL", "static": "STATIC", "harmonic": "HARMIC"}[spec.recipe]
        dat.write_text(
            "/PREP7\n! fake input — 진짜 실행기가 오면 WriteInputFile 의 것으로 바뀐다\n"
            f"! material {_material(spec).name}\n/SOLU\nANTYPE,{kind}\nSOLVE\nFINISH\n",
            encoding="utf-8",
        )
        mechdb = ctx.workdir / "model.mechdb"
        mechdb.write_bytes(b"fake mechdb\n")
        nodes, elements = _mesh_counts(spec)
        return StageResult(
            artifacts=[ArtifactSpec("dat", dat), ArtifactSpec("mechdb", mechdb)],
            summary={
                "bodies": 1,
                "nodes": nodes,
                "elements": elements,
                # **실제로 쓴 전역 요소 크기** — 메시 수렴 점검이 이것을 기준으로 줄인다.
                "element_size_mm": _element_size(spec),
                # 지어낸 부피 x 진짜 밀도 — 화면이 「질량 칸이 있다」 를 보고 만들어진다.
                "mass_kg": round(1.2e-4 * _material(spec).density_kg_m3, 4),
            },
            detail=f"바디 1 · 절점 {nodes:,}",
        )

    def _solving(self, ctx: StageContext, spec: AnySpec) -> StageResult:
        if not (ctx.workdir / "model.dat").is_file():
            raise StageFailure(
                "solver_failed", "model.dat 이 없습니다 — 모델링 단계가 남긴 것이 없습니다."
            )
        rst = ctx.workdir / "model.rst"
        rst.write_bytes(b"fake rst\n")
        out = ctx.workdir / "solve.out"
        out.write_text("*** FAKE SOLVE ***\nELAPSED TIME 0.0 s\n", encoding="utf-8")
        return StageResult(
            artifacts=[ArtifactSpec("rst", rst), ArtifactSpec("solve_out", out)],
            detail="fake 솔브",
        )

    def _extracting(self, ctx: StageContext, spec: AnySpec) -> StageResult:
        if isinstance(spec, StaticSpec):
            return _static(ctx, spec)
        if isinstance(spec, HarmonicSpec):
            return _harmonic(ctx, spec)
        modes: list[dict[str, Any]] = []
        elastic_index = 0
        for index, value in enumerate(_fake_frequencies(spec)):
            rigid = spec.is_free_free and index < RIGID_BODY_MODES
            if not rigid:
                elastic_index += 1
            # **진짜 실행기와 같은 칸을 낸다.** 화면이 이 모양을 보고 만들어지므로, 여기가
            # 한 칸 모자라면 fake 로 본 화면과 진짜로 본 화면이 다르다.
            modes.append(
                {
                    "number": index + 1,
                    "elastic_number": None if rigid else elastic_index,
                    "frequency_hz": round(value, 4),
                    "rigid_body": rigid,
                }
            )
        result: dict[str, Any] = {
            "recipe": "modal",
            "boundary": "free-free" if spec.is_free_free else "constrained",
            # **단위계와 정규화 방식을 반드시 싣는다.** 값만 보면 mm-t-s 와 SI 가 구별되지
            # 않고, 그 차이는 고유진동수를 31.6배 틀리게 한다.
            "units": {"frequency": "Hz", "length": "mm", "mass": "t"},
            "normalization": "mass",
            "rigid_body_modes": RIGID_BODY_MODES if spec.is_free_free else 0,
            "mesh": dict(zip(("nodes", "elements"), _mesh_counts(spec), strict=True)),
            "modes": modes,
            # 모드 형상 · 참여계수는 **안 만든다.** 가짜 그림을 그리면 화면에서 진짜와
            # 구별되지 않는다 — 없으면 화면이 「그림이 없습니다」 라고 말한다.
            "participation": {},
            "fake": True,
        }
        result_path = ctx.workdir / "result.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        elastic = [one for one in modes if not one["rigid_body"]]
        first: float | None = elastic[0]["frequency_hz"] if elastic else None
        return StageResult(
            artifacts=[ArtifactSpec("result_json", result_path)],
            summary={"modes": len(modes), "first_elastic_hz": first},
            detail=f"모드 {len(modes)}개" + (f" · 1차 {first} Hz" if first else ""),
        )


AnySpec = ModalSpec | StaticSpec | HarmonicSpec

#: 요소 크기를 안 주면 이것으로 본다(mm) — 지어낸 기준.
BASE_SIZE_MM = 5.0


#: 스펙에 물성이 없을 때(CAD 가 보낸 것으로 풀 때) 숫자를 지어낼 값 — 자릿수만 정한다.
CAD_STAND_IN = MaterialSpec(
    name="CAD 물성", youngs_modulus_gpa=200, poisson_ratio=0.3, density_kg_m3=7850
)


def _material(spec: AnySpec) -> MaterialSpec:
    return spec.material or CAD_STAND_IN


def _element_size(spec: AnySpec) -> float:
    return float(spec.mesh.element_size_mm or BASE_SIZE_MM)


def _mesh_counts(spec: AnySpec) -> tuple[int, int]:
    """요소 크기에 따라 **세제곱으로** 는다(크기를 반으로 줄이면 절점이 여덟 배)."""
    ratio = (BASE_SIZE_MM / _element_size(spec)) ** 3
    return round(12_345 * ratio), round(6_789 * ratio)


def _stiffening(spec: AnySpec) -> float:
    """성긴 메시는 **뻣뻣하다** — 크기의 제곱에 비례해 강성이 부푼다(2차 요소의 수렴 차수)."""
    return 1.0 + 0.02 * (_element_size(spec) / BASE_SIZE_MM) ** 2


def _fake_frequencies(spec: ModalSpec | HarmonicSpec) -> list[float]:
    """지어낸 고유진동수. 강성/밀도 제곱근에 비례하게 만들어 물성을 바꾸면 값이 따라오게
    한다. 성긴 메시일수록 조금 높다."""
    material = _material(spec)
    scale = (
        math.sqrt(material.youngs_modulus_gpa * 1e9 / material.density_kg_m3) / 1000
    ) * math.sqrt(_stiffening(spec))
    values: list[float] = []
    if isinstance(spec, ModalSpec) and spec.is_free_free:
        values.extend(0.0001 * (index + 1) for index in range(RIGID_BODY_MODES))
    # 1차가 250 Hz 남짓 — 실제 부품의 자릿수다(0.25 Hz 로 두면 반올림에 메시 차이가 묻힌다).
    values.extend(scale * (50 * (index + 1) ** 1.5) for index in range(spec.modes))
    return values


def _topology(ctx: StageContext) -> dict[str, Any]:
    path = ctx.workdir / "topology.json"
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _spots(topology: dict[str, Any]) -> list[core_probes.Spot]:
    """점 그룹마다 「절점」 하나 — 지어낸 번호, 거리 0."""
    return [
        core_probes.Spot(
            name=name,
            point=point,
            node=index + 1,
            distance_mm=0.0,
            body=core_probes.body_of(topology, name),
        )
        for index, (name, point) in enumerate(core_probes.wanted(topology).items())
    ]


def _write(ctx: StageContext, result: dict[str, Any]) -> Path:
    path = ctx.workdir / "result.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _static(ctx: StageContext, spec: StaticSpec) -> StageResult:
    """정적 — `dpf/static.py` 와 같은 열쇠. 변형은 강성에 반비례, 응력은 **정련할수록 큰다**
    (구속 모서리의 특이점처럼)."""
    softness = 200.0 / _material(spec).youngs_modulus_gpa
    largest = round(0.04 * softness / _stiffening(spec), 8)
    stress = round(120.0 * (1 + 0.05 * BASE_SIZE_MM / _element_size(spec)), 6)
    topology = _topology(ctx)
    probes = [
        core_probes.row(
            name=spot.name,
            point=spot.point,
            node=spot.node,
            distance_mm=spot.distance_mm,
            value=largest * (0.5 + 0.1 * index),
            unit="mm",
            vector=[largest * (0.5 + 0.1 * index), 0.0, 0.0],
            body=spot.body,
            # 수직 변형률 — 변형처럼 강성에 반비례하게 지어낸다.
            strain=[2e-4 * softness / _stiffening(spec), -6e-5 * softness, -1e-4 * softness],
        )
        for index, spot in enumerate(_spots(topology))
    ]
    reactions: dict[str, list[float]] = {}
    if topology:
        given = condition_model.read(topology, recipe="static")
        for rule in given.constraints:
            if rule.kind == "displacement":
                reactions[rule.region] = [round(1500.0 / _stiffening(spec), 6), 0.0, 0.0]
    nodes, elements = _mesh_counts(spec)
    result: dict[str, Any] = {
        "recipe": "static",
        "units": {
            "system": "ConsistentNMM",
            "displacement": "mm",
            "stress": "MPa",
            "force": "N",
        },
        "mesh": {"nodes": nodes, "elements": elements},
        "max_displacement": largest,
        **({"probes": probes} if probes else {}),
        **({"reactions": reactions} if reactions else {}),
        "max_von_mises": stress,
        "material": _material(spec).name,
        "fake": True,
    }
    path = _write(ctx, result)
    return StageResult(
        artifacts=[ArtifactSpec("result_json", path)],
        summary={"nodes": nodes, "max_displacement": largest, "max_von_mises": stress},
        detail=f"최대 변형 {largest:.4g} mm",
    )


def _harmonic(ctx: StageContext, spec: HarmonicSpec) -> StageResult:
    """조화 — `dpf/harmonic.py` 와 같은 열쇠. 1차 모드 하나의 공진(1자유도)으로 곡선을
    짓는다. 범위 · 점 수 · 감쇠비는 진짜와 같이 **CAD 가 적은 것이 먼저다**
    (`harmonic_plan`)."""
    topology = _topology(ctx)
    plan = harmonic_plan(spec, condition_model.read(topology, recipe="harmonic"))
    low, high = plan.low, plan.high
    count = max(plan.intervals, 1)
    natural = _fake_frequencies(spec)[0]
    damping = plan.damping_ratio
    spots = _spots(topology)
    points: list[dict[str, Any]] = []
    for index in range(count + 1):
        frequency = low + (high - low) * index / count
        ratio = frequency / natural if natural > 0 else 0.0
        size = 0.01 / math.sqrt((1 - ratio**2) ** 2 + (2 * damping * ratio) ** 2)
        row: dict[str, Any] = {
            "frequency_hz": round(frequency, 4),
            "max_displacement": round(size, 10),
        }
        if spots:
            row["probes"] = {spot.name: round(size * 0.6, 10) for spot in spots}
        points.append(row)
    worst = max(points, key=lambda one: one["max_displacement"])
    nodes, elements = _mesh_counts(spec)
    result: dict[str, Any] = {
        "recipe": "harmonic",
        "units": {"frequency": "Hz", "displacement": "mm", "system": "ConsistentNMM"},
        "mesh": {"nodes": nodes, "elements": elements},
        "damping_ratio": damping,
        "points": points,
        "peak": worst,
        "material": _material(spec).name,
        "fake": True,
    }
    tops = core_probes.peaks(spots, points, unit="mm")
    if tops:
        result["probes"] = tops
    path = _write(ctx, result)
    return StageResult(
        artifacts=[ArtifactSpec("result_json", path)],
        summary={
            "frequency_points": len(points),
            "peak_hz": worst["frequency_hz"],
            "peak_displacement": worst["max_displacement"],
        },
        detail=f"{len(points)}점 · 최대 {worst['max_displacement']:.4g} mm",
    )


def write_fixture_step(path: Path) -> None:
    """시험용 STEP 흉내. 진짜 STEP 헤더만 있어 fake 실행기가 「비지 않은 파일」 로 받는다."""
    path.write_text(
        "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('fake'),'2;1');\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n",
        encoding="utf-8",
    )
