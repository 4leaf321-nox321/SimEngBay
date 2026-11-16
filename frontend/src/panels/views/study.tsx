/**
 * 「DOE 비교」 화면 — `study_get` 의 결과 아래에 뜬다. 웹 DOE 화면의 비교 · 설계점 · 검증 탭과 같은
 * 부품이다(다변수는 `study_analyze`, 주파수 요구는 `study_frequency` 의 화면이 따로 있다). 읽기만 한다.
 */

import { useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import { RECIPE_LABELS, SOLVER_LABELS } from '@/modules/simulations/labels'
import { StudyMeasurements } from '@/modules/simulations/StudyMeasurements'
import { StudyOverview } from '@/modules/simulations/StudyOverview'
import { StudyPoints } from '@/modules/simulations/StudyPoints'
import { StudyValues } from '@/modules/simulations/StudyValues'
import { field, mountPanel, text } from '@/panels/mount'
import { Loaded, PanelTitle } from '@/panels/parts'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'
import { useResource } from '@/shared/hooks/useResource'

type Tab = 'compare' | 'points' | 'checks'

function StudyPanel({ studyId }: { studyId: string }) {
  const study = useResource(() => simulationApi.study(studyId), [studyId])
  const [tab, setTab] = useState<Tab | null>(null)
  if (!study.data) return <Loaded resource={study} what="DOE" />
  const data = study.data
  const points = data.points
  const finished = points.filter((one) => one.status === 'done').length
  const comparable = finished > 0
  const shown: Tab = tab ?? (comparable ? 'compare' : 'points')
  const solvers = (data.solvers ?? []).map((one) => SOLVER_LABELS[one] ?? one).join(' + ')
  return (
    <div className="space-y-4">
      <PanelTitle
        title={data.name}
        line={[
          RECIPE_LABELS[data.recipe] ?? data.recipe,
          solvers,
          `설계점 ${points.length}개(끝남 ${finished})`,
          `변수 ${data.factors.join(' · ') || '없음'}`,
        ]}
      />
      <Tabs value={shown} onValueChange={(next) => setTab(next as Tab)}>
        <TabsList variant="line">
          <TabsTrigger value="compare" disabled={!comparable} title={comparable ? undefined : '끝난 설계점이 생기면 나옵니다'}>
            비교
          </TabsTrigger>
          <TabsTrigger value="points">
            설계점 ({finished}/{points.length})
          </TabsTrigger>
          <TabsTrigger value="checks">검증</TabsTrigger>
        </TabsList>
        <TabsContent value="compare" className="space-y-6 pt-4">
          {comparable && (data.recipe === 'modal' ? <StudyOverview study={data} /> : <StudyValues study={data} />)}
        </TabsContent>
        <TabsContent value="points" className="pt-4">
          <StudyPoints points={points} factors={data.factors} linked={false} />
        </TabsContent>
        <TabsContent value="checks" className="space-y-6 pt-4">
          <StudyMeasurements studyId={studyId} factors={data.factors} readOnly />
        </TabsContent>
      </Tabs>
    </div>
  )
}

mountPanel({
  tool: 'study_get',
  title: 'DOE 비교',
  pick: ({ args, result }) => text(args.study_id) ?? text(field(result, 'study_id')),
  render: (studyId) => <StudyPanel studyId={studyId} />,
})
