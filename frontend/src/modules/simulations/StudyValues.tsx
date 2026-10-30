/**
 * 정적 · 조화 DOE 를 한 장으로 — 모드 대신 **값**을 견준다.
 *
 * 묻는 것은 「변수를 이만큼 움직였더니 무엇이 얼마나 변했나」 다 — 정적이면 최대 변형 · 상당응력 ·
 * 반력 · 측정점 변위(전단 이음이면 반력과 미끄럼), 조화면 봉우리와 센서 자리의 봉우리. **가로축은
 * 설계 변수**다: 숫자면 수치 축(`Spectrum`), 재료 같은 고르는 값이면 막대 — 사이를 잇는 선은
 * 「그 중간이 있다」 는 말이고 재료에는 중간이 없다.
 *
 * ## 주파수는 점으로만 찍는다
 *
 * 조화의 봉우리 주파수를 선으로 잇지 않는다. 치수가 바뀌면 가장 크게 흔들리는 공진이 **다른
 * 모드로 옮겨 탈 수 있고**, 그것을 이은 선은 모드를 순번으로 이은 것과 같은 거짓 그림이다.
 *
 * 값은 서버가 **mm · MPa · N · Hz 로 맞춰** 보낸다(`app/core/values.py`) — 솔버마다 단위가 달라도
 * 여기서는 다시 옮기지 않는다.
 *
 * 설계 변수가 여럿이면 요약의 「끝 점 둘」 은 그 변수의 효과가 아니다 — 범위 · 그 점 · 영향 순위로
 * 적는다(`StudySummary`). 고를 점은 「최적점 찾기」 가 짚는다(`StudyChoice`, 2026-10-25).
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import type { Study, StudyPoint } from '@/modules/simulations/api'
import { magnitudeOf, shownForce, shownMass, shownValue } from '@/modules/simulations/format'
import { AxisPicker, useAxis } from '@/modules/simulations/StudyAxis'
import { ChoiceMark, ChoicePanel, useChoice } from '@/modules/simulations/StudyChoice'
import { FactorSummary } from '@/modules/simulations/StudySummary'
import { barNames, caseName, caseTicks } from '@/modules/simulations/studyTable'
import { Chart, Spectrum } from '@/shared/charts'
import type { SpectrumPoint } from '@/shared/charts'
import { colorAt } from '@/shared/charts'
import { StatusBadge } from '@/shared/components/StatusBadge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'

/** 견줄 값 하나 — 이름 · 단위 · 설계점에서 꺼내는 법. */
export interface Metric {
  key: string
  label: string
  unit: string
  pick: (point: StudyPoint) => number | null
  /** 주파수처럼 **잇지 않을** 값. 봉우리가 다른 공진으로 옮겨 탈 수 있다. */
  scatterOnly?: boolean
  force?: boolean
}

function names(points: StudyPoint[], pick: (point: StudyPoint) => Record<string, unknown> | undefined) {
  const seen: string[] = []
  for (const point of points) {
    for (const name of Object.keys(pick(point) ?? {})) if (!seen.includes(name)) seen.push(name)
  }
  return seen
}

/** 레시피별로 견줄 값들. 영역 · 측정점 이름은 스터디마다 다르므로 점들에서 모은다. */
export function metricsOf(recipe: string, points: StudyPoint[]): Metric[] {
  if (recipe === 'harmonic') {
    return [
      { key: 'peak_hz', label: '봉우리 주파수', unit: 'Hz', pick: (one) => one.peak_hz ?? null, scatterOnly: true },
      { key: 'peak_mm', label: '봉우리 변위', unit: 'mm', pick: (one) => one.peak_displacement_mm ?? null },
      ...names(points, (one) => one.probes_mm).flatMap((name): Metric[] => [
        {
          key: `probe:${name}`,
          label: `측정점 ${name} 봉우리 진폭`,
          unit: 'mm',
          pick: (one) => one.probes_mm?.[name] ?? null,
        },
        {
          key: `probe-hz:${name}`,
          label: `측정점 ${name} 봉우리 주파수`,
          unit: 'Hz',
          pick: (one) => one.probe_peaks_hz?.[name] ?? null,
          scatterOnly: true,
        },
      ]),
    ]
  }
  return [
    { key: 'max_mm', label: '최대 변형', unit: 'mm', pick: (one) => one.max_displacement_mm ?? null },
    { key: 'max_mpa', label: '최대 상당응력', unit: 'MPa', pick: (one) => one.max_von_mises_mpa ?? null },
    ...names(points, (one) => one.reactions_n).map(
      (region): Metric => ({
        key: `reaction:${region}`,
        label: `반력 ${region}`,
        unit: 'N',
        pick: (one) => {
          const vector = one.reactions_n?.[region]
          return vector ? magnitudeOf(vector) : null
        },
        force: true,
      }),
    ),
    ...names(points, (one) => one.bolts_n).map(
      (name): Metric => ({
        key: `bolt:${name}`,
        label: `볼트 ${name} 힘`,
        unit: 'N',
        pick: (one) => one.bolts_n?.[name] ?? null,
        force: true,
      }),
    ),
    ...names(points, (one) => one.probes_mm).map(
      (name): Metric => ({
        key: `probe:${name}`,
        label: `측정점 ${name} 변위`,
        unit: 'mm',
        pick: (one) => one.probes_mm?.[name] ?? null,
      }),
    ),
    ...names(points, (one) => one.relative_mm).map(
      (pair): Metric => ({
        key: `relative:${pair}`,
        label: `상대 변위 ${pair}`,
        unit: 'mm',
        pick: (one) => {
          const vector = one.relative_mm?.[pair]
          return vector ? magnitudeOf(vector) : null
        },
      }),
    ),
  ]
}

