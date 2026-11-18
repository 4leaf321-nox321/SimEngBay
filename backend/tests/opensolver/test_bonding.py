"""**본딩을 `*TIE` 로** — 바디를 따로 메시하고 묶는다(`calculix/bonding.py`, 2026-11-16).

운영에서 막힌 넷: ① CAD 의 본딩 접촉 쌍이 쓰이지 않았다(맞닿은 면은 전부 붙었다) ② 형상이
정확히
맞닿아야 했다(미세 간극이면 바디가 떨어졌다) ③ 접합면 양쪽 메시가 묶여 파트별 메시를 따로 못
정했다 ④ 정식 본딩(MPC)은 Ansys 에만 있었다. 「조건_측면가진」(강판 위 알루미늄 기둥, 바닥 고정
·
본딩 「기둥-판」)으로 본다 — 기둥을 띄운 형상은 gmsh 로 만든다.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.core.calculix import tools
from app.core.calculix.mesh import read_mesh
from app.core.stages import StageFailure
from tests.opensolver.test_calculix import FIXTURES, SIDE_SHAKE, SPEC, _run

pytestmark = pytest.mark.opensolver


@pytest.fixture
def ready() -> None:
    for find in (tools.gmsh_bin, tools.ccx_bin):
        try:
            find()
        except StageFailure as failure:
            pytest.skip(str(failure))


def _lifted(
    work: Path, gap: float, *, contact: dict[str, Any] | None = None, **extra: Any
) -> None:
    """기둥을 `gap` mm 띄운 측면가진 — 형상과 점 파일의 기둥 쪽 지문을 함께 옮긴다.
    `contact` 를 주면 「기둥-판」 에 덧씌우고, `None` 이면 그대로, `extra` 는 점 파일 위에
    얹는다."""
    work.mkdir(parents=True)
    geo = work / "lifted.geo"
    # 판 윗면에 기둥 자리를 새긴다 — CompCore 의 STEP 이 그렇다(「접합 판쪽」 은 넓이 100 의
    # 면).
    geo.write_text(
        'SetFactory("OpenCASCADE");\n'
        "Box(1) = {-40, -40, 0, 80, 80, 10};\n"
        "Rectangle(10) = {-5, -5, 10, 10, 10};\n"
        "BooleanFragments{ Volume{1}; Delete; }{ Surface{10}; Delete; }\n"
        f"Box(2) = {{-5, -5, {10 + gap}, 10, 10, 80}};\n",
        encoding="utf-8",
    )
    tools.run(
        tools.gmsh_bin(),
        [str(geo), "-0", "-o", str(work / "input.step"), "-v", "1"],
        cwd=work,
        timeout_seconds=120,
        what="gmsh",
    )
    payload = json.loads((SIDE_SHAKE / "points" / "p0001.json").read_text(encoding="utf-8"))
    for rows in payload["regions"].values():
        for one in rows:
            if isinstance(one, dict) and one.get("body") == "기둥" and "centroid" in one:
                one["centroid"][2] += gap
    for body in payload["bodies"]:
        if body["name"] == "기둥":
            body["centroid"][2] += gap
            body["bbox"][0][2] += gap
            body["bbox"][1][2] += gap
    if contact is not None:
        payload["conditions"]["contacts"] = [
            {**payload["conditions"]["contacts"][0], **contact}
        ]
    payload.update(extra)
    (work / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _floating(work: Path) -> bool:
    """기둥이 떴나 — 바닥을 고정한 모델이라 강체 모드 칸은 0 이고, 0 Hz 모드가 나온다."""
    return float(_result(work)["modes"][0]["frequency_hz"]) < 1.0


def _result(work: Path) -> dict[str, Any]:
    found: dict[str, Any] = json.loads((work / "result.json").read_text(encoding="utf-8"))
    return found


def test_선언한_본딩은_pinball_안의_간극만_묶는다(ready: None, tmp_path: Path) -> None:
    """기둥이 0.3 mm 떠 있다. pinball 0.5 mm 면 묶여 맞닿은 모델과 같은 1차가 나오고, 0.1 mm 면
    안 묶여 기둥이 떠서 0 Hz 모드가 나온다. pinball 이 없으면 요소 크기의 절반(2.5 mm)이라
    묶인다. 종 절점은 늘 주 면에 붙인다(ccx 의 기본 — `ADJUST=NO` 를 안 쓴다)."""
    touching = tmp_path / "touching"
    _lifted(touching, 0.0)
    _run(touching, SPEC)
    base = next(one for one in _result(touching)["modes"] if not one["rigid_body"])

    for pinball, tied in ((0.5, True), (0.1, False), (None, True)):
        work = tmp_path / f"pinball-{pinball}"
        _lifted(work, 0.3, contact={"pinball": pinball})
        summary = _run(work, SPEC)
        result = _result(work)
        if tied:
            assert not _floating(work), pinball
            first = next(one for one in result["modes"] if not one["rigid_body"])
            assert first["frequency_hz"] == pytest.approx(base["frequency_hz"], rel=0.01)
        else:
            assert _floating(work), pinball
        assert "tie:기둥-판" in summary["constrained_regions"]

    # **CAD 가 「Adjust to Touch」 를 안 적어도 옮긴다** — 안 옮기면 종 절점이 주 면에서 떨어진
    # 만큼 구속식이 회전 강체 모드를 잡는다(`bonding.py`, 아래 자유-자유 시험).
    # ccx 는 옮기는 것이 기본이고 `ADJUST=NO` 만 알아듣는다 — `ADJUST=YES` 는 「parameter not
    # recognized」 로 건너뛴다. 그래서 아무것도 안 쓴다.
    deck = (tmp_path / "pinball-None" / "model.inp").read_text(encoding="utf-8")
    assert "*TIE, NAME=" in deck and "ADJUST" not in deck


def test_선언이_없으면_미세_간극은_묶고_CompCore_가_알린_틈새는_남긴다(
    ready: None, tmp_path: Path
) -> None:
    """접촉을 선언하지 않은 조립은 맞닿은 바디를 찾아 묶는다(Mechanical 의 자동 접촉) —
    0.005 mm 뜬 기둥도 묶인다. CompCore 가 그 두 바디 사이의 틈으로 알렸으면
    (`quality.contacts`) 설계한 틈새라 묶지 않는다."""
    loose = tmp_path / "loose"
    _lifted(loose, 0.005)
    payload = json.loads((loose / "topology.json").read_text(encoding="utf-8"))
    payload["conditions"]["contacts"] = []
    (loose / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    summary = _run(loose, SPEC)
    assert any(one.startswith("tie:auto:") for one in summary["constrained_regions"])
    assert not _floating(loose)

    designed = tmp_path / "designed"
    shutil.copytree(loose, designed, ignore=shutil.ignore_patterns("*.msh", "*.frd", "*.dat"))
    payload["quality"]["contacts"] = [
        {"kind": "gap", "a": "받침판", "b": "기둥", "size": 0.005, "at": [0, 0, 10]}
    ]
    (designed / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    summary = _run(designed, SPEC)
    assert not any(one.startswith("tie:auto:") for one in summary["constrained_regions"])
    assert _floating(designed)


def _plate_elements(work: Path) -> int:
    mesh = read_mesh(work / "model.msh")
    plate = max(mesh.bodies, key=lambda one: one.volume).index
    return len(mesh.solids[plate])


def test_파트_메시는_이웃_바디로_번지지_않는다(
    ready: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기둥만 1.5 mm 로 줄인다. `*TIE` 로 묶으면 받침판 메시가 그대로다 — 절점을 공유하던 옛
    방식(`CALCULIX_BONDING=shared`)은 접합부가 기둥을 따라 촘촘해져 받침판 요소가 는다."""
    counts: dict[str, tuple[int, int]] = {}
    for mode in ("tie", "shared"):
        monkeypatch.setenv("CALCULIX_BONDING", mode)
        sizes = []
        for fine in (False, True):
            work = tmp_path / f"{mode}-{fine}"
            _lifted(work, 0.0)
            if fine:
                payload = json.loads((work / "topology.json").read_text(encoding="utf-8"))
                payload["conditions"]["body_settings"] = [
                    {"name": "기둥", "mesh": {"element_size": 1.5}}
                ]
                (work / "topology.json").write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                )
            _run(work, SPEC)
            sizes.append(_plate_elements(work))
        counts[mode] = (sizes[0], sizes[1])
    tie, shared = counts["tie"], counts["shared"]
    assert tie[1] == pytest.approx(tie[0], rel=0.1), counts
    assert shared[1] > 1.3 * shared[0], counts


