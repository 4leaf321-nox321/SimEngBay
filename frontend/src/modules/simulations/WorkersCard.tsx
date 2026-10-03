/**
 * 서버 화면의 「워커 · 솔버」 — **살아 있나 · 무엇을 집나 · 무엇이 깔렸나 · 누가 라이선스를 쥐었나.**
 *
 * 이 카드가 없을 때 「대기에서 안 움직인다」 는 `journalctl` 로만 알 수 있었다. 가장 조용한 사고는
 * **CalculiX 작업이 있는데 CalculiX 를 집는 워커가 없는 것**이다 — 그 작업은 영원히 대기하고,
 * 아무도 그 사실을 말해 주지 않는다. 그래서 그 경우를 맨 위에 빨갛게 적는다.
 *
 * **집는 솔버와 깔린 도구는 워커가 적은 값이다** — 워커마다 환경 파일 · 이미지가 다르다. 서버
 * 상태(`/server/status`)와 **따로 묻는다**: 그쪽이 오류여도(뒤처진 DB) 이 카드는 떠야 한다.
 */

import { useEffect } from 'react'
import { Link } from 'react-router-dom'

import { simulationApi } from '@/modules/simulations/api'
import type { WorkerRow } from '@/modules/simulations/api'
import { SOLVER_LABELS } from '@/modules/simulations/labels'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { StatusBadge } from '@/shared/components/StatusBadge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'
import { useResource } from '@/shared/hooks/useResource'
import { shownDateTime } from '@/shared/lib/datetime'

/** 신호를 다시 묻는 간격 — 워커가 15초마다 적으므로 그보다 촘촘할 이유가 없다. */
const POLL_MS = 10_000

