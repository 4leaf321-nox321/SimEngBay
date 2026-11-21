"""lever 본딩 — **간극을 둔 채** 종 절점을 주 요소에 구속식으로 묶는다(2026-11-20).

## 왜 — 앞의 두 방식이 다르게 틀렸다

CompCore 의 STEP 에서 본딩 쌍 일부는 간극이 0.005 mm 를 넘는다. 거기서:

- **v0.28 `*TIE, ADJUST=NO`** — ccx 의 식은 u종 = Σ N·u주 로 **병진만** 묶는다. 종 절점이
  주 면에서 d 떨어져 있으면 강체 회전 ω 에서 ω x d 만큼 어긋나 그 회전을 잡는다 — 가짜 회전
  강성이 생겨 주파수가 높게 나오고, 자유-자유의 회전 강체 모드가 0 Hz 에서 올라온다.
- **v0.30 `*TIE`(옮김, ccx 의 기본)** — 종 절점을 주 면 위로 옮긴다. 간극이 얇은 요소의
  두께에 견줄 만하면 그 요소가 뒤집혀 ccx 가 「nonpositive jacobian」 으로 멈추고, 간극을 메운
  부피만큼 질량도 는다. 용접 쌍을 묶으면 매번 멈춘 모델이 있었다(방향을 바꾸거나 pinball 을
  줄여도 같다).

여기서는 절점을 **옮기지 않고** 간극을 지레(lever)로 잇는다 — Abaqus 기준과 맞는 식이다.

## 식

종 절점 x_s 마다:

1. 주 면에서 **가장 가까운 점** x_p 를 찾는다 — 후보 면 전부에서(먼저 걸린 면이 아니라),
   2차 면이면 곡면 위에서(주 요소의 형상함수로 면을 그려 가우스-뉴턴, `locate`).
2. x_p 에서 주 **요소**(면이 아니라 사면체)의 형상함수 N_a 와 미분 g_a = ∂N_a/∂x.
3. 간극 벡터 d = x_s - x_p.
4. u종 = u(x_p) + θ x d,  θ = ½ ∇ x u = ½ Σ g_a x u_a. 성분마다 식 하나 — x · y · z 셋:

       u_s,i = Σ_a Σ_j [ (N_a + ½ g_a·d) δ_ij - ½ g_a,i d_j ] u_a,j

   등매개 요소는 Σ N_a = 1 · Σ g_a = 0 · Σ x_a g_aᵀ = I 이라 강체 병진 · 회전을 **그대로**
   만족한다(쓴 뒤 다시 잰다 — 「쓴 뒤 검사」).

## 쓰기 전 정리

덱을 다 쓴 뒤 그 덱의 구속을 읽어서(`_Deck`):

- **고정된 자유도는 종속으로 쓰지 않는다**(`*BOUNDARY` — ccx 는 구속된 자유도를 구속식의
  종속으로 못 받는다). 그 방향의 식은 뺀다 — 구속이 이긴다.
- **다른 구속의 종속은 피한다** — `*EQUATION` 의 첫 항, `*RIGID BODY` · `*TIE` 의 종 절점.
  국부 좌표계(`*TRANSFORM`)가 걸린 절점이 낀 식도 뺀다(그 절점의 자유도는 국부로
  읽힌다).
- **두 접합에 걸린 종 절점은 가까운 쪽 하나에만** 묶는다(1번의 「후보 면 전부」 가 접촉을
  넘는다).
- **종속 자유도가 다른 식의 우변에 나오면 대입해 없앤다** — lever 끼리(종 절점이 다른 쌍의 주
  요소 절점일 때)도, 덱에 이미 있는 구속식(볼트 · 기울어진 지지 · 쉘 본딩)과도. 그 구속식을
  고쳤으면 덱의 구속식을 모두 걷어 한 덩이로 다시 쓴다.

## 쓴 뒤 검사

- 식마다 강체 운동 여섯(병진 셋 · 회전 셋)을 넣어 잔차를 잰다(`rigid_residual`).
- 종속 자유도가 두 번 나오지 않는지 · 우변에 남지 않는지 센다(`overlaps`).
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.core.calculix import deck as deck_writer
from app.core.calculix.bonding import _closest

logger = logging.getLogger(__name__)

Vector = tuple[float, float, float]
Dof = tuple[int, int]
"""(절점, 자유도 1 · 2 · 3)."""

#: 사면체 꼭짓점의 자연 좌표 — ccx · Abaqus 의 C3D4 · C3D10(N1 = 1 - r - s - t, N2 = r …).
NATURAL: tuple[Vector, ...] = (
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
)
#: C3D10 중간 절점 5 ~ 10 이 놓인 모서리(꼭짓점 차례) — `mesh._TET10_EDGES` 와 같다.
TET10_EDGES = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))
_CORNER_GRADIENTS: tuple[Vector, ...] = (
    (-1.0, -1.0, -1.0),
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
)
#: 이보다 작은 계수는 적지 않는다 — 맞닿은 면(d = 0)에서 면 밖 절점의 항이 정확히 0 이다.
ZERO = 1e-12
#: 강체 운동 잔차의 허용(식의 계수 · 좌표 크기에 견준 상대값).
RIGID_TOLERANCE = 1e-7
#: 곡면 최근접의 가우스-뉴턴 횟수 · 멈춤.
NEWTON_STEPS = 30
NEWTON_STOP = 1e-13
#: **투영이 주 면 안에 들 때만 묶는다** — 가장 가까운 점이 주 면의 바깥 테두리에 걸려 간극이
#: 면 방향으로 기울었으면(법선에서 45° 넘게) 그 절점은 맞닿은 자리가 아니다. ccx 의 `*TIE` ·
#: Ansys 와 같은 규칙이다. 안 가리면 주 면 테두리 옆 반경 안의 절점까지 옆으로 뻗은 지레로 묶여
#: 접합이 굳는다(판 위 기둥 둘, 판 윗면 하나를 나눠 쓴 모델 — 판 절점 38 개 · 간극 최대 2.1 mm
#: 가 묶여 1차가 `*TIE`(22 개)보다 1.3 % 높았다, 2026-11-20).
SIDEWAYS = 1.0
"""옆 성분 ≤ 이것 x 법선 성분 + `SIDEWAYS_FLOOR` 이면 안이다(tan 45° = 1)."""
SIDEWAYS_FLOOR = 1e-6
"""mm — 테두리에 딱 붙은 절점(간극이 거의 0)은 방향을 따지지 않는다."""


# --- 형상함수 ------------------------------------------------------------------


def shape(count: int, xi: Vector) -> tuple[list[float], list[Vector]]:
    """사면체(`C3D4` · `C3D10`)의 형상함수와 자연 좌표 미분 — 절점 차례는 ccx 의 것."""
    r, s, t = xi
    lam = (1.0 - r - s - t, r, s, t)
    if count == 4:
        return list(lam), list(_CORNER_GRADIENTS)
    if count == 10:
        values = [lam[i] * (2.0 * lam[i] - 1.0) for i in range(4)]
        values += [4.0 * lam[i] * lam[j] for i, j in TET10_EDGES]
        grads = [
            (
                (4.0 * lam[i] - 1.0) * _CORNER_GRADIENTS[i][0],
                (4.0 * lam[i] - 1.0) * _CORNER_GRADIENTS[i][1],
                (4.0 * lam[i] - 1.0) * _CORNER_GRADIENTS[i][2],
            )
            for i in range(4)
        ]
        grads += [
            (
                4.0 * (_CORNER_GRADIENTS[i][0] * lam[j] + lam[i] * _CORNER_GRADIENTS[j][0]),
                4.0 * (_CORNER_GRADIENTS[i][1] * lam[j] + lam[i] * _CORNER_GRADIENTS[j][1]),
                4.0 * (_CORNER_GRADIENTS[i][2] * lam[j] + lam[i] * _CORNER_GRADIENTS[j][2]),
            )
            for i, j in TET10_EDGES
        ]
        return values, grads
    raise ValueError(f"사면체 절점 수가 아닙니다: {count}")


def _point(points: list[Vector], values: list[float]) -> Vector:
    return (
        sum(w * p[0] for w, p in zip(values, points, strict=True)),
        sum(w * p[1] for w, p in zip(values, points, strict=True)),
        sum(w * p[2] for w, p in zip(values, points, strict=True)),
    )


def gradients(points: list[Vector], natural: list[Vector]) -> list[Vector]:
    """∂N/∂x — J = Σ x_a ⊗ ∂N_a/∂ξ, ∂N/∂x = J⁻ᵀ ∂N/∂ξ. 뒤집힌 요소면 `ValueError`."""
    j = [
        [sum(points[n][a] * natural[n][b] for n in range(len(points))) for b in range(3)]
        for a in range(3)
    ]
    det = (
        j[0][0] * (j[1][1] * j[2][2] - j[1][2] * j[2][1])
        - j[0][1] * (j[1][0] * j[2][2] - j[1][2] * j[2][0])
        + j[0][2] * (j[1][0] * j[2][1] - j[1][1] * j[2][0])
    )
    if det <= 0:
        raise ValueError("주 요소의 야코비안이 0 이하입니다")
    inv = [
        [
            (
                j[(c + 1) % 3][(r + 1) % 3] * j[(c + 2) % 3][(r + 2) % 3]
                - j[(c + 1) % 3][(r + 2) % 3] * j[(c + 2) % 3][(r + 1) % 3]
            )
            / det
            for c in range(3)
        ]
        for r in range(3)
    ]
    # inv[b][a] = (J⁻¹)_ba — ∂N/∂x_a = Σ_b (J⁻¹)_ba ∂N/∂ξ_b.
    return [
        (
            inv[0][0] * dn[0] + inv[1][0] * dn[1] + inv[2][0] * dn[2],
            inv[0][1] * dn[0] + inv[1][1] * dn[1] + inv[2][1] * dn[2],
            inv[0][2] * dn[0] + inv[1][2] * dn[1] + inv[2][2] * dn[2],
        )
        for dn in natural
    ]


# --- 주 면 위 가장 가까운 점 --------------------------------------------------------


def _in_triangle(w1: float, w2: float) -> tuple[float, float]:
    """자연 좌표의 삼각형(w1 ≥ 0 · w2 ≥ 0 · w1 + w2 ≤ 1)으로 되돌린다."""
    w1, w2 = max(w1, 0.0), max(w2, 0.0)
    over = w1 + w2 - 1.0
    if over > 0:
        w1, w2 = w1 - over / 2, w2 - over / 2
        if w1 < 0:
            w1, w2 = 0.0, 1.0
        elif w2 < 0:
            w1, w2 = 1.0, 0.0
    return w1, w2


def locate(target: Vector, points: list[Vector], face: str) -> tuple[float, Vector, Vector]:
    """요소 `points` 의 면 `face`(`P1` ~ `P4`) 위에서 `target` 에 가장 가까운 점 —
    (거리, 그 점, 그 점의 요소 자연 좌표). 그 점의 면 법선은 `normal_at`.

    면은 **요소의 형상함수로 그린다** — 2차 요소면 곡면이다(평평한 삼각형에 투영하면 처짐만큼
    틀린 x_p 에서 N · ∂N 를 잰다). 꼭짓점 삼각형에 투영한 자리에서 가우스-뉴턴으로 다듬는다."""
    corners = deck_writer.TET_FACES[face]
    base = NATURAL[corners[0]]
    e1 = tuple(NATURAL[corners[1]][k] - base[k] for k in range(3))
    e2 = tuple(NATURAL[corners[2]][k] - base[k] for k in range(3))
    _, (_, w1, w2) = _closest(target, *(points[one] for one in corners))
    count = len(points)

    def at(w1: float, w2: float) -> tuple[Vector, Vector, list[float], list[Vector]]:
        xi = (
            base[0] + w1 * e1[0] + w2 * e2[0],
            base[1] + w1 * e1[1] + w2 * e2[1],
            base[2] + w1 * e1[2] + w2 * e2[2],
        )
        values, natural = shape(count, xi)
        return xi, _point(points, values), values, natural

    xi, here, _, natural = at(w1, w2)
    if count > 4:
        for _step in range(NEWTON_STEPS):
            t1 = _point(points, [d[0] * e1[0] + d[1] * e1[1] + d[2] * e1[2] for d in natural])
            t2 = _point(points, [d[0] * e2[0] + d[1] * e2[1] + d[2] * e2[2] for d in natural])
            r = (here[0] - target[0], here[1] - target[1], here[2] - target[2])
            a11, a12, a22 = _dot(t1, t1), _dot(t1, t2), _dot(t2, t2)
            b1, b2 = -_dot(t1, r), -_dot(t2, r)
            det = a11 * a22 - a12 * a12
            if det <= 0:
                break
            d1 = (b1 * a22 - b2 * a12) / det
            d2 = (a11 * b2 - a12 * b1) / det
            n1, n2 = _in_triangle(w1 + d1, w2 + d2)
            moved = abs(n1 - w1) + abs(n2 - w2)
            w1, w2 = n1, n2
            xi, here, _, natural = at(w1, w2)
            if moved < NEWTON_STOP:
                break
    return math.dist(target, here), here, xi


def normal_at(points: list[Vector], face: str, xi: Vector) -> Vector:
    """요소면 `face` 의 자연 좌표 `xi` 자리 단위 법선(방향은 따지지 않는다) — 곡면의 접선 둘의
    외적."""
    corners = deck_writer.TET_FACES[face]
    base = NATURAL[corners[0]]
    e1 = tuple(NATURAL[corners[1]][k] - base[k] for k in range(3))
    e2 = tuple(NATURAL[corners[2]][k] - base[k] for k in range(3))
    _, natural = shape(len(points), xi)
    t1 = _point(points, [d[0] * e1[0] + d[1] * e1[1] + d[2] * e1[2] for d in natural])
    t2 = _point(points, [d[0] * e2[0] + d[1] * e2[1] + d[2] * e2[2] for d in natural])
    cross = (
        t1[1] * t2[2] - t1[2] * t2[1],
        t1[2] * t2[0] - t1[0] * t2[2],
        t1[0] * t2[1] - t1[1] * t2[0],
    )
    size = math.sqrt(_dot(cross, cross))
    return (cross[0] / size, cross[1] / size, cross[2] / size) if size > 0 else (0.0, 0.0, 0.0)


def inside(target: Vector, here: Vector, normal: Vector) -> bool:
    """종 절점의 투영이 주 면 안인가 — 간극이 법선에서 45° 안(`SIDEWAYS`)이거나 거의 0."""
    d = (target[0] - here[0], target[1] - here[1], target[2] - here[2])
    along = abs(_dot(d, normal))
    sideways = math.sqrt(max(_dot(d, d) - along * along, 0.0))
    return sideways <= SIDEWAYS * along + SIDEWAYS_FLOOR


def _dot(a: Vector, b: Vector) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def lever_terms(
    slave_point: Vector, element: list[int], points: list[Vector], xi: Vector
) -> tuple[Vector, dict[int, dict[Dof, float]]]:
    """x_p(자연 좌표 `xi`)에서의 lever 식 — (간극 d, 자유도 i → {(주 절점, j): 계수})."""
    values, natural = shape(len(points), xi)
    grads = gradients(points, natural)
    here = _point(points, values)
    d = (slave_point[0] - here[0], slave_point[1] - here[1], slave_point[2] - here[2])
    rows: dict[int, dict[Dof, float]] = {1: {}, 2: {}, 3: {}}
    for node, n_a, g_a in zip(element, values, grads, strict=True):
        along = n_a + 0.5 * _dot(g_a, d)
        for i in range(3):
            for j in range(3):
                c = (along if i == j else 0.0) - 0.5 * g_a[i] * d[j]
                if abs(c) > ZERO:
                    key = (node, j + 1)
                    rows[i + 1][key] = rows[i + 1].get(key, 0.0) + c
    return d, rows


# --- 덱 읽기 ----------------------------------------------------------------------


@dataclass
class _Equation:
    terms: list[tuple[int, int, float]]
    """(절점, 자유도, 계수) — 첫 항이 종속이다."""


@dataclass
class _Deck:
    """덱에 이미 있는 구속 — lever 식이 피하고 대입할 것."""

    lines: list[str]
    first_step: int
    fixed: set[Dof] = field(default_factory=set)
    opaque: set[Dof] = field(default_factory=set)
    """식이 아닌 구속의 종속 — `*RIGID BODY` · `*TIE` 의 종 절점(ccx 가 안에서 식을 세운다)."""
    equations: list[_Equation] = field(default_factory=list)
    spans: list[tuple[int, int]] = field(default_factory=list)
    """`*EQUATION` 덩이의 줄 자리(시작, 끝 다음)."""
    transformed: set[int] = field(default_factory=set)
    coordinates: dict[int, Vector] = field(default_factory=dict)


_PARAM = re.compile(r"([A-Za-z ]+)=\s*([^,]+)")


def _keyword(line: str) -> tuple[str, dict[str, str]]:
    head, *rest = line[1:].split(",")
    params: dict[str, str] = {}
    for one in rest:
        if "=" in one:
            key, value = one.split("=", 1)
            params[key.strip().upper()] = value.strip()
        elif one.strip():
            params[one.strip().upper()] = ""
    return head.strip().upper(), params


def _numbers(text: str) -> list[str]:
    return [one.strip() for one in text.split(",") if one.strip()]


def read_deck(text: str) -> _Deck:
    lines = text.split("\n")
    first_step = next(
        (at for at, line in enumerate(lines) if line.upper().startswith("*STEP")), len(lines)
    )
    deck = _Deck(lines=lines, first_step=first_step)
    nsets: dict[str, set[int]] = defaultdict(set)
    surfaces: dict[str, list[str]] = {}
    pending_nset_refs: list[tuple[str, str]] = []
    boundary_rows: list[list[str]] = []
    rigid_sets: list[str] = []
    tie_slaves: list[str] = []
    transform_sets: list[str] = []
    at = 0
    while at < len(lines):
        line = lines[at]
        if not line.startswith("*") or line.startswith("**"):
            at += 1
            continue
        name, params = _keyword(line)
        start = at
        at += 1
        data: list[str] = []
        while at < len(lines) and not (
            lines[at].startswith("*") and not lines[at].startswith("**")
        ):
            if lines[at].strip() and not lines[at].startswith("**"):
                data.append(lines[at])
            at += 1
        if name == "NSET":
            set_name = params.get("NSET", "").upper()
            generate = "GENERATE" in params
            for row in data:
                parts = _numbers(row)
                if generate and len(parts) >= 2:
                    step = int(parts[2]) if len(parts) > 2 else 1
                    nsets[set_name] |= set(range(int(parts[0]), int(parts[1]) + 1, step))
                    continue
                for part in parts:
                    if part.lstrip("-").isdigit():
                        nsets[set_name].add(int(part))
                    else:
                        pending_nset_refs.append((set_name, part.upper()))
        elif name == "NODE":
            for row in data:
                parts = _numbers(row)
                if len(parts) >= 4:
                    with _quiet():
                        deck.coordinates[int(parts[0])] = (
                            float(parts[1]),
                            float(parts[2]),
                            float(parts[3]),
                        )
        elif name == "SURFACE" and params.get("TYPE", "").upper() == "NODE":
            surfaces[params.get("NAME", "").upper()] = [
                part.upper() for row in data for part in _numbers(row)
            ]
        elif name == "BOUNDARY":
            boundary_rows += [_numbers(row) for row in data]
        elif name == "RIGID BODY":
            rigid_sets.append(params.get("NSET", "").upper())
        elif name == "TIE":
            for row in data:
                parts = _numbers(row)
                if parts:
                    tie_slaves.append(parts[0].upper())
        elif name == "TRANSFORM":
            transform_sets.append(params.get("NSET", "").upper())
        elif name == "EQUATION":
            deck.spans.append((start, at))
            values = [part for row in data for part in _numbers(row)]
            k = 0
            while k < len(values):
                count = int(values[k])
                k += 1
                chunk = values[k : k + 3 * count]
                k += 3 * count
                deck.equations.append(
                    _Equation(
                        [
                            (int(chunk[m]), int(chunk[m + 1]), float(chunk[m + 2]))
                            for m in range(0, len(chunk), 3)
                        ]
                    )
                )
    for target, source in pending_nset_refs:
        nsets[target] |= nsets.get(source, set())

    def members(token: str) -> set[int]:
        token = token.strip()
        if token.lstrip("-").isdigit():
            return {int(token)}
        return set(nsets.get(token.upper(), set()))

    for entry in boundary_rows:
        if len(entry) < 2:
            continue
        first = int(entry[1])
        last = int(entry[2]) if len(entry) > 2 and entry[2].lstrip("-").isdigit() else first
        for node in members(entry[0]):
            deck.fixed |= {(node, dof) for dof in range(first, last + 1)}
    for set_name in rigid_sets:
        deck.opaque |= {(node, dof) for node in members(set_name) for dof in (1, 2, 3)}
    for surface in tie_slaves:
        for token in surfaces.get(surface, [surface]):
            deck.opaque |= {(node, dof) for node in members(token) for dof in (1, 2, 3)}
    for set_name in transform_sets:
        deck.transformed |= members(set_name)
    return deck


class _quiet:
    """숫자가 아닌 *NODE 줄(머리 · 주석)은 건너뛴다."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind: Any, value: Any, trace: Any) -> bool:
        return kind is ValueError


