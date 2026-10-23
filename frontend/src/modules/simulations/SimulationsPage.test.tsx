/**
 * 「해석」 목록 — **단일 해석과 DOE 한 벌이 한 줄씩**(2026-10-23, ADR 0014). DOE 줄은 이름을 누르면
 * DOE 화면, ▸ 를 누르면 그 자리에서 설계점이 펼쳐진다. 작업공간은 위의 탭, 폴더는 왼쪽 나무(CompCore
 * 와 같은 손놀림), 고른 것 여럿에 폴더 이동 · 게시 · 해제 · 삭제.
 *
 * 서버는 `fetch` 를 가짜로 둔다 — 어느 경로로 무엇을 보내는지가 이 화면의 약속이다.
 */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({ admin: false }))

vi.mock('@/shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'me', is_system_admin: auth.admin, memberships: [] } }),
}))

import SimulationsPage from '@/modules/simulations/SimulationsPage'
import { buildTree, normalizePath } from '@/shared/folders/paths'

const job = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id,
  name,
  recipe: 'static',
  status: 'done',
  source_kind: 'upload',
  source_ref: '',
  source_meta: {},
  solver: 'calculix',
  owner_workspace_id: null,
  owner_workspace_name: null,
  requested_by_id: 'me',
  requested_by_name: '나',
  published_at: null,
  published_by_name: null,
  folder: '',
  error_code: null,
  summary: { max_displacement: 0.42 },
  created_at: '2026-10-23T00:00:00Z',
  started_at: null,
  finished_at: null,
  ...extra,
})

const STUDY = {
  study_id: 'st1',
  name: 'ISO178 두께 훑기',
  factors: ['두께'],
  recipe: 'static',
  solvers: ['calculix'],
  points: 3,
  done: 2,
  failed: 1,
  running: 0,
  owner_id: 'me',
  owner_name: '나',
  published: 0,
  folder: '고객A',
  created_at: '2026-10-23T01:00:00Z',
}

const ITEMS = [
  { kind: 'doe', key: 'doe:st1', study: STUDY, job: null },
  { kind: 'job', key: 'job:j1', job: job('j1', '측면가진 단품', { folder: '고객A/2026' }), study: null },
  {
    kind: 'job',
    key: 'job:j3',
    job: job('j3', '남의 결과', { requested_by_id: 'you', published_at: '2026-10-22T00:00:00Z' }),
    study: null,
  },
]

const POINTS = [1, 2, 3].map((number) => ({
  simulation_id: `p${number}`,
  number,
  params: { 두께: number + 2 },
  status: number === 2 ? 'failed' : 'done',
  error_code: number === 2 ? 'mesh_failed' : null,
  recipe: 'static',
  solver: 'calculix',
  frequencies: [],
  max_displacement_mm: number === 2 ? null : 4.78,
}))

type Call = { method: string; path: string; search: URLSearchParams; body?: unknown }

/** 가짜 서버 — (메서드 경로) → 응답. 함수면 요청을 보고 답한다. */
function serve(table: Record<string, unknown | ((call: Call) => [number, unknown])>): Call[] {
  const calls: Call[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = new URL(String(input), 'http://x')
    const call: Call = {
      method: init?.method ?? 'GET',
      path: url.pathname.replace(/^\/api/, ''),
      search: url.searchParams,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    }
    calls.push(call)
    const found = table[`${call.method} ${call.path}`]
    const [status, out] = typeof found === 'function' ? found(call) : [200, found ?? []]
    return new Response(JSON.stringify(out), { status, headers: { 'Content-Type': 'application/json' } })
  })
  return calls
}

function items(call: Call): [number, unknown] {
  const folder = call.search.get('folder')
  const kind = call.search.get('kind')
  const folderOf = (one: (typeof ITEMS)[number]) => (one.study ?? one.job)?.folder ?? ''
  const found = ITEMS.filter(
    (one) =>
      (!kind || one.kind === kind) &&
      (folder === null || (folder ? folderOf(one) === folder || folderOf(one).startsWith(`${folder}/`) : !folderOf(one))),
  )
  return [200, { items: found, total: found.length, limit: 50, offset: 0 }]
}

function show(path = '/simulations', element: ReactNode = <SimulationsPage />) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/simulations" element={element} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  auth.admin = false
})

describe('폴더 경로', () => {
  it('나무로 — 위 폴더도 세고 하위까지 합친다(CompCore 와 같은 규칙)', () => {
    expect(normalizePath(' /고객A//2026/ ')).toBe('고객A/2026')
    const tree = buildTree([
      { path: '', count: 2 },
      { path: '고객A', count: 1 },
      { path: '고객A/2026', count: 3 },
    ])
    expect(tree.map((one) => [one.name, one.total])).toEqual([['고객A', 4]])
  })
})

