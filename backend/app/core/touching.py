"""**맞닿은 바디 쌍** — 접촉을 건 점에서 접촉 없이 맞닿은 쌍은 떨어진 채로 풀린다(두 솔버
공통).

CompCore 가 점 파일 `quality.touching[]` 에 맞닿은 솔리드 쌍을 싣는다(CompCore `411247f`,
2026-11-16): `{a, b, area, at}` — 거리 0 · 맞닿은 넓이 mm² > 0(못 재면 `null`), 모서리 ·
꼭짓점만 닿은 것은 뺀다, `at` 은 맞닿은 자리 위의 점(mm). 접촉을 하나라도 건 점에서 그중
접촉이 없는 쌍이 있으면 CompCore 도 `quality.warnings` 에 「접촉 미정의: 인접 바디」 를 싣는다.
**우리도 이 목록으로 말한다** — 두 쪽이 같은 쌍을 짚게.

- 접촉을 하나도 안 걸었으면 말하지 않는다 — CalculiX 는 맞닿은 바디를 찾아 묶고(`bonding`),
  Mechanical 은 자동 접촉을 만든다.
- 해석 제외 파트가 낀 쌍은 뺀다(CompCore 와 같다).
- 목록이 없는 옛 점 파일이면 `None` — CalculiX 는 메시에서 잰다(`bonding.untied_pairs`).

미끄럼으로 푸는 접촉(분리 없음 · 모달 · 조화의 마찰 없음)도 여기서 그 두 바디를 적는다 — 0 Hz
모드의 까닭을 짚는 재료다(`modes.rigid`).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.core import conditions as condition_model

#: 미끄럼으로 푸는 접촉의 말(Mechanical 경로) — 모달 · 조화에서 법선으로만 잇는다.
SLIDING_NOTE = (
    "법선으로만 이어 **면 방향으로 미끄러지게** 풉니다(선형 해석의 분리 없음) — 이 접촉으로만 "
    "이어진 바디는 미끄러지는 방향이 0 Hz 모드로 나옵니다."
)


def contact_bodies(topology: dict[str, Any], contact: condition_model.Contact) -> list[str]:
    """접촉 두 면의 바디 — 영역 지문의 `body`(조립일 때만 있다)."""
    regions = (topology or {}).get("regions") or {}
    bodies: list[str] = []
    for side in (contact.source, contact.target):
        for row in regions.get(side) or []:
            name = row.get("body") if isinstance(row, dict) else None
            if name and str(name) not in bodies:
                bodies.append(str(name))
    return bodies


def _sides(topology: dict[str, Any], contact: condition_model.Contact) -> list[set[str]]:
    regions = (topology or {}).get("regions") or {}
    return [
        {
            str(row["body"])
            for row in regions.get(side) or []
            if isinstance(row, dict) and row.get("body")
        }
        for side in (contact.source, contact.target)
    ]


def uncovered(
    topology: dict[str, Any], given: condition_model.Conditions
) -> list[dict[str, Any]] | None:
    """접촉 없이 맞닿은 쌍(`quality.touching` 중) — 목록이 없으면 None."""
    found = ((topology or {}).get("quality") or {}).get("touching")
    if not isinstance(found, list):
        return None
    if not given.contacts:
        return []
    covered: set[frozenset[str]] = set()
    for contact in given.contacts:
        first, second = _sides(topology, contact)
        covered |= {frozenset({a, b}) for a in first for b in second if a != b}
    left = set(given.suppressed)
    made: list[dict[str, Any]] = []
    for row in found:
        if not isinstance(row, dict) or not row.get("a") or not row.get("b"):
            continue
        a, b = str(row["a"]), str(row["b"])
        if a in left or b in left or frozenset({a, b}) in covered:
            continue
        made.append({"a": a, "b": b, "area": row.get("area"), "at": row.get("at")})
    return made


def sliding(
    topology: dict[str, Any], contacts: Iterable[condition_model.Contact], *, modal: bool
) -> list[dict[str, Any]]:
    """미끄럼으로 푸는 접촉 — 분리 없음, 모달 · 조화의 마찰 없음(Ansys 가 선형 해석에서
    그렇게 푼다 — CalculiX 도 같다, `bonding._sliding`)."""
    return [
        {"contact": one.name, "kind": one.kind, "bodies": contact_bodies(topology, one)}
        for one in contacts
        if one.kind == "no_separation" or (modal and one.kind == "frictionless")
    ]


def line(rows: Iterable[dict[str, Any]]) -> str:
    """요약 한 줄 — 「A ↔ B (넓이 n mm² · 자리 (x, y, z) mm)」(메시로 잰 것은 절점 수)."""
    shown: list[str] = []
    for one in rows:
        parts: list[str] = []
        if isinstance(one.get("area"), int | float):
            parts.append(f"넓이 {float(one['area']):g} mm²")
        if isinstance(one.get("nodes"), int):
            parts.append(f"절점 {one['nodes']}")
        at = one.get("at")
        if isinstance(at, list | tuple) and len(at) == 3:
            parts.append(f"자리 ({', '.join(f'{float(value):g}' for value in at)}) mm")
        tail = f" ({' · '.join(parts)})" if parts else ""
        shown.append(f"{one['a']} ↔ {one['b']}{tail}")
    return " · ".join(shown)
