/**
 * 새 해석 작업 — **설계 하나든 DOE 든 같은 창이다.** 체크가 실행할 점, 행이 오른쪽에 볼 점이다.
 *
 * 전에는 「DOE 가져오기」 창이 따로 있었다(같은 폴더 · 같은 서버 길, 다른 것은 점의 수뿐). 이 시험이
 * 두 창의 시험을 합친 것이다 — 하나면 이름을 받고 상세로, 여럿이면 같은 스펙으로 만들고 목록으로.
 *
 * 점 파일을 올리면(또는 폴더의 점을 보면) 서버가 읽은 것을 보여 주고, CAD 값이 먼저라는 것을 스펙에
 * 그대로 싣는다. 물성 칸은 없고 **파트마다 붙을 재료**를 보인다 — 물성은 CompCore 가 파트마다 정한다.
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { simulationApi } from '@/modules/simulations/api'
import type { ConditionsPreview } from '@/modules/simulations/api'
import { NewSimulationDialog } from '@/modules/simulations/NewSimulationDialog'

vi.mock('@/modules/simulations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/simulations/api')>()
  return {
    ...actual,
    simulationApi: {
      ...actual.simulationApi,
      previewConditions: vi.fn(),
      create: vi.fn(),
      solvers: vi.fn(),
      browseDoe: vi.fn(),
      previewDoe: vi.fn(),
      previewDoePoint: vi.fn(),
      importDoe: vi.fn(),
      get: vi.fn(),
    },
  }
})

vi.mock('@/shared/auth/AuthContext', () => ({
  useAuth: () => ({
    user: {
      home_workspace_slug: 'hq',
      is_system_admin: false,
      memberships: [{ slug: 'hq', name: '본부', role: 'member' }],
    },
  }),
}))

/** CompCore 전단 이음 p0002 를 서버가 읽은 모양에서 추렸다. */
const SHEAR: ConditionsPreview = {
  recipe: 'static',
  regions: [
    { name: '당기는 끝', count: 1, kind: 'face' },
    { name: '이음 입구 위판', count: 1, kind: 'point' },
  ],
  unresolved: [],
  bodies: [
    { name: '아래판', volume_mm3: 30000, material: 'SS400', suppressed: false, shell: false, setting: '' },
    { name: '위판', volume_mm3: 30000, material: 'AL6061', suppressed: false, shell: false, setting: '' },
  ],
  materials: [
    { name: 'SS400', bodies: ['아래판'], youngs_modulus_gpa: 206, poisson_ratio: 0.3, density_kg_m3: 7850 },
    { name: 'AL6061', bodies: ['위판'], youngs_modulus_gpa: 68.9, poisson_ratio: 0.33, density_kg_m3: 2700 },
  ],
  material_error: '',
  suggested_recipe: 'static',
  suggested_modes: null,
  suggested_element_size_mm: 2.5,
  conditions: {
    lines: [
      { kind: 'constraint', label: '당김', detail: 'displacement · 당기는 끝 · 면 1', status: 'applied', why: '' },
      { kind: 'load', label: '클램프', detail: 'force 10000 N', status: 'applied', why: '' },
    ],
    unit_system: 'mm_n_tonne',
    prestressed: false,
    drives: false,
  },
}

function step(): File {
  return new File(['ISO-10303-21;'], '시편.step', { type: 'model/step' })
}

function point(): File {
  return new File(['{"regions": {}}'], 'p0002.json', { type: 'application/json' })
}

/** 파일 직접 업로드 쪽 — 공용 폴더에 없는 파일용. */
async function open() {
  render(<NewSimulationDialog open onClose={() => {}} onCreated={() => {}} onImported={() => {}} />)
  await userEvent.click(screen.getByRole('tab', { name: '파일 직접 업로드' }))
  await userEvent.upload(screen.getByLabelText('형상 파일 (STEP)'), step())
}

const ROOT = { path: '/data/doe', parent: null, roots: ['/data/doe'], truncated: false, is_study: false, entries: [] }

function folderOf(single: boolean) {
  return {
    path: '/data/doe/브래킷_해석-1a2b',
    study_id: '1a2b',
    name: '브래킷_해석',
    factors: single ? [] : ['두께'],
    single,
    method: 'factorial',
    usable: single ? 1 : 2,
    skipped: 0,
    materials: ['SS400'],
    points: single
      ? [{ number: 1, params: {}, usable: true, skip_reason: '' }]
      : [
          { number: 1, params: { 두께: 2 }, usable: true, skip_reason: '' },
          { number: 2, params: { 두께: 3 }, usable: true, skip_reason: '' },
        ],
  }
}

async function openWithPoint() {
  await open()
  await userEvent.upload(screen.getByLabelText('CAD 점 파일 (pNNNN.json)'), point())
  await waitFor(() => expect(screen.getByText('클램프')).toBeDefined())
}

