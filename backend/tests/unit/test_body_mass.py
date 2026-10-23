"""바디마다의 질량 — **해석에서 지그와 부품은 같은 바디다**(2026-10-23).

강체 지그도 메시 · 질량 · 관성을 가지므로 전체 질량은 모델 전체다. 그래서 무엇이 설계 대상인지
고르지 않고 바디마다 적는다 — 3점 굽힘 시편 3.8 g 이 강재 롤러 · 노즈와 합쳐 40.8 g 으로만
보였다(MCP 데모). 설계점 비교는 「질량 · 시편」 열을 고른다.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.calculix.build import _masses_kg
from app.core.materials import mass_summary
from app.modules.simulations import analysis
from app.modules.simulations.schemas import StudyOut, StudyPointOut


def test_바디가_둘_이상이면_바디마다_적고_전체는_합이다() -> None:
    made = mass_summary({"시편": 0.003840, "롤러_1": 0.0123, "롤러_2": 0.0123})
    assert made["mass_kg"] == pytest.approx(0.02844)
    assert made["mass_by_body"] == {"시편": 0.00384, "롤러_1": 0.0123, "롤러_2": 0.0123}
    # 단품은 전체가 곧 그 바디다 — 같은 값을 두 번 적지 않는다.
    assert "mass_by_body" not in mass_summary({"전체": 0.5})
    # 못 쟀거나 0 이면 없는 값이다.
    assert mass_summary(None) == {"mass_kg": None}
    assert mass_summary({"전체": 0.0})["mass_kg"] is None


def test_CalculiX_는_파트마다_부피와_그_파트의_밀도로_잰다() -> None:
    pc = SimpleNamespace(bodies=["시편"], density_kg_m3=1200.0)
    steel = SimpleNamespace(bodies=["롤러_1", "노즈"], density_kg_m3=7850.0)
    mesh = SimpleNamespace(
        bodies=[
            SimpleNamespace(index=1, volume=3200.0),
            SimpleNamespace(index=2, volume=1570.8),
            SimpleNamespace(index=3, volume=1570.8),
        ]
    )
    found = _masses_kg([pc, steel], {"시편": 1, "롤러_1": 2, "노즈": 3}, mesh)  # type: ignore[list-item]
    assert found is not None
    assert found["시편"] == pytest.approx(0.00384)
    assert found["롤러_1"] == pytest.approx(0.01233078)
    # 메시에서 못 찾은 파트가 있으면 질량을 내지 않는다 — 틀린 질량은 맞는 침묵보다 나쁘다.
    assert _masses_kg([pc], {"시편": 9}, mesh) is None  # type: ignore[list-item]


def test_설계점_비교는_바디마다의_질량을_열로_고른다() -> None:
    points = [
        StudyPointOut(
            simulation_id=uuid.uuid4(),
            number=number,
            params={"두께": thickness},
            status="done",
            recipe="static",
            max_displacement_mm=1.0 / thickness,
            mass_kg=0.037 + 0.0012 * thickness,
            mass_by_body={"시편": 0.0012 * thickness, "롤러_1": 0.0123},
        )
        for number, thickness in ((1, 3.0), (2, 4.0), (3, 5.0))
    ]
    study = StudyOut(
        study_id="s", name="3점 굽힘", factors=["두께"], recipe="static", points=points
    )
    keys = [one.key for one in analysis.columns_of(study)]
    assert "mass:시편" in keys and "mass:롤러_1" in keys and "mass_kg" in keys
    found = analysis.analyze(study, result="mass:시편")
    # 시편만 보면 두께에 정비례(상관 1) — 전체 질량은 롤러에 묻혀 폭이 작게 보였다.
    assert found.sensitivity[0].factors[0].correlation == pytest.approx(1.0)
