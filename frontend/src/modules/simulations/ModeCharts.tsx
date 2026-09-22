/**
 * 모드를 **여러 방식으로** 본다 — 같은 값이라도 묻는 것이 다르면 그림이 달라야 한다.
 *
 *     스펙트럼        주파수 축 · 유효질량비 높이 — 「어느 대역에 무엇이 있나」 (기본)
 *     누적 유효질량   주파수 축 · 방향별 누적 % — 「몇 Hz 까지 봐야 질량을 다 잡나」
 *     모드별          모드 번호 축 · 주파수 막대 — 「몇 번째가 몇 Hz 인가」
 *
 * **기본이 스펙트럼인 이유**: 모드 번호를 가로축에 두면 그림은 늘 단조 증가하는 계단이고,
 * 그 물음에는 표가 더 잘 답한다. 진동에서 실제로 묻는 것은 대역이다.
 *
 * ## 자유-자유에서는 유효질량비가 비어 있다
 *
 * 강체 모드가 질량을 전부 가져가므로 탄성 모드의 값이 0 이다. 그때 스펙트럼은 균일한 높이로
 * 서고 이유를 적으며, 누적 그림은 **탭 자체가 잠기고 왜 잠겼는지 말한다** — 눌러 보고 빈
 * 그림을 만나는 것보다 낫다.
 */

import { useMemo, useState } from 'react'

import type { ModeResult, SimulationResult } from '@/modules/simulations/api'
import { Chart, Spectrum } from '@/shared/charts'
import type { SpectrumLine, SpectrumPoint } from '@/shared/charts'
import { Button } from '@/shared/components/ui/button'
import { cn } from '@/shared/lib/utils'

type View = 'spectrum' | 'cumulative' | 'byMode'

/** 누적 곡선을 그릴 방향 — 이동 셋. 회전(ROTX…)까지 겹치면 선 여섯이 서로를 가린다. */
const CURVE_DIRECTIONS = ['X', 'Y', 'Z'] as const

const DIRECTION_LABELS: Record<string, string> = {
  X: 'X 이동',
  Y: 'Y 이동',
  Z: 'Z 이동',
}

interface Props {
  result: SimulationResult
  /** 스펙트럼에서 모드를 누르면 그 모드를 고른다(형상 뷰어가 따라간다). */
  onPick?: (mode: ModeResult) => void
  selected?: number | null
}

export function ModeCharts({ result, onPick, selected }: Props) {
  const [view, setView] = useState<View>('spectrum')
  const elastic = useMemo(() => result.modes.filter((one) => !one.rigid_body), [result.modes])
  const unit = result.units.frequency

  /** 방향별 누적 유효질량 — **모드 번호 순으로 더한다**(주파수 오름차순과 같다). */
  const curves = useMemo<SpectrumLine[]>(() => {
    const table = result.participation ?? {}
    const byNumber = new Map(result.modes.map((one) => [one.number, one]))
    const made: SpectrumLine[] = []
    for (const direction of CURVE_DIRECTIONS) {
      const ratios = table[direction]
      if (!ratios) continue
      let running = 0
      const points: { x: number; y: number }[] = []
      for (const [rawNumber, ratio] of Object.entries(ratios).sort(
        (a, b) => Number(a[0]) - Number(b[0]),
      )) {
        const mode = byNumber.get(Number(rawNumber))
        if (!mode) continue
        running += ratio
        points.push({ x: mode.frequency_hz, y: Math.min(running, 1) * 100 })
      }
      if (points.some((one) => one.y > 0)) {
        made.push({ key: direction, label: DIRECTION_LABELS[direction] ?? direction, points })
      }
    }
    return made
  }, [result.participation, result.modes])

  const spectrumPoints = useMemo<SpectrumPoint[]>(
    () =>
      elastic.map((one) => ({
        key: String(one.number),
        x: one.frequency_hz,
        y: (one.effective_mass_ratio ?? 0) * 100,
        label: `${one.elastic_number}차`,
      })),
    [elastic],
  )

  const byMode = useMemo(
    () =>
      elastic.map((one) => ({
        name: `${one.elastic_number}차`,
        주파수: one.frequency_hz,
      })),
    [elastic],
  )

  const views: { id: View; label: string; disabled?: string }[] = [
    { id: 'spectrum', label: '스펙트럼' },
    {
      id: 'cumulative',
      label: '누적 유효질량',
      disabled:
        curves.length === 0
          ? result.boundary === 'free-free'
            ? '구속이 없어 탄성 모드의 유효질량이 0 입니다(강체 모드가 전부 가져갑니다).'
            : '참여계수 표가 없습니다.'
          : undefined,
    },
    { id: 'byMode', label: '모드별' },
  ]
  const current = views.find((one) => one.id === view)

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1">
        {views.map((one) => (
          <Button
            key={one.id}
            variant={view === one.id ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setView(one.id)}
            className={cn(one.disabled && 'text-muted-foreground')}
            title={one.disabled}
          >
            {one.label}
          </Button>
        ))}
      </div>

      {current?.disabled ? (
        // **눌러 보고 빈 그림을 만나게 하지 않는다** — 왜 못 그리는지가 곧 다음에 할 일이다.
        <p className="text-muted-foreground rounded-md border border-dashed py-8 text-center text-sm">
          {current.disabled}
        </p>
      ) : view === 'spectrum' ? (
        <Spectrum
          points={spectrumPoints}
          xLabel={`주파수 (${unit})`}
          yLabel="유효질량비 (%)"
          flatNote={
            result.boundary === 'free-free'
              ? '구속이 없어 탄성 모드의 유효질량비가 0 입니다 — 줄기 높이는 균일하게 그렸습니다. 위치(주파수)만 읽으세요.'
              : '유효질량비가 없어 줄기 높이는 균일하게 그렸습니다.'
          }
          title="모드 스펙트럼"
          onPick={(point) => {
            const mode = result.modes.find((one) => String(one.number) === point.key)
            if (mode && onPick) onPick(mode)
          }}
          emptyText="탄성 모드가 없습니다."
        />
      ) : view === 'cumulative' ? (
        <>
          <Spectrum
            lines={curves}
            xLabel={`주파수 (${unit})`}
            yLabel="누적 유효질량 (%)"
            title="방향별 누적 유효질량"
          />
          <p className="text-muted-foreground text-xs">
            곡선이 90%에 닿는 주파수까지가 이 해석이 붙잡은 범위입니다 — 그 아래에서 멈추면 모드
            수를 늘려 다시 실행합니다. 선: {curves.map((one) => one.label).join(' · ')}
          </p>
        </>
      ) : (
        <Chart
          kind="bar"
          data={byMode}
          x="name"
          series={[{ key: '주파수', label: `주파수 (${unit})` }]}
          height={240}
          title="모드별 고유진동수"
          emptyText="탄성 모드가 없습니다."
        />
      )}

      {selected != null && view === 'spectrum' && (
        <p className="text-muted-foreground text-xs">
          줄기를 누르면 아래 3D 뷰어가 그 모드로 바뀝니다.
        </p>
      )}
    </div>
  )
}
