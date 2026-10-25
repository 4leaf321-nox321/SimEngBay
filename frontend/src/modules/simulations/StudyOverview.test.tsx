/**
 * 개요 화면 — **한 장으로 본다.**
 *
 * 모드를 하나씩 눌러 봐야 아는 화면은 「전반적으로 어떤가」 에 답하지 못한다. 여기서 지키는
 * 것은 그 한 장에 무엇이 있어야 하는가다: 변화의 크기 · 모드 전부 · 고를 후보 · 못 이은 자리.
 */

import { cloneElement } from 'react'
import type { ReactElement } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
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
  published: 0,
  name: '브래킷_두께훑기',
  factors: ['두께'],
  recipe: 'modal',
  solvers: ['ansys'],
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
      published: false,
      recipe: 'modal',
      solver: 'ansys',
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
      published: false,
      recipe: 'modal',
      solver: 'ansys',
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
      published: false,
      recipe: 'modal',
      solver: 'ansys',
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
    show()
    const matrix = screen.getByText('설계점 × 모드 (Hz)').closest('section') as HTMLElement
    const lastRow = matrix.querySelectorAll('tbody tr')[2]
    expect(lastRow.textContent).toContain('1,713')
    expect(lastRow.textContent).not.toContain('3,374') // 2차를 못 이었다
  })

  it('못 이은 자리에는 까닭과 할 일을 적는다 — 닮은 정도로 가른다', () => {
    // 2차 · p0003 은 닮은 정도 0.41 — 닮았지만 문턱(0.6) 아래: 모양이 바뀐 것, 형상을 직접 본다.
    show()
    const matrix = screen.getByText('설계점 × 모드 (Hz)').closest('section') as HTMLElement
    const gap = matrix.querySelectorAll('tbody tr')[2].querySelector('[title]') as HTMLElement
    expect(gap.title).toContain('닮은 정도 0.41')
    expect(gap.title).toContain('모드 형상을 직접 보세요')
    const note = within(matrix).getByLabelText('못 이은 자리')
    expect(note.textContent).toContain('2차 — 1점에서 닮은 모드가 있지만 확실하지 않습니다')
    expect(screen.getByText(/선이 끊긴 자리의 까닭과 할 일은/)).toBeDefined()
  })

  it('구한 모드 안에 닮은 것이 아예 없으면 — 모드 수를 늘려 다시 걸라고(위의 단추로, 지우지 않고)', () => {
    // 실측(외팔보 두께 × 폭): 폭 방향 2차 굽힘이 폭 20 이상에서 6번째 위로 밀려나 닮은 정도 0.01.
    show({
      ...STUDY,
      tracks: [
        STUDY.tracks![0],
        { reference: 2, numbers: { 1: 2, 2: 3 }, confidence: { 2: 0.99, 3: 0.01 } },
      ],
    })
    const matrix = screen.getByText('설계점 × 모드 (Hz)').closest('section') as HTMLElement
    const note = within(matrix).getByLabelText('못 이은 자리')
    expect(note.textContent).toContain('2차 — 1점에서 구한 모드(3개) 안에 닮은 모양이 없습니다')
    expect(note.textContent).toContain('10개로 늘리면 이어질 수 있습니다')
    expect(note.textContent).toContain('「모드 수 바꿔 다시 걸기」')
    expect(note.textContent).toContain('옛 결과는 기록으로 남습니다')
  })

  it('지문이 없는 옛 스터디도 그린다', () => {
    // 모드 지도는 비지만 요약과 트레이드오프는 그대로 읽힌다 — 질량과 1차는 요약에 있다.
    show({ ...STUDY, tracks: [], reference_point: null })
    expect(screen.getByText('6 → 20')).toBeDefined()
    expect(screen.getByRole('img', { name: /질량 대 주파수/ })).toBeDefined()
    // **빈 까닭을 맞게 말한다** — 점은 다 끝났다. 「차례로 돕니다」 는 기다리라는 거짓말이다.
    expect(screen.getByText(/모드 지문이 없는 작업이라 모드를 잇지 못합니다/)).toBeDefined()
    expect(screen.queryByText(/설계점이 차례로 돕니다/)).toBeNull()
    // 고를 모드가 없으면 빈 고르기 칸을 두지 않고, 무엇을 그렸는지 적는다.
    const trade = screen.getByText('질량 대 주파수', { selector: 'h2' }).closest('section') as HTMLElement
    expect(within(trade).queryByRole('combobox')).toBeNull()
    expect(screen.getByText('1차 탄성 모드')).toBeDefined()
  })
})

