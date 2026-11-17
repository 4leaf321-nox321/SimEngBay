"""본딩 — **바디를 따로 메시하고 `*TIE` 로 묶는다**(2026-11-16).

## 왜 절점 공유를 버렸나

전에는 맞닿은 면을 쪼개(`BooleanFragments`) 절점을 공유시키는 것이 본딩의 전부였다. 운영에서
네 가지가 막혔다:

- CAD 가 넣은 본딩 접촉 쌍이 쓰이지 않았다 — 맞닿은 면은 선언과 상관없이 **전부** 붙었다.
- 형상이 정확히 맞닿아야 했다 — 미세 간극이 있으면 바디가 떨어졌다(Workbench 처럼 pinball 안의
  면을 묶거나 초기 간극을 무시하는 처리가 없었다).
- 접합면 양쪽 메시가 묶였다 — 작은 연결 바디가 있으면 이웃 바디의 접합부도 같이 촘촘해져야 해서
  파트별 메시를 독립적으로 정할 수 없었다.
- 정식 본딩(MPC)은 Ansys 경로에만 있었다.

`*TIE` 는 종 절점을 주 요소면에 구속식으로 묶는다 — 메시가 맞지 않아도 되고, 정적과 고유치에
같이 쓴다(접촉 쌍은 고유치에 안 들어간다). 기둥(3 mm) · 판(5 mm) 따로 메시한 2차 모델이 절점
공유와 정적 최대 변위 0.12 %, 1 ~ 3차 주파수 0.06 % 안에서 같았다(ccx 2.21, 2026-11-16).

## 무엇을 묶나 — Ansys 경로와 같다

- CAD 가 접촉을 선언했으면 **선언한 쌍만** 묶는다. Ansys 경로는 그때 Mechanical 의 자동 접촉을
  지운다(`mechanical/build.py`) — 같은 폴더를 두 솔버로 풀면 같은 쌍이 붙어야 한다.
- 선언이 없으면 **맞닿은 바디를 찾아 묶는다**(Mechanical 의 자동 접촉) — 검색 반경 안의 절점만.
- 검색 반경은 pinball 이 오면 그것, 아니면 선언한 쌍은 요소 크기의 절반(그 두 면 사이에서만
  찾으므로 넉넉해도 엉뚱한 면에 안 붙는다), 자동은 형상 맞춤 허용오차와 요소 크기의 2 % 중 큰
  것 — CompCore 가 그 두 바디 사이의 틈을 알렸으면 그 0.4 배 아래(설계 틈새를 묶지 않는다).
- **본딩 `*TIE` 는 늘 `ADJUST=YES` 다**(2026-11-17) — 종 절점을 주 면 위로 옮긴다. ccx 의
  구속식은 u종 = Σ N·u주 라, 종 절점이 주 면에서 δ 떨어져 있으면 강체 회전 ω 에서 ω x δ 만큼
  어긋나 **회전 강체 모드를 잡는다**. 따로 메시한 2차 곡면의 현 오차 · CAD 의 미세 간극만으로
  생긴다 — 자유-자유 「조건_볼트예압_판본딩」 의 회전 셋이 0.23 · 0.30 · 0.30 Hz 로 올라왔고
  (옮기면 0.003 Hz, 절점 공유와 같다), 64쌍 조립은 1 Hz 를 넘어 강체 모드가 3개로 셌다.
  Mechanical 의 본딩(MPC)은 간극을 둔 채로 강체 운동에 맞는 구속식을 세운다 — ccx 에서 그와
  같아지는 길이 이것이다. 옮기는 거리는 검색 반경 안이다(맞닿게 그린 면이면 현 오차뿐).
- **강체가 낀 묶음은 `*TIE` 를 쓰지 않고 상대 절점을 그 강체에 넣는다** — 강체 표면에 묶으면
  구속이 사슬이 되어 ccx 가 기준점 반력에 그 몫을 안 넣었다(쉘 묶음과 같은 까닭,
  `build._ties`).
- **구속된 절점은 주(master) 쪽에 두지 않는다** — 고정 절점이 주 면에 있으면 종에서 넘어온
  힘이 그 절점의 반력(RF)에 안 들어간다(강체 묶음의 「구속 사슬」 과 같다). 바닥까지 뚫린
  나사 구멍을 주로 두었더니 볼트 조립의 바닥 반력이 600 N 이 아니라 428 N 이었다
  (2026-11-16). 구속 절점이 적은 쪽을 주로 고르고, 그래도 남으면 그 절점이 든 주 요소면을
  뺀다. 종 쪽의 구속 절점은 ccx 가 묶지 않는다.
- 한 절점은 한 묶음의 종이다 — 먼저 묶인 절점은 뒤 묶음의 종에서 뺀다(ccx 는 두 번째를 건너뛰며
  경고를 낸다).

## 묶지 않은 것도 말한다(2026-11-16, CompCore 의 조립 점검)

- 선언이 있을 때 **맞닿았는데 접촉이 없는 바디 쌍**은 떨어진 채로 풀린다(Ansys 와 같다).
  묶지는 않고 자리와 함께 알린다(요약 `unbonded_touching`). 쌍은 CompCore 가 잰 목록
  (`quality.touching` — `app/core/touching.py`, 두 솔버 공통)으로 고른다. 그 목록이 없는 옛 점
  파일이면 메시에서 잰다(`Bonding.untied` — 자동 묶음과 같은 반경, 쉘이 낀 쌍은 못 잰다).
- 미끄럼으로 푼 접촉(분리 없음 · 모달의 마찰 없음)은 면 방향을 잡지 않는다 — 그 접촉으로만
  이어진 바디는 0 Hz 모드가 나온다. 그렇다고 적는다(`SLIDING_NOTE`).
- 둘 다 `boundary.json` 의 `connections` 에 남는다 — 추출이 0 Hz 모드의 까닭을 짚는다
  (`modes.rigid`).
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from app.core import conditions as condition_model
from app.core import touching
from app.core.calculix import deck as deck_writer
from app.core.calculix.mesh import element_faces
from app.core.regions import match_regions

logger = logging.getLogger(__name__)

#: 본딩 방식 — `tie`(따로 메시하고 `*TIE`, 기본) · `shared`(옛 방식: 쪼개 절점 공유).
BONDING_ENV = "CALCULIX_BONDING"
#: 묶음마다 종 절점 · 반경 — 모델링이 쓰고 솔브가 ccx 로그와 맞대어 쌍마다 몇 개가 묶였나 센다.
TIES_NAME = "ties.json"
#: 선언한 본딩의 기본 검색 반경 = 요소 크기 x 이것(pinball 이 없을 때).
PINBALL_RATIO = 0.5
#: 자동 묶음의 검색 반경 = max(형상 맞춤 허용오차, 요소 크기 x 이것). 1차 요소의 곡면 접합부는
#: 평평한 삼각형이라 종 절점이 처짐만큼 떨어져 보인다(R4 · 요소 1 mm 면 0.03 mm) — 그보다 커야
#: 하고, 설계 틈새(핸드폰 부품 0.05 ~ 0.2 mm)보다 작아야 한다. CompCore 가 그 두 바디의 틈을
#: 알렸으면 그보다 작게 줄인다(`GAP_SHARE`).
AUTO_RATIO = 0.02
#: CompCore 가 알린 틈이 있으면 자동 묶음의 반경을 그 틈 x 이것 아래로 — 후보는 두 배 반경에서
#: 고르므로(`_automatic`) 그래도 틈보다 작다.
GAP_SHARE = 0.4
#: 미끄럼으로 푼 접촉의 말 — 모달 · 조화, 정적.
SLIDING_NOTE = {
    True: (
        "법선으로만 묶어 **면 방향으로 미끄러지게** 풀었습니다(Ansys 도 선형 해석에서 "
        "같습니다) — 이 접촉으로만 이어진 바디는 미끄러지는 방향이 0 Hz 모드로 나옵니다."
    ),
    False: (
        "법선으로만 묶어 **면 방향으로 미끄러지게** 풀었습니다 — 이 접촉으로만 이어진 바디는 "
        "그 방향을 다른 구속이 잡아야 풀립니다."
    ),
}


def bonding_mode() -> str:
    """`tie` 또는 `shared`. 모르는 값은 `tie` 다."""
    mode = os.environ.get(BONDING_ENV, "").strip().lower()
    return "shared" if mode == "shared" else "tie"


@dataclass
class Bonding:
    """묶은 것 — 덱에 넘길 묶음, 고친 강체, 처리한 접촉, 사람에게 할 말."""

    ties: list[deck_writer.Tie | deck_writer.Slide] = field(default_factory=list)
    rigid: list[deck_writer.RigidBody] = field(default_factory=list)
    handled: set[str] = field(default_factory=set)
    """`*TIE` · 강체로 처리한 접촉 이름 — 덱의 접촉 쌍에서 뺀다."""
    dropped: set[str] = field(default_factory=set)
    """거절한 접촉 이름 — 이것도 덱에서 뺀다(안 빼면 덱이 「붙었다」 고 적는다)."""
    notes: list[condition_model.Note] = field(default_factory=list)
    refused: list[condition_model.Note] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)
    """강체에 넣은 묶음 · 자동 묶음의 이름(`*TIE` 는 덱이 적는다)."""
    untied: list[dict[str, Any]] = field(default_factory=list)
    """맞닿았는데 접촉이 없는 바디 쌍 — `{a, b, nodes, at}`(선언이 있을 때만 잰다)."""
    sliding: list[dict[str, Any]] = field(default_factory=list)
    """미끄럼으로 푼 접촉 — `{contact, kind, bodies}`."""


def bond(
    topology: dict[str, Any],
    contacts: list[condition_model.Contact],
    mesh: Any,
    rigid: list[deck_writer.RigidBody],
    body_of: dict[str, int],
    *,
    declared: bool,
    nonlinear: bool,
    modal: bool,
    size: float,
    length_mm: float,
    tolerance: float,
    taken: set[int] | None = None,
    held: set[int] | None = None,
    find_untied: bool = True,
) -> Bonding:
    """선언한 접촉(`declared`) 또는 맞닿은 바디(선언이 없을 때)를 묶는다.

    `nonlinear` 면 마찰 · 무마찰 · rough 는 묶지 않는다 — 정적의 비선형 접촉 쌍으로 건다
    (`deck.contact_block`). `modal` 은 붙인 까닭을 고유치에 맞게 적으려고 받는다.
    `find_untied` 면 선언이 있을 때 접촉 없이 맞닿은 쌍을 메시에서 잰다 — CompCore 가 그 목록을
    보냈으면(`touching.uncovered`) 끈다.
    """
    made = Bonding(rigid=list(rigid))
    used = set(taken or set())
    for one in made.rigid:
        used |= one.nodes
    faces_of = _boundary_faces(mesh)
    fixed = set(held or set())
    if declared:
        _declared(
            topology,
            contacts,
            mesh,
            made,
            used,
            nonlinear,
            modal,
            size,
            length_mm,
            tolerance,
            fixed,
        )
        if find_untied and len(faces_of) > 1:
            made.untied = untied_pairs(
                topology,
                contacts,
                mesh,
                faces_of,
                body_of,
                made.rigid,
                max(tolerance, AUTO_RATIO * size),
                _reported_gaps(topology),
            )
    elif len(faces_of) > 1:
        _automatic(
            mesh,
            faces_of,
            body_of,
            made,
            used,
            max(tolerance, AUTO_RATIO * size),
            _reported_gaps(topology),
            fixed,
        )
    return made


def _reported_gaps(topology: dict[str, Any]) -> dict[frozenset[str], float]:
    """CompCore 가 잰 바디끼리의 **틈**(`quality.contacts`) — 바디 이름 쌍 → 가장 작은 틈(mm).
    그 틈은 설계한 것이다(「CAD 가 남긴 틈」 보다 크다) — 자동 묶음이 닫으면 안 된다."""
    found: dict[frozenset[str], float] = {}
    for row in ((topology or {}).get("quality") or {}).get("contacts") or []:
        if not isinstance(row, dict) or row.get("kind") != "gap":
            continue
        try:
            size = float(row["size"])
        except (KeyError, TypeError, ValueError):
            continue
        key = frozenset({str(row.get("a")), str(row.get("b"))})
        found[key] = min(size, found.get(key, size))
    return found


def _declared(
    topology: dict[str, Any],
    contacts: list[condition_model.Contact],
    mesh: Any,
    made: Bonding,
    used: set[int],
    nonlinear: bool,
    modal: bool,
    size: float,
    length_mm: float,
    tolerance: float,
    fixed: set[int],
) -> None:
    pairs = [
        one
        for one in contacts
        if not (nonlinear and one.kind in deck_writer.NONLINEAR_CONTACTS)
    ]
    if not pairs:
        return
    wanted = sorted({one.source for one in pairs} | {one.target for one in pairs})
    found = match_regions(topology, mesh.faces, wanted_regions=wanted)
    lookup = element_faces(mesh)
    for index, pair in enumerate(pairs, start=1):
        what = f"접촉 「{pair.name}」({pair.kind})"
        if pair.kind not in deck_writer.LINEARIZED_CONTACTS:
            made.refused.append(condition_model.Note(what, "모르는 접촉입니다."))
            made.dropped.add(pair.name)
            continue
        source = found.faces.get(pair.source) or []
        target = found.faces.get(pair.target) or []
        if not source or not target:
            made.refused.append(
                condition_model.Note(
                    what,
                    f"면을 못 찾았습니다({pair.source} · {pair.target}) — 접합면이 양쪽으로 "
                    "와야 합니다.",
                )
            )
            made.dropped.add(pair.name)
            continue
        slave_side, master_side = source, target
        owners = [_rigid_owner(made.rigid, mesh, side) for side in (source, target)]
        if owners[0] is not None and owners[1] is not None:
            made.refused.append(
                condition_model.Note(
                    what, "강체 파트끼리는 묶지 못합니다 — 한쪽을 변형체로 두세요."
                )
            )
            made.dropped.add(pair.name)
            continue
        if owners[0] is not None:
            # **강체는 주(master) 쪽이다** — 그 절점은 이미 `*RIGID BODY` 의 종이다.
            slave_side, master_side = target, source
        elif owners[1] is None and _fixed_count(mesh, source, fixed) < _fixed_count(
            mesh, target, fixed
        ):
            # **구속 절점이 적은 쪽이 주다** — 주 면의 구속 절점은 반력에서 종의 몫을 잃는다.
            slave_side, master_side = target, source
        owner = owners[0] if owners[0] is not None else owners[1]
        slaves: set[int] = set()
        for face in slave_side:
            slaves |= mesh.face_nodes.get(face, set())
        slaves -= used
        if owner is not None:
            held = made.rigid[owner]
            made.rigid[owner] = replace(held, nodes=held.nodes | frozenset(slaves))
            made.applied.append(f"bonded:{pair.source}↔{pair.target}")
            logger.info(
                "접촉 %s → 절점 %s 를 강체 %s 에 넣었습니다", pair.name, len(slaves), held.part
            )
        elif _sliding(pair, modal):
            radius = (
                pair.pinball * length_mm
                if pair.pinball is not None and pair.pinball > 0
                else max(PINBALL_RATIO * size, tolerance)
            )
            rings = [ring for face in master_side for ring in mesh.face_rings.get(face, [])]
            rows = slide_rows(mesh.nodes, slaves - fixed, rings, radius)
            made.ties.append(
                deck_writer.Slide(
                    contact=pair.name, name=f"SLIDE{index}", rows=tuple(rows), tolerance=radius
                )
            )
            slaves = {row[0] for row in rows}
            made.sliding.append(
                {
                    "contact": pair.name,
                    "kind": pair.kind,
                    "bodies": touching.contact_bodies(topology, pair),
                }
            )
            logger.info(
                "접촉 %s → 법선 구속식 %s 개(떨어지지 않고 미끄러짐) · 반경 %.4g mm",
                pair.name,
                len(rows),
                radius,
            )
        else:
            masters = _free_faces(
                [
                    (triangle, hit)
                    for face in master_side
                    for triangle in mesh.face_triangles.get(face, [])
                    if (hit := lookup.get(frozenset(triangle))) is not None
                ],
                fixed,
            )
            radius = (
                pair.pinball * length_mm
                if pair.pinball is not None and pair.pinball > 0
                else max(PINBALL_RATIO * size, tolerance)
            )
            made.ties.append(
                deck_writer.Tie(
                    contact=pair.name,
                    name=f"BOND{index}",
                    slave_nodes=frozenset(slaves),
                    master_faces=masters,
                    tolerance=radius,
                    # 늘 옮긴다 — 안 옮기면 회전 강체 모드를 잡는다(맨 위 「본딩 `*TIE` 는 늘
                    # `ADJUST=YES`」).
                    adjust=True,
                )
            )
            logger.info(
                "접촉 %s → TIE 종 절점 %s · 주 요소면 %s · 반경 %.4g mm",
                pair.name,
                len(slaves),
                len(masters),
                radius,
            )
        used |= slaves
        made.handled.add(pair.name)
        note = _linearized(pair, modal, sliding=owner is None and _sliding(pair, modal))
        if note is not None:
            made.notes.append(condition_model.Note(what, note))


def _sliding(pair: condition_model.Contact, modal: bool) -> bool:
    """법선으로만 묶나(떨어지지 않고 미끄러진다) — no separation 은 늘, 무마찰은 모달 ·
    조화에서(Ansys 가 선형 해석에서 무마찰을 no separation 으로 푼다).

    ⚠️ **마찰은 미끄러지게 하지 않는다.** 「조건_조건훑기」 의 마찰 블록을 미끄러지게 했더니
    0 Hz 모드가 셋(판 위에서 블록이 미끄러진다) 나왔는데 Ansys 는 26,472.8 Hz 였다 — Ansys
    는 닫힌 마찰 접촉을 **붙여** 풀고, 벌칙 강성만큼 물러 접착(27,940.6)보다 5.3% 낮을
    뿐이다(2026-11-16). rough 도 미끄러지지 않는다."""
    return pair.kind == "no_separation" or (modal and pair.kind == "frictionless")


def _linearized(
    pair: condition_model.Contact, modal: bool, *, sliding: bool = False
) -> str | None:
    """본딩이 아닌 접촉을 풀었을 때의 말 — 무엇이 Ansys 와 다른가. 같으면 말하지 않는다.

    - 미끄러짐으로 푼 무마찰 · no separation 은 Ansys 와 같지만 **그렇다고 적는다** — 그
      접촉으로만 이어진 바디는 0 Hz 모드가 나온다(마찰에는 말이 있는데 미끄럼에는 없었다 —
      CompCore 의 조립 점검, 2026-11-16). 모달의 rough(미끄러지지 않는다)는 Ansys 와 같다.
    - 모달의 마찰은 붙여 푼다 — Ansys 도 붙여 풀지만 벌칙 강성만큼 물러 조금 낮다.
    - 강체와의 접촉이라 강체에 넣었으면 미끄러지지 못한다.
    - 힘으로 미는 정적의 마찰 · 무마찰 · rough 는 붙은 것으로 풀었다(접촉 쌍은 변위로 당길
      때만).
    """
    if pair.kind == "bonded":
        return None
    if sliding:
        return SLIDING_NOTE[modal]
    if _sliding(pair, modal):
        return "강체 파트와의 접촉이라 강체에 붙여 **미끄러짐 없이** 풀었습니다."
    if pair.kind == "rough" and modal:
        return None
    if pair.kind == "frictional" and modal:
        return (
            "면을 묶어 **붙은 것으로** 풀었습니다 — Ansys 도 모달에서 닫힌 마찰 접촉을 붙여 "
            "풀지만 접촉의 벌칙 강성만큼 물러 주파수가 조금 낮게 나옵니다(실측 5.3%)."
        )
    if pair.kind in deck_writer.NONLINEAR_CONTACTS:
        return "하중으로 미는 정적이라 면을 묶어 **붙은 것으로** 풀었습니다."
    return None


def _fixed_count(mesh: Any, faces: list[int], fixed: set[int]) -> int:
    members: set[int] = set()
    for face in faces:
        members |= mesh.face_nodes.get(face, set())
    return len(members & fixed)


def _free_faces(
    rows: list[tuple[tuple[int, int, int], tuple[int, str]]], fixed: set[int]
) -> list[tuple[int, str]]:
    """주 요소면에서 **구속 절점이 든 것을 뺀다** — 다 빠지면 그대로 둔다(묶음이 없어지면 더
    나쁘다). 주 면의 구속 절점은 종에서 넘어온 힘을 반력에 안 넣는다."""
    free = [hit for triangle, hit in rows if not fixed.intersection(triangle)]
    return free if free else [hit for _, hit in rows]


def _rigid_owner(
    rigid: list[deck_writer.RigidBody], mesh: Any, faces: list[int]
) -> int | None:
    """그 면들이 강체 파트의 것이면 그 강체의 차례."""
    members: set[int] = set()
    for face in faces:
        members |= mesh.face_nodes.get(face, set())
    if not members:
        return None
    return next((at for at, one in enumerate(rigid) if members <= one.nodes), None)


def _boundary_faces(mesh: Any) -> dict[int, list[int]]:
    """솔리드 → 그 솔리드의 겉면들(쉘 중간면은 뺀다). 면의 첫 삼각형이 든 요소로 가린다."""
    lookup = element_faces(mesh)
    solid_of = {number: solid for solid, rows in mesh.solids.items() for number, _ in rows}
    shells = set(getattr(mesh, "shells", {}) or {})
    found: dict[int, list[int]] = defaultdict(list)
    for face in mesh.faces:
        if face.id in shells:
            continue
        triangles = mesh.face_triangles.get(face.id) or []
        if not triangles:
            continue
        hit = lookup.get(frozenset(triangles[0]))
        if hit is not None and hit[0] in solid_of:
            found[solid_of[hit[0]]].append(face.id)
    return dict(found)


def _automatic(
    mesh: Any,
    faces_of: dict[int, list[int]],
    body_of: dict[str, int],
    made: Bonding,
    used: set[int],
    radius: float,
    gaps: dict[frozenset[str], float] | None = None,
    fixed: set[int] | None = None,
) -> None:
    """**선언이 없으면 맞닿은 바디를 묶는다** — 상자가 닿는 쌍마다, 상대 겉면에서 `radius`
    안에 든 절점만. 촘촘한 쪽을 종으로 둔다(ccx 의 권고). 강체가 끼면 그 강체에 넣는다.

    정확한 거리는 ccx 가 잰다(`*TIE` 의 POSITION TOLERANCE — 2차 면에 투영한다). 여기서는
    평평한 삼각형으로 두 배 반경 안의 후보만 고른다 — 맞닿았는지 알고, 덱을 작게 두려고."""
    name_of = {entity: name for name, entity in body_of.items()}
    lookup = element_faces(mesh)
    surface = _surfaces(mesh, faces_of)
    boxes = {solid: _box(mesh.nodes, data[0]) for solid, data in surface.items()}
    solids = sorted(surface)
    count = 0
    for at, first in enumerate(solids):
        for second in solids[at + 1 :]:
            names = (name_of.get(first, str(first)), name_of.get(second, str(second)))
            reach_here = radius
            if gaps and frozenset(names) in gaps:
                reach_here = min(radius, GAP_SHARE * gaps[frozenset(names)])
            if not _meet(boxes[first], boxes[second], 2 * reach_here):
                continue
            owners = {
                solid: next(
                    (i for i, one in enumerate(made.rigid) if surface[solid][0] <= one.nodes),
                    None,
                )
                for solid in (first, second)
            }
            if owners[first] is not None and owners[second] is not None:
                continue
            # 구속 절점이 많은 쪽이 종(주 면의 구속 절점은 반력에서 종의 몫을 잃는다), 같으면
            # 촘촘한 쪽(넓이당 절점이 많은 쪽)이 종 — 강체는 늘 주.
            held_here = {
                solid: len(surface[solid][0] & (fixed or set())) for solid in (first, second)
            }
            slave, master = (
                (first, second)
                if (held_here[first], surface[first][2])
                >= (held_here[second], surface[second][2])
                else (second, first)
            )
            if owners[slave] is not None:
                slave, master = master, slave
            near_box = _grow(boxes[master], 2 * reach_here)
            candidates = {
                n for n in surface[slave][0] - used if _inside(mesh.nodes[n], near_box)
            }
            reach = _grow(boxes[slave], 2 * reach_here)
            triangles = [
                one
                for one in surface[master][1]
                if any(_inside(mesh.nodes[n], reach) for n in one)
            ]
            near = near_nodes(mesh.nodes, candidates, triangles, 2 * reach_here)
            if not near:
                continue
            label = f"auto:{name_of.get(slave, slave)}↔{name_of.get(master, master)}"
            owner = owners[master]
            if owner is not None:
                held = made.rigid[owner]
                made.rigid[owner] = replace(held, nodes=held.nodes | frozenset(near))
                made.applied.append(label)
            else:
                count += 1
                made.ties.append(
                    deck_writer.Tie(
                        contact=label,
                        name=f"AUTO{count}",
                        slave_nodes=frozenset(near),
                        master_faces=_free_faces(
                            [
                                (one, hit)
                                for one in triangles
                                if (hit := lookup.get(frozenset(one))) is not None
                            ],
                            fixed or set(),
                        ),
                        tolerance=reach_here,
                        adjust=True,
                    )
                )
            used |= near
            logger.info("자동 묶음 %s — 절점 %s · 반경 %.4g mm", label, len(near), reach_here)


Surface = tuple[set[int], list[tuple[int, int, int]], float]


def _surfaces(mesh: Any, faces_of: dict[int, list[int]]) -> dict[int, Surface]:
    """솔리드마다 겉면 — (절점, 삼각형, 넓이당 절점 수)."""
    surface: dict[int, Surface] = {}
    for solid, faces in faces_of.items():
        nodes: set[int] = set()
        triangles: list[tuple[int, int, int]] = []
        for face in faces:
            nodes |= mesh.face_nodes.get(face, set())
            triangles += mesh.face_triangles.get(face, [])
        area = sum(_area(*(mesh.nodes[one] for one in triangle)) for triangle in triangles)
        surface[solid] = (nodes, triangles, len(nodes) / area if area > 0 else 0.0)
    return surface


def untied_pairs(
    topology: dict[str, Any],
    contacts: list[condition_model.Contact],
    mesh: Any,
    faces_of: dict[int, list[int]],
    body_of: dict[str, int],
    rigid: list[deck_writer.RigidBody],
    radius: float,
    gaps: dict[frozenset[str], float] | None = None,
) -> list[dict[str, Any]]:
    """**맞닿았는데 접촉이 없는 바디 쌍** — 접촉을 선언했으면 나머지는 떨어진 채로 풀린다
    (Ansys 경로도 선언한 쌍만 붙인다). 부품이 수십 개인 조립에서 한 쌍을 빠뜨리기 쉽고,
    빠뜨리면 그 바디가 떠서 모달이 0 Hz 를 낸다 — 그런데 아무도 말하지 않았다(CompCore 의 조립
    점검, 2026-11-16). 묶지는 않고 쌍마다 `{a, b, nodes, at}` 로 알린다.

    맞닿음은 자동 묶음과 같은 반경으로 잰다(`_automatic` — 선언이 없었으면 묶였을 쌍이다).
    선언한 접촉은 종류와 상관없이 그 두 바디를 덮는다. 강체끼리는 묶을 수 없어 세지 않는다.
    """
    solid_of = {face: solid for solid, faces in faces_of.items() for face in faces}
    wanted = sorted({one.source for one in contacts} | {one.target for one in contacts})
    found = match_regions(topology, mesh.faces, wanted_regions=wanted) if wanted else None
    covered: set[frozenset[int]] = set()
    for pair in contacts:
        ends = [
            {solid_of[face] for face in (found.faces.get(side) or []) if face in solid_of}
            if found is not None
            else set()
            for side in (pair.source, pair.target)
        ]
        covered |= {frozenset({a, b}) for a in ends[0] for b in ends[1] if a != b}
    name_of = {entity: name for name, entity in body_of.items()}
    surface = _surfaces(mesh, faces_of)
    boxes = {solid: _box(mesh.nodes, data[0]) for solid, data in surface.items() if data[0]}
    rigid_solids = {
        solid
        for solid, data in surface.items()
        if any(data[0] and data[0] <= one.nodes for one in rigid)
    }
    made: list[dict[str, Any]] = []
    solids = sorted(boxes)
    for at, first in enumerate(solids):
        for second in solids[at + 1 :]:
            if frozenset({first, second}) in covered:
                continue
            if first in rigid_solids and second in rigid_solids:
                continue
            names = (name_of.get(first, str(first)), name_of.get(second, str(second)))
            reach = radius
            if gaps and frozenset(names) in gaps:
                reach = min(radius, GAP_SHARE * gaps[frozenset(names)])
            if not _meet(boxes[first], boxes[second], 2 * reach):
                continue
            # 절점이 적은 쪽에서 잰다 — 셈이 가볍다.
            slave, master = (
                (first, second)
                if len(surface[first][0]) <= len(surface[second][0])
                else (second, first)
            )
            near_box = _grow(boxes[master], 2 * reach)
            candidates = {n for n in surface[slave][0] if _inside(mesh.nodes[n], near_box)}
            grown = _grow(boxes[slave], 2 * reach)
            triangles = [
                one
                for one in surface[master][1]
                if any(_inside(mesh.nodes[n], grown) for n in one)
            ]
            near = near_nodes(mesh.nodes, candidates, triangles, 2 * reach)
            if not near:
                continue
            points = [mesh.nodes[n] for n in near]
            centre = [round(sum(p[k] for p in points) / len(points), 3) for k in range(3)]
            made.append({"a": names[0], "b": names[1], "nodes": len(near), "at": centre})
            logger.warning(
                "바디 %s ↔ %s 가 맞닿았는데(절점 %s · 자리 %s mm) 접촉이 없습니다 — "
                "떨어진 채로 풉니다",
                names[0],
                names[1],
                len(near),
                centre,
            )
    return made


def write_ties(
    workdir: Path, ties: Sequence[deck_writer.Tie | deck_writer.Slide], rigid: list[str]
) -> None:
    """묶음을 적어 둔다 — 솔브가 ccx 로그에서 「묶이지 않은 절점」 을 세어 쌍마다 보고한다
    (`connection_report`). 강체에 넣은 묶음은 ccx 가 안 보므로 이름만."""
    rows = [
        {
            "name": one.name,
            "contact": one.contact,
            "radius": one.tolerance,
            "slaves": sorted(one.slave_nodes),
        }
        for one in ties
    ]
    (workdir / TIES_NAME).write_text(
        json.dumps({"ties": rows, "rigid": rigid}, ensure_ascii=False), encoding="utf-8"
    )


#: ccx 가 반경 밖의 종 절점에 찍는 말 — `no tied MPC generated for node N … too far away`.
_FAR = re.compile(r"no tied MPC\s+generated for node\s+(\d+)")


def connection_report(workdir: Path, log: str) -> dict[str, str]:
    """**쌍마다 몇 절점이 묶였나** — `ties.json` 과 ccx 로그(반경 밖이라 안 묶인 절점)를
    맞댄다.

    요약 칸 둘: `bonded_pairs`(「쌍 묶인/종 절점 · 반경」) · 한 절점도 안 묶인 쌍이 있으면
    `bond_warning` — 그 쌍의 바디는 떨어진 채 풀렸다(모달이면 강체 모드가 나온다).
    """
    path = workdir / TIES_NAME
    if not path.is_file():
        return {}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    far = {int(one) for one in _FAR.findall(log)}
    shown: list[str] = []
    empty: list[str] = []
    for row in saved.get("ties") or []:
        slaves = set(row.get("slaves") or [])
        if not slaves:
            empty.append(str(row.get("contact")))
            continue
        tied = len(slaves - far)
        radius = float(row.get("radius") or 0)
        shown.append(f"{row.get('contact')} {tied}/{len(slaves)} 절점(반경 {radius:.3g} mm)")
        if tied == 0:
            empty.append(str(row.get("contact")))
    shown += [f"{one} → 강체에 넣음" for one in saved.get("rigid") or []]
    found: dict[str, str] = {}
    if shown:
        found["bonded_pairs"] = " · ".join(shown)
    if empty:
        found["bond_warning"] = (
            f"{', '.join(empty)} 는 한 절점도 묶이지 않았습니다 — 반경 안에 상대 면이 없거나 "
            "종 면이 비었습니다. 그 바디는 떨어진 채 풀렸습니다(pinball 을 넓히거나 형상 · "
            "영역을 보세요)."
        )
    return found


def slide_rows(
    nodes: dict[int, tuple[float, float, float]],
    slaves: set[int],
    rings: list[list[int]],
    radius: float,
) -> list[tuple[int, tuple[float, float, float], tuple[tuple[int, float], ...]]]:
    """종 절점마다 **가장 가까운 주 면 요소**에 투영해 법선 구속식의 재료를 만든다 — (종, 단위
    법선, ((주 절점, 형상함수 값), …)). 반경 밖의 종은 뺀다. 2차 면(6 절점)이면 2차 형상함수,
    1차(3 절점)면 1차 — 주 면의 변위장과 같은 함수로 잇는다."""
    if not slaves or not rings:
        return []
    corners = [tuple(nodes[n] for n in ring[:3]) for ring in rings]
    edges = [math.dist(one[0], one[1]) for one in corners[: min(len(corners), 500)]]
    cell = max(radius, sum(edges) / len(edges), 1e-9)
    grid: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index, points in enumerate(corners):
        low = [math.floor((min(p[a] for p in points) - radius) / cell) for a in range(3)]
        high = [math.floor((max(p[a] for p in points) + radius) / cell) for a in range(3)]
        for i in range(low[0], high[0] + 1):
            for j in range(low[1], high[1] + 1):
                for k in range(low[2], high[2] + 1):
                    grid[(i, j, k)].append(index)
    rows: list[tuple[int, tuple[float, float, float], tuple[tuple[int, float], ...]]] = []
    for node in sorted(slaves):
        point = nodes[node]
        key = (
            math.floor(point[0] / cell),
            math.floor(point[1] / cell),
            math.floor(point[2] / cell),
        )
        best: tuple[float, int, tuple[float, float, float]] | None = None
        for index in grid.get(key, ()):
            gap, weights = _closest(point, *corners[index])
            if gap <= radius and (best is None or gap < best[0]):
                best = (gap, index, weights)
        if best is None:
            continue
        _, index, (la, lb, lc) = best
        ring = rings[index]
        a, b, c = corners[index]
        u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        normal = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        size = math.sqrt(sum(one * one for one in normal))
        if size == 0:
            continue
        unit = (normal[0] / size, normal[1] / size, normal[2] / size)
        shape: tuple[float, ...]
        if len(ring) >= 6:
            shape = (
                la * (2 * la - 1),
                lb * (2 * lb - 1),
                lc * (2 * lc - 1),
                4 * la * lb,
                4 * lb * lc,
                4 * lc * la,
            )
        else:
            shape = (la, lb, lc)
        rows.append((node, unit, tuple(zip(ring[: len(shape)], shape, strict=True))))
    return rows


def near_nodes(
    nodes: dict[int, tuple[float, float, float]],
    candidates: set[int],
    triangles: list[tuple[int, int, int]],
    radius: float,
) -> set[int]:
    """`candidates` 중 삼각형들에서 `radius` 안에 든 절점 — 격자로 가려 가까운 것만 잰다."""
    if not candidates or not triangles:
        return set()
    edges = [
        math.dist(nodes[one[0]], nodes[one[1]])
        for one in triangles[: min(len(triangles), 500)]
    ]
    cell = max(radius, sum(edges) / len(edges), 1e-9)
    grid: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    corners = [tuple(nodes[n] for n in one) for one in triangles]
    for index, points in enumerate(corners):
        low = [math.floor((min(p[a] for p in points) - radius) / cell) for a in range(3)]
        high = [math.floor((max(p[a] for p in points) + radius) / cell) for a in range(3)]
        for i in range(low[0], high[0] + 1):
            for j in range(low[1], high[1] + 1):
                for k in range(low[2], high[2] + 1):
                    grid[(i, j, k)].append(index)
    found: set[int] = set()
    for node in candidates:
        point = nodes[node]
        key = (
            math.floor(point[0] / cell),
            math.floor(point[1] / cell),
            math.floor(point[2] / cell),
        )
        for index in grid.get(key, ()):
            if _distance(point, *corners[index]) <= radius:
                found.add(node)
                break
    return found


def _distance(
    p: tuple[float, float, float],
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> float:
    """점과 삼각형의 거리."""
    return _closest(p, a, b, c)[0]


def _closest(
    p: tuple[float, float, float],
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[float, tuple[float, float, float]]:
    """점과 삼각형 위의 가장 가까운 점 — (거리, 그 점의 무게중심 좌표(a · b · c 몫)).
    Ericson, Real-Time Collision Detection 의 영역 판정."""

    def sub(u: tuple[float, ...], v: tuple[float, ...]) -> tuple[float, float, float]:
        return (u[0] - v[0], u[1] - v[1], u[2] - v[2])

    def dot(u: tuple[float, ...], v: tuple[float, ...]) -> float:
        return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]

    def at(weights: tuple[float, float, float]) -> tuple[float, tuple[float, float, float]]:
        point = tuple(
            weights[0] * a[k] + weights[1] * b[k] + weights[2] * c[k] for k in range(3)
        )
        return math.dist(p, point), weights

    ab, ac, ap = sub(b, a), sub(c, a), sub(p, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return at((1.0, 0.0, 0.0))
    bp = sub(p, b)
    d3, d4 = dot(ab, bp), dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return at((0.0, 1.0, 0.0))
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        t = d1 / (d1 - d3)
        return at((1 - t, t, 0.0))
    cp = sub(p, c)
    d5, d6 = dot(ab, cp), dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return at((0.0, 0.0, 1.0))
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        t = d2 / (d2 - d6)
        return at((1 - t, 0.0, t))
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return at((0.0, 1 - t, t))
    total = va + vb + vc
    v, w = vb / total, vc / total
    return at((1 - v - w, v, w))


def _area(
    a: tuple[float, float, float], b: tuple[float, float, float], c: tuple[float, float, float]
) -> float:
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    return math.sqrt(sum(one * one for one in cross)) / 2


Box = tuple[float, float, float, float, float, float]


def _box(nodes: dict[int, tuple[float, float, float]], members: set[int]) -> Box:
    points = [nodes[one] for one in members]
    return (
        min(p[0] for p in points),
        min(p[1] for p in points),
        min(p[2] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
        max(p[2] for p in points),
    )


def _grow(box: Box, by: float) -> Box:
    return (box[0] - by, box[1] - by, box[2] - by, box[3] + by, box[4] + by, box[5] + by)


def _meet(first: Box, second: Box, margin: float) -> bool:
    return all(
        first[axis] - margin <= second[axis + 3] and second[axis] - margin <= first[axis + 3]
        for axis in range(3)
    )


def _inside(point: tuple[float, float, float], box: Box) -> bool:
    return all(box[axis] <= point[axis] <= box[axis + 3] for axis in range(3))
