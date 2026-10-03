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
 */

import { useEffect, useMemo, useState } from 'react'
import { Grid3x3 } from 'lucide-react'
import { Link } from 'react-router-dom'

import { simulationApi } from '@/modules/simulations/api'
import type { Convergence, ConvergenceMetric } from '@/modules/simulations/api'
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
const FINAL = new Set(['done', 'failed', 'canceled'])

/** 기준 크기에서 줄일 크기 둘 — ×0.7 · ×0.5(유효 숫자 둘). 차수를 재려면 고르게 줄여야 한다. */
export function suggestedSizes(base: number | null | undefined): string[] {
  if (!base || base <= 0) return ['', '']
  return [0.7, 0.5].map((ratio) => String(Number((base * ratio).toPrecision(2))))
}

function shownPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${Number(value.toPrecision(3))}%`
}

interface Props {
  simulationId: string
  status: string
  solver: string
}

export function ConvergencePanel({ simulationId, status, solver }: Props) {
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
        if (!disposed) setData(found)
      })
      .catch((caught: unknown) => {
        if (!disposed) setError(caught instanceof Error ? caught : new Error('수렴 묶음을 읽지 못했습니다.'))
      })
    return () => {
      disposed = true
    }
  }, [simulationId, done, tick])

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
              <TableHead>요소 크기</TableHead>
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
                    {level.element_size_mm == null ? '기본' : `${level.element_size_mm} mm`}
                  </Link>
                  {level.is_original && <span className="text-muted-foreground ml-1 text-xs">원래 작업</span>}
                </TableCell>
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
              <TableCell colSpan={3} className="text-muted-foreground text-xs">
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
  solver,
  onClose,
  onDone,
}: {
  simulationId: string
  base: number | null
  solver: string
  onClose: () => void
  onDone: (next: Convergence) => void
}) {
  const [sizes, setSizes] = useState<string[]>(() => suggestedSizes(base))
  const [chosen, setChosen] = useState<Solver>(solver === 'calculix' ? 'calculix' : 'ansys')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const numbers = sizes.map((one) => Number(one)).filter((one) => Number.isFinite(one) && one > 0)

  async function run() {
    setBusy(true)
    setError(null)
    try {
      onDone(await simulationApi.requestConvergence(simulationId, { sizes_mm: numbers, solver: chosen }))
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('수렴 점검을 생성하지 못했습니다.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>메시 수렴 점검</DialogTitle>
          <DialogDescription>
            같은 형상 · 조건을 요소 크기만 바꿔 다시 실행합니다 — 크기마다 작업 하나.
            {base != null ? ` 원래 작업의 전역 요소 크기는 ${base} mm 입니다.` : ' 원래 작업은 기본 크기로 실행됐습니다.'}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            {sizes.map((value, index) => (
              <div key={index} className="space-y-1.5">
                <Label htmlFor={`convergence-size-${index}`}>요소 크기 {index + 1} (mm)</Label>
                <Input
                  id={`convergence-size-${index}`}
                  type="number"
                  step="any"
                  min={0}
                  value={value}
                  onChange={(event) =>
                    setSizes((current) => current.map((one, at) => (at === index ? event.target.value : one)))
                  }
                />
              </div>
            ))}
          </div>
          <p className="text-muted-foreground text-xs">
            차수를 재려면 고르게 줄입니다(×0.7 · ×0.5). 크기를 반으로 줄이면 절점이 여덟 배가 됩니다.
          </p>
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
          <Button onClick={run} disabled={busy || numbers.length === 0}>
            {busy ? '생성 중…' : `${numbers.length + (chosen !== solver && base != null ? 1 : 0)}건 실행`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
