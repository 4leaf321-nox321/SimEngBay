"""**주파수 요구 판정**(`app/modules/simulations/frequency.py`) — 목표 주파수 · 회피 대역.

두께 5 x 리브 높이 5 = 25점의 모달 DOE 를 짓는다(화면 시안과 같은 값). 모드 다섯 —
1차 굽힘 · 1차 비틀림 · 2차 굽힘 · 리브 국부 · 면내 굽힘. 리브 국부 · 면내 굽힘은 Z 유효질량 ·
센서 움직임이 작아 회피 대역의 판정 대상이 아니다. 점마다 모드를 **주파수 차례**로 두고 추적은
형상으로 이은 것처럼 기준 차수 → 그 점의 차례로 준다(차례가 뒤바뀌어도 같은 모드를 본다).
"""

from __future__ import annotations

import math
import uuid
from typing import Any

import pytest

from app.modules.simulations import frequency
from app.modules.simulations.schemas import (
    FrequencyBand,
    FrequencyTarget,
    ModeTrackOut,
    StudyOut,
    StudyPointOut,
)

THICKNESS = (1.2, 1.4, 1.6, 1.8, 2.0)
RIB = (0, 1, 2, 3, 4)
#: 기준 차수 → (Z 유효질량비, 센서 A 움직임) — 0~1.
PARTICIPATION = {
    1: ({"X": 0.002, "Y": 0.001, "Z": 0.46}, 0.72),
    2: ({"X": 0.031, "Y": 0.004, "Z": 0.012}, 0.58),
    3: ({"X": 0.001, "Y": 0.002, "Z": 0.17}, 0.31),
    4: ({"X": 0.003, "Y": 0.002, "Z": 0.004}, 0.03),
    5: ({"X": 0.02, "Y": 0.38, "Z": 0.001}, 0.01),
}


def _hz(track: int, t: float, h: float) -> float:
    r = t / 1.6
    if track == 1:
        return 575 * r * (1 + 0.035 * h)
    if track == 2:
        return 1170 * math.pow(r, 1.1) * (1 + 0.05 * h)
    if track == 3:
        return 1980 * r * (1 + 0.06 * h)
    if track == 4:
        return 1020 * math.pow(r, 0.5) * (1 + 0.06 * (4 - h))
    return 3150 * math.pow(r, 0.3)


def _study(*, tracked: bool = True, drop: tuple[int, int] | None = None) -> StudyOut:
    """`drop` = (설계점, 기준 차수) — 그 점에서 그 모드를 잇지 못한 것으로."""
    points: list[StudyPointOut] = []
    numbers: dict[int, dict[int, int]] = {track: {} for track in PARTICIPATION}
    for i, t in enumerate(THICKNESS):
        for j, h in enumerate(RIB):
            n = i * 5 + j + 1
            order = sorted(PARTICIPATION, key=lambda track: _hz(track, t, h))
            for at, track in enumerate(order, start=1):
                if drop != (n, track):
                    numbers[track][n] = at
            points.append(
                StudyPointOut(
                    simulation_id=uuid.uuid4(),
                    number=n,
                    params={"두께": t, "리브": h},
                    status="done",
                    mass_kg=(30 * t + 2 * h + 8) / 1000,
                    frequencies=[round(_hz(track, t, h), 3) for track in order],
                    mode_mass=[PARTICIPATION[track][0] for track in order],
                    mode_probes=[{"센서 A": PARTICIPATION[track][1]} for track in order],
                )
            )
    tracks = [
        ModeTrackOut(reference=track, numbers=numbers[track], confidence={})
        for track in PARTICIPATION
    ]
    return StudyOut(
        study_id="s1",
        name="브래킷",
        factors=["두께", "리브"],
        points=points,
        tracks=tracks if tracked else [],
        reference_point=1 if tracked else None,
    )


TARGET = FrequencyTarget(label="비틀림 공진", mode=2, target_hz=1300, tolerance_pct=3)
BAND = FrequencyBand(
    label="모터 가진",
    low_hz=700,
    high_hz=900,
    margin_pct=10,
    mass_filter=True,
    mass_direction="Z",
    mass_min_pct=5,
    probe_filter=True,
    probe="센서 A",
    probe_min_pct=20,
)


def _point(out: Any, number: int) -> Any:
    return next(one for one in out.points if one.number == number)


def test_목표_주파수와_회피_대역으로_설계점마다_판정한다() -> None:
    out = frequency.evaluate(_study(), [TARGET, BAND])
    assert out.counts == {
        "conform": 1,
        "band_violation": 1,
        "target_deviation": 8,
        "nonconform": 15,
        "pending": 0,
    }
    # 두께 1.6 · 리브 2 — 비틀림 1,287 Hz(-1.0 %), 1차 굽힘 615 Hz 가 하한 700 에서 12.1 %.
    best = _point(out, 13)
    assert best.verdict == "conform"
    assert best.targets[0].error_pct == pytest.approx(-1.0, abs=0.05)
    assert best.bands[0].closest_track == 1
    assert best.bands[0].margin_pct == pytest.approx(12.14, abs=0.05)
    # 두께 1.8 · 리브 0 — 목표는 맞췄지만 1차 굽힘 647 Hz 가 이격 여유(630 Hz) 안이다.
    assert _point(out, 16).verdict == "band_violation"
    assert _point(out, 16).bands[0].inside is False
    # 두께 1.2 — 비틀림 853 Hz 가 대역 안(센서가 움직이는 모드라 판정 대상).
    thin = _point(out, 1)
    assert thin.verdict == "nonconform"
    assert thin.bands[0].inside and thin.bands[0].closest_track == 2


