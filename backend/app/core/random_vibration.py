"""**랜덤 진동** — 가속도 PSD 로 지지부를 흔든 응답의 1σ(실효값). 모드 중첩으로 셈한다.

CompCore 의 가진 프로파일(2026-11-17): 해석 `random` 과 하중 `psd_acceleration`(모든 고정
지지를 `direction` 으로, `psd_table` 은 g²/Hz · 로그-로그 · 표 밖 0). 여럿이면 서로 무관한
가진으로 더한다.

## 어떻게 푸나

모드를 풀고(모달 덱 그대로), **모드 형상 φ · 참여계수 Γ · 고유진동수 ωₘ** 로 기저 가진의
응답을 셈한다 — Ansys 의 랜덤 진동(모드 중첩)과 같은 길이다.

    상대 변위 u(f) = Σₘ φₘ · Γₘ · hₘ(f),  hₘ(f) = -g / (ωₘ² - Ω² + 2iζωₘΩ)   (1 g 가진당)
    절대 가속도 a(f) = -Ω² · u(f) / g + d                                     (g / g)
    응답 PSD = |a(f)|² · S(f),  1σ = √∫ 응답 PSD df

Γ 는 `.dat` 의 참여계수(질량 정규화 모드)를 가진 방향 d 로 모은 것이다. **CalculiX 의 조화
응답(`*STEADY STATE DYNAMICS`, 같은 모드 · 같은 감쇠)과 측정점 변위가 상대 2x10⁻⁵ 안에서 같다**
(실측 2026-11-17, 조건_사인스윕 기둥 끝 20 ~ 2,000 Hz — 차이는 `.dat` 표의 유효 숫자다).
조화 응답 덱을 PSD 방향마다 풀어도 되지만, 그 길은 주파수 점마다 모든 절점을 `.frd` 에 적어
큰 모델에서 수 GB 가 된다. 이 길은 모드 수만큼만 적고, 적분 격자도 우리가 정한다.

## 적분 격자

로그 간격 바탕에 **모드마다 반전력 폭(2ζfₘ)을 촘촘히** 더하고 PSD 표의 꺾인 점을 넣는다. 그
위에서 사다리꼴로 적분한다 — 봉우리 폭의 1/20 간격이라 봉우리를 놓치지 않는다. 한 자유도
진동계에서 정확한 적분과 0.1 % 안에서 같다(`tests/unit/test_random_vibration.py`).

numpy 없이 쓴다 — CalculiX 워커(API 와 같은 파이썬)에는 numpy 가 없다.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.core import conditions as condition_model
from app.core.excitation import G_MM_S2

#: `boundary.json` 의 열쇠 — 모델링이 적고 추출이 읽는다.
KEY = "random"

#: 바탕 격자의 점 수(로그 간격).
BASE_POINTS = 400
#: 모드 둘레에 더하는 자리 — fₘ(1 ± ζ·x). 반전력 폭이 x = 1 이고, 0.04 에서 40 까지 등비(1.12
#: 배)로 놓는다 — 봉우리 꼬리(∝ 1/x²)를 사다리꼴로 적분할 때 간격비가 크면 몇 % 넘친다.
_AROUND = (0.0, *(0.04 * 1.12**at for at in range(62)))
#: 가장 높은 모드가 가진 대역 위끝의 이 배수에 못 미치면 「모드를 늘리라」 고 적는다 — 위쪽
#: 모드의 정적 몫이 빠진다(Ansys 가 권하는 기준).
MODE_REACH = 1.5


@dataclass(frozen=True)
class Shake:
    """가진 하나 — 전역 단위 방향 · PSD 표(Hz, g²/Hz) · CompCore 가 셈한 Grms(견줌용)."""

    name: str
    direction: tuple[float, float, float]
    table: tuple[tuple[float, float], ...]
    declared_grms: float | None = None

    def as_boundary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "direction": list(self.direction),
            "table": [list(one) for one in self.table],
            "declared_grms": self.declared_grms,
        }


@dataclass(frozen=True)
class RandomPlan:
    """랜덤 진동을 **무엇으로 풀 것인가** — 범위 · 감쇠비 · 가진들. 덱 · 요약 · 결과가 같은
    것을 말하게 한 자리에서 정한다(`harmonic.HarmonicPlan` 과 같은 규칙)."""

    low: float
    high: float
    """**가진 대역** — PSD 표들이 덮는 범위(표 밖은 0). CAD 의 `frequency_range` 는 모드를 찾을
    범위라 여기 쓰지 않는다(CompCore 계약 2026-11-17, `modes.search`)."""
    damping_ratio: float
    shakes: tuple[Shake, ...]
    residual_steps: int = 0
    """덱이 고유치 단계 뒤에 붙인 **1 g 정적 단계 수**(가진마다 하나, 잔여 벡터) — `.frd` 의
    마지막 변위 블록들이다. 0 이면 붙이지 못했다(선응력 · 비선형 접촉)."""

    def as_boundary(self) -> dict[str, Any]:
        return {
            "band_hz": [self.low, self.high],
            "damping_ratio": self.damping_ratio,
            "shakes": [one.as_boundary() for one in self.shakes],
            "residual_steps": self.residual_steps,
        }


def plan(
    given: condition_model.Conditions, *, damping_ratio: float
) -> tuple[RandomPlan | None, list[condition_model.Note]]:
    """CAD 조건과 스펙(감쇠비)을 합친다. **못 풀면 까닭을 돌려준다** — 가진이 없거나, 좌표계를
    못 찾았을 때. 가진 대역은 PSD 표들이 덮는 범위다."""
    refused: list[condition_model.Note] = []
    shakes: list[Shake] = []
    for psd in given.psd:
        moved = condition_model.in_global(
            condition_model.Load(
                name=psd.name, kind="acceleration", cs=psd.cs, direction=psd.direction
            ),
            given.frames,
        )
        if isinstance(moved, str) or moved.direction is None:
            refused.append(
                condition_model.Note(f"하중 「{psd.name}」(가속도 PSD)", str(moved))
            )
            continue
        size = math.sqrt(sum(one * one for one in moved.direction))
        shakes.append(
            Shake(
                name=psd.name,
                direction=(
                    moved.direction[0] / size,
                    moved.direction[1] / size,
                    moved.direction[2] / size,
                ),
                table=psd.table,
                declared_grms=psd.grms,
            )
        )
    if refused:
        return None, refused
    if not shakes:
        return None, [
            condition_model.Note(
                "랜덤 진동",
                "흔드는 가속도 PSD 가 하나도 없습니다 — CAD 조건에 psd_acceleration 하중이"
                " 있어야 합니다.",
            )
        ]
    low = min(one.table[0][0] for one in shakes)
    high = max(one.table[-1][0] for one in shakes)
    damping = given.analysis.damping_ratio
    return (
        RandomPlan(
            low=low,
            high=high,
            damping_ratio=damping if damping is not None and damping > 0 else damping_ratio,
            shakes=tuple(shakes),
        ),
        [],
    )


def read(payload: dict[str, Any]) -> RandomPlan | None:
    """`boundary.json` 에 남긴 설정. 없거나 깨졌으면 None."""
    block = payload.get(KEY) if isinstance(payload, dict) else None
    if not isinstance(block, dict):
        return None
    try:
        low, high = (float(one) for one in block["band_hz"])
        shakes = tuple(
            Shake(
                name=str(row["name"]),
                direction=tuple(float(one) for one in row["direction"])[:3],  # type: ignore[arg-type]
                table=tuple((float(a), float(b)) for a, b in row["table"]),
                declared_grms=(
                    float(row["declared_grms"])
                    if isinstance(row.get("declared_grms"), int | float)
                    else None
                ),
            )
            for row in block["shakes"]
        )
        return RandomPlan(
            low=low,
            high=high,
            damping_ratio=float(block["damping_ratio"]),
            shakes=shakes,
            residual_steps=int(block.get("residual_steps") or 0),
        )
    except (KeyError, TypeError, ValueError):
        return None


# --- PSD 표 ------------------------------------------------------------------


def psd_at(table: Sequence[tuple[float, float]], hz: float) -> float:
    """그 주파수의 PSD(g²/Hz) — 로그-로그 보간, **표 밖은 0**(CompCore · Ansys 와 같은 뜻)."""
    if not table or hz < table[0][0] or hz > table[-1][0]:
        return 0.0
    for (f1, p1), (f2, p2) in itertools.pairwise(table):
        if hz <= f2:
            slope = math.log(p2 / p1) / math.log(f2 / f1)
            return float(p1 * (hz / f1) ** slope)
    return table[-1][1]


def grms(
    table: Sequence[tuple[float, float]], low: float = 0.0, high: float = math.inf
) -> float:
    """표의 Grms(g) — 로그-로그 구간마다 **닫힌 꼴로** 적분한다. `low` · `high` 로 자른다.

    CompCore 손셈(조건_랜덤진동): 20 ~ 2,000 Hz 6.058 g."""
    total = 0.0
    for (f1, p1), (f2, p2) in itertools.pairwise(table):
        a, b = max(f1, low), min(f2, high)
        if not a < b:
            continue
        slope = math.log(p2 / p1) / math.log(f2 / f1)
        if math.isclose(slope, -1.0, abs_tol=1e-12):
            total += p1 * f1 * math.log(b / a)
        else:
            total += p1 / (f1**slope) * (b ** (slope + 1) - a ** (slope + 1)) / (slope + 1)
    return math.sqrt(max(total, 0.0))


# --- 격자 · 모드 중첩 --------------------------------------------------------


def grid(
    low: float,
    high: float,
    naturals: Iterable[float],
    damping_ratio: float,
    breaks: Iterable[float] = (),
) -> list[float]:
    """적분 · 그림 격자(Hz) — 로그 바탕 + 모드 둘레 + PSD 꺾인 점. 커지는 차례, 겹침 없음."""
    found = {low, high}
    ratio = (high / low) if low > 0 else None
    for at in range(BASE_POINTS + 1):
        if ratio is not None:
            found.add(low * ratio ** (at / BASE_POINTS))
        else:
            found.add(low + (high - low) * at / BASE_POINTS)
    for natural in naturals:
        if natural <= 0 or math.isinf(natural):
            continue
        for offset in _AROUND:
            for sign in (1.0, -1.0):
                hz = natural * (1 + sign * damping_ratio * offset)
                if low <= hz <= high:
                    found.add(hz)
    found.update(one for one in breaks if low <= one <= high)
    ordered = sorted(found)
    kept = [ordered[0]]
    for hz in ordered[1:]:
        if hz - kept[-1] > 1e-9 * max(1.0, hz):
            kept.append(hz)
    return kept


def trapezoid(freqs: Sequence[float]) -> list[float]:
    """사다리꼴 무게 — Σ wⱼ·yⱼ 가 ∫ y df 다."""
    if len(freqs) < 2:
        return [0.0 for _ in freqs]
    weights = [0.0] * len(freqs)
    for at in range(len(freqs) - 1):
        half = (freqs[at + 1] - freqs[at]) / 2
        weights[at] += half
        weights[at + 1] += half
    return weights


def modal_gain(natural_hz: float, hz: float, damping_ratio: float) -> complex:
    """모드 좌표의 응답(mm 당 Γ, 1 g 가진당) — hₘ(f) = -g / (ωₘ² - Ω² + 2iζωₘΩ).

    **잔여 벡터**(`RESIDUAL`)는 주파수와 무관하게 1 이다 — 그 「모드 형상」 이 이미 1 g 당 정적
    변위다(`with_residual`)."""
    if math.isinf(natural_hz):
        return 1.0 + 0j
    wn = 2 * math.pi * natural_hz
    w = 2 * math.pi * hz
    return -G_MM_S2 / complex(wn * wn - w * w, 2 * damping_ratio * wn * w)


@dataclass(frozen=True)
class Modes:
    """모드 중첩의 재료 — 고유진동수(Hz) · 가진마다 모드 참여 Γ(가진 방향으로 모은 것)."""

    naturals: tuple[float, ...]
    participation: dict[str, tuple[float, ...]]
    """가진 이름 → 모드마다 Γ = Σᵢ dᵢ·Γₘ,ᵢ."""


def gather(
    naturals: Sequence[float],
    factors: Mapping[int, Sequence[float]],
    shakes: Sequence[Shake],
) -> Modes:
    """`.dat` 의 참여계수(모드 → X · Y · Z · …)를 가진 방향으로 모은다. 없는 모드는 0."""
    out: dict[str, tuple[float, ...]] = {}
    for shake in shakes:
        row = []
        for number in range(1, len(naturals) + 1):
            values = list(factors.get(number) or [0.0, 0.0, 0.0])[:3]
            row.append(sum(shake.direction[axis] * values[axis] for axis in range(3)))
        out[shake.name] = tuple(row)
    return Modes(naturals=tuple(naturals), participation=out)


#: 잔여 벡터의 「고유진동수」 — 모드 중첩에 주파수와 무관한 모드로 끼운다(`modal_gain`).
RESIDUAL = math.inf


def with_residual(
    modes: Modes,
    shapes: Sequence[Mapping[int, Sequence[float]]],
    statics: Sequence[Mapping[int, Sequence[float]]],
    shakes: Sequence[Shake],
) -> tuple[Modes, list[Mapping[int, Sequence[float]]]]:
    """**빠진 모드의 정적 몫**(잔여 벡터)을 가진마다 「모드」 하나로 더한다.

    가진 s 를 1 g 로 걸었을 때의 정적 변위 uₛ(덱의 정적 단계) 에서 모드들이 이미 낸 정적 몫
    Σₘ φₘ Γₘ,ₛ hₘ(0) 을 뺀 것 Rₛ 가 그 형상이다. 고유진동수가 가진 대역보다 훨씬 높은
    부품(준정적)은 모드 수가 모자라면 응답이 모드 수에 따라 출렁인다(시험_랜덤진동: 모드 10 ·
    40 · 100 개에 +20 · -13 · +6 %). Rₛ 를 더하면 낮은 주파수 끝에서 정적 해와 같아진다(Ansys
    의 잔여 벡터와 같은 길). 0 Hz 모드는 hₘ(0) 이 없어 빼지 않는다."""
    naturals = list(modes.naturals)
    participation = {name: list(values) for name, values in modes.participation.items()}
    out: list[Mapping[int, Sequence[float]]] = list(shapes)
    for shake, static in zip(shakes, statics, strict=True):
        gamma = modes.participation[shake.name]
        gains = [
            gamma[m] * modal_gain(natural, 0.0, 0.0).real
            if natural > 0 and not math.isinf(natural)
            else 0.0
            for m, natural in enumerate(modes.naturals)
        ]
        used = [m for m, gain in enumerate(gains) if gain != 0.0]
        residual: dict[int, list[float]] = {}
        for node, moved in static.items():
            vector = [float(one) for one in list(moved)[:3]]
            for m in used:
                phi = shapes[m].get(node)
                if phi is None:
                    continue
                for axis in range(3):
                    vector[axis] -= phi[axis] * gains[m]
            residual[node] = vector
        out.append(residual)
        naturals.append(RESIDUAL)
        for name, values in participation.items():
            values.append(1.0 if name == shake.name else 0.0)
    return (
        Modes(
            naturals=tuple(naturals),
            participation={name: tuple(values) for name, values in participation.items()},
        ),
        out,
    )


@dataclass(frozen=True)
class Response:
    """한 자리의 랜덤 응답 — 1σ 가속도(g, 절대) · 1σ 변위(mm, 지지부 기준) · 응답 PSD 곡선."""

    accel_grms: float
    accel_axes: tuple[float, float, float]
    displacement_mm: float
    psd: list[float]
    """격자 점마다 절대 가속도 응답 PSD(g²/Hz) — 세 축의 합, 가진들의 합."""


def transfer(
    shapes: Sequence[Sequence[float]],
    gamma: Sequence[float],
    naturals: Sequence[float],
    direction: Sequence[float],
    hz: float,
    damping_ratio: float,
) -> tuple[list[complex], list[complex]]:
    """한 자리 · 한 주파수의 **1 g 가진당 응답** — (상대 변위 mm, 절대 가속도 g) 세 축(복소).

    `shapes` 는 모드마다 그 절점의 φ(x, y, z), `gamma` 는 모드마다 가진 방향 참여다. 기저를
    1 g 로 흔든 조화 응답과 같은 값이다(`tests/opensolver` 가 견준다)."""
    u = [0j, 0j, 0j]
    for number, natural in enumerate(naturals):
        if gamma[number] == 0:
            continue
        gain = gamma[number] * modal_gain(natural, hz, damping_ratio)
        phi = shapes[number]
        for axis in range(3):
            u[axis] += phi[axis] * gain
    omega2 = (2 * math.pi * hz) ** 2
    return u, [-omega2 * u[axis] / G_MM_S2 + direction[axis] for axis in range(3)]


def at_point(
    shapes: Sequence[Sequence[float]],
    modes: Modes,
    shakes: Sequence[Shake],
    freqs: Sequence[float],
    damping_ratio: float,
) -> Response:
    """측정점 하나 — `shapes` 는 모드마다 그 절점의 φ(x, y, z)."""
    weights = trapezoid(freqs)
    psd_out = [0.0] * len(freqs)
    axes = [0.0, 0.0, 0.0]
    moved = 0.0
    for shake in shakes:
        gamma = modes.participation[shake.name]
        for at, hz in enumerate(freqs):
            level = psd_at(shake.table, hz)
            if level <= 0:
                continue
            u, accel = transfer(
                shapes, gamma, modes.naturals, shake.direction, hz, damping_ratio
            )
            for axis in range(3):
                power = abs(accel[axis]) ** 2 * level
                psd_out[at] += power
                axes[axis] += weights[at] * power
                moved += weights[at] * abs(u[axis]) ** 2 * level
    total = sum(weights[at] * psd_out[at] for at in range(len(freqs)))
    return Response(
        accel_grms=math.sqrt(max(total, 0.0)),
        accel_axes=(math.sqrt(axes[0]), math.sqrt(axes[1]), math.sqrt(axes[2])),
        displacement_mm=math.sqrt(max(moved, 0.0)),
        psd=psd_out,
    )


def couplings(
    modes: Modes, shakes: Sequence[Shake], freqs: Sequence[float], damping_ratio: float
) -> list[list[float]]:
    """**모드 사이의 결합 행렬** Rₘₖ = Σ_가진 Γₘ Γₖ ∫ Re(hₘ h̄ₖ) S df — 절점마다 1σ² = Σₐₓᵢₛ
    φᵀ R φ 다. 대칭 · 양의 준정부호."""
    count = len(modes.naturals)
    weights = trapezoid(freqs)
    matrix = [[0.0] * count for _ in range(count)]
    for shake in shakes:
        gamma = modes.participation[shake.name]
        for at, hz in enumerate(freqs):
            level = psd_at(shake.table, hz) * weights[at]
            if level <= 0:
                continue
            gains = [
                gamma[m] * modal_gain(natural, hz, damping_ratio)
                for m, natural in enumerate(modes.naturals)
            ]
            for m in range(count):
                if gains[m] == 0:
                    continue
                row = matrix[m]
                for k in range(m, count):
                    row[k] += level * (gains[m] * gains[k].conjugate()).real
    for m in range(count):
        for k in range(m):
            matrix[m][k] = matrix[k][m]
    return matrix


def field(
    shapes: Sequence[Mapping[int, Sequence[float]]],
    matrix: Sequence[Sequence[float]],
    nodes: Iterable[int],
) -> dict[int, float]:
    """절점마다 **1σ 변위(mm, 지지부 기준)** — 크기 √(σx² + σy² + σz²).

    응답에 거의 안 보태는 모드는 뺀다(몫이 가장 큰 것의 10⁻¹⁰ 아래) — 가진 방향과 직각인
    모드들이다. **몫은 대각값 x 형상의 크기²** 로 본다 — 모드 형상은 질량 정규화 값이고 잔여
    벡터는 mm 라, 대각값만 견주면 잔여 벡터 곁에서 진짜 모드가 다 빠진다(실측 2026-11-17,
    시험_랜덤진동). 남은 모드 K 개로 절점마다 K² 번 곱한다."""
    sizes = [
        max((sum(c * c for c in list(v)[:3]) for v in one.values()), default=0.0)
        for one in shapes
    ]
    diagonal = [matrix[m][m] * sizes[m] for m in range(len(matrix))]
    top = max(diagonal, default=0.0)
    kept = [m for m, value in enumerate(diagonal) if top > 0 and value > 1e-10 * top]
    rows = [[matrix[m][k] for k in kept] for m in kept]
    picked = [shapes[m] for m in kept]
    out: dict[int, float] = {}
    for node in nodes:
        total = 0.0
        vectors = [one.get(node) for one in picked]
        if any(one is None for one in vectors):
            continue
        for axis in range(3):
            values = [one[axis] for one in vectors]  # type: ignore[index]
            total += sum(
                value * sum(r * v for r, v in zip(row, values, strict=True))
                for value, row in zip(values, rows, strict=True)
            )
        out[node] = math.sqrt(max(total, 0.0))
    return out
