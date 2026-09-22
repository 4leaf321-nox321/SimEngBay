/**
 * 스펙트럼 — **가로축이 주파수인** 그림. 막대그래프와는 묻는 것이 다르다.
 *
 * 모드 번호를 가로축에 두면 막대는 정의상 **단조 증가하는 계단**이 된다(모드는 주파수 순으로
 * 번호가 붙으니까). 그림이 모델마다 거의 같아지고, 「몇 번째 모드가 몇 Hz」 는 표가 더 잘
 * 답한다. 반면 가로축을 주파수로 두면 **어느 대역에 모드가 몰려 있나 · 내 가진 대역 안에
 * 무엇이 있나** 가 한눈에 보인다 — 그것이 진동에서 실제로 묻는 것이다.
 *
 * ## 줄기(stem)를 값 자리에 세운다
 *
 * 막대를 수치 축에 얹는 대신 **선분을 직접 놓는다**(`ReferenceLine segment`). 막대는 축 종류에
 * 따라 자리 잡는 규칙이 달라지는데, 선분은 「이 x 에서 0 부터 y 까지」 라고 적은 그대로 선다.
 * 점(`Scatter`)은 손을 올렸을 때 값을 말해 주는 자리다 — 줄기만 있으면 뭘 가리키는지 못 읽는다.
 *
 * ## 높이가 전부 0 일 수 있다
 *
 * 자유-자유 해석에서는 강체 모드가 유효질량을 전부 가져가서 탄성 모드의 값이 0 이다. 그때
 * 높이로 그리면 **빈 그림**이 되므로 균일한 높이로 세우고 `flatNote` 로 이유를 적는다 —
 * 「그림이 비었다」 와 「값이 0 이다」 는 다른 말이다.
 */

import {
  CartesianGrid,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { AXIS_COLOR, GRID_COLOR, colorAt, shownNumber } from '@/shared/charts/palette'

export interface SpectrumPoint {
  key: string
  x: number
  y: number
  /** 손을 올렸을 때 보여 줄 이름(「3차 · 2583 Hz」). 없으면 좌표만. */
  label?: string
}

export interface SpectrumLine {
  key: string
  label: string
  color?: string
  points: { x: number; y: number }[]
}

export interface SpectrumProps {
  /** 줄기 하나 = 모드 하나. */
  points?: SpectrumPoint[]
  /** 겹쳐 그릴 곡선들(누적 유효질량 같은 것). */
  lines?: SpectrumLine[]
  xLabel: string
  yLabel: string
  /** 강조할 가로축 구간(가진 대역 · 운전 범위). 그 안에 든 모드가 곧 할 일이다. */
  band?: { from: number; to: number; label?: string }
  height?: number
  /** 값이 전부 0 일 때 균일 높이로 세우고 여기 적은 말을 함께 보여 준다. */
  flatNote?: string
  emptyText?: string
  title?: string
  onPick?: (point: SpectrumPoint) => void
  className?: string
}

const MARGIN = { top: 12, right: 16, bottom: 20, left: 8 }
//: 줄기를 이보다 많이 그리지 않는다. 그 너머는 선이 겹쳐 검은 띠가 될 뿐이라 점만 남긴다.
const MAX_STEMS = 300

export function Spectrum({
  points = [],
  lines = [],
  xLabel,
  yLabel,
  band,
  height = 260,
  flatNote,
  emptyText = '그릴 것이 없습니다.',
  title,
  onPick,
  className,
}: SpectrumProps) {
  const hasCurves = lines.some((one) => one.points.length > 0)
  if (points.length === 0 && !hasCurves) {
    return (
      <p className={`text-muted-foreground py-8 text-center text-sm ${className ?? ''}`}>
        {emptyText}
      </p>
    )
  }

  const peak = Math.max(0, ...points.map((one) => one.y), ...lines.flatMap((one) => one.points.map((p) => p.y)))
  const flat = points.length > 0 && peak === 0
  const drawn = flat ? points.map((one) => ({ ...one, y: 1 })) : points
  const top = flat ? 1 : peak
  const stems = drawn.length <= MAX_STEMS ? drawn : []

  return (
    <div className={className}>
      <div
        style={{ height }}
        role="img"
        aria-label={title ?? `${xLabel} 대 ${yLabel} 스펙트럼`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={MARGIN}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
            <XAxis
              type="number"
              dataKey="x"
              name={xLabel}
              stroke={AXIS_COLOR}
              fontSize={12}
              tickFormatter={shownNumber}
              label={{ value: xLabel, position: 'insideBottom', offset: -12, fontSize: 12 }}
            />
            <YAxis
              type="number"
              dataKey="y"
              name={yLabel}
              stroke={AXIS_COLOR}
              fontSize={12}
              domain={[0, top * 1.1]}
              tickFormatter={flat ? () => '' : shownNumber}
              label={{ value: flat ? '' : yLabel, angle: -90, position: 'insideLeft', fontSize: 12 }}
            />
            {band && (
              // **가진 대역 안에 든 모드가 곧 할 일이다.** 숫자로만 주면 사람이 표를 훑으며
              // 손으로 비교하게 되고, 그 비교는 자주 틀린다.
              <ReferenceArea
                x1={band.from}
                x2={band.to}
                fill="var(--destructive)"
                fillOpacity={0.08}
                label={{ value: band.label ?? '가진 대역', fontSize: 11, position: 'insideTop' }}
              />
            )}
            {stems.map((one) => (
              <ReferenceLine
                key={one.key}
                segment={[
                  { x: one.x, y: 0 },
                  { x: one.x, y: one.y },
                ]}
                stroke={colorAt(0)}
                strokeWidth={1.5}
              />
            ))}
            {lines.map((one, index) => (
              <Scatter
                key={one.key}
                name={one.label}
                data={one.points}
                line={{ stroke: one.color ?? colorAt(index + 1), strokeWidth: 2 }}
                shape={() => <g />}
              />
            ))}
            {drawn.length > 0 && (
              <Scatter
                name={yLabel}
                data={drawn}
                fill={colorAt(0)}
                onClick={(entry: unknown) => {
                  const row = entry as SpectrumPoint | undefined
                  if (onPick && row?.key) onPick(row)
                }}
              />
            )}
            <Tooltip
              cursor={{ strokeDasharray: '3 3' }}
              formatter={(value: unknown, name: unknown) =>
                typeof value === 'number' ? [shownNumber(value), String(name)] : [String(value), String(name)]
              }
              labelFormatter={() => ''}
              contentStyle={{
                background: 'var(--popover)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                color: 'var(--popover-foreground)',
                fontSize: 12,
              }}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      {flat && flatNote && <p className="text-muted-foreground mt-1 text-xs">{flatNote}</p>}
      {drawn.length > MAX_STEMS && (
        <p className="text-muted-foreground mt-1 text-xs">
          모드가 {drawn.length.toLocaleString()}개라 줄기는 생략하고 점만 표시합니다.
        </p>
      )}
    </div>
  )
}