describe('「해석」 목록', () => {
  it('DOE 는 한 줄 — 이름은 DOE 화면으로, ▸ 는 그 자리에서 설계점을 펼친다', async () => {
    const calls = serve({ 'GET /simulations/items': items, 'GET /simulations/studies/st1': { points: POINTS } })
    show()
    const link = await screen.findByRole('link', { name: 'ISO178 두께 훑기' })
    expect(link.getAttribute('href')).toBe('/simulations/studies/st1')
    expect(screen.getByText(/완료 2\/3/)).toBeDefined()
    expect(screen.getByText(/실패 1/)).toBeDefined()
    // 펼치기 전에는 설계점을 읽지 않는다.
    expect(calls.some((one) => one.path === '/simulations/studies/st1')).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: 'ISO178 두께 훑기 설계점 펼치기' }))
    const failed = await screen.findByRole('link', { name: 'p0002' })
    expect(failed.getAttribute('href')).toBe('/simulations/p2')
    expect(screen.getByText('mesh_failed')).toBeDefined()
    expect(screen.getAllByText(/최대 변형 4.78 mm/).length).toBe(2)

    fireEvent.click(screen.getByRole('button', { name: 'ISO178 두께 훑기 설계점 접기' }))
    expect(screen.queryByRole('link', { name: 'p0002' })).toBeNull()
  })

  it('종류 거르개 · 상태 거르개를 주소와 서버에 그대로 싣는다', async () => {
    const calls = serve({ 'GET /simulations/items': items })
    show('/simulations?status=failed')
    expect(await screen.findByText(/설계점까지 작업 하나하나로 펼쳐/)).toBeDefined()
    expect(calls.some((one) => one.search.get('status') === 'failed')).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'DOE' }))
    await waitFor(() => expect(calls.some((one) => one.search.get('kind') === 'doe')).toBe(true))
  })

  it('폴더를 누르면 그 폴더(하위까지)로 거르고, 남의 줄은 고를 수 없다', async () => {
    const calls = serve({
      'GET /simulations/items': items,
      'GET /simulations/items/folders': [
        { path: '', count: 1 },
        { path: '고객A', count: 1 },
        { path: '고객A/2026', count: 1 },
      ],
    })
    show()
    expect(await screen.findByText('남의 결과')).toBeDefined()
    const tree = screen.getByRole('navigation', { name: '폴더' })
    expect(within(tree).getByText('고객A').closest('button')?.textContent).toContain('2')
    expect(screen.getByLabelText<HTMLInputElement>('남의 결과 선택').disabled).toBe(true)

    fireEvent.click(within(tree).getByText('고객A'))
    await waitFor(() => expect(screen.queryByText('남의 결과')).toBeNull())
    expect(calls.some((one) => one.path === '/simulations/items' && one.search.get('folder') === '고객A')).toBe(true)
    expect(screen.getByText(/📁 고객A › 2026/)).toBeDefined()
  })

  it('단일 해석과 DOE 를 섞어 골라 게시하면 제 API 로 하나씩, 못 한 것은 까닭을 말한다', async () => {
    const calls = serve({
      'GET /simulations/items': items,
      'POST /simulations/j1/publish': job('j1', '측면가진 단품'),
      'POST /simulations/studies/st1/publish': () => [
        409,
        { error: { code: 'SEB-SIMULATIONS-0034', message: '끝난 설계점이 없어 게시할 것이 없습니다.' } },
      ],
    })
    show()
    fireEvent.click(await screen.findByLabelText('이 페이지 전체 선택'))
    // 고를 수 있는 줄(내 것)만 골랐다.
    expect(await screen.findByText('2개 선택됨')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: '게시' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toContain('조직의 누구나')
    fireEvent.click(within(dialog).getByRole('button', { name: '게시' }))
    expect(
      await screen.findByText(/항목 1개를 게시했습니다. 하지 못한 것 1개: ISO178 두께 훑기 — 끝난 설계점이 없어/),
    ).toBeDefined()
    expect(calls.filter((one) => one.method === 'POST').map((one) => one.path).sort()).toEqual([
      '/simulations/j1/publish',
      '/simulations/studies/st1/publish',
    ])
  })

  it('골라서 폴더로 옮기면 항목 열쇠(job: · doe:)로 한 번에 보낸다', async () => {
    const calls = serve({ 'GET /simulations/items': items, 'POST /simulations/items/move': { moved: 2 } })
    show()
    fireEvent.click(await screen.findByLabelText('측면가진 단품 선택'))
    fireEvent.click(screen.getByLabelText('ISO178 두께 훑기 선택'))
    fireEvent.click(screen.getByRole('button', { name: '폴더로 이동' }))
    fireEvent.change(screen.getByLabelText('폴더 경로'), { target: { value: '보관/ 2026 ' } })
    fireEvent.click(screen.getByRole('button', { name: '이동' }))
    await waitFor(() =>
      expect(calls.find((one) => one.path === '/simulations/items/move')?.body).toEqual({
        ids: ['job:j1', 'doe:st1'],
        folder: '보관/2026',
      }),
    )
  })

  it('작업공간은 위의 탭 — 주소가 고른 칸을 켜고, 「전체」 는 시스템 관리자에게만', async () => {
    serve({ 'GET /simulations/items': items })
    const { unmount } = show('/simulations?scope=published')
    const tabs = within(await screen.findByRole('navigation', { name: '작업공간' }))
    expect(tabs.getByRole('link', { current: 'page' }).textContent).toContain('공용 작업공간')
    expect(tabs.queryByText('전체')).toBeNull()
    unmount()

    auth.admin = true
    show('/simulations')
    const admin = within(await screen.findByRole('navigation', { name: '작업공간' }))
    expect(admin.getByRole('link', { name: /전체/ }).getAttribute('href')).toBe('/simulations?scope=all')
    expect(admin.getByRole('link', { current: 'page' }).textContent).toContain('개인 작업')
  })
})
