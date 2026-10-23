/**
 * DOE 를 **여러 그림으로** — 「변수 하나 대 결과 하나」 를 넘어서.
 *
 * 비교 탭은 가로축이 설계 변수 하나, 세로축이 결과다. 변수가 둘 이상이면 그 그림으로는 「두 변수를
 * 함께 움직이면 어떻게 되나 · 무엇이 결과를 가장 크게 움직이나 · 조건에 맞는 조합은 어디인가」 에
 * 답하지 못한다. 그림은 MechanicalDesign 의 DOE 결과 화면(3D 산점도 · 산점도 행렬 · 평행 좌표 · 상관
 * 히트맵)을 따르고, 해석 DOE 에 쓰는 둘(2변수 영향 등고선 · 주효과)을 더했다.
 *
 * 모든 그림이 **같은 표**를 본다(`studyTable.ts`) — 끝난 설계점만, 모달은 추적한 모드로.
 */

import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import type { Study, StudyPoint } from '@/modules/simulations/api'
import {
  columnsOf,
  correlation,
  gridOf,
  labelOf,
  mainEffect,
  numberOf,
  rowsOf,
} from '@/modules/simulations/studyTable'
import type { Column } from '@/modules/simulations/studyTable'
import { LazyPlot } from '@/shared/charts/LazyPlot'
import type { PlotTrace } from '@/shared/charts/LazyPlot'
import { Button } from '@/shared/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'

export type ExplorerView = 'scatter3d' | 'contour' | 'effects' | 'splom' | 'parallel' | 'correlation'

const VIEWS: { id: ExplorerView; label: string; hint: string }[] = [
  { id: 'scatter3d', label: '3D 산점도', hint: 'X · Y · Z · 색에 변수와 결과를 골라 놓는다' },
  {
    id: 'contour',
    label: '2변수 영향',
    hint: '숫자 설계 변수 둘을 함께 움직였을 때 결과 — 전 조합이면 등고선',
  },
  {
    id: 'effects',
    label: '주효과',
    hint: '설계 변수마다 수준별 결과의 평균(막대는 최소~최대) — 무엇이 결과를 가장 크게 움직이나',
  },
  { id: 'splom', label: '산점도 행렬', hint: '고른 열끼리 모든 짝의 산점도(최대 6)' },
  { id: 'parallel', label: '평행 좌표', hint: '축 위를 끌어 범위를 걸면 그 조합만 남는다' },
  { id: 'correlation', label: '상관', hint: '피어슨 상관계수 r — 1 에 가까우면 함께 오르고 −1 이면 반대로' },
]

/** 산점도 행렬에 한 번에 놓을 열 수 — 넘으면 칸이 너무 작아 읽히지 않는다. */
const MAX_SPLOM = 6
const SCALE = 'Viridis'

function hoverOf(point: StudyPoint): string {
  const params = Object.entries(point.params)
    .map(([key, value]) => `${key} ${value}`)
    .join(' · ')
  return `p${String(point.number).padStart(4, '0')}${params ? ` — ${params}` : ''}`
}

