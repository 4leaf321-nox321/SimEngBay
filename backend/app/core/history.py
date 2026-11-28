"""하중 이력(CompCore ② — 해석-확장-설계 8장) — **두 솔버가 같은 뜻으로** 푸는 자리.

정적 케이스 하나 안의 하중 단계(`analysis.load_steps`)와 하중마다의 이력(시간별 배율
`time_table` · 적용 단계 `active_steps` · 볼트 단계 `bolt_steps`)을 **총 시각 위의 배율표**
하나로 바꾼다. CalculiX 는 그 표를 `*AMPLITUDE, TIME=TOTAL TIME` 으로, Ansys 는 하중의 Tabular
Data(시각 → 값)로 건다 — 둘 다 표 사이를 선형으로 잇는다.

## 뜻(CompCore 와 정함 2026-11-27)

- 배율이 없는 하중은 **첫 단계에서 0 → 크기로 오르고 유지**한다.
- 적용 단계는 켜지는 단계 안에서 0 → 크기, 꺼지는 단계 안에서 0 으로 선형으로 내린다 — 단계 끝
  시각마다 (켜 있으면 1, 꺼져 있으면 0)인 표다.
- 시간별 배율은 그대로(양 끝 0 · 마지막 끝 시각). 회전 속도는 **ω 에 곱한다** — ccx 의 원심력은
  ω² 이라 그쪽은 제곱한 표를 쓴다(`squared`).
- 중력은 모든 단계(첫 단계에서 오르고 유지), 볼트는 첫 단계에서 조이고 뒤로 잠근다.
- 단계 끝 시각마다 표에 점을 넣는다(선형이라 값이 같다) — 결과를 단계 끝에서 읽는다.

v1 볼트 정적(`steps: 2`)과 같은 뜻은 단계 둘 · 볼트 [load, lock] · 볼트가 아닌 하중 적용 단계
[2] · 중력은 모든 단계다.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from app.core import conditions as condition_model

#: 부단계 처음을 비웠을 때 — 비선형 단계를 열 걸음으로 시작한다(전부터의 ccx 기본 0.1).
DEFAULT_SUBSTEPS = 10
#: 원심력 배율(ω²)을 표로 옮길 때 구간마다 나누는 수 — ω 가 선형이면 ω² 는 곡선이다.
SQUARE_PIECES = 8

Table = tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class History:
    """하중 단계들 — 비면 끝 시각 1 의 한 단계."""

    steps: tuple[condition_model.LoadStep, ...]

    @property
    def ends(self) -> tuple[float, ...]:
        return tuple(one.end_time for one in self.steps)

    def scale(self, load: condition_model.Load) -> Table:
        """그 하중의 총 시각 배율표 — 단계 끝 시각마다 점이 있다."""
        if load.time_table:
            return _with_points(load.time_table, self.ends)
        if load.active_steps:
            on = set(load.active_steps)
            rows = [(0.0, 0.0)]
            rows += [
                (end, 1.0 if index in on else 0.0) for index, end in enumerate(self.ends, 1)
            ]
            return tuple(rows)
        return ((0.0, 0.0), *((end, 1.0) for end in self.ends))

    def squared(self, table: Table) -> Table:
        """ω 배율표 → ω² 배율표(원심력) — 구간마다 나눠 곡선을 따른다."""
        rows: list[tuple[float, float]] = [(table[0][0], table[0][1] ** 2)]
        for (start, low), (stop, high) in pairwise(table):
            for piece in range(1, SQUARE_PIECES + 1):
                share = piece / SQUARE_PIECES
                value = low + (high - low) * share
                rows.append((start + (stop - start) * share, value * value))
        return tuple(rows)


def of(given: condition_model.Conditions) -> History | None:
    """② 칸을 쓴 정적이면 그 이력 — 아니면 `None`(지금까지의 길 그대로, 덱이 한 글자도 안
    바뀐다)."""
    steps = given.analysis.load_steps
    timed = any(one.time_table or one.active_steps or one.bolt_steps for one in given.loads)
    if not steps and not timed:
        return None
    return History(steps or (condition_model.LoadStep(name="", end_time=1.0),))


def at(table: Table, time: float) -> float:
    """표의 그 시각 값 — 선형 보간, 양 끝 밖은 끝 값."""
    if time <= table[0][0]:
        return table[0][1]
    for (start, low), (stop, high) in pairwise(table):
        if time <= stop:
            if stop == start:
                return high
            return low + (high - low) * (time - start) / (stop - start)
    return table[-1][1]


def _with_points(table: Table, ends: tuple[float, ...]) -> Table:
    """단계 끝 시각마다 점을 넣는다(선형이라 값은 같다)."""
    times = {one[0] for one in table}
    rows = list(table) + [(end, at(table, end)) for end in ends if end not in times]
    return tuple(sorted(rows))


@dataclass(frozen=True)
class Increments:
    """한 단계의 증분 — 총 시각으로(ccx `*STATIC` 의 데이터 줄). 최소 · 최대가 `None` 이면
    솔버의 기본."""

    initial: float
    period: float
    minimum: float | None
    maximum: float | None
    #: 증분 수 상한(ccx `*STEP, INC=`) — 기본 100 이 모자랄 때만.
    count: int | None


def increments(
    step: condition_model.LoadStep, start: float, *, incremental: bool
) -> Increments:
    """그 단계를 몇 걸음으로 밟나. 선형이면 한 걸음, 비선형(소성 · 큰 변형 · 접촉)이면 부단계
    수로 — 처음 = 길이 / 처음 수, 최소 = 길이 / 최대 수, 최대 = 길이 / 최소 수. Ansys 는 같은
    수를 부단계로 받는다(`mechanical.build`)."""
    period = step.end_time - start
    if not incremental:
        return Increments(period, period, None, None, None)
    first = step.initial or DEFAULT_SUBSTEPS
    return Increments(
        initial=period / first,
        period=period,
        minimum=period / step.maximum if step.maximum else None,
        maximum=period / step.minimum if step.minimum else None,
        count=max(100, 2 * step.maximum) if step.maximum else None,
    )
