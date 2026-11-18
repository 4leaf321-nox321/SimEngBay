"""**단위가 어긋났는가** — 덱에 쓴 물성 · 솔버가 셈한 질량 · 형상 크기(2026-11-17).

운영에서 1차 탄성이 1000배로 나왔고 질량이 mg 이었다. 고유진동수는 √(탄성계수 / 밀도) /
길이라, 길이 · 탄성계수 · 밀도 중 하나가 10³ · 10⁶ 배 어긋나면 **오류 없이** 그럴듯하게
틀린다. 셋을 결과 요약에서 가릴 수 있게 한다:

- `deck_materials` — 덱에 실제로 쓴 탄성계수(GPa) · 밀도(kg/m³)와 그 바디.
- `solver_mass_kg` · `mass_warning` — ccx 가 덱으로 셈한 질량(`*EL PRINT … EMAS`)과 형상 부피 x
  밀도의 비교.
- `size_warning` — gmsh 가 STEP 을 읽어 잰 부피와 CompCore `bodies[].volume` 의 비교.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from app.core.bodies import BodyRecord
from app.core.calculix import deck, tables

# 패키지가 같은 이름의 함수(`build` · `solve`)를 내보내 모듈은 이렇게 꺼낸다.
build = importlib.import_module("app.core.calculix.build")
solve = importlib.import_module("app.core.calculix.solve")

DAT = """
 total mass for set EMASS and time  0.1000000E+01

        1.262566E-04

 total mass moment of inertia (xx,yy,zz,xy,xz,yz) for set EMASS and time  0.1000000E+01
