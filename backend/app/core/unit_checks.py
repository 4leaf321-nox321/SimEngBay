"""**단위가 어긋났는가** — 두 솔버가 같은 말로 하는 세 점검(2026-11-17 CalculiX ·
2026-11-18 Ansys).

운영에서 1차 탄성이 1000배로 나왔고 질량이 mg 이었다. 고유진동수는 √(탄성계수 / 밀도) /
길이라 셋 중 하나가 10³ · 10⁶ 배 어긋나면 **오류 없이** 그럴듯하게 틀린다. 결과 요약에서
가린다:

- `deck_materials` — 덱에 쓴 탄성계수(GPa) · 밀도(kg/m³)와 그 바디(`material_line`).
- `solver_mass_kg` · `mass_warning` — 솔버가 덱으로 셈한 질량과 형상 부피 x 밀도(`mass_check`).
- `size_warning` — 형상을 읽어 잰 바디 부피와 CompCore `bodies[].volume`(`size_warning`).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

#: 형상 부피가 CAD 의 부피와 이만큼 넘게 다르면 적는다.
SIZE_TOLERANCE = 0.01
#: 솔버가 셈한 질량이 모델링 셈과 이만큼 넘게 다르면 적는다 — 하나는 형상 부피, 하나는 메시
#: 부피라 곡면에서 조금 갈린다. 단위가 어긋나면 10³ 배씩 갈린다.
MASS_TOLERANCE = 0.05


def size_warning(
    topology: Mapping[str, Any] | None,
    volumes_mm3: Mapping[str, float],
    *,
    total_mm3: float | None = None,
    skip: Iterable[str] = (),
) -> str | None:
    """**형상 크기가 CAD 와 다른가** — 바디 이름 → 형상을 읽어 잰 부피(mm³, 메시가 아니라
    형상이라 요소 크기와 상관없다)를 CompCore 의 `bodies[].volume`(mm³)과 견준다.

    STEP 의 길이 단위가 어긋나면 부피가 10⁻⁹ · 10⁹ 배로 갈린다 — 고유진동수는 오류 없이 10³
    배 틀린다. 1 % 넘게 다르면 적는다. 쉘 · 해석 제외(`skip`) · 잴 수 없는 바디는 뺀다. 바디별
    짝이 하나도 없으면(바디 하나 · 물성 하나면 짝짓기가 실패해도 푼다) `total_mm3` 로 전체를
    견준다."""
    rows = topology.get("bodies") if isinstance(topology, Mapping) else None
    left_out = set(skip)
    solids = [
        row
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, Mapping)
        and row.get("kind") != "sheet"
        and str(row.get("name") or "") not in left_out
        and isinstance(row.get("volume"), int | float)
        and row["volume"] > 0
    ]
    off: list[tuple[str, float, float, float]] = []
    compared = 0
    for row in solids:
        name = str(row.get("name") or "")
        if name not in volumes_mm3:
            continue
        compared += 1
        ours, cad = float(volumes_mm3[name]), float(row["volume"])
        if ours > 0 and abs(ours / cad - 1) > SIZE_TOLERANCE:
            off.append((name, ours / cad, ours, cad))
    if not compared and solids and total_mm3:
        cad = sum(float(row["volume"]) for row in solids)
        if abs(total_mm3 / cad - 1) > SIZE_TOLERANCE:
            off.append(("전체", total_mm3 / cad, float(total_mm3), cad))
    if not off:
        return None
    worst = max(off, key=lambda one: abs(math.log10(one[1])))
    shown = " · ".join(
        f"「{name}」 {ours:.6g} mm³(CAD {cad:.6g} mm³, {ratio:.3g} 배)"
        for name, ratio, ours, cad in off[:5]
    ) + (f" 외 {len(off) - 5}개" if len(off) > 5 else "")
    if abs(math.log10(worst[1])) >= 2:
        return (
            f"형상 크기가 CAD 와 다릅니다(길이 단위) — 부피가 CAD 의 {worst[1]:.3g} 배"
            f"(길이 {worst[1] ** (1 / 3):.3g} 배)입니다: {shown}. STEP 의 길이 단위를 "
            "보세요 — 고유진동수가 그만큼 틀립니다."
        )
    return (
        f"형상 크기가 CAD 와 다릅니다 — 바디 부피가 1 % 넘게 다릅니다: {shown}. 형상 맞춤 · "
        "겹침 정리로 바뀌었거나 다른 형상일 수 있습니다."
    )


def material_line(rows: Iterable[tuple[str, float, float]]) -> str | None:
    """**덱에 쓴 물성** 한 줄 — (바디, 탄성계수 GPa, 밀도 kg/m³). 값이 같은 바디는 묶는다.

    「E 205 GPa · 밀도 7,850 kg/m³ (받침판, 기둥)」 — Pa 값을 MPa 칸에 넣은 꼴이면
    「E 2.05e+08 GPa」 로 바로 보인다."""
    grouped: dict[tuple[float, float], list[str]] = {}
    for body, gpa, kg_m3 in rows:
        key = (float(f"{gpa:.4g}"), float(f"{kg_m3:.4g}"))
        grouped.setdefault(key, []).append(body)
    if not grouped:
        return None
    return " · ".join(
        f"E {gpa:g} GPa · 밀도 {kg_m3:,.4g} kg/m³ ({', '.join(dict.fromkeys(bodies))})"
        for (gpa, kg_m3), bodies in grouped.items()
    )


def mass_check(solver_kg: float | None, ours_kg: float | None) -> dict[str, object]:
    """요약 칸 `solver_mass_kg` 와, 형상 부피 x 밀도(`ours_kg`)와 5 % 넘게 다르면
    `mass_warning` — 덱의 밀도 · 단위가 어긋난 것이다."""
    if solver_kg is None or solver_kg <= 0:
        return {}
    out: dict[str, object] = {"solver_mass_kg": float(f"{solver_kg:.6g}")}
    if ours_kg is None or ours_kg <= 0:
        return out
    if abs(solver_kg / ours_kg - 1) > MASS_TOLERANCE:
        out["mass_warning"] = (
            f"솔버가 셈한 질량({solver_kg:.4g} kg)이 형상 부피 x 밀도({ours_kg:.4g} kg)와 "
            f"{solver_kg / ours_kg:.3g} 배 다릅니다 — 덱의 밀도 · 단위를 보세요(요약의 「덱 "
            "물성」)."
        )
    return out
