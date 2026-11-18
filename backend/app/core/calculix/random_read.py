"""랜덤 진동 결과 — 모드(`.dat` · `.frd`)와 PSD 로 **응답 1σ** 를 셈한다(`random_vibration`).

솔버는 모달만 푼다(덱은 모달 덱 그대로). 여기서

- 측정점마다 **절대 가속도 1σ(Grms)** · 축 성분 · **응답 PSD 곡선** · 1σ 변위(지지부 기준),
- 모든 절점의 **1σ 변위**(그림 `mode_01.vtp` — 크기만, 모양은 휘지 않는다) · 최대 자리,
- 가진마다 입력 Grms(표를 닫힌 꼴로 적분 — CompCore 손셈 6.058 g 과 같다),
- 모드마다 가진 방향 참여 · 유효질량 몫, 모드들이 덮은 가진 방향 질량,

을 낸다. 1σ 는 68.3 % 의 시간 그 아래에 있다는 뜻이다(3σ 는 세 배 — 99.7 %).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.core import boundary
from app.core import probes as core_probes
from app.core import random_vibration as random_model
from app.core.calculix import frd as frd_reader
from app.core.calculix import probes, tables, vtp
from app.core.calculix.mesh import Mesh, read_mesh
from app.core.modes import rigid as rigid_modes
from app.core.modes import search as mode_search
from app.core.numbers import significant
from app.core.spec import RandomSpec
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

RESULT_NAME = "result.json"
DATA_NAME = "model.dat"
FRD_NAME = "model.frd"
MSH_NAME = "model.msh"
SHAPE_NAME = "mode_01.vtp"
#: 입력 Grms 가 CompCore 의 셈과 이만큼 넘게 다르면 적는다(같은 표를 다르게 읽은 것이다).
GRMS_TOLERANCE = 0.01


def extract(spec: RandomSpec, workdir: Path, **_ignored: object) -> StageResult:
    """`model.dat` · `model.frd` → `result.json`(+ 1σ 변위 그림)."""
    data = workdir / DATA_NAME
    if not data.is_file():
        raise StageFailure("solver_failed", f"결과 파일이 없습니다: {DATA_NAME}")
    report = data.read_text(encoding="utf-8", errors="replace")
    naturals = tables.frequencies(report)
    if not naturals:
        raise StageFailure(
            "solver_failed",
            f"{DATA_NAME} 에서 고유진동수를 못 읽었습니다 — 솔버 로그를 보세요.",
        )
    factors = tables.participation_factors(report)
    if not factors:
        raise StageFailure(
            "solver_failed",
            f"{DATA_NAME} 에 참여계수 표가 없습니다 — 모드 중첩으로 응답을 셈할 수 없습니다.",
        )
    shaking = random_model.read(boundary.read(workdir))
    if shaking is None:
        raise StageFailure(
            "internal",
            "boundary.json 에 랜덤 진동 설정(가진 · 범위 · 감쇠비)이 없습니다 — 모델링을 다시"
            " 돌리세요.",
        )
    mesh, shapes, statics = _mode_shapes(workdir, len(naturals), shaking.residual_steps)
    mode_stresses, static_stresses = _mode_stresses(
        workdir, len(naturals), shaking.residual_steps
    )
    # **찾을 범위**(모달과 같다) — 범위 안의 모드만 `modes` 개까지 중첩에 쓴다. 솔브가 범위를
    # 채우려 더 풀었을 수 있으니 차례(`number`)로 고른다 — 표 · 형상은 전체 차례 그대로다.
    searched = mode_search.read(workdir / boundary.BOUNDARY_NAME)
    solved = list(naturals)
    numbers = list(range(1, len(naturals) + 1))
    if searched is not None:
        picked, _ = mode_search.kept(
            [
                {
                    "number": at,
                    "frequency_hz": hz,
                    "rigid_body": rigid_modes.is_rigid(hz),
                }
                for at, hz in enumerate(solved, start=1)
            ],
            searched,
        )
        numbers = [int(one["number"]) for one in picked]
        if not numbers:
            raise StageFailure(
                "solver_failed",
                f"찾을 범위 {searched.label} 안에 모드가 없습니다 — 중첩할 모드가 없어 응답을"
                " 셈할 수 없습니다. 범위를 넓히거나 비우세요.",
            )
        naturals = [naturals[at - 1] for at in numbers]
        shapes = [shapes[at - 1] for at in numbers]
        if mode_stresses:
            mode_stresses = [mode_stresses[at - 1] for at in numbers]
        factors = {
            order: factors[at] for order, at in enumerate(numbers, start=1) if at in factors
        }

    damping = shaking.damping_ratio
    modes = random_model.gather(naturals, factors, shaking.shakes)
    # **잔여 벡터** — 모드가 빠뜨린 정적 몫을 가진마다 「모드」 하나로 더한다. 모드 표 · 「가장
    # 높은 모드」 는 진짜 모드만 본다.
    real_modes = modes
    used: list[Mapping[int, Sequence[float]]] = list(shapes)
    if statics:
        modes, used = random_model.with_residual(modes, shapes, statics, shaking.shakes)
    breaks = sorted({hz for shake in shaking.shakes for hz, _ in shake.table})
    freqs = random_model.grid(shaking.low, shaking.high, naturals, damping, breaks)

    warnings: list[str] = []
    rigid = [hz for hz in naturals if rigid_modes.is_rigid(hz)]
    if rigid:
        warnings.append(
            f"0 Hz 모드가 {len(rigid)}개 있습니다 — 지지에 안 붙은 바디 · 열어 둔 방향이"
            " 흔들려 응답이 크게 나옵니다. 모달로 먼저 보세요."
        )

    inputs = []
    for shake in shaking.shakes:
        ours = random_model.grms(shake.table)
        line: dict[str, Any] = {
            "name": shake.name,
            "direction": [round(one, 6) for one in shake.direction],
            "grms": significant(ours),
            "table": [list(one) for one in shake.table],
        }
        if shake.declared_grms is not None:
            line["declared_grms"] = significant(shake.declared_grms)
            if shake.declared_grms > 0 and (
                abs(ours - shake.declared_grms) > GRMS_TOLERANCE * shake.declared_grms
            ):
                warnings.append(
                    f"가진 「{shake.name}」 의 입력 Grms 가 CAD 의 셈"
                    f"({shake.declared_grms:.4g} g)과 다릅니다({ours:.4g} g) — 표를 다르게"
                    " 읽었는지 보세요."
                )
        inputs.append(line)

    if naturals[-1] < random_model.MODE_REACH * shaking.high:
        # 대역 위쪽 모드도 정적 몫을 보탠다 — 위끝의 1.5배까지 풀어야 응답이 맞는다(Ansys 가
        # 권하는 기준). 유효질량 몫은 기준으로 쓰지 않는다: 고정된 바디의 질량이 분모에 들어
        # 받침판이 무거운 모델(조건_랜덤진동 96 %)에서 늘 모자라 보인다.
        capped = (
            searched is not None and searched.high < random_model.MODE_REACH * shaking.high
        )
        warnings.append(
            f"중첩한 가장 높은 모드가 {naturals[-1]:,.0f} Hz 입니다 — 가진 대역 위끝"
            f"({shaking.high:,.0f} Hz)의 {random_model.MODE_REACH:g}배 넘게 풀어야 응답이"
            " 맞습니다. "
            + (
                f"찾을 범위({searched.label})의 상한을 올리세요."
                if capped and searched is not None
                else "모드 수를 늘리세요."
            )
        )
    if searched is not None:
        said = mode_search.note(searched, len(numbers), solved)
        if said:
            warnings.append(said)
        # 범위 아래 모드를 뺐다 — 대역 안의 모드라면 응답이 그만큼 빠진다(사람이 고른 것이다).
        dropped = [
            hz
            for hz in solved
            if shaking.low <= hz < searched.low and not rigid_modes.is_rigid(hz)
        ]
        if dropped:
            warnings.append(
                f"찾을 범위({searched.label}) 아래의 모드 {len(dropped)}개"
                f"({dropped[0]:,.0f} Hz …)가 가진 대역 안인데 중첩에서 빠졌습니다 — 그 모드의"
                " 응답은 결과에 없습니다."
            )

    # **측정점** — 가속도계와 견줄 값(절대 가속도 1σ)과 응답 PSD 곡선.
    spots = probes.spots(workdir)
    probe_rows: list[dict[str, Any]] = []
    curves: dict[str, Any] = {
        "frequency_hz": [significant(hz) for hz in freqs],
        "input_psd": {
            shake.name: [significant(random_model.psd_at(shake.table, hz)) for hz in freqs]
            for shake in shaking.shakes
        },
    }
    responses: dict[str, list[float]] = {}
    for spot in spots:
        phis = [list(one.get(spot.node) or [0.0, 0.0, 0.0])[:3] for one in used]
        got = random_model.at_point(phis, modes, shaking.shakes, freqs, damping)
        top = max(range(len(freqs)), key=lambda at: got.psd[at]) if freqs else 0
        row = core_probes.row(
            name=spot.name,
            point=spot.point,
            node=spot.node,
            distance_mm=spot.distance_mm,
            value=got.accel_grms,
            unit="g",
            vector=list(got.accel_axes),
        )
        row["displacement_1sigma_mm"] = significant(got.displacement_mm)
        row["psd_peak_hz"] = round(freqs[top], 4) if freqs else None
        row["psd_peak"] = significant(got.psd[top]) if freqs else None
        probe_rows.append(row)
        responses[spot.name] = [significant(one) for one in got.psd]
    if responses:
        curves["probes"] = responses

    # **모든 절점의 1σ 변위** — 모드 결합 행렬로(절점마다 K² 번).
    matrix = random_model.couplings(modes, shaking.shakes, freqs, damping)
    ids = [node for node in mesh.nodes if node in shapes[0]]
    sigma = random_model.field(used, matrix, ids)
    worst = max(sigma, key=lambda node: sigma[node]) if sigma else None
    # **상당응력 1σ**(Segalman) — 모드 응력 + 잔여 응력을 같은 결합 행렬로(2026-11-18).
    stress_row: dict[str, Any] | None = None
    if mode_stresses and len(mode_stresses) == len(real_modes.naturals):
        stress_shapes: list[Mapping[int, Sequence[float]]] = list(mode_stresses)
        if statics and len(static_stresses) == len(statics):
            stress_shapes += random_model.residual_fields(
                real_modes, mode_stresses, static_stresses, shaking.shakes, 6
            )
        if len(stress_shapes) == len(modes.naturals):
            peak_mpa, node = random_model.stress_sigma(stress_shapes, matrix)
            if node is not None:
                stress_row = {
                    "max_von_mises_mpa": significant(peak_mpa),
                    "node": node,
                    "point": [round(one, 6) for one in mesh.nodes[node]]
                    if node in mesh.nodes
                    else None,
                    "method": "segalman",
                }

    result: dict[str, Any] = {
        "recipe": "random",
        "solver": "calculix",
        "units": {
            "frequency": "Hz",
            "displacement": "mm",
            "acceleration": "g",
            "psd": "g^2/Hz",
            "system": "ConsistentNMM",
        },
        # 1σ(표준 편차 = 실효값, 평균 0). 3σ 는 세 배.
        "sigma": 1,
        "damping_ratio": damping,
        # **가진 대역** — PSD 표가 덮는 범위(적분 범위).
        "band_hz": [shaking.low, shaking.high],
        # 찾을 범위(모달과 같은 열쇠) — 있을 때만.
        **(
            {
                "frequency_range_hz": [searched.low, searched.high],
                "range_from": searched.source,
            }
            if searched is not None
            else {}
        ),
        "inputs": inputs,
        "modes": _mode_rows(naturals, numbers, real_modes, report, shaking),
        # 빠진 모드의 정적 몫(잔여 벡터)을 더했나 — 못 더했으면 모드 수에 따라 응답이 출렁인다.
        "residual": bool(statics),
        # 측정점 가속도의 기준 — 지지부의 가속도를 더한 **절대** 값(가속도계가 재는 것).
        "acceleration": "absolute",
        "displacement": "relative",
        "frequency_points": len(freqs),
        "curves": curves,
        "material": boundary.used_material(workdir, spec),
    }
    size = _mesh_size(workdir)
    if size:
        result["mesh"] = size
    if worst is not None:
        result["max_displacement"] = {
            "value_mm": significant(sigma[worst]),
            "node": worst,
            "point": [round(one, 6) for one in mesh.nodes[worst]],
        }
    if stress_row is not None:
        result["stress"] = stress_row
    if probe_rows:
        result["probes"] = probe_rows
    if warnings:
        result["warning"] = " ".join(warnings)
    drawn = _draw(workdir, mesh, sigma, result)

    path = workdir / RESULT_NAME
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    first = probe_rows[0] if probe_rows else None
    largest = result.get("max_displacement", {}).get("value_mm")
    return StageResult(
        artifacts=[
            ArtifactSpec("result_json", path),
            *([ArtifactSpec("mode_vtp", workdir / SHAPE_NAME)] if drawn else []),
        ],
        summary={
            "solver": "calculix",
            "modes": len(naturals),
            "frequency_points": len(freqs),
            "input_grms": " · ".join(f"{one['name']} {one['grms']:.4g}" for one in inputs),
            **({"max_displacement_1sigma_mm": largest} if largest is not None else {}),
            **(
                {"max_von_mises_1sigma_mpa": stress_row["max_von_mises_mpa"]}
                if stress_row is not None
                else {}
            ),
            **(
                {"probe_grms": f"{first['name']} {first['value']:.4g} g"}
                if first is not None
                else {}
            ),
            **({"result_warning": result["warning"]} if warnings else {}),
        },
        detail=(
            f"모드 {len(naturals)}개 · 1σ 변위 최대 {largest:.4g} mm"
            if largest is not None
            else f"모드 {len(naturals)}개"
        )
        + (f" · {first['name']} {first['value']:.4g} Grms" if first is not None else ""),
    )


def _mode_shapes(
    workdir: Path, count: int, statics: int = 0
) -> tuple[Mesh, list[dict[int, list[float]]], list[dict[int, list[float]]]]:
    """메시 · 모드마다의 변위(질량 정규화) · 잔여 벡터의 1 g 정적 변위(가진마다). **응답의
    재료라 없으면 실패다**(모달과 다르다).

    블록 차례는 [선응력의 앞 정적 단계] · 모드 `count` 개 · 1 g 정적 `statics` 개다 — 모드는
    **뒤에서부터** 센다."""
    result = workdir / FRD_NAME
    msh = workdir / MSH_NAME
    if not result.is_file() or not msh.is_file():
        raise StageFailure("solver_failed", f"모드 형상 파일이 없습니다: {FRD_NAME}")
    mesh = read_mesh(msh, require_solid=False)
    blocks = [one for one in frd_reader.read_folded(workdir, result) if one.kind == "DISP"]
    if len(blocks) < count + statics:
        raise StageFailure(
            "solver_failed",
            f"{FRD_NAME} 의 변위 블록이 {len(blocks)}개뿐입니다(고유진동수 {count}개 · 정적"
            f" {statics}개).",
        )
    end = len(blocks) - statics
    return (
        mesh,
        [one.values for one in blocks[end - count : end]],
        [one.values for one in blocks[end:]],
    )


def _mode_stresses(
    workdir: Path, count: int, statics: int = 0
) -> tuple[list[dict[int, list[float]]], list[dict[int, list[float]]]]:
    """모드마다의 응력(성분 여섯) · 잔여 벡터의 1 g 정적 응력 — 변위와 같은 차례(뒤에서부터).
    덱이 응력을 안 적었으면(옛 덱) 둘 다 빈 것."""
    blocks = [
        one
        for one in frd_reader.read_folded(workdir, workdir / FRD_NAME)
        if one.kind == "STRESS"
    ]
    if len(blocks) < count + statics:
        return [], []
    end = len(blocks) - statics
    return [one.values for one in blocks[end - count : end]], [
        one.values for one in blocks[end:]
    ]


def _mode_rows(
    naturals: list[float],
    numbers: list[int],
    modes: random_model.Modes,
    report: str,
    shaking: random_model.RandomPlan,
) -> list[dict[str, Any]]:
    """모드마다 주파수 · 가진마다 참여 Γ · 유효질량 몫(Γ² / 전체 질량). `number` 는 푼 차례다
    (찾을 범위가 있으면 1 부터가 아니다)."""
    totals = tables.total_masses(report)
    mass = totals[0] if totals and totals[0] > 0 else None
    rows = []
    for at, hz in enumerate(naturals):
        row: dict[str, Any] = {
            "number": numbers[at],
            "frequency_hz": round(hz, 4),
            "participation": {
                shake.name: significant(modes.participation[shake.name][at])
                for shake in shaking.shakes
            },
        }
        if mass is not None:
            row["mass_share"] = {
                shake.name: round(modes.participation[shake.name][at] ** 2 / mass, 4)
                for shake in shaking.shakes
            }
        rows.append(row)
    return rows


def _draw(workdir: Path, mesh: Mesh, sigma: dict[int, float], result: dict[str, Any]) -> bool:
    """1σ 변위 그림 한 장 — **크기만 싣고 변위 벡터는 0**: 1σ 는 방향이 없는 통계값이라 그
    모양으로 휘면 그림이 거짓말을 한다. 못 그려도 해석은 끝난 것이다."""
    if not sigma:
        return False
    try:
        try:
            triangles, parts, names = vtp.parted(mesh, workdir)
        except Exception:  # pragma: no cover - 나누기만 못 한다
            logger.warning("그림을 파트로 못 나눴습니다 — 나누지 않고 그립니다", exc_info=True)
            triangles, parts, names = list(mesh.triangles), None, []
        counts = vtp.write(
            workdir / SHAPE_NAME,
            nodes=mesh.nodes,
            triangles=triangles,
            displacement={},
            magnitude=sigma,
            parts=parts,
        )
    except Exception:  # pragma: no cover - 파일이 깨진 경우
        logger.warning("1σ 그림을 못 만들었습니다 — 그림 없이 갑니다", exc_info=True)
        return False
    result["shape"] = {"vtp": SHAPE_NAME, "points": counts["points"], "field": "1σ 변위"}
    if names:
        result["parts"] = names
    return True


def _mesh_size(workdir: Path) -> dict[str, int]:
    """메시 크기 — `.msh` 의 머리에서 센다. 없으면 비워 둔다."""
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
