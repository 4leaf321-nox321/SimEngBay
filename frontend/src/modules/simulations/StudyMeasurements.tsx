/**
 * 스터디의 **실측과 맞추기** — 실측 한 벌을 설계점마다 견주어 **가장 가까운 점**을 고른다.
 *
 * 물성 · 감쇠를 훑은 DOE 라면 이것이 곧 「차이를 변수로 설명하는」 일이다: 실측에 가장 가까운
 * 점의 값(영률 195 GPa 같은 것)이 해석과 실측의 차이를 설명하는 값이다. 점수는 차이의 절댓값
 * 평균(%) — 공진은 짝마다, FRF 는 봉우리 위치, 정적은 값마다 하나씩 센다.
 */

import { useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'

import { simulationApi } from '@/modules/simulations/api'
import type { StudyMeasurement } from '@/modules/simulations/api'
import { KIND_LABELS, MeasurementUpload } from '@/modules/simulations/MeasurementsPanel'
import { ApiError } from '@/shared/api/client'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { Button } from '@/shared/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'
import { cn } from '@/shared/lib/utils'

export function StudyMeasurements({ studyId, factors }: { studyId: string; factors: string[] }) {
  const [rows, setRows] = useState<StudyMeasurement[] | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [removing, setRemoving] = useState<StudyMeasurement | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let disposed = false
    simulationApi
      .studyMeasurements(studyId)
      .then((found) => {
        if (!disposed) setRows(found)
      })
      .catch((caught: unknown) => {
        if (!disposed) setError(caught instanceof Error ? caught : new Error('실측을 읽지 못했습니다.'))
      })
    return () => {
      disposed = true
    }
  }, [studyId, tick])

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium">실측과 맞추기</h2>
      <MeasurementUpload
        onUpload={async (file, label) => {
          await simulationApi.addStudyMeasurement(studyId, file, label)
          setTick((value) => value + 1)
        }}
      />
      <ErrorNotice error={error} />
      {rows && rows.length === 0 && (
        <p className="text-muted-foreground text-sm">
          아직 붙인 실측이 없습니다 — 올리면 설계점마다 견주어 실측에 가장 가까운 점을 고릅니다.
        </p>
      )}
      {(rows ?? []).map((one) => (
        <article key={one.id} className="space-y-3 rounded-md border p-4">
          <header className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <p className="font-medium">{one.label}</p>
              <p className="text-muted-foreground text-xs">
                {one.kinds.map((kind) => KIND_LABELS[kind] ?? kind).join(' · ')} · {one.rows}줄
              </p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setRemoving(one)}>
              <Trash2 className="size-4" />
              삭제
            </Button>
          </header>
          <p className="text-sm">{one.explanation}</p>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>점</TableHead>
                {factors.map((name) => (
                  <TableHead key={name}>{name}</TableHead>
                ))}
                <TableHead>상태</TableHead>
                <TableHead className="text-right">평균 차이</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(one.points ?? []).map((point) => (
                <TableRow
                  key={point.simulation_id}
                  className={cn(point.number === one.best_point && 'bg-emerald-500/5')}
                >
                  <TableCell>
                    <Link to={`/simulations/${point.simulation_id}`} className="font-mono hover:underline">
                      p{String(point.number).padStart(4, '0')}
                    </Link>
                    {point.number === one.best_point && (
                      <span className="ml-1 text-xs text-emerald-700 dark:text-emerald-400">가장 가까움</span>
                    )}
                  </TableCell>
                  {factors.map((name) => (
                    <TableCell key={name} className="font-mono">
                      {point.params[name] ?? '—'}
                    </TableCell>
                  ))}
                  <TableCell>
                    <StatusBadge kind="simulation" value={point.status} />
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {point.score_pct == null ? '—' : `${point.score_pct.toFixed(2)}%`}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="text-muted-foreground text-xs">
            점마다의 자세한 비교(짝지은 모드 · FRF 곡선 · 감쇠 제안)는 그 점의 작업 화면에 있습니다.
          </p>
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
