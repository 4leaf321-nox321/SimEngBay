/**
 * DOE 한 벌을 **한 장으로** — 모드를 하나씩 눌러 봐야 아는 화면은 「전반적으로 어떤가」 에
 * 답하지 못한다.
 *
 * 순서가 곧 사람이 묻는 순서다:
 *
 *   1. 한 줄 요약   — 변수를 이만큼 움직였더니 1차와 질량이 이만큼 변했다
 *   2. 모드 지도    — 모드 전부를 한 그림에. 어느 것이 빨리 오르고 어디서 엇갈리나
 *   3. 트레이드오프 — 질량 대 주파수. **파레토**(더 나은 것이 없는 점)를 짚어 준다
 *   4. 행렬        — 모드 x 설계점 숫자표. 눈으로 훑고 값을 집어 가는 자리
 *
 * **모드는 형상으로 이어져 있다**(`core/modes` 의 MAC). 순번으로 이으면 치수가 바뀌는 순간
 * 다른 모드를 잇는다 — 실측으로 2차와 4차가 자리를 바꿨다.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import type { ModeTrack, Study, StudyPoint } from '@/modules/simulations/api'
import { Spectrum } from '@/shared/charts'
import type { SpectrumLine, SpectrumPoint } from '@/shared/charts'
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
import { cn } from '@/shared/lib/utils'

/** 한 그림에 그릴 모드 수. 여섯을 넘으면 선이 서로를 가린다. */
const MAX_LINES = 6

/** 추적된 모드가 그 설계점에서 몇 Hz인가. 못 이었으면 없다. */
function frequency(point: StudyPoint, track: ModeTrack): number | null {
  const number = track.numbers[point.number]
  if (number == null) return null
  return point.frequencies?.[number - 1] ?? null
}

function change(first: number | null, last: number | null): string {
  if (first == null || last == null || first === 0) return '—'
  const ratio = ((last - first) / first) * 100
  return `${ratio >= 0 ? '+' : ''}${ratio.toFixed(0)}%`
}

/**
 * 파레토 — **더 나은 것이 없는 점들.**
 *
 * 주파수는 높을수록, 질량은 낮을수록 좋다. 어떤 점보다 주파수도 낮고 질량도 무거우면 그 점은
 * 고를 이유가 없다. 남는 것이 **고민할 가치가 있는 후보**다.
 */
function paretoNumbers(rows: { number: number; hz: number | null; mass: number | null }[]) {
  const usable = rows.filter(
    (one): one is { number: number; hz: number; mass: number } =>
      one.hz != null && one.mass != null,
  )
  return new Set(
    usable
      .filter(
        (one) =>
          !usable.some(
            (other) =>
              other.number !== one.number &&
              other.hz >= one.hz &&
              other.mass <= one.mass &&
              (other.hz > one.hz || other.mass < one.mass),
          ),
      )
      .map((one) => one.number),
  )
}

