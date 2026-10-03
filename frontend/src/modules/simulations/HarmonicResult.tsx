/**
 * 조화 응답 결과 — **그 주파수에서 얼마나 크게 흔들리나.**
 *
 * 모달은 「어디서 떠는가」, 정적은 「얼마나 밀리나」 였다. 여기서 사람이 먼저 보는 것은
 * **봉우리** 다: 어느 주파수에서 가장 크게 흔들리고, 그것이 창의 다른 자리보다 몇 배인가.
 *
 * **감쇠비를 곡선 옆에 적는다.** 봉우리 높이를 거의 감쇠가 정하기 때문이다(1/2ζ) — 2% 와 5%
 * 로 같은 모델을 돌렸을 때 봉우리가 2.46배 갈렸다(실측 2026-10-02). 그 값을 안 보여 주면 큰
 * 수를 보고도 그것이 물리인지 가정인지 알 수 없다.
 *
 * **봉우리가 창 끝에 붙으면 말해 준다.** 그때 곡선은 공진의 옆구리만 보여 준 것이라, 범위를
 * 넓히거나 점을 늘려야 한다 — 그대로 읽으면 가장 큰 떨림을 놓친다. 29~31 kHz 를 훑고
 * 「봉우리 31 kHz」 를 읽었다가 실제 공진이 60 kHz 였던 일을 그대로 겪었다.
 */

import type { HarmonicResult as HarmonicResultData, ProbeRow } from '@/modules/simulations/api'
import { shownValue as shown } from '@/modules/simulations/format'
import { Chart } from '@/shared/charts'

type Props = {
  result: HarmonicResultData
}

/** 표에 열로 세울 측정점 수 상한 — 그보다 많으면 곡선과 봉우리 줄로만 본다. */
const TABLE_PROBES = 4

/**
 * 측정점마다 **그 자리 곡선의 봉우리**. 결과가 한 줄씩 적어 보내면(절점 거리 · 경고 포함) 그것을,
 * 옛 결과면 곡선에서 직접 찾는다.
 */
function probePeaks(result: HarmonicResultData, names: string[]): ProbeRow[] {
  if (result.probes?.length) return result.probes
  return names.flatMap((name) => {
    const curve = result.points.filter((one) => typeof one.probes?.[name] === 'number')
    if (curve.length === 0) return []
    const top = curve.reduce((best, one) =>
      (one.probes?.[name] ?? 0) > (best.probes?.[name] ?? 0) ? one : best,
    )
    return [
      {
        name,
        point: [0, 0, 0],
        node: 0,
        distance_mm: Number.NaN,
        value: top.probes?.[name] ?? 0,
        unit: result.units.displacement ?? '',
        frequency_hz: top.frequency_hz,
      } satisfies ProbeRow,
    ]
  })
}

