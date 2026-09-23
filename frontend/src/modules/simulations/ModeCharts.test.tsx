/**
 * 여러 그림 사이를 오가는 규칙.
 *
 * **눌러 보고 빈 그림을 만나지 않게 한다** — 못 그리는 그림은 왜 못 그리는지를 먼저 말한다.
 * 그 말이 곧 다음에 할 일이다(구속을 걸어라 · 모드 수를 늘려라).
 */

import { cloneElement } from 'react'
import type { ReactElement } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

// happy-dom 에는 배치 엔진이 없어 ResponsiveContainer 가 0x0 을 잰다(Chart.test 와 같은 이유).
vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      cloneElement(children, { width: 400, height: 300 } as Record<string, unknown>),
  }
})

import type { SimulationResult } from '@/modules/simulations/api'
import { ModeCharts } from '@/modules/simulations/ModeCharts'

function freeFree(): SimulationResult {
  return {
    recipe: 'modal',
    boundary: 'free-free',
    units: { frequency: 'Hz' },
    normalization: 'mass',
    rigid_body_modes: 1,
    modes: [
      { number: 1, elastic_number: null, frequency_hz: 0, rigid_body: true },
      { number: 2, elastic_number: 1, frequency_hz: 2583.1, rigid_body: false },
      { number: 3, elastic_number: 2, frequency_hz: 3315.2, rigid_body: false },
    ],
    participation: {},
  }
}

function constrained(): SimulationResult {
  return {
    ...freeFree(),
    boundary: 'constrained',
    rigid_body_modes: 0,
    modes: [
      {
        number: 1,
        elastic_number: 1,
        frequency_hz: 120.5,
        rigid_body: false,
        effective_mass_ratio: 0.62,
        dominant_direction: 'Y',
      },
      { number: 2, elastic_number: 2, frequency_hz: 480.2, rigid_body: false },
    ],
    participation: { X: { '1': 0.1, '2': 0.2 }, Y: { '1': 0.62, '2': 0.05 } },
  }
}

describe('모드 그림 고르기', () => {
  it('기본은 스펙트럼이다', () => {
    // 모드 번호 축의 막대는 늘 단조 증가하는 계단이라 표가 더 잘 답한다.
    render(<ModeCharts result={constrained()} />)
    expect(screen.getByRole('img', { name: /스펙트럼/ })).toBeDefined()
  })

  it('자유-자유에서는 누적 그림이 왜 없는지 말한다', async () => {
    render(<ModeCharts result={freeFree()} />)
    await userEvent.click(screen.getByRole('button', { name: '누적 유효질량' }))
    expect(screen.getByText(/강체 모드가 전부 가져갑니다/)).toBeDefined()
  })

  it('참여계수가 있으면 누적 곡선을 그린다', async () => {
    render(<ModeCharts result={constrained()} />)
    await userEvent.click(screen.getByRole('button', { name: '누적 유효질량' }))
    expect(screen.getByRole('img', { name: /누적 유효질량/ })).toBeDefined()
    // 방향 이름을 사람의 말로 적어 준다 — 범례와 아래 설명 둘 다에 나온다.
    expect(screen.getAllByText(/Y 이동/).length).toBeGreaterThan(0)
  })

  it('모드별 막대도 고를 수 있다', async () => {
    render(<ModeCharts result={constrained()} />)
    await userEvent.click(screen.getByRole('button', { name: '모드별' }))
    expect(screen.getByRole('img', { name: /모드별 고유진동수/ })).toBeDefined()
  })
})
