/**
 * 랜덤 진동 결과 — **흔들림의 통계**(1σ). 조화 응답이 「그 주파수에서 얼마나」 라면 이것은 「PSD 로
 * 흔들 때 보통 얼마나」 다.
 *
 * 사람이 먼저 보는 것은 **측정점의 가속도 1σ**(Grms — 가속도계가 재는 절대 가속도)와 **최대 1σ
 * 변위**(지지부 기준 — 틈 · 간섭을 보는 값)다. 1σ 는 시간의 68.3 % 가 그 아래라는 뜻이라 설계는 흔히
 * 3σ(99.7 %, 세 배)로 본다 — 두 값을 함께 적는다.
 *
 * PSD 곡선은 **로그-로그**로 그린다 — 입력과 응답이 몇 자릿수에 걸쳐 있어 선형 축에서는 공진 봉우리
 * 하나만 보이고 입력 PSD 가 바닥에 깔린다.
 */
import { lazy, Suspense, useEffect, useState } from 'react'

import type { Artifact, RandomResult as RandomResultData } from '@/modules/simulations/api'
import { simulationApi } from '@/modules/simulations/api'
import { rangeText, shownValue as shown } from '@/modules/simulations/format'
import { Chart } from '@/shared/charts'

// **3D 뷰어는 `lazy()` 로만 받는다** — vtk.js 한 덩어리가 수백 KB 다(`shared/viewer`).
const MeshViewer = lazy(() => import('@/shared/viewer/MeshViewer'))

type Props = {
  simulationId: string
  result: RandomResultData
  artifacts: Artifact[]
}

const RANGE_FROM: Record<'cad' | 'spec', string> = {
  cad: 'CAD 가 적은 범위',
  spec: '작업에서 준 범위',
}

/** 그림에 싣는 점 상한 — 넘으면 고르게 솎는다(봉우리 자리는 남긴다). */
const CHART_POINTS = 800

function thinned(count: number, keep: number[]): number[] {
  if (count <= CHART_POINTS) return Array.from({ length: count }, (_, index) => index)
  const step = count / CHART_POINTS
  const picked = new Set<number>(keep)
  for (let at = 0; at < count; at += step) picked.add(Math.floor(at))
  picked.add(count - 1)
  return [...picked].sort((a, b) => a - b)
}

function direction(vector: [number, number, number]): string {
  const axes = ['X', 'Y', 'Z']
  const big = vector.map((one) => Math.abs(one))
  const top = big.indexOf(Math.max(...big))
  if (big[top] > 0.999) return `${vector[top] < 0 ? '−' : ''}${axes[top]}`
  return `(${vector.map((one) => one.toFixed(3)).join(', ')})`
}

