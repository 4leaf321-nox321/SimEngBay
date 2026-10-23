"""DOE 를 **한 표로 읽고 셈한다** — 민감도 · 주효과 · 조건을 건 최적점 · 두 변수의 격자.

화면의 「다변수」 탭(`frontend/src/modules/simulations/studyTable.ts`)과 **같은 열 · 같은
셈**이다. AI(MCP)가 설계점 200개를 통째로 받아 평균 · 상관을 손으로 내면 문맥을 다 먹고, 셈은
틀리기 쉽다 — 그래서 서버가 셈해 준다(`GET /simulations/studies/{id}/analysis`).

## 열

- 설계 변수 `factor:<이름>` — 글자 값이 하나라도 있으면 범주다(좌표를 못 매긴다).
- 결과 — 모달은 **추적한 모드** `mode:<기준 차수>`(MAC 로 이은 것 — 순번이 아니다. 치수가
  바뀌면 모드 순서가 뒤바뀐다), 정적 · 조화는 견줄 값(`max_mm` · `max_mpa` ·
  `reaction:<영역>` · `probe:<이름>` …), 그리고 `mass_kg`. 값은 서버가 맞춘 단위(mm · MPa ·
  N · Hz · kg)다.
- **끝난 점만** — 실패 · 대기 점의 빈 값이 0 으로 섞이지 않게.

## 민감도

변수마다 **주효과의 폭**(수준별 평균의 최대 - 최소)을 결과 평균에 견준 %다. 다른 변수는 섞인
채로 평균한다 — 전 조합 설계가 아니면 다른 변수의 효과가 섞일 수 있고, 그래서 상관계수도 함께
낸다. 수준이 많은 변수(LHS 처럼 점마다 값이 다른 것)는 같은 수의 점으로 다섯 구간에 묶는다 —
점 하나짜리 수준 200개의 평균은 효과가 아니라 잡음이다.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.core.numbers import significant
from app.modules.simulations.schemas import (
    AnalysisColumnOut,
    ChoiceOut,
    ChosenPointOut,
    EffectLevelOut,
    EffectOut,
    FactorRankOut,
    PairGridOut,
    RangeOut,
    SensitivityOut,
    StudyAnalysisOut,
    StudyOut,
    StudyPointOut,
)

#: 모달에서 추적한 모드 몇 개까지 열로 두나 — 화면의 모드 지도와 같다.
MAX_TRACKS = 6
#: 이보다 수준이 많은 숫자 변수는 구간으로 묶는다.
MAX_LEVELS = 10
#: 묶을 때 구간 수.
BINS = 5
#: 조건을 만족하는 점 중 몇 개를 줄 세워 보이나.
RANKED = 5

Value = float | str | None


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    unit: str
    kind: Literal["factor", "result"]
    numeric: bool
    value: Callable[[StudyPointOut], Value]

    def out(self) -> AnalysisColumnOut:
        return AnalysisColumnOut(
            key=self.key,
            label=self.label,
            unit=self.unit,
            kind=self.kind,
            numeric=self.numeric,
        )


def _number(value: Value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _magnitude(vector: list[float] | None) -> float | None:
    return math.sqrt(sum(one * one for one in vector)) if vector else None


def _names(
    points: list[StudyPointOut], pick: Callable[[StudyPointOut], dict[str, object]]
) -> list[str]:
    seen: list[str] = []
    for point in points:
        for name in pick(point):
            if name not in seen:
                seen.append(name)
    return seen


Pick = Callable[[StudyPointOut], Value]


def _tracked(numbers: dict[int, int]) -> Pick:
    return lambda point: _frequency(point, numbers)


def _probe(name: str) -> Pick:
    return lambda point: point.probes_mm.get(name)


def _probe_peak(name: str) -> Pick:
    return lambda point: point.probe_peaks_hz.get(name)


def _reaction(region: str) -> Pick:
    return lambda point: _magnitude(point.reactions_n.get(region))


def _relative(pair: str) -> Pick:
    return lambda point: _magnitude(point.relative_mm.get(pair))


def _param(name: str) -> Pick:
    return lambda point: point.params.get(name)


def rows_of(study: StudyOut) -> list[StudyPointOut]:
    return [one for one in study.points if one.status == "done"]


def _frequency(point: StudyPointOut, numbers: dict[int, int]) -> float | None:
    number = numbers.get(point.number)
    if number is None or number < 1 or number > len(point.frequencies):
        return None
    return point.frequencies[number - 1]


def _results(study: StudyOut, rows: list[StudyPointOut]) -> list[Column]:
    if study.recipe == "modal":
        tracked = [
            Column(
                key=f"mode:{track.reference}",
                label=f"{track.reference}차 모드",
                unit="Hz",
                kind="result",
                numeric=True,
                value=_tracked(track.numbers),
            )
            for track in study.tracks[:MAX_TRACKS]
        ]
        # 모드를 추적하지 못한 모달(설계점 하나 · 지문이 없는 옛 작업)도 1차는 견준다.
        return tracked or [
            Column(
                "first_elastic_hz",
                "1차 고유진동수",
                "Hz",
                "result",
                True,
                lambda point: point.first_elastic_hz,
            )
        ]
    if study.recipe == "harmonic":
        made = [
            Column("peak_hz", "봉우리 주파수", "Hz", "result", True, lambda one: one.peak_hz),
            Column(
                "peak_mm",
                "봉우리 변위",
                "mm",
                "result",
                True,
                lambda one: one.peak_displacement_mm,
            ),
        ]
        for name in _names(rows, lambda one: dict(one.probes_mm)):
            made.append(
                Column(
                    f"probe:{name}",
                    f"측정점 {name} 봉우리 진폭",
                    "mm",
                    "result",
                    True,
                    _probe(name),
                )
            )
            made.append(
                Column(
                    f"probe-hz:{name}",
                    f"측정점 {name} 봉우리 주파수",
                    "Hz",
                    "result",
                    True,
                    _probe_peak(name),
                )
            )
        return made
    made = [
        Column(
            "max_mm", "최대 변형", "mm", "result", True, lambda one: one.max_displacement_mm
        ),
        Column(
            "max_mpa",
            "최대 상당응력",
            "MPa",
            "result",
            True,
            lambda one: one.max_von_mises_mpa,
        ),
    ]
    for region in _names(rows, lambda one: dict(one.reactions_n)):
        made.append(
            Column(
                f"reaction:{region}",
                f"반력 {region}",
                "N",
                "result",
                True,
                _reaction(region),
            )
        )
    for name in _names(rows, lambda one: dict(one.probes_mm)):
        made.append(
            Column(
                f"probe:{name}",
                f"측정점 {name} 변위",
                "mm",
                "result",
                True,
                _probe(name),
            )
        )
    for pair in _names(rows, lambda one: dict(one.relative_mm)):
        made.append(
            Column(
                f"relative:{pair}",
                f"상대 변위 {pair}",
                "mm",
                "result",
                True,
                _relative(pair),
            )
        )
    return made


def columns_of(study: StudyOut) -> list[Column]:
    """설계 변수 다음에 결과, 그리고 질량. **값이 하나도 없는 열은 뺀다** — 고를 수 있으면
    빈 열은 「영향 없음」 으로 읽힌다."""
    rows = rows_of(study)
    factors = [
        Column(
            key=f"factor:{name}",
            label=name,
            unit="",
            kind="factor",
            numeric=all(not isinstance(one.params.get(name), str) for one in rows),
            value=_param(name),
        )
        for name in study.factors
    ]
    results = _results(study, rows)
    # **질량 0 은 없는 값이다** — 옛 작업은 kg 을 소수 넷째 자리로 잘라 작은 부품이 0 이 됐다.
    results.append(
        Column(
            "mass_kg",
            "질량",
            "kg",
            "result",
            True,
            lambda one: one.mass_kg if one.mass_kg and one.mass_kg > 0 else None,
        )
    )
    return [
        column
        for column in [*factors, *results]
        if any(column.value(one) is not None for one in rows)
    ]


# --- 셈 ------------------------------------------------------------------------------


def pearson(pairs: list[tuple[float, float]]) -> float | None:
    """피어슨 상관계수. 짝이 셋 미만이거나 한쪽이 변하지 않으면 **None** — 0 으로 적으면
    「상관없다」 로 읽힌다."""
    if len(pairs) < 3:
        return None
    count = len(pairs)
    mx = sum(x for x, _ in pairs) / count
    my = sum(y for _, y in pairs) / count
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _levels(
    rows: list[StudyPointOut], factor: Column
) -> list[tuple[Value, list[StudyPointOut]]]:
    """변수의 수준마다 그 점들. 숫자 변수의 수준이 많으면 **같은 수의 점으로 구간**을
    묶는다."""
    groups: dict[str, tuple[Value, list[StudyPointOut]]] = {}
    for row in rows:
        level = factor.value(row)
        if level is None:
            continue
        key = str(level)
        groups.setdefault(key, (level, []))[1].append(row)
    found = list(groups.values())
    if not factor.numeric or len(found) <= MAX_LEVELS:
        return sorted(
            found,
            key=lambda one: (_number(one[0]) is None, _number(one[0]) or 0.0, str(one[0])),
        )
    ordered = sorted(
        (row for row in rows if _number(factor.value(row)) is not None),
        key=lambda row: _number(factor.value(row)) or 0.0,
    )
    binned: list[tuple[Value, list[StudyPointOut]]] = []
    for index in range(BINS):
        part = ordered[index * len(ordered) // BINS : (index + 1) * len(ordered) // BINS]
        if not part:
            continue
        low = _number(factor.value(part[0])) or 0.0
        high = _number(factor.value(part[-1])) or 0.0
        binned.append((f"{significant(low, 4):g}~{significant(high, 4):g}", part))
    return binned


def effect(rows: list[StudyPointOut], factor: Column, result: Column) -> EffectOut:
    levels: list[EffectLevelOut] = []
    for level, members in _levels(rows, factor):
        values = [
            value for one in members if (value := _number(result.value(one))) is not None
        ]
        if not values:
            continue
        levels.append(
            EffectLevelOut(
                level=level if level is not None else "",
                mean=significant(sum(values) / len(values)),
                min=min(values),
                max=max(values),
                count=len(values),
            )
        )
    every = [value for one in rows if (value := _number(result.value(one))) is not None]
    spread = (
        max(one.mean for one in levels) - min(one.mean for one in levels)
        if len(levels) > 1
        else None
    )
    middle = sum(every) / len(every) if every else 0.0
    pairs = [
        (x, y)
        for one in rows
        if (x := _number(factor.value(one))) is not None
        and (y := _number(result.value(one))) is not None
    ]
    return EffectOut(
        factor=factor.key,
        result=result.key,
        levels=levels,
        spread=significant(spread) if spread is not None else None,
        spread_pct=significant(spread / abs(middle) * 100, 4)
        if spread is not None and middle
        else None,
        correlation=(
            significant(found, 4)
            if factor.numeric and (found := pearson(pairs)) is not None
            else None
        ),
    )


@dataclass(frozen=True)
class Condition:
    column: str
    op: Literal[">=", "<=", ">", "<", "="]
    value: float | str

    def holds(self, found: Value) -> bool:
        if self.op == "=":
            number = _number(found)
            target = _number(self.value) if not isinstance(self.value, str) else None
            if number is not None and target is not None:
                return number == target
            return str(found) == str(self.value)
        number = _number(found)
        if number is None or isinstance(self.value, str):
            return False
        return {
            ">=": number >= self.value,
            "<=": number <= self.value,
            ">": number > self.value,
            "<": number < self.value,
        }[self.op]

    def __str__(self) -> str:
        return f"{self.column}{self.op}{self.value}"


_CONDITION = re.compile(r"^\s*(.+?)\s*(>=|<=|>|<|=)\s*(.+?)\s*$")


def parse_condition(text: str) -> Condition:
    """`mode:1>=300` · `max_mpa<=200` · `factor:재료=SS400` 같은 글자 한 줄 → 조건."""
    found = _CONDITION.match(text)
    if found is None:
        raise ValueError(
            f"조건을 못 읽었습니다: {text!r} — 「열>=값」 · 「열<=값」 · 「열=값」 꼴입니다."
        )
    column, op, raw = found.groups()
    try:
        value: float | str = float(raw)
    except ValueError:
        if op != "=":
            raise ValueError(
                f"「{text}」 — 크기를 견주는 조건의 값은 숫자여야 합니다."
            ) from None
        value = raw
    return Condition(column=column, op=op, value=value)  # type: ignore[arg-type]


def _chosen(row: StudyPointOut, shown: list[Column]) -> ChosenPointOut:
    return ChosenPointOut(
        number=row.number,
        simulation_id=row.simulation_id,
        params=dict(row.params),
        values={column.key: column.value(row) for column in shown},
    )


def _need(columns: dict[str, Column], key: str) -> Column:
    if key not in columns:
        raise ValueError(f"「{key}」 열이 없습니다 — 쓸 수 있는 열: {', '.join(columns)}")
    return columns[key]


def analyze(
    study: StudyOut,
    *,
    result: str | None = None,
    objective: str | None = None,
    goal: Literal["min", "max"] = "min",
    where: list[str] | None = None,
    x: str | None = None,
    y: str | None = None,
) -> StudyAnalysisOut:
    """민감도 · 주효과 · 결과마다 최소 · 최대 점, 그리고 (주면) 조건을 건 최적점과 두 변수의
    격자. 모르는 열 이름은 `ValueError` — 쓸 수 있는 열을 함께 말한다."""
    rows = rows_of(study)
    columns = columns_of(study)
    by_key = {one.key: one for one in columns}
    factors = [one for one in columns if one.kind == "factor"]
    results = [one for one in columns if one.kind == "result"]
    if result is not None:
        results = [_need(by_key, result)]

    effects = [effect(rows, factor, target) for target in results for factor in factors]
    sensitivity = [
        SensitivityOut(
            result=target.key,
            factors=sorted(
                (
                    FactorRankOut(
                        factor=one.factor,
                        spread_pct=one.spread_pct,
                        correlation=one.correlation,
                    )
                    for one in effects
                    if one.result == target.key
                ),
                key=lambda one: -(abs(one.spread_pct) if one.spread_pct is not None else -1.0),
            ),
        )
        for target in results
    ]
    ranges: list[RangeOut] = []
    for target in results:
        found = [
            (value, one) for one in rows if (value := _number(target.value(one))) is not None
        ]
        if not found:
            continue
        low = min(found, key=lambda pair: pair[0])
        high = max(found, key=lambda pair: pair[0])
        ranges.append(
            RangeOut(
                result=target.key,
                min=low[0],
                max=high[0],
                min_point=low[1].number,
                max_point=high[1].number,
            )
        )

    choice: ChoiceOut | None = None
    conditions = [parse_condition(one) for one in where or []]
    if objective is not None or conditions:
        for one in conditions:
            _need(by_key, one.column)
        aim = _need(by_key, objective) if objective is not None else None
        feasible = [
            row
            for row in rows
            if all(one.holds(by_key[one.column].value(row)) for one in conditions)
        ]
        shown = [
            by_key[key]
            for key in dict.fromkeys(
                [*(c.column for c in conditions), *([aim.key] if aim else [])]
            )
        ]
        ranked = feasible
        if aim is not None:
            scored = [row for row in feasible if _number(aim.value(row)) is not None]
            ranked = sorted(
                scored, key=lambda row: _number(aim.value(row)) or 0.0, reverse=goal == "max"
            )
        choice = ChoiceOut(
            objective=aim.key if aim else None,
            goal=goal,
            where=[str(one) for one in conditions],
            feasible=len(feasible),
            best=_chosen(ranked[0], shown) if aim is not None and ranked else None,
            ranked=[_chosen(row, shown) for row in ranked[:RANKED]],
        )

    pair: PairGridOut | None = None
    if x is not None or y is not None:
        if x is None or y is None or result is None:
            raise ValueError(
                "두 변수의 격자는 x · y(설계 변수)와 result(결과 열)를 함께 줍니다."
            )
        pair = grid(rows, _need(by_key, x), _need(by_key, y), by_key[result])

    notes: list[str] = []
    if len(rows) < 3:
        notes.append("끝난 설계점이 셋 미만이라 상관 · 민감도를 말할 수 없습니다.")
    if any(len(_levels(rows, one)) == BINS and one.numeric for one in factors):
        notes.append(
            f"수준이 {MAX_LEVELS}개를 넘는 변수는 같은 수의 점으로 {BINS}구간에 묶었습니다."
        )
    return StudyAnalysisOut(
        study_id=study.study_id,
        name=study.name,
        recipe=study.recipe,
        done=len(rows),
        total=len(study.points),
        columns=[one.out() for one in columns],
        sensitivity=sensitivity,
        effects=effects,
        ranges=ranges,
        choice=choice,
        pair=pair,
        notes=notes,
    )


def grid(rows: list[StudyPointOut], x: Column, y: Column, z: Column) -> PairGridOut:
    """두 변수의 수준마다 결과 평균 — **빈 칸은 None 으로 둔다**(메우면 없는 값을 지어낸다)."""
    cells: dict[tuple[str, str], list[float]] = {}
    xs: dict[str, Value] = {}
    ys: dict[str, Value] = {}
    for row in rows:
        a, b, c = x.value(row), y.value(row), _number(z.value(row))
        if a is None or b is None or c is None:
            continue
        xs[str(a)] = a
        ys[str(b)] = b
        cells.setdefault((str(a), str(b)), []).append(c)

    def order(found: dict[str, Value]) -> list[Value]:
        return sorted(
            found.values(),
            key=lambda one: (_number(one) is None, _number(one) or 0.0, str(one)),
        )

    across, down = order(xs), order(ys)
    table = [
        [
            significant(sum(values) / len(values))
            if (values := cells.get((str(a), str(b))))
            else None
            for a in across
        ]
        for b in down
    ]
    return PairGridOut(
        x=x.key,
        y=y.key,
        result=z.key,
        xs=[one if one is not None else "" for one in across],
        ys=[one if one is not None else "" for one in down],
        z=table,
        complete=all(cell is not None for line in table for cell in line),
    )
