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


CONDITION_FOLDERS = FIXTURES / "doe"


def test_조건_픽스처의_물성에는_탄성계수가_없다() -> None:
    """**CompCore 가 2026-09-28 에 준 조건 폴더 두 벌의 실제 상태다.**

    고른 MatNexus 줄(SECC 선언물성 · AL5052 데모)에 탄성계수가 없어서 `converted` 에
    `missing_structural: ["탄성계수"]` 가 실려 온다. 그러면 선형 탄성으로 풀 수 없다 —
    **그때 조용히 넘어가면** Mechanical 이 기본값(구조용 강)으로 풀고, 알루미늄 블록이
    강으로 풀린 결과가 그럴듯하게 나온다.

    이 시험은 「지금 이 폴더로는 CAD 물성으로 못 돈다」 를 못 박는다 — 그쪽이 탄성계수가 있는
    재료로 폴더를 다시 내보내면 여기서 먼저 알려 준다(그때 이 시험을 고친다).
    """
    for name in ("조건_두바디_두재료", "조건_원통_SI"):
        payload = json.loads(
            (CONDITION_FOLDERS / name / "points" / "p0001.json").read_text(encoding="utf-8")
        )
        with pytest.raises(materials.MaterialProblem) as caught:
            materials.read(payload, units.declared_in(payload))
        assert "탄성계수" in caught.value.reason

        # 다만 **밀도 · 푸아송비는 왔다** — 빠진 것이 무엇인지 말할 수 있어야 한다.
        first = payload["conditions"]["materials"][0]["converted"]
        assert first["density"] > 0
        assert first["poisson_ratio"] > 0
        assert first["missing_structural"] == ["탄성계수"]


def test_SI_로_내보낸_폴더도_같은_규칙으로_읽는다() -> None:
    """`조건_원통_SI` 는 내보내기 계가 SI 다 — 값은 Pa · kg/m³ 로 온다.

    우리 리더는 값 곁의 단위 이름을 읽으므로 계가 달라도 규칙이 하나다. 탄성계수가 없어 전체는
    거절되지만, **밀도만은 두 계에서 같은 kg/m³ 가 되어야** 한다(2,680).
    """
    payload = json.loads(
        (CONDITION_FOLDERS / "조건_원통_SI" / "points" / "p0001.json").read_text(
            encoding="utf-8"
        )
    )
    assert units.declared_in(payload) is units.SI
    converted = payload["conditions"]["materials"][0]["converted"]
    assert converted["density_unit"] == "kg/m3"
    assert units.density_from(converted["density"], converted["density_unit"]) == 2680.0

    # mm 계로 내보낸 같은 재료(두바디 폴더의 블록)와 값이 맞는다.
    other = json.loads(
        (CONDITION_FOLDERS / "조건_두바디_두재료" / "points" / "p0001.json").read_text(
            encoding="utf-8"
        )
    )
    block = other["conditions"]["materials"][1]["converted"]
    assert block["density_unit"] == "tonne/mm3"
    assert math.isclose(
        units.density_from(block["density"], block["density_unit"]), 2680.0, rel_tol=1e-9
    )


SWEEP = CONDITION_FOLDERS / "조건_재료훑기"


def _sweep_point(number: int) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (SWEEP / "points" / f"p{number:04d}.json").read_text(encoding="utf-8")
    )
    return loaded


def test_재료_훑기는_점마다_바디_물성이_바뀐다() -> None:
    """**CompCore 가 재료도 DOE 로 훑는다**(2026-09-29). 설계점마다 바디에 붙는 재료가
    달라지고, 형상은 하나를 나눠 쓴다.

    폴더의 물성에는 탄성계수가 없어(그쪽이 고른 MatNexus 줄의 한계) 값이 있는 `converted` 를
    바꿔 끼워 **붙는 자리**만 본다 — 값의 모양은 CompCore 의 환산 코드가 낸 그대로다.
    """
    steel = _converted("등록재료-mm_n_tonne.json")
    aluminium = _converted("문헌물성-mm_n_tonne.json")

    def with_values(payload: dict[str, Any]) -> dict[str, Any]:
        for row in payload["conditions"]["materials"]:
            name = row["ref"]["name"]
            row["converted"] = aluminium if "AL" in name.upper() else steel
        return payload

    first = materials.read(with_values(_sweep_point(1)), units.MM_N_TONNE)
    # 1번 점: 받침판은 강, 블록은 알루미늄 — 바디마다 다른 재료.
    plate = materials.for_body(first, "받침판")
    block = materials.for_body(first, "블록")
    assert plate is not None and block is not None
    assert math.isclose(plate.youngs_modulus_pa, 206e9, rel_tol=1e-9)
    assert math.isclose(block.youngs_modulus_pa, 68.9e9, rel_tol=1e-9)

    second = materials.read(with_values(_sweep_point(2)), units.MM_N_TONNE)
    # 2번 점: 한 재료가 **두 바디를 함께** 가리킨다(`apply_to: ["받침판", "블록"]`).
    assert len(second) == 1
    assert set(second[0].bodies) == {"받침판", "블록"}
    for body in ("받침판", "블록"):
        picked = materials.for_body(second, body)
        assert picked is not None
        assert math.isclose(picked.youngs_modulus_pa, 206e9, rel_tol=1e-9)
    # **담아만 둔 재료는 건너뛴다** — 2번 점의 알루미늄이 `apply_to: []` 로 온다.
    assert all(one.bodies for one in second)


CONDITION_SWEEP = CONDITION_FOLDERS / "조건_조건훑기"


def test_물성_배율이_점마다_반영된다() -> None:
    """**이 폴더는 값이 다 들어 있다**(탄성계수 포함) — 배율로 훑으려면 그 값이 있어야 한다.

    받침판은 그대로고 블록만 0.9 · 1.1 로 바뀐다. 우리가 `converted` 를 읽으므로 배율은 이미
    값에 반영돼 온다 — **우리가 다시 곱하지 않는다**(두 번 곱하면 조용히 틀린다).
    """
    found = {}
    for number in (1, 2):
        payload = json.loads(
            (CONDITION_SWEEP / "points" / f"p{number:04d}.json").read_text(encoding="utf-8")
        )
        found[number] = materials.read(payload, units.declared_in(payload))

    for number, rows in found.items():
        plate = materials.for_body(rows, "받침판")
        assert plate is not None, f"p{number} 의 받침판 물성이 없다"
        # 받침판은 배율 대상이 아니다 — 두 점에서 같은 값이어야 한다.
        assert math.isclose(plate.youngs_modulus_pa, 205e9, rel_tol=1e-9)

    low = materials.for_body(found[1], "블록")
    high = materials.for_body(found[2], "블록")
    assert low is not None and high is not None
    assert math.isclose(low.youngs_modulus_pa, 63.27e9, rel_tol=1e-9)
    assert math.isclose(high.youngs_modulus_pa, 77.33e9, rel_tol=1e-9)
    # 밀도는 배율 대상이 아니다 — 질량이 같아야 두 점을 견줄 수 있다.
    assert math.isclose(low.density_kg_m3, high.density_kg_m3, rel_tol=1e-9)
