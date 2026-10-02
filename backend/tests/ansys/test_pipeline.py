"""**진짜 Ansys 로 도는 시험.** 기본으로는 안 돈다(`-m ansys`).

    ANSYS_TEST_EXECUTOR=windows-bridge \
      ANSYS_TEST_PYTHON=/mnt/c/simengbay/venv/Scripts/python.exe \
      ANSYS_TEST_WORK_DIR=/mnt/c/simengbay/pytest \
      .venv/bin/python -m pytest -m ansys

**`SIMULATION_EXECUTOR` 이 아니라 전용 이름을 쓴다.** `tests/conftest.py` 가 그 값을 `fake` 로
못 박기 때문이다(시험이 개발 `.env` 를 따라가면 안 된다) — 같은 이름을 쓰면 이 시험들이
조용히 가짜 실행기로 돌고, **가짜 결과를 진짜로 읽어** 통과하거나 엉뚱하게 실패한다(실측).

여기서 보는 것은 **로드맵의 리스크 1 · 3**이다 — CAD 플랫폼(build123d/OpenCascade)이 낸 STEP 이
임포트되고 면 순회 · 메시 · `.dat` 까지 가는가, 그리고 그 결과를 솔버와 DPF 가 받아 주는가.
형상은 `tests/fixtures/step/` 에 있고 AutoJigGenerator 와 같은 도구로 만들었다.

**실측(2026-09-20, 2025 R2 Student · Windows)**: 판 100x60x5 — 절점 836 · 1차 탄성 2583.1 Hz,
L 브래킷 — 절점 1,976 · 3315.2 Hz. 둘 다 강체 모드 6개.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.core import executors
from app.core.spec import RIGID_BODY_MODES, parse_spec
from app.core.stages import STAGES, StageContext, StageFailure

pytestmark = pytest.mark.ansys

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
STEPS = FIXTURES / "step"
TOPOLOGY = FIXTURES / "topology"
#: CompCore 가 낸 DOE 폴더 한 벌 — 형상을 **나눠 쓰는** 쪽(`shapes/`)을 일부러 고른다.
SHARED_DOE = FIXTURES / "doe" / "재료훑기-7c1d3a44"
#: 바디 둘에 다른 재료가 붙은 폴더(CompCore 2026-09-28).
TWO_BODIES = FIXTURES / "doe" / "조건_두바디_두재료"
#: 조건 · 물성 배율까지 훑는 폴더(CompCore 2026-09-29) — **값이 다 들어 있다.**
CONDITION_SWEEP = FIXTURES / "doe" / "조건_조건훑기"
#: 점마다 바디의 재료가 바뀌는 폴더(CompCore 2026-10-02 에 값까지 채워 다시 뽑았다).
MATERIAL_SWEEP = FIXTURES / "doe" / "조건_재료훑기"
SPEC = {
    "recipe": "modal",
    "material": {
        "name": "SS400",
        "youngs_modulus_gpa": 200,
        "poisson_ratio": 0.3,
        "density_kg_m3": 7850,
    },
    "mesh": {"element_size_mm": 10},
    "modes": 5,
}


def _executor() -> executors.Executor:
    """이 시험들만의 실행기 — **`SIMULATION_EXECUTOR` 과 다른 이름을 본다**(머리말 참고)."""
    name = os.environ.get("ANSYS_TEST_EXECUTOR", "local")
    python = os.environ.get("ANSYS_TEST_PYTHON")
    return executors.resolve(name, python=Path(python) if python else None)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """**Ansys 가 쓸 수 있는 폴더여야 한다.** windows-bridge 면 Windows 쪽 경로를 준다 —
    `\\\\wsl$` 에 쓰게 하면 느리고 잠금 문제가 난다(계획서 3.1)."""
    base = os.environ.get("ANSYS_TEST_WORK_DIR")
    if base is None:
        return tmp_path
    target = Path(base) / tmp_path.name
    target.mkdir(parents=True, exist_ok=True)
    return target


@pytest.mark.parametrize("name", ["plate.step", "bracket.step"])
def test_CAD_가_낸_STEP_이_끝까지_간다(name: str, workdir: Path) -> None:
    shutil.copy(STEPS / name, workdir / "input.step")
    spec = parse_spec(SPEC)
    (workdir / "spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")

    runner = _executor()
    summary: dict[str, Any] = {}
    for stage in STAGES:
        result = runner.run(StageContext(stage=stage, spec=SPEC, workdir=workdir))
        summary.update(result.summary)

    assert (workdir / "model.dat").is_file()
    assert (workdir / "result.json").is_file()

    result = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
    assert result["boundary"] == "free-free"
    # **강체 모드가 6개여야 한다.** 다중 바디에서 접촉이 안 잡히면 바디마다 6개가 나온다 —
    # 값은 그럴듯한데 모델이 붙어 있지 않은 상태다.
    assert result["rigid_body_modes"] == RIGID_BODY_MODES
    assert "warning" not in result
    assert len(result["modes"]) == 5 + RIGID_BODY_MODES
    assert result["units"]["frequency"] == "Hz"
    assert "MKS" in result["units"]["system"]

    elastic = [one for one in result["modes"] if not one["rigid_body"]]
    # 강체 모드는 0 근처, 첫 탄성 모드는 그것과 자릿수가 다르다.
    assert elastic[0]["frequency_hz"] > 100
    assert all(one["frequency_hz"] < 1.0 for one in result["modes"] if one["rigid_body"])
    assert int(summary["nodes"]) > 0

    # --- 모드 형상 (3단계) ---------------------------------------------------
    drawn = [one for one in elastic if one.get("vtp")]
    assert drawn, "탄성 모드에 형상 파일이 하나도 없습니다"
    for one in drawn:
        vtp = workdir / str(one["vtp"])
        assert vtp.is_file() and vtp.stat().st_size > 0
        # 썸네일은 곁들이라 없을 수 있다 — 있으면 빈 파일이면 안 된다.
        if one.get("png"):
            assert (workdir / str(one["png"])).stat().st_size > 0
        assert float(one["max_displacement"]) > 0

    # 참여계수 — 자유-자유는 강체 모드가 유효질량을 전부 가져간다.
    assert sorted(result["participation"]) == ["ROTX", "ROTY", "ROTZ", "X", "Y", "Z"]


def test_볼트_구멍을_고정하면_강체_모드가_사라진다(workdir: Path) -> None:
    """**4단계의 완료 기준.** CAD 가 보낸 영역 지문으로 볼트 구멍을 찾아 고정한다.

    자유-자유와 갈리는 것은 두 가지다 — 0 Hz 여섯 개가 없어지고, **유효질량비가 살아난다**
    (구속이 없으면 강체 모드가 전부 가져가서 탄성 모드는 0 이다).

    실측(2026-09-23, L 브래킷 120x80 · 벽 60 · 볼트 4): 1차 1,519 Hz · ROTY 유효질량 0.40.
    """
    shutil.copy(STEPS / "bracket_bolted.step", workdir / "input.step")
    shutil.copy(TOPOLOGY / "bracket_bolted.topology.json", workdir / "topology.json")
    spec = dict(SPEC)
    spec["mesh"] = {"element_size_mm": 6}
    spec["constraints"] = [{"region": "bolt_holes", "kind": "fixed"}]
    parse_spec(spec)
    (workdir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    runner = _executor()
    for stage in STAGES:
        result = runner.run(StageContext(stage=stage, spec=spec, workdir=workdir))
        if stage == "modeling":
            assert result.summary["constrained_regions"] == ["bolt_holes"]

    result = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
    assert result["boundary"] == "constrained"
    assert result["rigid_body_modes"] == 0
    assert all(one["frequency_hz"] > 1.0 for one in result["modes"])
    # 유효질량비가 실값을 갖는다 — 이것이 구속 해석의 값이다.
    assert any((one.get("effective_mass_ratio") or 0) > 0.1 for one in result["modes"])


def test_DOE_점_파일_한_장으로_구속까지_간다(workdir: Path) -> None:
    """**CompCore 2026-09-24 계약**을 진짜 Ansys 로 받아 본다.

    바뀐 것은 두 가지다 — 점마다의 정보가 `pNNNN.json` 한 장으로 합쳐졌고(영역 · 바디 · 조건),
    형상은 여러 점이 나눠 쓰면 `shapes/<지문>.step` 에 있다. 폴더 읽기만 시험하면 「합친 파일을
    Mechanical 이 받아 주는가」 는 아무도 안 본 채로 남는다 — 조건 뭉치가 늘어난 파일을
    모델링이 그대로 읽는지 여기서 본다.

    **그리고 단위계다.** 이 폴더는 `conditions.units.system = mm_n_tonne` 을 선언한다 — 세션을
    그 계로 세우고 물성 숫자도 그 계로 적는다(2026-09-24 결정 1+3). 환산이 틀리면 나오는 것은
    오류가 아니라 **그럴듯한 값**이다: 탄성계수를 Pa 로 적으면 10⁶ 배 작아져 1차가 1.5 Hz 로
    내려간다. 그래서 MKS 로 돌린 같은 형상의 값과 견준다.

    실측(2026-09-24, 2025 R2 Student · Windows): mm 계로 세워도 1차 1,519 Hz — MKS 와 같다.
    """
    shutil.copy(SHARED_DOE / "shapes" / "8f3a1c92.step", workdir / "input.step")
    # **점 파일을 그대로 `topology.json` 자리에 둔다** — 가져오기가 하는 일과 같다.
    shutil.copy(SHARED_DOE / "points" / "p0001.json", workdir / "topology.json")
    spec = dict(SPEC)
    spec["mesh"] = {"element_size_mm": 6}
    spec["constraints"] = [{"region": "bolt_holes", "kind": "fixed"}]
    parse_spec(spec)
    (workdir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    runner = _executor()
    for stage in STAGES:
        result = runner.run(StageContext(stage=stage, spec=spec, workdir=workdir))
        if stage == "modeling":
            assert result.summary["constrained_regions"] == ["bolt_holes"]
            # 선언대로 세웠는가 — `.dat` 의 숫자가 읽히는 계까지 함께 남긴다.
            assert result.summary["unit_system"] == "mm_n_tonne"
            assert result.summary["solver_unit_system"] == "ConsistentNMM"
            # 질량은 계와 상관없이 kg 이다 — 부피를 mm³ 로 받고 안 고치면 10⁹ 배 커진다.
            assert 0.5 < float(result.summary["mass_kg"]) < 1.5

    result = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
    assert result["boundary"] == "constrained"
    assert result["rigid_body_modes"] == 0
    assert all(one["frequency_hz"] > 1.0 for one in result["modes"])
    # **MKS 로 돌린 같은 형상과 같은 값**(1,519 Hz). 단위가 어긋나면 여기서 자릿수가 갈린다.
    assert 1500 < result["modes"][0]["frequency_hz"] < 1540


@pytest.mark.parametrize(
    ("number", "material", "modulus_gpa", "density", "mass_kg"),
    [
        (1, "SS400", 206.0, 7850.0, 0.8902),
        (2, "AL6061", 68.9, 2700.0, 0.3062),
    ],
)
def test_CAD_가_보낸_물성으로_돈다(
    number: int,
    material: str,
    modulus_gpa: float,
    density: float,
    mass_kg: float,
    workdir: Path,
) -> None:
    """**재료를 훑는 DOE 가 뜻을 갖는 자리.** 점 파일의 물성을 읽어 그 값으로 푼다.

    여태는 사람이 넣은 한 벌을 모든 점에 썼다 — 그래서 SS400 점과 AL6061 점이 **이름만 다르고
    결과가 똑같이** 나왔다. 여기서 보는 것은 셋이다:

    - 스펙에 적힌 200 GPa 가 아니라 **CAD 의 206 GPa** 로 푼다(1번 점).
    - 점마다 다른 재료로 푼다(2번은 68.9 GPa · 2,700).
    - **질량이 갈린다** — 0.89 kg 대 0.31 kg. 주파수는 강과 알루미늄의 E/밀도 비가 비슷해서
      1% 안쪽으로 닮으므로(1,542 · 1,520 Hz), 물성이 안 들어간 것을 주파수만 보고는 알 수 없다.
      **질량이 그 유일한 증인이다.**
    """
    shutil.copy(SHARED_DOE / "shapes" / "8f3a1c92.step", workdir / "input.step")
    shutil.copy(SHARED_DOE / "points" / f"p{number:04d}.json", workdir / "topology.json")
    spec = dict(SPEC)  # 스펙의 물성은 SS400 200 GPa · 7,850 — CAD 가 이것을 덮는다
    spec["mesh"] = {"element_size_mm": 6}
    spec["constraints"] = [{"region": "bolt_holes", "kind": "fixed"}]
    parse_spec(spec)
    (workdir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    runner = _executor()
    for stage in STAGES:
        result = runner.run(StageContext(stage=stage, spec=spec, workdir=workdir))
        if stage == "modeling":
            summary = result.summary
            # **무슨 물성으로 돌았나를 요약이 말한다** — 값만 보고는 알 수 없다.
            assert summary["material"] == material
            assert summary["material_from"] == "cad"
            assert summary["youngs_modulus_gpa"] == pytest.approx(modulus_gpa, rel=1e-6)
            assert summary["density_kg_m3"] == pytest.approx(density, rel=1e-6)
            # 질량은 그 밀도로 낸다 — 재료가 안 바뀌면 여기가 같아진다.
            assert float(summary["mass_kg"]) == pytest.approx(mass_kg, rel=0.01)

    result = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
    assert result["rigid_body_modes"] == 0
    first = result["modes"][0]["frequency_hz"]
    # 스펙의 200 GPa 로 풀면 1,519 Hz 다(다른 시험이 그 값을 잰다). CAD 의 값으로 풀면
    # 1번은 206 GPa 라서 **더 높고**, 2번은 알루미늄인데도 비슷하다.
    assert 1400 < first < 1700
    if number == 1:
        assert first > 1530  # 200 GPa 로 풀었으면 1,519 였다


def test_파트마다_다른_물성을_바디마다_붙인다(workdir: Path) -> None:
    """**조립은 파트마다 재료가 다르다** — 강판 받침판 위에 알루미늄 블록.

    어느 Mechanical 바디가 CAD 의 어느 파트인지는 **이름으로 알 수 없다**: STEP 이 한글을 못
    나른다(실측 2026-09-28 — Mechanical 이 「챘째혴챙쨔짢챠혣혨|Solid」 로 읽었다). 그래서
    부피 · 무게중심으로 짝짓는다(`app/core/bodies.py`).

    **질량이 그 증인이다.** 받침판 30,000 mm³ · 블록 32,000 mm³ 이므로
    강(7,850)+알루미늄(2,700) 이면 0.2355 + 0.0864 = **0.3219 kg**, 물성이 뒤바뀌면
    0.081 + 0.2512 = 0.3322 kg 다 — 3% 차이라서 주파수만 보고는 못 가른다.

    폴더의 물성에는 **탄성계수가 없다**(CompCore 가 고른 MatNexus 줄에 그 값이 없다 —
    `missing_structural`). 그래서 여기서는 값이 있는 `converted` 두 벌을 **CompCore 의 환산
    코드로 만든 것**(`tests/fixtures/materials/`)으로 바꿔 끼운다. 바꾸는 것은 재료 선택뿐이고
    모양은 그쪽이 낸 그대로다.
    """
    point = json.loads((TWO_BODIES / "points" / "p0001.json").read_text(encoding="utf-8"))
    steel = json.loads(
        (FIXTURES / "materials" / "등록재료-mm_n_tonne.json").read_text(encoding="utf-8")
    )
    aluminium = json.loads(
        (FIXTURES / "materials" / "문헌물성-mm_n_tonne.json").read_text(encoding="utf-8")
    )
    point["conditions"]["materials"] = [
        {"apply_to": ["받침판"], "ref": {"name": "SS400"}, "converted": steel},
        {"apply_to": ["블록"], "ref": {"name": "AL6061"}, "converted": aluminium},
    ]
    shutil.copy(TWO_BODIES / "points" / "p0001.step", workdir / "input.step")
    (workdir / "topology.json").write_text(
        json.dumps(point, ensure_ascii=False), encoding="utf-8"
    )

    spec = dict(SPEC)
    spec["mesh"] = {"element_size_mm": 8}
    spec["constraints"] = [{"region": "바닥", "kind": "fixed"}]
    parse_spec(spec)
    (workdir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    runner = _executor()
    for stage in STAGES:
        result = runner.run(StageContext(stage=stage, spec=spec, workdir=workdir))
        if stage == "modeling":
            summary = result.summary
            assert summary["bodies"] == 2
            assert summary["material_from"] == "cad"
            # **어느 파트에 무엇을 붙였나**를 요약이 말한다 — 값 하나로 줄이면 뒤바뀐 것을
            # 알아볼 수 없다.
            assert summary["material_bodies"] == "받침판=SS400 · 블록=AL6061"
            assert float(summary["mass_kg"]) == pytest.approx(0.3219, rel=0.005)

    result = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
    assert result["boundary"] == "constrained"
    assert result["rigid_body_modes"] == 0


def test_CAD_폴더_그대로_두_설계점을_돈다(workdir: Path) -> None:
    """**바꿔 끼운 값이 하나도 없는 첫 판** — CAD 가 보낸 폴더를 그대로 돌린다.

    `조건_조건훑기` 는 블록의 탄성계수를 배율로 훑는다(0.9 · 1.1). 형상 · 재료 · 밀도는 두
    점이 같고 **블록의 탄성계수만** 다르다. 그래서 답이 갈리는 곳이 정해져 있다:

    - **질량은 같아야 한다** — 밀도가 안 바뀐다(받침판 강 0.2355 + 블록 알루미늄 0.0858).
    - **주파수는 올라야 한다** — 블록이 단단해지면(0.9 → 1.1) 고유진동수가 높아진다.

    물성을 안 읽으면 둘이 **똑같이** 나오고, 바디를 뒤바꿔 붙이면 질량이 어긋난다.
    """
    seen: dict[int, dict[str, Any]] = {}
    for number in (1, 2):
        place = workdir / f"p{number:04d}"
        place.mkdir(parents=True, exist_ok=True)
        shutil.copy(CONDITION_SWEEP / "shapes" / "c3aed82c2d74.step", place / "input.step")
        shutil.copy(
            CONDITION_SWEEP / "points" / f"p{number:04d}.json", place / "topology.json"
        )
        spec = dict(SPEC)
        spec["mesh"] = {"element_size_mm": 8}
        spec["constraints"] = [{"region": "바닥", "kind": "fixed"}]
        parse_spec(spec)
        (place / "spec.json").write_text(
            json.dumps(spec, ensure_ascii=False), encoding="utf-8"
        )

        runner = _executor()
        summary: dict[str, Any] = {}
        for stage in STAGES:
            result = runner.run(StageContext(stage=stage, spec=spec, workdir=place))
            summary.update(result.summary)
        result_json = json.loads((place / "result.json").read_text(encoding="utf-8"))
        seen[number] = {
            "mass": float(summary["mass_kg"]),
            "from": summary["material_from"],
            "bodies": summary["material_bodies"],
            "first": result_json["modes"][0]["frequency_hz"],
            "rigid": result_json["rigid_body_modes"],
        }

    for number, found in seen.items():
        assert found["from"] == "cad", f"p{number} 이 CAD 물성으로 안 돌았다"
        assert found["rigid"] == 0
        # 받침판 · 블록에 각각 다른 재료가 붙었다.
        assert "받침판=" in found["bodies"] and "블록=" in found["bodies"]
        assert found["mass"] == pytest.approx(0.3213, rel=0.01)

    # **밀도가 같으니 질량도 같다** — 다르면 바디에 물성을 뒤바꿔 붙인 것이다.
    assert seen[1]["mass"] == pytest.approx(seen[2]["mass"], rel=1e-6)
    # **블록이 단단해지면 주파수가 오른다**(E 배율 0.9 → 1.1).
    assert seen[2]["first"] > seen[1]["first"]


def test_CAD_가_보낸_구속과_접촉을_건다(workdir: Path) -> None:
    """**조건을 읽어 거는 첫 판** — 스펙에는 구속을 하나도 안 적고 CAD 것만으로 돈다.

    `조건_조건훑기` 는 접촉 종류를 훑는다(1번 본딩 · 3번 마찰). 접촉이 바뀌면 두 바디가 붙은
    정도가 달라지므로 **고유진동수가 달라져야 한다** — 조건을 안 읽으면 두 점이 같은 답을 낸다.

    실측(2026-10-02, 2025 R2 Student · Windows): 본딩 30,090.3 Hz · 마찰 쪽은 더 낮다.
    """
    seen: dict[int, dict[str, Any]] = {}
    for number in (1, 3):
        place = workdir / f"p{number:04d}"
        place.mkdir(parents=True, exist_ok=True)
        shutil.copy(CONDITION_SWEEP / "shapes" / "c3aed82c2d74.step", place / "input.step")
        shutil.copy(
            CONDITION_SWEEP / "points" / f"p{number:04d}.json", place / "topology.json"
        )
        # **스펙에는 구속이 없다** — 전부 CAD 가 보낸 조건에서 온다.
        spec = dict(SPEC)
        spec["mesh"] = {"element_size_mm": 8}
        parse_spec(spec)
        (place / "spec.json").write_text(
            json.dumps(spec, ensure_ascii=False), encoding="utf-8"
        )

        runner = _executor()
        summary: dict[str, Any] = {}
        for stage in STAGES:
            result = runner.run(StageContext(stage=stage, spec=spec, workdir=place))
            summary.update(result.summary)
        result_json = json.loads((place / "result.json").read_text(encoding="utf-8"))
        seen[number] = {
            "from": summary["conditions_from"],
            "regions": summary["constrained_regions"],
            "skipped": summary.get("conditions_skipped", ""),
            "first": result_json["modes"][0]["frequency_hz"],
            "rigid": result_json["rigid_body_modes"],
            "boundary": result_json["boundary"],
            "modes": len(result_json["modes"]),
            "requested": summary["modes_requested"],
        }

    for number, found in seen.items():
        assert found["from"] == "cad", f"p{number} 이 CAD 조건으로 안 돌았다"
        # 바닥 고정 지지 + 접촉 한 쌍이 걸렸다.
        assert any("fixed_support" in one for one in found["regions"])
        assert any("contact" in one for one in found["regions"])
        assert found["rigid"] == 0, "구속이 걸렸으면 강체 모드가 없어야 한다"
        # **스펙에는 구속이 없다** — 그래도 결과는 「구속」 이어야 한다. CAD 조건으로 걸었기
        # 때문이다. 여기가 「자유-자유」 로 적히면 강체 모드를 세는 경고까지 거짓이 된다.
        assert found["boundary"] == "constrained"
        # 자유-자유가 아니므로 강체 6개를 얹지 않는다 — 요청한 만큼만 나온다.
        assert found["requested"] == 5
        assert found["modes"] == 5
        # **모달에서 못 쓰는 하중은 버리지 않고 말한다.**
        assert "하중" in found["skipped"]

    # 본딩(1번)과 마찰(3번)은 붙은 정도가 다르다 — 같은 값이면 접촉이 안 걸린 것이다.
    assert seen[1]["first"] != pytest.approx(seen[3]["first"], rel=1e-4)


def test_선응력을_켜면_하중이_쓰인다(workdir: Path) -> None:
    """**조여 놓고 떠는 상태** — CompCore 의 주 용도다(볼트를 조인 뒤의 공진).

    같은 폴더를 두 번 돌린다. 한 번은 그대로(하중은 「건너뜀」), 한 번은 조건의 `prestressed`
    를 켜서. 켜면 정적 해석이 먼저 돌고 모달이 그 응력을 안고 푼다 — **주파수가 달라져야
    한다.** 같으면 하중이 안 걸린 것이다.
    """
    seen: dict[str, Any] = {}
    for label, prestressed in (("그냥", False), ("선응력", True)):
        place = workdir / label
        place.mkdir(parents=True, exist_ok=True)
        point = json.loads(
            (CONDITION_SWEEP / "points" / "p0001.json").read_text(encoding="utf-8")
        )
        point["conditions"]["analysis"]["prestressed"] = prestressed
        shutil.copy(CONDITION_SWEEP / "shapes" / "c3aed82c2d74.step", place / "input.step")
        (place / "topology.json").write_text(
            json.dumps(point, ensure_ascii=False), encoding="utf-8"
        )
        spec = dict(SPEC)
        spec["mesh"] = {"element_size_mm": 8}
        parse_spec(spec)
        (place / "spec.json").write_text(
            json.dumps(spec, ensure_ascii=False), encoding="utf-8"
        )

        runner = _executor()
        summary: dict[str, Any] = {}
        for stage in STAGES:
            result = runner.run(StageContext(stage=stage, spec=spec, workdir=place))
            summary.update(result.summary)
        result_json = json.loads((place / "result.json").read_text(encoding="utf-8"))
        seen[label] = {
            "prestressed": summary.get("prestressed", False),
            "loads": summary.get("loads", ""),
            "skipped": summary.get("conditions_skipped", ""),
            "first": result_json["modes"][0]["frequency_hz"],
            "static": (place / "static.dat").is_file(),
        }

    # 그냥 돌리면 하중은 걸지 않고 **그 사실을 말한다.**
    assert seen["그냥"]["prestressed"] is False
    assert "하중" in seen["그냥"]["skipped"]
    # 켜면 하중이 정적 해석에 걸린다.
    assert seen["선응력"]["prestressed"] is True
    assert "pressure" in seen["선응력"]["loads"]
    # 정적 덱이 따로 나왔다 — 모달의 덱은 그 재시작이다.
    assert seen["선응력"]["static"], "정적 덱(static.dat)이 없다"
    # **응력을 안고 풀면 값이 달라진다.** 누르는 하중은 구조를 무르게 하므로 **낮아진다** —
    # 실측(2026-10-02): 30,090.3497 → 30,090.1351 Hz(압력 1.5 MPa · 2,400 N).
    # 차이는 작지만(0.0007%) 방향이 정해져 있다. 같은 값이면 선응력이 안 걸린 것이다.
    assert seen["선응력"]["first"] < seen["그냥"]["first"]
    assert abs(seen["선응력"]["first"] - seen["그냥"]["first"]) > 0.05


def test_재료를_훑으면_설계점마다_물성이_갈린다(workdir: Path) -> None:
    """**CAD 폴더 그대로, 재료 DOE 를 끝까지.** 여태 폴더에 탄성계수가 없어 못 하던 검증이다.

    `조건_재료훑기` 는 블록의 재료를 바꿔 끼운다 — 1번은 알루미늄(AL5052), 2번은 두 바디 모두
    강(SECC). 형상은 한 벌을 나눠 쓴다.

    **질량이 갈려야 한다**: 받침판 30,000 mm³ · 블록 32,000 mm³ 이므로 1번은 강+알루미늄
    (0.2355 + 0.0858 = 0.3213 kg), 2번은 둘 다 강(0.2355 + 0.2512 = 0.4867 kg). 물성을 안
    읽으면 두 점이 **같은 값**으로 나온다.
    """
    seen: dict[int, dict[str, Any]] = {}
    for number in (1, 2):
        place = workdir / f"p{number:04d}"
        place.mkdir(parents=True, exist_ok=True)
        point = json.loads(
            (MATERIAL_SWEEP / "points" / f"p{number:04d}.json").read_text(encoding="utf-8")
        )
        shape = MATERIAL_SWEEP / point["point"]["step_file"]
        shutil.copy(shape, place / "input.step")
        shutil.copy(MATERIAL_SWEEP / "points" / f"p{number:04d}.json", place / "topology.json")
        spec = dict(SPEC)
        spec["mesh"] = {"element_size_mm": 8}
        parse_spec(spec)
        (place / "spec.json").write_text(
            json.dumps(spec, ensure_ascii=False), encoding="utf-8"
        )

        runner = _executor()
        summary: dict[str, Any] = {}
        for stage in STAGES:
            result = runner.run(StageContext(stage=stage, spec=spec, workdir=place))
            summary.update(result.summary)
        result_json = json.loads((place / "result.json").read_text(encoding="utf-8"))
        seen[number] = {
            "mass": float(summary["mass_kg"]),
            "material": summary["material"],
            "first": result_json["modes"][0]["frequency_hz"],
        }

    # 1번: 강판 + 알루미늄 블록. 2번: 둘 다 강.
    assert seen[1]["mass"] == pytest.approx(0.3213, rel=0.01)
    assert seen[2]["mass"] == pytest.approx(0.4867, rel=0.01)
    # **무거워지면 주파수가 내려간다** — 블록이 알루미늄에서 강으로 바뀌면 질량이 더 는다.
    assert seen[2]["first"] < seen[1]["first"]


def test_정적_해석이_변형과_응력을_낸다(workdir: Path) -> None:
    """**하중이 답을 만드는 해석** — `조건_두바디_두재료` 가 바로 그 폴더다(바닥 고정 ·
    블록 윗면 압력 1.5 MPa · 해석 종류 `static`).

    모달과 달리 보는 것이 다르다: **얼마나 밀리고 어디가 버거운가.** 그래서 결과에 모드가
    없고 최대 변형 · 최대 상당응력이 있다.

    실측(2026-10-02, 2025 R2 Student · Windows): 최대 변형 **5.204e-4 mm** · 최대 상당응력
    **2.523 MPa**(요소 8 mm). 응력은 DPF 에서 부르는 길이 판마다 달라 **차례로 해 본다** —
    첫 길이 없다고 포기하면 사람이 가장 보고 싶어 하는 수가 비어서 나간다(실측으로 겪었다).
    """
    shutil.copy(TWO_BODIES / "points" / "p0001.step", workdir / "input.step")
    shutil.copy(TWO_BODIES / "points" / "p0001.json", workdir / "topology.json")
    spec = {
        "recipe": "static",
        "material": SPEC["material"],
        "mesh": {"element_size_mm": 8},
    }
    parse_spec(spec)
    (workdir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    runner = _executor()
    summary: dict[str, Any] = {}
    for stage in STAGES:
        result = runner.run(StageContext(stage=stage, spec=spec, workdir=workdir))
        summary.update(result.summary)
        if stage == "modeling":
            # 구속도 하중도 CAD 조건에서 왔다.
            assert summary["conditions_from"] == "cad"
            assert "pressure" in summary["loads"]

    result_json = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
    assert result_json["recipe"] == "static"
    assert "modes" not in result_json
    # **밀린 만큼이 0 이 아니어야 한다** — 0 인 결과는 「해석이 됐다」 처럼 보인다.
    assert result_json["max_displacement"] > 0
    assert "warning" not in result_json
    assert result_json["max_displacement"] == pytest.approx(5.204e-4, rel=0.05)
    # 응력도 함께 — 못 읽으면 None 이고, 그때는 수를 지어내지 않는다.
    assert result_json["max_von_mises"] == pytest.approx(2.523, rel=0.05)
    assert result_json["units"]["displacement"] == "mm"
    # 변형 그림도 남는다(모달의 모드 형상과 같은 길).
    assert (workdir / "mode_01.vtp").is_file()


def test_조화_응답이_주파수_곡선을_낸다(workdir: Path) -> None:
    """**주파수를 훑으며 흔든다** — 모달이 「어디서 떠는가」 라면 이것은 「그때 얼마나 크게
    흔들리는가」 다.

    `조건_두바디_두재료`(바닥 고정 · 블록 윗면 압력)를 조화 응답으로 돌린다. 구속은 앞선
    모달에, 흔드는 하중은 조화 쪽에 걸린다.

    **결과가 곡선이다** — 주파수 점마다 최대 변위가 붙는다. 공진 근처에서 값이 솟아야 한다.
    """
    shutil.copy(TWO_BODIES / "points" / "p0001.step", workdir / "input.step")
    shutil.copy(TWO_BODIES / "points" / "p0001.json", workdir / "topology.json")
    spec = {
        "recipe": "harmonic",
        "material": SPEC["material"],
        "mesh": {"element_size_mm": 8},
        # **1차가 30,090 Hz 근처다**(모달 실측). 감쇠 2% 면 공진 폭이 ~0.6 kHz 라, 넓게
        # 훑으면 점 사이로 봉우리가 빠져나간다 — 실제로 2 kHz 간격에서 그랬다. 좁게 훑는다.
        "frequency_range_hz": [29000, 31000],
        "intervals": 10,
        "modes": 6,
        "damping_ratio": 0.02,
    }
    parse_spec(spec)
    (workdir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    runner = _executor()
    summary: dict[str, Any] = {}
    for stage in STAGES:
        result = runner.run(StageContext(stage=stage, spec=spec, workdir=workdir))
        summary.update(result.summary)

    result_json = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
    assert result_json["recipe"] == "harmonic"
    points = result_json["points"]
    assert len(points) == 10, "주파수 점이 요청한 수만큼 나와야 한다"
    assert all(one["max_displacement"] > 0 for one in points), (
        "응답이 0 이면 하중이 안 걸린 것"
    )
    assert points[0]["frequency_hz"] == pytest.approx(29200, abs=1)
    assert points[-1]["frequency_hz"] == pytest.approx(31000, abs=1)
    # 앞선 모달의 덱이 따로 나왔다 — 모드 중첩은 그것을 이어받는다.
    assert (workdir / "upstream.dat").is_file()

    # **아직 못 본 것: 공진 증폭.** 1차(30,090 Hz)를 지나는데 응답이 정적값(5.204e-4)에서
    # 거의 안 움직인다(5.1e-4 ~ 5.3e-4). 덱에는 `hropt,msup` · `harfrq` 가 바르게 적히지만
    # 감쇠(`dmprat`)가 안 실린다 — 모드 중첩이 증폭을 안 하고 있다는 뜻이다. 그 자리를 찾기
    # 전까지 **봉우리를 단정하지 않는다**(2026-10-02, 계획서에 적어 두었다).


def test_영역_이름이_없으면_모델링에서_즉시_실패한다(workdir: Path) -> None:
    """**조용히 자유-자유로 풀지 않는다.** 그 결과는 0 Hz 여섯 개를 달고 나오고, 사람은 그것을
    「해석이 됐다」 로 읽는다."""
    shutil.copy(STEPS / "bracket_bolted.step", workdir / "input.step")
    shutil.copy(TOPOLOGY / "bracket_bolted.topology.json", workdir / "topology.json")
    spec = dict(SPEC)
    spec["constraints"] = [{"region": "load_face", "kind": "fixed"}]
    (workdir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    runner = _executor()
    runner.run(StageContext(stage="fetching", spec=spec, workdir=workdir))
    with pytest.raises(StageFailure) as caught:
        runner.run(StageContext(stage="modeling", spec=spec, workdir=workdir))
    assert caught.value.code == "region_unresolved"
