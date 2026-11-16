/**
 * 「실측 비교」 화면 — `measurements_get` 의 결과 아래에 뜬다. 작업이면 웹 작업 화면 「검증」 탭의 실측,
 * 스터디면 DOE 화면 「검증」 탭(실측에 가장 가까운 설계점)과 같은 부품이다. 읽기만 한다 — 실측을 붙이는
 * 것은 `measurement_add` · 웹에서.
 */

import { simulationApi } from '@/modules/simulations/api'
import { MeasurementsPanel } from '@/modules/simulations/MeasurementsPanel'
import { StudyMeasurements } from '@/modules/simulations/StudyMeasurements'
import { mountPanel, text } from '@/panels/mount'
import { Loaded, PanelTitle } from '@/panels/parts'
import { useResource } from '@/shared/hooks/useResource'

function JobChecks({ jobId }: { jobId: string }) {
  const simulation = useResource(() => simulationApi.get(jobId), [jobId])
  if (!simulation.data) return <Loaded resource={simulation} what="해석" />
  return (
    <div className="space-y-4">
      <PanelTitle title={`${simulation.data.name} — 실측 비교`} line={[]} />
      <MeasurementsPanel simulationId={jobId} status={simulation.data.status} readOnly />
    </div>
  )
}

function StudyChecks({ studyId }: { studyId: string }) {
  const study = useResource(() => simulationApi.study(studyId), [studyId])
  if (!study.data) return <Loaded resource={study} what="DOE" />
  return (
    <div className="space-y-4">
      <PanelTitle title={`${study.data.name} — 실측 비교`} line={[`설계점 ${study.data.points.length}개`]} />
      <StudyMeasurements studyId={studyId} factors={study.data.factors} readOnly />
    </div>
  )
}

type Target = { kind: 'job' | 'study'; id: string }

mountPanel<Target>({
  tool: 'measurements_get',
  title: '실측 비교',
  pick: ({ args }) => {
    const job = text(args.job_id)
    if (job) return { kind: 'job', id: job }
    const study = text(args.study_id)
    return study ? { kind: 'study', id: study } : null
  },
  render: (target) => (target.kind === 'job' ? <JobChecks jobId={target.id} /> : <StudyChecks studyId={target.id} />),
})
