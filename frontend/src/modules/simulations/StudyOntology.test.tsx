/**
 * DOE 의 기준정보 — CompCore 가 이은 적용 모델 · 태그를 칩으로 보이고, 우리 온톨로지 사본에 있는
 * 객체만 그 객체로 잇는다. 그 전에 내보낸 폴더(빈 두 목록)는 아무것도 그리지 않는다.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { StudyOntology as Ontology } from '@/modules/simulations/api'
import { StudyOntology } from '@/modules/simulations/StudyOntology'

const ONTOLOGY: Ontology = {
  tags: [
    { object_id: 't1', key: '', label: '시제품', type_slug: 'cc_tag', type_label: '일반 태그', known: false },
    { object_id: 't2', key: 'C-1', label: '고객사 A', type_slug: 'customer', type_label: '고객사', known: false },
  ],
  links: [
    {
      object_id: 'o1',
      key: 'VM-001',
      label: '차종 X',
      type_slug: 'vehicle_model',
      type_label: '차종',
      known: true,
      on: { kind: 'part', id: 'p1', name: '브래킷' },
      relation: 'applies_to',
      relation_label: '적용 모델',
    },
  ],
}

function show(node: React.ReactNode) {
  return render(<MemoryRouter>{node}</MemoryRouter>)
}

describe('DOE 의 기준정보', () => {
  it('부품의 칸은 주인과 함께, 태그는 그 타입으로 — 우리 사본에 있는 것만 잇는다', () => {
    show(<StudyOntology ontology={ONTOLOGY} />)
    expect(screen.getByText(/브래킷 — 적용 모델/)).toBeDefined()
    const link = screen.getByRole('link', { name: '차종 X (VM-001)' })
    expect(link.getAttribute('href')).toBe('/ontology?type=vehicle_model&key=VM-001')
    // 「일반 태그」 는 「태그」 로, 다른 타입은 그 이름으로 — 둘 다 우리 사본에 없어 글자로만.
    expect(screen.getByText('태그')).toBeDefined()
    expect(screen.getByText('고객사')).toBeDefined()
    expect(screen.queryByRole('link', { name: /고객사 A/ })).toBeNull()
  })

  it('목록 한 줄에는 칸만 짧게', () => {
    show(<StudyOntology ontology={ONTOLOGY} compact />)
    expect(screen.getByText(/적용 모델/)).toBeDefined()
    expect(screen.queryByText('시제품')).toBeNull()
  })

  it('기준정보가 없는 옛 폴더는 그리지 않는다', () => {
    const { container } = show(<StudyOntology ontology={{ tags: [], links: [] }} />)
    expect(container.textContent).toBe('')
  })
})
