"""능력표가 **받는 코드와 같은 말을 하나** — 종류마다 점 파일을 지어 실제 조건 읽기와 만들 때
점검(`services.conditions_gap` 의 솔버 점검)에 넣고 표와 견준다.

표의 뜻(`app/core/capabilities.py`):
- 이름만 → 막지도 넘기지도 않는다(받고 쓴다).
- `{name, note}` → 막지 않는다. 선응력 note 면 선응력을 켰을 때 쓴다.
- 표에 없음 → 막거나 넘긴다(그 해석에서 안 쓴다).
"""

from __future__ import annotations

import json
import typing
from pathlib import Path
from typing import Any

import pytest

from app.core import capabilities, cases, conditions
from app.core.calculix import deck as calculix_deck
from app.core.mechanical.build import unsupported as ansys_unsupported
from app.core.spec import RUNNABLE_RECIPES, ModalSpec
from app.modules.simulations import services

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "doe"

#: CompCore 등록부의 종류 전부(CompCore `conditions/registry.py` 의 `ITEMS`) — 표가 고를 우주.
COMPCORE_ITEMS = {
    "constraints": (
        "fixed_support",
        "displacement",
        "remote_displacement",
        "frictionless",
        "cylindrical",
        "compression_only",
        "elastic_support",
    ),
    "loads": (
        "pressure",
        "force",
        "moment",
        "bearing",
        "bolt_pretension",
        "standard_earth_gravity",
        "acceleration",
        "rotational_velocity",
        "psd_acceleration",
    ),
    "contacts": ("bonded", "no_separation", "frictional", "frictionless", "rough"),
    "initial": ("environment_temperature", "velocity", "temperature", "prestress"),
}
#: CompCore 등록부가 해석마다 내는 해석 설정 칸(`ANALYSES[*].fields`).
COMPCORE_FIELDS = {
    "modal": ("modes", "frequency_range", "prestressed", "solver"),
    "static": ("large_deflection", "steps", "substeps", "solver"),
    "harmonic": (
        "modes",
        "frequency_range",
        "solution_intervals",
        "method",
        "damping_ratio",
        "solver",
    ),
    "random": ("modes", "frequency_range", "prestressed", "damping_ratio", "solver"),
}
PSD = {
    "name": "랜덤 가진",
    "type": "psd_acceleration",
    "psd_table": [[10, 0.01], [100, 0.01]],
    "unit": "g^2/Hz",
    "direction": [0, 0, 1],
}
FORCE = {"name": "힘", "type": "force", "on": "면A", "magnitude": 1, "unit": "N"}


def _row(group: str, kind: str) -> dict[str, Any]:
    if group == "constraints":
        return {"name": "구속", "type": kind, "on": "면A", "stiffness": 1.0}
    if group == "contacts":
        return {"name": "접촉", "type": kind, "source": "면A", "target": "면B"}
    if group == "initial":
        return {"type": kind, "value": 22, "unit": "C"}
    if kind == "psd_acceleration":
        return dict(PSD)
    return {
        "name": "하중",
        "type": kind,
        "on": "면A",
        "magnitude": 1,
        "unit": "N",
        "direction": [0, 0, 1],
        "preload": 100,
    }


def _payload(recipe: str, group: str, kind: str, *, prestressed: bool) -> dict[str, Any]:
    block: dict[str, Any] = {
        "analysis": {"type": recipe, "prestressed": prestressed},
        "named_selections": [
            {"name": "면A", "entity": "face"},
            {"name": "면B", "entity": "face"},
        ],
        "constraints": [],
        "loads": [],
        "contacts": [],
        "initial": [],
    }
    block[group].append(_row(group, kind))
    if recipe == "random" and kind != "psd_acceleration":
        block["loads"].append(dict(PSD))  # 랜덤의 가진 — 없으면 그 해석이 아니다
    if group == "initial" and kind == "prestress":
        block["loads"].append(dict(FORCE))  # 선응력은 하중이 있어야 뜻이 있다
    return {"schema_version": 1, "regions": {"면A": {}, "면B": {}}, "conditions": block}


