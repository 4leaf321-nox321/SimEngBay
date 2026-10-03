"""**실측과 맞추기** — 센서 자리의 실측값을 해석 결과와 **같은 자리에서** 견준다.

해석과 실측을 잇는 유일한 공통 좌표가 **측정점**이다 — CAD 가 점 그룹으로 보낸 자리, 곧
센서를 붙인 자리(`app/core/probes.py`). 그래서 실측 표의 열쇠도 측정점 이름이다. 장비마다
내보내는 열 이름이 다르므로 **장비 고유의 열을 가정하지 않는다** — 이 플랫폼의 표 하나로 받고,
장비 파일은 사람이 그 모양으로 옮긴다(양식을 내려받는다).

## 실측 표 한 장 — 종류 넷을 한 표에

| 열 | 다른 이름 | 무엇 |
| --- | --- | --- |
| 측정점 | probe · point · sensor · 센서 | CAD 점 그룹 이름. 공진은 비워도 된다 |
| 종류 | kind · type | 공진(frequency) · FRF · 변위(displacement) · 변형률(strain) |
| 주파수 | frequency · frequency_hz · freq · hz | Hz — 공진 · FRF |
| 값 | value · amplitude · 진폭 | FRF 진폭 · 변위 · 변형률(공진은 비운다) |
| 단위 | unit | 변위 m · mm · um, 속도 m/s · mm/s, 가속도 m/s2 · g, 변형률 비움 · ue |
| 성분 | component · direction · 방향 · axis | x · y · z · 크기(변형률은 x · y · z 만) |

FRF 의 단위가 `/N` 으로 끝나면(가진력으로 나눈 FRF) **봉우리 위치만** 견준다 — 해석의 가진력과
같은 힘으로 나눴는지 알 수 없어 높이를 견주면 거짓말이 된다.

## 짝을 억지로 짓지 않는다

실측 공진에는 모드 형상(지문)이 없다 — 설계점 사이처럼 MAC 으로 잇지 못한다. 그래서
① **센서 자리에서 거의 안 움직이는 모드는 후보에서 뺀다**(그 센서로는 안 보인다), ② 남은 것 중
가장 가까운 주파수를 **한 모드에 한 번만** 짓는다, ③ 가까운 후보가 둘이면 「짝이 불확실」 을
적는다. 창(±25%) 밖이면 짝을 짓지 않는다 — 억지로 이은 짝은 없는 짝보다 나쁘다.

## 차이를 변수로 설명한다

- **주파수가 모든 모드에서 같은 비율로 어긋나면** 강성/질량 비의 문제다: f ∝ √(E/밀도) 이므로
  영률을 E x (f실측/f해석)² 로 두면 맞는다. 모드마다 비율이 다르면 물성 하나로 설명되지 않는다
  (경계조건 · 접촉 · 형상을 본다) — 그때는 영률을 제안하지 않는다.
- **봉우리 높이는 감쇠가 정한다**(≈ 1/2ζ). 높이 비만큼 감쇠비를 고치면 맞는다. 실측 곡선에서
  반전력 대역(봉우리의 1/√2 폭)으로 감쇠비를 직접 잴 수도 있다.
- **힘으로 건 정적 모델**의 변위 · 변형률은 1/E 에 비례한다 — 같은 비율로 어긋나면 영률로
  설명된다. 변위로 당긴 모델(전단 이음)에는 해당하지 않는다.
"""

from __future__ import annotations

import math
import re
from typing import Any

from app.core.values import elastic_modes, to_mm

KINDS = ("frequency", "frf", "displacement", "strain")

#: 센서 자리에서 이보다 덜 움직이는 모드는 그 센서로는 안 보인다(그 자리 최대에 대한 비).
VISIBLE_SHARE = 0.05
#: 이 창 밖이면 짝을 짓지 않는다(상대 차이).
PAIR_WINDOW = 0.25
#: 이 안에 후보가 둘이면 「짝이 불확실」.
AMBIGUOUS_WINDOW = 0.10
#: 비율이 이만큼 안에서 같으면 「같은 비율로 어긋났다」 로 본다.
CONSISTENT_SPREAD = 0.03
#: 곡선을 화면에 실을 때 점 수 상한 — 실측 FRF 는 수천 점이다.
CURVE_POINTS = 400

