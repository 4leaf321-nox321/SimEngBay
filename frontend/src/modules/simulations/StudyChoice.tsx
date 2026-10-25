/**
 * **최적점 찾기** — 조건을 만족한 설계점 중에서 목표가 가장 좋은 점(2026-10-25).
 *
 * 전에는 「후보」 가 하나의 규칙뿐이었다 — 모달에서 「주파수는 높을수록 · 질량은 낮을수록」 의
 * 파레토. 변위 · 응력 · 다른 모드는 보지 않았고, 「1차 ≥ 300 Hz」 같은 조건도, 주파수를 낮추고 싶은
 * 경우(가진 대역 피하기)도 담지 못했다. 이제 사람이 고른다:
 *
 *   - **목표 하나** — 그 결과를 작게 · 크게. 맨 앞이 「최적」, 다섯까지 줄 세운다.
 *   - **목표 둘** — 무게와 강성처럼 서로 맞바꾸는 두 값은 「가장 좋은 하나」 가 없다. 두 목표
 *     모두에서 더 나은 점이 없는 점들(파레토)을 「후보」 로 짚고, 그 사이는 사람이 고른다.
 *   - **조건** — 「1차 모드 ≥ 300」 · 「최대 상당응력 ≤ 200」 · 「재료 = SS400」. 만족한 점만 본다.
 *
 * 처음 모양은 예전 「후보」 와 같다(모달: 1차 크게 + 질량 작게). 셈은 서버 `analysis.analyze` 의
 * `choice` 와 같은 규칙이고(`studyTable.chooseFrom`), 화면이 가진 표로 하므로 고치는 즉시 바뀐다 —
 * 값은 화면에 보이는 단위(질량이면 g)로 적는다.
 */

import { useMemo, useState } from 'react'
import { Plus, X } from 'lucide-react'
import { Link } from 'react-router-dom'

import type { Study } from '@/modules/simulations/api'
import {
  caseName,
  chooseFrom,
  columnsOf,
  labelOf,
  rowsOf,
} from '@/modules/simulations/studyTable'
import type { Choice, Column, Condition, Goal, Objective, Op } from '@/modules/simulations/studyTable'
import { shownNumber } from '@/shared/charts'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'

/** 목표 하나일 때 줄 세울 점 수 — 서버와 같다. */
const RANKED = 5
/** 후보(파레토)를 몇 개까지 적나 — 넘는 것은 「외 n」. */
const FRONT = 10

const SELECT =
  'border-input bg-background text-foreground h-8 rounded-md border px-2 text-xs disabled:opacity-50'

export interface ChoiceState {
  objectives: Objective[]
  where: Condition[]
}

/** 처음 모양 — **예전 「후보」 와 같은 물음**에서 시작한다(사람이 익숙한 것부터). */
export function defaultChoice(recipe: string, columns: Column[]): ChoiceState {
  const results = columns.filter((one) => one.kind === 'result' && one.numeric)
  const has = (key: string) => results.some((one) => one.key === key)
  const lead: Objective | null =
    recipe === 'modal'
      ? results[0] && results[0].key !== 'mass_kg'
        ? { column: results[0].key, goal: 'max' }
        : null
      : has(recipe === 'harmonic' ? 'peak_mm' : 'max_mm')
        ? { column: recipe === 'harmonic' ? 'peak_mm' : 'max_mm', goal: 'min' }
        : results[0]
          ? { column: results[0].key, goal: 'min' }
          : null
  const objectives = lead ? [lead] : []
  if (has('mass_kg') && lead?.column !== 'mass_kg') objectives.push({ column: 'mass_kg', goal: 'min' })
  return { objectives, where: [] }
}

export interface ChoiceModel {
  columns: Column[]
  rows: ReturnType<typeof rowsOf>
  state: ChoiceState
  setState: (next: ChoiceState) => void
  outcome: Choice
}

/** 패널과 표가 **같은 답**을 본다 — 표의 「최적」 · 「후보」 가 패널의 결과다. */
export function useChoice(study: Study): ChoiceModel {
  const rows = useMemo(() => rowsOf(study), [study])
  const columns = useMemo(() => columnsOf(study), [study])
  const initial = useMemo(() => defaultChoice(study.recipe, columns), [study.recipe, columns])
  const [chosen, setState] = useState<ChoiceState | null>(null)
  const state = chosen ?? initial
  const outcome = useMemo(
    () => chooseFrom(rows, columns, state.objectives, state.where),
    [rows, columns, state],
  )
  return { columns, rows, state, setState, outcome }
}