export function HarmonicResult({ result }: Props) {
  const points = result.points ?? []
  const peak = result.peak
  const edges = [points[0], points[points.length - 1]].filter(Boolean)
  // **창 끝에 붙은 봉우리는 봉우리가 아니다** — 공진을 지나지 않았다는 뜻이다.
  const onEdge = edges.some((one) => one.frequency_hz === peak?.frequency_hz)
  const floor = points.length ? Math.min(...points.map((one) => one.max_displacement)) : 0
  const gain = floor > 0 && peak ? peak.max_displacement / floor : null
  const displacement = result.units.displacement
  const frequency = result.units.frequency || 'Hz'
  // 측정점 이름은 CAD 가 준 아무 글자다(「이음 입구 위판」) — **그대로 데이터 열쇠로 쓰지
  // 않는다**(점이 든 이름을 차트가 중첩 경로로 읽는다). 열쇠는 번호, 이름은 범례에.
  const names = [...new Set(points.flatMap((one) => Object.keys(one.probes ?? {})))]
  const peaks = probePeaks(result, names)
  const tabled = names.slice(0, TABLE_PROBES)

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium">조화 응답 결과</h2>

      {result.warning && (
        // **큰 수는 그럴듯해 보인다** — 감쇠가 모자랄 때의 치솟음을 맨 위에 둔다.
        <p className="rounded-md border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          {result.warning}
        </p>
      )}

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-md border p-4 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground text-xs">봉우리 주파수</dt>
          <dd className="font-medium">{peak ? shown(peak.frequency_hz, frequency) : '—'}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">그때 최대 변위</dt>
          <dd className="font-medium">
            {peak ? shown(peak.max_displacement, displacement) : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">감쇠비</dt>
          <dd className="font-medium">{(result.damping_ratio * 100).toFixed(1)}%</dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">창에서 몇 배</dt>
          <dd className="font-medium">{gain ? `${gain.toFixed(1)}배` : '—'}</dd>
        </div>
      </dl>

      {onEdge && (
        <p className="rounded-md border border-sky-300 bg-sky-50 px-4 py-2 text-sm text-sky-900 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-200">
          봉우리가 훑은 범위의 끝에 있습니다 — 공진을 지나지 않았을 수 있습니다. 범위를 넓혀 다시
          돌려 보세요.
        </p>
      )}

      {peaks.length > 0 && (
        // **센서 자리의 봉우리** — 전체 봉우리와 주파수가 다를 수 있다(최대가 나는 자리가
        // 주파수마다 옮겨 다닌다). 실측 FRF 와 견줄 값은 이쪽이다.
        <div className="space-y-1 rounded-md border p-3 text-sm">
          <p className="text-muted-foreground text-xs">측정점 봉우리</p>
          <ul className="space-y-1">
            {peaks.map((one) => (
              <li key={one.name}>
                <span className="font-medium">{one.name}</span>{' '}
                {one.frequency_hz !== undefined && shown(one.frequency_hz, frequency)} ·{' '}
                {shown(one.value, displacement)}
                {Number.isFinite(one.distance_mm) && (
                  <span className="text-muted-foreground"> · 절점 거리 {shown(one.distance_mm, 'mm')}</span>
                )}
                {one.warning && (
                  <span className="block text-xs text-amber-700 dark:text-amber-400">{one.warning}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Chart
        kind="line"
        data={points.map((one) => ({
          frequency: one.frequency_hz,
          최대변위: one.max_displacement,
          ...Object.fromEntries(names.map((name, index) => [`p${index}`, one.probes?.[name] ?? null])),
        }))}
        x="frequency"
        series={[
          { key: '최대변위', label: '최대 변위' },
          ...names.map((name, index) => ({ key: `p${index}`, label: `측정점: ${name}` })),
        ]}
        height={280}
      />

      <table className="w-full text-sm">
        <thead className="text-muted-foreground text-xs">
          <tr>
            <th className="py-1 text-left font-normal">주파수 ({frequency})</th>
            <th className="py-1 text-right font-normal">
              최대 변위{displacement ? ` (${displacement})` : ''}
            </th>
            {tabled.map((name) => (
              <th key={name} className="py-1 text-right font-normal">
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {points.map((one) => (
            <tr
              key={one.frequency_hz}
              className={one.frequency_hz === peak?.frequency_hz ? 'font-medium' : undefined}
            >
              <td className="py-1">{shown(one.frequency_hz)}</td>
              <td className="py-1 text-right">{shown(one.max_displacement)}</td>
              {tabled.map((name) => (
                <td key={name} className="py-1 text-right">
                  {shown(one.probes?.[name])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      <p className="text-muted-foreground text-xs">
        단위계 {result.units.system ?? '—'} · 물성 {result.material ?? '—'} · 절점{' '}
        {result.mesh?.nodes?.toLocaleString() ?? '—'} · 봉우리 높이는 감쇠비에 거의 반비례합니다
        (1/2ζ)
      </p>
    </section>
  )
}