/** 뿌리를 열었을 때 — CAD 폴더 둘과 일반 폴더 하나. */
const ROOT_LISTING = {
  ...ROOT,
  entries: [
    { name: '브래킷_해석-1a2b', path: '/data/doe/브래킷_해석-1a2b', is_study: true },
    { name: '브래킷_튜닝-3f9a21', path: '/data/doe/브래킷_튜닝-3f9a21', is_study: true },
    { name: '옛자료', path: '/data/doe/옛자료', is_study: false },
  ],
}

/** 설계점 넷(그중 하나는 못 거는) DOE 폴더. */
const DOE = {
  path: '/data/doe/브래킷_튜닝-3f9a21',
  study_id: '3f9a21',
  name: '브래킷_두께훑기',
  factors: ['두께'],
  single: false,
  method: 'full',
  seed: 1,
  usable: 3,
  skipped: 1,
  materials: ['SS400', 'AL6061'],
  suggested_modes: null,
  points: [
    { number: 1, params: { 두께: 6 }, usable: true, skip_reason: '' },
    { number: 2, params: { 두께: 12 }, usable: true, skip_reason: '' },
    { number: 3, params: { 두께: 20 }, usable: true, skip_reason: '' },
    { number: 4, params: { 두께: 26 }, usable: false, skip_reason: '벽이 판을 넘습니다' },
  ],
}

/** 창이 CAD 폴더 자체에서 열린다 — 창은 그 위를 목록으로 두고 그것을 고른다. */
function openAt(folder: { path: string } & Record<string, unknown>, imported: (result: unknown) => void = () => {}) {
  vi.mocked(simulationApi.browseDoe)
    .mockResolvedValueOnce({ ...ROOT, path: folder.path, parent: '/data/doe', is_study: true })
    .mockResolvedValue(ROOT_LISTING)
  vi.mocked(simulationApi.previewDoe).mockResolvedValue(folder as never)
  render(<NewSimulationDialog open onClose={() => {}} onCreated={() => {}} onImported={imported} />)
}