# --- 묶기 ------------------------------------------------------------------------


@dataclass
class Result:
    """lever 단계의 결과 — 새 덱 · 쌍마다 몇 절점 · 사람에게 할 말 · 검사."""

    text: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    """쌍마다 `{name, contact, radius, slaves, tied, far, max_gap_mm}`."""
    notes: list[str] = field(default_factory=list)
    equations: int = 0
    rigid_residual: float = 0.0
    """식마다 강체 운동 여섯을 넣은 잔차의 가장 큰 값(상대)."""
    rigid_failed: int = 0
    overlaps: int = 0
    """종속 자유도가 두 번 나오거나 우변에 남은 수 — 0 이어야 한다."""


@dataclass
class _Hit:
    pair: int
    distance: float
    element: int
    face: str
    point: Vector
    xi: Vector


def _candidates(
    nodes: dict[int, Vector],
    elements: dict[int, list[int]],
    faces: list[tuple[int, str]],
    reach: float,
) -> tuple[float, dict[tuple[int, int, int], list[int]]]:
    """주 면을 격자에 넣는다 — 꼭짓점 삼각형의 상자를 `reach` 만큼 키운 칸마다."""
    corners = [
        tuple(nodes[elements[element][one]] for one in deck_writer.TET_FACES[face])
        for element, face in faces
    ]
    edges = [math.dist(one[0], one[1]) for one in corners[: min(len(corners), 500)]]
    cell = max(reach, sum(edges) / len(edges) if edges else 1.0, 1e-9)
    grid: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index, points in enumerate(corners):
        low = [math.floor((min(p[a] for p in points) - reach) / cell) for a in range(3)]
        high = [math.floor((max(p[a] for p in points) + reach) / cell) for a in range(3)]
        for i in range(low[0], high[0] + 1):
            for j in range(low[1], high[1] + 1):
                for k in range(low[2], high[2] + 1):
                    grid[(i, j, k)].append(index)
    return cell, grid


