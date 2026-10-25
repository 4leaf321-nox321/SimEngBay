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
 *
 * ## 점이 무엇인지 말한다(2026-10-25)
 *
 * DOE 그림의 점 하나는 설계점 하나다. 이름 없이 점만 찍으면 「이 점이 어느 설계냐」 를 표에서
 * 값으로 거꾸로 찾아야 한다. 그래서 **손을 올리면 이름**(`label`)을, 점이 적으면 **점 옆에 이름**
 * (`pointLabels`)을, 가로축이 설계 변수면 **눈금 아래에 그 값의 설계점**(`xTicks`)을 적는다.
 * 많으면(`MAX_NAMED_*` 넘게) 적지 않는다 — 글자가 겹쳐 점을 가린다. 그때는 손을 올려 읽는다.
 */

import {
  CartesianGrid,
  LabelList,
  Legend,
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
  /** `label` 은 손을 올렸을 때 그 점의 이름(설계점). */
  points: { x: number; y: number; label?: string }[]
  /**
   * 점을 선으로 이을지(기본 잇는다). **잇지 않으면 점만** — 같은 가로축 값에 다른 설계가 쌓인 DOE
   * 에서 이으면 서로 다른 설계를 잇는다(`StudyAxis`).
   */
  connect?: boolean
}

export interface SpectrumProps {
  /** 줄기 하나 = 모드 하나. */
  points?: SpectrumPoint[]
  /**
   * 겹쳐 그릴 곡선들(누적 유효질량 · 모드별 추이).
   *
   * **둘 이상이면 범례를 단다.** 선이 여럿인데 이름이 없으면 어느 선이 무엇인지 못 읽고,
   * 그때 그림은 「대충 이렇게 생겼다」 밖에 말하지 못한다.
   */
  lines?: SpectrumLine[]
  xLabel: string
  yLabel: string
  /** 강조할 가로축 구간(가진 대역 · 운전 범위). 그 안에 든 모드가 곧 할 일이다. */
  band?: { from: number; to: number; label?: string }
  height?: number
  /** 값이 전부 0 일 때 균일 높이로 세우고 여기 적은 말을 함께 보여 준다. */
  flatNote?: string
  /**
   * 줄기를 그릴지. **설계점 산점도에서는 끈다** — 거기서 y 는 「0 에서 얼마나 올라왔나」 가
   * 아니라 그냥 결과값이라, 0 까지 내려가는 줄기가 없는 뜻을 만든다.
   */
  stems?: boolean
  emptyText?: string
  title?: string
  onPick?: (point: SpectrumPoint) => void
  className?: string
  /** `points` 의 점 옆에 `label` 을 늘 적는다(점이 `MAX_NAMED_POINTS` 개 이하일 때). */
  pointLabels?: boolean
  /**
   * 가로축 눈금을 이 값들에 두고 **값 아래에 이름**을 한 줄 더 적는다 — 가로축이 설계 변수일 때
   * 그 값의 설계점(「p0002」 · 「p0002 외 3」). `MAX_NAMED_TICKS` 개를 넘으면 보통 눈금으로 돌아간다.
   */
  xTicks?: { value: number; label: string }[]
}

const MARGIN = { top: 12, right: 16, bottom: 20, left: 8 }
//: 줄기를 이보다 많이 그리지 않는다. 그 너머는 선이 겹쳐 검은 띠가 될 뿐이라 점만 남긴다.
const MAX_STEMS = 300
//: 이름을 늘 적는 상한 — 넘으면 글자가 겹쳐 점을 가린다(그때는 손을 올려 읽는다). 눈금은 한 줄에
//: 늘어서 빨리 붙고, 점은 평면에 흩어져 더 견딘다(실측 2026-10-25: 2변수 20점의 질량 대 주파수).
export const MAX_NAMED_TICKS = 12
export const MAX_NAMED_POINTS = 30

/** 툴팁에 실려 오는 점 하나 — 그린 데이터 그대로(`series` 는 선의 이름). */
interface TipRow {
  x?: number
  y?: number
  label?: string
  series?: string
}

/** 손을 올린 점 — **이름이 먼저**, 그다음 좌표. 이름이 없으면 좌표만. */
function Tip({
  active,
  row,
  xLabel,
  yLabel,
}: {
  active?: boolean
  row?: TipRow
  xLabel: string
  yLabel: string
}) {
  if (!active || !row) return null
  const title = [row.label, row.series].filter(Boolean).join(' · ')
  return (
    <div
      className="rounded-md border px-2 py-1 text-xs"
      style={{ background: 'var(--popover)', color: 'var(--popover-foreground)' }}
    >
      {title && <p className="font-medium">{title}</p>}
      {row.x != null && (
        <p>
          {xLabel} {shownNumber(row.x)}
        </p>
      )}
      {row.y != null && (
        <p>
          {yLabel} {shownNumber(row.y)}
        </p>
      )}
    </div>
  )
}