function Picker({
  label,
  value,
  columns,
  onChange,
}: {
  label: string
  value: string
  columns: Column[]
  onChange: (key: string) => void
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground w-10 shrink-0">{label}</span>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="w-56" aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {columns.map((column) => (
            <SelectItem key={column.key} value={column.key}>
              {column.kind === 'factor' ? '◆ ' : ''}
              {labelOf(column)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  )
}

function Note({ children }: { children: ReactNode }) {
  return <p className="text-muted-foreground rounded-md border border-dashed p-6 text-sm">{children}</p>
}

export function StudyExplorer({ study }: { study: Study }) {
  const rows = useMemo(() => rowsOf(study), [study])
  const columns = useMemo(() => columnsOf(study), [study])
  const numeric = columns.filter((one) => one.numeric)
  const factors = numeric.filter((one) => one.kind === 'factor')
  const results = numeric.filter((one) => one.kind === 'result')
  const byKey = (key: string) => columns.find((one) => one.key === key)

  const [view, setView] = useState<ExplorerView>('scatter3d')
  const [x, setX] = useState(factors[0]?.key ?? numeric[0]?.key ?? '')
  const [y, setY] = useState(factors[1]?.key ?? numeric[1]?.key ?? '')
  const [z, setZ] = useState(results[0]?.key ?? numeric[2]?.key ?? '')
  const [color, setColor] = useState(results[1]?.key ?? results[0]?.key ?? '')
  const [effectOf, setEffectOf] = useState(results[0]?.key ?? '')
  const [picked, setPicked] = useState<string[]>(() =>
    [...factors, ...results].slice(0, 4).map((one) => one.key),
  )

  if (rows.length < 3 || numeric.length < 2) {
    return (
      <Note>
        끝난 설계점이 셋 이상이고 숫자로 견줄 열이 둘 이상이어야 여러 그림으로 볼 수 있습니다(지금 끝난
        점 {rows.length}개).
      </Note>
    )
  }

  const values = (column: Column | undefined) =>
    rows.map((row) => (column ? numberOf(column, row) : null))
  const text = rows.map(hoverOf)

  function chart() {
    const cx = byKey(x)
    const cy = byKey(y)
    const cz = byKey(z)
    const cc = byKey(color)
    switch (view) {
      case 'scatter3d':
        return (
          <LazyPlot
            height={560}
            toolbar
            data={[
              {
                type: 'scatter3d',
                mode: 'markers',
                x: values(cx),
                y: values(cy),
                z: values(cz),
                text,
                hovertemplate: '%{text}<extra></extra>',
                marker: {
                  size: 5,
                  color: values(cc),
                  colorscale: SCALE,
                  showscale: true,
                  colorbar: { title: { text: cc ? labelOf(cc) : '' } },
                },
              },
            ]}
            layout={{
              showlegend: false,
              margin: { t: 8, r: 8, b: 8, l: 8 },
              scene: {
                xaxis: { title: { text: cx ? labelOf(cx) : '' } },
                yaxis: { title: { text: cy ? labelOf(cy) : '' } },
                zaxis: { title: { text: cz ? labelOf(cz) : '' } },
              },
            }}
          />
        )
      case 'contour': {
        if (factors.length < 2 || !cx || !cy || !cz)
          return <Note>숫자 설계 변수가 둘 이상인 DOE 에서 그릴 수 있습니다.</Note>
        const grid = gridOf(rows, cx, cy, cz)
        const points: PlotTrace = {
          type: 'scatter',
          mode: 'markers',
          x: values(cx),
          y: values(cy),
          text,
          hovertemplate: `%{text}<br>${labelOf(cz)} %{marker.color:.4g}<extra></extra>`,
          marker: grid
            ? { size: 7, color: values(cz), colorscale: SCALE, line: { width: 1, color: '#fff' } }
            : {
                size: 11,
                color: values(cz),
                colorscale: SCALE,
                showscale: true,
                colorbar: { title: { text: labelOf(cz) } },
              },
          showlegend: false,
        }
        return (
          <div className="space-y-2">
            {!grid && (
              <p className="text-muted-foreground text-xs">
                두 변수의 모든 조합이 다 있지 않아(무작위 · LHS 설계) 등고선 대신 색으로 그립니다 — 빈
                조합을 메워 그리면 없는 값을 지어내게 됩니다.
              </p>
            )}
            <LazyPlot
              height={520}
              toolbar
              data={
                grid
                  ? [
                      {
                        type: 'contour',
                        x: grid.xs,
                        y: grid.ys,
                        z: grid.z,
                        colorscale: SCALE,
                        contours: { coloring: 'heatmap', showlabels: true },
                        colorbar: { title: { text: labelOf(cz) } },
                        hovertemplate: `${labelOf(cx)} %{x}<br>${labelOf(cy)} %{y}<br>${labelOf(cz)} %{z:.4g}<extra></extra>`,
                      },
                      points,
                    ]
                  : [points]
              }
              layout={{
                xaxis: { title: { text: labelOf(cx) } },
                yaxis: { title: { text: labelOf(cy) } },
              }}
            />
          </div>
        )
      }
      case 'effects': {
        const target = byKey(effectOf)
        const each = columns.filter((one) => one.kind === 'factor')
        if (!target || each.length === 0) return <Note>설계 변수가 없습니다.</Note>
        return (
          <div className="grid gap-4 md:grid-cols-2">
            {each.map((factor) => {
              const effects = mainEffect(rows, factor, target)
              const spread = effects.length
                ? Math.max(...effects.map((one) => one.mean)) -
                  Math.min(...effects.map((one) => one.mean))
                : 0
              return (
                <div key={factor.key} className="rounded-md border p-2">
                  <p className="px-1 text-sm font-medium">
                    {factor.label}{' '}
                    <span className="text-muted-foreground text-xs">
                      — 평균의 폭 {spread.toPrecision(3)} {target.unit}
                    </span>
                  </p>
                  <LazyPlot
                    height={260}
                    data={[
                      {
                        type: 'scatter',
                        mode: factor.numeric ? 'lines+markers' : 'markers',
                        x: effects.map((one) => one.level),
                        y: effects.map((one) => one.mean),
                        error_y: {
                          type: 'data',
                          symmetric: false,
                          array: effects.map((one) => one.max - one.mean),
                          arrayminus: effects.map((one) => one.mean - one.min),
                        },
                        text: effects.map((one) => `${one.count}점`),
                        hovertemplate: `${factor.label} %{x}<br>평균 %{y:.4g} (%{text})<extra></extra>`,
                        showlegend: false,
                      },
                    ]}
                    layout={{
                      margin: { t: 8, r: 8, b: 40, l: 56 },
                      xaxis: {
                        title: { text: factor.label },
                        type: factor.numeric ? 'linear' : 'category',
                      },
                      yaxis: { title: { text: labelOf(target) } },
                    }}
                  />
                </div>
              )
            })}
          </div>
        )
      }
      case 'splom': {
        const chosen = picked.map(byKey).filter((one): one is Column => !!one && one.numeric)
        if (chosen.length < 2) return <Note>열을 둘 이상 고르세요.</Note>
        return (
          <LazyPlot
            height={Math.max(420, chosen.length * 150)}
            toolbar
            data={[
              {
                type: 'splom',
                dimensions: chosen.map((one) => ({ label: labelOf(one), values: values(one) })),
                text,
                hovertemplate: '%{text}<extra></extra>',
                marker: {
                  size: 5,
                  color: values(byKey(color)),
                  colorscale: SCALE,
                  showscale: true,
                },
                diagonal: { visible: false },
                showupperhalf: false,
              },
            ]}
            layout={{ showlegend: false, dragmode: 'select' }}
          />
        )
      }
      case 'parallel': {
        const dimensions = columns.map((one) => {
          if (one.numeric) return { label: labelOf(one), values: values(one) }
          // 고르는 값은 순번으로 놓고 이름을 적는다 — 축의 위아래는 뜻이 없다.
          const levels = [...new Set(rows.map((row) => String(one.value(row) ?? '—')))]
          return {
            label: one.label,
            values: rows.map((row) => levels.indexOf(String(one.value(row) ?? '—'))),
            tickvals: levels.map((_, index) => index),
            ticktext: levels,
          }
        })
        return (
          <LazyPlot
            height={480}
            toolbar
            data={[
              {
                type: 'parcoords',
                dimensions,
                line: {
                  color: values(byKey(color)),
                  colorscale: SCALE,
                  showscale: true,
                },
              },
            ]}
            layout={{ margin: { t: 48, r: 48, b: 24, l: 48 } }}
          />
        )
      }
      case 'correlation': {
        const labels = numeric.map(labelOf)
        const matrix = numeric.map((a) => numeric.map((b) => correlation(rows, a, b)))
        return (
          <LazyPlot
            height={Math.max(360, numeric.length * 44 + 120)}
            data={[
              {
                type: 'heatmap',
                x: labels,
                y: labels,
                z: matrix,
                zmin: -1,
                zmax: 1,
                colorscale: 'RdBu',
                reversescale: true,
                texttemplate: '%{z:.2f}',
                hovertemplate: '%{y} ↔ %{x}<br>r = %{z:.2f}<extra></extra>',
              },
            ]}
            layout={{
              margin: { t: 8, r: 8, b: 140, l: 180 },
              yaxis: { autorange: 'reversed' },
              showlegend: false,
            }}
          />
        )
      }
    }
  }

  const current = VIEWS.find((one) => one.id === view)
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="그림 고르기">
        {VIEWS.map((one) => (
          <Button
            key={one.id}
            size="sm"
            role="tab"
            aria-selected={view === one.id}
            variant={view === one.id ? 'default' : 'outline'}
            onClick={() => setView(one.id)}
          >
            {one.label}
          </Button>
        ))}
      </div>
      <p className="text-muted-foreground text-sm">
        {current?.hint} · 끝난 설계점 {rows.length}개 · ◆ 는 설계 변수
      </p>

      <div className="flex flex-wrap gap-3">
        {(view === 'scatter3d' || view === 'contour') && (
          <>
            <Picker
              label="X"
              value={x}
              columns={view === 'contour' ? factors : numeric}
              onChange={setX}
            />
            <Picker
              label="Y"
              value={y}
              columns={view === 'contour' ? factors : numeric}
              onChange={setY}
            />
            <Picker label={view === 'contour' ? '결과' : 'Z'} value={z} columns={numeric} onChange={setZ} />
          </>
        )}
        {(view === 'scatter3d' || view === 'splom' || view === 'parallel') && (
          <Picker label="색" value={color} columns={numeric} onChange={setColor} />
        )}
        {view === 'effects' && (
          <Picker label="결과" value={effectOf} columns={results} onChange={setEffectOf} />
        )}
      </div>

      {view === 'splom' && (
        <div className="flex flex-wrap gap-1.5">
          {numeric.map((one) => {
            const on = picked.includes(one.key)
            return (
              <Button
                key={one.key}
                size="sm"
                variant={on ? 'secondary' : 'ghost'}
                aria-pressed={on}
                disabled={!on && picked.length >= MAX_SPLOM}
                onClick={() =>
                  setPicked(on ? picked.filter((key) => key !== one.key) : [...picked, one.key])
                }
              >
                {one.kind === 'factor' ? '◆ ' : ''}
                {labelOf(one)}
              </Button>
            )
          })}
        </div>
      )}

      {chart()}
    </section>
  )
}
