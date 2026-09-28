"""물성 읽기 — **CAD 가 보낸 값으로 도는가.**

지금까지는 사람이 넣은 한 벌을 설계점 전부에 썼다. 그래서 재료를 훑는 DOE 가 **이름만 다르고
결과가 똑같이** 나왔다 — 값이 안 나오는 게 아니라 그럴듯한 값이 나온다. 여기서 못 박는 것은
둘이다: 값이 제대로 들어오는가, 그리고 **못 읽을 때 조용히 넘어가지 않는가.**

값은 CompCore 의 환산 코드로 만든 것이다(`tests/fixtures/materials/README.txt`).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from app.core import materials, units

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CONVERTED = FIXTURES / "materials"
DOE = FIXTURES / "doe" / "재료훑기-7c1d3a44"


def _converted(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((CONVERTED / name).read_text(encoding="utf-8"))
    return loaded


def _point(number: int) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (DOE / "points" / f"p{number:04d}.json").read_text(encoding="utf-8")
    )
    return loaded


def _row(converted: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """조건 한 줄 — CompCore 가 보내는 모양(`ref` · `payload` · `converted`)."""
    return {
        "apply_to": ["전체"],
        "ref": {"source": "matnexus", "code": "M-000241", "name": "SS400"},
        "payload": {"record_name": "SS400"},
        "converted": converted,
        **extra,
    }


def _payload(row: dict[str, Any], system: str = "mm_n_tonne") -> dict[str, Any]:
    return {"conditions": {"units": {"system": system}, "materials": [row]}}


def test_CAD_가_환산한_값을_읽는다() -> None:
    """**정본 경로.** 등록 재료와 문헌은 출처가 다른데도 `converted` 가 한 모양이라, 받는
    쪽의 규칙은 하나다."""
    row = _row(_converted("등록재료-mm_n_tonne.json"))
    found = materials.read(_payload(row), units.MM_N_TONNE)

    assert len(found) == 1
    one = found[0]
    assert one.name == "SS400"
    assert math.isclose(one.youngs_modulus_pa, 206e9, rel_tol=1e-9)
    assert math.isclose(one.density_kg_m3, 7850.0, rel_tol=1e-9)
    assert one.poisson_ratio == 0.3
    # 온도 표에서 고른 점을 적어 둔다 — 「무슨 온도로 돌았나」 를 나중에 볼 수 있어야 한다.
    assert one.temperature_c == 22.0
    assert one.source == "converted"
    # 「전체」 는 모든 바디라는 뜻이다.
    assert one.every_body

    # 사람이 읽는 스펙으로 나온다 — 화면 · 명령 조각이 쓰는 모양.
    spec = one.spec()
    assert math.isclose(spec.youngs_modulus_gpa, 206.0, rel_tol=1e-9)
    assert math.isclose(spec.density_kg_m3, 7850.0, rel_tol=1e-9)


def test_어느_계로_와도_같은_값이_된다() -> None:
    """**단위는 값 곁의 이름으로 읽는다.** 같은 재료를 두 계로 보내면 같은 SI 값이어야 한다 —
    계를 믿고 「mm 계니까 MPa 겠지」 로 읽으면 SI 폴더에서 10⁶ 배 틀린다."""
    mm = materials.read(
        _payload(_row(_converted("등록재료-mm_n_tonne.json"))), units.MM_N_TONNE
    )
    si = materials.read(_payload(_row(_converted("등록재료-si.json")), system="si"), units.SI)
    assert math.isclose(mm[0].youngs_modulus_pa, si[0].youngs_modulus_pa, rel_tol=1e-9)
    assert math.isclose(mm[0].density_kg_m3, si[0].density_kg_m3, rel_tol=1e-9)


def test_문헌_물성도_같은_규칙으로_읽는다() -> None:
    """문헌 카탈로그는 원본의 모양이 다르지만(`values[]`), CompCore 가 `converted` 를 한 모양
    으로 내놓는다 — 밀도 · 푸아송비를 목록에서 끌어올려 준다."""
    found = materials.read(
        _payload(_row(_converted("문헌물성-mm_n_tonne.json"))), units.MM_N_TONNE
    )
    one = found[0]
    assert math.isclose(one.youngs_modulus_pa, 68.9e9, rel_tol=1e-9)
    assert math.isclose(one.density_kg_m3, 2700.0, rel_tol=1e-9)
    assert one.poisson_ratio == 0.33
    # 온도가 없는 값이다 — 없는 것을 22 °C 라고 적지 않는다.
    assert one.temperature_c is None
    # **등급은 값의 일부다** — B 등급으로 돌았다는 것을 사람이 알아야 한다.
    assert any("B" in note for note in one.notes)


def test_열쇠가_안_붙었으면_실패한다() -> None:
    """**항목 이름으로 짐작하지 않는다.** 「탄성계수」 같아 보이는 줄을 골라 쓰면 값은 나오고
    그것이 영률이 아닐 수 있다. CompCore 가 `missing_structural` 로 먼저 말해 준다."""
    row = _row(_converted("등록재료-열쇠없음.json"))
    with pytest.raises(materials.MaterialProblem) as caught:
        materials.read(_payload(row), units.MM_N_TONNE)
    assert caught.value.material == "SS400"
    assert "탄성계수" in caught.value.reason


def test_선언한_계와_환산한_계가_다르면_실패한다() -> None:
    """점 파일은 `units.system` 으로 「이 파일의 값은 이 계」 라고 말한다. 물성이 딴 계로
    환산돼 있으면 **어느 쪽이 맞는지 알 수 없다** — 그대로 쓰면 조용히 틀린다."""
    row = _row(_converted("등록재료-si.json"))  # SI 로 환산된 값을
    with pytest.raises(materials.MaterialProblem) as caught:
        materials.read(_payload(row), units.MM_N_TONNE)  # mm 계라고 선언한 파일에
    assert "si" in caught.value.reason and "mm_n_tonne" in caught.value.reason


def test_옛_폴더의_평평한_칸도_읽는다() -> None:
    """2026-09-24 에 내보낸 폴더는 `converted.youngs_modulus` 한 칸이다(열쇠도 단위 이름도
    없다). 디스크에 남아 있는 폴더를 못 읽으면 사람은 왜 안 되는지 알 수 없다."""
    payload = _point(1)
    found = materials.read(payload, units.declared_in(payload))
    assert math.isclose(found[0].youngs_modulus_pa, 206e9, rel_tol=1e-9)
    assert math.isclose(found[0].density_kg_m3, 7850.0, rel_tol=1e-9)

    second = materials.read(_point(2), units.MM_N_TONNE)
    assert math.isclose(second[0].youngs_modulus_pa, 68.9e9, rel_tol=1e-9)
    assert math.isclose(second[0].density_kg_m3, 2700.0, rel_tol=1e-9)
    # **두 점의 물성이 다르다** — 이것이 재료 DOE 가 뜻이 있으려면 있어야 하는 차이다.
    assert found[0].name != second[0].name


def test_환산값이_없으면_원본에서_읽는다() -> None:
    """대비 경로 — `payload` 에서 직접. 값과 단위를 떼지 않는 것이 전부다."""
    row = {
        "apply_to": ["전체"],
        "ref": {"name": "SS400"},
        "payload": {
            "record_name": "SS400",
            "density": 7850.0,
            "density_unit": "kg/m3",
            "poisson_ratio": 0.3,
            "declared_properties": [
                {
                    "item": "탄성계수",
                    "si_unit": "Pa",
                    "points": [
                        {"temperature_C": 22, "value_si": 206e9},
                        {"temperature_C": 300, "value_si": 180e9},
                    ],
                }
            ],
        },
    }
    one = materials.read(_payload(row), units.MM_N_TONNE)[0]
    assert one.source == "payload"
    # **상온 점을 고른다** — 300 °C 값으로 상온 공진을 풀면 5% 낮게 나온다.
    assert one.temperature_c == 22.0
    assert math.isclose(one.youngs_modulus_pa, 206e9, rel_tol=1e-9)
    assert any("원본" in note for note in one.notes)


def test_조건이_없으면_빈_목록이다() -> None:
    """형상만 온 폴더도 있다 — 그때는 사람이 화면에서 준 스펙으로 돈다(오류가 아니다)."""
    assert materials.read({}, units.SI) == []
    assert materials.read({"conditions": {"units": {"system": "si"}}}, units.SI) == []


def test_담아만_둔_재료는_건너뛴다() -> None:
    """CompCore 화면에서 목록에 담았을 뿐 아직 어느 파트에도 안 붙인 재료다(`apply_to: []`).
    그것을 전체에 붙이면 **사람이 고르지 않은 재료로** 푼다."""
    kept = _row(_converted("등록재료-mm_n_tonne.json"), apply_to=[])
    assert materials.read(_payload(kept), units.MM_N_TONNE) == []


def test_바디마다_다른_물성을_고른다() -> None:
    """조립은 파트마다 재료가 다르다. **이름으로 붙은 것이 「전체」 보다 먼저다.**"""
    plate = _row(_converted("등록재료-mm_n_tonne.json"), apply_to=["지그판"])
    everything = _row(_converted("문헌물성-mm_n_tonne.json"))
    found = materials.read(_payload(plate), units.MM_N_TONNE)
    both = materials.read(
        {
            "conditions": {
                "units": {"system": "mm_n_tonne"},
                "materials": [plate, everything],
            }
        },
        units.MM_N_TONNE,
    )
    assert found[0].bodies == ("지그판",)

    picked = materials.for_body(both, "지그판")
    assert picked is not None and picked.bodies == ("지그판",)
    # 이름이 안 붙은 바디는 「전체」 물성을 받는다.
    other = materials.for_body(both, "부품")
    assert other is not None and other.every_body
    # 둘 다 없으면 None — 부르는 쪽이 사람 스펙으로 갈지 정한다.
    assert materials.for_body([], "부품") is None
