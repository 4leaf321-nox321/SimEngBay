/**
 * 새 해석 작업 — **CAD 점 파일을 올리면 서버가 읽은 것을 보여 주고, CAD 값이 먼저라는 것을
 * 스펙에 그대로 싣는가.**
 *
 * 전에는 물성 칸이 늘 쓰이는 것처럼 보였고(실제로는 CAD 물성이 이겼다), 해석 종류는 모달로
 * 못 박혀 정적 점 파일이 하중을 건너뛴 채 모달로 돌았다. 이제 물성 칸은 없고 **파트마다 붙을
 * 재료**를 보인다 — 물성은 CompCore 가 파트마다 정한다. 그래서 점 파일이 있어야 실행한다.
 */

import { render, screen, waitFor } from '@testing-library/react'
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
  render(<NewSimulationDialog open onClose={() => {}} onCreated={() => {}} />)
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

describe('새 해석 작업', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.previewConditions).mockReset().mockResolvedValue(SHEAR)
    vi.mocked(simulationApi.create).mockReset().mockResolvedValue({ id: 'new' } as never)
    vi.mocked(simulationApi.solvers).mockReset().mockResolvedValue([])
    vi.mocked(simulationApi.browseDoe).mockReset().mockResolvedValue(ROOT)
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
    render(<NewSimulationDialog open onClose={() => {}} onCreated={created} />)
    await waitFor(() => expect(screen.getByText('설계 하나')).toBeDefined())
    await waitFor(() => expect(screen.getByText('클램프')).toBeDefined())
    expect(simulationApi.previewDoePoint).toHaveBeenCalledWith(folderOf(true).path, 1, undefined)
    // 폴더에서 오면 파일 칸이 없다.
    expect(screen.queryByLabelText('형상 파일 (STEP)')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '실행' }))
    await waitFor(() => expect(created).toHaveBeenCalled())
    const sent = vi.mocked(simulationApi.importDoe).mock.calls[0][0]
    expect(sent.path).toBe(folderOf(true).path)
    expect(sent.numbers).toEqual([1])
    expect('material' in sent.spec).toBe(false)
    expect(simulationApi.get).toHaveBeenCalledWith('made')
  })

  it('DOE 폴더면 설계점 하나를 선택한다', async () => {
    vi.mocked(simulationApi.browseDoe).mockResolvedValue({ ...ROOT, path: folderOf(false).path, is_study: true })
    vi.mocked(simulationApi.previewDoe).mockResolvedValue(folderOf(false) as never)
    render(<NewSimulationDialog open onClose={() => {}} onCreated={() => {}} />)
    await waitFor(() => expect(screen.getByText('클램프')).toBeDefined())
    await userEvent.click(screen.getByRole('radio', { name: /p0002/ }))
    await waitFor(() => expect(simulationApi.previewDoePoint).toHaveBeenLastCalledWith(folderOf(false).path, 2, undefined))
    await waitFor(() => expect(screen.getByRole('button', { name: '실행' })).toBeEnabled())
    await userEvent.type(screen.getByLabelText('이름'), '두께 3 확인')
    await userEvent.click(screen.getByRole('button', { name: '실행' }))
    await waitFor(() => expect(simulationApi.importDoe).toHaveBeenCalled())
    const sent = vi.mocked(simulationApi.importDoe).mock.calls[0][0]
    expect(sent.numbers).toEqual([2])
    expect(sent.name).toBe('두께 3 확인')
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
    render(<NewSimulationDialog open onClose={() => {}} onCreated={() => {}} />)
    await waitFor(() => expect(screen.getByRole('button', { name: '실행' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: '실행' }))
    await waitFor(() => expect(screen.getByText(/이미 가져온 점입니다/)).toBeDefined())
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