describe('설계 변수가 여럿', () => {
  /** 두께 · 폭 2 x 2 — 끝 점 둘(p1 · p4)은 두께도 폭도 다르다. */
  const TWO: Study = {
    ...STUDY,
    factors: ['두께', '폭'],
    tracks: [{ reference: 1, numbers: { 1: 1, 2: 1, 3: 1, 4: 1 }, confidence: {} }],
    points: [
      { ...STUDY.points[0], number: 1, simulation_id: 'a', params: { 두께: 6, 폭: 20 }, frequencies: [1000], mass_kg: 0.5 },
      { ...STUDY.points[1], number: 2, simulation_id: 'b', params: { 두께: 12, 폭: 20 }, frequencies: [1600], mass_kg: 1.0 },
      { ...STUDY.points[2], number: 3, simulation_id: 'c', params: { 두께: 6, 폭: 40 }, frequencies: [1100], mass_kg: 1.0 },
      { ...STUDY.points[2], number: 4, simulation_id: 'd', params: { 두께: 12, 폭: 40 }, frequencies: [1700], mass_kg: 2.0 },
    ],
  }

  it('끝 점 둘을 견주지 않는다 — 변수마다 범위, 결과의 최소 ~ 최대와 그 점, 영향 순위', () => {
    show(TWO)
    // 「6 → 12 · +70%」 는 폭까지 다른 두 점의 차이라 두께의 효과가 아니다.
    expect(screen.queryByText(/→/)).toBeNull()
    expect(screen.getByText('설계 변수 2개')).toBeDefined()
    expect(screen.getByText('6 ~ 12')).toBeDefined()
    expect(screen.getByText('20 ~ 40')).toBeDefined()
    // 1차 모드도 질량도 p0001 이 가장 작고 p0004 가 가장 크다.
    expect(screen.getAllByText(/최소 p0001 · 최대 p0004/)).toHaveLength(2)
    // 1차 모드: 두께 수준 평균 1050 · 1650 → 폭 600 ÷ 평균 1350 = 44%(r 0.98 ↑). 폭: 1300 · 1400 →
    // 7% — 상관이 약해(r 0.16) 방향을 붙이지 않는다.
    const ranking = screen.getByText('가장 크게 움직인 변수').parentElement as HTMLElement
    expect(ranking.textContent).toContain('1차 모드 ← 두께 44% ↑ › 폭 7%질량')
  })

  it('선은 나머지 변수를 고정한 단면만 — 처음 가로축은 1차를 가장 크게 움직이는 변수', () => {
    // 변수 차례는 두께 · 폭이지만 그것과 상관없이 두께(44%)가 폭(7%)보다 1차를 크게 움직인다.
    show({ ...TWO, factors: ['폭', '두께'] })
    expect(screen.getByText('가로축').parentElement?.textContent).toContain('두께')
    const fixed = screen.getByLabelText<HTMLSelectElement>('나머지 고정')
    // 단면은 폭 = 20 · 폭 = 40, 처음은 가운데(앞쪽).
    expect([...fixed.options].map((one) => one.text)).toEqual(['폭 = 20', '폭 = 40', '고정 안 함 — 점만'])
    expect(screen.getByText(/폭 = 20 인 점 2개만 잇습니다/)).toBeDefined()

    // 고정을 풀면 잇지 않는다 — 같은 두께에 폭이 다른 설계가 쌓인다.
    fireEvent.change(fixed, { target: { value: '' } })
    expect(screen.getByText(/잇지 않고 점만 찍습니다/)).toBeDefined()
    expect(screen.getByText(/색 하나가 모드 하나 — 잇지 않음/)).toBeDefined()
  })

  it('가로축이 재료면 단면마다 막대를, 고정을 풀면 막대마다 설계점을 붙인다고 말한다', () => {
    // 재료가 1차를 크게(1000 대 1600), 두께가 조금(1000 대 1100) 움직인다 — 처음 가로축이 재료다.
    const point = (number: number, 재료: string, 두께: number, hz: number) => ({
      ...STUDY.points[0],
      number,
      simulation_id: `m${number}`,
      params: { 재료, 두께 },
      frequencies: [hz],
      mass_kg: 1,
    })
    show({
      ...STUDY,
      factors: ['두께', '재료'],
      tracks: [{ reference: 1, numbers: { 1: 1, 2: 1, 3: 1, 4: 1 }, confidence: {} }],
      points: [
        point(1, 'AL6061', 6, 1000),
        point(2, 'SS400', 6, 1600),
        point(3, 'AL6061', 12, 1100),
        point(4, 'SS400', 12, 1700),
      ],
    })
    expect(screen.getByRole('img', { name: /값별 모드 고유진동수/ })).toBeDefined()
    const fixed = screen.getByLabelText<HTMLSelectElement>('나머지 고정')
    expect([...fixed.options].map((one) => one.text)).toEqual([
      '두께 = 6',
      '두께 = 12',
      '고정 안 함 — 점마다 막대',
    ])
    expect(screen.getByText(/두께 = 6 인 점 2개만 재료 마다 막대로 놓습니다/)).toBeDefined()
    fireEvent.change(fixed, { target: { value: '' } })
    expect(screen.getByText(/막대마다 설계점을 붙입니다/)).toBeDefined()
  })

  it('표에는 변수를 모두 적는다 — 가로축 하나만 적으면 같은 값의 줄들이 구별되지 않는다', () => {
    show(TWO)
    const matrix = screen.getByText('설계점 × 모드 (Hz)').closest('section') as HTMLElement
    const head = matrix.querySelector('thead')?.textContent ?? ''
    expect(head).toContain('두께')
    expect(head).toContain('폭')
  })
})

