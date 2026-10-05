"""조건 읽기 — **걸 것 · 넘길 것 · 막을 것**으로 갈리는가.

여기서 지키는 것은 「조용히 버리지 않는다」 하나다. 조건을 넣었는데 결과가 같으면 사람은
그것이 **무시된 것인지 원래 그런 것인지** 알 수 없다. 그래서 넘긴 것은 넘겼다고, 못 거는 것은
못 건다고 말해야 한다.

폴더는 CompCore 의 내보내기 코드가 쓴 것이다(`tests/fixtures/doe/README-조건픽스처.md`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core import conditions

FOLDERS = Path(__file__).resolve().parents[1] / "fixtures" / "doe"


def _point(folder: str, number: int = 1) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (FOLDERS / folder / "points" / f"p{number:04d}.json").read_text(encoding="utf-8")
    )
    return loaded


def test_고정_지지와_접촉을_읽는다() -> None:
    """`조건_두바디_두재료` — 바닥 고정 · 본딩 접촉 · 압력."""
    found = conditions.read(_point("조건_두바디_두재료"))

    assert [(one.kind, one.region) for one in found.constraints] == [("fixed_support", "바닥")]
    assert [(one.kind, one.source, one.target) for one in found.contacts] == [
        ("bonded", "블록 아랫면", "판 윗면")
    ]
    # **압력은 모달에서 답을 바꾸지 않는다** — 버리지 않고 그 사실을 적어 둔다.
    assert any("압력" in one.what or "pressure" in one.what for one in found.skipped)
    assert found.refused == []


def test_원통_지지의_방향을_읽는다() -> None:
    """`조건_원통_SI` — 구멍면에 원통 지지, **접선만 자유**(핀에 끼운 채 돈다).

    셋 중 하나라도 놓치면 구속이 통째로 달라진다 — 접선을 고정하면 돌지 못한다.
    """
    found = conditions.read(_point("조건_원통_SI"))

    cylinder = next(one for one in found.constraints if one.kind == "cylindrical")
    assert cylinder.region == "구멍면"
    assert (cylinder.radial, cylinder.axial, cylinder.tangential) == ("fixed", "fixed", "free")
    # 힘 · 베어링 하중은 모달에서 넘긴다.
    assert len(found.skipped) >= 2
    assert found.refused == []
    # 해석 설정도 함께 온다 — 모드 수 · 주파수 범위.
    assert found.analysis.kind == "modal"
    assert found.analysis.modes == 8
    assert found.analysis.frequency_range == (0.0, 5000.0)


def test_접촉_종류가_점마다_바뀐다() -> None:
    """`조건_조건훑기` — 1 · 2번은 본딩, 3 · 4번은 마찰(계수 0.2).

    접촉이 바뀌면 고유진동수가 바뀐다 — 안 읽으면 네 점이 같은 답을 낸다.
    """
    bonded = conditions.read(_point("조건_조건훑기", 1))
    frictional = conditions.read(_point("조건_조건훑기", 3))

    assert [one.kind for one in bonded.contacts] == ["bonded"]
    assert [one.kind for one in frictional.contacts] == ["frictional"]
    assert frictional.contacts[0].friction == 0.2
    assert bonded.refused == [] and frictional.refused == []


def test_메시_힌트는_선언된_계로_온다() -> None:
    """`조건_원통_SI` 는 SI 로 내보낸 폴더다 — 2 mm 힌트가 **0.002 m** 로 실려 온다.

    숫자만 읽고 mm 로 넘기면 메시가 1000배 잘다.
    """
    found = conditions.read(_point("조건_원통_SI"))
    hint = next(one for one in found.mesh_hints if one.element_size is not None)
    assert hint.element_size == 0.002


def test_조건이_없으면_빈_것이다() -> None:
    """형상만 온 폴더 — 오류가 아니다. 그때는 사람이 준 스펙으로 돈다."""
    found = conditions.read(_point("브래킷_두께훑기-3f9a2177"))
    assert found.empty and not found.refused


def test_없는_자리를_가리키면_막는다() -> None:
    """CAD 가 못 푼 그룹을 가리키는 구속 — **그대로 두면 구속 없는 해석이 끝까지 돈다.**"""
    payload = _point("조건_두바디_두재료")
    payload["conditions"]["constraints"][0]["on"] = "없는면"
    found = conditions.read(payload)
    assert found.constraints == []
    assert any("없는면" in one.why for one in found.refused)


def _edges(count: int) -> list[dict[str, Any]]:
    """엣지 지문 — `midpoint` · `length`(CompCore 의 모양 그대로)."""
    return [{"midpoint": [float(index), 0.0, 4.0], "length": 8.0} for index in range(count)]


def test_면으로_선언하고_엣지_지문이_오면_막고_그렇다고_말한다() -> None:
    """CompCore 가 09-24 에 내보낸 「솔버 덱 함께」 — 「바닥」 을 **면으로 선언하고 엣지 지문
    15개를** 실었다(그때는 규칙에 `what` 이 없으면 엣지를 골랐다). 전에는 이 자리가 「반영」
    으로 지나가고 모델링에서야 「바닥[0] 엣지 그룹입니다」 로 멈췄다(2026-10-05). 고칠 자리가
    우리 창이 아니라 CompCore 의 내보내기라는 것까지 말한다."""
    payload = _point("조건_두바디_두재료")
    payload["regions"]["바닥"] = _edges(15)
    found = conditions.read(payload)
    assert found.constraints == []
    assert any(
        "면으로 선언했는데 지문은 엣지(edge) 15개" in one.why and "다시 내보내" in one.why
        for one in found.refused
    ), found.refused


def test_엣지_그룹에_걸린_접촉과_하중을_막는다() -> None:
    """매처는 면만 짝짓는다 — 접촉 · 하중도 같다. **모달의 하중은 답을 안 바꾸므로 넘긴다**
    (막으면 모달로 돌려 보는 것까지 막힌다). 정적이면 막는다."""
    payload = _point("조건_두바디_두재료")
    payload["regions"]["블록 아랫면"] = _edges(4)
    payload["regions"]["블록 윗면"] = _edges(4)
    for one in payload["conditions"]["named_selections"]:
        if one["name"] in ("블록 아랫면", "블록 윗면"):
            one["entity"] = "edge"
    modal = conditions.read(payload)
    assert modal.contacts == []
    assert any("「블록 아랫면」 은 엣지(edge) 그룹" in one.why for one in modal.refused)
    assert not any("누름" in one.what for one in modal.refused)
    static = conditions.read(payload, recipe="static")
    assert static.loads == []
    assert any("누름" in one.what and "엣지(edge)" in one.why for one in static.refused)


def test_모르는_구속은_막는다() -> None:
    """종류가 늘어도 **모르면 걸지 않는다**.

    짐작해서 비슷한 것을 걸면 답이 조용히 달라진다.
    """
    payload = _point("조건_두바디_두재료")
    payload["conditions"]["constraints"][0]["type"] = "spring_support"
    found = conditions.read(payload)
    assert any("spring_support" in one.why for one in found.refused)


def test_조건_줄에_면_수가_붙는다() -> None:
    """**면 수가 안 보이면 줄어든 것을 모른다.**

    CompCore v0.4.0(2026-10-02)부터 선택 규칙 `near` 가 「가장 가까운 **하나**」 로 바뀌었다.
    볼트 구멍 넷을 잡던 규칙이 하나만 잡아도 조건의 이름(`fixed_support · bolt_holes`)은
    똑같다 — 그러면 주파수만 조용히 달라진다. 그래서 화면 줄에 **몇 면으로 풀렸는지**를 적는다.
    """
    from app.modules.simulations.services import conditions_out

    out = conditions_out(_point("조건_두바디_두재료"), recipe="static")

    constraint = next(one for one in out.lines if one.kind == "constraint")
    assert constraint.detail == "fixed_support · 바닥 · 면 1"
    load = next(one for one in out.lines if one.kind == "load" and one.status == "applied")
    assert load.detail.endswith("· 면 1")


def _with_settings(settings: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _point("조건_측면가진")
    payload["conditions"]["body_settings"] = settings
    return payload


def test_파트별_설정을_읽는다() -> None:
    """CompCore 제안(2026-10-04)의 예 그대로 — 강체 · 메시 · 해석 제외."""
    found = conditions.read(
        _with_settings(
            [
                {
                    "name": "받침판",
                    "behavior": "rigid",
                    "representation": "solid",
                    "suppressed": False,
                    "mesh": {
                        "element_size": 4,
                        "method": "automatic",
                        "order": "program_controlled",
                    },
                },
                {"name": "기둥", "mesh": {"element_size": 1.5, "order": "quadratic"}},
                {"name": "표시나사", "suppressed": True},
            ]
        )
    )
    assert found.refused == []
    by_name = {one.name: one for one in found.body_settings}
    assert by_name["받침판"].rigid and by_name["받침판"].element_size == 4
    assert by_name["기둥"].order == "quadratic" and not by_name["기둥"].rigid
    assert found.suppressed == {"표시나사"}
    assert found.rigid == {"받침판"}
    assert by_name["받침판"].describe() == "강체 · 요소 4"
    assert by_name["표시나사"].describe() == "해석 제외"


def test_중간면이_없는_쉘_파트는_막는다() -> None:
    """**솔리드로 풀지 않는다** — 쉘로 둔 판을 솔리드로 풀면 강성이 다른 모델이 되고, 사람은
    쉘로 풀었다고 읽는다. 점 파일에 그 파트의 중간면이 없거나 CompCore 가 못 만들었으면
    (`midsurface.failed[]`) 그 까닭을 단다. 뺀 파트면 표현은 상관없다."""
    payload = _with_settings(
        [
            {"name": "받침판", "representation": "shell"},
            {"name": "기둥", "representation": "shell", "suppressed": True},
        ]
    )
    found = conditions.read(payload)
    assert [one.what for one in found.refused] == ["파트 「받침판」 쉘 표현"]
    assert "중간면" in found.refused[0].why
    assert [one.name for one in found.body_settings] == ["기둥"]

    payload["midsurface"] = {"failed": [{"name": "받침판", "error": "판이 아닙니다."}]}
    failed = conditions.read(payload)
    assert "판이 아닙니다" in failed.refused[0].why


SHELL_FOLDER = "조건_강체지그_쉘브래킷"


def test_쉘_파트를_중간면과_두께로_읽는다() -> None:
    """CompCore v0.8.1 — 중간면은 쉘 파트만, 두께는 `midsurface.bodies[]`, 쉘 파트의 영역은
    지문의 `mid`(중간면의 면 · 모서리 · 점)."""
    payload = _point(SHELL_FOLDER)
    found = conditions.read(payload, recipe="static")
    assert found.refused == []
    assert found.shells == {"브래킷": 2.0}
    assert found.rigid == {"지그블록"} and found.suppressed == {"명판"}
    view = conditions.shell_view(payload, set(found.shells))
    # 겉면은 중간면의 면 — 앞뒤가 없고(`two_sided`), 원래 바깥 법선이 남는다(미는 쪽).
    (face,) = view["regions"]["하중면"]
    assert face["two_sided"] and face["outer_normal"] == [1.0, 0.0, 0.0]
    assert face["centroid"] == [49.0, 0.0, 48.0]  # x = 50 - t/2
    # 쉘이 아닌 파트의 지문은 그대로다.
    assert view["regions"]["블록 윗면"] == payload["regions"]["블록 윗면"]
    # 두께 쪽 면은 중간면의 모서리다 — 거기 건 조건은 아직 못 건다(이 픽스처는 조건에 안 쓴다).
    assert "midpoint" in view["regions"]["브래킷 앞끝"][0]

    payload["conditions"]["constraints"].append(
        {"name": "끝 고정", "type": "fixed_support", "on": "브래킷 앞끝"}
    )
    edged = conditions.read(payload, recipe="static")
    assert any("모서리" in one.why for one in edged.refused)


def test_뺀_파트에_걸린_조건은_가려_낸다() -> None:
    """CompCore 는 저장할 때 막지만, 왔으면 **엉뚱한 면을 집기 전에** 까닭을 단다.

    실측(2026-10-04): 기둥을 빼고 「접합 기둥쪽」 접촉을 두었더니 Ansys 가 받침판의 맞닿은
    면을 집고 「법선이 180도 틀어져 있다」 로 멈췄다 — 고칠 곳을 가리키지 않는 말이다.
    """
    gone_column = conditions.read(_with_settings([{"name": "기둥", "suppressed": True}]))
    # 접촉은 한쪽이 없으면 없다 — 넘긴다. 모달의 하중은 원래 답과 상관없다.
    assert gone_column.contacts == [] and gone_column.refused == []
    assert any("접촉" in one.what and "기둥" in one.why for one in gone_column.skipped)

    static = conditions.read(
        _with_settings([{"name": "기둥", "suppressed": True}]), recipe="harmonic"
    )
    assert any(one.what.startswith("하중") for one in static.refused)

    gone_plate = conditions.read(_with_settings([{"name": "받침판", "suppressed": True}]))
    assert gone_plate.constraints == []
    assert any("뺀 파트(받침판)" in one.why for one in gone_plate.refused)


def test_모르는_거동은_막고_모르는_메시_칸은_넘긴다() -> None:
    """거동은 답을 바꾸므로 막고, 메시 칸은 바람이므로 적고 넘어간다."""
    found = conditions.read(
        _with_settings(
            [
                {"name": "받침판", "behavior": "elastic"},
                {"name": "기둥", "mesh": {"method": "voxel", "element_size": "=t/2"}},
                {"name": "기둥", "suppressed": True},
            ]
        )
    )
    refused = [one.what for one in found.refused]
    assert refused == ["파트 「받침판」", "파트 「기둥」"]  # 모르는 거동 · 두 줄
    assert {one.what for one in found.skipped} >= {
        "파트 「기둥」 요소 형상",
        "파트 「기둥」 요소 크기",
    }
    column = found.body_settings[0]
    assert column.method == "automatic" and column.element_size is None


def test_국부_메시_규칙을_따른다() -> None:
    """CompCore 2026-10-04 — 메시 힌트는 「국부 메시」 다.

    - 「전체」 는 크기 · 요소 형상 · 차수를 함께 싣는다.
    - **바디 그룹에 건 옛 힌트는 그 파트의 파트 메시로** 읽는다(파트별 설정에 크기가 따로
      있으면 그것이 이긴다).
    - 엣지 그룹은 아직 못 건다 — 조용히 버리지 않고 적는다.
    """
    payload = _point("조건_측면가진")
    block = payload["conditions"]
    block["named_selections"] = [
        {"name": "기둥 통째", "entity": "body"},
        {"name": "판 통째", "entity": "body"},
        {"name": "기둥 모서리", "entity": "edge"},
    ]
    payload["regions"]["기둥 통째"] = [{"centroid": [0, 0, 50], "body": "기둥"}]
    payload["regions"]["판 통째"] = [{"centroid": [0, 0, 5], "body": "받침판"}]
    payload["regions"]["기둥 모서리"] = [
        {"midpoint": [5, 5, 50], "length": 80, "body": "기둥"}
    ]
    block["mesh_hints"] = [
        {"on": "전체", "element_size": 2, "method": "hex_dominant", "order": "linear"},
        {"on": "기둥 통째", "element_size": 1},
        {"on": "판 통째", "element_size": 3},
        {"on": "기둥 모서리", "element_size": 0.5},
    ]
    block["body_settings"] = [
        {"name": "받침판", "behavior": "rigid", "mesh": {"element_size": 8}}
    ]
    found = conditions.read(payload)

    whole = found.whole_mesh
    assert whole is not None
    assert (whole.element_size, whole.method, whole.order) == (2, "hex_dominant", "linear")
    sizes = {one.name: one.element_size for one in found.body_settings}
    # 기둥은 옛 힌트로 파트 메시가 생기고, 받침판은 파트별 설정의 8 이 이긴다.
    assert sizes == {"받침판": 8, "기둥": 1}
    assert next(one for one in found.body_settings if one.name == "받침판").rigid
    whats = {one.what for one in found.skipped}
    assert "국부 메시 「기둥 모서리」(엣지)" in whats
    assert "국부 메시 「판 통째」" in whats
    # 면 · 엣지로 옮겨 간 것은 국부 힌트로 남지 않는다.
    assert [one.region for one in found.mesh_hints] == ["전체"]

    note = conditions.whole_order_note(found, "quadratic")
    assert note is not None and "1차" in note.why and "2차" in note.why
    assert conditions.whole_order_note(found, "linear") is None


def test_비례_정련은_파트와_면_크기를_같은_비율로_줄이고_전체는_두다() -> None:
    """메시 수렴 점검 — 전체 크기만 줄이면 CAD 가 크기를 적은 파트 · 면은 그대로라 정련이
    고르지 않았다. 「전체」 는 점검 수준이 스펙에 직접 적으므로 건드리지 않는다."""
    payload = _with_settings([{"name": "기둥", "mesh": {"element_size": 1.5}}])
    payload["conditions"]["mesh_hints"].append({"on": "기둥 끝", "element_size": 0.8})
    found = conditions.read(payload)
    half = conditions.scaled(found, 0.5)
    assert {one.name: one.element_size for one in half.body_settings} == {"기둥": 0.75}
    sizes = {one.region: one.element_size for one in half.mesh_hints}
    assert sizes == {"전체": 2.0, "기둥 끝": 0.4}
    # 원본은 그대로, 1 이면 같은 것.
    assert {one.name: one.element_size for one in found.body_settings} == {"기둥": 1.5}
    assert conditions.scaled(found, 1) is found
