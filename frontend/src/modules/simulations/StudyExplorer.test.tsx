/**
 * 「다변수」 탭 — 그림을 고르면 같은 표의 열이 그 그림의 축으로 간다. plotly 는 무거워 시험에서는
 * 받은 trace 만 본다.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const drawn: { data: Record<string, unknown>[] }[] = []
vi.mock('@/shared/charts/LazyPlot', () => ({
  LazyPlot: (props: { data: Record<string, unknown>[] }) => {
    drawn.push(props)
    return <div data-testid="plot">{String(props.data[0]?.type)}</div>
  },
}))

import type { Study, StudyPoint } from '@/modules/simulations/api'
import { StudyExplorer } from '@/modules/simulations/StudyExplorer'

function point(number: number, thickness: number, width: number, mm: number): StudyPoint {
  return {
    simulation_id: `s${number}`,
    number,
    params: { 두께: thickness, 폭: width },
    status: 'done',
    published: false,
    recipe: 'static',
    solver: 'calculix',
    frequencies: [],
    mass_kg: thickness * width * 0.01,
    max_displacement_mm: mm,
    max_von_mises_mpa: mm * 30,
    reactions_n: {},
    probes_mm: {},
    probe_vectors_mm: {},
    probe_peaks_hz: {},
    relative_mm: {},
  } as StudyPoint
}

function study(points: StudyPoint[]): Study {
  return {
    study_id: 's',
    name: '브래킷',
    factors: ['두께', '폭'],
    recipe: 'static',
    solvers: ['calculix'],
    points,
    published: 0,
    tracks: [],
  } as unknown as Study
}

const FULL = [point(1, 2, 10, 4), point(2, 3, 10, 3), point(3, 2, 20, 2), point(4, 3, 20, 1)]

describe('StudyExplorer', () => {
  beforeEach(() => {
    drawn.length = 0
  })

  it('처음은 3D 산점도 — X · Y 는 설계 변수, Z 는 첫 결과', () => {
    render(<StudyExplorer study={study(FULL)} />)
    expect(screen.getByTestId('plot').textContent).toBe('scatter3d')
    const trace = drawn.at(-1)!.data[0]
    expect(trace.x).toEqual([2, 3, 2, 3])
    expect(trace.y).toEqual([10, 10, 20, 20])
    expect(trace.z).toEqual([4, 3, 2, 1])
  })

  it('2변수 영향은 전 조합이면 등고선, 아니면 색 산점도로 말한다', () => {
    const { unmount } = render(<StudyExplorer study={study(FULL)} />)
    fireEvent.click(screen.getByRole('tab', { name: '2변수 영향' }))
    expect(drawn.at(-1)!.data[0].type).toBe('contour')
    unmount()

    render(<StudyExplorer study={study(FULL.slice(0, 3))} />)
    fireEvent.click(screen.getByRole('tab', { name: '2변수 영향' }))
    expect(drawn.at(-1)!.data[0].type).toBe('scatter')
    expect(screen.getByText(/등고선 대신 색으로/)).toBeInTheDocument()
  })

  it('주효과는 설계 변수마다 한 장 · 상관은 히트맵 하나 · 평행 좌표 · 산점도 행렬', () => {
    render(<StudyExplorer study={study(FULL)} />)
    fireEvent.click(screen.getByRole('tab', { name: '주효과' }))
    expect(screen.getAllByTestId('plot')).toHaveLength(2)
    fireEvent.click(screen.getByRole('tab', { name: '상관' }))
    expect(drawn.at(-1)!.data[0].type).toBe('heatmap')
    fireEvent.click(screen.getByRole('tab', { name: '평행 좌표' }))
    expect(drawn.at(-1)!.data[0].type).toBe('parcoords')
    fireEvent.click(screen.getByRole('tab', { name: '산점도 행렬' }))
    expect(drawn.at(-1)!.data[0].type).toBe('splom')
  })

  it('끝난 점이 셋 미만이면 그리지 않고 그렇다고 말한다', () => {
    render(<StudyExplorer study={study(FULL.slice(0, 2))} />)
    expect(screen.queryByTestId('plot')).toBeNull()
    expect(screen.getByText(/셋 이상/)).toBeInTheDocument()
  })
})
