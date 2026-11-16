"""조화 응답의 **가진(기저 가속도)과 그것으로 셈하는 응답** — 두 솔버 공통(2026-11-17).

CompCore 의 가진 프로파일(사인 스윕): 고정 지지 + 가속도 하중이 **기저 가진**이다. 덱은 그것을
관성력
(-M·a)으로 받으므로 솔버가 내는 변위는 **지지부 기준 상대**
변위다(`calculix/deck._inertia_rows`).
가속도계는 절대 가속도를 잰다 — 그래서 측정점의 가속도는

    절대 가속도 = -ω²·u(상대, 복소) + Σ 기저 가속도(그 주파수의 배율 · 위상, 방향)

로 낸다. 기저 가진이 없으면(힘 · 압력으로 흔든다) 변위가 곧 절대라 -ω²·u 다. 위상은 측정점의
가장 크게 움직이는 축 성분의 것이다(도, 가진 기준).

실측 맞춤(2026-11-17, CompCore 손셈): `조건_사인스윕` 기둥 끝이 1,263 Hz 에서 상대 39.0 g(손셈
약
39 g, Q = 25).
"""

from __future__ import annotations

import cmath
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.core import conditions as condition_model

#: 표준 중력(mm/s²) — 결과의 g 는 이것으로 나눈다.
G_MM_S2 = 9806.65
#: 가속도 단위 → mm/s²(덱 · 결과의 계).
ACCELERATION_MM_S2 = {
    "mm/s^2": 1.0,
    "mm/s2": 1.0,
    "mm/s²": 1.0,
    "m/s^2": 1000.0,
    "m/s2": 1000.0,
    "m/s²": 1000.0,
    "g": G_MM_S2,
}
#: `boundary.json` 의 열쇠 — 모델링이 적고 추출이 읽는다.
KEY = "base_excitation"


@dataclass(frozen=True)
class Base:
    """기저 가속도 하나 — 전역 단위 방향, 크기(mm/s²), 주파수별 배율, 위상(도)."""

    direction: tuple[float, float, float]
    magnitude: float
    table: tuple[tuple[float, float], ...] | None = None
    phase: float = 0.0

    def at(self, hz: float) -> complex:
        """그 주파수의 복소 크기(mm/s²)."""
        size = self.magnitude * condition_model.table_factor(self.table, hz)
        return size * cmath.exp(1j * math.radians(self.phase))

    def as_boundary(self) -> dict[str, Any]:
        return {
            "direction": list(self.direction),
            "magnitude_mm_s2": self.magnitude,
            "table": [list(one) for one in self.table] if self.table else None,
            "phase": self.phase,
        }


def bases(given: condition_model.Conditions) -> list[Base]:
    """조건의 가속도 하중 → 기저 가속도들(못 읽는 것은 뺀다 — 덱이 그 까닭을 말한다)."""
    found: list[Base] = []
    for load in given.loads:
        if load.kind != "acceleration" or load.magnitude is None:
            continue
        moved = condition_model.in_global(load, given.frames)
        if isinstance(moved, str) or moved.direction is None or moved.magnitude is None:
            continue
        scale = ACCELERATION_MM_S2.get((moved.unit or "mm/s^2").replace(" ", "").lower())
        length = math.sqrt(sum(one * one for one in moved.direction))
        if scale is None or length == 0:
            continue
        found.append(
            Base(
                direction=(
                    moved.direction[0] / length,
                    moved.direction[1] / length,
                    moved.direction[2] / length,
                ),
                magnitude=moved.magnitude * scale,
                table=moved.frequency_table,
                phase=moved.phase or 0.0,
            )
        )
    return found


def read(payload: dict[str, Any]) -> list[Base]:
    """`boundary.json` 에 남긴 기저 가속도들."""
    rows = payload.get(KEY) if isinstance(payload, dict) else None
    found: list[Base] = []
    for row in rows if isinstance(rows, list) else []:
        try:
            table = row.get("table")
            found.append(
                Base(
                    direction=tuple(float(one) for one in row["direction"])[:3],  # type: ignore[arg-type]
                    magnitude=float(row["magnitude_mm_s2"]),
                    table=tuple((float(a), float(b)) for a, b in table) if table else None,
                    phase=float(row.get("phase") or 0.0),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return found


def response(
    hz: float, real: Sequence[float], imaginary: Sequence[float], given: Sequence[Base]
) -> tuple[float, float] | None:
    """측정점의 **가속도 크기(g)와 위상(도)** — 가장 크게 움직이는 축 성분의 위상(가진
    기준)."""
    if len(real) < 3 or len(imaginary) < 3:
        return None
    omega = 2 * math.pi * hz
    vector = [-(omega**2) * complex(real[axis], imaginary[axis]) for axis in range(3)]
    for base in given:
        moved = base.at(hz)
        for axis in range(3):
            vector[axis] += moved * base.direction[axis]
    size = math.sqrt(sum(abs(one) ** 2 for one in vector))
    axis = max(range(3), key=lambda at: abs(vector[at]))
    return size / G_MM_S2, math.degrees(cmath.phase(vector[axis])) if size else 0.0


def amplitude_g(hz: float, displacement_mm: float) -> float:
    """변위 진폭(mm)만 있을 때의 가속도 크기(g) — ω²·|u|. 기저 가진이 있으면 **상대** 가속도다
    (위상이 없어 기저를 더할 수 없다 — Ansys 경로)."""
    omega = 2 * math.pi * hz
    return omega**2 * displacement_mm / G_MM_S2