def test_들뜨지_않는_모드는_대역_안이어도_판정에서_뺀다() -> None:
    out = frequency.evaluate(_study(), [TARGET, BAND])
    # 두께 1.2 · 리브 4 — 리브 국부 883 Hz 는 대역 안이지만 Z 0.4 % · 센서 3 %.
    point = _point(out, 5)
    local = next(one for one in point.modes if one.track == 4)
    # 수로는 대역 안이지만 그 대역의 판정 대상이 아니므로 「회피 대역 안」으로 세지 않는다.
    assert BAND.low_hz <= local.frequency_hz <= BAND.high_hz
    assert local.role == "excluded" and not local.in_band and local.bands == []
    assert "Z 유효질량 0.4 %" in local.reason and "센서 A 3 %" in local.reason
    assert next(one for one in point.modes if one.track == 2).role == "target"
    assert next(one for one in point.modes if one.track == 1).role == "judged"
    # 기준을 다 끄면 모든 모드가 판정 대상 — 리브 국부도 대역 안이라 걸린다.
    loose = BAND.model_copy(update={"mass_filter": False, "probe_filter": False})
    strict = _point(frequency.evaluate(_study(), [TARGET, loose]), 5)
    assert strict.bands[0].inside and strict.bands[0].judged == 5
    # 방향을 Y 로 바꾸면 면내 굽힘(Y 38 %)이 대상이 된다.
    sideways = BAND.model_copy(update={"mass_direction": "Y", "probe_filter": False})
    roles = {
        one.track: one.role
        for one in _point(frequency.evaluate(_study(), [sideways]), 5).modes
    }
    assert roles[5] == "judged" and roles[1] == "excluded"


def test_대역이_여럿이면_모드마다_어느_대역의_판정_대상인지_따로_센다() -> None:
    """Z 가진 대역의 대상이 Y 가진 대역에서는 제외다.

    「회피 대역 안」 표시도 그 대역의 판정 대상일 때만 붙는다.
    """
    fan = FrequencyBand(
        label="팬 가진",
        low_hz=2800,
        high_hz=3000,
        mass_filter=True,
        mass_direction="Y",
        mass_min_pct=5,
        probe_filter=False,
    )
    # 두께 1.2 · 리브 4 — 1차 굽힘 492 Hz(Z 46 %) · 면내 굽힘 2,889 Hz(Y 38 %).
    point = _point(frequency.evaluate(_study(), [BAND, fan]), 5)
    by_track = {one.track: one for one in point.modes}
    assert by_track[1].bands == [0] and not by_track[1].in_band
    assert by_track[5].bands == [1] and by_track[5].in_band and by_track[5].role == "judged"
    assert "Y 유효질량" in by_track[5].reason
    assert by_track[4].bands == [] and not by_track[4].in_band
    assert point.bands[1].inside and point.bands[1].closest_track == 5


def test_목표를_지나는_자리와_대역_끝을_보간하고_추정을_낸다() -> None:
    out = frequency.evaluate(_study(), [TARGET, BAND])
    hits = [
        one
        for one in out.crossings
        if one.kind == "target" and one.factor == "두께" and one.fixed == {"리브": 2}
    ]
    assert len(hits) == 1 and hits[0].value == pytest.approx(1.6146, abs=0.002)
    edges = [
        one
        for one in out.crossings
        if one.kind == "band_edge" and one.factor == "두께" and one.fixed == {"리브": 0}
    ]
    # 1차 굽힘이 630 Hz(하한 700 - 여유 10 %)를 지나는 자리.
    assert any(one.track == 1 and one.level_hz == pytest.approx(630) for one in edges)
    # 이격 여유가 가장 큰 추정 — 리브 4 · 두께 ≈ 1.49.
    assert out.estimate is not None
    assert out.estimate.params["리브"] == 4
    assert out.estimate.params["두께"] == pytest.approx(1.4916, abs=0.002)
    assert out.estimate.margin_pct == pytest.approx(12.6, abs=0.2)
    assert "DOE 에 없는 자리" in out.estimate.text


def test_공차_민감도는_이웃_설계점의_기울기다() -> None:
    out = frequency.evaluate(_study(), [TARGET, BAND])
    rows = {one.factor: one for one in _point(out, 13).sensitivity}
    slope = (_hz(2, 1.8, 2) - _hz(2, 1.4, 2)) / 0.4
    assert rows["두께"].hz_per_unit == pytest.approx(slope, rel=1e-3)
    # 허용 폭 ±39 Hz 에 해당하는 두께 폭.
    assert rows["두께"].equivalent == pytest.approx(39 / slope, rel=1e-3)
    assert "리브" in rows


def test_그_모드를_잇지_못한_점은_판정_보류이고_추적이_없으면_차례로_센다() -> None:
    out = frequency.evaluate(_study(drop=(13, 2)), [TARGET, BAND])
    point = _point(out, 13)
    assert point.verdict == "pending"
    assert "잇지 못했습니다" in str(point.targets[0].note)
    assert out.counts["pending"] == 1

    plain = frequency.evaluate(_study(tracked=False), [TARGET])
    assert plain.tracked is False and any("차례" in one for one in plain.notes)
    assert plain.tracks == [1, 2, 3, 4, 5]
    assert plain.crossings == [] and plain.estimate is None


def test_요구가_없으면_모두_판정_보류이고_그렇다고_말한다() -> None:
    out = frequency.evaluate(_study(), [])
    assert out.counts["pending"] == 25
    assert any("요구 조건이 없습니다" in one for one in out.notes)


def test_회피_대역의_상한은_하한보다_커야_한다() -> None:
    with pytest.raises(ValueError, match="상한이 하한보다"):
        FrequencyBand(low_hz=900, high_hz=700)