function shown(metric: Metric, value: number | null): string {
  return metric.force ? shownForce(value, metric.unit) : shownValue(value, metric.unit)
}

function change(first: number | null, last: number | null): string {
  if (first == null || last == null || first === 0) return '—'
  const ratio = ((last - first) / first) * 100
  return `${ratio >= 0 ? '+' : ''}${ratio.toFixed(0)}%`
}

export function StudyValues({ study }: { study: Study }) {
  const factors = study.factors
  // 처음 가로축은 최대 변형(조화는 봉우리 변위)을 가장 크게 움직이는 변수, 선은 나머지를 고정한
  // 단면만(`StudyAxis`).
  const axis = useAxis(study, study.recipe === 'harmonic' ? 'peak_mm' : 'max_mm')
  const x = axis.x

  const points = useMemo(() => {
    const rows = [...study.points]
    // 숫자면 값 순서, 글자면 **가져온 순서**(설계점 번호).
    return rows.sort((first, second) => {
      const a = first.params[x]
      const b = second.params[x]
      if (typeof a === 'number' && typeof b === 'number') return a - b
      return first.number - second.number
    })
  }, [study.points, x])
  const done = points.filter((one) => one.status === 'done')
  const metrics = useMemo(() => metricsOf(study.recipe, study.points), [study.recipe, study.points])
  const [chosen, setChosen] = useState<string | null>(null)
  const metric = metrics.find((one) => one.key === chosen) ?? metrics[0]

  const numeric = useMemo(
    () => points.every((one) => typeof one.params[x] !== 'string'),
    [points, x],
  )

  const plotted = useMemo<SpectrumPoint[]>(() => {
    const made: SpectrumPoint[] = []
    for (const one of done.filter(axis.shows)) {
      const value = metric?.pick(one) ?? null
      const across = one.params[x]
      if (value == null || typeof across !== 'number') continue
      made.push({ key: String(one.number), x: across, y: value, label: caseName(one.number) })
    }
    return made
  }, [done, metric, x, axis.shows])

  const bars = useMemo(() => {
    if (numeric || !metric) return []
    // 단면을 골랐으면 그 점만 — 값마다 막대 하나. 아니면 겹치는 이름에 설계점을 붙인다.
    const shown = done.filter(axis.shows)
    const names = barNames(shown, x)
    return shown.map((one) => ({ name: names.get(one.number), [metric.label]: metric.pick(one) }))
  }, [numeric, done, metric, x, axis.shows])

  // 표의 「최적」 · 「후보」 는 최적점 찾기의 답이다 — 처음 모양은 최대 변형 작게 · 질량 작게.
  const choice = useChoice(study)

  const first = done[0]
  const last = done[done.length - 1]
  const firstValue = first && metric ? metric.pick(first) : null
  const lastValue = last && metric ? metric.pick(last) : null

  if (!metric) return null

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-4">
        <AxisPicker study={study} axis={axis} />
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground text-sm">세로축</span>
          <Select value={metric.key} onValueChange={setChosen}>
            <SelectTrigger className="h-8 w-64">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {metrics.map((one) => (
                <SelectItem key={one.key} value={one.key}>
                  {one.label} ({one.unit})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* 한 줄 요약 — **무엇을 얼마나 바꿨더니 무엇이 얼마나 변했나.** 변수가 여럿이면 끝 점 둘이
          그 변수의 효과가 아니다 — 범위 · 그 점 · 영향 순위로. */}
      {factors.length > 1 ? (
        <FactorSummary study={study} primary={metric.key} />
      ) : (
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-md border p-4 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground text-xs">설계점</dt>
          <dd className="font-medium">
            {done.length} / {points.length} 완료
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">{x}</dt>
          <dd className="font-medium">
            {numeric
              ? `${first?.params[x] ?? '—'} → ${last?.params[x] ?? '—'}`
              : [...new Set(points.map((one) => String(one.params[x] ?? '—')))].join(' · ')}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">{metric.label}</dt>
          <dd className="font-medium">
            {shown(metric, firstValue)} → {shown(metric, lastValue)}{' '}
            <span className="text-muted-foreground">{change(firstValue, lastValue)}</span>
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">질량</dt>
          <dd className="font-medium">
            {shownMass(first?.mass_kg)} → {shownMass(last?.mass_kg)}{' '}
            <span className="text-muted-foreground">
              {change(first?.mass_kg ?? null, last?.mass_kg ?? null)}
            </span>
          </dd>
        </div>
      </dl>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-medium">
          {x} 대 {metric.label}
        </h2>
        {numeric ? (
          <Spectrum
            points={plotted}
            lines={
              metric.scatterOnly || plotted.length < 2 || !axis.connect
                ? []
                : [{ key: metric.key, label: metric.label, color: colorAt(0), points: plotted }]
            }
            stems={false}
            xLabel={x}
            yLabel={`${metric.label} (${metric.unit})`}
            height={320}
            title={`${x} 대 ${metric.label}`}
            emptyText="아직 그릴 결과가 없습니다. 설계점이 끝나면 여기에 표시됩니다."
            xTicks={caseTicks(done.filter(axis.shows), x)}
            // 잇지 않으면 같은 가로축 값에 점이 쌓인다 — 눈금 이름 대신 점마다 이름.
            pointLabels={!axis.connect}
          />
        ) : (
          // **잇지 않는다.** 선은 「그 중간이 있다」 는 말인데 재료에는 중간이 없다.
          <Chart
            kind="bar"
            data={bars}
            x="name"
            series={[{ key: metric.label }]}
            height={320}
            title={`값별 ${metric.label}`}
            emptyText="아직 그릴 결과가 없습니다. 설계점이 끝나면 여기에 표시됩니다."
          />
        )}
        {metric.scatterOnly && (
          <p className="text-muted-foreground text-xs">
            주파수는 <b>점으로만</b> 찍습니다 — 치수가 바뀌면 가장 크게 흔들리는 공진이 다른 모드로
            옮겨 탈 수 있어, 이은 선은 서로 다른 공진을 잇습니다.
          </p>
        )}
      </section>

      {/* 최적점 찾기 — 표의 「최적」 · 「후보」 가 이 답이다. */}
      <ChoicePanel model={choice} />

      {/* 설계점 × 값 — 눈으로 훑고 값을 집어 가는 자리. */}
      <section className="space-y-2">
        <h2 className="text-sm font-medium">설계점 × 값</h2>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>점</TableHead>
                {factors.map((one) => (
                  <TableHead key={one}>{one}</TableHead>
                ))}
                <TableHead>상태</TableHead>
                {metrics.map((one) => (
                  <TableHead key={one.key} className="text-right">
                    {one.label} ({one.unit})
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {points.map((point) => (
                <TableRow
                  key={point.simulation_id}
                  className={choice.outcome.marks.has(point.number) ? 'bg-emerald-500/5' : undefined}
                >
                  <TableCell>
                    <Link to={`/simulations/${point.simulation_id}`} className="font-mono hover:underline">
                      {caseName(point.number)}
                    </Link>
                    <ChoiceMark mark={choice.outcome.marks.get(point.number)} />
                  </TableCell>
                  {factors.map((one) => (
                    <TableCell key={one} className="font-mono">
                      {point.params[one] ?? '—'}
                    </TableCell>
                  ))}
                  <TableCell>
                    <StatusBadge kind="simulation" value={point.status} />
                  </TableCell>
                  {metrics.map((one) => (
                    <TableCell key={one.key} className="text-right font-mono">
                      {(one.force ? shownForce : shownValue)(one.pick(point))}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <p className="text-muted-foreground text-xs">
          값은 솔버와 무관하게 mm · MPa · N · Hz 로 맞춰 표시합니다. 반력과 상대 변위는 크기입니다 —
          성분은 CSV 에 있습니다.
        </p>
      </section>
    </div>
  )
}
