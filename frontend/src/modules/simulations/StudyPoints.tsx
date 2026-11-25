/**
 * DOE 의 설계점 표 — 웹 화면의 「설계점」 탭과 대화 안 결과 화면(패널)이 함께 쓴다.
 */

import { Link } from 'react-router-dom'

import type { StudyPoint } from '@/modules/simulations/api'
import { SOLVE_ON_LABELS, SOLVER_LABELS } from '@/modules/simulations/labels'
import { PublishedBadge } from '@/modules/simulations/Publishing'
import { EmptyState } from '@/shared/components/EmptyState'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/table'

/**
 * 설계점마다 **상태 · 오류 · 솔버 · 게시** — 작업 화면의 「진행」 에 해당한다. 결과 값은 비교
 * 탭의 행렬에 있다(여기는 「어느 점이 왜 안 끝났나」 를 보는 자리).
 */
export function StudyPoints({
  points,
  factors,
  linked = true,
}: {
  points: StudyPoint[]
  factors: string[]
  /** 점 번호를 작업 화면으로 잇는다 — 대화 안 화면(패널)에서는 잇지 않는다. */
  linked?: boolean
}) {
  if (points.length === 0) {
    return <EmptyState title="설계점이 없습니다" hint="가져온 점이 여기에 표시됩니다." />
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>점</TableHead>
          {factors.map((one) => (
            <TableHead key={one}>{one}</TableHead>
          ))}
          <TableHead>상태</TableHead>
          <TableHead>오류</TableHead>
          <TableHead>솔버</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {points.map((point) => (
          <TableRow key={point.simulation_id}>
            <TableCell>
              {linked ? (
                <Link to={`/simulations/${point.simulation_id}`} className="font-mono hover:underline">
                  p{String(point.number).padStart(4, '0')}
                </Link>
              ) : (
                <span className="font-mono">p{String(point.number).padStart(4, '0')}</span>
              )}
              {point.published && <PublishedBadge className="ml-1" />}
            </TableCell>
            {factors.map((one) => (
              <TableCell key={one} className="font-mono">
                {point.params[one] ?? '—'}
              </TableCell>
            ))}
            <TableCell>
              <StatusBadge kind="simulation" value={point.status} />
            </TableCell>
            <TableCell className="text-destructive font-mono text-xs">{point.error_code ?? ''}</TableCell>
            <TableCell>
              {SOLVER_LABELS[point.solver] ?? point.solver}
              {point.solve_on === 'ste' && ` · ${SOLVE_ON_LABELS.ste}`}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