function valueOf(column: Column | undefined, row: ChoiceModel['rows'][number]): string {
  const value = column?.value(row)
  if (value == null) return '—'
  return typeof value === 'number' ? shownNumber(value) : String(value)
}

export function ChoicePanel({ model }: { model: ChoiceModel }) {
  const { columns, rows, state, setState, outcome } = model
  const results = columns.filter((one) => one.kind === 'result' && one.numeric)
  const byKey = new Map(columns.map((one) => [one.key, one]))
  const { objectives, where } = state

  function setObjective(index: number, next: Partial<Objective>) {
    setState({
      ...state,
      objectives: objectives.map((one, at) => (at === index ? { ...one, ...next } : one)),
    })
  }
  function setCondition(index: number, next: Partial<Condition>) {
    setState({ ...state, where: where.map((one, at) => (at === index ? { ...one, ...next } : one)) })
  }
  function addCondition() {
    const first = results[0] ?? columns[0]
    if (first) setState({ ...state, where: [...where, { column: first.key, op: '>=', value: '' }] })
  }

  // 표에 적을 열 — 목표, 그다음 조건(겹치면 한 번).
  const shown = [...new Set([...objectives.map((one) => one.column), ...where.map((one) => one.column)])]
    .map((key) => byKey.get(key))
    .filter((one): one is Column => one != null)
  const two = objectives.length >= 2
  const listed = two ? outcome.ranked.slice(0, FRONT) : outcome.ranked.slice(0, RANKED)

  return (
    <section className="space-y-3 rounded-md border p-4" aria-label="최적점 찾기">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">최적점 찾기</h2>
        <p className="text-muted-foreground text-xs">
          조건에 드는 점 가운데 — 목표가 하나면 가장 좋은 점, 둘이면 서로 맞바꾸는 점(파레토)
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground w-10 shrink-0 text-xs">목표</span>
        {objectives.map((one, index) => (
          <span key={index} className="flex items-center gap-1">
            {index > 0 && <span className="text-muted-foreground px-1 text-xs">그리고</span>}
            <select
              aria-label={`목표 ${index + 1}`}
              className={SELECT}
              value={one.column}
              onChange={(event) => setObjective(index, { column: event.target.value })}
            >
              {results.map((column) => (
                <option key={column.key} value={column.key}>
                  {labelOf(column)}
                </option>
              ))}
            </select>
            <select
              aria-label={`목표 ${index + 1} 방향`}
              className={SELECT}
              value={one.goal}
              onChange={(event) => setObjective(index, { goal: event.target.value as Goal })}
            >
              <option value="max">크게</option>
              <option value="min">작게</option>
            </select>
            {objectives.length > 1 && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`목표 ${index + 1} 빼기`}
                onClick={() =>
                  setState({ ...state, objectives: objectives.filter((_, at) => at !== index) })
                }
              >
                <X />
              </Button>
            )}
          </span>
        ))}
        {objectives.length < 2 && results.length > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              setState({
                ...state,
                objectives: [
                  ...objectives,
                  {
                    column: (results.find((c) => !objectives.some((o) => o.column === c.key)) ?? results[0]).key,
                    goal: 'min',
                  },
                ],
              })
            }
          >
            <Plus /> 목표
          </Button>
        )}
      </div>

      <div className="space-y-1.5 text-sm">
        {where.map((one, index) => {
          const column = byKey.get(one.column)
          const numeric = column?.numeric ?? true
          const levels = numeric
            ? []
            : [...new Set(rows.map((row) => String(column?.value(row) ?? '')))].filter(Boolean)
          return (
            <div key={index} className="flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground w-10 shrink-0 text-xs">{index === 0 ? '조건' : ''}</span>
              <select
                aria-label={`조건 ${index + 1} 열`}
                className={SELECT}
                value={one.column}
                onChange={(event) => {
                  const next = byKey.get(event.target.value)
                  // 고르는 값(재료)은 크기를 견줄 수 없다 — 「=」 만.
                  setCondition(index, {
                    column: event.target.value,
                    op: next && !next.numeric ? '=' : one.op,
                    value: '',
                  })
                }}
              >
                {columns.map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.kind === 'factor' ? '◆ ' : ''}
                    {labelOf(option)}
                  </option>
                ))}
              </select>
              <select
                aria-label={`조건 ${index + 1} 비교`}
                className={SELECT}
                value={one.op}
                disabled={!numeric}
                onChange={(event) => setCondition(index, { op: event.target.value as Op })}
              >
                <option value=">=">≥</option>
                <option value="<=">≤</option>
                <option value="=">=</option>
              </select>
              {numeric ? (
                <Input
                  aria-label={`조건 ${index + 1} 값`}
                  inputMode="decimal"
                  className="h-8 w-28 text-xs"
                  value={one.value}
                  placeholder="값"
                  onChange={(event) => setCondition(index, { value: event.target.value })}
                />
              ) : (
                <select
                  aria-label={`조건 ${index + 1} 값`}
                  className={SELECT}
                  value={one.value}
                  onChange={(event) => setCondition(index, { value: event.target.value })}
                >
                  <option value="">고르기</option>
                  {levels.map((level) => (
                    <option key={level} value={level}>
                      {level}
                    </option>
                  ))}
                </select>
              )}
              {column?.unit && <span className="text-muted-foreground text-xs">{column.unit}</span>}
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`조건 ${index + 1} 빼기`}
                onClick={() => setState({ ...state, where: where.filter((_, at) => at !== index) })}
              >
                <X />
              </Button>
            </div>
          )
        })}
        <div className="flex items-center gap-2">
          {where.length === 0 && <span className="text-muted-foreground w-10 shrink-0 text-xs">조건</span>}
          <Button variant="outline" size="sm" className={where.length ? 'ml-12' : ''} onClick={addCondition}>
            <Plus /> 조건
          </Button>
        </div>
      </div>

      <div className="space-y-2 border-t pt-3 text-sm">
        <p>
          조건을 만족한 점 <b>{outcome.feasible.length}</b> / {rows.length}
          {outcome.idle > 0 && (
            <span className="text-muted-foreground"> · 값이 빈 조건 {outcome.idle}개는 아직 걸지 않았습니다</span>
          )}
        </p>
        {outcome.feasible.length === 0 ? (
          <p className="text-muted-foreground">조건을 모두 만족한 점이 없습니다 — 조건을 늦춰 보세요.</p>
        ) : objectives.length === 0 ? null : listed.length === 0 ? (
          <p className="text-muted-foreground">목표 값이 있는 점이 없습니다.</p>
        ) : (
          <>
            <p>
              {two ? (
                <>
                  <span className="font-medium text-emerald-700 dark:text-emerald-400">후보</span>{' '}
                  {outcome.ranked.length}개 — 두 목표 모두에서 더 나은 점이 없는 점들입니다. 그 사이는
                  맞바꿈이라 사람이 고릅니다.
                </>
              ) : (
                <>
                  <span className="font-medium text-emerald-700 dark:text-emerald-400">최적</span>{' '}
                  {caseName(listed[0].number)} — 조건 안에서 「{byKey.get(objectives[0].column)?.label}」{' '}
                  {objectives[0].goal === 'max' ? '최대' : '최소'}
                </>
              )}
            </p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">{two ? '' : '순위'}</TableHead>
                  <TableHead>점</TableHead>
                  <TableHead>설계 변수</TableHead>
                  {shown.map((column) => (
                    <TableHead key={column.key} className="text-right">
                      {labelOf(column)}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {listed.map((row, index) => (
                  <TableRow key={row.simulation_id}>
                    <TableCell className="text-muted-foreground">{two ? '' : index + 1}</TableCell>
                    <TableCell>
                      <Link to={`/simulations/${row.simulation_id}`} className="font-mono hover:underline">
                        {caseName(row.number)}
                      </Link>
                    </TableCell>
                    <TableCell className="text-xs">
                      {Object.entries(row.params)
                        .map(([name, value]) => `${name} ${value}`)
                        .join(' · ')}
                    </TableCell>
                    {shown.map((column) => (
                      <TableCell key={column.key} className="text-right font-mono">
                        {valueOf(column, row)}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {outcome.ranked.length > listed.length && (
              <p className="text-muted-foreground text-xs">외 {outcome.ranked.length - listed.length}개</p>
            )}
          </>
        )}
      </div>
    </section>
  )
}

/** 표의 점 옆 표시 — 패널의 답을 그대로. */
export function ChoiceMark({ mark }: { mark: 'best' | 'pareto' | undefined }) {
  if (!mark) return null
  return (
    <span className="ml-1 text-xs text-emerald-700 dark:text-emerald-400">
      {mark === 'best' ? '최적' : '후보'}
    </span>
  )
}
