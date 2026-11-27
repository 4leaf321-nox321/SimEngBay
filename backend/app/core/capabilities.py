"""능력표 — 솔버마다 **CompCore 조건에서 무엇을 받나**(CompCore 해석-확장-설계 5장).

CompCore 는 케이스의 대상 솔버(`target.solver`)로 저장 · 내보내기 때 이 표를 겹쳐
거르고, 화면에 「이 솔버가 아직 받지 않음」 을 붙인다. 표는 **1차 거르기**다 — 자리 · 방향 ·
크기처럼 값을 봐야 아는 것은 작업을 만들 때(`services.conditions_gap`)와 모델링이 판정한다.

## 손으로 적지 않는다

목록은 받는 코드의 표에서 끌어온다 — 조건 읽기(`conditions`), CalculiX 덱(`calculix.deck`),
Ansys 빌드(`mechanical.build`), 물성(`materials`). 해석마다 갈리는 규칙도 그 자리의 상수다
(`PRESTRESS_RECIPES` · `HARMONIC_REFUSED_LOADS` · `ANALYSIS_FIELDS`). 시험
(`tests/unit/test_capabilities.py`)이 종류마다 점 파일을 지어 **실제 조건 읽기와 만들 때
점검**에 넣고 표와 견준다 — 표와 코드가 어긋나면 그 시험이 깨진다.

## 항목의 뜻

- 이름만 — 받고 쓴다.
- `{"name", "note"}` — 받되 조건이 붙는다(선응력일 때만 쓰는 하중, 선형화하는 접촉 …).
- 표에 없음 — 막거나(작업을 만들 때 까닭과 함께), 그 해석에서 뜻이 없어 쓰지 않는다(조화
  응답의 가속도 PSD 처럼 — 조건 처리 알림에 적는다).

`fields.<묶음>` 은 그 해석에서 그 묶음의 **읽는 칸 전부**다(CompCore 와 정함 — 묶음이 없으면
거르지 않는다). `analysis` 의 없는 칸(정적의 `steps` · `solver`)은 지금 말없이 안 읽히던 것이라
「받지 않음」 으로 보인다. `loads` 에는 `curve` 가 없다 — CompCore 가 표로 풀어 보낸다.
"""

from __future__ import annotations

from typing import Any

from app.core import cases as core_cases
from app.core import conditions as condition_model
from app.core import materials
from app.core.calculix import deck as calculix_deck
from app.core.mechanical.build import PRESTRESS_RECIPES as ANSYS_PRESTRESS
from app.core.mechanical.build import SUPPORTED_CONSTRAINTS as ANSYS_CONSTRAINTS
from app.core.mechanical.build import SUPPORTED_CONTACTS as ANSYS_CONTACTS
from app.core.mechanical.build import SUPPORTED_LOADS as ANSYS_LOADS

#: 표를 내는 솔버 — 작업 스펙의 `solver` 값과 같은 이름이다.
SOLVERS = ("calculix", "ansys")
#: 받는 해석 — 두 솔버가 같다(`calculix.deck.SUPPORTED_RECIPES`, Ansys 빌드도 넷). 명시적
#: 동해석 · 열은 없다.
RECIPES = calculix_deck.SUPPORTED_RECIPES
#: 접촉 · 지지를 **선형화하는** 해석 — 모드를 풀고 그 위에서 셈한다.
LINEARIZED = ("modal", "harmonic", "random")


def _tag(name: str) -> str:
    """CompCore 화면의 칸 이름표 — 작은 꺾쇠 따옴표(U+2018 · U+2019)로 감싼다."""
    return f"\u2018{name}\u2019"


#: note 는 CompCore 화면(대상 솔버를 지정한 해석 케이스의 준비 점검)에 글자 그대로 나간다 —
#: 그쪽 화면 규칙대로 줄표로 잇지 않고, 낱말 · 칸 이름표는 CompCore 의 것이다(2026-11-27 정함).
PRESTRESS_LOAD = (
    "해석 케이스에서는 선응력을 만드는 하중을 앞 정적 케이스에 적습니다. 해석 케이스가 없는"
    f" 조건에서는 {_tag('선응력 반영')}을 켤 때만 앞 정적에 겁니다(끄면 고유진동수를"
    " 바꾸지 않아 쓰지 않습니다)."
)
TWO_STEP_BOLT = (
    "한 해석 안에서는 먼저 조이고, 그 길이를 잠근 채 나머지 하중을 겁니다(두 단계)."
    " 앞 케이스에서 조인 볼트는 뒤 케이스에서 그 길이로 잠긴 채 이어집니다."
)
LINEAR_BONDED = "모드 · 주파수 해석에서는 붙은 것으로 풉니다"
LINEAR_SLIDING = "모드 · 주파수 해석에서는 법선만 묶어 미끄러지게 풉니다"
LINEAR_SUPPORT = "모드 · 주파수 해석에서는 닿은 채로(같은 강성의 법선 스프링) 풉니다"
TEMPERATURE = "물성 기준 온도로만 씁니다. 열 변형은 풀지 않습니다."
PRESTRESS = (
    "해석 케이스에서는 앞 정적 케이스가 선응력을 정하므로 적지 않습니다. 해석 케이스가 없는"
    f" 조건에서는 {_tag('선응력 반영')}과 함께 씁니다. {_tag('선행 정적 해석')} 입력란은"
    " 아직 받지 않습니다."
)
PSD_AXES_ONLY = "가진 방향은 X · Y · Z 축만 받습니다"