def _nearest(
    nodes: dict[int, Vector],
    elements: dict[int, list[int]],
    pairs: list[deck_writer.Lever],
) -> tuple[dict[int, _Hit], dict[int, int]]:
    """종 절점마다 **후보 면 전부에서** 가장 가까운 주 면의 점 — 한 절점이 두 쌍의 종이면 더
    가까운 쪽(「두 접합에 걸린 절점은 가까운 쪽 하나에만」). (종 → 맞은 자리, 종 → 반경 밖이라
    안 묶인 쌍)."""
    hits: dict[int, _Hit] = {}
    far: dict[int, int] = {}
    outside: dict[int, int] = {}
    for index, pair in enumerate(pairs):
        faces = list(pair.master_faces)
        if not faces or not pair.slave_nodes:
            continue
        # 2차 면은 꼭짓점 삼각형보다 처진다 — 그만큼 넉넉히 찾고 곡면 거리로 거른다.
        slack = pair.tolerance + 0.25 * max(
            (
                math.dist(nodes[elements[e][0]], nodes[elements[e][1]])
                for e, _ in faces[: min(len(faces), 200)]
            ),
            default=0.0,
        )
        cell, grid = _candidates(nodes, elements, faces, slack)
        for slave in pair.slave_nodes:
            point = nodes[slave]
            key = (
                math.floor(point[0] / cell),
                math.floor(point[1] / cell),
                math.floor(point[2] / cell),
            )
            best: _Hit | None = None
            for at in grid.get(key, ()):
                element, face = faces[at]
                ids = elements[element]
                points = [nodes[one] for one in ids]
                corners = [points[one] for one in deck_writer.TET_FACES[face]]
                if _closest(point, *corners)[0] > slack:
                    continue
                distance, here, xi = locate(point, points, face)
                if best is None or distance < best.distance:
                    best = _Hit(index, distance, element, face, here, xi)
            if best is not None and not inside(
                point,
                best.point,
                normal_at([nodes[one] for one in elements[best.element]], best.face, best.xi),
            ):
                # 주 면 테두리 옆 — 맞닿은 자리가 아니다(`SIDEWAYS`).
                outside.setdefault(slave, index)
                continue
            if best is None or best.distance > pair.tolerance:
                far.setdefault(slave, index)
                continue
            held = hits.get(slave)
            if held is None or best.distance < held.distance:
                hits[slave] = best
    for slave in hits:
        far.pop(slave, None)
        outside.pop(slave, None)
    for slave, owner in outside.items():
        far.setdefault(slave, owner)
    return hits, far


