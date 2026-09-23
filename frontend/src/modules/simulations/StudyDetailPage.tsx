/**
 * 설계점 비교 — **이것이 DOE 를 돌린 이유다.**
 *
 * 「두께 6 · 12 · 20 중 1차 공진이 가장 높은 것」, 그리고 「그 대가로 질량이 얼마나 늘었나」.
 * CAD 플랫폼은 결과를 받지 않으므로(CompCore 0장) 고르는 일이 여기서 끝나야 한다.
 *
 * 그림은 `StudyOverview` 가 그린다 — **한 장으로 본다.** 모드를 하나씩 눌러 봐야 아는 화면은
 * 「전반적으로 어떤가」 에 답하지 못한다(실제로 그래서 다시 짰다).
 *
 * 아직 안 끝난 점은 안 끝난 대로 보인다. DOE 하나가 다 도는 데 점 수 x 1~2분이 걸리고,
 * 다 끝나야 보여 주면 그동안 아무것도 못 본다.
 */

import { useParams } from 'react-router-dom'

import { simulationApi } from '@/modules/simulations/api'
import { StudyOverview } from '@/modules/simulations/StudyOverview'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { PageHeader } from '@/shared/components/PageHeader'
import { useResource } from '@/shared/hooks/useResource'

export default function StudyDetailPage() {
  const { id = '' } = useParams()
  const study = useResource(() => simulationApi.study(id), [id])

  if (study.error) {
    return (
      <div className="space-y-6">
        <PageHeader title="DOE 비교" back={{ to: '/simulations/studies', label: 'DOE 비교' }} />
        <ErrorNotice error={study.error} />
      </div>
    )
  }
  if (!study.data) return null

  const points = study.data.points
  const tracked = study.data.tracks ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title={study.data.name}
        description={
          <>
            설계점 {points.length}개 · 변수 {study.data.factors.join(' · ') || '없음'}
            {tracked.length > 0 ? (
              <>
                {' '}
                · 모드 {tracked.length}개를 형상으로 이어 견줍니다(기준 p
                {String(study.data.reference_point ?? 0).padStart(4, '0')})
              </>
            ) : (
              // **추적이 없으면 그렇다고 말한다** — 순번으로 이은 선은 모드가 뒤바뀌는 순간
              // 서로 다른 모드를 잇는다.
              <> · 모드 지문이 없어 차수로만 견줍니다(다시 걸면 지문이 생깁니다)</>
            )}
          </>
        }
        back={{ to: '/simulations/studies', label: 'DOE 비교' }}
      />

      {points.every((one) => one.status !== 'done') ? (
        <EmptyState
          title="아직 끝난 설계점이 없습니다"
          hint="설계점이 차례로 돕니다. 한 건에 1~2분 걸리고, 끝난 것부터 여기에 나타납니다."
        />
      ) : (
        <StudyOverview study={study.data} />
      )}
    </div>
  )
}