_COLUMNS: dict[str, tuple[str, ...]] = {
    "probe": ("측정점", "probe", "point", "sensor", "센서", "위치"),
    "kind": ("종류", "kind", "type"),
    "frequency_hz": ("주파수", "frequency", "frequencyhz", "freq", "hz", "주파수hz"),
    "value": ("값", "value", "amplitude", "진폭"),
    "unit": ("단위", "unit", "units"),
    "component": ("성분", "component", "direction", "방향", "axis", "축"),
}

_KIND_NAMES: dict[str, str] = {
    "공진": "frequency",
    "공진주파수": "frequency",
    "고유진동수": "frequency",
    "frequency": "frequency",
    "resonance": "frequency",
    "frf": "frf",
    "주파수응답": "frf",
    "변위": "displacement",
    "displacement": "displacement",
    "변형률": "strain",
    "strain": "strain",
}

_COMPONENTS: dict[str, str] = {
    "x": "x",
    "y": "y",
    "z": "z",
    "크기": "magnitude",
    "magnitude": "magnitude",
    "mag": "magnitude",
    "total": "magnitude",
    "합": "magnitude",
}

#: 단위 → (물리량, 기준 단위로의 곱수). 기준은 mm · mm/s · mm/s² · 무차원.
_UNITS: dict[str, tuple[str, float]] = {
    "m": ("displacement", 1000.0),
    "mm": ("displacement", 1.0),
    "um": ("displacement", 1e-3),
    "µm": ("displacement", 1e-3),
    "μm": ("displacement", 1e-3),
    "m/s": ("velocity", 1000.0),
    "mm/s": ("velocity", 1.0),
    "m/s2": ("acceleration", 1000.0),
    "m/s^2": ("acceleration", 1000.0),
    "m/s²": ("acceleration", 1000.0),
    "mm/s2": ("acceleration", 1.0),
    "mm/s^2": ("acceleration", 1.0),
    "mm/s²": ("acceleration", 1.0),
    "g": ("acceleration", 9806.65),
}

_STRAIN_UNITS: dict[str, float] = {
    "": 1.0,
    "-": 1.0,
    "m/m": 1.0,
    "mm/mm": 1.0,
    "ue": 1e-6,
    "με": 1e-6,
    "µε": 1e-6,
    "microstrain": 1e-6,
    "ustrain": 1e-6,
}

#: 기준 단위의 이름 — 화면이 곡선 축에 적는다.
BASE_UNITS = {"displacement": "mm", "velocity": "mm/s", "acceleration": "mm/s²"}


def _key(text: str) -> str:
    return re.sub(r"[\s_()\[\]]", "", text.strip().lower())


def _column_map(header: list[str]) -> dict[str, str]:
    """표의 열 이름 → 우리 칸. 모르는 열은 무시한다(장비가 덧붙인 메모 같은 것)."""
    wanted = {_key(alias): name for name, aliases in _COLUMNS.items() for alias in aliases}
    return {column: wanted[_key(column)] for column in header if _key(column) in wanted}


