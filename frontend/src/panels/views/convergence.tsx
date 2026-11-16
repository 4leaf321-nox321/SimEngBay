/**
 * 「메시 수렴」 화면 — `convergence_get` 의 결과 아래에 뜬다. 웹 작업 화면 「검증」 탭의 메시 수렴과 같은
 * 부품이다. 읽기만 한다 — 수렴 점검을 거는 것은 `convergence_start` · 웹에서.
 */

import { simulationApi } from '@/modules/simulations/api'
import { ConvergencePanel } from '@/modules/simulations/ConvergencePanel'
import { RECIPE_LABELS, SOLVER_LABELS, solverOf } from '@/modules/simulations/labels'
import { mountPanel, text } from '@/panels/mount'
import { Loaded, PanelTitle } from '@/panels/parts'
import { useResource } from '@/shared/hooks/useResource'

function ConvergenceView({ jobId }: { jobId: string }) {
  const simulation = useResource(() => simulationApi.get(jobId), [jobId])
  if (!simulation.data) return <Loaded resource={simulation} what="해석" />
  const sim = simulation.data
  const solver = solverOf(sim.spec)
  return (
    <div className="space-y-4">
      <PanelTitle title={`${sim.name} — 메시 수렴`} line={[RECIPE_LABELS[sim.recipe] ?? sim.recipe, SOLVER_LABELS[solver] ?? solver]} />
      <ConvergencePanel simulationId={jobId} status={sim.status} solver={solver} readOnly />
    </div>
  )
}

mountPanel({
  tool: 'convergence_get',
  title: '메시 수렴',
  pick: ({ args }) => text(args.job_id),
  render: (jobId) => <ConvergenceView jobId={jobId} />,
})