def _with_settings(work: Path, settings: list[dict[str, Any]]) -> None:
    payload = json.loads((work / "topology.json").read_text(encoding="utf-8"))
    payload["conditions"]["body_settings"] = settings
    (work / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _first_hz(work: Path) -> float:
    return float(
        next(one for one in _result(work)["modes"] if not one["rigid_body"])["frequency_hz"]
    )


def test_바디마다_요소_차수를_달리한다(ready: None, tmp_path: Path) -> None:
    """2차로 메시하고 1차 바디의 중간 절점을 뺀다(`mesh.demote`) — 바디를 따로 메시해 `*TIE` 로
    묶으므로 접합부의 중간 절점을 따로 묶지 않아도 된다. 1차 사면체는 굽힘에 단단해 기둥을
    1차로
    내리면 1차 굽힘이 오른다. 전체를 1차로 두고 판만 2차로 올리는 것도 된다."""
    base = tmp_path / "base"
    _lifted(base, 0.0)
    plain = _run(base, SPEC)

    mixed = tmp_path / "mixed"
    _lifted(mixed, 0.0)
    _with_settings(mixed, [{"name": "기둥", "mesh": {"order": "linear"}}])
    summary = _run(mixed, SPEC)
    deck = (mixed / "model.inp").read_text(encoding="utf-8")
    assert "TYPE=C3D4" in deck and "TYPE=C3D10" in deck
    assert summary["mesh_order"] == "mixed"
    assert "기둥 1차" in summary["mesh_order_by_body"]
    assert "받침판 2차" in summary["mesh_order_by_body"]
    assert "conditions_skipped" not in summary or "차수" not in summary["conditions_skipped"]
    assert int(summary["nodes"]) < int(plain["nodes"])
    assert 1.0 < _first_hz(mixed) / _first_hz(base) < 1.3

    raised = tmp_path / "raised"
    _lifted(raised, 0.0)
    _with_settings(raised, [{"name": "받침판", "mesh": {"order": "quadratic"}}])
    summary = _run(raised, {**SPEC, "mesh": {**SPEC["mesh"], "order": "linear"}})
    assert summary["mesh_order"] == "mixed"
    assert (
        "받침판 2차" in summary["mesh_order_by_body"]
        and "기둥 1차" in summary["mesh_order_by_body"]
    )


#: CompCore 가 잰 맞닿은 쌍(`quality.touching`, CompCore `411247f`) — 모자를 얹은 조립.
CAPPED_TOUCHING = [
    {"a": "받침판", "b": "기둥", "area": 100.0, "at": [0.0, 0.0, 10.0]},
    {"a": "기둥", "b": "모자", "area": 100.0, "at": [0.0, 0.0, 90.0]},
]


def _capped(work: Path, cap: dict[str, Any] | None, *, listed: bool = True) -> None:
    """측면가진 기둥 끝에 「모자」(10 x 10 x 5)를 얹는다 — 바디 셋, 판-기둥은 본딩 그대로.
    `cap` 은 「모자-기둥」 접촉의 덧씌울 칸이고, `None` 이면 그 접촉을 빠뜨린다(CompCore 의
    조립 점검과 같은 꼴 — 판 · 받침 · 덮개에서 받침-덮개만 바꿨다). `listed` 면 점 파일에
    CompCore 의 맞닿은 쌍 목록을 싣는다(없으면 그 전 점 파일)."""
    work.mkdir(parents=True)
    geo = work / "capped.geo"
    geo.write_text(
        'SetFactory("OpenCASCADE");\n'
        "Box(1) = {-40, -40, 0, 80, 80, 10};\n"
        "Rectangle(10) = {-5, -5, 10, 10, 10};\n"
        "BooleanFragments{ Volume{1}; Delete; }{ Surface{10}; Delete; }\n"
        "Box(2) = {-5, -5, 10, 10, 10, 80};\n"
        "Box(3) = {-5, -5, 90, 10, 10, 5};\n",
        encoding="utf-8",
    )
    tools.run(
        tools.gmsh_bin(),
        [str(geo), "-0", "-o", str(work / "input.step"), "-v", "1"],
        cwd=work,
        timeout_seconds=120,
        what="gmsh",
    )
    payload = json.loads((SIDE_SHAKE / "points" / "p0001.json").read_text(encoding="utf-8"))
    payload["bodies"].append(
        {
            "name": "모자",
            "step_product": "body_3",
            "volume": 500.0,
            "kind": "solid",
            "area": 400.0,
            "centroid": [0.0, 0.0, 92.5],
            "bbox": [[-5.0, -5.0, 90.0], [5.0, 5.0, 95.0]],
        }
    )
    payload["regions"]["모자 바닥"] = [
        {
            "centroid": [0.0, 0.0, 90.0],
            "area": 100.0,
            "normal": [0.0, 0.0, -1.0],
            "body": "모자",
        }
    ]
    conditions = payload["conditions"]
    for row in conditions["materials"]:
        if "기둥" in row["apply_to"]:
            row["apply_to"] = [*row["apply_to"], "모자"]
    conditions["loads"] = []
    if listed:
        payload["quality"]["touching"] = CAPPED_TOUCHING
    else:
        # 그 전 점 파일 — CompCore v0.26.0 픽스처에는 이미 목록이 있다(모자 없는 조립의 것).
        payload["quality"].pop("touching", None)
    if cap is not None:
        conditions["contacts"].append(
            {
                **conditions["contacts"][0],
                "name": "모자-기둥",
                "source": "모자 바닥",
                "target": "기둥 끝",
                **cap,
            }
        )
    (work / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_조립에서_빠진_접촉과_미끄럼_접촉을_0_Hz_모드와_함께_말한다(
    ready: None, tmp_path: Path
) -> None:
    """CompCore 의 조립 점검(2026-11-16): 바닥을 고정한 조립에서 한 쌍의 접촉을 빠뜨리면 그
    바디가 떠서 0 Hz 가 나오는데 「강체 모드 0개 · 1차 탄성 0 Hz」 로 나왔고, 아무도 말하지
    않았다. 미끄럼 접촉에도 말이 없었다.

    - 접촉을 빠뜨리면: 요약 `unbonded_touching` 이 그 쌍과 자리를 말하고, 모자가 통째로 떠
      0 Hz 6개가 **강체 모드**로 세어지며, 경고가 움직인 바디(모자)와 빠진 쌍을 짚는다. 쌍은
      CompCore 의 목록(`quality.touching`)에서 고르고 — 두 쪽이 같은 쌍을 말한다 — 목록이 없는
      옛 점 파일이면 메시에서 잰다.
    - 분리 없음이면: 모자가 기둥 끝에서 미끄러져(두 방향 · 법선 둘레 회전) 0 Hz 가 셋, 조건
      처리 말과 경고가 그 접촉을 짚는다.
    - 본딩이면: 0 Hz 도 경고도 없다. 모자가 기둥 끝의 질량이 되어 1차 굽힘이 내려간다(실측
      1,121.5 Hz). 빠뜨린 경우의 1차 탄성은 모자 없는 측면가진 기둥과 같다(1,263.5 Hz) —
      떠 있는 모자의 0 Hz 를 탄성 모드에서 뺐다는 뜻이다."""
    spec = {**SPEC, "modes": 8}
    found: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for label, cap, listed in (
        ("missing", None, True),
        ("measured", None, False),
        ("sliding", {"type": "no_separation"}, True),
        ("bonded", {}, True),
    ):
        work = tmp_path / label
        _capped(work, cap, listed=listed)
        found[label] = (_run(work, spec), _result(work))

    summary, result = found["missing"]
    # CompCore 가 잰 것 그대로 — 넓이 · 자리.
    assert summary["unbonded_touching"] == "기둥 ↔ 모자 (넓이 100 mm² · 자리 (0, 0, 90) mm)"
    boundary = json.loads((tmp_path / "missing" / "boundary.json").read_text(encoding="utf-8"))
    assert boundary["connections"]["untied"] == [{**CAPPED_TOUCHING[1]}]
    assert result["rigid_body_modes"] == 6
    assert summary["first_elastic_hz"] > 1.0
    assert all(one["elastic_number"] is None for one in result["modes"][:6])
    assert "움직이는 바디: 모자" in result["warning"]
    assert "기둥 ↔ 모자" in result["warning"] and "접촉을 거세요" in result["warning"]
    assert summary["result_warning"] == result["warning"]

    # 목록이 없는 옛 점 파일 — 메시에서 잰 같은 쌍(절점 수 · 자리), 같은 경고.
    measured, measured_result = found["measured"]
    assert measured["unbonded_touching"].startswith("기둥 ↔ 모자 (절점 ")
    assert measured_result["rigid_body_modes"] == 6
    assert "기둥 ↔ 모자" in measured_result["warning"]

    summary, result = found["sliding"]
    assert "unbonded_touching" not in summary
    assert "no_separation:모자-기둥" in summary["constrained_regions"]
    assert "미끄러지게" in summary["conditions_skipped"]
    assert result["rigid_body_modes"] == 3, [one["frequency_hz"] for one in result["modes"]]
    assert "움직이는 바디: 모자" in result["warning"]
    assert "「모자-기둥」" in result["warning"]

    summary, result = found["bonded"]
    assert "unbonded_touching" not in summary and "warning" not in result
    assert result["rigid_body_modes"] == 0
    assert found["missing"][0]["first_elastic_hz"] == pytest.approx(1263.5, rel=0.01)
    assert 0.8 < summary["first_elastic_hz"] / found["missing"][0]["first_elastic_hz"] < 0.95


def _free_free(folder: Path, work: Path) -> dict[str, Any]:
    """CAD 폴더의 첫 점을 **지지 · 하중 없이** 모달로 — 본딩만 남긴다. 결과를 돌려준다."""
    work.mkdir(parents=True)
    points = folder / "points"
    step = points / "p0001.step"
    if not step.exists():
        step = next((folder / "shapes").glob("*.step"))
    shutil.copy(step, work / "input.step")
    if (points / "p0001_mid.step").exists():
        shutil.copy(points / "p0001_mid.step", work / "input_mid.step")
    payload = json.loads((points / "p0001.json").read_text(encoding="utf-8"))
    conditions = payload["conditions"]
    conditions["constraints"] = []
    conditions["loads"] = []
    conditions["analysis"] = {"type": "modal", "modes": 6, "solver": "program_controlled"}
    (work / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    _run(work, {"recipe": "modal", "solver": "calculix", "modes": 6})
    return _result(work)


def test_자유_자유_본딩은_강체_모드가_여섯이고_구속식이_회전을_잡지_않는다(
    ready: None, tmp_path: Path
) -> None:
    """**종 절점을 주 면 위로 옮긴다**(ccx 의 기본 — `ADJUST=NO` 를 안 쓴다, 2026-11-17).
    안 옮기면 종 절점이 주 면에서 떨어진 만큼(2차 곡면의 현 오차 · 미세 간극) 구속식이 강체
    회전을 잡는다.
    「조건_볼트예압_판본딩」(본딩 셋, 나사 물림은 원통면) 자유-자유의 회전 셋이 0.23 · 0.30 ·
    0.30 Hz 였고(옮기면 0.003 Hz, 절점 공유와 같다), 64쌍 조립은 1 Hz 를 넘어 강체 모드가
    3개로 셌다."""
    bolted = tmp_path / "bolted"
    result = _free_free(FIXTURES / "doe" / "조건_볼트예압_판본딩", bolted)
    deck = (bolted / "model.inp").read_text(encoding="utf-8")
    assert deck.count("*TIE, NAME=") == 3 and "ADJUST" not in deck
    assert "parameter not recognized" not in (bolted / "ccx.out").read_text(encoding="utf-8")
    rigid = [one for one in result["modes"] if one["rigid_body"]]
    assert len(rigid) == 6 and not any(one.get("held_rigid") for one in rigid)
    assert max(one["frequency_hz"] for one in rigid) < 0.05
    assert "warning" not in result, result.get("warning")


def test_쉘_솔리드_본딩은_구속식으로_묶어_회전을_잡지_않는다(
    ready: None, tmp_path: Path
) -> None:
    """**쉘 ↔ 솔리드 본딩은 `*TIE` 가 아니라 `*EQUATION`** 이다(`deck.Slide.bonded`,
    2026-11-17). `*TIE` 는 쉘을 펼친 3D 절점(중간면 ± 두께/2)을 모두 솔리드 면에 묶어,
    두께만큼 떨어진 절점들이 강체 회전을 잡았다 — 셸모델_시트받침조립 자유-자유의 회전 셋이
    2.62 · 5.04 · 12.8 Hz(1차 탄성 475.30 Hz, `ADJUST` 로는 안 풀린다). 구속식은 원래 쉘
    절점(펼친 절점의 평균 = 중간면)에 걸린다 — 0.011 Hz 아래 여섯 · 1차 탄성 475.25 Hz."""
    sheet = tmp_path / "sheet"
    result = _free_free(FIXTURES / "doe" / "셸모델_시트받침조립", sheet)
    deck = (sheet / "model.inp").read_text(encoding="utf-8")
    assert "*TIE" not in deck and "*EQUATION" in deck
    rigid = [one for one in result["modes"] if one["rigid_body"]]
    assert len(rigid) == 6 and not any(one.get("held_rigid") for one in rigid)
    assert max(one["frequency_hz"] for one in rigid) < 0.1
    first = next(one for one in result["modes"] if not one["rigid_body"])
    assert first["frequency_hz"] == pytest.approx(475.25, rel=0.01)
    assert "warning" not in result, result.get("warning")
