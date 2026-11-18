"""조화 응답 결과 — `.frd` 에서 **주파수마다 진폭.**

CalculiX 는 주파수 하나에 블록을 **둘** 적는다(실측 2026-10-03): `DISP` 가 실수부,
`DISPI` 가 허수부다. 진폭은 성분마다 둘을 합쳐 크기를 낸다 —

    진폭 = √( Σ (실수부² + 허수부²) )

**실수부만 읽으면 안 된다.** 위상에 따라 작게 나오고 공진이 평평해 보인다 — Ansys 쪽에서
진폭 연산자를 쓰기로 한 것과 같은 이유다.

결과 모양은 Ansys 쪽과 같다(`app/core/dpf/harmonic.py`) — 화면(`HarmonicResult`)이 그 열쇠를
읽는다.

## 잔여 벡터 · 응력 (2026-11-18)

덱이 하중마다 정적 단계 · 거의 0 Hz 훑기 단계를 붙이고 고유치 단계에 모드 형상 · 응력을 적는다
(`deck.write_harmonic`). 블록은 단계 번호로 가른다(`frd.Block.stage` — 고유치 1 · 훑기 2 ·
하중 l 의 정적 3+2l · 0 Hz 4+2l). 하중마다

- 모드 계수 c 를 0 Hz 응답에서 되찾고(`superposition.modal_coefficients`),
- 잔여 벡터 R = 정적 해 - Σ cₘφₘ 를 주파수마다 배율 · 위상을 곱해 더한다 — 준정적 부품
  (고유진동수 ≫ 범위)이 모드 수만큼 작게 나오던 것(시험_진동_150Hz 모드 20 개 -29.5 %)을
  메운다.
- **응력은 봉우리 주파수에서** 모드 응력 x 모드 좌표 + 잔여 응력으로 낸다 — 위상을 돌린 최대
  상당응력(`superposition.peak_von_mises`). 훑기 단계에 응력을 적으면 `.frd` 가 주파수 점마다
  모든 절점의 응력으로 1,000만 줄이 된다.

**감쇠비는 모델링이 남긴 `boundary.json` 에서 읽는다**: CAD 가 적어 보낸 값이 스펙을
이길 수 있고, 그때 결과에 스펙 값을 적으면 화면이 거짓말을 한다(봉우리 높이는 1/2ζ 로 읽힌다).
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from app.core import boundary, excitation, superposition
from app.core import conditions as condition_model
from app.core import probes as core_probes
from app.core.calculix import frd as frd_reader
from app.core.calculix import probes
from app.core.numbers import significant
from app.core.spec import HarmonicSpec
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

RESULT_NAME = "result.json"
FRD_NAME = "model.frd"
BOUNDARY_NAME = "boundary.json"
MSH_NAME = "model.msh"

#: 이보다 크면 「감쇠가 모자란 것 아닌가」 를 적어 둔다(mm). Ansys 쪽과 같은 문턱.
SUSPICIOUS_DISPLACEMENT = 1e3


def extract(spec: HarmonicSpec, workdir: Path, **_ignored: object) -> StageResult:
    """`model.frd` → `result.json` (주파수 곡선)."""
    result_file = workdir / FRD_NAME
    if not result_file.is_file():
        raise StageFailure("solver_failed", f"결과 파일이 없습니다: {FRD_NAME}")

    real: dict[float, frd_reader.Block] = {}
    imaginary: dict[float, frd_reader.Block] = {}
    blocks = frd_reader.read_folded(workdir, result_file)
    staged = _staged(blocks, boundary.read(workdir))
    for block in blocks:
        if staged is not None and block.stage != SWEEP_STAGE:
            continue
        if block.kind == "DISP":
            real[block.value] = block
        elif block.kind == "DISPI":
            imaginary[block.value] = block
    damping = _damping(spec, workdir)

    # **측정점은 그 자리의 곡선을 만든다.** 전체 최대의 곡선과 봉우리 주파수가 다를 수 있고
    # (최대가 나는 자리가 주파수마다 옮겨 다닌다), 센서는 한 자리에 붙어 있다 — 실측과 견줄
    # 수 있는 것은 그쪽이다.
    spots = probes.spots(workdir)
    # **기저 가진**(가속도 하중) — 측정점의 절대 가속도를 셈한다(`excitation`).
    shaken = excitation.read(boundary.read(workdir))
    points: list[dict[str, Any]] = []
    for value in sorted(real):
        other = imaginary.get(value)
        if other is None:
            # 짝이 없는 블록은 **버린다** — 실수부만으로 진폭을 지어내면 공진이 평평해진다.
            continue
        extra = staged.corrections(value) if staged is not None else []
        row: dict[str, Any] = {
            "frequency_hz": round(value, 4),
            "max_displacement": significant(_amplitude(real[value], other, extra)),
        }
        if spots:
            row["probes"] = {
                spot.name: significant(_at_node(real[value], other, spot.node, extra))
                for spot in spots
            }
            # 측정점의 **가속도(g) · 위상(도)** — 가속도계와 견줄 값. 기저 가진이면 절대
            # 가속도.
            accel: dict[str, float] = {}
            phase: dict[str, float] = {}
            for spot in spots:
                re_part, im_part = _corrected(real[value], other, spot.node, extra)
                got = excitation.response(value, re_part, im_part, shaken)
                if got is not None:
                    accel[spot.name] = significant(got[0])
                    phase[spot.name] = round(got[1], 1)
            if accel:
                row["probes_accel_g"] = accel
                row["probes_phase_deg"] = phase
        points.append(row)
    if not points:
        raise StageFailure(
            "solver_failed",
            f"{FRD_NAME} 에 주파수 점이 없습니다 — 솔버 로그를 보세요.",
        )

    worst = max(points, key=lambda one: one["max_displacement"])
    result: dict[str, Any] = {
        "recipe": "harmonic",
        "solver": "calculix",
        # 덱을 mm · tonne · N 으로 쓴다(`calculix/deck.py`).
        "units": {"frequency": "Hz", "displacement": "mm", "system": "ConsistentNMM"},
        "damping_ratio": damping,
        "points": points,
        "peak": worst,
        "material": boundary.used_material(workdir, spec),
        **({"mesh": _mesh(workdir)} if _mesh(workdir) else {}),
        # 측정점 가속도의 기준 — 기저 가진이면 상대 변위에 기저 가속도를 더한 **절대** 값이다.
        "acceleration": "absolute",
        **({"base_excitation": True} if shaken else {}),
    }
    if staged is not None:
        # 빠진 높은 모드의 정적 몫을 더했다 — 못 더했으면(옛 덱) 이 칸이 없다.
        result["residual"] = True
        stress = staged.peak_stress(float(worst["frequency_hz"]), damping, workdir)
        if stress is not None:
            result["stress"] = stress
    # **측정점마다 그 자리의 봉우리 한 줄** — 절점 거리와 「멀다」 경고가 여기 실린다.
    tops = core_probes.peaks(spots, points, unit="mm")
    if tops:
        result["probes"] = tops
    if worst["max_displacement"] > SUSPICIOUS_DISPLACEMENT:
        result["warning"] = (
            f"공진 응답이 {worst['max_displacement']:.3g} 로 큽니다 — "
            f"감쇠비({damping})가 실제보다 작지 않은지 보세요."
        )

    path = workdir / RESULT_NAME
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return StageResult(
        artifacts=[ArtifactSpec("result_json", path)],
        summary={
            "solver": "calculix",
            "frequency_points": len(points),
            "peak_hz": worst["frequency_hz"],
            "peak_displacement": worst["max_displacement"],
            **(
                {"peak_von_mises": result["stress"]["max_von_mises_mpa"]}
                if "stress" in result
                else {}
            ),
            "damping_ratio": damping,
        },
        detail=(
            f"{len(points)}점 · 최대 {worst['max_displacement']:.4g} mm @ "
            f"{worst['frequency_hz']:.1f} Hz"
        ),
    )


#: 블록의 단계 번호 — 고유치(모드 형상 · 응력) · 주파수 훑기. 하중 l 의 정적은 3 + 2l, 0 Hz 는
#: 4 + 2l.
MODE_STAGE = 1
SWEEP_STAGE = 2

#: 잔여 벡터 하나 — (절점 → 변위 세 성분, 그 주파수의 복소 배율 k(f)·e^{iφ}).
Correction = tuple[dict[int, list[float]], complex]


class Staged:
    """단계로 가른 조화 응답 덱의 재료 — 모드 · 하중마다 모드 계수 · 잔여 벡터(변위 · 응력)."""

    def __init__(
        self,
        naturals: list[float],
        shapes: list[dict[int, list[float]]],
        stresses: list[dict[int, list[float]]],
        loads: list[dict[str, Any]],
    ) -> None:
        self.naturals = naturals
        self.shapes = shapes
        self.stresses = stresses
        self.loads = loads

    def factor(self, load: dict[str, Any], hz: float) -> complex:
        """그 하중의 복소 배율 k(f)·e^{iφ}(배율 표는 선형 보간 — 덱의 `*AMPLITUDE` 와 같다)."""
        table = tuple(tuple(one) for one in load.get("table") or ())
        scale = condition_model.table_factor(table or None, hz)
        angle = math.radians(float(load.get("phase_deg") or 0.0))
        return complex(scale * math.cos(angle), scale * math.sin(angle))

    def corrections(self, hz: float) -> list[Correction]:
        return [(one["residual"], self.factor(one, hz)) for one in self.loads]

    def peak_stress(self, hz: float, damping: float, workdir: Path) -> dict[str, Any] | None:
        """**봉우리 주파수의 최대 상당응력**(MPa) — 모드 응력 x 모드 좌표 + 잔여 응력, 위상을
        돌린 최대. 모드 응력이 없으면 None."""
        if not self.stresses or len(self.stresses) != len(self.naturals):
            return None
        gains = [superposition.dynamic_gain(natural, hz, damping) for natural in self.naturals]
        modal = [0j] * len(self.naturals)
        extra: list[tuple[dict[int, list[float]], complex]] = []
        for load in self.loads:
            factor = self.factor(load, hz)
            for m, coefficient in enumerate(load["coefficients"]):
                modal[m] += coefficient * gains[m] * factor
            if load.get("stress_residual"):
                extra.append((load["stress_residual"], factor))
        best = (-1.0, 0)
        for node in self.stresses[0]:
            re = [0.0] * superposition.STRESS_COMPONENTS
            im = [0.0] * superposition.STRESS_COMPONENTS
            for m, q in enumerate(modal):
                if not q:
                    continue
                values = self.stresses[m].get(node)
                if values is None:
                    continue
                for c in range(superposition.STRESS_COMPONENTS):
                    re[c] += values[c] * q.real
                    im[c] += values[c] * q.imag
            for field, factor in extra:
                values = field.get(node)
                if values is None:
                    continue
                for c in range(superposition.STRESS_COMPONENTS):
                    re[c] += values[c] * factor.real
                    im[c] += values[c] * factor.imag
            size = superposition.peak_von_mises(re, im)
            if size > best[0]:
                best = (size, node)
        if best[0] < 0:
            return None
        out: dict[str, Any] = {
            "frequency_hz": round(hz, 4),
            "max_von_mises_mpa": significant(best[0]),
            "node": best[1],
        }
        point = _point_of(workdir, best[1])
        if point is not None:
            out["point"] = point
        return out


def _staged(blocks: list[frd_reader.Block], saved: dict[str, Any]) -> Staged | None:
    """단계로 가른 덱이면 그 재료 — 아니면(옛 덱 · 단계 번호를 못 읽음) None."""
    rows = saved.get("harmonic_residual") if isinstance(saved, dict) else None
    if not isinstance(rows, list) or not rows or not any(one.stage for one in blocks):
        return None
    modes = [one for one in blocks if one.stage == MODE_STAGE and one.kind == "DISP"]
    stresses = [one for one in blocks if one.stage == MODE_STAGE and one.kind == "STRESS"]
    if not modes:
        return None
    shapes = [one.values for one in modes]
    loads: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        static_stage, zero_stage = 3 + 2 * index, 4 + 2 * index
        static = next(
            (one for one in blocks if one.stage == static_stage and one.kind == "DISP"), None
        )
        zero = next(
            (one for one in blocks if one.stage == zero_stage and one.kind == "DISP"), None
        )
        if static is None or zero is None:
            logger.warning("잔여 벡터 단계 %s 를 못 찾았습니다 — 잔여 없이 갑니다", index + 1)
            return None
        coefficients = superposition.modal_coefficients(shapes, zero.values)
        residual = _minus_modes(static.values, shapes, coefficients, 3)
        stress_block = next(
            (one for one in blocks if one.stage == static_stage and one.kind == "STRESS"), None
        )
        stress_residual = (
            _minus_modes(
                stress_block.values,
                [one.values for one in stresses],
                coefficients,
                superposition.STRESS_COMPONENTS,
            )
            if stress_block is not None and len(stresses) == len(modes)
            else None
        )
        loads.append(
            {
                **row,
                "coefficients": coefficients,
                "residual": residual,
                "stress_residual": stress_residual,
            }
        )
    return Staged(
        naturals=[one.value for one in modes],
        shapes=shapes,
        stresses=[one.values for one in stresses],
        loads=loads,
    )


def _minus_modes(
    whole: dict[int, list[float]],
    shapes: list[dict[int, list[float]]],
    coefficients: list[float],
    width: int,
) -> dict[int, list[float]]:
    """whole - Σₘ cₘ·shapeₘ — 절점마다 앞 `width` 성분."""
    out: dict[int, list[float]] = {}
    used = [(m, c) for m, c in enumerate(coefficients) if c]
    for node, values in whole.items():
        left = list(values[:width])
        if len(left) < width:
            continue
        for m, c in used:
            mode = shapes[m].get(node)
            if mode is None or len(mode) < width:
                continue
            for axis in range(width):
                left[axis] -= c * mode[axis]
        out[node] = left
    return out


def _point_of(workdir: Path, node: int) -> list[float] | None:
    """절점의 자리(mm) — `.msh` 에서. 못 읽으면 None."""
    from app.core.calculix.mesh import read_mesh

    msh = workdir / MSH_NAME
    if not msh.is_file():
        return None
    try:
        where = read_mesh(msh, require_solid=False).nodes.get(node)
    except Exception:  # pragma: no cover - 메시가 깨진 경우
        logger.warning("자리를 못 읽었습니다", exc_info=True)
        return None
    return [round(one, 6) for one in where] if where is not None else None


def _corrected(
    real: frd_reader.Block,
    imaginary: frd_reader.Block,
    node: int,
    extra: list[Correction],
) -> tuple[list[float], list[float]]:
    """그 절점의 (실수부, 허수부) 세 성분 — 잔여 벡터를 더한 것."""
    re = list((real.values.get(node) or [0.0, 0.0, 0.0])[:3])
    im = list((imaginary.values.get(node) or [0.0, 0.0, 0.0])[:3])
    for field, factor in extra:
        values = field.get(node)
        if values is None:
            continue
        for axis in range(3):
            re[axis] += values[axis] * factor.real
            im[axis] += values[axis] * factor.imag
    return re, im


def _at_node(
    real: frd_reader.Block,
    imaginary: frd_reader.Block,
    node: int,
    extra: list[Correction] | None = None,
) -> float:
    """그 절점의 진폭 — 실수부 · 허수부를 성분마다 합쳐 크기를 낸다(잔여 벡터를 더해)."""
    values = real.values.get(node)
    other = imaginary.values.get(node)
    if values is None or other is None or len(values) < 3 or len(other) < 3:
        return 0.0
    re, im = _corrected(real, imaginary, node, extra or [])
    return math.sqrt(sum(re[axis] ** 2 + im[axis] ** 2 for axis in range(3)))


def _amplitude(
    real: frd_reader.Block, imaginary: frd_reader.Block, extra: list[Correction] | None = None
) -> float:
    """그 주파수의 **최대 진폭** — 절점마다 복소 크기를 내고 가장 큰 것(잔여 벡터를 더해)."""
    best = 0.0
    for node, values in real.values.items():
        other = imaginary.values.get(node)
        if other is None or len(values) < 3 or len(other) < 3:
            continue
        if extra:
            re, im = _corrected(real, imaginary, node, extra)
            size = math.sqrt(sum(re[axis] ** 2 + im[axis] ** 2 for axis in range(3)))
        else:
            size = math.sqrt(sum(values[axis] ** 2 + other[axis] ** 2 for axis in range(3)))
        best = max(best, size)
    return best


def _damping(spec: HarmonicSpec, workdir: Path) -> float:
    """**실제로 덱에 실린 감쇠비.** 모델링이 남긴 파일이 정본이고, 없으면 스펙으로 본다."""
    path = workdir / BOUNDARY_NAME
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            value = loaded.get("damping_ratio")
            if isinstance(value, int | float):
                return float(value)
        except (OSError, ValueError):
            logger.warning("%s 를 읽지 못했습니다 — 스펙으로 봅니다", BOUNDARY_NAME)
    return spec.damping_ratio


def _mesh(workdir: Path) -> dict[str, int]:
    """메시 크기 — `.msh` 의 머리에서 센다. 없으면 비워 둔다(지어내지 않는다)."""
    import re

    msh = workdir / MSH_NAME
    if not msh.is_file():
        return {}
    text = msh.read_text(encoding="utf-8", errors="replace")
    found: dict[str, int] = {}
    nodes = re.search(r"\$Nodes\s*\n\s*(\d+)", text)
    elements = re.search(r"\$Elements\s*\n\s*(\d+)", text)
    if nodes:
        found["nodes"] = int(nodes.group(1))
    if elements:
        found["elements"] = int(elements.group(1))
    return found
