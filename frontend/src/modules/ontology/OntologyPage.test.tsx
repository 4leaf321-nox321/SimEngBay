/**
 * 온톨로지 — **받아 둔 사본을 읽기만 한다.** 설정이 없으면 무엇을 적어야 하는지 말하고, 「지금
 * 받기」 는 시스템 관리자에게만 있고, 타입을 고르면 그 객체와 선이 보인다.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ontologyApi } from '@/modules/ontology/api'
import type { OntologyObjectDetail, OntologyStatus, OntologyType } from '@/modules/ontology/api'
import OntologyPage from '@/modules/ontology/OntologyPage'

const auth = vi.hoisted(() => ({ admin: true }))

vi.mock('@/shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: { is_system_admin: auth.admin, memberships: [] } }),
}))

vi.mock('@/modules/ontology/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/ontology/api')>()
  return {
    ...actual,
    ontologyApi: {
      status: vi.fn(),
      types: vi.fn(),
      runs: vi.fn(),
      objects: vi.fn(),
      object: vi.fn(),
      sync: vi.fn(),
      setEnabled: vi.fn(),
    },
  }
})

const AT = '2026-10-13T01:00:00Z'

const STATUS: OntologyStatus = {
  configured: true,
  source: 'https://sp.example.com/api',
  sync_minutes: 1440,
  full_days: 7,
  next_due_at: '2026-10-14T01:00:00Z',
  running: null,
  last_run: {
    id: 'r1',
    trigger: 'timer',
    full: false,
    status: 'ok',
    revision: '3-0481920033',
    summary: { types: { material: { rows: 3, created: 3 } } },
    error: '',
    actor_name: null,
    started_at: AT,
    finished_at: AT,
  },
  revision: '3-0481920033',
  types: 1,
  objects: 3,
  relations: 1,
}

const MATERIAL: OntologyType = {
  slug: 'material',
  label: '재료',
  properties: [
    { key: 'density', label: '밀도', data_type: 'number', unit: 'kg/m3' },
    { key: 'supplier', label: '공급사', data_type: 'object_ref', ref_type_slug: 'vendor', multi: false },
  ],
  relations: ['supplied_by'],
  source_count: 3,
  active_count: 3,
  inactive_count: 0,
  relation_count: 1,
  published: true,
  enabled: true,
  synced_at: AT,
  full_at: AT,
  last_error: '',
}

const SS400: OntologyObjectDetail = {
  type_slug: 'material',
  key: 'SS400',
  label: '일반구조용강',
  status: 'active',
  properties: { density: 7850, supplier: 'ACME-001' },
  active: true,
  removed_reason: '',
  merged_into: null,
  previous_keys: [],
  source_updated_at: AT,
  synced_at: AT,
  ref_labels: { 'ACME-001': 'ACME 정밀' },
  outgoing: [
    {
      relation: 'supplied_by',
      src_type: 'material',
      src_key: 'SS400',
      src_label: '일반구조용강',
      dst_type: 'vendor',
      dst_key: 'ACME-001',
      dst_label: 'ACME 정밀',
      evidence_note: '',
      properties: {},
    },
  ],
  incoming: [],
}

function show(at = '/ontology') {
  return render(
    <MemoryRouter initialEntries={[at]}>
      <OntologyPage />
    </MemoryRouter>,
  )
}

describe('온톨로지', () => {
  beforeEach(() => {
    auth.admin = true
    vi.mocked(ontologyApi.status).mockReset().mockResolvedValue(STATUS)
    vi.mocked(ontologyApi.types).mockReset().mockResolvedValue([MATERIAL])
    vi.mocked(ontologyApi.runs).mockReset().mockResolvedValue([STATUS.last_run!])
    vi.mocked(ontologyApi.objects)
      .mockReset()
      .mockResolvedValue({ items: [SS400], total: 1, limit: 50, offset: 0 })
    vi.mocked(ontologyApi.object).mockReset().mockResolvedValue(SS400)
    vi.mocked(ontologyApi.sync).mockReset().mockResolvedValue({ ...STATUS.last_run!, status: 'running' })
  })

  it('설정이 없으면 무엇을 적어야 하는지 말한다', async () => {
    vi.mocked(ontologyApi.status).mockResolvedValue({ ...STATUS, configured: false, last_run: null })
    vi.mocked(ontologyApi.types).mockResolvedValue([])
    show()
    await waitFor(() => expect(screen.getByText(/연결이 설정되지 않았습니다\./)).toBeDefined())
    expect(screen.getAllByText('ONTOLOGY_SOURCE_TOKEN').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: '지금 받기' })).toBeNull()
  })

  it('시스템 관리자는 지금 받을 수 있고, 다른 사람에게는 버튼이 없다', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: '지금 받기' }))
    expect(ontologyApi.sync).toHaveBeenCalledWith(false)
    await userEvent.click(screen.getByRole('button', { name: '처음부터 전량 받기' }))
    expect(ontologyApi.sync).toHaveBeenCalledWith(true)
  })

  it('관리자가 아니면 받기 버튼도 받나 칸도 없다', async () => {
    auth.admin = false
    show()
    await screen.findByText('재료')
    expect(screen.queryByRole('button', { name: '지금 받기' })).toBeNull()
    expect(screen.queryByRole('checkbox', { name: '재료 받기' })).toBeNull()
  })

  it('타입을 고르면 객체가 나오고, 객체를 열면 칸과 선이 보인다', async () => {
    show()
    await userEvent.click(await screen.findByText('재료'))
    // 칸은 카탈로그의 이름과 단위로 보이고, 참조 칸은 받아 둔 이름을 함께 보인다.
    expect(await screen.findByText('7850 kg/m3')).toBeDefined()
    expect(screen.getByText('ACME 정밀 (ACME-001)')).toBeDefined()
    await userEvent.click(screen.getByText('SS400'))
    expect(await screen.findByText('나가는 선')).toBeDefined()
    // 표 · 칸 · 선 — 공급사 이름이 세 자리에 보인다.
    expect(screen.getAllByText(/ACME 정밀/).length).toBeGreaterThan(2)
    expect(ontologyApi.object).toHaveBeenCalledWith('material', 'SS400')
  })

  it('주소에 타입 · 식별자가 있으면 그 객체를 바로 연다(DOE 의 기준정보에서 온다)', async () => {
    show('/ontology?type=material&key=SS400')
    expect(await screen.findByText('나가는 선')).toBeDefined()
    expect(ontologyApi.object).toHaveBeenCalledWith('material', 'SS400')
  })

  it('받나를 끄면 그 타입을 안 받게 한다', async () => {
    show()
    await userEvent.click(await screen.findByRole('checkbox', { name: '재료 받기' }))
    expect(ontologyApi.setEnabled).toHaveBeenCalledWith('material', false)
  })
})