describe('최적점 찾기', () => {
  const matrixRow = (index: number) => {
    const matrix = screen.getByText('설계점 × 모드 (Hz)').closest('section') as HTMLElement
    return matrix.querySelectorAll('tbody tr')[index]
  }

  it('처음은 예전 후보와 같다 — 1차 크게 · 질량 작게의 파레토', () => {
    show()
    const panel = screen.getByRole('region', { name: '최적점 찾기' })
    expect(within(panel).getByText(/두 목표 모두에서 더 나은 점이 없는/)).toBeDefined()
    expect(matrixRow(0).textContent).toContain('후보')
  })

  it('목표를 하나로 줄이고 조건을 걸면 그 안에서 「최적」 하나', () => {
    show()
    const panel = screen.getByRole('region', { name: '최적점 찾기' })
    fireEvent.click(within(panel).getByRole('button', { name: '목표 2 빼기' }))
    // 1차 크게 → p0003(1,713 Hz). 질량 1.5 kg 이하만 → p0002(1,651 Hz).
    expect(matrixRow(2).textContent).toContain('최적')
    fireEvent.click(within(panel).getByRole('button', { name: /조건/ }))
    fireEvent.change(within(panel).getByLabelText('조건 1 열'), { target: { value: 'mass_kg' } })
    fireEvent.change(within(panel).getByLabelText('조건 1 비교'), { target: { value: '<=' } })
    fireEvent.change(within(panel).getByLabelText('조건 1 값'), { target: { value: '1.5' } })
    expect(within(panel).getByText(/조건을 만족한 점/).textContent).toContain('2 / 3')
    expect(within(panel).getByText(/p0002 — 조건 안에서 「1차 모드」 최대/)).toBeDefined()
    expect(matrixRow(1).textContent).toContain('최적')
    expect(matrixRow(2).textContent).not.toContain('최적')
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