def _verdict(solver: str, recipe: str, payload: dict[str, Any]) -> tuple[bool, bool]:
    """(막았나, 넘겼나) — 작업을 만들 때와 같은 점검."""
    given = conditions.read(payload, recipe=recipe)
    if solver == "calculix":
        blocked = calculix_deck.unsupported(given)
    else:
        blocked = ansys_unsupported(given, recipe)
    return bool(given.refused or blocked), bool(given.skipped)


def _listed(table: dict[str, Any], recipe: str, group: str) -> dict[str, str]:
    """표의 항목 → note(이름만이면 빈 말)."""
    return {
        one if isinstance(one, str) else one["name"]: ""
        if isinstance(one, str)
        else one["note"]
        for one in table[recipe][group]
    }


CASES = [
    (solver, recipe, group, kind)
    for solver in capabilities.SOLVERS
    for recipe in capabilities.RECIPES
    for group, kinds in COMPCORE_ITEMS.items()
    for kind in kinds
]


@pytest.mark.parametrize(("solver", "recipe", "group", "kind"), CASES)
def test_표의_항목은_받는_코드와_같은_말을_한다(
    solver: str, recipe: str, group: str, kind: str
) -> None:
    listed = _listed(capabilities.analyses(solver), recipe, group)
    off_refused, off_skipped = _verdict(
        solver, recipe, _payload(recipe, group, kind, prestressed=False)
    )
    on_refused, on_skipped = _verdict(
        solver, recipe, _payload(recipe, group, kind, prestressed=True)
    )
    if kind not in listed:
        # 표에 없으면 받는 코드도 막거나 넘긴다 — 선응력을 켜도 마찬가지다.
        assert off_refused or off_skipped, "표에는 없는데 받는 코드는 받는다"
        assert on_refused or on_skipped, "표에는 없는데 선응력을 켜면 받는다"
        return
    assert not off_refused, "표에는 있는데 받는 코드가 막는다"
    note = listed[kind]
    if note in (capabilities.PRESTRESS_LOAD, capabilities.PRESTRESS):
        # 선응력일 때만 쓰는 것 — 켜면 막지도 넘기지도 않는다.
        assert not on_refused and not on_skipped, "선응력을 켜도 쓰지 않는다"
        if note == capabilities.PRESTRESS_LOAD:
            assert off_skipped, "선응력을 끄면 쓰지 않는다고 알려야 한다"
    elif not note:
        assert not off_skipped, "표에는 조건 없이 있는데 받는 코드가 넘긴다"


def test_해석_설정_칸은_읽는_칸만_싣는다() -> None:
    """조건 읽기가 실제로 묻는 칸 = 표에 실린 칸 전부(+ 종류). CompCore 의 칸 중 나머지는
    「받지 않음」 이다."""
    asked: set[str] = set()

    class Spy(dict[str, Any]):
        def get(self, key: str, default: Any = None) -> Any:
            asked.add(key)
            return super().get(key, default)

    conditions._analysis(Spy())
    declared = {one for fields in conditions.ANALYSIS_FIELDS.values() for one in fields}
    assert asked - {"type"} == declared
    for recipe, fields in conditions.ANALYSIS_FIELDS.items():
        assert set(fields) <= set(COMPCORE_FIELDS[recipe]), recipe
    for solver in capabilities.SOLVERS:
        table = capabilities.analyses(solver)
        for recipe in capabilities.RECIPES:
            shown = table[recipe]["fields"]["analysis"]
            assert ("prestressed" in shown) == (
                recipe in capabilities.prestress_recipes(solver)
            ), (solver, recipe)
            assert "steps" not in shown and "solver" not in shown


class _Spy(dict[str, Any]):
    """읽힌 칸을 적는 줄 — 조건 읽기가 실제로 묻는 칸을 모은다."""

    def __init__(self, row: dict[str, Any], asked: set[str]) -> None:
        super().__init__(row)
        self.asked = asked

    def get(self, key: str, default: Any = None) -> Any:
        self.asked.add(key)
        return super().get(key, default)

    def __getitem__(self, key: str) -> Any:
        self.asked.add(key)
        return super().__getitem__(key)