def _number(text: Any) -> float | None:
    if isinstance(text, int | float):
        return float(text)
    cleaned = str(text or "").strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse(table: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """표 → 실측 줄들과 오류들. **오류가 하나라도 있으면 줄을 쓰지 않는다**(부르는 쪽이 거절).

    반쯤 들어간 실측은 그럴듯하게 틀린 비교를 낸다 — 몇 줄이 빠진 FRF 는 봉우리가 옮겨 간다.
    """
    if not table:
        return [], ["표가 비었습니다."]
    # 열은 **모든 줄의 열쇠를 합쳐** 정한다 — JSON 은 줄마다 칸이 다를 수 있다(빈 칸을 뺀다).
    columns = _column_map(list(dict.fromkeys(key for one in table for key in one)))
    missing = [name for name in ("kind",) if name not in columns.values()]
    if missing:
        return [], [
            "「종류」 열이 없습니다 — 양식의 열 이름(측정점 · 종류 · 주파수 · 값 · 단위 · "
            "성분)을 쓰세요."
        ]

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for line, raw in enumerate(table, start=2):  # 1 줄은 머리
        cell = {name: raw.get(column) for column, name in columns.items()}
        if not any(str(value or "").strip() for value in cell.values()):
            continue  # 빈 줄
        kind = _KIND_NAMES.get(_key(str(cell.get("kind") or "")))
        if kind is None:
            errors.append(
                f"{line}줄: 모르는 종류 「{cell.get('kind')}」 — 공진 · FRF · 변위 · 변형률"
            )
            continue
        probe = str(cell.get("probe") or "").strip() or None
        frequency = _number(cell.get("frequency_hz"))
        value = _number(cell.get("value"))
        unit = str(cell.get("unit") or "").strip()
        component_text = _key(str(cell.get("component") or ""))
        component = _COMPONENTS.get(component_text) if component_text else None
        if component_text and component is None:
            errors.append(
                f"{line}줄: 모르는 성분 「{cell.get('component')}」 — x · y · z · 크기"
            )
            continue

        made: dict[str, Any] = {"kind": kind, "probe": probe, "unit": unit}
        if kind == "frequency":
            if frequency is None or frequency <= 0:
                errors.append(f"{line}줄: 공진에는 주파수(Hz)가 있어야 합니다.")
                continue
            made["frequency_hz"] = frequency
        elif kind == "frf":
            if probe is None or frequency is None or value is None:
                errors.append(f"{line}줄: FRF 에는 측정점 · 주파수 · 값이 있어야 합니다.")
                continue
            normalized = unit.lower().endswith("/n")
            base = unit[:-2].strip() if normalized else unit
            known = _UNITS.get(base.lower() if base.lower() != "g" else "g")
            if known is None:
                errors.append(
                    f"{line}줄: FRF 단위 「{unit}」 를 모릅니다 — mm · m/s · m/s2 · g …"
                )
                continue
            made.update(
                frequency_hz=frequency,
                value=abs(value) * known[1],
                quantity=known[0],
                normalized=normalized,
            )
        elif kind == "displacement":
            known = _UNITS.get(unit.lower() or "mm")
            if probe is None or value is None or known is None or known[0] != "displacement":
                errors.append(
                    f"{line}줄: 변위에는 측정점 · 값과 길이 단위(mm · m · um)가 있어야 합니다."
                )
                continue
            made.update(value=value * known[1], component=component or "magnitude")
        else:  # strain
            scale = _STRAIN_UNITS.get(unit.lower())
            if probe is None or value is None or scale is None:
                errors.append(
                    f"{line}줄: 변형률에는 측정점 · 값이 있어야 하고 단위는 비우거나 "
                    "ue 입니다."
                )
                continue
            if component not in ("x", "y", "z"):
                errors.append(
                    f"{line}줄: 변형률의 성분은 x · y · z 중 하나입니다 — 게이지 방향입니다."
                )
                continue
            made.update(value=value * scale, component=component)
        rows.append(made)
    if not rows and not errors:
        errors.append("읽을 줄이 없습니다.")
    return (rows if not errors else []), errors


# --- 견주기 -----------------------------------------------------------------------


def _pct(analysis: float, measured: float) -> float | None:
    return (analysis - measured) / measured * 100 if measured else None


def _visibility(result: dict[str, Any]) -> dict[str, dict[int, float]]:
    """측정점 → 모드 번호 → **그 자리에서 얼마나 움직이나**(그 자리 최대에 대한 비)."""
    by_probe: dict[str, dict[int, float]] = {}
    for row in result.get("probes") or []:
        mode = row.get("mode")
        value = row.get("value")
        if isinstance(mode, int) and isinstance(value, int | float):
            by_probe.setdefault(str(row["name"]), {})[mode] = float(value)
    shares: dict[str, dict[int, float]] = {}
    for name, values in by_probe.items():
        top = max(values.values(), default=0.0)
        if top > 0:
            shares[name] = {mode: value / top for mode, value in values.items()}
    return shares


def _resonances(
    result: dict[str, Any], rows: list[dict[str, Any]], youngs_gpa: float | None
) -> dict[str, Any] | None:
    measured = [one for one in rows if one["kind"] == "frequency"]
    if not measured:
        return None
    modes = [
        one
        for one in elastic_modes(result)
        if isinstance(one.get("frequency_hz"), int | float)
    ]
    shares = _visibility(result)

    candidates: list[tuple[float, int, int]] = []  # (|차이|, 실측 순번, 모드 번호)
    near: dict[int, int] = {}
    for index, row in enumerate(measured):
        seen = shares.get(row["probe"] or "")
        for mode in modes:
            if seen is not None and seen.get(int(mode["number"]), 0.0) < VISIBLE_SHARE:
                continue
            gap = abs(float(mode["frequency_hz"]) - row["frequency_hz"]) / row["frequency_hz"]
            if gap <= AMBIGUOUS_WINDOW:
                near[index] = near.get(index, 0) + 1
            if gap <= PAIR_WINDOW:
                candidates.append((gap, index, int(mode["number"])))

    # **한 모드는 한 번만** — 가까운 짝부터 짓는다(설계점 사이 모드 잇기와 같은 규칙).
    chosen: dict[int, int] = {}
    used: set[int] = set()
    for _, index, number in sorted(candidates):
        if index in chosen or number in used:
            continue
        chosen[index] = number
        used.add(number)

    by_number = {int(one["number"]): one for one in modes}
    matches: list[dict[str, Any]] = []
    for index, row in enumerate(measured):
        picked = chosen.get(index)
        paired = by_number.get(picked) if picked is not None else None
        seen = shares.get(row["probe"] or "")
        matches.append(
            {
                "probe": row["probe"],
                "measured_hz": row["frequency_hz"],
                "mode": picked,
                "elastic_number": paired.get("elastic_number") if paired else None,
                "analysis_hz": float(paired["frequency_hz"]) if paired else None,
                "diff_pct": _pct(float(paired["frequency_hz"]), row["frequency_hz"])
                if paired
                else None,
                "visibility": seen.get(picked)
                if seen is not None and picked is not None
                else None,
                "ambiguous": near.get(index, 0) > 1,
            }
        )
    diffs = [abs(one["diff_pct"]) for one in matches if one["diff_pct"] is not None]
    explanation, suggested = _explain_frequencies(matches, youngs_gpa)
    return {
        "matches": matches,
        "mean_abs_pct": sum(diffs) / len(diffs) if diffs else None,
        "max_abs_pct": max(diffs) if diffs else None,
        "explanation": explanation,
        "suggested_modulus_gpa": suggested,
    }


def _explain_frequencies(
    matches: list[dict[str, Any]], youngs_gpa: float | None
) -> tuple[str, float | None]:
    pairs = [
        (one["measured_hz"], one["analysis_hz"])
        for one in matches
        if one["analysis_hz"] and not one["ambiguous"]
    ]
    if not pairs:
        return (
            "짝을 지은 공진이 없습니다 — 창(±25%) 안에 센서 자리에서 움직이는 모드가 "
            "없습니다.",
            None,
        )
    ratios = [(measured / analysis) ** 2 for measured, analysis in pairs]
    mean = sum(ratios) / len(ratios)
    spread = max(abs(one / mean - 1) for one in ratios)
    if len(pairs) >= 2 and spread > CONSISTENT_SPREAD:
        return (
            f"모드마다 어긋난 비율이 다릅니다(±{spread * 100:.1f}%) — 물성 하나로는 설명되지 "
            "않습니다. 경계조건 · 접촉 · 형상을 봅니다.",
            None,
        )
    if youngs_gpa is None:
        return (
            f"짝 {len(pairs)}개가 같은 비율로 어긋났습니다 — 강성/질량 비가 "
            f"{mean:.3f} 배면 맞습니다.",
            None,
        )
    suggested = youngs_gpa * mean
    basis = "모든 짝이 같은 비율로 어긋났습니다" if len(pairs) >= 2 else "짝이 하나뿐입니다"
    return (
        f"{basis} — 영률을 {youngs_gpa:g} → {suggested:.1f} GPa 로 두면 맞습니다"
        "(f ∝ √(E/밀도), 밀도가 맞다고 볼 때).",
        suggested,
    )


def _decimate(points: list[tuple[float, float]]) -> list[list[float]]:
    if len(points) <= CURVE_POINTS:
        return [[f, a] for f, a in points]
    step = len(points) / CURVE_POINTS
    picked = [points[int(index * step)] for index in range(CURVE_POINTS)]
    top = max(points, key=lambda pair: pair[1])
    if top not in picked:
        picked.append(top)  # 봉우리는 꼭 남긴다
    return [[f, a] for f, a in sorted(picked)]


def _half_power(points: list[tuple[float, float]]) -> float | None:
    """반전력 대역 감쇠비 ζ ≈ (f₂ - f₁) / 2fₙ — 봉우리 양쪽이 1/√2 를 지나야 잰다."""
    if len(points) < 3:
        return None
    index = max(range(len(points)), key=lambda at: points[at][1])
    f_peak, top = points[index]
    level = top / math.sqrt(2)

    def crossing(direction: int) -> float | None:
        at = index
        while 0 <= at + direction < len(points):
            f0, a0 = points[at]
            f1, a1 = points[at + direction]
            if a1 <= level <= a0 and a0 != a1:
                return f0 + (level - a0) * (f1 - f0) / (a1 - a0)
            at += direction
        return None

    low, high = crossing(-1), crossing(1)
    if low is None or high is None or f_peak <= 0:
        return None
    return (high - low) / (2 * f_peak)


def _frf(
    result: dict[str, Any], rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    measured = [one for one in rows if one["kind"] == "frf"]
    if not measured:
        return [], []
    skipped: list[str] = []
    scale = to_mm((result.get("units") or {}).get("displacement"))
    damping = result.get("damping_ratio")
    made: list[dict[str, Any]] = []
    for probe in dict.fromkeys(one["probe"] for one in measured):
        mine = sorted(
            (one for one in measured if one["probe"] == probe),
            key=lambda one: one["frequency_hz"],
        )
        quantity = mine[0]["quantity"]
        normalized = any(one.get("normalized") for one in mine)
        curve_m = [(float(one["frequency_hz"]), float(one["value"])) for one in mine]
        curve_a: list[tuple[float, float]] = []
        for point in result.get("points") or []:
            amplitude = (point.get("probes") or {}).get(probe)
            if not isinstance(amplitude, int | float) or scale is None:
                continue
            frequency = float(point["frequency_hz"])
            omega = 2 * math.pi * frequency
            base = float(amplitude) * scale  # mm
            value = {
                "displacement": base,
                "velocity": omega * base,
                "acceleration": omega**2 * base,
            }[quantity]
            curve_a.append((frequency, value))
        if not curve_a:
            skipped.append(
                f"측정점 「{probe}」 의 해석 곡선이 없습니다 — CAD 점 그룹 이름과 같아야 "
                "합니다."
            )
            continue
        peak_m = max(curve_m, key=lambda pair: pair[1])
        peak_a = max(curve_a, key=lambda pair: pair[1])
        ratio = peak_a[1] / peak_m[1] if not normalized and peak_m[1] > 0 else None
        zeta_m = _half_power(curve_m)
        suggested = (
            float(damping) * ratio
            if ratio is not None and isinstance(damping, int | float)
            else None
        )
        if normalized:
            note = "가진력으로 나눈 FRF 라 봉우리 높이는 견주지 않습니다 — 위치만 봅니다."
        elif suggested is not None and ratio is not None and isinstance(damping, int | float):
            note = (
                f"봉우리 높이가 {ratio:.2f} 배입니다 — 높이는 감쇠에 반비례하므로 감쇠비를 "
                f"{float(damping) * 100:.2f}% → {suggested * 100:.2f}% 로 두면 맞습니다"
                "(같은 가진력일 때)."
            )
        else:
            note = ""
        made.append(
            {
                "probe": probe,
                "quantity": quantity,
                "unit": BASE_UNITS[quantity] + ("/N" if normalized else ""),
                "measured": _decimate(curve_m),
                "analysis": _decimate(curve_a),
                "measured_peak_hz": peak_m[0],
                "analysis_peak_hz": peak_a[0],
                "peak_diff_pct": _pct(peak_a[0], peak_m[0]),
                "amplitude_ratio": ratio,
                "measured_damping": zeta_m,
                "analysis_damping": float(damping)
                if isinstance(damping, int | float)
                else None,
                "suggested_damping": suggested,
                "note": note,
            }
        )
    return made, skipped


_AXES = {"x": 0, "y": 1, "z": 2}


def _static(
    result: dict[str, Any],
    rows: list[dict[str, Any]],
    youngs_gpa: float | None,
    force_driven: bool,
) -> tuple[dict[str, Any] | None, list[str]]:
    measured = [one for one in rows if one["kind"] in ("displacement", "strain")]
    if not measured:
        return None, []
    skipped: list[str] = []
    probes = {str(one["name"]): one for one in result.get("probes") or []}
    matches: list[dict[str, Any]] = []
    for row in measured:
        probe = probes.get(row["probe"] or "")
        analysis: float | None = None
        note = ""
        if probe is None:
            note = "해석 결과에 이 측정점이 없습니다 — CAD 점 그룹 이름과 같아야 합니다."
        elif row["kind"] == "displacement":
            scale = to_mm(probe.get("unit"))
            if scale is None:
                note = f"해석 변위의 단위 「{probe.get('unit')}」 를 모릅니다."
            elif row["component"] == "magnitude":
                analysis = float(probe["value"]) * scale
            elif isinstance(probe.get("vector"), list):
                analysis = float(probe["vector"][_AXES[row["component"]]]) * scale
            else:
                note = "해석 결과에 성분이 없습니다(옛 결과) — 크기로 견주세요."
        else:
            strain = probe.get("strain")
            if isinstance(strain, list) and len(strain) == 3:
                analysis = float(strain[_AXES[row["component"]]])
            else:
                note = "해석 결과에 변형률이 없습니다 — 다시 실행하면 생깁니다."
        matches.append(
            {
                "probe": row["probe"],
                "kind": row["kind"],
                "component": row["component"],
                "measured": row["value"],
                "analysis": analysis,
                "unit": "mm" if row["kind"] == "displacement" else "",
                "diff_pct": _pct(analysis, row["value"]) if analysis is not None else None,
                "note": note,
            }
        )
    diffs = [abs(one["diff_pct"]) for one in matches if one["diff_pct"] is not None]
    explanation, suggested = _explain_static(matches, youngs_gpa, force_driven)
    return (
        {
            "matches": matches,
            "mean_abs_pct": sum(diffs) / len(diffs) if diffs else None,
            "explanation": explanation,
            "suggested_modulus_gpa": suggested,
        },
        skipped,
    )


def _explain_static(
    matches: list[dict[str, Any]], youngs_gpa: float | None, force_driven: bool
) -> tuple[str, float | None]:
    pairs = [
        (one["measured"], one["analysis"])
        for one in matches
        if one["analysis"] not in (None, 0) and one["measured"] != 0
    ]
    if not pairs:
        return "견줄 값이 없습니다.", None
    if not force_driven:
        return (
            "변위로 당긴 모델입니다 — 변위 · 변형률의 차이는 영률로 설명되지 않습니다"
            "(반력 · 접촉을 봅니다).",
            None,
        )
    ratios = [analysis / measured for measured, analysis in pairs]  # u ∝ 1/E
    if any(one <= 0 for one in ratios):
        return "부호가 다른 값이 있습니다 — 방향(성분)과 하중 방향을 먼저 맞춥니다.", None
    mean = sum(ratios) / len(ratios)
    spread = max(abs(one / mean - 1) for one in ratios)
    if len(pairs) >= 2 and spread > CONSISTENT_SPREAD * 2:
        return (
            f"측정점마다 어긋난 비율이 다릅니다(±{spread * 100:.1f}%) — 물성 하나로는 "
            "설명되지 "
            "않습니다. 하중 자리 · 구속 · 형상을 봅니다.",
            None,
        )
    if youngs_gpa is None:
        return f"해석이 실측의 {mean:.3f} 배입니다(모든 자리에서 같은 비율).", None
    suggested = youngs_gpa * mean
    return (
        f"모든 자리에서 같은 비율로 어긋났습니다 — 영률을 {youngs_gpa:g} → "
        f"{suggested:.1f} GPa "
        "로 두면 맞습니다(힘으로 건 선형 정적이면 변위가 1/E 에 비례).",
        suggested,
    )


def compare(
    result: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    youngs_gpa: float | None = None,
    force_driven: bool = True,
) -> dict[str, Any]:
    """실측 줄들과 해석 결과 → 견준 것. 그 레시피로 못 견주는 종류는 `skipped` 에 까닭을
    적는다."""
    recipe = str(result.get("recipe") or "")
    kinds = {one["kind"] for one in rows}
    skipped: list[str] = []
    frequency = None
    frf: list[dict[str, Any]] = []
    static = None
    if "frequency" in kinds:
        if recipe == "modal":
            frequency = _resonances(result, rows, youngs_gpa)
        else:
            skipped.append("공진은 모달 결과와 견줍니다 — 이 작업은 모달이 아닙니다.")
    if "frf" in kinds:
        if recipe == "harmonic":
            frf, missing = _frf(result, rows)
            skipped += missing
        else:
            skipped.append(
                "FRF 는 조화 응답 결과와 견줍니다 — 이 작업은 조화 응답이 아닙니다."
            )
    if kinds & {"displacement", "strain"}:
        if recipe == "static":
            static, missing = _static(result, rows, youngs_gpa, force_driven)
            skipped += missing
        else:
            skipped.append("변위 · 변형률은 정적 결과와 견줍니다 — 이 작업은 정적이 아닙니다.")
    return {
        "recipe": recipe,
        "frequency": frequency,
        "frf": frf,
        "static": static,
        "skipped": skipped,
        "score_pct": score(frequency, frf, static),
    }


def score(
    frequency: dict[str, Any] | None,
    frf: list[dict[str, Any]],
    static: dict[str, Any] | None,
) -> float | None:
    """**한 수로 줄인 차이**(절댓값 평균, %) — 스터디에서 실측에 가장 가까운 설계점을 고른다.

    공진은 짝마다, FRF 는 봉우리 위치, 정적은 값마다 하나씩 센다. 높이(감쇠)는 넣지 않는다 —
    감쇠는 설계점을 바꿔 맞출 값이 아니다.
    """
    gaps: list[float] = []
    if frequency is not None:
        gaps += [
            abs(one["diff_pct"]) for one in frequency["matches"] if one["diff_pct"] is not None
        ]
    gaps += [abs(one["peak_diff_pct"]) for one in frf if one["peak_diff_pct"] is not None]
    if static is not None:
        gaps += [
            abs(one["diff_pct"]) for one in static["matches"] if one["diff_pct"] is not None
        ]
    return sum(gaps) / len(gaps) if gaps else None


TEMPLATE = (
    "측정점,종류,주파수,값,단위,성분\n"
    ",공진,1250.3,,,\n"
    "측정점,공진,3410,,,\n"
    "측정점,FRF,1200,0.031,mm,x\n"
    "측정점,FRF,1250,0.402,mm,x\n"
    "측정점,FRF,1300,0.044,mm,x\n"
    "이음 입구 위판,변위,,0.0401,mm,x\n"
    "이음 입구 위판,변형률,,-120,ue,z\n"
)
"""양식 — 종류 넷을 한 표에. 장비 파일은 이 모양으로 옮긴다."""
