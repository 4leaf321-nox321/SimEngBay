"""**랜덤 진동**(CompCore 2026-11-17, 가진 프로파일) — PSD 읽기 · 셈 · 설정 합치기.

솔버까지 도는 시험은 `tests/opensolver/test_calculix.py` 다(조건_랜덤진동 기둥 끝 36.7 g, 조화
응답과 같은 전달). 여기서는 PSD 표 · 모드 중첩 셈 · 조건 · 스펙을 본다.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core import conditions as condition_model
from app.core import random_vibration as random_model
from app.core import values as core_values
from app.core.calculix import tables
from app.core.modes import search as mode_search
from app.core.spec import RandomSpec, parse_spec

#: CompCore 조건_랜덤진동의 PSD — 20 ~ 2,000 Hz, Grms 6.058(CompCore 손셈).
TABLE = ((20.0, 0.01), (80.0, 0.04), (350.0, 0.04), (2000.0, 0.007))
PSD = {
    "name": "X 랜덤",
    "type": "psd_acceleration",
    "on": "",
    "cs": "global",
    "unit": "g^2/Hz",
    "direction": [1, 0, 0],
    "psd_table": [list(one) for one in TABLE],
    "grms": 6.058182092907139,
}
DAT = Path(__file__).resolve().parents[1] / "fixtures" / "calculix" / "cantilever_modal.dat"


def _read(
    loads: list[dict[str, Any]], analysis: dict[str, Any] | None = None, recipe: str = "random"
) -> condition_model.Conditions:
    return condition_model.read(
        {
            "conditions": {
                "loads": loads,
                "analysis": {"type": recipe, **(analysis or {})},
            }
        },
        recipe=recipe,
    )


def test_PSD_는_로그_로그로_보간하고_표_밖은_0() -> None:
    assert random_model.psd_at(TABLE, 80) == 0.04
    # 350 ~ 2,000 Hz 는 기울기 -1(0.04 → 0.007, 350/2000 의 비와 같다):
    # 1,263 Hz 는 0.04·350/1263.
    assert random_model.psd_at(TABLE, 1263) == pytest.approx(0.04 * 350 / 1263, rel=1e-9)
    # 20 ~ 80 Hz 는 +1 — 40 Hz 는 0.02.
    assert random_model.psd_at(TABLE, 40) == pytest.approx(0.02, rel=1e-9)
    assert random_model.psd_at(TABLE, 19.9) == 0.0
    assert random_model.psd_at(TABLE, 2000.1) == 0.0


def test_입력_Grms_는_CompCore_손셈과_같다() -> None:
    assert random_model.grms(TABLE) == pytest.approx(6.058182092907139, rel=1e-12)
    # 자르면 그 범위만 — 80 ~ 350 Hz 평탄 구간은 √(0.04 · 270).
    assert random_model.grms(TABLE, 80, 350) == pytest.approx(math.sqrt(0.04 * 270))


def _single() -> tuple[random_model.Modes, random_model.Shake]:
    """한 자유도 — 500 Hz, 질량 1, 참여 1, 평탄한 PSD 0.01 g²/Hz."""
    shake = random_model.Shake("X", (1.0, 0.0, 0.0), ((10.0, 0.01), (5000.0, 0.01)))
    return random_model.Modes((500.0,), {"X": (1.0,)}), shake


@pytest.mark.parametrize("damping", [0.01, 0.02, 0.05])
def test_한_자유도는_촘촘한_적분과_0_1_퍼센트_안에서_같고_Miles_와_맞는다(
    damping: float,
) -> None:
    modes, shake = _single()
    grid = random_model.grid(10, 5000, [500.0], damping)
    got = random_model.at_point([[1.0, 0.0, 0.0]], modes, [shake], grid, damping)
    dense = [10 * 500 ** (at / 100_000) for at in range(100_001)]
    exact = random_model.at_point([[1.0, 0.0, 0.0]], modes, [shake], dense, damping)
    assert got.accel_grms == pytest.approx(exact.accel_grms, rel=1e-3)
    assert got.displacement_mm == pytest.approx(exact.displacement_mm, rel=1e-3)
    # Miles: √(π/2 · fₙ · Q · S) — 감쇠가 작을수록 잘 맞는다.
    miles = math.sqrt(math.pi / 2 * 500 / (2 * damping) * 0.01)
    assert got.accel_grms == pytest.approx(miles, rel=0.01)
    assert len(grid) < 600, "격자가 너무 크면 큰 모델에서 느리다"


def test_무관한_가진은_제곱으로_더하고_절점_장은_측정점과_같다() -> None:
    naturals = (300.0, 900.0)
    shapes = [
        {1: [1.0, 0.2, 0.0], 2: [0.5, 0.0, 0.1]},
        {1: [0.0, 1.0, 0.3], 2: [0.2, 0.4, 0.0]},
    ]
    factors = {1: [0.8, 0.1, 0.0], 2: [0.05, 0.9, 0.0]}
    x = random_model.Shake("X", (1.0, 0.0, 0.0), TABLE)
    y = random_model.Shake("Y", (0.0, 1.0, 0.0), TABLE)
    grid = random_model.grid(20, 2000, naturals, 0.03, [hz for hz, _ in TABLE])
    both = random_model.gather(naturals, factors, [x, y])
    at = [shapes[0][1], shapes[1][1]]
    joined = random_model.at_point(at, both, [x, y], grid, 0.03)
    alone = [
        random_model.at_point(
            at, random_model.gather(naturals, factors, [one]), [one], grid, 0.03
        )
        for one in (x, y)
    ]
    assert joined.accel_grms**2 == pytest.approx(sum(one.accel_grms**2 for one in alone))
    # 절점 장(결합 행렬)은 측정점 셈과 같은 1σ 변위를 낸다.
    matrix = random_model.couplings(both, [x, y], grid, 0.03)
    field = random_model.field(shapes, matrix, [1, 2])
    assert field[1] == pytest.approx(joined.displacement_mm, rel=1e-9)


def test_조화_응답과_같은_전달을_쓴다() -> None:
    """1 g 기저 가진의 절대 가속도 = -ω²·u(상대)/g + 1. 공진에서 Q 배(위상 -90°)."""
    u, accel = random_model.transfer([[1.0, 0.0, 0.0]], [1.0], [500.0], (1, 0, 0), 500.0, 0.02)
    assert abs(accel[0]) == pytest.approx(math.hypot(1 / (2 * 0.02), 1), rel=1e-9)
    assert u[0].imag > 0 and abs(u[0].real) < 1e-12 * abs(u[0])
    # 아주 낮은 주파수 — 끝이 기저를 그대로 따라간다.
    _, slow = random_model.transfer([[1.0, 0.0, 0.0]], [1.0], [500.0], (1, 0, 0), 1.0, 0.02)
    assert abs(slow[0]) == pytest.approx(1, abs=1e-5)


def test_참여계수를_읽는다() -> None:
    factors = tables.participation_factors(DAT.read_text(encoding="utf-8"))
    assert len(factors) == 10 and len(factors[1]) == 6
    assert tables.total_masses(DAT.read_text(encoding="utf-8"))[0] > 0


def test_랜덤_진동은_PSD_를_가진으로_읽고_다른_하중은_넘긴다() -> None:
    force = {
        "name": "끝 힘",
        "type": "force",
        "on": "끝",
        "magnitude": 10,
        "direction": [1, 0, 0],
    }
    got = _read([PSD, force])
    assert got.psd == [
        condition_model.Psd(
            name="X 랜덤",
            table=TABLE,
            direction=(1.0, 0.0, 0.0),
            grms=6.058182092907139,
        )
    ]
    assert not got.loads, "선응력이 아니면 다른 하중은 정적 단계가 없다"
    assert "PSD 로만" in next(one.why for one in got.skipped if "끝 힘" in one.what)
    assert not got.prestressed
    # 선응력을 켜면 다른 하중은 앞 정적 단계에 — PSD 는 여전히 가진이다.
    pre = _read([PSD, force], {"prestressed": True})
    assert [one.name for one in pre.loads] == ["끝 힘"] and len(pre.psd) == 1


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"unit": "(m/s^2)^2/Hz"}, "g^2/Hz 만"),
        ({"on": "바닥"}, "한 영역"),
        ({"direction": [0, 0, 0]}, "방향"),
        ({"psd_table": [[20, 0.01]]}, "두 줄 이상"),
        ({"psd_table": [[20, 0.01], [10, 0.02]]}, "커지는 차례"),
        ({"psd_table": [[20, 0.0], [100, 0.02]]}, "0 보다 커야"),
        ({"psd_table": None}, "없습니다"),
    ],
)
def test_못_쓰는_PSD_는_까닭을_달아_막는다(change: dict[str, Any], why: str) -> None:
    got = _read([{**PSD, **change}])
    assert not got.psd
    assert why in got.refused[0].why


def test_가진_대역은_PSD_표고_CAD_범위는_모드를_찾을_범위다() -> None:
    """CompCore 계약(2026-11-17 답): 랜덤의 `frequency_range` 는 **모달 단계의 찾을 범위**다.
    가진 대역은 PSD 표가 정하므로 그 범위로 PSD 를 자르지 않는다."""
    given = _read([PSD], {"damping_ratio": 0.03, "frequency_range": [100, 1000]})
    plan, refused = random_model.plan(given, damping_ratio=0.02)
    assert not refused and plan is not None
    assert (plan.low, plan.high) == (20, 2000), "CAD 범위로 PSD 를 자르지 않는다"
    assert plan.damping_ratio == 0.03, "CAD 감쇠비가 먼저다"
    assert random_model.read({random_model.KEY: plan.as_boundary()}) == plan
    # 찾을 범위는 모달과 같은 자리에서 — CAD 가 먼저, 없으면 스펙.
    spec = parse_spec({"recipe": "random", "modes": 6, "frequency_range_hz": [10, 500]})
    assert isinstance(spec, RandomSpec)
    searched = mode_search.mode_search(spec, given)
    assert searched is not None
    assert searched == mode_search.ModeSearch(100, 1000, 6, "cad")
    assert mode_search.mode_search(spec, _read([PSD])) == mode_search.ModeSearch(
        10, 500, 6, "spec"
    )
    bare = parse_spec({"recipe": "random"})
    assert isinstance(bare, RandomSpec) and mode_search.mode_search(bare, _read([PSD])) is None
    # 조화로 적은 범위(훑을 범위)는 찾을 범위가 아니다.
    harmonic = _read([PSD], {"frequency_range": [100, 1000]}, recipe="harmonic")
    assert mode_search.cad_range(harmonic) is None
    # 가진 없음 · 없는 좌표계는 막는다.
    _, refused = random_model.plan(_read([]), damping_ratio=0.02)
    assert "하나도 없습니다" in refused[0].why
    _, refused = random_model.plan(_read([{**PSD, "cs": "기울인 계"}]), damping_ratio=0.02)
    assert "기울인 계" in refused[0].why


def test_다른_해석에서는_PSD_를_쓰지_않고_랜덤에서는_가진으로() -> None:
    assert not _read([PSD], recipe="modal").psd
    assert _read([PSD], recipe="harmonic").skipped[0].what.endswith("(가속도 PSD)")


def test_랜덤_진동은_아직_CalculiX_로만() -> None:
    assert parse_spec({"recipe": "random"}).solver == "calculix"
    with pytest.raises(ValidationError, match="CalculiX 로만"):
        parse_spec({"recipe": "random", "solver": "ansys"})
    with pytest.raises(ValidationError, match="찾을 주파수 범위는 0 ≤ 하한 < 상한"):
        parse_spec({"recipe": "random", "frequency_range_hz": [500, 100]})


def test_견줄_값은_1σ_변위와_측정점_가속도() -> None:
    found = core_values.read(
        {
            "recipe": "random",
            "max_displacement": {"value_mm": 0.0058, "node": 358},
            "probes": [
                {
                    "name": "측정점",
                    "value": 36.7,
                    "unit": "g",
                    "displacement_1sigma_mm": 0.0058,
                }
            ],
        }
    )
    assert found.max_displacement_mm == 0.0058
    assert found.probe_grms == {"측정점": 36.7}
    assert found.probes_mm == {"측정점": 0.0058}


def test_잔여_벡터는_빠진_모드의_정적_몫을_채우고_절점_장도_그것을_본다() -> None:
    """준정적 부품(고유진동수 ≫ 가진 대역) — 모드 하나가 정적 변위의 절반만 낸다고 하자. 잔여
    벡터를 더하면 낮은 주파수에서 응답이 **정적 해 그대로**다.

    절점 장은 모드를 몫으로 거른다 — 몫을 대각값만으로 보면 질량 정규화 형상(수백)과 mm 형상인
    잔여 벡터의 단위가 달라 진짜 모드가 다 빠졌다(실측 2026-11-17, 시험_랜덤진동 -16 %)."""
    natural = 60_000.0
    phi = 300.0  # 질량 정규화 형상은 크다(질량이 t 단위라)
    gamma = 1e-4
    static_by_mode = phi * gamma * random_model.modal_gain(natural, 0.0, 0.0).real
    shake = random_model.Shake("Z", (0.0, 0.0, 1.0), TABLE)
    modes = random_model.Modes((natural,), {"Z": (gamma,)})
    shapes = [{1: [0.0, 0.0, phi], 2: [0.0, 0.0, phi / 2]}]
    statics = [{1: [0.0, 0.0, 2 * static_by_mode], 2: [0.0, 0.0, static_by_mode]}]
    joined, used = random_model.with_residual(modes, shapes, statics, [shake])
    assert math.isinf(joined.naturals[-1]) and joined.participation["Z"] == (gamma, 1.0)
    u, _ = random_model.transfer(
        [one[1] for one in used],
        joined.participation["Z"],
        joined.naturals,
        (0, 0, 1),
        20.0,
        0.02,
    )
    assert u[2].real == pytest.approx(2 * static_by_mode, rel=1e-6)
    grid = random_model.grid(20, 2000, joined.naturals, 0.02, [hz for hz, _ in TABLE])
    point = random_model.at_point([one[1] for one in used], joined, [shake], grid, 0.02)
    # 준정적 — 1σ 변위 = 1 g 정적 변위 x Grms(CompCore 손셈의 꼴).
    assert point.displacement_mm == pytest.approx(
        abs(2 * static_by_mode) * random_model.grms(TABLE), rel=1e-3
    )
    matrix = random_model.couplings(joined, [shake], grid, 0.02)
    assert random_model.field(used, matrix, [1])[1] == pytest.approx(
        point.displacement_mm, rel=1e-9
    )