export function StudyOverview({ study }: { study: Study }) {
  const factors = study.factors
  const [factor, setFactor] = useState<string | null>(null)
  const x = factor ?? factors[0] ?? ''

  const points = useMemo(
    () => [...study.points].sort((first, second) => (first.params[x] ?? 0) - (second.params[x] ?? 0)),
    [study.points, x],
  )
  const done = points.filter((one) => one.status === 'done')
  const tracks = (study.tracks ?? []).slice(0, MAX_LINES)

  /** 모드 지도 — 선 하나가 **추적된 모드 하나**다. */
  const lines = useMemo<SpectrumLine[]>(
    () =>
      tracks
        .map((track, index) => ({
          key: `mode-${track.reference}`,
          label: `${track.reference}차`,
          color: colorAt(index),
          points: points
            .map((point) => {
              const hz = frequency(point, track)
              const across = point.params[x]
              return hz != null && across != null ? { x: across, y: hz } : null
            })
            .filter((one): one is { x: number; y: number } => one !== null),
        }))
        .filter((one) => one.points.length > 0),
    [tracks, points, x],
  )

  /** 트레이드오프 — 질량 대 그 모드. 파레토 점은 색이 다르다. */
  const [tradeMode, setTradeMode] = useState('1')
  const track = tracks.find((one) => String(one.reference) === tradeMode) ?? tracks[0]
  const rows = points.map((one) => ({
    number: one.number,
    hz: track ? frequency(one, track) : (one.first_elastic_hz ?? null),
    mass: one.mass_kg ?? null,
  }))
  const pareto = useMemo(() => paretoNumbers(rows), [rows])
  const tradePoints = useMemo<SpectrumPoint[]>(
    () =>
      rows
        .filter((one) => one.hz != null && one.mass != null)
        .map((one) => ({
          key: String(one.number),
          x: one.mass as number,
          y: one.hz as number,
          label: `p${String(one.number).padStart(4, '0')}`,
        })),
    [rows],
  )

  const first = done[0]
  const last = done[done.length - 1]
  const firstHz = first?.first_elastic_hz ?? null
  const lastHz = last?.first_elastic_hz ?? null

  return (
    <div className="space-y-6">
      {factors.length > 1 && (
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground text-sm">가로축</span>
          <Select value={x} onValueChange={setFactor}>
            <SelectTrigger className="h-8 w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {factors.map((one) => (
                <SelectItem key={one} value={one}>
                  {one}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* 1. 한 줄 요약 — **무엇을 얼마나 바꿨더니 무엇이 얼마나 변했나.** */}
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
            {first?.params[x] ?? '—'} → {last?.params[x] ?? '—'}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">1차 모드</dt>
          <dd className="font-medium">
            {firstHz?.toLocaleString() ?? '—'} → {lastHz?.toLocaleString() ?? '—'} Hz{' '}
            <span className="text-muted-foreground">{change(firstHz, lastHz)}</span>
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">질량</dt>
          <dd className="font-medium">
            {first?.mass_kg?.toFixed(2) ?? '—'} → {last?.mass_kg?.toFixed(2) ?? '—'} kg{' '}
            <span className="text-muted-foreground">
              {change(first?.mass_kg ?? null, last?.mass_kg ?? null)}
            </span>
          </dd>
        </div>
      </dl>

      {/* 2 · 3. 두 그림을 **나란히** — 가로로 긴 그림 하나는 축이 멀어 값을 못 읽는다.
          좁은 화면에서는 위아래로 쌓인다(그때는 폭이 곧 높이 대비 과하지 않다). */}
      <div className="grid gap-6 xl:grid-cols-2">
        <section className="space-y-2">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-sm font-medium">모드 지도</h2>
            <p className="text-muted-foreground text-xs">선 하나가 모드 하나</p>
          </div>
          <Spectrum
            lines={lines}
            stems={false}
            xLabel={x}
            yLabel="주파수 (Hz)"
            height={320}
            title="설계 변수에 따른 모드별 고유진동수"
            emptyText="아직 그릴 결과가 없습니다. 설계점이 차례로 돕니다."
          />
          <p className="text-muted-foreground text-xs">
            모드는 <b>형상으로 이어</b> 견줍니다 — 순번으로 이으면 치수가 바뀌는 순간 다른
            모드를 잇습니다.
          </p>
        </section>

        <section className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-medium">질량 대 주파수</h2>
            <Select value={tradeMode} onValueChange={setTradeMode}>
              <SelectTrigger className="h-7 w-24">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {tracks.map((one) => (
                  <SelectItem key={one.reference} value={String(one.reference)}>
                    {one.reference}차
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Spectrum
            points={tradePoints}
            stems={false}
            xLabel="질량 (kg)"
            yLabel="주파수 (Hz)"
            height={320}
            title="질량 대 주파수"
            emptyText="질량이 없는 작업입니다(옛 작업은 질량을 안 냅니다)."
          />
          <p className="text-muted-foreground text-xs">
            오른쪽 아래일수록 무겁고 무릅니다 — <b>왼쪽 위</b>가 좋고, 아래 표의 「후보」 가
            그중 고를 만한 점입니다.
          </p>
        </section>
      </div>

      {/* 4. 행렬 — 눈으로 훑고 값을 집어 가는 자리. */}
      <section className="space-y-2">
        <h2 className="text-sm font-medium">설계점 × 모드 (Hz)</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>점</TableHead>
              <TableHead>{x}</TableHead>
              <TableHead>상태</TableHead>
              {tracks.map((one) => (
                <TableHead key={one.reference}>{one.reference}차</TableHead>
              ))}
              <TableHead>질량 (kg)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {points.map((point) => (
              <TableRow
                key={point.simulation_id}
                className={cn(pareto.has(point.number) && 'bg-emerald-500/5')}
              >
                <TableCell>
                  <Link
                    to={`/simulations/${point.simulation_id}`}
                    className="font-mono hover:underline"
                  >
                    p{String(point.number).padStart(4, '0')}
                  </Link>
                  {/* **고를 가치가 있는 점을 짚어 준다** — 더 가볍고 더 단단한 점이 없다는 뜻. */}
                  {pareto.has(point.number) && (
                    <span className="ml-1 text-xs text-emerald-700 dark:text-emerald-400">
                      후보
                    </span>
                  )}
                </TableCell>
                <TableCell className="font-mono">{point.params[x] ?? '—'}</TableCell>
                <TableCell>
                  <StatusBadge kind="simulation" value={point.status} />
                </TableCell>
                {tracks.map((one) => {
                  const hz = frequency(point, one)
                  return (
                    <TableCell key={one.reference} className="font-mono">
                      {hz?.toLocaleString() ?? (
                        // 못 이은 자리는 비운다 — 숫자를 채우면 그 값이 같은 모드로 읽힌다.
                        <span className="text-muted-foreground" title="같은 모드를 못 찾았습니다">
                          —
                        </span>
                      )}
                    </TableCell>
                  )
                })}
                <TableCell className="font-mono">{point.mass_kg?.toFixed(3) ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
    </div>
  )
}