/** 「12초 전」 · 「5분 전」 · 「3시간 전」. */
export function ago(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 60) return `${Math.round(seconds)}초 전`
  if (seconds < 3600) return `${Math.round(seconds / 60)}분 전`
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}시간 전`
  return `${Math.round(seconds / 86_400)}일 전`
}

function solversOf(row: WorkerRow): string {
  return row.solvers.length === 0
    ? '전부'
    : row.solvers.map((one) => SOLVER_LABELS[one] ?? one).join(' · ')
}

/** 워커가 기동 때 찾은 도구 — 경로가 있으면 있다, 없으면 없다, Ansys 는 확인 못 한 까닭까지. */
function Tools({ tools }: { tools: Record<string, unknown> }) {
  const ansys = (tools.ansys ?? {}) as { path?: string | null; checked?: boolean; note?: string }
  const mark = (value: unknown) => (typeof value === 'string' && value ? '있음' : '없음')
  return (
    <span className="text-xs">
      <span title={String(tools.ccx ?? '')}>ccx {mark(tools.ccx)}</span> ·{' '}
      <span title={String(tools.gmsh ?? '')}>gmsh {mark(tools.gmsh)}</span> ·{' '}
      <span title={ansys.path ?? ansys.note ?? ''}>
        Ansys {ansys.path ? '있음' : ansys.checked ? '없음' : '확인 안 함'}
      </span>
    </span>
  )
}

export function WorkersCard() {
  const overview = useResource(() => simulationApi.workers(), [])
  const { reload } = overview

  useEffect(() => {
    const timer = setInterval(reload, POLL_MS)
    return () => clearInterval(timer)
  }, [reload])

  const data = overview.data
  const stranded = (data?.queues ?? []).filter((one) => one.queued > 0 && one.workers_alive === 0)

  return (
    <section className="space-y-3">
      <h2 className="text-base font-semibold">워커 · 솔버</h2>
      <ErrorNotice error={overview.error} />

      {stranded.map((one) => (
        // **영원히 대기하는 작업** — 집을 워커가 없다는 사실을 아무도 말해 주지 않는다.
        <div
          key={one.solver}
          className="border-destructive/40 bg-destructive/5 text-destructive rounded-md border p-3 text-sm"
        >
          {SOLVER_LABELS[one.solver] ?? one.solver} 작업 {one.queued}개가 기다리지만 그 솔버를 집는 살아
          있는 워커가 없습니다. 워커를 실행하거나(<span className="font-mono">SIMULATION_SOLVERS</span>) 작업의
          솔버를 바꾸세요.
        </div>
      ))}

      {data && data.workers.length === 0 ? (
        <EmptyState
          title="신호를 적는 워커가 없습니다"
          hint="워커가 꺼져 있거나 이 버전보다 옛 워커입니다(옛 워커는 신호를 적지 않습니다). 작업을 요청 안에서 실행하는 설치(JOBS_INLINE)면 워커가 없어도 됩니다."
        />
      ) : (
        data && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>워커</TableHead>
                <TableHead>상태</TableHead>
                <TableHead>집는 솔버</TableHead>
                <TableHead>실행기</TableHead>
                <TableHead>깔린 도구</TableHead>
                <TableHead>마지막 신호</TableHead>
                <TableHead>하는 일</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.workers.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="font-mono text-xs">
                    {row.id}
                    {row.version && <span className="text-muted-foreground"> · {row.version}</span>}
                  </TableCell>
                  <TableCell>
                    <StatusBadge kind="worker" value={row.state} />
                  </TableCell>
                  <TableCell>{solversOf(row)}</TableCell>
                  <TableCell className="font-mono text-xs">{row.executor || '—'}</TableCell>
                  <TableCell>
                    <Tools tools={row.tools} />
                  </TableCell>
                  <TableCell className="text-sm" title={shownDateTime(row.last_seen_at)}>
                    {ago(row.silent_seconds)}
                  </TableCell>
                  <TableCell className="text-sm">
                    {row.job ? (
                      <Link to={`/simulations/${row.job.id}`} className="hover:underline">
                        {row.job.name}
                        <span className="text-muted-foreground"> · {row.job.status}</span>
                        {row.job.cancelling && <span className="text-amber-700"> · 취소 요청됨</span>}
                      </Link>
                    ) : (
                      '—'
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )
      )}

      {data && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <h3 className="text-sm font-medium">솔버별 줄</h3>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>솔버</TableHead>
                  <TableHead className="text-right">대기</TableHead>
                  <TableHead className="text-right">실행 중</TableHead>
                  <TableHead className="text-right">가장 오래 기다린 것</TableHead>
                  <TableHead className="text-right">집을 워커</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.queues.map((one) => (
                  <TableRow key={one.solver}>
                    <TableCell>{SOLVER_LABELS[one.solver] ?? one.solver}</TableCell>
                    <TableCell className="text-right tabular-nums">{one.queued}</TableCell>
                    <TableCell className="text-right tabular-nums">{one.running}</TableCell>
                    <TableCell className="text-right">
                      {one.oldest_queued_seconds == null ? '—' : ago(one.oldest_queued_seconds)}
                    </TableCell>
                    <TableCell
                      className={
                        one.queued > 0 && one.workers_alive === 0
                          ? 'text-destructive text-right tabular-nums'
                          : 'text-right tabular-nums'
                      }
                    >
                      {one.workers_alive}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="space-y-2">
            <h3 className="text-sm font-medium">Ansys 라이선스를 쥔 작업</h3>
            {data.license_holders.length === 0 ? (
              <p className="text-muted-foreground text-sm">지금 라이선스를 쥔 해석 작업이 없습니다.</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {data.license_holders.map((one) => (
                  <li key={one.simulation_id}>
                    <Link to={`/simulations/${one.simulation_id}`} className="font-medium hover:underline">
                      {one.name}
                    </Link>{' '}
                    <StatusBadge kind="simulation" value={one.status} />{' '}
                    <span className="text-muted-foreground font-mono text-xs">{one.worker_id ?? '—'}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-muted-foreground text-xs">
              모델링(Mechanical) · 솔버 단계의 해석 작업 기준입니다 — 사람이 따로 연 Mechanical 이나
              다른 플랫폼이 쥔 라이선스는 보이지 않습니다.
            </p>
          </div>
        </div>
      )}
    </section>
  )
}
