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
    simulationApi: {
      ...actual.simulationApi,
      browseDoe: vi.fn(),
      previewDoe: vi.fn(),
      importDoe: vi.fn(),
    },
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

/** 뿌리를 열었을 때 — 폴더 둘, 그중 하나가 DOE. */
const ROOT_LISTING = {
  path: '/data/doe',
  parent: null,
  roots: ['/data/doe'],
  truncated: false,
  is_study: false,
  entries: [
    { name: '브래킷_튜닝-3f9a21', path: '/data/doe/브래킷_튜닝-3f9a21', is_study: true },
    { name: '옛자료', path: '/data/doe/옛자료', is_study: false },
  ],
}

/** 그 DOE 폴더로 들어갔을 때. */
const STUDY_LISTING = {
  ...ROOT_LISTING,
  path: '/data/doe/브래킷_튜닝-3f9a21',
  parent: '/data/doe',
  is_study: true,
  entries: [{ name: 'points', path: '/data/doe/브래킷_튜닝-3f9a21/points', is_study: false }],
}

describe('DOE 가져오기', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.browseDoe).mockReset().mockResolvedValue(ROOT_LISTING)
    vi.mocked(simulationApi.previewDoe).mockReset().mockResolvedValue(PREVIEW)
    vi.mocked(simulationApi.importDoe).mockReset()
  })

  it('창을 열면 공용 폴더부터 보여 준다', async () => {
    // **경로를 외워서 치게 하지 않는다** — 아무것도 안 쳐도 고를 것이 있어야 한다.
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    await waitFor(() => expect(simulationApi.browseDoe).toHaveBeenCalled())
    expect(screen.getByText('브래킷_튜닝-3f9a21')).toBeDefined()
    expect(screen.getByText('옛자료')).toBeDefined()
    // 가져올 수 있는 폴더는 미리 표시한다 — 눌러 보고 알게 하지 않는다.
    expect(screen.getByText('DOE')).toBeDefined()
  })

  it('고르기 전에는 실행할 수 없다', async () => {
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    await waitFor(() => expect(simulationApi.browseDoe).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: /0건 실행/ })).toBeDisabled()
  })

  it('DOE 폴더로 들어가면 곧바로 훑어 본다', async () => {
    // 한 번 더 누르게 하지 않는다.
    vi.mocked(simulationApi.browseDoe).mockResolvedValueOnce(ROOT_LISTING)
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    await waitFor(() => expect(screen.getByText('브래킷_튜닝-3f9a21')).toBeDefined())

    vi.mocked(simulationApi.browseDoe).mockResolvedValueOnce(STUDY_LISTING)
    await userEvent.click(screen.getByText('브래킷_튜닝-3f9a21'))

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
    vi.mocked(simulationApi.browseDoe).mockResolvedValueOnce(STUDY_LISTING)
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
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