describe('새 해석 작업', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.previewConditions).mockReset().mockResolvedValue(SHEAR)
    vi.mocked(simulationApi.create).mockReset().mockResolvedValue({ id: 'new' } as never)
    vi.mocked(simulationApi.solvers).mockReset().mockResolvedValue([])
    vi.mocked(simulationApi.browseDoe).mockReset().mockResolvedValue(ROOT)
    vi.mocked(simulationApi.previewDoe).mockReset()
    vi.mocked(simulationApi.previewDoePoint).mockReset().mockResolvedValue(SHEAR)
    vi.mocked(simulationApi.importDoe)
      .mockReset()
      .mockResolvedValue({ study_id: '1a2b', name: '브래킷_해석', created: ['made'], skipped: [] })
    vi.mocked(simulationApi.get).mockReset().mockResolvedValue({ id: 'made' } as never)
  })

  it('CAD 폴더의 설계 하나를 선택해 실행한다 — 파일 셋이 폴더에서 짝이 맞게 따라온다', async () => {
    // CompCore v0.9.0 「해석용으로 내보내기」 — 인자 0개 폴더가 설계 하나다.
    vi.mocked(simulationApi.browseDoe).mockResolvedValue({ ...ROOT, path: folderOf(true).path, is_study: true })
    vi.mocked(simulationApi.previewDoe).mockResolvedValue(folderOf(true) as never)
    const created = vi.fn()
    const imported = vi.fn()
    render(<NewSimulationDialog open onClose={() => {}} onCreated={created} onImported={imported} />)
    await waitFor(() => expect(screen.getByText('설계 하나')).toBeDefined())
    await waitFor(() => expect(screen.getByText('클램프')).toBeDefined())
    expect(simulationApi.previewDoePoint).toHaveBeenCalledWith(folderOf(true).path, 1, undefined)
    // 폴더에서 오면 파일 칸이 안 보인다(탭을 오가도 고른 파일이 남게 숨겨만 둔다).
    expect(screen.getByLabelText('형상 파일 (STEP)').closest('[hidden]')).not.toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '실행' }))
    await waitFor(() => expect(created).toHaveBeenCalled())
    const sent = vi.mocked(simulationApi.importDoe).mock.calls[0][0]
    expect(sent.path).toBe(folderOf(true).path)
    expect(sent.numbers).toEqual([1])
    expect('material' in sent.spec).toBe(false)
    expect(simulationApi.get).toHaveBeenCalledWith('made')
    expect(imported).not.toHaveBeenCalled()
  })

  it('왼쪽은 설계점 목록, 고르면 오른쪽에 그 점의 조건이 나온다', async () => {
    // **고르기 전에는 오른쪽이 비어 있다** — 무엇의 조건인지 모르는 설정 칸을 먼저 보이지 않는다.
    const { unmount } = render(
      <NewSimulationDialog open onClose={() => {}} onCreated={() => {}} onImported={() => {}} />,
    )
    const empty = await screen.findByRole('region', { name: '조건 · 설정' })
    await waitFor(() => expect(within(empty).getByText(/CAD 폴더를 선택하면/)).toBeDefined())
    expect(within(empty).queryByLabelText('해석 종류')).toBeNull()
    unmount()

    openAt(DOE)
    const left = screen.getByRole('region', { name: '설계점 목록' })
    const right = screen.getByRole('region', { name: '조건 · 설정' })
    await waitFor(() => expect(within(right).getByText('클램프')).toBeDefined())
    expect(within(left).getByRole('checkbox', { name: 'p0002 선택' })).toBeDefined()
    expect(within(left).getByRole('button', { name: 'p0001 보기', pressed: true })).toBeDefined()
    expect(within(right).getByLabelText('해석 종류')).toBeDefined()
    expect(within(right).getByText(/p0001/)).toBeDefined()
  })

  it('CAD 폴더를 고르면 목록은 그 자리에 두고, 옆 폴더로 바로 바꾼다', async () => {
    // **들어가지 않는다** — 옆 폴더로 바꾸려고 위로 올라가지 않게.
    vi.mocked(simulationApi.browseDoe).mockResolvedValue(ROOT_LISTING)
    vi.mocked(simulationApi.previewDoe).mockResolvedValue(DOE as never)
    render(<NewSimulationDialog open onClose={() => {}} onCreated={() => {}} onImported={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: /브래킷_튜닝-3f9a21/ }))
    await waitFor(() => expect(screen.getByText('브래킷_두께훑기')).toBeDefined())
    expect(simulationApi.previewDoe).toHaveBeenCalledWith('/data/doe/브래킷_튜닝-3f9a21')
    expect(simulationApi.browseDoe).toHaveBeenCalledTimes(1)
    expect(screen.getByText('옛자료')).toBeDefined()
    expect(screen.getByRole('button', { name: /브래킷_튜닝-3f9a21/, pressed: true })).toBeDefined()
    // 걸 수 없는 점은 까닭과 함께 보인다.
    expect(screen.getByText(/벽이 판을 넘습니다/)).toBeDefined()
  })

  it('DOE 폴더면 걸 수 있는 점을 전부 골라 열고, 같은 스펙으로 여러 건을 만든다', async () => {
    // **그래야 결과를 견줄 수 있다** — 그러려고 DOE 를 돌린다.
    vi.mocked(simulationApi.importDoe).mockResolvedValue({
      study_id: '3f9a21',
      name: '브래킷_두께훑기',
      created: ['a', 'b', 'c'],
      skipped: [],
    })
    const imported = vi.fn()
    openAt(DOE, imported)
    await waitFor(() => expect(screen.getByRole('button', { name: '3건 실행' })).toBeEnabled())
    // 여러 건이면 이름은 점마다 붙는다 — 칸이 없다.
    expect(screen.queryByLabelText('이름')).toBeNull()
    expect(screen.getByText(/선택한 3건에 같게 적용합니다/)).toBeDefined()
    await userEvent.click(screen.getByRole('button', { name: '3건 실행' }))

    await waitFor(() => expect(imported).toHaveBeenCalled())
    const sent = vi.mocked(simulationApi.importDoe).mock.calls[0][0]
    expect(sent.path).toBe(DOE.path)
    // 다 고른 것이면 보내지 않는다 — 서버가 「걸 수 있는 전부」 로 받는다.
    expect(sent.numbers).toBeNull()
    expect(sent.name).toBeNull()
    // CAD 가 적은 해석 종류(정적)를 미리 고른다 — 정적 스펙에 modes 를 실으면 서버가 거절한다.
    const spec = sent.spec as Record<string, unknown>
    expect(spec.recipe).toBe('static')
    expect('modes' in spec).toBe(false)
    expect(simulationApi.get).not.toHaveBeenCalled()
  })

  it('고른 설계점만 보낸다 — 걸 수 없는 점은 고를 수 없다', async () => {
    const imported = vi.fn()
    openAt(DOE, imported)
    await waitFor(() => expect(screen.getByRole('button', { name: '3건 실행' })).toBeEnabled())
    expect(screen.getByRole('checkbox', { name: 'p0004 선택' })).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: 'p0002 선택' }))
    await userEvent.click(screen.getByRole('button', { name: '2건 실행' }))
    await waitFor(() => expect(imported).toHaveBeenCalled())
    expect(vi.mocked(simulationApi.importDoe).mock.calls[0][0].numbers).toEqual([1, 3])
  })

  it('하나만 고르면 이름을 받고 그 작업의 상세로 간다', async () => {
    const created = vi.fn()
    vi.mocked(simulationApi.browseDoe)
      .mockResolvedValueOnce({ ...ROOT, path: DOE.path, parent: '/data/doe', is_study: true })
      .mockResolvedValue(ROOT_LISTING)
    vi.mocked(simulationApi.previewDoe).mockResolvedValue(DOE as never)
    render(<NewSimulationDialog open onClose={() => {}} onCreated={created} onImported={() => {}} />)
    await waitFor(() => expect(screen.getByText('클램프')).toBeDefined())
    // 행(점 이름)을 누르면 그 점을 본다 — 지금 고른 해석 종류로 읽는다.
    await userEvent.click(screen.getByRole('button', { name: 'p0002 보기' }))
    await waitFor(() => expect(simulationApi.previewDoePoint).toHaveBeenLastCalledWith(DOE.path, 2, 'static'))
    // 보기는 실행할 점을 바꾸지 않는다 — 체크로 고른다.
    await userEvent.click(screen.getByRole('checkbox', { name: '설계점 전체 선택' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'p0002 선택' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '실행' })).toBeEnabled())
    await userEvent.type(screen.getByLabelText('이름'), '두께 12 확인')
    await userEvent.click(screen.getByRole('button', { name: '실행' }))
    await waitFor(() => expect(created).toHaveBeenCalled())
    const sent = vi.mocked(simulationApi.importDoe).mock.calls[0][0]
    expect(sent.numbers).toEqual([2])
    expect(sent.name).toBe('두께 12 확인')
  })

  it('가져오지 못하면 그 까닭을 보인다', async () => {
    vi.mocked(simulationApi.browseDoe).mockResolvedValue({ ...ROOT, path: folderOf(true).path, is_study: true })
    vi.mocked(simulationApi.previewDoe).mockResolvedValue(folderOf(true) as never)
    vi.mocked(simulationApi.importDoe).mockResolvedValue({
      study_id: '1a2b',
      name: '브래킷_해석',
      created: [],
      skipped: [{ number: 1, params: {}, usable: false, skip_reason: '이미 가져온 점입니다.' }],
    })
    render(<NewSimulationDialog open onClose={() => {}} onCreated={() => {}} onImported={() => {}} />)
    await waitFor(() => expect(screen.getByRole('button', { name: '실행' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: '실행' }))
    await waitFor(() => expect(screen.getByText(/이미 가져온 점입니다/)).toBeDefined())
  })

  it('여러 점이면 폴더의 재료를 함께 말한다', async () => {
    // **재료를 훑는 DOE 는 물성이 결과의 절반이다** — 화면이 말해 주지 않으면 사람은 이름만 다른
    // 결과를 받고도 모른다.
    openAt(DOE)
    await waitFor(() => expect(screen.getByText(/이 폴더: SS400 · AL6061/)).toBeDefined())
    expect(screen.queryByLabelText('재료 이름')).toBeNull()
  })

  it('물성을 안 보낸 폴더는 실행하지 않는다', async () => {
    openAt({ ...DOE, materials: [] })
    await waitFor(() => expect(screen.getByText(/이 폴더는 물성을 보내지 않았습니다/)).toBeDefined())
    expect(screen.getByRole('button', { name: '3건 실행' })).toBeDisabled()
  })

  it('CalculiX 를 고르면 모든 점이 그 솔버로 가고, 비운 요소 크기는 점마다 CAD 값을 쓴다', async () => {
    // 미리 채워 보내면 그 값이 점마다 다른 힌트를 덮는다.
    openAt(DOE)
    await waitFor(() => expect(screen.getByPlaceholderText('CAD 값 2.5')).toBeDefined())
    await userEvent.selectOptions(screen.getByLabelText('솔버'), 'calculix')
    await userEvent.click(screen.getByRole('button', { name: '3건 실행' }))
    await waitFor(() => expect(simulationApi.importDoe).toHaveBeenCalled())
    const spec = vi.mocked(simulationApi.importDoe).mock.calls[0][0].spec as Record<string, unknown>
    expect(spec.solver).toBe('calculix')
    expect(spec.mesh).toEqual({ order: 'quadratic' })
  })

  it('CAD 가 적은 모드 수를 미리 채운다', async () => {
    // **조용히 쓰면 그쪽 기본값이 우리 것을 말없이 덮는다** — 채워 두고 사람이 고치게 한다.
    vi.mocked(simulationApi.previewDoePoint).mockResolvedValue({
      ...SHEAR,
      recipe: 'modal',
      suggested_recipe: 'modal',
      suggested_modes: 8,
    })
    openAt(DOE)
    await waitFor(() => expect(screen.getByText(/CAD 가 적은 값 8/)).toBeDefined())
    expect((screen.getByLabelText('탄성 모드 수') as HTMLInputElement).value).toBe('8')
  })

  it('해석 종류를 바꾸면 보는 점의 조건을 그 종류로 다시 읽는다', async () => {
    openAt(DOE)
    await waitFor(() => expect(screen.getByText('클램프')).toBeDefined())
    await userEvent.selectOptions(screen.getByLabelText('해석 종류'), 'modal')
    await waitFor(() => expect(simulationApi.previewDoePoint).toHaveBeenLastCalledWith(DOE.path, 1, 'modal'))
  })

  it('늦게 온 앞 점의 답이 지금 보는 점의 조건을 덮지 않는다', async () => {
    // 점을 빨리 넘기면 앞 물음의 답이 뒤에 온다 — 그대로 쓰면 p0003 을 보면서 p0002 조건을 본다.
    const third = {
      ...SHEAR,
      conditions: { ...SHEAR.conditions, lines: [{ ...SHEAR.conditions.lines[1], label: '셋째 점 하중' }] },
    }
    const second = {
      ...SHEAR,
      conditions: { ...SHEAR.conditions, lines: [{ ...SHEAR.conditions.lines[1], label: '둘째 점 하중' }] },
    }
    let answerSecond: (found: ConditionsPreview) => void = () => {}
    openAt(DOE)
    await waitFor(() => expect(screen.getByText('클램프')).toBeDefined())
    vi.mocked(simulationApi.previewDoePoint).mockImplementation((_path, number) =>
      number === 2
        ? new Promise((resolve) => {
            answerSecond = resolve
          })
        : Promise.resolve(number === 3 ? third : SHEAR),
    )
    await userEvent.click(screen.getByRole('button', { name: 'p0002 보기' }))
    await userEvent.click(screen.getByRole('button', { name: 'p0003 보기' }))
    await waitFor(() => expect(screen.getByText('셋째 점 하중')).toBeDefined())
    answerSecond(second)
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.queryByText('둘째 점 하중')).toBeNull()
    expect(screen.getByText('셋째 점 하중')).toBeDefined()
  })

  it('파일 업로드 쪽에 갔다 돌아오면 보던 점의 조건을 다시 보인다', async () => {
    openAt(DOE)
    await waitFor(() => expect(screen.getByText('클램프')).toBeDefined())
    await userEvent.click(screen.getByRole('tab', { name: '파일 직접 업로드' }))
    expect(screen.queryByText('클램프')).toBeNull()
    await userEvent.click(screen.getByRole('tab', { name: 'CAD 폴더에서 선택' }))
    await waitFor(() => expect(screen.getByText('클램프')).toBeDefined())
    expect(simulationApi.previewDoePoint).toHaveBeenLastCalledWith(DOE.path, 1, 'static')
  })

  it('집을 워커가 없는 솔버를 고르면 미리 말한다', async () => {
    // **영원히 대기하는 작업을 거는 자리에서 막는다** — 걸고 나면 아무도 그 사실을 말하지 않는다.
    // 기본은 CalculiX(2026-10-08) — 그 워커는 있고, Ansys 를 집는 워커가 없다.
    vi.mocked(simulationApi.solvers).mockResolvedValue([
      { solver: 'calculix', workers_alive: 1, queued: 0 },
      { solver: 'ansys', workers_alive: 0, queued: 2 },
    ])
    openAt(DOE)
    await waitFor(() => expect(screen.getByRole('button', { name: '3건 실행' })).toBeEnabled())
    expect(screen.queryByText(/이 솔버를 집는 워커가 없습니다/)).toBeNull()
    await userEvent.selectOptions(screen.getByLabelText('솔버'), 'ansys')
    expect(screen.getByText(/이 솔버를 집는 워커가 없습니다/)).toBeDefined()
    expect(screen.getByText(/이미 2건 대기 중/)).toBeDefined()
  })

  it('서버가 워커를 모르면 경고하지 않는다', async () => {
    // 요청 안에서 도는 설치 · 옛 워커 — 「모른다」 를 「없다」 로 말하지 않는다.
    vi.mocked(simulationApi.solvers).mockResolvedValue([
      { solver: 'ansys', workers_alive: -1, queued: 0 },
      { solver: 'calculix', workers_alive: -1, queued: 0 },
    ])
    openAt(DOE)
    await waitFor(() => expect(screen.getByRole('button', { name: '3건 실행' })).toBeEnabled())
    await userEvent.selectOptions(screen.getByLabelText('솔버'), 'calculix')
    expect(screen.queryByText(/이 솔버를 집는 워커가 없습니다/)).toBeNull()
  })

  it('걸 수 없는 CAD 조건이 있으면 실행하지 않고, CAD 조건을 끄면 실행한다', async () => {
    // CompCore 가 「바닥」 을 면으로 선언하고 엣지 지문을 실은 폴더 — 전에는 「반영」 으로 지나가고
    // 모델링에서야 멈췄다(2026-10-05). 서버도 만들 때 거절한다(SIMULATIONS-0030).
    vi.mocked(simulationApi.previewConditions).mockResolvedValue({
      ...SHEAR,
      conditions: {
        ...SHEAR.conditions,
        lines: [
          {
            kind: 'constraint',
            label: '구속 「고정」',
            detail: '',
            status: 'refused',
            why: '「바닥」 을 CAD 는 면으로 선언했는데 지문은 엣지(edge) 15개로 왔습니다',
          },
          ...SHEAR.conditions.lines,
        ],
      },
    })
    await openWithPoint()
    expect(screen.getByText(/걸 수 없는\(막음\) CAD 조건이 있어 이대로는 실행하지 않습니다/)).toBeDefined()
    expect(screen.getByRole('button', { name: '실행' })).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: /CAD 가 보낸 조건 사용/ }))
    // CAD 조건을 끄면 CAD 의 요소 크기도 안 쓴다 — 기본 솔버 CalculiX 는 크기를 받아야 돈다.
    await userEvent.type(screen.getByLabelText('요소 크기 (mm)'), '2.5')
    expect(screen.getByRole('button', { name: '실행' })).toBeEnabled()
  })

  it('점 파일이 없으면 실행하지 않는다 — 물성이 거기서 온다', async () => {
    await open()
    expect(screen.getByText(/CAD 점 파일이 있어야 실행합니다/)).toBeDefined()
    expect(screen.queryByLabelText('재료 이름')).toBeNull()
    expect(screen.getByRole('button', { name: '실행' })).toBeDisabled()
  })

  it('물성이 없는 점 파일이면 실행하지 않는다', async () => {
    vi.mocked(simulationApi.previewConditions).mockResolvedValue({ ...SHEAR, bodies: [], materials: [] })
    await openWithPoint()
    expect(screen.getByText(/이 점 파일에는 물성이 없습니다/)).toBeDefined()
    expect(screen.getByRole('button', { name: '실행' })).toBeDisabled()
  })

  it('점 파일을 올리면 서버가 읽은 조건 · 물성 · 해석 종류를 보여 준다', async () => {
    await openWithPoint()
    // 조건마다 반영 · 넘김 · 막음 — 서버가 판정한 그대로.
    expect(screen.getByText('클램프')).toBeDefined()
    expect(screen.getByText(/측정점/)).toBeDefined()
    // CAD 가 적은 해석 종류를 미리 고른다.
    expect((screen.getByLabelText('해석 종류') as HTMLSelectElement).value).toBe('static')
    expect(screen.getByPlaceholderText('CAD 값 2.5')).toBeDefined()
    // **파트마다 붙을 재료**를 보인다 — 물성 칸은 없다.
    expect(screen.getByRole('cell', { name: '아래판' })).toBeDefined()
    expect(screen.getByRole('cell', { name: 'AL6061' })).toBeDefined()
    expect(screen.getByRole('cell', { name: '68.9' })).toBeDefined()
    expect(screen.queryByLabelText('재료 이름')).toBeNull()
  })

  it('재료가 빠진 파트가 있으면 실행하지 않는다', async () => {
    // 모델링이 그 자리에서 멈춘다 — 사람이 지정한 한 벌로 메우지 않는다.
    vi.mocked(simulationApi.previewConditions).mockResolvedValue({
      ...SHEAR,
      bodies: [
        { name: '아래판', material: 'SS400', suppressed: false, shell: false, setting: '' },
        { name: '볼트', suppressed: false, shell: false, setting: '' },
      ],
    })
    await open()
    await userEvent.upload(screen.getByLabelText('CAD 점 파일 (pNNNN.json)'), point())
    await waitFor(() => expect(screen.getByText(/재료가 지정되지 않은 파트가 있습니다: 볼트/)).toBeDefined())
    expect(screen.getByText('재료 없음')).toBeDefined()
    expect(screen.getByRole('button', { name: '실행' })).toBeDisabled()
  })

  it('해석에서 뺀 파트는 재료가 없어도 실행하고, 파트 설정을 보여 준다', async () => {
    // CompCore 의 파트별 설정(body_settings) — 뺀 파트는 메시에도 안 나오므로 물성이 필요 없다.
    vi.mocked(simulationApi.previewConditions).mockResolvedValue({
      ...SHEAR,
      bodies: [
        { name: '아래판', material: 'SS400', suppressed: false, shell: false, setting: '강체' },
        { name: '위판', material: 'AL6061', suppressed: false, shell: false, setting: '' },
        { name: '표시나사', suppressed: true, shell: false, setting: '해석 제외' },
      ],
    })
    await openWithPoint()
    expect(screen.getByText('해석에서 제외')).toBeDefined()
    expect(screen.getByRole('cell', { name: '강체' })).toBeDefined()
    expect(screen.queryByText(/재료가 지정되지 않은 파트/)).toBeNull()
    expect(screen.getByRole('button', { name: '실행' })).toBeEnabled()
  })

  it('CAD 가 「전체」 에 적은 요소 차수를 미리 채운다', async () => {
    vi.mocked(simulationApi.previewConditions).mockResolvedValue({ ...SHEAR, suggested_order: 'linear' })
    await openWithPoint()
    expect((screen.getByLabelText('요소 차수') as HTMLSelectElement).value).toBe('linear')
    await userEvent.click(screen.getByRole('button', { name: '실행' }))
    await waitFor(() => expect(simulationApi.create).toHaveBeenCalled())
    const spec = vi.mocked(simulationApi.create).mock.calls[0][0].spec as Record<string, any>
    expect(spec.mesh.order).toBe('linear')
  })

  it('쉘 파트가 있으면 중간면 형상을 받아야 실행한다', async () => {
    // CompCore 의 쉘 파트(body_settings representation: shell) — 중간면 + 두께로 푼다.
    vi.mocked(simulationApi.previewConditions).mockResolvedValue({
      ...SHEAR,
      bodies: [
        { name: '아래판', material: 'SS400', suppressed: false, shell: false, setting: '강체' },
        { name: '위판', material: 'AL6061', suppressed: false, shell: true, setting: '변형체 · 쉘 2 mm' },
      ],
    })
    await openWithPoint()
    expect(screen.getByText(/쉘 파트\(위판\)는 중간면과 두께로 풉니다/)).toBeDefined()
    expect(screen.getByRole('button', { name: '실행' })).toBeDisabled()
    const mid = new File(['ISO-10303-21;'], 'p0002_mid.step', { type: 'model/step' })
    await userEvent.upload(screen.getByLabelText('중간면 형상 (pNNNN_mid.step)'), mid)
    expect(screen.getByRole('button', { name: '실행' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: '실행' }))
    await waitFor(() => expect(simulationApi.create).toHaveBeenCalled())
    expect(vi.mocked(simulationApi.create).mock.calls[0][0].midsurface?.name).toBe('p0002_mid.step')
  })

  it('CAD 값을 그대로 쓰는 스펙을 보낸다', async () => {
    await openWithPoint()
    await userEvent.click(screen.getByRole('button', { name: '실행' }))
    await waitFor(() => expect(simulationApi.create).toHaveBeenCalled())
    const sent = vi.mocked(simulationApi.create).mock.calls[0][0]
    expect(sent.topology?.name).toBe('p0002.json')
    expect(sent.spec.recipe).toBe('static')
    expect('modes' in sent.spec).toBe(false)
    // 물성은 싣지 않는다 — 서버가 점 파일의 재료를 파트마다 붙인다.
    expect('material' in sent.spec).toBe(false)
    expect(sent.spec.conditions_from).toBe('cad')
    expect(sent.spec.constraints).toEqual([])
  })

  it('CAD 조건을 끄면 고른 영역만 완전 고정한다', async () => {
    await openWithPoint()
    await userEvent.click(screen.getByRole('checkbox', { name: /CAD 가 보낸 조건 사용/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: /당기는 끝/ }))
    await userEvent.type(screen.getByLabelText('요소 크기 (mm)'), '2.5')
    // 하중이 빠지면 정적은 멈춘다 — 미리 말한다.
    expect(screen.getByText(/하중은 CAD 점 파일의 조건에서 옵니다/)).toBeDefined()
    await userEvent.click(screen.getByRole('button', { name: '실행' }))
    await waitFor(() => expect(simulationApi.create).toHaveBeenCalled())
    const spec = vi.mocked(simulationApi.create).mock.calls[0][0].spec as Record<string, any>
    expect('material' in spec).toBe(false)
    expect(spec.conditions_from).toBe('spec')
    expect(spec.constraints).toEqual([{ region: '당기는 끝', kind: 'fixed' }])
  })

  it('해석 종류를 바꾸면 조건을 그 종류로 다시 읽는다', async () => {
    await openWithPoint()
    await userEvent.selectOptions(screen.getByLabelText('해석 종류'), 'modal')
    await waitFor(() => expect(simulationApi.previewConditions).toHaveBeenCalledTimes(2))
    expect(vi.mocked(simulationApi.previewConditions).mock.calls[1][1]).toBe('modal')
    expect(screen.getByText(/CAD 가 적은 해석: 정적/)).toBeDefined()
  })

  it('조화 응답은 범위 · 점 수 · 감쇠비를 받는다', async () => {
    await openWithPoint()
    await userEvent.selectOptions(screen.getByLabelText('해석 종류'), 'harmonic')
    await userEvent.clear(screen.getByLabelText('감쇠비 (%)'))
    await userEvent.type(screen.getByLabelText('감쇠비 (%)'), '3')
    await userEvent.click(screen.getByRole('button', { name: '실행' }))
    await waitFor(() => expect(simulationApi.create).toHaveBeenCalled())
    const spec = vi.mocked(simulationApi.create).mock.calls[0][0].spec
    expect(spec.damping_ratio).toBeCloseTo(0.03)
    expect(spec.frequency_range_hz).toEqual([0, 2000])
    expect(spec.intervals).toBe(10)
  })

  it('CAD 조건을 끄면 CAD 의 요소 크기도 안 쓴다 — CalculiX 는 크기를 받아야 실행한다', async () => {
    // 끄면 모델링이 점 파일을 안 읽는다 — 「비우면 CAD 값」 이 거짓말이 되고 메시에서 멈춘다.
    await openWithPoint()
    await userEvent.selectOptions(screen.getByLabelText('솔버'), 'calculix')
    await userEvent.click(screen.getByRole('checkbox', { name: /CAD 가 보낸 조건 사용/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: /당기는 끝/ }))
    expect(screen.getByText(/CalculiX 는 요소 크기가 필요합니다/)).toBeDefined()
    expect(screen.getByRole('button', { name: '실행' })).toBeDisabled()
  })

  it('점 파일을 바꾸면 앞 점의 중간면을 버린다', async () => {
    vi.mocked(simulationApi.previewConditions).mockResolvedValue({
      ...SHEAR,
      bodies: [{ name: '위판', material: 'AL6061', suppressed: false, shell: true, setting: '쉘 2 mm' }],
    })
    await openWithPoint()
    const mid = new File(['ISO-10303-21;'], 'p0002_mid.step', { type: 'model/step' })
    await userEvent.upload(screen.getByLabelText('중간면 형상 (pNNNN_mid.step)'), mid)
    expect(screen.getByRole('button', { name: '실행' })).toBeEnabled()
    const other = new File(['{"regions": {}}'], 'p0003.json', { type: 'application/json' })
    await userEvent.upload(screen.getByLabelText('CAD 점 파일 (pNNNN.json)'), other)
    await waitFor(() => expect(screen.getByText('클램프')).toBeDefined())
    expect(screen.getByRole('button', { name: '실행' })).toBeDisabled()
  })

  it('CAD 가 해석 종류를 안 적었으면 서버가 편 종류(모달)로 칸을 맞춘다', async () => {
    await openWithPoint()
    expect((screen.getByLabelText('해석 종류') as HTMLSelectElement).value).toBe('static')
    vi.mocked(simulationApi.previewConditions).mockResolvedValue({ ...SHEAR, recipe: 'modal', suggested_recipe: null })
    await userEvent.upload(screen.getByLabelText('CAD 점 파일 (pNNNN.json)'), point())
    await waitFor(() => expect((screen.getByLabelText('해석 종류') as HTMLSelectElement).value).toBe('modal'))
  })

  it('설계 하나를 걸 수 없으면 그 까닭을 보인다', async () => {
    const blocked = {
      ...folderOf(true),
      usable: 0,
      skipped: 1,
      points: [{ number: 1, params: {}, usable: false, skip_reason: 'CAD 가 풀지 못한 영역이 있습니다: 바닥' }],
    }
    vi.mocked(simulationApi.browseDoe).mockResolvedValue({ ...ROOT, path: blocked.path, is_study: true })
    vi.mocked(simulationApi.previewDoe).mockResolvedValue(blocked as never)
    render(<NewSimulationDialog open onClose={() => {}} onCreated={() => {}} onImported={() => {}} />)
    await waitFor(() => expect(screen.getByText(/CAD 가 풀지 못한 영역이 있습니다: 바닥/)).toBeDefined())
    expect(screen.getByText(/이 설계는 실행할 수 없습니다/)).toBeDefined()
  })

  it('보려는 점을 못 읽으면 앞 점의 조건을 그 이름 아래 두지 않는다', async () => {
    openAt(DOE)
    await waitFor(() => expect(screen.getByText('클램프')).toBeDefined())
    vi.mocked(simulationApi.previewDoePoint).mockRejectedValue(new Error('점 파일이 없습니다'))
    await userEvent.click(screen.getByRole('button', { name: 'p0002 보기' }))
    await waitFor(() => expect(screen.getByText(/점 파일이 없습니다/)).toBeDefined())
    expect(screen.queryByText('클램프')).toBeNull()
    expect(screen.getByRole('button', { name: /실행/ })).toBeDisabled()
  })

  it('CalculiX 인데 요소 크기가 어디에도 없으면 실행하지 않는다', async () => {
    vi.mocked(simulationApi.previewConditions).mockResolvedValue({ ...SHEAR, suggested_element_size_mm: null })
    await openWithPoint()
    await userEvent.selectOptions(screen.getByLabelText('솔버'), 'calculix')
    expect(screen.getByText(/CalculiX 는 요소 크기가 필요합니다/)).toBeDefined()
    expect(screen.getByRole('button', { name: '실행' })).toBeDisabled()
    await userEvent.type(screen.getByLabelText('요소 크기 (mm)'), '4')
    expect(screen.getByRole('button', { name: '실행' })).toBeEnabled()
  })
})