def analyses(solver: str) -> dict[str, dict[str, Any]]:
    """해석마다 받는 항목 · 칸 · 재료 — 능력표의 `analyses`."""
    if solver not in SOLVERS:
        raise ValueError(f"모르는 솔버입니다: {solver}")
    return {recipe: _analysis(solver, recipe) for recipe in RECIPES}


def _analysis(solver: str, recipe: str) -> dict[str, Any]:
    linear = recipe in LINEARIZED
    prestress = recipe in prestress_recipes(solver)
    return {
        "constraints": [
            _noted(kind, LINEAR_SUPPORT if linear and kind == "compression_only" else "")
            for kind in condition_model.CONSTRAINT_KINDS
            if kind in _supports(solver)
        ],
        "loads": _loads(solver, recipe, prestress=prestress),
        "contacts": [
            _noted(kind, _contact_note(kind) if linear else "")
            for kind in condition_model.CONTACT_KINDS
            if kind in _contacts(solver)
        ],
        "initial": [
            _noted("environment_temperature", TEMPERATURE),
            *([_noted("prestress", PRESTRESS)] if prestress else []),
        ],
        "fields": {
            "analysis": [
                one
                for one in condition_model.ANALYSIS_FIELDS[recipe]
                if one != "prestressed" or prestress
            ],
            "loads": _load_fields(recipe, prestress=prestress),
        },
        "materials": list(materials.MODELS),
        "follows": follows(solver, recipe),
    }


def follows(solver: str, recipe: str) -> list[str]:
    """앞 케이스로 올 수 있는 해석(판 2 의 사슬) — 비면 사슬의 첫 케이스로만 온다.

    앞 케이스는 정적만이다(`cases.LEADS` — 끝 상태를 남긴다). 정적은 정적 뒤에 오고, 선응력을
    받는 해석(`prestress_recipes` — 그 솔버가 받는 것)도 정적 뒤에 온다. 조화 응답은 선응력을
    받지
    않아 첫 케이스로만 온다."""
    if recipe == "static" or recipe in prestress_recipes(solver):
        return list(core_cases.LEADS)
    return []


def _load_fields(recipe: str, *, prestress: bool) -> list[str]:
    """그 해석에서 읽는 하중 칸 전부 — 모달 · 랜덤의 보통 하중 칸은 선응력을 받을 때만, 랜덤은
    가속도 PSD 의 칸이 늘 있다."""
    wanted: set[str] = set()
    if recipe in ("static", "harmonic") or prestress:
        wanted |= set(condition_model.LOAD_FIELDS[recipe])
    if recipe == "random":
        wanted |= set(condition_model.PSD_FIELDS)
    return [one for one in condition_model.LOAD_FIELD_ORDER if one in wanted]


def prestress_recipes(solver: str) -> tuple[str, ...]:
    """그 솔버가 선응력을 받는 해석 — 조건 읽기의 것에서 솔버가 더 좁힌다."""
    narrower = ANSYS_PRESTRESS if solver == "ansys" else condition_model.PRESTRESS_RECIPES
    return tuple(one for one in condition_model.PRESTRESS_RECIPES if one in narrower)


def _loads(solver: str, recipe: str, *, prestress: bool) -> list[str | dict[str, str]]:
    supported = [one for one in condition_model.LOAD_KINDS if one in _load_kinds(solver)]
    if recipe == "static":
        return [
            _noted(one, TWO_STEP_BOLT if one == "bolt_pretension" else "") for one in supported
        ]
    if recipe == "harmonic":
        return [one for one in supported if one not in condition_model.HARMONIC_REFUSED]
    quiet = [_noted(one, PRESTRESS_LOAD) for one in supported] if prestress else []
    if recipe == "random":
        return [_noted("psd_acceleration", PSD_AXES_ONLY if solver == "ansys" else ""), *quiet]
    return quiet


def _supports(solver: str) -> set[str]:
    if solver == "ansys":
        return set(ANSYS_CONSTRAINTS)
    return {*calculix_deck.SUPPORTED_CONSTRAINTS, *calculix_deck.REMOTE_CONSTRAINTS}


def _load_kinds(solver: str) -> set[str]:
    if solver == "ansys":
        return set(ANSYS_LOADS)
    return set(calculix_deck.SUPPORTED_LOADS)


def _contacts(solver: str) -> set[str]:
    if solver == "ansys":
        return set(ANSYS_CONTACTS)
    return set(calculix_deck.LINEARIZED_CONTACTS)


def _contact_note(kind: str) -> str:
    if kind in ("frictional", "rough"):
        return LINEAR_BONDED
    if kind in ("no_separation", "frictionless"):
        return LINEAR_SLIDING
    return ""


def _noted(name: str, note: str) -> str | dict[str, str]:
    return {"name": name, "note": note} if note else name