@pytest.mark.parametrize("recipe", capabilities.RECIPES)
def test_하중_칸은_읽는_칸만_싣는다(recipe: str) -> None:
    """`fields.loads` = 그 해석에서 하중 줄에서 실제로 읽는 칸 전부(선응력을 켰을 때). 랜덤의
    가속도 PSD 는 따로 센다. CompCore 가 그 묶음을 이 목록으로 거른다."""
    plain: set[str] = set()
    shaken: set[str] = set()
    payload = _payload(recipe, "loads", "force", prestressed=True)
    payload["conditions"]["loads"] = [
        _Spy(_row("loads", kind), plain)
        for kind in COMPCORE_ITEMS["loads"]
        if kind != "psd_acceleration"
    ] + ([_Spy(dict(PSD), shaken)] if recipe == "random" else [])
    conditions.read(payload, recipe=recipe)
    assert plain == set(conditions.LOAD_FIELDS[recipe])
    if recipe == "random":
        assert shaken == set(conditions.PSD_FIELDS)
    for solver in capabilities.SOLVERS:
        shown = capabilities.analyses(solver)[recipe]["fields"]["loads"]
        wanted = set(conditions.PSD_FIELDS) if recipe == "random" else set()
        if recipe in ("static", "harmonic") or recipe in capabilities.prestress_recipes(
            solver
        ):
            wanted |= plain
        assert shown == [one for one in conditions.LOAD_FIELD_ORDER if one in wanted]
        assert "curve" not in shown


def test_솔버와_해석은_작업_스펙과_같은_이름이다() -> None:
    literal = typing.get_args(ModalSpec.model_fields["solver"].annotation)
    assert set(capabilities.SOLVERS) == set(literal) == set(services.SOLVERS)
    assert set(capabilities.RECIPES) == set(RUNNABLE_RECIPES)


def test_솔버마다_갈리는_곳() -> None:
    calculix = capabilities.analyses("calculix")
    ansys = capabilities.analyses("ansys")
    # Ansys 랜덤은 선응력이 없어 가진만 받는다.
    assert _listed(ansys, "random", "loads") == {
        "psd_acceleration": capabilities.PSD_AXES_ONLY
    }
    assert "prestress" not in _listed(ansys, "random", "initial")
    assert "prestress" in _listed(calculix, "random", "initial")
    # 조화는 두 솔버 모두 선응력 · 볼트 · 회전 속도 · 중력을 받지 않는다(중력은 사용자가 두
    # 솔버 모두 막기로 정했다 — Mechanical 은 실측으로 못 푼다).
    for table in (calculix, ansys):
        assert "prestress" not in _listed(table, "harmonic", "initial")
        assert "prestressed" not in table["harmonic"]["fields"]["analysis"]
        assert _listed(table, "harmonic", "loads") == {
            "pressure": "",
            "force": "",
            "moment": "",
            "bearing": "",
            "acceleration": "",
        }
        assert table["static"]["materials"] == ["linear_elastic"]


def test_모르는_솔버는_표를_내지_않는다() -> None:
    with pytest.raises(ValueError, match="모르는 솔버"):
        capabilities.analyses("abaqus")


@pytest.mark.parametrize("solver", capabilities.SOLVERS)
@pytest.mark.parametrize("recipe", capabilities.RECIPES)
def test_follows_는_받는_코드와_같은_말을_한다(solver: str, recipe: str) -> None:
    """「볼트 예압 → 그 해석」 사슬 — `follows` 에 정적이 있으면 사슬 규칙 · 만들 때 점검을
    지나고, 없으면 어느 한쪽이 막는다."""
    payload = json.loads(
        (FIXTURES / "조건_볼트예압_두케이스_솔버없음" / "points" / "p0001.json").read_text()
    )
    end = payload["conditions"]["cases"][1]
    end["analysis"] = {"type": recipe}
    if recipe == "random":
        end["loads"] = [dict(PSD)]
    elif recipe == "modal":
        end["loads"] = []
    [chain] = cases.chains(payload)[0]
    why = cases.problem(chain)
    blocked = bool(why)
    if not why:
        given = conditions.read(cases.view(payload, chain), recipe=recipe)
        refused = given.refused or (
            calculix_deck.unsupported(given)
            if solver == "calculix"
            else ansys_unsupported(given, recipe)
        )
        blocked = bool(refused)
    follows = capabilities.analyses(solver)[recipe]["follows"]
    assert ("static" in follows) == (not blocked), (solver, recipe, why)
