/**
 * 개요 화면 — **한 장으로 본다.**
 *
 * 모드를 하나씩 눌러 봐야 아는 화면은 「전반적으로 어떤가」 에 답하지 못한다. 여기서 지키는
 * 것은 그 한 장에 무엇이 있어야 하는가다: 변화의 크기 · 모드 전부 · 고를 후보 · 못 이은 자리.
 */

import { cloneElement } from 'react'
import type { ReactElement } from 'react'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      cloneElement(children, { width: 400, height: 300 } as Record<string, unknown>),
  }
})

import type { Study } from '@/modules/simulations/api'
import { StudyOverview } from '@/modules/simulations/StudyOverview'

/** 실측에서 나온 모양 — 두께를 올리면 1차는 조금 오르고 질량은 크게 는다. */
const STUDY: Study = {
  study_id: '3f9a21',
  name: '브래킷_두께훑기',
  factors: ['두께'],
  reference_point: 1,
  tracks: [
    { reference: 1, numbers: { 1: 1, 2: 1, 3: 1 }, confidence: { 2: 0.99, 3: 0.95 } },
    // 2차는 t=20 에서 닮은 모드를 못 찾았다 — 그 자리는 비운다.
    { reference: 2, numbers: { 1: 2, 2: 3 }, confidence: { 2: 0.99, 3: 0.41 } },
  ],
  points: [
    {
      simulation_id: 'a',
      number: 1,
      params: { 두께: 6 },
      status: 'done',
      first_elastic_hz: 1336,
      mass_kg: 0.743,
      nodes: 3901,
      frequencies: [1336, 1698, 2238],
    },
    {
      simulation_id: 'b',
      number: 2,
      params: { 두께: 12 },
      status: 'done',
      first_elastic_hz: 1651,
      mass_kg: 1.185,
      nodes: 4102,
      frequencies: [1651, 3313, 3613],
    },
    {
      simulation_id: 'c',
      number: 3,
      params: { 두께: 20 },
      status: 'done',
      first_elastic_hz: 1713,
      mass_kg: 1.773,
      nodes: 4300,
      frequencies: [1713, 3374, 5284],
    },
  ],
}

function show(study: Study = STUDY) {
  return render(
    <MemoryRouter>
      <StudyOverview study={study} />
    </MemoryRouter>,
  )
}

describe('DOE 개요', () => {
  it('무엇을 얼마나 바꿨더니 무엇이 얼마나 변했는지 한 줄로 말한다', () => {
    show()
    expect(screen.getByText('6 → 20')).toBeDefined()
    expect(screen.getByText(/\+28%/)).toBeDefined() // 1336 → 1713
    expect(screen.getByText(/\+139%/)).toBeDefined() // 0.743 → 1.773 kg
  })

  it('모드 전부를 한 그림에 놓는다', () => {
    // **하나씩 눌러 보게 하지 않는다** — 그러면 「전반적으로」 를 못 읽는다.
    show()
    expect(screen.getByRole('img', { name: /모드별 고유진동수/ })).toBeDefined()
  })

  it('고를 가치가 있는 점을 짚어 준다', () => {
    // 파레토 — 더 가볍고 더 단단한 점이 없는 설계점.
    show()
    expect(screen.getAllByText('후보').length).toBeGreaterThan(0)
  })

  it('못 이은 모드 자리는 비운다', () => {
    // 숫자를 채우면 그 값이 같은 모드로 읽힌다.
    const { container } = show()
    const lastRow = container.querySelectorAll('tbody tr')[2]
    expect(lastRow.textContent).toContain('1,713')
    expect(lastRow.textContent).not.toContain('3,374') // 2차를 못 이었다
  })

  it('지문이 없는 옛 스터디도 그린다', () => {
    // 모드 지도는 비지만 요약과 트레이드오프는 그대로 읽힌다 — 질량과 1차는 요약에 있다.
    show({ ...STUDY, tracks: [], reference_point: null })
    expect(screen.getByText('6 → 20')).toBeDefined()
    expect(screen.getByRole('img', { name: /질량 대 주파수/ })).toBeDefined()
  })
})

describe('숫자가 아닌 변수', () => {
  /** 재료처럼 **고르는 인자** — CompCore 가 물성 DOE 를 붙이면서 들어온다. */
  const BY_MATERIAL: Study = {
    ...STUDY,
    name: '재료훑기',
    factors: ['재료'],
    points: [
      { ...STUDY.points[0], number: 1, params: { 재료: 'SS400' }, mass_kg: 1.42 },
      { ...STUDY.points[1], number: 2, params: { 재료: 'AL6061' }, mass_kg: 0.49 },
    ],
  }

  it('값 사이를 잇지 않는다', () => {
    // 선은 「그 중간이 있다」 는 말인데 재료에는 중간이 없다 — 막대로 그린다.
    show(BY_MATERIAL)
    expect(screen.getByRole('img', { name: /값별 모드 고유진동수/ })).toBeDefined()
    expect(screen.queryByRole('img', { name: /설계 변수에 따른/ })).toBeNull()
    expect(screen.getByText(/그 중간이 없기 때문/)).toBeDefined()
  })

  it('요약은 범위가 아니라 목록으로 적는다', () => {
    show(BY_MATERIAL)
    expect(screen.getByText('SS400 · AL6061')).toBeDefined()
  })

  it('표에는 고른 값이 그대로 보인다', () => {
    // **버리면 두 설계점이 똑같아 보인다** — 왜 결과가 다른지 알 방법이 없어진다.
    const { container } = show(BY_MATERIAL)
    expect(container.textContent).toContain('SS400')
    expect(container.textContent).toContain('AL6061')
  })

  it('질량 대 주파수는 그대로 읽힌다', () => {
    // 고르는 인자든 숫자든 트레이드오프의 두 축은 늘 숫자다.
    show(BY_MATERIAL)
    expect(screen.getByRole('img', { name: /질량 대 주파수/ })).toBeDefined()
  })
})
