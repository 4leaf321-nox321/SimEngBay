/**
 * 「해석 결과」 화면 — `job_result` 의 결과 아래에 뜬다. 웹 작업 화면의 한눈에 보기 · 결과 · 검증 · 조건과
 * 같은 부품이다(3D 형상은 웹에서 본다). 읽기만 한다 — 실측을 붙이거나 수렴 점검을 거는 것은 웹에서.
 */

import { useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import { ConditionList } from '@/modules/simulations/ConditionList'
import { ConvergencePanel } from '@/modules/simulations/ConvergencePanel'
import { FAILURE_LABELS, RECIPE_LABELS, SOLVER_LABELS, solverOf } from '@/modules/simulations/labels'
import { MeasurementsPanel } from '@/modules/simulations/MeasurementsPanel'
import { ResultGlance } from '@/modules/simulations/ResultGlance'
import { ResultPanel, useSimulationResult } from '@/modules/simulations/ResultPanel'
import { mountPanel, text } from '@/panels/mount'
import { Loaded, PanelTitle } from '@/panels/parts'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'
import { useResource } from '@/shared/hooks/useResource'

type Tab = 'result' | 'checks' | 'conditions'

function ResultView({ jobId }: { jobId: string }) {
  const simulation = useResource(() => simulationApi.get(jobId), [jobId])
  const loaded = useSimulationResult(jobId, simulation.data?.status ?? '', simulation.data != null)
  const [tab, setTab] = useState<Tab | null>(null)
  if (!simulation.data) return <Loaded resource={simulation} what="해석" />
  const sim = simulation.data
  const done = sim.status === 'done'
  const solver = solverOf(sim.spec)
  const shown: Tab = tab ?? (done ? 'result' : 'conditions')
  return (
    <div className="space-y-4">
      <PanelTitle
        title={sim.name}
        line={[
          <StatusBadge key="status" kind="simulation" value={sim.status} />,
          RECIPE_LABELS[sim.recipe] ?? sim.recipe,
          SOLVER_LABELS[solver] ?? solver,
        ]}
      />
      {sim.status === 'failed' && (
        <p className="text-destructive text-sm">
          실패 — {FAILURE_LABELS[sim.error_code ?? ''] ?? sim.error_code}
          {sim.error_message && ` · ${sim.error_message}`}
        </p>
      )}
      <ResultGlance
        simulation={sim}
        result={loaded.result}
        onJump={(next) => setTab(next === 'checks' ? 'checks' : next === 'progress' ? 'conditions' : 'result')}
      />
      <Tabs value={shown} onValueChange={(next) => setTab(next as Tab)}>
        <TabsList variant="line">
          <TabsTrigger value="result" disabled={!done} title={done ? undefined : '끝나면 나옵니다'}>
            결과
          </TabsTrigger>
          <TabsTrigger value="checks" disabled={!done} title={done ? undefined : '끝나면 나옵니다'}>
            검증
          </TabsTrigger>
          <TabsTrigger value="conditions">조건</TabsTrigger>
        </TabsList>
        <TabsContent value="result" className="space-y-6 pt-4">
          <ResultPanel simulationId={jobId} status={sim.status} artifacts={sim.artifacts} loaded={loaded} />
        </TabsContent>
        <TabsContent value="checks" className="space-y-8 pt-4">
          <MeasurementsPanel simulationId={jobId} status={sim.status} readOnly />
          <ConvergencePanel simulationId={jobId} status={sim.status} solver={solver} readOnly />
        </TabsContent>
        <TabsContent value="conditions" className="space-y-6 pt-4">
          <ConditionList conditions={sim.conditions} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

mountPanel({
  tool: 'job_result',
  title: '해석 결과',
  pick: ({ args }) => text(args.job_id),
  render: (jobId) => <ResultView jobId={jobId} />,
})
