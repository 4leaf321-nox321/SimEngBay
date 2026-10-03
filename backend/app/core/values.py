"""결과 파일에서 **견줄 값**을 꺼낸다 — 스터디 비교 · 메시 수렴 · 실측 맞추기가 같은 값을 본다.

`result.json` 이 정본이고, 레시피 · 솔버마다 칸과 단위가 조금씩 다르다: Ansys 는 DPF 가
읽은 계 그대로 적고(SI 로 돌면 m · Pa), CalculiX 는 늘 mm · MPa 다. 견주는 자리가 셋인데 셋이
저마다 단위를 맞추면 언젠가 하나가 안 맞고, **그때 1000배 차이가 숫자로만 보인다.** 그래서
여기서 한 번 **mm · MPa · N · Hz** 로 맞춘다.

**모르는 단위는 옮기지 않는다** — 값을 비워 둔다. 짐작해서 곱하면 그럴듯하게 틀린 수가 된다.
단위가 아예 적혀 있지 않으면 mm 로 본다(이 플랫폼의 계와 모의 실행기의 결과가 그렇다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 길이 단위 → mm 곱수.
_TO_MM: dict[str, float] = {
    "": 1.0,
    "mm": 1.0,
    "m": 1000.0,
    "meter": 1000.0,
    "metre": 1000.0,
    "cm": 10.0,
    "um": 1e-3,
    "µm": 1e-3,
    "μm": 1e-3,
}

#: 응력 단위 → MPa 곱수.
_TO_MPA: dict[str, float] = {
    "": 1.0,
    "mpa": 1.0,
    "n/mm^2": 1.0,
    "n/mm2": 1.0,
    "pa": 1e-6,
    "kpa": 1e-3,
    "gpa": 1e3,
}


def to_mm(unit: str | None) -> float | None:
    """길이 단위의 mm 곱수. 모르면 `None`."""
    return _TO_MM.get((unit or "").strip().lower())


def to_mpa(unit: str | None) -> float | None:
    """응력 단위의 MPa 곱수. 모르면 `None`."""
    return _TO_MPA.get((unit or "").strip().lower())


def _scaled(value: Any, scale: float | None) -> float | None:
    if scale is None or not isinstance(value, int | float):
        return None
    return float(value) * scale


@dataclass
class Values:
    """설계점 하나의 견줄 값 — **늘 mm · MPa · N · Hz.**"""

    recipe: str
    first_elastic_hz: float | None = None
    frequencies: list[float] = field(default_factory=list)
    """탄성 모드 주파수(앞에서부터, Hz)."""
    max_displacement_mm: float | None = None
    max_von_mises_mpa: float | None = None
    peak_hz: float | None = None
    peak_displacement_mm: float | None = None
    reactions_n: dict[str, list[float]] = field(default_factory=dict)
    """변위를 준 영역 → 반력 합 `[Fx, Fy, Fz]`(N)."""
    probes_mm: dict[str, float] = field(default_factory=dict)
    """측정점 → 값(mm). 정적은 변위 크기, 조화는 **그 자리 곡선의 봉우리** 진폭."""
    probe_vectors_mm: dict[str, list[float]] = field(default_factory=dict)
    """정적 — 측정점 → 변위 성분 `[ux, uy, uz]`(mm)."""
    probe_strains: dict[str, list[float]] = field(default_factory=dict)
    """정적 — 측정점 → 수직 변형률 `[εxx, εyy, εzz]`(무차원)."""
    probe_peaks_hz: dict[str, float] = field(default_factory=dict)
    """조화 — 측정점 → 그 자리 곡선의 봉우리 주파수(Hz)."""
    relative_mm: dict[str, list[float]] = field(default_factory=dict)
    """정적 — **같은 자리 · 다른 바디**의 두 측정점 `「A - B」` → 변위 차 `[dx, dy, dz]`(mm).
    전단 이음이면 이것이 미끄럼이다. 크기만 보면 두 판이 함께 밀린 것과 서로 미끄러진 것이
    구별되지 않는다."""
    nodes: int | None = None


def elastic_modes(result: dict[str, Any]) -> list[dict[str, Any]]:
    """강체를 뺀 모드들(앞에서부터)."""
    return [one for one in result.get("modes") or [] if not one.get("rigid_body")]


def read(result: dict[str, Any]) -> Values:
    """`result.json` 한 장 → 견줄 값. 없는 칸은 비워 둔다(0 으로 적지 않는다)."""
    recipe = str(result.get("recipe") or "modal")
    units = result.get("units") or {}
    made = Values(recipe=recipe)
    mesh = result.get("mesh") or {}
    if isinstance(mesh.get("nodes"), int):
        made.nodes = int(mesh["nodes"])

    if recipe == "modal":
        made.frequencies = [
            float(one["frequency_hz"])
            for one in elastic_modes(result)
            if isinstance(one.get("frequency_hz"), int | float)
        ]
        made.first_elastic_hz = made.frequencies[0] if made.frequencies else None
        return made

    length = to_mm(units.get("displacement"))
    if recipe == "static":
        made.max_displacement_mm = _scaled(result.get("max_displacement"), length)
        made.max_von_mises_mpa = _scaled(
            result.get("max_von_mises"), to_mpa(units.get("stress"))
        )
        for region, vector in (result.get("reactions") or {}).items():
            if isinstance(vector, list) and len(vector) == 3:
                made.reactions_n[str(region)] = [float(one) for one in vector]
        placed: list[tuple[str, list[float], str]] = []
        for row in result.get("probes") or []:
            scale = to_mm(row.get("unit"))
            value = _scaled(row.get("value"), scale)
            if value is None:
                continue
            name = str(row["name"])
            made.probes_mm[name] = value
            vector = row.get("vector")
            if isinstance(vector, list) and len(vector) == 3 and scale is not None:
                made.probe_vectors_mm[name] = [float(one) * scale for one in vector]
                point, body = row.get("point"), row.get("body")
                if isinstance(point, list) and len(point) == 3 and isinstance(body, str):
                    placed.append((name, [float(one) for one in point], body))
            strain = row.get("strain")
            if isinstance(strain, list) and len(strain) == 3:
                made.probe_strains[name] = [float(one) for one in strain]
        for index, (first, where, body) in enumerate(placed):
            for second, there, other in placed[index + 1 :]:
                if (
                    body == other
                    or max(abs(a - b) for a, b in zip(where, there, strict=True)) > 1e-6
                ):
                    continue
                made.relative_mm[f"{first} - {second}"] = [
                    a - b
                    for a, b in zip(
                        made.probe_vectors_mm[first],
                        made.probe_vectors_mm[second],
                        strict=True,
                    )
                ]
        return made

    if recipe == "harmonic":
        peak = result.get("peak") or {}
        if isinstance(peak.get("frequency_hz"), int | float):
            made.peak_hz = float(peak["frequency_hz"])
        made.peak_displacement_mm = _scaled(peak.get("max_displacement"), length)
        tops = {str(one["name"]): one for one in result.get("probes") or [] if "name" in one}
        names = list(tops) or sorted(
            {name for one in result.get("points") or [] for name in (one.get("probes") or {})}
        )
        for name in names:
            top = tops.get(name) or _curve_peak(result.get("points") or [], name)
            if top is None:
                continue
            value = _scaled(
                top.get("value"), to_mm(top.get("unit")) if "unit" in top else length
            )
            if value is not None:
                made.probes_mm[name] = value
            if isinstance(top.get("frequency_hz"), int | float):
                made.probe_peaks_hz[name] = float(top["frequency_hz"])
    return made


def _curve_peak(points: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """옛 조화 결과(측정점 봉우리 줄이 없다) — 곡선에서 직접 찾는다."""
    best: dict[str, Any] | None = None
    for one in points:
        value = (one.get("probes") or {}).get(name)
        if isinstance(value, int | float) and (best is None or value > best["value"]):
            best = {"value": float(value), "frequency_hz": one.get("frequency_hz")}
    return best
