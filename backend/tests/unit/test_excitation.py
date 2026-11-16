"""**가진 프로파일**(CompCore 2026-11-17) — 조화 응답 하중의 주파수별 배율 · 위상, 기저 가진의
절대 가속도.

솔버까지 도는 시험은 `tests/opensolver/test_calculix.py` 의 사인 스윕이다(손셈 39 g). 여기서는
읽기 ·
덱 줄 · 셈을 본다.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from app.core import conditions as condition_model
from app.core import excitation
from app.core import probes as core_probes
from app.core.calculix import deck

SWEEP = {
    "name": "X 사인 스윕",
    "type": "acceleration",
    "on": "",
    "cs": "global",
    "magnitude": 9806.65,
    "unit": "mm/s^2",
    "direction": [1, 0, 0],
    "frequency_table": [[100, 0.5], [800, 1], [2000, 1]],
    "phase": 0.0,
}


def _read(load: dict[str, Any], recipe: str = "harmonic") -> condition_model.Conditions:
    return condition_model.read({"conditions": {"loads": [load]}}, recipe=recipe)


def test_조화_하중의_주파수별_배율과_위상을_읽는다() -> None:
    got = _read({**SWEEP, "phase": 30})
    assert got.loads[0].frequency_table == ((100, 0.5), (800, 1), (2000, 1))
    assert got.loads[0].phase == 30
    # 옛 폴더에는 새 열쇠가 없다 — 없으면 배율 1 · 위상 0.
    plain = _read(
        {key: value for key, value in SWEEP.items() if key not in ("frequency_table", "phase")}
    )
    assert plain.loads[0].frequency_table is None and plain.loads[0].phase is None
    # 조화 응답이 아니면 쓰지 않는다(선응력 정적에서 배율을 걸 자리가 없다).
    assert _read(SWEEP, recipe="static").loads[0].frequency_table is None


@pytest.mark.parametrize(
    ("table", "why"),
    [
        ([[100, 0.5]], "두 줄 이상"),
        ([[800, 1], [100, 0.5]], "커지는 차례"),
        ([[100, -0.5], [800, 1]], "0 이상"),
        ([[100, "x"], [800, 1]], "[주파수, 배율]"),
    ],
)
def test_틀린_배율_표는_까닭을_달아_막는다(table: list[Any], why: str) -> None:
    got = _read({**SWEEP, "frequency_table": table})
    assert not got.loads
    assert why in got.refused[0].why


def test_배율은_주파수에_대해_선형_보간하고_범위를_덮어야_한다() -> None:
    table = ((100.0, 0.5), (800.0, 1.0), (2000.0, 1.0))
    # CompCore 손셈: 200 Hz 의 배율 0.5 + (200-100)/(800-100)·0.5 ≈ 0.571.
    assert condition_model.table_factor(table, 200) == pytest.approx(0.5714, abs=1e-4)
    assert condition_model.table_factor(table, 50) == 0.5, "표 밖은 끝값(ccx 와 같다)"
    assert condition_model.table_factor(None, 300) == 1.0
    assert condition_model.table_covers(table, 200, 2000)
    assert not condition_model.table_covers(table, 50, 2000)
    assert condition_model.table_covers(None, 0, 1e9)


def test_랜덤_진동의_PSD_는_다른_해석에서_쓰지_않고_알린다() -> None:
    psd = {
        "name": "X 랜덤",
        "type": "psd_acceleration",
        "on": "",
        "psd_table": [[20, 0.01], [2000, 0.007]],
    }
    got = _read(psd, recipe="modal")
    assert not got.loads and not got.refused
    assert "랜덤 진동" in got.skipped[0].why


def test_위상은_실수부_cos_와_허수부_sin_으로_나눈다() -> None:
    load = _read({**SWEEP, "phase": 30}).loads[0]
    parts = deck._phased(load)
    assert [case for _, case in parts] == ["", "LOAD CASE=2"]
    assert parts[0][0].magnitude == pytest.approx(9806.65 * math.cos(math.radians(30)))
    assert parts[1][0].magnitude == pytest.approx(9806.65 * math.sin(math.radians(30)))
    # 0 · 360 이면 그대로 하나, 90 이면 허수부만, 180 이면 방향을 뒤집는다.
    full_turn = deck._phased(_read({**SWEEP, "phase": 360}).loads[0])
    assert [(one.magnitude, case) for one, case in full_turn] == [(9806.65, "")]
    assert [case for _, case in deck._phased(_read({**SWEEP, "phase": 90}).loads[0])] == [
        "LOAD CASE=2"
    ]
    flipped, _ = deck._phased(_read({**SWEEP, "phase": 180}).loads[0])[0]
    assert flipped.direction == (-1, 0, 0) and flipped.magnitude == pytest.approx(9806.65)


def test_덱_줄에_배율_표와_허수부를_단다() -> None:
    rows = ["*DLOAD", "E1, GRAV, 9806.65, -1, 0, 0", "*CLOAD", "1, 1, 2.0"]
    assert deck._keyed(rows, ["AMPLITUDE=SEBAMP1", "LOAD CASE=2"]) == [
        "*DLOAD, AMPLITUDE=SEBAMP1, LOAD CASE=2",
        "E1, GRAV, 9806.65, -1, 0, 0",
        "*CLOAD, AMPLITUDE=SEBAMP1, LOAD CASE=2",
        "1, 1, 2.0",
    ]
    table = ((1.0, 0.1), (2.0, 0.2), (3.0, 0.3), (4.0, 0.4), (5.0, 0.5))
    assert deck._amplitude_lines("A", table) == [
        "*AMPLITUDE, NAME=A",
        "1, 0.1, 2, 0.2, 3, 0.3, 4, 0.4",
        "5, 0.5",
    ]


def test_기저_가진이면_측정점의_절대_가속도와_위상을_낸다() -> None:
    bases = excitation.bases(_read(SWEEP))
    assert bases == [
        excitation.Base((1.0, 0.0, 0.0), 9806.65, ((100, 0.5), (800, 1), (2000, 1)), 0.0)
    ]
    # 상대 변위가 0 이면 절대 가속도는 기저 그대로 — 200 Hz 의 배율 0.571 g.
    size, phase = excitation.response(200, [0, 0, 0], [0, 0, 0], bases) or (0, 0)
    assert size == pytest.approx(0.5714, abs=1e-4) and phase == pytest.approx(0)
    # 공진에서 상대 변위가 위상 -90° 로 크게 — 절대는 상대(ω²|u|)에 기저 1 g 가 직각으로
    # 더해진다.
    omega = 2 * math.pi * 1263
    u = 39 * excitation.G_MM_S2 / omega**2
    size, phase = excitation.response(1263, [0, 0, 0], [u, 0, 0], bases) or (0, 0)
    assert size == pytest.approx(math.hypot(39, 1), rel=1e-6)
    # 기저 가진이 없으면 -ω²·u — 힘으로 흔든 모델.
    size, _ = excitation.response(1263, [u, 0, 0], [0, 0, 0], []) or (0, 0)
    assert size == pytest.approx(39, rel=1e-6)
    assert excitation.amplitude_g(1263, u) == pytest.approx(39, rel=1e-6)
    # SI 로 적은 크기(m/s²)는 mm/s² 로 옮긴다.
    si = excitation.bases(_read({**SWEEP, "magnitude": 9.80665, "unit": "m/s^2"}))
    assert si[0].magnitude == pytest.approx(9806.65)
    assert excitation.read({excitation.KEY: [one.as_boundary() for one in bases]}) == bases


def test_측정점_봉우리에_가속도_봉우리와_위상이_실린다() -> None:
    spot = core_probes.Spot(name="끝", point=(0.0, 0.0, 90.0), node=7, distance_mm=0.0)
    points = [
        {
            "frequency_hz": 1000,
            "probes": {"끝": 0.001},
            "probes_accel_g": {"끝": 4.0},
            "probes_phase_deg": {"끝": -3.0},
        },
        {
            "frequency_hz": 1263,
            "probes": {"끝": 0.006},
            "probes_accel_g": {"끝": 39.0},
            "probes_phase_deg": {"끝": -88.5},
        },
        {
            "frequency_hz": 1300,
            "probes": {"끝": 0.005},
            "probes_accel_g": {"끝": 39.5},
            "probes_phase_deg": {"끝": -120.0},
        },
    ]
    line = core_probes.peaks([spot], points, unit="mm")[0]
    assert line["frequency_hz"] == 1263 and line["phase_deg"] == -88.5
    assert (line["acceleration_g"], line["acceleration_hz"]) == (39.5, 1300), (
        "가속도 봉우리는 따로 찾는다"
    )
