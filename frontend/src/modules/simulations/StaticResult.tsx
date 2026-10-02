/**
 * 정적 해석 결과 — **얼마나 밀리고 어디가 버거운가.**
 *
 * 모달은 「어느 주파수에서 어떻게 떠는가」 였다. 여기서 사람이 먼저 보는 것은 **최대 변형**
 * 이고, 그다음이 최대 상당응력이다. 값에 **단위를 붙여** 보여 준다 — 값만 보면 mm 와 m 가
 * 구별되지 않는다(모달에서 겪은 그대로다).
 */
import { useEffect, useState } from 'react'

import type { Artifact, StaticResult as StaticResultData } from '@/modules/simulations/api'
import { simulationApi } from '@/modules/simulations/api'
import MeshViewer from '@/shared/viewer/MeshViewer'

type Props = {
  simulationId: string
  result: StaticResultData
  artifacts: Artifact[]
}

function shown(value: number | null, unit?: string): string {
  if (value === null) return '—'
  const digits = Math.abs(value) >= 1 ? 4 : 6
  return `${Number(value.toPrecision(digits))}${unit ? ` ${unit}` : ''}`
}

export function StaticResult({ simulationId, result, artifacts }: Props) {
  const vtp = artifacts.find((one) => one.kind === 'mode_vtp')
  const [mesh, setMesh] = useState<ArrayBuffer | null>(null)

  useEffect(() => {
    if (!vtp) return
    let disposed = false
    void simulationApi.mesh(simulationId, vtp.id).then((bytes) => {
      if (!disposed) setMesh(bytes)
    })
    return () => {
      disposed = true
    }
  }, [simulationId, vtp])

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium">정적 해석 결과</h2>

      {result.warning && (
        // **0 인 결과는 「해석이 됐다」 처럼 보인다** — 그래서 맨 위에 둔다.
        <p className="rounded-md border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          {result.warning}
        </p>
      )}

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-md border p-4 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground text-xs">최대 변형</dt>
          <dd className="font-medium">
            {shown(result.max_displacement, result.units.displacement)}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">최대 상당응력</dt>
          <dd className="font-medium">{shown(result.max_von_mises, result.units.stress)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">물성</dt>
          <dd className="font-medium">{result.material ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">절점</dt>
          <dd className="font-medium">{result.mesh?.nodes?.toLocaleString() ?? '—'}</dd>
        </div>
      </dl>

      {/* 정적의 변형은 **실제 크기**라 과장을 작게 둔다 — 모달처럼 흔들 이유도 없다. */}
      {mesh && <MeshViewer data={mesh} warpRatio={0.05} periodMs={0} heightClass="h-[28rem]" />}
      <p className="text-muted-foreground text-xs">
        단위계 {result.units.system ?? '—'} · 변형 그림은 과장해서 그립니다
      </p>
    </section>
  )
}
