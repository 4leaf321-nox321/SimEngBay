/**
 * DOE 목록 — 가져온 설계점 묶음들.
 *
 * **스터디를 따로 저장하지 않는다.** 작업 표에서 모은다(서버) — 따로 두면 작업을 지웠을 때
 * 둘이 어긋나고, 그때 어느 쪽이 맞는지 알 방법이 없다.
 */

import { Link } from 'react-router-dom'

import { simulationApi } from '@/modules/simulations/api'
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
  const studies = useResource(() => simulationApi.studies(), [])

  return (
    <div className="space-y-6">
      <PageHeader
        title="DOE 비교"
        description="CAD 가 내보낸 설계점 묶음과 그 결과입니다. 결과는 이 플랫폼이 들고 있습니다 — CAD 로 돌려보내지 않습니다."
      />

      <ErrorNotice error={studies.error} />

      {studies.data && studies.data.length === 0 ? (
        <EmptyState
          title="가져온 DOE 가 없습니다"
          hint="해석 작업 화면의 「DOE 가져오기」 로 CAD 가 내보낸 폴더를 읽어 옵니다."
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>이름</TableHead>
              <TableHead>변수</TableHead>
              <TableHead>설계점</TableHead>
              <TableHead>진행</TableHead>
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