/** 눈금 하나 — 값, 그 아래 이름. */
function NamedTick({
  x,
  y,
  payload,
  names,
}: {
  x?: number
  y?: number
  payload?: { value: number }
  names: Map<number, string>
}) {
  const value = payload?.value
  if (value == null) return null
  const name = names.get(value)
  return (
    <g transform={`translate(${x ?? 0},${y ?? 0})`}>
      <text dy={12} textAnchor="middle" fill={AXIS_COLOR} fontSize={12}>
        {shownNumber(value)}
      </text>
      {name && (
        <text dy={26} textAnchor="middle" fill={AXIS_COLOR} fontSize={10}>
          {name}
        </text>
      )}
    </g>
  )
}

export function Spectrum({
  points = [],
  lines = [],
  xLabel,
  yLabel,
  band,
  height = 260,
  flatNote,
  stems: withStems = true,
  emptyText = '그릴 것이 없습니다.',
  title,
  onPick,
  className,
  pointLabels = false,
  xTicks,
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
  const stems = withStems && drawn.length <= MAX_STEMS ? drawn : []
  const named = xTicks && xTicks.length > 0 && xTicks.length <= MAX_NAMED_TICKS ? xTicks : null
  const names = new Map((named ?? []).map((one) => [one.value, one.label]))
  const labelled = pointLabels && drawn.length <= MAX_NAMED_POINTS

  return (
    <div className={className}>
      <div
        style={{ height }}
        role="img"
        aria-label={title ?? `${xLabel} 대 ${yLabel} 스펙트럼`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={named ? { ...MARGIN, bottom: MARGIN.bottom + 14 } : MARGIN}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
            <XAxis
              type="number"
              dataKey="x"
              name={xLabel}
              stroke={AXIS_COLOR}
              fontSize={12}
              tickFormatter={shownNumber}
              label={{
                value: xLabel,
                position: 'insideBottom',
                offset: named ? -26 : -12,
                fontSize: 12,
              }}
              {...(named && {
                // 눈금을 설계점 값에만 — 사이의 눈금(2.5 같은)은 그런 설계가 없다는 것을 흐린다.
                ticks: named.map((one) => one.value),
                tick: <NamedTick names={names} />,
                height: 44,
                domain: ['dataMin', 'dataMax'],
                padding: { left: 24, right: 24 },
              })}
            />
            <YAxis
              type="number"
              dataKey="y"
              name={yLabel}
              stroke={AXIS_COLOR}
              fontSize={12}
              domain={withStems ? [0, top * 1.1] : ['auto', 'auto']}
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
                // 툴팁이 「p0002 · 2차」 로 말할 수 있게 선의 이름을 점마다 싣는다.
                data={one.points.map((point) => ({ ...point, series: one.label }))}
                fill={one.color ?? colorAt(index)}
                line={
                  one.connect === false ? undefined : { stroke: one.color ?? colorAt(index), strokeWidth: 2 }
                }
                // 선이 여럿이면 점을 함께 찍는다 — 설계점이 셋뿐일 때 선만 있으면 어디가
                // 실제로 잰 자리인지 알 수 없다. 잇지 않으면 점이 곧 그림이다.
                shape={lines.length > 1 || one.connect === false ? undefined : () => <g />}
              />
            ))}
            {lines.length > 1 && (
              // **위에 둔다** — 아래에 두면 가로축 이름(축 아래)과 같은 자리라 「4차」 위에
              // 「두께」 가 겹쳐 찍혔다(2026-10-24 화면).
              <Legend verticalAlign="top" height={28} wrapperStyle={{ fontSize: 12 }} />
            )}
            {drawn.length > 0 && (
              <Scatter
                name={yLabel}
                data={drawn}
                fill={colorAt(0)}
                onClick={(entry: unknown) => {
                  const row = entry as SpectrumPoint | undefined
                  if (onPick && row?.key) onPick(row)
                }}
              >
                {labelled && (
                  <LabelList dataKey="label" position="right" fontSize={10} fill={AXIS_COLOR} />
                )}
              </Scatter>
            )}
            <Tooltip
              cursor={{ strokeDasharray: '3 3' }}
              content={({ active, payload }) => (
                <Tip
                  active={active}
                  row={payload?.[0]?.payload as TipRow | undefined}
                  xLabel={xLabel}
                  yLabel={yLabel}
                />
              )}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      {flat && flatNote && <p className="text-muted-foreground mt-1 text-xs">{flatNote}</p>}
      {withStems && drawn.length > MAX_STEMS && (
        <p className="text-muted-foreground mt-1 text-xs">
          모드가 {drawn.length.toLocaleString()}개라 줄기는 생략하고 점만 표시합니다.
        </p>
      )}
    </div>
  )
}