def apply(
    text: str,
    nodes: dict[int, Vector],
    elements: dict[int, list[int]],
    pairs: list[deck_writer.Lever],
) -> Result:
    """덱을 다 쓴 뒤 lever 구속식을 넣는다 — 정리 · 대입 · 검사를 거쳐 첫 `*STEP` 앞에."""
    deck = read_deck(text)
    hits, far = _nearest(nodes, elements, pairs)
    notes: list[str] = []
    existing: dict[Dof, dict[Dof, float]] = {}
    for one in deck.equations:
        node, dof, value = one.terms[0]
        existing[(node, dof)] = {(n, d): -c / value for n, d, c in one.terms[1:] if abs(c) > 0}
    blocked_fixed = blocked_taken = blocked_frame = 0
    lever: dict[Dof, dict[Dof, float]] = {}
    tied_by_pair: dict[int, set[int]] = defaultdict(set)
    gap_by_pair: dict[int, float] = defaultdict(float)
    for slave in sorted(hits):
        hit = hits[slave]
        ids = elements[hit.element]
        if slave in deck.transformed or deck.transformed.intersection(ids):
            blocked_frame += 1
            continue
        d, terms = lever_terms(nodes[slave], ids, [nodes[one] for one in ids], hit.xi)
        made = False
        for dof, row in terms.items():
            key = (slave, dof)
            if key in deck.fixed:
                blocked_fixed += 1
                continue
            if key in existing or key in deck.opaque:
                blocked_taken += 1
                continue
            lever[key] = row
            made = True
        if made:
            tied_by_pair[hit.pair].add(slave)
            gap_by_pair[hit.pair] = max(gap_by_pair[hit.pair], math.sqrt(_dot(d, d)))
    if blocked_fixed:
        notes.append(
            f"고정된 자유도 {blocked_fixed}개는 lever 식의 종속으로 쓰지 않았습니다(구속이 "
            "이깁니다)."
        )
    if blocked_taken:
        notes.append(
            f"다른 구속(구속식 · 강체 · TIE)의 종속인 자유도 {blocked_taken}개는 lever 식에서 "
            "뺐습니다."
        )
    if blocked_frame:
        notes.append(
            f"국부 좌표계(원통 지지)가 걸린 절점이 낀 종 절점 {blocked_frame}개는 lever 로 "
            "묶지 않았습니다 — 그 절점의 자유도는 국부로 읽혀 전역 계수가 틀립니다."
        )

    # **대입** — 종속 자유도가 우변에 나오면 그 식으로 바꾼다(lever 끼리 · 덱의 구속식과).
    source: dict[Dof, dict[Dof, float]] = {**existing, **lever}
    done: dict[Dof, dict[Dof, float]] = {}
    mixed: set[Dof] = set()
    """대입에 덱의 구속식이 섞인 식 — 강체 운동의 식이 아니라서 잔차를 재지 않는다."""
    cyclic: set[Dof] = set()

    def resolve(dep: Dof, visiting: set[Dof]) -> dict[Dof, float]:
        if dep in done:
            return done[dep]
        if dep in visiting:
            raise _Cycle(dep)
        visiting.add(dep)
        out: dict[Dof, float] = defaultdict(float)
        for term, c in source[dep].items():
            if term in source:
                for inner, c2 in resolve(term, visiting).items():
                    out[inner] += c * c2
                if term in existing or term in mixed:
                    mixed.add(dep)
            else:
                out[term] += c
        visiting.discard(dep)
        clean = {key: value for key, value in out.items() if abs(value) > ZERO}
        done[dep] = clean
        return clean

    final: dict[Dof, dict[Dof, float]] = {}
    for dep in list(lever):
        try:
            final[dep] = resolve(dep, set())
        except _Cycle:
            cyclic.add(dep)
    for dep in cyclic:
        lever.pop(dep, None)
    if cyclic:
        notes.append(f"서로를 가리키는 lever 식 {len(cyclic)}개는 뺐습니다(대입이 돌고 돈다).")
    deps = set(lever)
    rewritten: dict[Dof, dict[Dof, float]] = {}
    for dep, expr in existing.items():
        if any(term in deps for term in expr):
            try:
                rewritten[dep] = resolve(dep, set())
            except _Cycle:
                cyclic.add(dep)
    can_rewrite = all(end <= deck.first_step for _, end in deck.spans)
    if rewritten and not can_rewrite:
        # 덱의 구속식이 단계 안에 있으면 걷어 다시 쓸 수 없다 — 그 식이 가리키는 lever 종속을
        # 뺀다.
        drop = {term for expr in (existing[dep] for dep in rewritten) for term in expr} & deps
        for dep in drop:
            lever.pop(dep, None)
            final.pop(dep, None)
        notes.append(f"덱의 구속식에 걸린 lever 식 {len(drop)}개는 뺐습니다.")
        rewritten = {}

    # **쓴 뒤 검사** — 강체 운동 여섯 · 종속의 겹침.
    coordinates = {**deck.coordinates, **nodes}
    worst = 0.0
    failed = 0
    for dep, expr in final.items():
        if dep in mixed:
            continue
        residual = rigid_residual(dep, expr, coordinates)
        if residual is None:
            continue
        worst = max(worst, residual)
        if residual > RIGID_TOLERANCE:
            failed += 1
    dependents = list(final) + [dep for dep in existing if dep not in final]
    seen: set[Dof] = set()
    overlaps = 0
    for dep in dependents:
        if dep in seen or dep in deck.fixed or dep in deck.opaque:
            overlaps += 1
        seen.add(dep)
    for expr in (*final.values(), *rewritten.values()):
        overlaps += sum(1 for term in expr if term in seen)
    if failed:
        notes.append(
            f"강체 운동을 그대로 만족하지 않는 lever 식이 {failed}개 있습니다(가장 큰 잔차 "
            f"{worst:.3g}) — 그 자리에서 가짜 강성이 생길 수 있습니다."
        )
    if overlaps:
        notes.append(
            f"종속 자유도가 겹친 자리가 {overlaps}개 있습니다 — ccx 가 거절할 수 있습니다."
        )

    # **쓰기** — 첫 `*STEP` 앞에. 덱의 구속식을 고쳤으면 그 덩이들을 걷고 한 덩이로.
    block = ["** lever 본딩 — 간극을 둔 채 묶는다(`calculix/lever.py`)."]
    written = dict(final)
    lines = list(deck.lines)
    if rewritten:
        for start, end in sorted(deck.spans, reverse=True):
            del lines[start:end]
        removed = sum(end - start for start, end in deck.spans if end <= deck.first_step)
        insert_at = deck.first_step - removed
        for one in deck.equations:
            dep = (one.terms[0][0], one.terms[0][1])
            if dep in rewritten:
                written[dep] = rewritten[dep]
            else:
                written[dep] = existing[dep]
    else:
        insert_at = deck.first_step
    if written:
        block += _equation_lines(written)
    lines[insert_at:insert_at] = block
    rows = [
        {
            "name": pair.name,
            "contact": pair.contact,
            "radius": pair.tolerance,
            "slaves": sorted(pair.slave_nodes),
            "tied": len(tied_by_pair.get(index, set())),
            "far": sum(1 for owner in far.values() if owner == index),
            "max_gap_mm": round(gap_by_pair.get(index, 0.0), 6),
        }
        for index, pair in enumerate(pairs)
    ]
    logger.info(
        "lever 본딩 — 식 %s 개 · 강체 잔차 %.3g · 겹침 %s", len(final), worst, overlaps
    )
    return Result(
        text="\n".join(lines),
        rows=rows,
        notes=notes,
        equations=len(final),
        rigid_residual=worst,
        rigid_failed=failed,
        overlaps=overlaps,
    )


