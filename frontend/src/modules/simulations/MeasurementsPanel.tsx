/**
 * **실측과 맞추기** — 센서 자리의 실측값을 이 결과와 **같은 자리에서** 견준다.
 *
 * 해석과 실측을 잇는 유일한 공통 좌표가 측정점(CAD 점 그룹 = 센서 자리)이다. 실측 표 한 장에
 * 종류 넷(공진 · FRF · 변위 · 변형률)을 담아 올리면, 서버가 **읽을 때마다** 이 결과와 견준다
 * (`backend/app/core/measured.py`) — 결과가 다시 돌면 견준 값도 따라 바뀐다.
 *
 * 무엇을 보여 주나:
 *
 * - **공진** — 센서 자리에서 움직이는 모드 중 가장 가까운 것과 짝, 차이(%), 짝이 불확실한지.
 *   모든 짝이 같은 비율로 어긋나면 영률로 설명한다(f ∝ √(E/밀도)).
 * - **FRF** — 실측과 해석 곡선을 같은 물리량으로 겹치고(해석 변위를 속도 · 가속도로 옮긴다),
 *   봉우리 위치 · 높이 · 반전력 감쇠비를 견준다. 높이 비만큼 감쇠비를 고치면 맞는다.
 * - **변위 · 변형률** — 측정점 성분마다 실측 대 해석.
 *
 * 가로축이 주파수인 그림은 수치 축(`Spectrum`)이다 — 실측과 해석의 주파수 격자가 다르다.
 */

import { useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'

import { simulationApi } from '@/modules/simulations/api'
import { MeasurementEntry } from '@/modules/simulations/MeasurementEntry'
import type { Comparison, FrfComparison, Measurement } from '@/modules/simulations/api'
import { shownValue } from '@/modules/simulations/format'
import { ApiError } from '@/shared/api/client'
import { Spectrum, colorAt } from '@/shared/charts'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { Button } from '@/shared/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'
import { shownDateTime } from '@/shared/lib/datetime'

export const KIND_LABELS: Record<string, string> = {
  frequency: '공진',
  frf: 'FRF',
  displacement: '변위',
  strain: '변형률',
}

const QUANTITY_LABELS: Record<string, string> = {
  displacement: '변위',
  velocity: '속도',
  acceleration: '가속도',
}

function shownPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(2)}%`
}

function FrequencyView({ comparison }: { comparison: NonNullable<Comparison['frequency']> }) {
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium">공진</h4>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>측정점</TableHead>
            <TableHead className="text-right">실측 (Hz)</TableHead>
            <TableHead>짝지은 모드</TableHead>
            <TableHead className="text-right">해석 (Hz)</TableHead>
            <TableHead className="text-right">차이</TableHead>
            <TableHead className="text-right">센서 자리 움직임</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {comparison.matches.map((one, index) => (
            <TableRow key={`${one.probe ?? ''}-${index}`}>
              <TableCell>{one.probe ?? '—'}</TableCell>
              <TableCell className="text-right font-mono">{shownValue(one.measured_hz)}</TableCell>
              <TableCell>
                {one.mode == null ? (
                  // **억지로 짓지 않는다** — 창 안에 센서 자리에서 움직이는 모드가 없다.
                  <span className="text-muted-foreground">짝 없음</span>
                ) : (
                  <>
                    {one.elastic_number ? `${one.elastic_number}차` : `모드 ${one.mode}`}
                    {one.ambiguous && (
                      <span className="ml-1 text-xs text-amber-700 dark:text-amber-400">
                        짝 불확실(가까운 모드가 둘)
                      </span>
                    )}
                  </>
                )}
              </TableCell>
              <TableCell className="text-right font-mono">{shownValue(one.analysis_hz)}</TableCell>
              <TableCell className="text-right font-mono">{shownPct(one.diff_pct)}</TableCell>
              <TableCell className="text-right font-mono">
                {one.visibility == null ? '—' : `${Math.round(one.visibility * 100)}%`}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-sm">{comparison.explanation}</p>
    </div>
  )
}

function FrfView({ one }: { one: FrfComparison }) {
  const lines = [
    {
      key: 'measured',
      label: '실측',
      color: colorAt(0),
      points: one.measured.map(([x, y]) => ({ x, y })),
    },
    {
      key: 'analysis',
      label: '해석',
      color: colorAt(1),
      points: one.analysis.map(([x, y]) => ({ x, y })),
    },
  ]
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium">
        FRF — {one.probe} ({QUANTITY_LABELS[one.quantity] ?? one.quantity})
      </h4>
      <Spectrum
        lines={lines}
        stems={false}
        xLabel="주파수 (Hz)"
        yLabel={`${QUANTITY_LABELS[one.quantity] ?? one.quantity} (${one.unit})`}
        height={260}
        title={`${one.probe} 실측 대 해석 FRF`}
      />
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground text-xs">봉우리 (실측 → 해석)</dt>
          <dd className="font-medium">
            {shownValue(one.measured_peak_hz)} → {shownValue(one.analysis_peak_hz, 'Hz')}{' '}
            <span className="text-muted-foreground">{shownPct(one.peak_diff_pct)}</span>
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">높이 비 (해석/실측)</dt>
          <dd className="font-medium">
            {one.amplitude_ratio == null ? '—' : `${one.amplitude_ratio.toFixed(2)}배`}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">감쇠비 (실측 반전력 · 해석)</dt>
          <dd className="font-medium">
            {percent(one.measured_damping)} · {percent(one.analysis_damping)}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">높이를 맞추는 감쇠비</dt>
          <dd className="font-medium">{percent(one.suggested_damping)}</dd>
        </div>
      </dl>
      {one.note && <p className="text-sm">{one.note}</p>}
    </div>
  )
}

function StaticView({ comparison }: { comparison: NonNullable<Comparison['static']> }) {
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium">변위 · 변형률</h4>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>측정점</TableHead>
            <TableHead>종류</TableHead>
            <TableHead>성분</TableHead>
            <TableHead className="text-right">실측</TableHead>
            <TableHead className="text-right">해석</TableHead>
            <TableHead className="text-right">차이</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {comparison.matches.map((one, index) => (
            <TableRow key={`${one.probe ?? ''}-${one.kind}-${one.component}-${index}`}>
              <TableCell>{one.probe ?? '—'}</TableCell>
              <TableCell>{KIND_LABELS[one.kind] ?? one.kind}</TableCell>
              <TableCell className="font-mono">{one.component === 'magnitude' ? '크기' : one.component}</TableCell>
              <TableCell className="text-right font-mono">{shownValue(one.measured, one.unit)}</TableCell>
              <TableCell className="text-right font-mono">
                {one.analysis == null ? (
                  <span className="text-muted-foreground" title={one.note}>
                    —
                  </span>
                ) : (
                  shownValue(one.analysis, one.unit)
                )}
              </TableCell>
              <TableCell className="text-right font-mono">{shownPct(one.diff_pct)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {comparison.matches
        .filter((one) => one.note)
        .map((one, index) => (
          <p key={index} className="text-xs text-amber-700 dark:text-amber-400">
            {one.probe}: {one.note}
          </p>
        ))}
      <p className="text-sm">{comparison.explanation}</p>
    </div>
  )
}

export function ComparisonView({ comparison }: { comparison: Comparison }) {
  return (
    <div className="space-y-4">
      {comparison.frequency && <FrequencyView comparison={comparison.frequency} />}
      {(comparison.frf ?? []).map((one) => (
        <FrfView key={one.probe} one={one} />
      ))}
      {comparison.static && <StaticView comparison={comparison.static} />}
      {(comparison.skipped ?? []).length > 0 && (
        <ul className="text-muted-foreground space-y-1 text-xs">
          {(comparison.skipped ?? []).map((one) => (
            <li key={one}>{one}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function MeasurementsPanel({
  simulationId,
  status,
  onData,
}: {
  simulationId: string
  status: string
  /** 새로 읽었다(올리거나 지운 뒤 포함) — 한눈에 보기 줄이 따라 바꾼다. 같은 함수를 줘야 한다. */
  onData?: (rows: Measurement[]) => void
}) {
  const [rows, setRows] = useState<Measurement[] | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [removing, setRemoving] = useState<Measurement | null>(null)
  const [tick, setTick] = useState(0)
  const done = status === 'done'

  useEffect(() => {
    if (!done) return
    let disposed = false
    simulationApi
      .measurements(simulationId)
      .then((found) => {
        if (disposed) return
        setRows(found)
        // 한 번 못 받은 것(5초 폴링 중 한 번 등)이 다음에 받은 표 위에 남지 않게.
        setError(null)
      })
      .catch((caught: unknown) => {
        if (!disposed) setError(caught instanceof Error ? caught : new Error('실측을 읽지 못했습니다.'))
      })
    return () => {
      disposed = true
    }
  }, [simulationId, done, tick])

  useEffect(() => {
    if (rows) onData?.(rows)
  }, [rows, onData])

  if (!done) return null

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium">실측과 맞추기</h2>
      <MeasurementEntry
        onSubmit={async (file, label) => {
          await simulationApi.addMeasurement(simulationId, file, label)
          setTick((value) => value + 1)
        }}
      />
      <ErrorNotice error={error} />
      {rows && rows.length === 0 && (
        <p className="text-muted-foreground text-sm">
          아직 붙인 실측이 없습니다 — 센서 자리의 공진 · FRF · 변위 · 변형률을 위 표에 넣고 검토하면 이 결과와 같은 자리에서
          견줍니다.
        </p>
      )}
      {(rows ?? []).map((one) => (
        <article key={one.id} className="space-y-3 rounded-md border p-4">
          <header className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <p className="font-medium">{one.label}</p>
              <p className="text-muted-foreground text-xs">
                {one.kinds.map((kind) => KIND_LABELS[kind] ?? kind).join(' · ')} · {one.rows}줄 ·{' '}
                {one.study_id ? '스터디에 붙은 실측' : '이 작업의 실측'} · {one.created_by_name ?? '—'} ·{' '}
                {shownDateTime(one.created_at)}
              </p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setRemoving(one)}>
              <Trash2 className="size-4" />
              삭제
            </Button>
          </header>
          {one.comparison ? (
            <ComparisonView comparison={one.comparison} />
          ) : (
            <p className="text-muted-foreground text-sm">이 작업의 결과 파일이 없어 견주지 못했습니다.</p>
          )}
        </article>
      ))}
      <ConfirmDialog
        open={removing !== null}
        title="실측 삭제"
        description={
          <>
            「{removing?.label}」 을 목록에서 삭제합니다. 해석 결과는 그대로 남고, 견준 값은 저장하지
            않으므로 함께 사라지는 것은 이 실측 표뿐입니다.
          </>
        }
        confirmLabel="삭제"
        destructive
        onConfirm={async () => {
          if (!removing) return
          await simulationApi.removeMeasurement(removing.id)
          setTick((value) => value + 1)
        }}
        onClose={() => setRemoving(null)}
      />
    </section>
  )
}