export function RandomResult({ simulationId, result, artifacts }: Props) {
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
        if (!disposed) setMeshError(caught instanceof Error ? caught.message : '1σ 그림을 받지 못했습니다.')
      })
    return () => {
      disposed = true
    }
  }, [simulationId, vtp])

  const probes = result.probes ?? []
  const inputs = result.inputs ?? []
  const curves = result.curves
  const freqs = curves?.frequency_hz ?? []
  const responseNames = Object.keys(curves?.probes ?? {})
  // 측정점 이름 · 가진 이름은 CAD 가 준 아무 글자다 — 데이터 열쇠는 번호, 이름은 범례에(조화와 같다).
  const peaks = responseNames.map((name) => {
    const values = curves?.probes?.[name] ?? []
    return values.indexOf(Math.max(...values))
  })
  const rows = thinned(freqs.length, peaks).map((at) => ({
    frequency: freqs[at],
    ...Object.fromEntries(inputs.map((one, index) => [`i${index}`, curves?.input_psd?.[one.name]?.[at] ?? null])),
    ...Object.fromEntries(responseNames.map((name, index) => [`p${index}`, curves?.probes?.[name]?.[at] ?? null])),
  }))
  const first = probes[0]
  const largest = result.max_displacement?.value_mm
  // **v0.29.0 의 결과는 `band_hz` 가 없다** — 그때는 `frequency_range_hz` 가 적분 대역이었다(찾을 범위가
  // 아니다). 저장된 옛 결과도 읽는다.
  const [low, high] = result.band_hz ?? result.frequency_range_hz ?? [freqs[0] ?? 0, freqs[freqs.length - 1] ?? 0]
  const searched = result.band_hz ? result.frequency_range_hz : undefined

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium">랜덤 진동 결과</h2>

      {result.warning && (
        <p className="rounded-md border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          {result.warning}
        </p>
      )}

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-md border p-4 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground text-xs">입력</dt>
          <dd className="font-medium">
            {inputs.length
              ? inputs.map((one) => `${one.name} ${shown(one.grms, 'Grms')}`).join(' · ')
              : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">
            {first ? `${first.name} 가속도 1σ` : '측정점 가속도 1σ'}
          </dt>
          <dd className="font-medium">
            {first ? `${shown(first.value, 'g')} · 3σ ${shown(first.value * 3, 'g')}` : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">최대 1σ 변위 (지지부 기준)</dt>
          <dd className="font-medium">
            {largest !== undefined ? `${shown(largest, 'mm')} · 3σ ${shown(largest * 3, 'mm')}` : '—'}
          </dd>
        </div>
        {result.stress && (
          <div>
            <dt className="text-muted-foreground text-xs">최대 상당응력 1σ</dt>
            <dd className="font-medium">
              {shown(result.stress.max_von_mises_mpa, 'MPa')} · 3σ {shown(result.stress.max_von_mises_mpa * 3, 'MPa')}
            </dd>
          </div>
        )}
        <div>
          <dt className="text-muted-foreground text-xs">감쇠비 · 가진 대역</dt>
          <dd className="font-medium">
            {(result.damping_ratio * 100).toFixed(1)}% · {shown(low)}~{shown(high)} Hz
          </dd>
        </div>
      </dl>
      <p className="text-muted-foreground text-xs">
        1σ(실효값) — 시간의 68.3 % 가 그 아래, 3σ 는 세 배(99.7 %). 가속도는 지지부의 가속도를 더한 절대 값
        (가속도계가 재는 값), 변위는 지지부 기준입니다. 가진 대역은 PSD 표의 범위이고, 가진이 여럿이면 서로 무관한
        것으로 더했습니다.
        {searched && (result.range_from === 'cad' || result.range_from === 'spec') && (
          <>
            {' '}
            모드는 {RANGE_FROM[result.range_from]} {rangeText(searched)} 안에서 찾은 것만 썼습니다.
          </>
        )}
        {result.solver === 'ansys'
          ? ' Ansys(Mechanical 의 Random Vibration)로 풀었습니다 — 빠진 높은 모드의 정적 몫(잔여 벡터)을 더하지 않고 상당응력 1σ 도 내지 않습니다. 모드 수가 모자라면 고유진동수가 대역보다 훨씬 높은 부품의 응답이 작게 나옵니다.'
          : result.residual === undefined
          ? null
          : result.residual
            ? ' 빠진 높은 모드의 정적 몫(잔여 벡터)을 더했습니다 — 고유진동수가 대역보다 훨씬 높은 부품도 모드 수와 상관없이 맞습니다.'
            : ' 빠진 높은 모드의 정적 몫(잔여 벡터)은 더하지 못했습니다(선응력 · 비선형 접촉) — 모드 수가 모자라면 응답이 달라집니다.'}
      </p>

      {probes.length > 0 && (
        <table className="w-full text-sm">
          <thead className="text-muted-foreground text-xs">
            <tr>
              <th className="py-1 text-left font-normal">측정점</th>
              <th className="py-1 text-right font-normal">가속도 1σ (g)</th>
              <th className="py-1 text-right font-normal">X · Y · Z (g)</th>
              <th className="py-1 text-right font-normal">1σ 변위 (mm)</th>
              <th className="py-1 text-right font-normal">응답 봉우리 (Hz)</th>
            </tr>
          </thead>
          <tbody>
            {probes.map((one) => (
              <tr key={one.name}>
                <td className="py-1">
                  {one.name}
                  {Number.isFinite(one.distance_mm) && one.distance_mm > 0 && (
                    <span className="text-muted-foreground text-xs"> · 절점 거리 {shown(one.distance_mm, 'mm')}</span>
                  )}
                  {one.warning && (
                    <span className="block text-xs text-amber-700 dark:text-amber-400">{one.warning}</span>
                  )}
                </td>
                <td className="py-1 text-right font-medium">{shown(one.value)}</td>
                <td className="py-1 text-right">{one.vector ? one.vector.map((axis) => shown(axis)).join(' · ') : '—'}</td>
                <td className="py-1 text-right">{shown(one.displacement_1sigma_mm)}</td>
                <td className="py-1 text-right">{shown(one.psd_peak_hz ?? undefined)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <Chart
        kind="line"
        logX
        logY
        data={rows}
        x="frequency"
        series={[
          ...inputs.map((one, index) => ({ key: `i${index}`, label: `입력: ${one.name}` })),
          ...responseNames.map((name, index) => ({ key: `p${index}`, label: `응답: ${name}` })),
        ]}
        height={300}
        title="입력 PSD 와 측정점 응답 PSD (g²/Hz, 로그-로그)"
        emptyText="측정점이 없어 응답 곡선이 없습니다 — CAD 점 그룹(측정점)을 보내면 그 자리의 응답 PSD 를 그립니다."
      />
      <p className="text-muted-foreground text-xs">
        가로 주파수(Hz) · 세로 PSD(g²/Hz), 둘 다 로그 축 — 응답은 세 축의 합입니다. 곡선 아래 넓이의 제곱근이
        Grms 입니다.
      </p>

      {result.modes?.length > 0 && (
        <table className="w-full text-sm">
          <thead className="text-muted-foreground text-xs">
            <tr>
              <th className="py-1 text-left font-normal">모드</th>
              <th className="py-1 text-right font-normal">주파수 (Hz)</th>
              {inputs.map((one) => (
                <th key={one.name} className="py-1 text-right font-normal">
                  {one.name}({direction(one.direction)}) 유효질량 몫
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.modes.map((one) => (
              <tr key={one.number} className={one.frequency_hz < low || one.frequency_hz > high ? 'text-muted-foreground' : undefined}>
                <td className="py-1">{one.number}</td>
                <td className="py-1 text-right">{shown(one.frequency_hz)}</td>
                {inputs.map((input) => (
                  <td key={input.name} className="py-1 text-right">
                    {one.mass_share?.[input.name] !== undefined
                      ? `${(one.mass_share[input.name] * 100).toFixed(1)}%`
                      : '—'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!vtp && <p className="text-muted-foreground text-sm">이 작업은 1σ 그림을 만들지 않았습니다.</p>}
      {meshError && <p className="text-destructive text-sm">{meshError}</p>}
      {mesh && (
        <Suspense fallback={<p className="text-muted-foreground py-8 text-center text-sm">1σ 그림을 불러오는 중…</p>}>
          <MeshViewer
            data={mesh}
            warpRatio={0}
            periodMs={0}
            displacement="actual"
            heightClass="h-[28rem]"
            partNames={result.parts}
          />
        </Suspense>
      )}
      <p className="text-muted-foreground text-xs">
        단위계 {result.units.system ?? '—'} · 물성 {result.material ?? '—'} · 절점{' '}
        {result.mesh?.nodes?.toLocaleString() ?? '—'} · 적분 점 {result.frequency_points?.toLocaleString() ?? '—'}{' '}
        · 그림의 색은 1σ 변위(모양은 휘지 않습니다 — 1σ 는 방향이 없는 통계값입니다)
      </p>
    </section>
  )
}
