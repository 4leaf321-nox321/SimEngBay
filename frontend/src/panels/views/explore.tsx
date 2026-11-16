/**
 * 「다변수」 화면 — `study_analyze` 의 결과 아래에 뜬다. 웹 DOE 화면의 「다변수」 탭과 같은 부품이다.
 * 패널은 2D plotly 묶음이라 2변수 영향 · 주효과 · 상관을 그리고, 3D · 산점도 행렬 · 평행 좌표는 웹에서 본다.
 */

import { simulationApi } from '@/modules/simulations/api'
import { RECIPE_LABELS } from '@/modules/simulations/labels'
import { StudyExplorer } from '@/modules/simulations/StudyExplorer'
import { field, mountPanel, text } from '@/panels/mount'
import { Loaded, PanelTitle } from '@/panels/parts'
import { useResource } from '@/shared/hooks/useResource'

function ExplorePanel({ studyId }: { studyId: string }) {
  const study = useResource(() => simulationApi.study(studyId), [studyId])
  if (!study.data) return <Loaded resource={study} what="DOE" />
  const data = study.data
  const finished = data.points.filter((one) => one.status === 'done').length
  return (
    <div className="space-y-4">
      <PanelTitle
        title={`${data.name} — 다변수`}
        line={[RECIPE_LABELS[data.recipe] ?? data.recipe, `끝난 설계점 ${finished}개`, `변수 ${data.factors.join(' · ') || '없음'}`]}
      />
      <StudyExplorer study={data} />
    </div>
  )
}

mountPanel({
  tool: 'study_analyze',
  title: 'DOE 다변수',
  pick: ({ args, result }) => text(args.study_id) ?? text(field(result, 'study_id')),
  render: (studyId) => <ExplorePanel studyId={studyId} />,
})
