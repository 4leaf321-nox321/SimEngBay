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
      solvers: vi.fn(),
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
  materials: [],
  suggested_modes: null,
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
    vi.mocked(simulationApi.solvers).mockReset().mockResolvedValue([
      { solver: 'ansys', workers_alive: 1, queued: 0 },
      { solver: 'calculix', workers_alive: 0, queued: 2 },
    ])
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
    // 목록이 그려질 때까지 — 부르기만 하고 보면 아직 읽는 중이다.
    await screen.findByText('브래킷_튜닝-3f9a21')
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
    // 아무것도 안 고르면 모달 · Ansys 다(스펙의 기본값과 같다).
    expect((sent.spec as Record<string, unknown>).recipe).toBe('modal')
    expect((sent.spec as Record<string, unknown>).solver).toBe('ansys')
  })

  it('CAD 가 적은 해석 종류를 미리 고르고 그 스펙을 보낸다', async () => {
    // **모달로 못 박으면** 전단 이음 같은 정적 DOE 가 하중을 건너뛴 채 모달로 돈다.
    vi.mocked(simulationApi.previewDoe).mockResolvedValue({
      ...PREVIEW,
      suggested_recipe: 'static',
    })
    vi.mocked(simulationApi.importDoe).mockResolvedValue({
      study_id: '3f9a21',
      name: '브래킷_두께훑기',
      created: ['a'],
      skipped: [],
    })
    vi.mocked(simulationApi.browseDoe).mockResolvedValueOnce(STUDY_LISTING)
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    await waitFor(() =>
      expect((screen.getByLabelText('해석 종류') as HTMLSelectElement).value).toBe('static'),
    )
    expect(screen.getByText('CAD 가 적은 해석입니다.')).toBeDefined()
    // 정적에는 모드 수가 없다 — 칸도 안 보인다.
    expect(screen.queryByLabelText('모드 수')).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: /3건 실행/ }))
    await waitFor(() => expect(simulationApi.importDoe).toHaveBeenCalled())
    const spec = vi.mocked(simulationApi.importDoe).mock.calls[0][0].spec as Record<
      string,
      unknown
    >
    expect(spec.recipe).toBe('static')
    // **스펙이 모르는 칸은 서버가 통째로 거절한다** — 정적 스펙에 modes 를 실으면 400 이다.
    expect('modes' in spec).toBe(false)
  })

  it('CAD 와 다른 해석 종류를 고르면 그 사실을 말한다', async () => {
    vi.mocked(simulationApi.previewDoe).mockResolvedValue({
      ...PREVIEW,
      suggested_recipe: 'harmonic',
    })
    vi.mocked(simulationApi.browseDoe).mockResolvedValueOnce(STUDY_LISTING)
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    await waitFor(() =>
      expect((screen.getByLabelText('해석 종류') as HTMLSelectElement).value).toBe('harmonic'),
    )
    await userEvent.selectOptions(screen.getByLabelText('해석 종류'), 'modal')
    expect(screen.getByText(/CAD 가 적은 해석: 조화 응답/)).toBeDefined()
  })

  it('CalculiX 를 고르면 모든 점이 그 솔버로 간다', async () => {
    // 요소 크기를 비워 두면 **점마다 CAD 의 「전체」 크기**로 돈다 — 미리 채워 보내면 그 값이
    // 점마다 다른 힌트를 덮는다.
    vi.mocked(simulationApi.previewDoe).mockResolvedValue({
      ...PREVIEW,
      suggested_element_size_mm: 2.5,
    })
    vi.mocked(simulationApi.importDoe).mockResolvedValue({
      study_id: '3f9a21',
      name: '브래킷_두께훑기',
      created: ['a'],
      skipped: [],
    })
    vi.mocked(simulationApi.browseDoe).mockResolvedValueOnce(STUDY_LISTING)
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    await waitFor(() => expect(screen.getByPlaceholderText('CAD 값 2.5')).toBeDefined())

    await userEvent.selectOptions(screen.getByLabelText('솔버'), 'calculix')
    await userEvent.click(screen.getByRole('button', { name: /3건 실행/ }))
    await waitFor(() => expect(simulationApi.importDoe).toHaveBeenCalled())
    const spec = vi.mocked(simulationApi.importDoe).mock.calls[0][0].spec as Record<
      string,
      unknown
    >
    expect(spec.solver).toBe('calculix')
    expect(spec.mesh).toEqual({})
  })

  it('요소 크기가 어디에도 없으면 CalculiX 로 실행하지 않는다', async () => {
    // **설계점 수만큼 메시 실패가 쌓이기 전에** 막는다.
    vi.mocked(simulationApi.browseDoe).mockResolvedValueOnce(STUDY_LISTING)
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    await waitFor(() => expect(screen.getByRole('button', { name: /3건 실행/ })).toBeEnabled())

    await userEvent.selectOptions(screen.getByLabelText('솔버'), 'calculix')
    expect(screen.getByText(/CalculiX 는 요소 크기가 필요합니다/)).toBeDefined()
    expect(screen.getByRole('button', { name: /3건 실행/ })).toBeDisabled()

    await userEvent.type(screen.getByLabelText('요소 크기 (mm)'), '3')
    expect(screen.getByRole('button', { name: /3건 실행/ })).toBeEnabled()
  })

  /** CAD 가 재료를 함께 보낸 폴더. */
  const WITH_MATERIALS = { ...PREVIEW, materials: ['SS400', 'AL6061'] }

  it('CAD 가 보낸 재료를 보여 주고 그 값으로 돌린다', async () => {
    // **재료를 훑는 DOE 는 물성이 결과의 절반이다** — 화면이 말해 주지 않으면 사람은 이름만
    // 다른 결과를 받고도 모른다.
    vi.mocked(simulationApi.previewDoe).mockResolvedValue(WITH_MATERIALS)
    vi.mocked(simulationApi.importDoe).mockResolvedValue({
      study_id: '3f9a21',
      name: '브래킷_두께훑기',
      created: ['a'],
      skipped: [],
    })
    vi.mocked(simulationApi.browseDoe).mockResolvedValueOnce(STUDY_LISTING)
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    await waitFor(() => expect(screen.getByText(/SS400 · AL6061/)).toBeDefined())

    await userEvent.click(screen.getByRole('button', { name: /3건 실행/ }))
    await waitFor(() => expect(simulationApi.importDoe).toHaveBeenCalled())
    const sent = vi.mocked(simulationApi.importDoe).mock.calls[0][0]
    expect((sent.spec as Record<string, unknown>).material_from).toBe('cad')
  })

  it('끄면 사람이 넣은 값으로 돌린다', async () => {
    vi.mocked(simulationApi.previewDoe).mockResolvedValue(WITH_MATERIALS)
    vi.mocked(simulationApi.importDoe).mockResolvedValue({
      study_id: '3f9a21',
      name: '브래킷_두께훑기',
      created: ['a'],
      skipped: [],
    })
    vi.mocked(simulationApi.browseDoe).mockResolvedValueOnce(STUDY_LISTING)
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    await waitFor(() => expect(screen.getByText(/SS400 · AL6061/)).toBeDefined())

    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: /3건 실행/ }))
    await waitFor(() => expect(simulationApi.importDoe).toHaveBeenCalled())
    const sent = vi.mocked(simulationApi.importDoe).mock.calls[0][0]
    expect((sent.spec as Record<string, unknown>).material_from).toBe('spec')
  })

  it('CAD 가 적은 모드 수를 미리 채운다', async () => {
    // **조용히 쓰면 그쪽 기본값이 우리 것을 말없이 덮는다** — 채워 두고 사람이 고치게 한다.
    vi.mocked(simulationApi.previewDoe).mockResolvedValue({ ...PREVIEW, suggested_modes: 8 })
    vi.mocked(simulationApi.browseDoe).mockResolvedValueOnce(STUDY_LISTING)
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)

    await waitFor(() => expect(screen.getByText(/CAD 가 적은 값 8/)).toBeDefined())
    // 칸 채우기는 효과(effect)라 한 틱 뒤다 — 값이 바뀔 때까지 기다린다.
    await waitFor(() =>
      expect((screen.getByLabelText('모드 수') as HTMLInputElement).value).toBe('8'),
    )
  })

  it('물성을 안 보낸 폴더면 그 사실을 말한다', async () => {
    // 아무 말도 없으면 사람은 「CAD 값으로 돌았겠지」 로 읽는다.
    vi.mocked(simulationApi.browseDoe).mockResolvedValueOnce(STUDY_LISTING)
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    await waitFor(() => expect(screen.getByText(/물성을 보내지 않았습니다/)).toBeDefined())
    expect(screen.getByRole('checkbox')).toBeDisabled()
  })
  it('집을 워커가 없는 솔버를 고르면 미리 말한다', async () => {
    // **영원히 대기하는 작업을 거는 자리에서 막는다** — 걸고 나면 아무도 그 사실을 말하지 않는다.
    vi.mocked(simulationApi.browseDoe).mockResolvedValueOnce(STUDY_LISTING)
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    await waitFor(() => expect(screen.getByRole('button', { name: /3건 실행/ })).toBeEnabled())
    expect(screen.queryByText(/이 솔버를 집는 워커가 없습니다/)).toBeNull()

    await userEvent.selectOptions(screen.getByLabelText('솔버'), 'calculix')
    expect(screen.getByText(/이 솔버를 집는 워커가 없습니다/)).toBeDefined()
    expect(screen.getByText(/이미 2건 대기 중/)).toBeDefined()
  })

  it('서버가 워커를 모르면 경고하지 않는다', async () => {
    // 요청 안에서 도는 설치 · 옛 워커 — 「모른다」 를 「없다」 로 말하지 않는다.
    vi.mocked(simulationApi.solvers).mockResolvedValue([
      { solver: 'ansys', workers_alive: -1, queued: 0 },
      { solver: 'calculix', workers_alive: -1, queued: 0 },
    ])
    vi.mocked(simulationApi.browseDoe).mockResolvedValueOnce(STUDY_LISTING)
    render(<DoeImportDialog open onClose={() => {}} onImported={() => {}} />)
    await waitFor(() => expect(screen.getByRole('button', { name: /3건 실행/ })).toBeEnabled())
    await userEvent.selectOptions(screen.getByLabelText('솔버'), 'calculix')
    expect(screen.queryByText(/이 솔버를 집는 워커가 없습니다/)).toBeNull()
  })
})
