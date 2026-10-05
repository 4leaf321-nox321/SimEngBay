/**
 * **메시 수렴** — 같은 설계점을 요소 크기만 바꿔 풀었을 때 값이 자리를 잡았나.
 *
 * 해석 값은 메시에 기대고, 그 기댐이 얼마인지 모르면 숫자의 자릿수를 믿을 수 없다. 크기마다
 * 작업 하나를 걸고(CalculiX 워커 여럿이 동시에 푼다), 다 끝나면 값마다 판정한다 — 셋 이상이면
 * 관측 수렴 차수와 **격자 수렴 지수(GCI)** 로, 둘이면 상대 변화로(`backend/app/core/convergence.py`).
 *
 * **첨두응력의 「발산」 은 고장이 아니다.** 구속 모서리의 특이점에 있으면 메시를 줄일수록 커진다 —
 * 그 값으로 판단하지 말고 측정점 · 변형을 보라고 적는다.
 *
 * 가로축은 **절점 수**다(수치 축 — `Spectrum`). 요청한 요소 크기는 비구조 메시가 그대로 지키지
 * 않아서, 실제로 얼마나 촘촘했는지는 절점 수가 말한다.
 *
 * **비율로 묻는다(비례 정련).** 사람은 mm 가 아니라 원래 대비 비율(×0.7 · ×0.5)을 적고, 전체 크기와
 * CAD 가 크기를 적은 파트 · 면이 모두 그 비율로 줄어든다(서버가 수준마다 배율을 스펙에 적는다). 창과
 * 결과 표는 **전체와 파트 · 면별 크기를 열로** 보인다 — 전체 크기 하나만 보이면 파트 · 면이 함께
 * 줄어든다는 사실이 안 보였다(2026-10-05).
 */

import { useEffect, useMemo, useState } from 'react'
import { Grid3x3 } from 'lucide-react'
import { Link } from 'react-router-dom'

import { simulationApi } from '@/modules/simulations/api'
import type { Convergence, ConvergenceLocalSize, ConvergenceMetric } from '@/modules/simulations/api'
import { shownValue } from '@/modules/simulations/format'
import { SOLVER_LABELS } from '@/modules/simulations/labels'
import { SolverSelect } from '@/modules/simulations/SolverSelect'
import type { Solver } from '@/modules/simulations/SolverSelect'
import { ApiError } from '@/shared/api/client'
import { Spectrum, colorAt } from '@/shared/charts'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
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

/** 끝나지 않은 수준이 있으면 다시 묻는 간격. */
const POLL_MS = 5000
// 원래 대비 비율의 범위 — 서버(`ConvergenceRequest`)와 같다. 열 배 촘촘하게부터 두 배 성기게까지.
const MIN_RATIO = 0.1
const MAX_RATIO = 2
const usableRatio = (one: number) => Number.isFinite(one) && one >= MIN_RATIO && one <= MAX_RATIO
const FINAL = new Set(['done', 'failed', 'canceled'])

/** 제안하는 정련 비율 — ×0.7 · ×0.5. 차수를 재려면 고르게 줄여야 한다. */
export const SUGGESTED_RATIOS = ['0.7', '0.5']

/** 크기를 보기 좋게 — 유효 숫자 셋. */
function mm(value: number): string {
  return String(Number(value.toPrecision(3)))
}

/** 비율을 보기 좋게 — ×0.7. */
function times(value: number): string {
  return `×${Number(value.toPrecision(3))}`
}

function shownPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${Number(value.toPrecision(3))}%`
}

interface Props {
  simulationId: string
  status: string
  solver: string
  /** 새로 읽었다 — 한눈에 보기 줄이 판정을 따라 바꾼다. 같은 함수를 줘야 한다(바뀌면 다시 알린다). */
  onData?: (data: Convergence) => void
}

export function ConvergencePanel({ simulationId, status, solver, onData }: Props) {
  const [data, setData] = useState<Convergence | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [open, setOpen] = useState(false)
  const [tick, setTick] = useState(0)
  const done = status === 'done'

  useEffect(() => {
    if (!done) return
    let disposed = false
    simulationApi
      .convergence(simulationId)
      .then((found) => {
        if (disposed) return
        setData(found)
        // 한 번 못 받은 것(5초 폴링 중 한 번 등)이 다음에 받은 표 위에 남지 않게.
        setError(null)
      })
      .catch((caught: unknown) => {
        if (!disposed) setError(caught instanceof Error ? caught : new Error('수렴 묶음을 읽지 못했습니다.'))
      })
    return () => {
      disposed = true
    }
  }, [simulationId, done, tick])

  useEffect(() => {
    if (data) onData?.(data)
  }, [data, onData])

  // **수준이 도는 동안은 다시 묻는다** — 다 끝나야 판정이 선다.
  const running = (data?.levels ?? []).some((one) => !FINAL.has(one.status))
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setTick((value) => value + 1), POLL_MS)
    return () => clearInterval(timer)
  }, [running])

  if (!done) return null
  const checked = (data?.levels.length ?? 0) > 1

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium">메시 수렴</h2>
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
          <Grid3x3 className="size-4" />
          메시 수렴 점검
        </Button>
      </div>
      <ErrorNotice error={error} />
      {!checked ? (
        <p className="text-muted-foreground text-sm">
          아직 점검하지 않았습니다 — 요소 크기를 줄여 두세 번 더 풀어 보면 이 결과의 값이 메시에 얼마나
          기대는지 압니다.
        </p>
      ) : (
        data && <ConvergenceTable data={data} />
      )}
      {open && (
        <ConvergenceDialog
          simulationId={simulationId}
          base={data?.base_size_mm ?? null}
          local={data?.local_sizes ?? []}
          solver={solver}
          onClose={() => setOpen(false)}
          onDone={(next) => {
            setData(next)
            setOpen(false)
          }}
        />
      )}
    </section>
  )
}

function ConvergenceTable({ data }: { data: Convergence }) {
  const [chosen, setChosen] = useState<string | null>(null)
  const local = data.local_sizes ?? []
  const metric: ConvergenceMetric | undefined =
    data.metrics.find((one) => one.key === chosen) ?? data.metrics[0]
  const curve = useMemo(() => {
    if (!metric) return []
    return data.levels
      .map((level, index) => ({ x: level.nodes ?? 0, y: metric.values[index] }))
      .filter((one): one is { x: number; y: number } => one.x > 0 && one.y != null)
  }, [data.levels, metric])
  const lines = metric
    ? [
        { key: 'value', label: metric.label, color: colorAt(0), points: curve },
        ...(metric.extrapolated != null && curve.length > 1
          ? [
              {
                key: 'extrapolated',
                label: '외삽값(무한히 촘촘한 메시)',
                color: colorAt(2),
                points: [
                  { x: curve[0].x, y: metric.extrapolated },
                  { x: curve[curve.length - 1].x, y: metric.extrapolated },
                ],
              },
            ]
          : []),
      ]
    : []

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>비율</TableHead>
              <TableHead className="text-right">전체 (mm)</TableHead>
              {local.map((one) => (
                <TableHead key={`${one.kind}-${one.name}`} className="text-right">
                  {one.name} <span className="font-normal">{one.kind === 'part' ? '파트' : '면'}</span> (mm)
                </TableHead>
              ))}
              <TableHead className="text-right">절점</TableHead>
              <TableHead>상태</TableHead>
              {data.metrics.map((one) => (
                <TableHead key={one.key} className="text-right">
                  {one.label} ({one.unit})
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.levels.map((level, index) => (
              <TableRow key={level.simulation_id}>
                <TableCell>
                  <Link to={`/simulations/${level.simulation_id}`} className="font-mono hover:underline">
                    {level.ratio == null ? '—' : times(level.ratio)}
                  </Link>
                  {level.is_original && <span className="text-muted-foreground ml-1 text-xs">원래 작업</span>}
                </TableCell>
                <TableCell className="text-right font-mono">
                  {level.element_size_mm == null ? '기본' : mm(level.element_size_mm)}
                </TableCell>
                {local.map((one) => (
                  // 파트 · 면은 원래 크기 × 그 수준이 곱한 배율 — 옛 수준(배율 1)은 그대로 풀렸다.
                  <TableCell key={`${one.kind}-${one.name}`} className="text-right font-mono">
                    {mm(one.size_mm * level.local_scale)}
                  </TableCell>
                ))}
                <TableCell className="text-right font-mono">{level.nodes?.toLocaleString() ?? '—'}</TableCell>
                <TableCell>
                  <StatusBadge kind="simulation" value={level.status} />
                </TableCell>
                {data.metrics.map((one) => (
                  <TableCell key={one.key} className="text-right font-mono">
                    {shownValue(one.values[index])}
                  </TableCell>
                ))}
              </TableRow>
            ))}
            {/* 판정 줄 — 값마다 수렴 · 미수렴 · 발산과 그 근거(변화 · 차수 · GCI). */}
            <TableRow>
              <TableCell colSpan={4 + local.length} className="text-muted-foreground text-xs">
                판정 (변화 · 차수 · GCI)
              </TableCell>
              {data.metrics.map((one) => (
                <TableCell key={one.key} className="text-right text-xs">
                  <StatusBadge kind="convergence" value={one.status} />
                  <span className="text-muted-foreground block">
                    {shownPercent(one.change_pct)} · {one.order == null ? '—' : one.order.toFixed(2)} ·{' '}
                    {shownPercent(one.gci_pct)}
                  </span>
                </TableCell>
              ))}
            </TableRow>
          </TableBody>
        </Table>
      </div>
      {data.metrics.some((one) => one.note) && (
        <ul className="space-y-1 text-xs text-amber-700 dark:text-amber-400">
          {data.metrics
            .filter((one) => one.note)
            .map((one) => (
              <li key={one.key}>
                {one.label}: {one.note}
              </li>
            ))}
        </ul>
      )}
      {(data.notes ?? []).length > 0 && (
        <ul className="text-muted-foreground space-y-1 text-xs">
          {(data.notes ?? []).map((one) => (
            <li key={one}>{one}</li>
          ))}
        </ul>
      )}
      {metric && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground text-sm">세로축</span>
            <Select value={metric.key} onValueChange={setChosen}>
              <SelectTrigger className="h-8 w-64">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {data.metrics.map((one) => (
                  <SelectItem key={one.key} value={one.key}>
                    {one.label} ({one.unit})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Spectrum
            lines={lines}
            stems={false}
            xLabel="절점 수"
            yLabel={`${metric.label} (${metric.unit})`}
            height={260}
            title={`절점 수 대 ${metric.label}`}
            emptyText="끝난 수준이 둘 이상이어야 그립니다."
          />
          <p className="text-muted-foreground text-xs">
            판정 문턱 {metric.tolerance_pct}% — 셋 이상이면 GCI(가장 촘촘한 메시의 값이 무한히 촘촘한 메시의
            값과 얼마나 다를 수 있나), 둘이면 두 값의 상대 변화로 봅니다.
          </p>
        </div>
      )}
    </div>
  )
}

function ConvergenceDialog({
  simulationId,
  base,
  local,
  solver,
  onClose,
  onDone,
}: {
  simulationId: string
  base: number | null
  local: ConvergenceLocalSize[]
  solver: string
  onClose: () => void
  onDone: (next: Convergence) => void
}) {
  const [ratios, setRatios] = useState<string[]>(SUGGESTED_RATIOS)
  const [chosen, setChosen] = useState<Solver>(solver === 'calculix' ? 'calculix' : 'ansys')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const numbers = ratios.map((one) => Number(one)).filter(usableRatio)

  async function run() {
    setBusy(true)
    setError(null)
    try {
      onDone(await simulationApi.requestConvergence(simulationId, { ratios: numbers, solver: chosen }))
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('수렴 점검을 생성하지 못했습니다.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>메시 수렴 점검</DialogTitle>
          <DialogDescription>
            같은 형상 · 조건을 요소 크기만 바꿔 다시 실행합니다 — 비율마다 작업 하나. 전체 요소 크기와 CAD 가
            크기를 적은 파트 · 면을 <b>모두 원래 대비 같은 비율로</b> 줄입니다.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            {ratios.map((value, index) => (
              <div key={index} className="space-y-1.5">
                <Label htmlFor={`convergence-ratio-${index}`}>정련 비율 {index + 1} (원래 대비)</Label>
                <Input
                  id={`convergence-ratio-${index}`}
                  type="number"
                  step="any"
                  min={MIN_RATIO}
                  max={MAX_RATIO}
                  value={value}
                  onChange={(event) =>
                    setRatios((current) => current.map((one, at) => (at === index ? event.target.value : one)))
                  }
                />
              </div>
            ))}
          </div>
          <p className="text-muted-foreground text-xs">
            1 보다 작으면 촘촘하게 · 크면 성기게 풉니다. 차수를 재려면 고르게 줄입니다(×0.7 · ×0.5) — 크기를
            반으로 줄이면 절점이 여덟 배가 됩니다.
          </p>
          {base != null ? (
            <SizePreview base={base} ratios={ratios.map((one) => Number(one))} local={local} />
          ) : (
            <p className="text-xs text-amber-700 dark:text-amber-400">
              원래 작업의 전체 요소 크기를 모릅니다 — Ansys 기본 크기로 풀린 작업이라 비율을 곱할 기준이 없습니다.
              전체 요소 크기를 정해 다시 실행한 뒤 점검하세요.
            </p>
          )}
          <SolverSelect id="convergence-solver" value={chosen} onChange={setChosen} />
          {chosen !== solver && (
            <p className="text-xs text-amber-700 dark:text-amber-400">
              원래 작업({SOLVER_LABELS[solver] ?? solver})과 솔버가 다릅니다 — 원래 크기도 이 솔버로 다시
              실행하고, 판정은 이 솔버의 수준끼리만 합니다.
            </p>
          )}
          <ErrorNotice error={error} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            취소
          </Button>
          <Button onClick={run} disabled={busy || numbers.length === 0 || base == null}>
            {busy ? '생성 중…' : `${numbers.length + (chosen !== solver ? 1 : 0)}건 실행`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * 비율마다 **전체와 CAD 가 크기를 적은 파트 · 면이 몇 mm 가 되나** — 서버와 같은 셈(원래 × 비율).
 * 빈 칸 · 범위 밖 비율은 아직 안 적은 것이라 비워 둔다.
 */
function SizePreview({
  base,
  ratios,
  local,
}: {
  base: number
  ratios: number[]
  local: ConvergenceLocalSize[]
}) {
  const shown = ratios.map((one) => (usableRatio(one) ? one : null))
  const rows = [
    { key: 'whole', name: '전체', tag: '', size: base },
    ...local.map((one) => ({
      key: `${one.kind}-${one.name}`,
      name: one.name,
      tag: one.kind === 'part' ? '파트' : '면',
      size: one.size_mm,
    })),
  ]
  return (
    <div className="space-y-1.5">
      <p className="text-sm font-medium">요소 크기 (mm)</p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>자리</TableHead>
            <TableHead className="text-right">원래</TableHead>
            {shown.map((ratio, index) => (
              <TableHead key={index} className="text-right">
                {ratio == null ? '—' : times(ratio)}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.key}>
              <TableCell>
                {row.name} {row.tag && <span className="text-muted-foreground text-xs">{row.tag}</span>}
              </TableCell>
              <TableCell className="text-right font-mono">{mm(row.size)}</TableCell>
              {shown.map((ratio, index) => (
                <TableCell key={index} className="text-right font-mono">
                  {ratio == null ? '—' : mm(row.size * ratio)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-muted-foreground text-xs">
        {local.length > 0
          ? 'CAD 가 보낸 점 파일은 그대로 두고, 모델링이 이 비율을 곱합니다.'
          : 'CAD 가 크기를 따로 적은 파트 · 면은 없습니다 — 모두 전체 크기를 따릅니다.'}
      </p>
    </div>
  )
}