class _Cycle(Exception):
    pass


def rigid_residual(
    dep: Dof, expr: dict[Dof, float], coordinates: dict[int, Vector]
) -> float | None:
    """u_dep - Σ c u 에 강체 병진 셋 · 회전 셋을 넣은 가장 큰 잔차(상대). 좌표를 모르는 절점이
    끼면 None — 덱이 세운 기준점(볼트 · 원격점)이 대입으로 들어온 식은 강체 운동의 식이
    아니다."""
    every = [dep[0], *(node for node, _ in expr)]
    if any(node not in coordinates for node in every):
        return None
    scale = max(1.0, *(abs(v) for node in every for v in coordinates[node]))
    weight = max(1.0, *(abs(c) for c in expr.values()))
    worst = 0.0
    for motion in range(6):

        def moved(node: int, dof: int, motion: int = motion) -> float:
            if motion < 3:
                return 1.0 if dof - 1 == motion else 0.0
            x = coordinates[node]
            omega = [0.0, 0.0, 0.0]
            omega[motion - 3] = 1.0
            cross = (
                omega[1] * x[2] - omega[2] * x[1],
                omega[2] * x[0] - omega[0] * x[2],
                omega[0] * x[1] - omega[1] * x[0],
            )
            return cross[dof - 1]

        value = moved(*dep) - sum(c * moved(node, dof) for (node, dof), c in expr.items())
        size = 1.0 if motion < 3 else scale
        worst = max(worst, abs(value) / (size * weight))
    return worst


def _equation_lines(equations: dict[Dof, dict[Dof, float]]) -> list[str]:
    """`*EQUATION` — 첫 항이 종속(계수 1), 한 줄에 넷까지."""
    out = ["*EQUATION"]
    for (node, dof), expr in equations.items():
        terms = [(node, dof, 1.0)] + [
            (other, axis, -value) for (other, axis), value in sorted(expr.items())
        ]
        out.append(str(len(terms)))
        for at in range(0, len(terms), 4):
            out.append(", ".join(f"{n}, {d}, {v:.12g}" for n, d, v in terms[at : at + 4]))
    return out


def slaves_of(rows: Iterable[dict[str, Any]]) -> int:
    """묶인 종 절점 수의 합 — 요약 한 줄."""
    return sum(int(row.get("tied") or 0) for row in rows)
