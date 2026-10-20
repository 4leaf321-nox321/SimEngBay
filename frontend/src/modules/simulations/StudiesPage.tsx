/**
 * DOE 목록 — 가져온 설계점 묶음들. 내가 가져온 것과 **게시된 것**이 보인다(작업은 건 사람의
 * 것이다, 2026-10-20).
 *
 * **스터디를 따로 저장하지 않는다.** 작업 표에서 모은다(서버) — 따로 두면 작업을 지웠을 때
 * 둘이 어긋나고, 그때 어느 쪽이 맞는지 알 방법이 없다.
 */

import { Link, useSearchParams } from 'react-router-dom'

import { simulationApi } from '@/modules/simulations/api'
import { RECIPE_LABELS, SOLVER_LABELS } from '@/modules/simulations/labels'
import { PublishedBadge } from '@/modules/simulations/Publishing'
import { scopeTitle, workScope } from '@/modules/simulations/SimulationsLayout'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { PageHeader } from '@/shared/components/PageHeader'
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

export default function StudiesPage() {
  // 어느 작업공간인지는 두 번째 사이드바가 고른다(주소의 `?scope=`).
  const [params] = useSearchParams()
  const scope = workScope(params)
  const studies = useResource(() => simulationApi.studies(scope), [scope])

  return (
    <div className="space-y-6">
      <PageHeader
        title={scopeTitle(scope, 'DOE 비교')}
        description={
          (scope === 'published'
            ? '게시된 설계점 묶음과 그 결과입니다. 누구나 읽을 수 있습니다.'
            : scope === 'all'
              ? '모든 사람이 가져온 설계점 묶음입니다(시스템 관리자).'
              : '내가 가져온 설계점 묶음과 그 결과입니다. 게시하면 공용 작업공간에 표시됩니다.') +
          ' 결과는 이 플랫폼이 들고 있습니다 — CAD 로 돌려보내지 않습니다.'
        }
      />

      <ErrorNotice error={studies.error} />

      {studies.data && studies.data.length === 0 ? (
        <EmptyState
          title={scope === 'published' ? '게시된 DOE 가 없습니다' : '가져온 DOE 가 없습니다'}
          hint={
            scope === 'published'
              ? 'DOE 화면에서 「게시」 하면 여기에 표시되고, 누구나 읽을 수 있습니다.'
              : '해석 작업 화면의 「새 해석 작업」 에서 CAD 가 내보낸 DOE 폴더를 선택해 가져옵니다.'
          }
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>이름</TableHead>
              <TableHead>해석 종류</TableHead>
              <TableHead>솔버</TableHead>
              <TableHead>변수</TableHead>
              <TableHead>설계점</TableHead>
              <TableHead>진행</TableHead>
              <TableHead>가져온 사람</TableHead>
              <TableHead>부서</TableHead>
              <TableHead>가져온 때</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(studies.data ?? []).map((one) => (
              <TableRow key={one.study_id}>
                <TableCell>
                  <Link
                    to={`/simulations/studies/${one.study_id}`}
                    className="font-medium hover:underline"
                  >
                    {one.name}
                  </Link>
                  {(one.published ?? 0) > 0 && (
                    <span className="text-muted-foreground ml-2 text-xs">
                      <PublishedBadge /> {one.published}/{one.points}
                    </span>
                  )}
                </TableCell>
                <TableCell>{RECIPE_LABELS[one.recipe] ?? one.recipe}</TableCell>
                <TableCell>
                  {(one.solvers ?? []).map((solver) => SOLVER_LABELS[solver] ?? solver).join(' + ') ||
                    '—'}
                </TableCell>
                <TableCell className="font-mono text-xs">{one.factors.join(' · ')}</TableCell>
                <TableCell>{one.points}</TableCell>
                <TableCell className="text-sm">
                  완료 {one.done}
                  {one.running > 0 && ` · 진행 ${one.running}`}
                  {one.failed > 0 && (
                    <span className="text-destructive"> · 실패 {one.failed}</span>
                  )}
                </TableCell>
                <TableCell>{one.owner_name ?? '—'}</TableCell>
                <TableCell>{one.workspace_name ?? '전역'}</TableCell>
                <TableCell className="whitespace-nowrap">
                  {shownDateTime(one.created_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
