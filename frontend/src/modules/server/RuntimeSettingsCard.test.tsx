/**
 * 서버 화면의 「해석 설정」 — 지금 값 · 어디서 왔나 · 언제 듣나를 보이고, 고치면 서버 설정으로 둔다.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { RuntimeSetting } from '@/shared/api/types'

const get = vi.hoisted(() => vi.fn())
const put = vi.hoisted(() => vi.fn())
const del = vi.hoisted(() => vi.fn())
vi.mock('@/shared/api/client', () => ({ api: { get, put, delete: del } }))

const BONDING: RuntimeSetting = {
  key: 'calculix_bonding',
  env: 'CALCULIX_BONDING',
  label: '본딩 방식',
  group: 'calculix',
  kind: 'choice',
  help: 'lever — 바디를 따로 메시하고 간극을 둔 채 구속식(기본).',
  choices: ['lever', 'tie', 'shared'],
  minimum: null,
  maximum: null,
  unit: '',
  default: 'lever',
  value: 'lever',
  source: 'default',
  server_value: null,
  env_value: null,
  problem: null,
  applies: 'new_jobs',
  updated_at: null,
  updated_by_name: null,
}
const POLL: RuntimeSetting = {
  ...BONDING,
  key: 'ste_poll_seconds',
  env: 'STE_POLL_SECONDS',
  label: 'STE 상태를 묻는 간격',
  group: 'ste',
  kind: 'number',
  help: '잡이 끝났나 묻는 간격.',
  choices: [],
  minimum: 1,
  maximum: 600,
  unit: '초',
  default: '15',
  value: '30',
  source: 'server',
  server_value: '30',
  env_value: '20',
  applies: 'next_stage',
  updated_at: '2026-11-25T01:00:00Z',
  updated_by_name: '관리자',
}

async function show(rows: RuntimeSetting[]) {
  get.mockResolvedValue(rows)
  const { RuntimeSettingsCard } = await import('@/modules/server/RuntimeSettingsCard')
  render(<RuntimeSettingsCard />)
}

describe('서버 화면 · 해석 설정', () => {
  beforeEach(() => vi.clearAllMocks())

  it('지금 값 · 출처 · 언제 듣나를 보인다', async () => {
    await show([BONDING, POLL])
    expect(await screen.findByText('본딩 방식')).toBeInTheDocument()
    expect(screen.getByText(/기본값 · 새로 거는 작업부터/)).toBeInTheDocument()
    expect(screen.getByText(/서버 설정 · 다음에 시작하는 단계부터/)).toBeInTheDocument()
    expect(screen.getByText(/지우면 \.env 의 20 초/)).toBeInTheDocument()
  })

  it('고르면 서버 설정으로 저장하고 다시 읽는다', async () => {
    await show([BONDING])
    put.mockResolvedValue({ ...BONDING, value: 'tie', source: 'server' })
    fireEvent.change(await screen.findByLabelText('본딩 방식'), { target: { value: 'tie' } })
    fireEvent.click(screen.getByRole('button', { name: '저장' }))
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith('/server/settings/calculix_bonding', { value: 'tie' }),
    )
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
  })

  it('서버 설정을 지우면 .env · 기본값으로 돌아간다', async () => {
    await show([POLL])
    del.mockResolvedValue({ ...POLL, value: '20', source: 'env' })
    fireEvent.click(await screen.findByRole('button', { name: '서버 설정 지우기' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('/server/settings/ste_poll_seconds'))
  })
})
