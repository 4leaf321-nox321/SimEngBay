/**
 * DOE 가져오기 — **먼저 보여 주고 나서 건다.**
 *
 * 200개를 잘못 걸면 되돌리기 어렵고, 그 사이 Mechanical 라이선스를 계속 문다. 그래서 훑어 보기
 * 전에는 실행 단추가 눌리지 않아야 하고, 걸 수 없는 점은 **이유가 보여야** 한다.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { simulationApi } from '@/modules/simulations/api'
import { DoeImportDialog } from '@/modules/simulations/DoeImportDialog'

vi.mock('@/modules/simulations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/simulations/api')>()
  return {
    ...actual,
    simulationApi: { ...actual.simulationApi, previewDoe: vi.fn(), importDoe: vi.fn() },
  }
})

vi.mock('@/shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: { home_workspace_slug: 'hq', memberships: [] } }),
}))

const PREVIEW = {
  path: '/data/doe/브래킷-3f9a21',
  study_id: '3f9a21',
  name: '브래킷_두께훑기',
  factors: ['두께'],
  method: 'full',
  seed: 1,
  usable: 3,
  skipped: 1,
  points: [
    { number: 1, params: { 두께: 6 }, usable: true, skip_reason: '' },
    { number: 2, params: { 두께: 12 }, usable: true, skip_reason: '' },
    { number: 3, params: { 두께: 20 }, usable: true, skip_reason: '' },
    { number: 4, params: { 두께: 26 }, usable: false, skip_reason: '벽이 판을 넘습니다' },
  ],
}

describe('DOE 가져오기', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.previewDoe).mockReset().mockResolvedValue(PREVIEW)
    vi.mocked(simulationApi.importDoe).mockReset()
  })

  it('훑어 보기 전에는 실행할 수 없다', () => {
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    expect(screen.getByRole('button', { name: /0건 실행/ })).toBeDisabled()
  })

  it('훑어 보면 점과 변수와 건너뛸 이유를 보여 준다', async () => {
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    await userEvent.type(screen.getByLabelText('폴더 경로'), '/data/doe/x')
    await userEvent.click(screen.getByRole('button', { name: '훑어 보기' }))

    await waitFor(() => expect(screen.getByText('브래킷_두께훑기')).toBeDefined())
    expect(screen.getByText(/벽이 판을 넘습니다/)).toBeDefined()
    expect(screen.getByRole('button', { name: /3건 실행/ })).toBeEnabled()
  })

  it('모든 점에 같은 스펙을 보낸다', async () => {
    // **그래야 결과를 견줄 수 있다** — 그러려고 DOE 를 돌린다.
    vi.mocked(simulationApi.importDoe).mockResolvedValue({
      study_id: '3f9a21',
      name: '브래킷_두께훑기',
      created: ['a', 'b', 'c'],
      skipped: [],
    })
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    await userEvent.type(screen.getByLabelText('폴더 경로'), '/data/doe/x')
    await userEvent.click(screen.getByRole('button', { name: '훑어 보기' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /3건 실행/ })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /3건 실행/ }))

    await waitFor(() => expect(simulationApi.importDoe).toHaveBeenCalled())
    const sent = vi.mocked(simulationApi.importDoe).mock.calls[0][0]
    expect(sent.path).toBe(PREVIEW.path)
    expect((sent.spec as Record<string, unknown>).constraints).toEqual([
      { region: 'bolt_holes', kind: 'fixed' },
    ])
  })
})
