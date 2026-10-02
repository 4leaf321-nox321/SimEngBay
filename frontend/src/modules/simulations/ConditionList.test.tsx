/**
 * 조건 목록 — **반영 · 넘김 · 막음**이 한눈에 갈리는가.
 *
 * 이 화면이 없던 동안 조건은 폴더까지 와서 조용히 버려졌다. 사람이 「압력을 줬는데 왜 결과가
 * 같지」 를 물을 자리가 여기다.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ConditionList } from '@/modules/simulations/ConditionList'

const CONDITIONS = {
  unit_system: 'mm_n_tonne',
  prestressed: false,
  lines: [
    { kind: 'constraint', label: '바닥 고정', detail: 'fixed_support · 바닥', status: 'applied', why: '' },
    { kind: 'contact', label: '판-블록', detail: 'bonded · 블록 아랫면 ↔ 판 윗면', status: 'applied', why: '' },
    {
      kind: 'load',
      label: '하중 「누름」(pressure)',
      detail: '',
      status: 'skipped',
      why: '모달에서는 하중이 고유진동수를 바꾸지 않습니다 — 선응력을 켜면 쓰입니다',
    },
  ],
} as const

describe('CAD 조건 목록', () => {
  it('반영한 것과 넘긴 것을 갈라 보여 준다', () => {
    render(<ConditionList conditions={{ ...CONDITIONS, lines: [...CONDITIONS.lines] }} />)

    expect(screen.getByText('바닥 고정')).toBeDefined()
    expect(screen.getAllByText('반영')).toHaveLength(2)
    // **넘긴 까닭을 같은 줄에서 읽는다** — 따로 찾게 하지 않는다.
    expect(screen.getByText('넘김')).toBeDefined()
    expect(screen.getByText(/고유진동수를 바꾸지 않습니다/)).toBeDefined()
    expect(screen.getByText(/단위계 mm_n_tonne/)).toBeDefined()
  })

  it('조건이 없으면 아무것도 그리지 않는다', () => {
    // 사람이 준 스펙으로 돈 작업 — 빈 칸을 보여 줄 이유가 없다.
    const { container } = render(
      <ConditionList conditions={{ lines: [], unit_system: '', prestressed: false }} />,
    )
    expect(container.firstChild).toBeNull()
  })
})
