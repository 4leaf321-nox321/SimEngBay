/**
 * 정적 해석 결과 — **얼마나 밀리고 어디가 버거운가.**
 *
 * 모달은 「어느 주파수에서 어떻게 떠는가」 였다. 여기서 사람이 먼저 보는 것은 **최대 변형**
 * 이고, 그다음이 최대 상당응력이다. 값에 **단위를 붙여** 보여 준다 — 값만 보면 mm 와 m 가
 * 구별되지 않는다(모달에서 겪은 그대로다).
 */
import { lazy, Suspense, useEffect, useState } from 'react'

import type { Artifact, StaticCaseResult, StaticResult as StaticResultData } from '@/modules/simulations/api'
import { simulationApi } from '@/modules/simulations/api'
import { shownValue as shown } from '@/modules/simulations/format'
import { BoltTable, ReactionTable, StaticProbeTable } from '@/modules/simulations/ProbeTables'

// **3D 뷰어는 `lazy()` 로만 받는다** — vtk.js 한 덩어리가 수백 KB 다(`shared/viewer`).
const MeshViewer = lazy(() => import('@/shared/viewer/MeshViewer'))

type Props = {
  simulationId: string
  result: StaticResultData
  artifacts: Artifact[]
}

export function StaticResult({ simulationId, result, artifacts }: Props) {
  const vtp = artifacts.find((one) => one.kind === 'mode_vtp')
  const [mesh, setMesh] = useState<ArrayBuffer | null>(null)
  const [meshError, setMeshError] = useState<string | null>(null)

  useEffect(() => {
    if (!vtp) return
    let disposed = false
    setMeshError(null)
    simulationApi
      .mesh(simulationId, vtp.id)
      .then((bytes) => {
        if (!disposed) setMesh(bytes)
      })
      .catch((caught: unknown) => {
        // **말없이 사라지지 않는다** — 숫자만 있고 그림이 없으면 사람은 까닭을 짐작할 길이 없다.
        if (!disposed) {
          setMeshError(caught instanceof Error ? caught.message : '변형 그림을 받지 못했습니다.')
        }
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
        {result.max_equivalent_plastic_strain != null && (
          <div>
            <dt className="text-muted-foreground text-xs">최대 등가 소성 변형률</dt>
            <dd className="font-medium">{result.max_equivalent_plastic_strain.toPrecision(4)}</dd>
          </div>
        )}
      </dl>

      {result.cases && result.cases.length > 1 && (
        <CaseTable
          result={result}
          rows={result.cases}
          label="케이스"
          caption="케이스마다 끝 상태 — 하중은 케이스 사이에 이어지지 않습니다(조인 볼트만 잠긴 채 이어집니다)"
        />
      )}
      {result.steps && result.steps.length > 1 && (
        <CaseTable
          result={result}
          rows={result.steps}
          label="하중 단계"
          caption="하중 단계 끝마다 — 하중은 시간별 배율 · 적용 단계를 따르고, 볼트는 첫 단계에서 조인 뒤 잠깁니다"
        />
      )}

      {/* **센서 자리의 값과 버틴 힘** — 실측과 견줄 수 있는 것은 전체 최대가 아니라 이쪽이다. */}
      <StaticProbeTable probes={result.probes ?? []} />
      <ReactionTable reactions={result.reactions ?? {}} unit={result.units.force} />
      <BoltTable bolts={result.bolts ?? {}} />

      {/* 정적의 변형은 **실제 크기**라 과장을 작게 둔다 — 모달처럼 흔들 이유도 없다(주기 0). */}
      {!vtp && <p className="text-muted-foreground text-sm">이 작업은 변형 그림을 만들지 않았습니다.</p>}
      {meshError && <p className="text-destructive text-sm">{meshError}</p>}
      {mesh && (
        <Suspense
          fallback={<p className="text-muted-foreground py-8 text-center text-sm">변형 그림을 불러오는 중…</p>}
        >
          <MeshViewer
            data={mesh}
            warpRatio={0.05}
            periodMs={0}
            displacement="actual"
            heightClass="h-[28rem]"
            partNames={result.parts}
          />
        </Suspense>
      )}
      <p className="text-muted-foreground text-xs">
        단위계 {result.units.system ?? '—'} · 변형 그림은 과장해서 그립니다
      </p>
    </section>
  )
}

/**
 * **케이스마다(또는 하중 단계마다) 끝 상태** — 해석 케이스의 사슬(정적 다단)이면 뒤 케이스는 앞 케이스의
 * 끝에서 시작하고 하중은 이어지지 않으므로, 앞 케이스(예: 볼트를 조인 끝)의 값은 맨 위의 값에 없다. 하중
 * 단계(CompCore ②)면 단계 끝마다 — 당겼다 풀면 마지막 단계에 잔류 변형만 남는다.
 */
function CaseTable({
  result,
  rows,
  label,
  caption,
}: {
  result: StaticResultData
  rows: StaticCaseResult[]
  label: string
  caption: string
}) {
  const regions = Array.from(new Set(rows.flatMap((one) => Object.keys(one.reactions ?? {}))))
  const bolts = Array.from(new Set(rows.flatMap((one) => Object.keys(one.bolts ?? {}))))
  const plastic = rows.some((one) => one.max_equivalent_plastic_strain != null)
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm" aria-label={`${label}마다 끝 상태`}>
        <caption className="text-muted-foreground px-3 pt-2 text-left text-xs">{caption}</caption>
        <thead>
          <tr className="text-muted-foreground text-left text-xs">
            <th className="px-3 py-2 font-medium">{label}</th>
            <th className="px-3 py-2 font-medium">최대 변형</th>
            <th className="px-3 py-2 font-medium">최대 상당응력</th>
            {plastic && <th className="px-3 py-2 font-medium">등가 소성 변형률</th>}
            {regions.map((name) => (
              <th key={`r-${name}`} className="px-3 py-2 font-medium">
                반력 {name} [{result.units.force ?? 'N'}]
              </th>
            ))}
            {bolts.map((name) => (
              <th key={`b-${name}`} className="px-3 py-2 font-medium">
                볼트 {name} [N]
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((one) => (
            <tr key={one.name} className="border-t">
              <td className="px-3 py-2 font-medium">
                {one.name}
                {one.end_time != null && <span className="text-muted-foreground ml-1 text-xs">({one.end_time} s)</span>}
              </td>
              <td className="px-3 py-2">{shown(one.max_displacement, result.units.displacement)}</td>
              <td className="px-3 py-2">{shown(one.max_von_mises, result.units.stress)}</td>
              {plastic && (
                <td className="px-3 py-2 tabular-nums">
                  {one.max_equivalent_plastic_strain != null ? one.max_equivalent_plastic_strain.toPrecision(4) : '—'}
                </td>
              )}
              {regions.map((name) => {
                const force = one.reactions?.[name]
                return (
                  <td key={`r-${name}`} className="px-3 py-2 tabular-nums">
                    {force ? force.map((part) => part.toPrecision(4)).join(' · ') : '—'}
                  </td>
                )
              })}
              {bolts.map((name) => {
                const bolt = one.bolts?.[name]
                return (
                  <td key={`b-${name}`} className="px-3 py-2 tabular-nums">
                    {bolt?.force_n != null ? bolt.force_n.toPrecision(5) : '—'}
                    {bolt?.force_given && <span className="text-muted-foreground ml-1 text-xs">(준 예압)</span>}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

