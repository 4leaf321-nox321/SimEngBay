/**
 * 차트 껍데기가 지키는 것 — **빈 데이터는 빈 그림이 아니고, 그림에는 이름이 붙는다.**
 *
 * 도표의 픽셀은 여기서 안 본다(recharts 가 제 일을 한다). 여기서 지키는 것은 그
 * 바깥 — 데이터가 없을 때 무엇이 보이나, 화면 낭독기가 무엇을 읽나.
 */

import { cloneElement } from 'react'
import type { ReactElement } from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// happy-dom 에는 배치 엔진이 없어 `ResponsiveContainer` 가 0×0 을 재고 recharts 가
// 경고를 쏟는다. 크기를 아는 것으로 바꿔 끼운다 — **경고를 참고 사는 시험은 곧
// 아무도 안 읽는 시험이 된다.**
vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      cloneElement(children, { width: 400, height: 300 } as Record<string, unknown>),
  }
})

import { Chart } from '@/shared/charts'
import { logTicks } from '@/shared/charts/Chart'

const DATA = [
  { name: 'A', 건수: 3 },
  { name: 'B', 건수: 1 },
]

describe('Chart', () => {
  it('데이터가 없으면 축이 아니라 이유를 보여 준다', () => {
    // 축만 덩그러니 그리면 사람은 그것을 「0 이 여럿」 으로 읽는다.
    render(
      <Chart
        kind="bar"
        data={[]}
        x="name"
        series={[{ key: '건수' }]}
        emptyText="거른 것이 없습니다."
      />,
    )
    expect(screen.getByText('거른 것이 없습니다.')).toBeInTheDocument()
  })

  it('계열이 하나도 없어도 빈 그림을 안 그린다', () => {
    render(<Chart kind="line" data={DATA} x="name" series={[]} />)
    expect(screen.getByText('그릴 것이 없습니다.')).toBeInTheDocument()
  })

  it('그림에 이름을 붙인다 — 낭독기에는 이것만 들린다', () => {
    render(<Chart kind="bar" data={DATA} x="name" series={[{ key: '건수' }]} title="등급별 건수" />)
    expect(screen.getByRole('img', { name: '등급별 건수' })).toBeInTheDocument()
  })

  it('이름을 안 주면 계열 이름으로 대신한다', () => {
    render(
      <Chart
        kind="bar"
        data={DATA}
        x="name"
        series={[
          { key: '건수', label: '건수' },
          { key: 'x', label: '무게' },
        ]}
      />,
    )
    expect(screen.getByRole('img', { name: '건수, 무게 차트' })).toBeInTheDocument()
  })

  it('로그 축 눈금은 1 · 2 · 5 x 10ⁿ — 많으면 10ⁿ 만', () => {
    expect(logTicks(20, 2000)).toEqual([20, 50, 100, 200, 500, 1000, 2000])
    expect(logTicks(0.007, 16.9)).toEqual([0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10])
    expect(logTicks(1e-6, 1e3)).toEqual([1e-6, 1e-5, 1e-4, 0.001, 0.01, 0.1, 1, 10, 100, 1000])
    expect(logTicks(0.007, 16.9, 6)).toEqual([0.01, 0.1, 1, 10])
    expect(logTicks(0, 10)).toBeUndefined()
  })
})
