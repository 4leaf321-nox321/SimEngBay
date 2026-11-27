"""해석 케이스(v2 — `schema_version: 2` · `cases[]`) → **작업 하나가 읽는 조건 한 벌**.

CompCore 는 조건을 공유 칸 한 벌과 케이스 여럿으로 나눈다(CompCore 해석-확장-설계 2장).
케이스는
`{name, depends_on, target: {solver}, analysis, constraints, loads, initial}` 이고,
`depends_on` 은
「앞 케이스의 끝 상태(변위 · 응력 · 접촉 상태)에서 시작하고, 앞에서 조인 볼트는 조인 길이로
잠근다」 는 뜻이다. **하중은 이어지지 않는다** — 케이스의 `loads` 가 그 케이스에 걸린 하중
전부다(SimEngBay 와 정함 2026-11-26).

## 사슬 하나 = 작업 하나

한 케이스 뒤에는 하나만 온다(갈래는 CompCore 가 저장에서 막는다). 그래서 케이스들은 **사슬**로
갈리고, 아무도 앞 케이스로 삼지 않은 케이스가 사슬의 끝이다. 작업은 사슬마다 하나이고 끝
케이스의 해석 종류가 레시피다. 무관한 케이스는 길이 1 인 사슬이다.

## 케이스 보기 — v1 모양 한 벌로 편다

작업을 만들 때 점 파일을 사슬마다 **v1 모양**(맨 위에 해석 하나)으로 편 한 벌을 작업에 담는다
(`view`). 그 뒤로 조건을 읽는 자리(물성 · 쉘 · 파트 설정 · 두 솔버의 모델링 · 추출)는 v1 을
읽던
그대로다. 보기의 `conditions.case` 에 어느 사슬인지 적는다.

v1 으로 **정확히 접히는** 사슬은 보기 안에서 지금의 v1 길로 푼다 — CompCore 의 접기
(`cases.fold_chain`)와 같은 규칙이다:

- 정적 → 모달 · 랜덤: 하중 = 정적의 것, 해석 = 끝의 것 + `prestressed` (v1 선응력 모달 · 랜덤).
- 「예압」(볼트 예압 · 같은 중력뿐) → 외력(→ 모달 · 랜덤): 하중 = 예압 + 외력(중력은
  한 번). v1 은 볼트와 다른 하중이 한 벌에 있으면 「조임 → 잠그고 나머지」 두 단계로 푼다.

그 밖(볼트가 아닌 앞 정적 · 정적 셋 이상 · 케이스마다 다른 해석 설정)은 정적 다단이라 아직
막는다.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

#: 케이스 칸 — 보기에서 맨 위로 올라온다. 나머지(단위 · 선택 그룹 · 재료 · 접촉 · 파트 설정 ·
#: 메시 힌트 · 좌표계 · 곡선)는 공유다.
CASE_KEYS = ("analysis", "constraints", "loads", "initial")
#: 앞 케이스가 될 수 있는 해석 — 끝 상태(변위 · 응력 · 접촉)를 남기는 것.
LEADS = ("static",)
#: 모드를 푸는 해석 — 앞 정적의 끝 상태를 선응력으로 받는다.
EIGEN = ("modal", "random")
GRAVITY = "standard_earth_gravity"
BOLT = "bolt_pretension"

#: 케이스 안의 선응력 칸 — v2 에서는 앞 케이스가 선응력을 말한다(CompCore 도 저장에서 막는다).
PRESTRESS_IN_CASE = (
    "케이스에서는 앞 케이스(정적)를 지정해 선응력을 적습니다 — 이 케이스의 「선응력 반영」 · "
    "초기조건 「선응력」 은 받지 않습니다"
)


@dataclass(frozen=True)
class Case:
    name: str
    depends_on: str
    #: `target.solver` — 비면 작업의 솔버를 따른다.
    solver: str
    kind: str
    raw: dict[str, Any]

    def rows(self, key: str) -> list[dict[str, Any]]:
        value = self.raw.get(key)
        return (
            [one for one in value if isinstance(one, dict)] if isinstance(value, list) else []
        )

    @property
    def analysis(self) -> dict[str, Any]:
        value = self.raw.get("analysis")
        return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class Chain:
    """앞 케이스부터 끝 케이스까지 — 작업 하나."""

    cases: tuple[Case, ...]

    @property
    def end(self) -> Case:
        return self.cases[-1]

    @property
    def name(self) -> str:
        """사슬의 이름 = 끝 케이스의 이름(CompCore 화면과 같은 이름으로 찾는다)."""
        return self.end.name

    @property
    def kind(self) -> str:
        return self.end.kind

    @property
    def solver(self) -> str:
        return self.end.solver

    @property
    def leads(self) -> tuple[Case, ...]:
        return self.cases[:-1]


def is_cases(payload: Any) -> bool:
    """케이스로 나눈 조건인가 — **판이 2 이고** `cases` 가 있을 때만. 다른 판에 `cases` 가
    있으면 판 검사(`contract.problem`)가 막을 것이라 케이스로 읽지 않는다."""
    block = _block(payload)
    keys = ("schema_version", "version")
    declared = next((block.get(key) for key in keys if key in block), None)
    return (
        isinstance(block.get("cases"), list)
        and isinstance(declared, int | float)
        and not isinstance(declared, bool)
        and declared == 2
    )


def picked(payload: Any) -> str | None:
    """이미 편 보기(`view`)면 그 사슬의 이름 — 아니면 `None`."""
    case = _block(payload).get("case")
    return str(case.get("name") or "") or None if isinstance(case, dict) else None


def read(payload: Any) -> tuple[list[Case], str]:
    """점 파일의 케이스와 **점 전체를 막는 까닭**(이름 겹침 · 앞 케이스를 못 찾음 · 갈래)."""
    block = _block(payload)
    rows = block.get("cases")
    if not isinstance(rows, list) or not rows:
        return [], "조건의 판이 2 인데 해석 케이스(cases)가 없습니다"
    found: list[Case] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            return [], f"cases[{index}] 가 케이스가 아닙니다"
        name = str(row.get("name") or "").strip()
        if not name:
            return [], f"cases[{index}] 에 이름이 없습니다"
        if name in seen:
            return [], f"케이스 이름 「{name}」 이 두 번 있습니다"
        ahead = str(row.get("depends_on") or "").strip()
        if ahead and ahead not in seen:
            return [], (
                f"케이스 「{name}」 의 앞 케이스 「{ahead}」 가 그보다 앞에 없습니다"
                if ahead != name
                else f"케이스 「{name}」 가 자기 자신을 앞 케이스로 가리킵니다"
            )
        seen.add(name)
        target = row.get("target")
        analysis = row.get("analysis")
        found.append(
            Case(
                name=name,
                depends_on=ahead,
                solver=str((target or {}).get("solver") or "").strip()
                if isinstance(target, dict)
                else "",
                kind=str((analysis or {}).get("type") or "modal")
                if isinstance(analysis, dict)
                else "modal",
                raw=row,
            )
        )
    followers: dict[str, list[str]] = {}
    for one in found:
        if one.depends_on:
            followers.setdefault(one.depends_on, []).append(one.name)
    for ahead, after in followers.items():
        if len(after) > 1:
            return [], (
                f"케이스 「{ahead}」 뒤에 둘 이상({' · '.join(after)})이 옵니다 — 사슬만"
                " 받습니다(갈래는 앞 케이스를 다른 이름으로 하나 더 적습니다)"
            )
    return found, ""


def chains(payload: Any) -> tuple[list[Chain], str]:
    """사슬들(끝 케이스가 적힌 차례)과 점 전체를 막는 까닭."""
    found, broken = read(payload)
    if broken:
        return [], broken
    by_name = {one.name: one for one in found}
    ahead_of = {one.depends_on for one in found if one.depends_on}
    out: list[Chain] = []
    for one in found:
        if one.name in ahead_of:
            continue
        cases = [one]
        while cases[0].depends_on:
            cases.insert(0, by_name[cases[0].depends_on])
        out.append(Chain(cases=tuple(cases)))
    return out, ""


def problem(chain: Chain) -> str:
    """이 사슬을 작업으로 걸 수 없는 까닭(비면 걸 수 있다) — 받는 쪽 첫 판의 규칙."""
    where = f"케이스 「{chain.name}」"
    for one in chain.cases:
        analysis = one.analysis
        if analysis.get("prestressed") or any(
            str(row.get("type") or "") == "prestress" for row in one.rows("initial")
        ):
            return f"케이스 「{one.name}」: {PRESTRESS_IN_CASE}"
    for one in chain.leads:
        if one.kind not in LEADS:
            return (
                f"케이스 「{one.name}」({one.kind}) 뒤에 케이스가 옵니다 — 앞 케이스는 정적"
                " 구조 해석이어야 합니다(끝 상태를 이어받습니다)"
            )
    if chain.leads and chain.kind == "harmonic":
        return (
            f"{where}: 정적 → 조화 응답(선응력 조화)은 아직 받지 않습니다 — 조화 응답은 앞"
            " 케이스 없이 적습니다"
        )
    solvers = {one.solver for one in chain.cases}
    if len(solvers) > 1:
        return f"{where}: 한 사슬의 대상 솔버가 다릅니다({' · '.join(sorted(solvers))})"
    held = _canonical(chain.cases[0].rows("constraints"))
    for one in chain.cases[1:]:
        if _canonical(one.rows("constraints")) != held:
            return (
                f"케이스 「{one.name}」 의 구속이 앞 케이스와 다릅니다 — 한 사슬 안의 구속은"
                " 같아야 합니다"
            )
    tightened: set[tuple[str, str]] = set()
    for one in chain.cases:
        bolts = {_bolt_key(row) for row in one.rows("loads") if _kind(row) == BOLT}
        again = bolts & tightened
        if again:
            return (
                f"케이스 「{one.name}」 가 앞에서 조인 볼트(「{sorted(again)[0][0]}」)에"
                " 예압을 다시 적었습니다 — 조인 볼트는 그 길이로 잠긴 채 이어집니다"
            )
        tightened |= bolts
    statics = [one for one in chain.cases if one.kind == "static"]
    if statics:
        pull = _gravity(statics[0])
        for one in statics[1:]:
            if _gravity(one) != pull:
                return (
                    f"케이스 「{one.name}」 의 중력이 앞 정적과 다릅니다 — 정적 케이스끼리"
                    " 중력은 같아야 합니다(하중이 이어지지 않으므로 케이스마다 같은 중력을"
                    " 적습니다)"
                )
        if chain.kind in EIGEN and chain.leads:
            mine = _gravity(chain.end)
            if mine and mine != pull:
                return (
                    f"{where}: 중력이 앞 정적과 다릅니다 — 모드 해석 케이스의 중력은 적지"
                    " 않거나 앞 정적과 같게 적습니다(앞 정적의 끝 상태에 들어 있습니다)"
                )
    first_initial = _canonical(chain.cases[0].rows("initial"))
    for one in chain.cases[1:]:
        rows = one.rows("initial")
        if rows and _canonical(rows) != first_initial:
            return (
                f"케이스 「{one.name}」 의 초기조건이 첫 케이스와 다릅니다 — 뒤 케이스의"
                " 초기조건은 아직 받지 않습니다(물성 기준 온도는 첫 케이스의 것을 씁니다)"
            )
    if chain.leads and chain.kind in EIGEN:
        allowed = {GRAVITY, "psd_acceleration"} if chain.kind == "random" else {GRAVITY}
        extra = [row for row in chain.end.rows("loads") if _kind(row) not in allowed]
        if extra:
            return (
                f"{where}: 앞 정적 뒤의 모드 해석에는 하중을 적지 않습니다(「"
                f"{extra[0].get('name') or _kind(extra[0])}」) — 선응력을 만드는 하중은 앞"
                " 정적에 적습니다"
            )
    split = {one.analysis.get("substeps") or None for one in statics}
    if len(split) > 1:
        return (
            f"{where}: 정적 케이스마다 초기 부단계(substeps)가 다릅니다 — 한 사슬에 하나만"
            " 받습니다"
        )
    bent = {bool(one.analysis.get("large_deflection")) for one in statics}
    if len(bent) > 1:
        return (
            f"{where}: 정적 케이스마다 큰 변형(large_deflection)이 다릅니다 — 한 사슬에 하나만"
            " 받습니다(Ansys 는 한 해석에 하나, CalculiX 는 한 번 켜면 끝까지 갑니다)"
        )
    return ""


def view(payload: dict[str, Any], chain: Chain) -> dict[str, Any]:
    """사슬 하나의 **v1 모양 점 파일** — 공유 칸 + 끝 케이스(접히면 접은 것)의 칸. 걸 수 있는
    사슬만 준다(`problem` 이 빈 것)."""
    folded = _fold(chain)
    if folded is None:
        folded = _staged(chain)
    block = {
        key: copy.deepcopy(value)
        for key, value in _block(payload).items()
        if key not in ("cases", "schema_version", "version")
    }
    block["schema_version"] = 1
    block.update(folded)
    block["case"] = {
        "name": chain.name,
        "chain": [one.name for one in chain.cases],
        "solver": chain.solver,
    }
    out = {key: value for key, value in payload.items() if key != "conditions"}
    out["conditions"] = block
    return out


def _staged(chain: Chain) -> dict[str, Any]:
    """v1 으로 못 접는 사슬 — 맨 위에는 끝 케이스의 칸, `stages` 에 앞 정적 케이스들(차례대로).
    구속 · 초기조건은 첫 케이스의 것이다(사슬 안에서 같다 — `problem`). 모드 해석의 끝 케이스는
    `prestressed` 를 켜고, 하중은 그 해석의 가진만 둔다(중력은 앞 정적에 있다)."""
    end, head = chain.end, chain.cases[0]
    eigen = end.kind in EIGEN
    analysis = copy.deepcopy(end.analysis)
    if eigen:
        analysis["prestressed"] = True
    return {
        "constraints": copy.deepcopy(head.rows("constraints")),
        "initial": copy.deepcopy(head.rows("initial")),
        "analysis": analysis,
        "loads": [
            copy.deepcopy(row)
            for row in end.rows("loads")
            if not (eigen and _kind(row) == GRAVITY)
        ],
        "stages": [
            {
                "name": one.name,
                "analysis": copy.deepcopy(one.analysis),
                "loads": copy.deepcopy(one.rows("loads")),
            }
            for one in chain.leads
        ],
    }


def _fold(chain: Chain) -> dict[str, Any] | None:
    """사슬을 v1 케이스 칸으로 — 못 접으면 `None`(정적 다단)."""
    end = chain.end
    if not chain.leads:
        return {key: copy.deepcopy(end.raw.get(key)) for key in CASE_KEYS if key in end.raw}
    if len(chain.leads) > (1 if end.kind == "static" else 2):
        return None
    statics = list(chain.leads) + ([end] if end.kind == "static" else [])
    if len(statics) == 2:
        first, second = statics
        if any(_kind(row) not in (BOLT, GRAVITY) for row in first.rows("loads")):
            return None
        if any(_kind(row) == BOLT for row in second.rows("loads")):
            return None  # 뒤 정적에서 새로 조이는 볼트 — v1 은 모든 볼트를 ① 에서 조인다
        if _settings(first) != _settings(second):
            return None
        # 중력은 한 번 — 정적끼리 같으므로(`problem`) 앞 정적의 것이 곧 뒤의 것이다.
        loads = [copy.deepcopy(row) for row in first.rows("loads")] + [
            copy.deepcopy(row) for row in second.rows("loads") if _kind(row) != GRAVITY
        ]
    elif len(statics) == 1:
        loads = [copy.deepcopy(row) for row in statics[0].rows("loads")]
    else:  # pragma: no cover - 앞 케이스가 하나 이상이면 정적이 하나 이상이다
        return None
    head = statics[0]
    folded: dict[str, Any] = {
        "constraints": copy.deepcopy(head.rows("constraints")),
        "loads": loads,
        "initial": copy.deepcopy(head.rows("initial")),
    }
    if end.kind == "static":
        folded["analysis"] = copy.deepcopy(statics[-1].analysis)
        return folded
    # 모드 해석 — v1 선응력은 앞 정적의 해석 설정을 읽지 않는다(기본값일 때만 접는다).
    if any(_settings(one) != _settings(None) for one in statics):
        return None
    folded["analysis"] = {**copy.deepcopy(end.analysis), "prestressed": True}
    shaking = [copy.deepcopy(row) for row in end.rows("loads") if _kind(row) != GRAVITY]
    folded["loads"] = loads + shaking
    return folded


def _settings(case: Case | None) -> tuple[Any, Any]:
    """정적 해석 설정 중 우리가 읽는 것(큰 변형 · 초기 부단계)."""
    analysis = case.analysis if case is not None else {}
    return bool(analysis.get("large_deflection")), analysis.get("substeps") or None


def _gravity(case: Case) -> str:
    """중력의 있고 없음 · 방향 · 좌표계 — 없으면 빈 글자."""
    rows = [row for row in case.rows("loads") if _kind(row) == GRAVITY]
    if not rows:
        return ""
    return _canonical([{key: row.get(key) for key in ("direction", "cs")} for row in rows])


def _bolt_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("on") or ""), str(row.get("cs") or "")


def _kind(row: dict[str, Any]) -> str:
    return str(row.get("type") or "")


def _canonical(rows: list[dict[str, Any]]) -> str:
    """적은 차례와 상관없이 같은지 — 줄마다 열쇠를 정렬해 적고 줄들을 정렬한다."""
    return json.dumps(
        sorted(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows),
        ensure_ascii=False,
    )


def _block(payload: Any) -> dict[str, Any]:
    block = payload.get("conditions") if isinstance(payload, dict) else None
    return block if isinstance(block, dict) else {}
