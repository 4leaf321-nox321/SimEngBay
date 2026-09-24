"""단위계 — **선언을 읽는가, 그 계로 숫자를 적는가.**

여기서 지키는 것은 하나다: CAD 가 어느 계로 보내도 값이 맞게 들어간다. 틀리면 나오는 것이
오류가 아니라 **그럴듯한 값**이라서(고유진동수만 10³ 배 어긋난다) 시험으로 못 박는다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from app.core import units
from app.core.mechanical.build import material_commands
from app.core.spec import MaterialSpec

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "doe"
#: 조건(물성 · 단위 선언)이 실려 오는 폴더 — CompCore 의 내보내기 코드로 만든 것.
WITH_CONDITIONS = FIXTURES / "재료훑기-7c1d3a44"
#: 조건 없이 형상만 훑은 폴더.
GEOMETRY_ONLY = FIXTURES / "브래킷_두께훑기-3f9a2177"


def _point(folder: Path, number: int) -> dict[str, Any]:
    text = (folder / "points" / f"p{number:04d}.json").read_text(encoding="utf-8")
    loaded: dict[str, Any] = json.loads(text)
    return loaded


def test_CAD_의_선언을_읽는다() -> None:
    """**CompCore 기본은 `mm_n_tonne` 이다.** mm 로 만든 형상에 mm 계가 맞으니 그쪽이 바꿀
    이유가 없고, 그래서 받는 쪽이 읽어야 한다(2026-09-24 결정)."""
    system = units.declared_in(_point(WITH_CONDITIONS, 1))
    assert system is units.MM_N_TONNE
    assert system.mechanical == "StandardNMMton"
    # `.dat` 의 숫자가 읽히는 계는 표시계가 아니라 이쪽이다(실측).
    assert system.solver == "ConsistentNMM"


def test_선언이_없으면_SI_로_본다() -> None:
    """조건 없이 형상만 오는 폴더도 있다 — 그때 스펙은 사람이 화면에서 준 것이고
    SI 계열이다(`youngs_modulus_gpa` · `density_kg_m3`)."""
    assert units.declared_in(_point(GEOMETRY_ONLY, 1)) is units.SI
    assert units.declared_in({}) is units.SI
    assert units.declared_in({"conditions": {"units": {}}}) is units.SI


def test_모르는_선언은_거절한다() -> None:
    """**추측하지 않는다.** 「아마 SI 겠지」 로 돌리면 틀렸을 때 값이 그럴듯하게 나온다 —
    그 상태는 고유진동수를 보고도 알 수 없다."""
    with pytest.raises(units.UnknownUnitSystem) as caught:
        units.declared_in({"conditions": {"units": {"system": "cgs_dyne"}}})
    assert caught.value.declared == "cgs_dyne"
    # 아는 것을 말해 준다 — 사람이 다음에 무엇을 할지 알 수 있어야 한다.
    assert "mm_n_tonne" in str(caught.value)


def test_CAD_가_환산한_값과_숫자까지_맞는다() -> None:
    """**남의 환산과 우리 환산이 같은가.** CompCore 는 `payload`(SI) 옆에 그 계로 환산한
    `converted` 를 함께 보낸다 — 우리 계수가 틀리면 여기서 갈린다.

    `payload.density` 는 MatNexus 화면 표시값이라 단위가 `density_unit` 에 따로 있다.
    **SI 로 읽을 칸은 `density_si` 다** — 「전부 SI」 로 가정하면 밀도는 맞고 탄성계수가
    10⁶ 배 틀린다(그쪽이 겪은 사고).
    """
    for number in (1, 2):
        payload = _point(WITH_CONDITIONS, number)
        system = units.declared_in(payload)
        material = payload["conditions"]["materials"][0]
        source, converted = material["payload"], material["converted"]
        modulus_pa = source["declared_properties"][0]["points"][0]["value_si"]

        assert math.isclose(
            system.stress(modulus_pa), converted["youngs_modulus"], rel_tol=1e-9
        )
        assert math.isclose(
            system.density(source["density_si"]), converted["density"], rel_tol=1e-9
        )


def test_환산은_되돌릴_수_있다() -> None:
    """강 7,850 kg/m³ = 7.85e-9 t/mm³ · 200 GPa = 200,000 MPa."""
    system = units.MM_N_TONNE
    assert math.isclose(system.density(7850.0), 7.85e-9, rel_tol=1e-12)
    assert math.isclose(system.stress(200e9), 2.0e5, rel_tol=1e-12)
    # 부피는 거꾸로 — 활성계에서 읽어 SI 로 낸다(질량이 kg 으로 나와야 한다).
    assert math.isclose(system.volume_m3(113395.8), 1.133958e-4, rel_tol=1e-9)
    assert units.SI.volume_m3(1.5) == 1.5


MATERIAL = MaterialSpec(
    name="SS400", youngs_modulus_gpa=200, poisson_ratio=0.3, density_kg_m3=7850
)


def test_물성_명령을_세션의_계로_적는다() -> None:
    """**명령 조각의 숫자에는 단위가 없다.** 세션이 mm 계인데 Pa 로 적으면 10⁶ 배 틀린 값이
    아무 오류 없이 들어간다 — 그래서 조각을 만드는 자리에서 환산한다."""
    mks = material_commands(MATERIAL, units.SI)
    assert "MP,EX,matid,2e+11" in mks
    assert "MP,DENS,matid,7850" in mks

    nmm = material_commands(MATERIAL, units.MM_N_TONNE)
    assert "MP,EX,matid,200000" in nmm
    assert "MP,DENS,matid,7.85e-09" in nmm
    # 어느 계로 적었는지 조각에 남는다 — `.dat` 를 열어 보는 사람이 알아야 한다.
    assert "mm_n_tonne" in nmm
    assert "MP,PRXY,matid,0.3" in nmm