"""


class _Mesh:
    def __init__(self, volumes: dict[int, float]) -> None:
        self.bodies = [
            BodyRecord(index=k, volume=v, centroid=(0, 0, 0)) for k, v in volumes.items()
        ]


def test_솔버가_셈한_질량을_dat_에서_읽는다() -> None:
    assert tables.model_mass(DAT) == 1.262566e-4
    assert tables.model_mass("no mass here") is None


def test_덱은_첫_단계에_솔리드_쉘_묶음의_질량을_찍는다() -> None:
    lines = [
        "*ELEMENT, TYPE=C3D10, ELSET=E1",
        "1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10",
        "*ELEMENT, TYPE=S6, ELSET=SHELL1",
        "*ELEMENT, TYPE=SPRINGA, ELSET=SPRING1",
        "*STEP",
        "*FREQUENCY, SOLVER=SPOOLES",
        "6",
        "*END STEP",
        "*STEP",
        "*STATIC",
        "*END STEP",
    ]
    out = deck._with_mass_print(lines)
    assert out[out.index("*ELSET, ELSET=EMASS") + 1] == "E1, SHELL1", "스프링은 질량이 없다"
    first_end = out.index("*END STEP")
    assert out[first_end - 2 : first_end] == ["*EL PRINT, ELSET=EMASS, TOTALS=ONLY", "EMAS"]
    assert out.count("EMAS") == 1, "첫 단계에만"
    assert deck._with_mass_print(out) == out, "두 번 넣지 않는다"


def test_덱에_쓴_물성을_바디_이름과_함께_적고_같은_값은_묶는다() -> None:
    text = "\n".join(
        [
            "*MATERIAL, NAME=M1",
            "*ELASTIC",
            "205000, 0.3",
            "*DENSITY",
            "7.85e-09",
            "*SOLID SECTION, ELSET=E1, MATERIAL=M1",
            "*MATERIAL, NAME=M2",
            "*ELASTIC",
            "205000, 0.3",
            "*DENSITY",
            "7.85e-09",
            "*SOLID SECTION, ELSET=E2, MATERIAL=M2",
            "*MATERIAL, NAME=M3",
            "*ELASTIC",
            "2.05e+11, 0.3",
            "*DENSITY",
            "7.85e-09",
            "*SOLID SECTION, ELSET=E3, MATERIAL=M3",
        ]
    )
    shown = build._deck_materials(text, {"받침": 1, "기둥": 2, "덮개": 3}, [])
    # 덮개는 Pa 값을 MPa 칸에 넣은 꼴 — 10⁶ 배가 그대로 보인다.
    assert shown == (
        "E 205 GPa · 밀도 7,850 kg/m³ (받침, 기둥) · E 2.05e+08 GPa · 밀도 7,850 kg/m³ (덮개)"
    )


def test_형상_부피가_CAD_와_다르면_적고_길이_단위면_그렇게_말한다() -> None:
    topology = {
        "bodies": [
            {"name": "판", "kind": "solid", "volume": 64000.0},
            {"name": "시트", "kind": "sheet", "volume": 0.0},
            {"name": "뺀 것", "kind": "solid", "volume": 10.0},
        ]
    }
    same = build._size_warning(topology, {"판": 1}, _Mesh({1: 64000.0}), skip={"뺀 것"})
    assert same is None
    # STEP 의 m 를 mm 로 읽은 꼴 — 부피 10⁻⁹ 배, 길이 10⁻³ 배.
    unit = build._size_warning(topology, {"판": 1}, _Mesh({1: 6.4e-5}), skip={"뺀 것"})
    assert unit is not None and "(길이 단위)" in unit and "길이 0.001 배" in unit
    mild = build._size_warning(topology, {"판": 1}, _Mesh({1: 62000.0}), skip={"뺀 것"})
    assert mild is not None and "1 % 넘게" in mild and "길이 단위" not in mild
    # 바디 하나 · 물성 하나면 짝짓기가 실패해도 푼다 — 전체 부피끼리 견준다.
    whole = build._size_warning(topology, {"solid1": 1}, _Mesh({1: 6.4e-5}), skip={"뺀 것"})
    assert whole is not None and "「전체」" in whole and "(길이 단위)" in whole


def test_솔버_질량이_형상_부피_x_밀도와_어긋나면_적는다(tmp_path: Path) -> None:
    (tmp_path / solve.DATA_NAME).write_text(DAT, encoding="utf-8")
    (tmp_path / solve.BOUNDARY_NAME).write_text(
        json.dumps({"mass_kg": 0.1262566}), encoding="utf-8"
    )
    assert solve._mass_check(tmp_path) == {"solver_mass_kg": 0.126257}
    # 덱의 밀도가 10⁶ 배 작게 들어간 꼴.
    (tmp_path / solve.BOUNDARY_NAME).write_text(
        json.dumps({"mass_kg": 126256.6}), encoding="utf-8"
    )
    said = solve._mass_check(tmp_path)
    assert said["solver_mass_kg"] == 0.126257
    assert "1e-06 배" in str(said["mass_warning"])


def test_Ansys_는_MAPDL_의_전체_질량을_세션_단위계로_옮겨_견준다(tmp_path: Path) -> None:
    """`solve.out` 의 `PRECISE MASS SUMMARY` — mm · N · t 세션이면 톤이다(실측 0.52920E-03).
    단위계를 모르는 옛 경계 파일이면 옮기지 않는다(SI 로 짐작하면 1000배 틀린다)."""
    from app.core import units
    from app.core.solve import mapdl

    log = "   TOTAL MASS = 0.52920E-03\n     The mass principal axes coincide"
    assert units.MM_N_TONNE.mass_kg(0.5292e-3) == 0.5292
    assert units.SI.mass_kg(0.5292) == 0.5292
    (tmp_path / "boundary.json").write_text(
        json.dumps({"unit_system": "mm_n_tonne", "mass_kg": 0.5292}), encoding="utf-8"
    )
    assert mapdl.mass_summary(tmp_path, log) == {"solver_mass_kg": 0.5292}
    (tmp_path / "boundary.json").write_text(
        json.dumps({"unit_system": "mm_n_tonne", "mass_kg": 529.2}), encoding="utf-8"
    )
    assert "0.001 배" in str(mapdl.mass_summary(tmp_path, log)["mass_warning"])
    (tmp_path / "boundary.json").write_text(json.dumps({"mass_kg": 0.5292}), encoding="utf-8")
    assert mapdl.mass_summary(tmp_path, log) == {}


def test_Ansys_랜덤_덱은_작업_폴더에서_풀리고_g_는_표준_중력이다() -> None:
    """Mechanical 이 쓴 랜덤 덱(실측 2026-11-18)은 앞 모달을 임시 폴더에서 찾고, PSD 의 g 를
    386.4 in/s² 를 옮긴 9,814.56 mm/s² 로 적는다 — 현재 폴더 · 9,806.65 로 고쳐 쓴다(경로를
    쓰면 한글 폴더 이름에서 MAPDL 이 모드 파일을 못 찾았다)."""
    from app.core import units
    from app.core.mechanical.build import localized_random_deck

    deck = "\n".join(
        [
            r"resume,'C:\Users\Home\AppData\Local\Temp\Mech\Modal\file',db",
            "/solu",
            r"modd,on,'C:\Users\Home\AppData\Local\Temp\Mech\Modal\',file",
            "PSDUNIT,1,ACCG,9814.56",
            "PSDFRQ,1,,20.,80.",
        ]
    )
    fixed = localized_random_deck(deck, units.MM_N_TONNE)
    assert fixed.splitlines() == [
        "resume,file,db",
        "/solu",
        "modd,on,,file",
        "PSDUNIT,1,ACCG,9806.65",
        "PSDFRQ,1,,20.,80.",
    ]
    assert "ACCG,9.80665" in localized_random_deck(deck, units.SI)
