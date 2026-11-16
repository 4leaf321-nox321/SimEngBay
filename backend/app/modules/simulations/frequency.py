"""**주파수 요구 판정** — 모달 DOE 를 목표 주파수 · 회피 대역으로 판정한다(2026-11-16).

설계 목표가 「이 모드를 이 주파수에 맞춘다」(공진 맞춤)와 「들뜨는 모드가 가진 대역에 들지
않는다」(공진 회피) 둘이다. 요구 조건은 스터디에 저장하고(`StudyFrequencyRequirement`), 판정은
읽을 때 셈한다 — 결과가 다시 돌면 판정도 따라 바뀐다. 화면(「주파수 요구」 탭)과 MCP
(`study_frequency`)가 **이 셈 하나**를 쓴다. 화면은 입력을 고칠 때마다 저장하지 않은 요구로
이 셈을 다시 부른다(미리보기) — 같은 규칙을 두 벌로 두지 않는다.

## 목표 주파수

추적한 모드(형상 MAC 으로 이은 모드 — 순번이 아니다)의 주파수가 목표 ± 허용 안이면 만족이다.
그 설계점에서 그 모드를 잇지 못했으면 판정 보류다(다른 모드를 견주면 거짓 판정이다). 스터디에
모드 추적이 없으면(지문이 없는 옛 작업) 차례로 센다 — 그렇다고 적는다.

## 회피 대역

**판정 대상 모드**만 본다 — 실제로 들뜨는 모드다. 범위 안의 모든 모드로 판정하면 거의 다
걸린다(국부 모드 · 다른 방향 모드). 둘 중 하나라도 문턱을 넘으면 대상이다:

- 유효질량비 — 가진 방향(X · Y · Z)의 유효질량이 문턱(%) 이상.
- 측정점 움직임 — 그 측정점이 가장 크게 움직인 모드 대비 문턱(%) 이상(실측 맞추기와 같은 셈,
  `core/measured.visibility`).

참여 정보가 없는 모드(표가 없는 결과)는 대상으로 둔다 — 들뜨지 않는다고 보일 수 없으면 피해야
한다. 대상 모드가 모두 `하한 x (1 - 여유)` 아래거나 `상한 x (1 + 여유)` 위면 만족이다. 회피
대역에는 추적하지 못한 모드도 든다 — 새로 나타난 모드도 대역에 들 수 있다.

## 판정

적합(모두 만족) · 대역 침범(목표는 만족, 회피 대역에 걸림) · 목표 이탈(대역은 피함, 목표를
벗어남) · 부적합(둘 다) · 판정 보류(끝나지 않음 · 모드를 잇지 못함).

## 보간 추정과 공차 민감도

- 한 설계 변수를 따라 이웃 설계점 사이를 곧게 이어, 맞출 모드가 목표를 지나는 자리와 판정
  대상 모드가 대역 끝(여유 포함)을 지나는 자리를 낸다(`crossings`). 목표를 지나는 자리 가운데
  모든 요구를 만족하고 이격 여유가 가장 큰 곳을 추정으로 낸다(`estimate`) — DOE 에 없는 점이다.
  SimEngBay 는 형상을 만들지 못하므로 CompCore 에서 그 값으로 점을 더해 확인한다.
- 공차 민감도: 맞출 모드가 변수 한 단위에 몇 Hz 움직이나(이웃 설계점의 기울기)와, 목표 허용
  폭(± Hz)에 해당하는 변수 폭 — 제조 공차가 이보다 크면 목표를 못 지킨다.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.core.numbers import significant
from app.modules.simulations.schemas import (
    FrequencyBand,
    FrequencyBandResultOut,
    FrequencyCheckOut,
    FrequencyCrossingOut,
    FrequencyEstimateOut,
    FrequencyModeOut,
    FrequencyPointOut,
    FrequencyRequirement,
    FrequencySensitivityOut,
    FrequencyTarget,
    FrequencyTargetResultOut,
    FrequencyVerdict,
    ModeTrackOut,
    StudyOut,
    StudyPointOut,
)

VERDICTS: tuple[FrequencyVerdict, ...] = (
    "conform",
    "band_violation",
    "target_deviation",
    "nonconform",
    "pending",
)
#: 판정의 이름 — 화면 · MCP 가 같은 말을 쓴다.
VERDICT_LABELS: dict[str, str] = {
    "conform": "적합",
    "band_violation": "대역 침범",
    "target_deviation": "목표 이탈",
    "nonconform": "부적합",
    "pending": "판정 보류",
}


@dataclass
class _Mode:
    index: int
    track: int | None
    hz: float
    mass: dict[str, float]
    probe: dict[str, float]


@dataclass
class _Point:
    source: StudyPointOut
    modes: list[_Mode] = field(default_factory=list)


def _modes_of(point: StudyPointOut, tracks: Sequence[ModeTrackOut]) -> list[_Mode]:
    track_of = {
        number: track.reference
        for track in tracks
        if (number := track.numbers.get(point.number)) is not None
    }
    made: list[_Mode] = []
    for at, hz in enumerate(point.frequencies):
        mass = point.mode_mass[at] if at < len(point.mode_mass) else {}
        probe = point.mode_probes[at] if at < len(point.mode_probes) else {}
        made.append(
            _Mode(
                index=at + 1,
                track=track_of.get(at + 1),
                hz=float(hz),
                mass={key: float(value) * 100 for key, value in mass.items()},
                probe={key: float(value) * 100 for key, value in probe.items()},
            )
        )
    return made


def _target_mode(
    point: _Point, req: FrequencyTarget, tracked: bool
) -> tuple[_Mode | None, str | None]:
    if tracked:
        found = next((one for one in point.modes if one.track == req.mode), None)
        if found is None:
            return None, f"이 설계점에서 {req.mode}차 모드를 형상으로 잇지 못했습니다."
        return found, None
    if req.mode > len(point.modes):
        return None, f"{req.mode}차 모드가 없습니다."
    return point.modes[req.mode - 1], None


def judged(req: FrequencyBand, mode: _Mode) -> tuple[bool, str]:
    """회피 대역의 판정 대상인가와 그 까닭."""
    if not req.mass_filter and not req.probe_filter:
        return True, "거르는 기준이 없어 모든 모드를 판정합니다"
    facts: list[str] = []
    hit = False
    known = False
    if req.mass_filter:
        mass = mode.mass.get(req.mass_direction)
        if mass is not None:
            known = True
            facts.append(f"{req.mass_direction} 유효질량 {mass:.1f} %")
            hit = hit or mass >= req.mass_min_pct
    if req.probe_filter:
        if req.probe:
            name, value = req.probe, mode.probe.get(req.probe)
        else:
            name, value = max(mode.probe.items(), key=lambda one: one[1], default=("", None))
        if value is not None:
            known = True
            facts.append(f"측정점 {name} {value:.0f} %")
            hit = hit or value >= req.probe_min_pct
    if not known:
        return True, "참여 정보가 없어 판정 대상으로 둡니다"
    return hit, " · ".join(facts)


def _zone(req: FrequencyBand) -> tuple[float, float]:
    return req.low_hz * (1 - req.margin_pct / 100), req.high_hz * (1 + req.margin_pct / 100)


def _margin(req: FrequencyBand, hz: float) -> tuple[float, bool]:
    """대역 끝까지의 이격률(%)과 대역 안인가."""
    if req.low_hz <= hz <= req.high_hz:
        return 0.0, True
    if hz < req.low_hz:
        return (req.low_hz - hz) / req.low_hz * 100, False
    return (hz - req.high_hz) / req.high_hz * 100, False


def _band_result(
    at: int, req: FrequencyBand, modes: Sequence[_Mode]
) -> FrequencyBandResultOut:
    worst: tuple[bool, float, _Mode] | None = None
    count = 0
    for mode in modes:
        if not judged(req, mode)[0]:
            continue
        count += 1
        margin, inside = _margin(req, mode.hz)
        key = (inside, margin, mode)
        if worst is None or (inside, -margin) > (worst[0], -worst[1]):
            worst = key
    if worst is None:
        return FrequencyBandResultOut(requirement=at, judged=0, ok=True)
    inside, margin, mode = worst
    return FrequencyBandResultOut(
        requirement=at,
        closest_index=mode.index,
        closest_track=mode.track,
        closest_hz=significant(mode.hz),
        margin_pct=round(margin, 3),
        inside=inside,
        ok=not inside and margin >= req.margin_pct - 1e-9,
        judged=count,
    )


def _verdict(
    targets: Sequence[FrequencyTargetResultOut], bands: Sequence[FrequencyBandResultOut]
) -> FrequencyVerdict:
    if any(one.frequency_hz is None for one in targets):
        return "pending"
    target_ok = all(one.ok for one in targets)
    band_ok = all(one.ok for one in bands)
    if target_ok and band_ok:
        return "conform"
    if not target_ok and not band_ok:
        return "nonconform"
    return "target_deviation" if not target_ok else "band_violation"


def _numeric(value: float | str | None) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(value)
    except ValueError:
        return None


def _numeric_factors(points: Sequence[_Point], factors: Sequence[str]) -> list[str]:
    """값이 모두 숫자이고 두 수준 이상인 변수."""
    made: list[str] = []
    for name in factors:
        values = [_numeric(one.source.params.get(name)) for one in points]
        if values and all(one is not None for one in values) and len(set(values)) > 1:
            made.append(name)
    return made


def _lines(points: Sequence[_Point], factors: Sequence[str], along: str) -> list[list[_Point]]:
    """`along` 만 다르고 나머지 변수가 같은 점들의 줄 — `along` 차례로."""
    groups: dict[tuple[str, ...], list[_Point]] = {}
    for point in points:
        key = tuple(str(point.source.params.get(name)) for name in factors if name != along)
        groups.setdefault(key, []).append(point)
    made: list[list[_Point]] = []
    for members in groups.values():
        members.sort(key=lambda one: _numeric(one.source.params.get(along)) or 0.0)
        if len(members) >= 2:
            made.append(members)
    return made


def _track_hz(point: _Point, track: int) -> float | None:
    found = next((one for one in point.modes if one.track == track), None)
    return found.hz if found else None


def _crossing(a: float, b: float, level: float) -> float | None:
    """a → b 가 level 을 지나는 자리(0~1)."""
    da, db = a - level, b - level
    if da == 0:
        return 0.0
    if (da < 0 < db) or (da > 0 > db):
        return da / (da - db)
    return None


def _sensitivity(
    point: _Point,
    done: Sequence[_Point],
    factors: Sequence[str],
    req: FrequencyTarget,
    tracked: bool,
) -> list[FrequencySensitivityOut]:
    """맞출 모드의 기울기 — 그 변수만 다른 이웃 설계점과."""
    here, _ = _target_mode(point, req, tracked)
    if here is None:
        return []
    made: list[FrequencySensitivityOut] = []
    for name in factors:
        x = _numeric(point.source.params.get(name))
        if x is None:
            continue
        others = [n for n in factors if n != name]
        same = [
            one
            for one in done
            if one is not point
            and all(
                str(one.source.params.get(n)) == str(point.source.params.get(n))
                for n in others
            )
        ]
        near: list[tuple[float, float]] = []
        for one in same:
            ox = _numeric(one.source.params.get(name))
            mode, _ = _target_mode(one, req, tracked)
            if ox is None or mode is None or ox == x:
                continue
            near.append((ox, mode.hz))
        below = max((one for one in near if one[0] < x), default=None, key=lambda one: one[0])
        above = min((one for one in near if one[0] > x), default=None, key=lambda one: one[0])
        if below is not None and above is not None:
            slope = (above[1] - below[1]) / (above[0] - below[0])
        elif below is not None:
            slope = (here.hz - below[1]) / (x - below[0])
        elif above is not None:
            slope = (above[1] - here.hz) / (above[0] - x)
        else:
            continue
        allowed = req.target_hz * req.tolerance_pct / 100
        made.append(
            FrequencySensitivityOut(
                factor=name,
                hz_per_unit=significant(slope),
                equivalent=significant(allowed / abs(slope)) if slope else None,
            )
        )
    return made


def _fmt(value: float) -> str:
    return f"{value:,.0f}"


def _shown(value: float) -> str:
    return f"{significant(value, 3):g}"


def evaluate(
    study: StudyOut, requirements: Sequence[FrequencyRequirement]
) -> FrequencyCheckOut:
    """판정 — 점마다 요구 줄의 결과 · 모드의 역할 · 공차 민감도, 그리고 보간 자리와 추정."""
    tracks = list(study.tracks)
    tracked = bool(tracks)
    points = [_Point(source=one, modes=_modes_of(one, tracks)) for one in study.points]
    done = [one for one in points if one.source.status == "done" and one.modes]
    targets = [
        (at, one) for at, one in enumerate(requirements) if isinstance(one, FrequencyTarget)
    ]
    bands = [
        (at, one) for at, one in enumerate(requirements) if isinstance(one, FrequencyBand)
    ]
    numeric = _numeric_factors(done, study.factors)
    notes: list[str] = []
    if not tracked:
        notes.append(
            "모드를 형상으로 잇지 못한 스터디라 차례(1차 · 2차 …)로 셉니다 — 치수가 바뀌어 "
            "모드 순서가 뒤바뀌면 다른 모드를 견줍니다."
        )
    if bands and any(
        not mode.mass and not mode.probe for point in done for mode in point.modes
    ):
        notes.append(
            "참여 정보(유효질량 · 측정점)가 없는 모드는 회피 대역의 판정 대상으로 둡니다."
        )
    if not requirements:
        notes.append("요구 조건이 없습니다 — 목표 주파수나 회피 대역을 더하세요.")

    out_points: list[FrequencyPointOut] = []
    for point in points:
        source = point.source
        if source.status != "done" or not point.modes or not requirements:
            out_points.append(
                FrequencyPointOut(
                    simulation_id=source.simulation_id,
                    number=source.number,
                    params=source.params,
                    status=source.status,
                    verdict="pending",
                    mass_kg=source.mass_kg,
                )
            )
            continue
        target_out: list[FrequencyTargetResultOut] = []
        target_index: set[int] = set()
        for at, req in targets:
            mode, note = _target_mode(point, req, tracked)
            if mode is None:
                target_out.append(FrequencyTargetResultOut(requirement=at, note=note))
                continue
            target_index.add(mode.index)
            error = (mode.hz - req.target_hz) / req.target_hz * 100
            target_out.append(
                FrequencyTargetResultOut(
                    requirement=at,
                    index=mode.index,
                    frequency_hz=significant(mode.hz),
                    error_pct=round(error, 3),
                    ok=abs(error) <= req.tolerance_pct + 1e-9,
                )
            )
        band_out = [_band_result(at, req, point.modes) for at, req in bands]
        modes_out: list[FrequencyModeOut] = []
        for mode in point.modes:
            hits = [judged(req, mode) for _, req in bands]
            judging = [
                (at, req) for (at, req), (hit, _) in zip(bands, hits, strict=True) if hit
            ]
            in_band = any(req.low_hz <= mode.hz <= req.high_hz for _, req in judging)
            role: Literal["target", "judged", "excluded"]
            if mode.index in target_index:
                role, reason = "target", "목표 주파수 대상"
            elif any(hit for hit, _ in hits):
                role, reason = "judged", next(why for hit, why in hits if hit)
            else:
                role = "excluded"
                reason = hits[0][1] if hits else "회피 대역이 없습니다"
            modes_out.append(
                FrequencyModeOut(
                    index=mode.index,
                    track=mode.track,
                    frequency_hz=significant(mode.hz),
                    mass_pct={key: round(value, 3) for key, value in mode.mass.items()},
                    probe_pct={key: round(value, 2) for key, value in mode.probe.items()},
                    role=role,
                    bands=[at for at, _ in judging],
                    in_band=in_band,
                    reason=reason,
                )
            )
        out_points.append(
            FrequencyPointOut(
                simulation_id=source.simulation_id,
                number=source.number,
                params=source.params,
                status=source.status,
                verdict=_verdict(target_out, band_out),
                mass_kg=source.mass_kg,
                targets=target_out,
                bands=band_out,
                modes=modes_out,
                sensitivity=(
                    _sensitivity(point, done, numeric, targets[0][1], tracked)
                    if targets
                    else []
                ),
            )
        )

    crossings, estimate = _interpolate(done, study.factors, numeric, targets, bands, tracked)
    counts: dict[str, int] = {name: 0 for name in VERDICTS}
    for one in out_points:
        counts[one.verdict] += 1
    probes: list[str] = []
    for point in done:
        for mode in point.modes:
            for name in mode.probe:
                if name not in probes:
                    probes.append(name)
    return FrequencyCheckOut(
        study_id=study.study_id,
        requirements=list(requirements),
        factors=list(study.factors),
        probes=probes,
        tracks=[one.reference for one in tracks]
        if tracked
        else list(range(1, max((len(one.modes) for one in done), default=0) + 1)),
        tracked=tracked,
        counts=counts,
        points=out_points,
        crossings=crossings,
        estimate=estimate,
        notes=notes,
    )


def _interpolate(
    done: Sequence[_Point],
    factors: Sequence[str],
    numeric: Sequence[str],
    targets: Sequence[tuple[int, FrequencyTarget]],
    bands: Sequence[tuple[int, FrequencyBand]],
    tracked: bool,
) -> tuple[list[FrequencyCrossingOut], FrequencyEstimateOut | None]:
    """한 변수를 따라 이은 선이 기준을 지나는 자리, 그리고 추정."""
    crossings: list[FrequencyCrossingOut] = []
    best: tuple[float, float, FrequencyEstimateOut] | None = None
    if not tracked:
        return crossings, None
    for along in numeric:
        for line in _lines(done, factors, along):
            fixed = {
                name: line[0].source.params[name]
                for name in factors
                if name != along and name in line[0].source.params
            }
            for a, b in itertools.pairwise(line):
                xa = _numeric(a.source.params.get(along))
                xb = _numeric(b.source.params.get(along))
                if xa is None or xb is None:
                    continue
                for at, req in targets:
                    fa, fb = _track_hz(a, req.mode), _track_hz(b, req.mode)
                    if fa is None or fb is None:
                        continue
                    share = _crossing(fa, fb, req.target_hz)
                    if share is None:
                        continue
                    value = xa + (xb - xa) * share
                    crossings.append(
                        FrequencyCrossingOut(
                            kind="target",
                            requirement=at,
                            track=req.mode,
                            factor=along,
                            value=significant(value),
                            fixed=fixed,
                            level_hz=req.target_hz,
                            label=(
                                f"{req.mode}차 모드가 목표 {_fmt(req.target_hz)} Hz 를 지나는 "
                                f"자리 — {along} ≈ {_shown(value)}"
                            ),
                        )
                    )
                    if at == targets[0][0]:
                        found = _estimate(a, b, share, along, value, fixed, targets, bands)
                        if found is not None and (best is None or found[:2] > best[:2]):
                            best = found
                for at, band in bands:
                    for track in sorted({m.track for m in a.modes if m.track is not None}):
                        mode_a = next(m for m in a.modes if m.track == track)
                        mode_b = next((m for m in b.modes if m.track == track), None)
                        if mode_b is None:
                            continue
                        if not (judged(band, mode_a)[0] or judged(band, mode_b)[0]):
                            continue
                        for level in _zone(band):
                            share = _crossing(mode_a.hz, mode_b.hz, level)
                            if share is None:
                                continue
                            value = xa + (xb - xa) * share
                            crossings.append(
                                FrequencyCrossingOut(
                                    kind="band_edge",
                                    requirement=at,
                                    track=track,
                                    factor=along,
                                    value=significant(value),
                                    fixed=fixed,
                                    level_hz=round(level, 3),
                                    label=(
                                        f"{track}차 모드가 {_fmt(level)} Hz(회피 대역 ± 이격 "
                                        f"여유의 끝)를 지나는 자리 — {along} ≈ {_shown(value)}"
                                    ),
                                )
                            )
    return crossings, best[2] if best else None


def _estimate(
    a: _Point,
    b: _Point,
    share: float,
    along: str,
    value: float,
    fixed: dict[str, float | str],
    targets: Sequence[tuple[int, FrequencyTarget]],
    bands: Sequence[tuple[int, FrequencyBand]],
) -> tuple[float, float, FrequencyEstimateOut] | None:
    """목표를 지나는 자리에서 모든 요구를 만족하나 — 추적한 모드를 곧게 이어 본다. 만족하면
    (이격 여유, -질량, 추정)."""
    modes: list[_Mode] = []
    for mode_a in a.modes:
        if mode_a.track is None:
            continue
        mode_b = next((m for m in b.modes if m.track == mode_a.track), None)
        if mode_b is None:
            continue
        mass_mix = {
            key: mode_a.mass.get(key, 0.0)
            + (mode_b.mass.get(key, 0.0) - mode_a.mass.get(key, 0.0)) * share
            for key in set(mode_a.mass) | set(mode_b.mass)
        }
        probes = {
            key: mode_a.probe.get(key, 0.0)
            + (mode_b.probe.get(key, 0.0) - mode_a.probe.get(key, 0.0)) * share
            for key in set(mode_a.probe) | set(mode_b.probe)
        }
        modes.append(
            _Mode(
                index=mode_a.index,
                track=mode_a.track,
                hz=mode_a.hz + (mode_b.hz - mode_a.hz) * share,
                mass=mass_mix,
                probe=probes,
            )
        )
    for _, req in targets:
        found = next((m for m in modes if m.track == req.mode), None)
        if found is None or abs((found.hz - req.target_hz) / req.target_hz * 100) > (
            req.tolerance_pct + 1e-9
        ):
            return None
    results = [_band_result(at, req, modes) for at, req in bands]
    if not all(one.ok for one in results):
        return None
    margins = [one.margin_pct for one in results if one.margin_pct is not None]
    margin = min(margins) if margins else math.inf
    mass = None
    if a.source.mass_kg is not None and b.source.mass_kg is not None:
        mass = a.source.mass_kg + (b.source.mass_kg - a.source.mass_kg) * share
    params: dict[str, float | str] = {**fixed, along: significant(value, 4)}
    closest_row = min(
        (one for one in results if one.margin_pct is not None),
        key=lambda one: one.margin_pct or 0.0,
        default=None,
    )
    closest = (
        f"{closest_row.closest_track}차 모드 {_fmt(closest_row.closest_hz or 0)} Hz"
        if closest_row is not None and closest_row.closest_track is not None
        else None
    )
    where = " · ".join(
        f"{name} {_shown(v) if isinstance(v, int | float) else v}" for name, v in fixed.items()
    )
    lead = f"{where} · " if where else ""
    text = (
        f"DOE 에 없는 자리 — {lead}{along} ≈ {_shown(value)} 에서 모든 요구 조건을 "
        "만족할 것으로 보입니다."
    )
    if closest is not None and margins:
        text += f" 가장 가까운 판정 대상 모드는 {closest}, 이격 여유 {min(margins):.1f} %."
    if mass is not None:
        text += f" 질량 ≈ {mass * 1000:.1f} g."
    estimate = FrequencyEstimateOut(
        params=params,
        margin_pct=round(margin, 3) if math.isfinite(margin) else None,
        closest=closest,
        mass_kg=significant(mass) if mass is not None else None,
        text=text,
    )
    return margin, -(mass or 0.0), estimate
