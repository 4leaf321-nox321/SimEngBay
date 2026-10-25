/**
 * 스터디 상세 — **200점짜리 DOE 에서 점마다 누르게 하지 않는다.** 실패한 점을 한 번에 다시
 * 실행하고, 중간 파일을 스터디째 정리한다(서버의 `studies/{id}/tidy`).
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { simulationApi } from '@/modules/simulations/api'
import type { Study, StudyPoint } from '@/modules/simulations/api'
import StudyDetailPage from '@/modules/simulations/StudyDetailPage'

// 화면이 「건 사람인가」 를 본다(`ownsWork`) — 스터디의 주인으로 연다.
vi.mock('@/shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'me', is_system_admin: false, memberships: [] } }),
}))

vi.mock('@/modules/simulations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/simulations/api')>()
  return {
    ...actual,
    simulationApi: {
      ...actual.simulationApi,
      study: vi.fn(),
      retry: vi.fn(),
      tidyStudy: vi.fn(),
      cancelStudy: vi.fn(),
      rerunStudy: vi.fn(),
      removeStudy: vi.fn(),
      studyTable: vi.fn(),
      studyMeasurements: vi.fn(),
    },
  }
})

const clipboard = vi.hoisted(() => ({ copied: [] as string[] }))
vi.mock('@/shared/lib/clipboard', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/clipboard')>()),
  copyText: async (text: string) => {
    clipboard.copied.push(text)
  },
}))

function point(number: number, status: string): StudyPoint {
  return {
    simulation_id: `s${number}`,
    number,
    params: { 두께: number * 2 },
    status,
    published: false,
    recipe: 'modal',
    solver: 'calculix',
    frequencies: [],
  }
}

const STUDY: Study = {
  study_id: 'st',
  name: '브래킷',
  factors: ['두께'],
  recipe: 'modal',
  solvers: ['calculix'],
  tracks: [],
  owner_id: 'me',
  owner_name: '나',
  published: 0,
  points: [point(1, 'failed'), point(2, 'canceled'), point(3, 'failed')],
}

function ListPlace() {
  const { search } = useLocation()
  return <p>해석 목록{search}</p>
}

function show(path = '/simulations/studies/st') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/simulations/studies/:id" element={<StudyDetailPage />} />
        {/* 지우면 「해석」 목록의 DOE 거르개로 간다(`/simulations?kind=doe`, ADR 0014). */}
        <Route path="/simulations" element={<ListPlace />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('스터디 상세', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.study).mockReset().mockResolvedValue(STUDY)
    vi.mocked(simulationApi.retry).mockReset().mockResolvedValue({} as never)
    vi.mocked(simulationApi.tidyStudy).mockReset().mockResolvedValue({ bytes_freed: 3 * 1024 * 1024, files: 12, points: 3 })
    vi.mocked(simulationApi.studyMeasurements).mockReset().mockResolvedValue([])
  })

  it('모드 수를 바꿔 다시 건다 — 지우지 않고, 옛 결과는 기록으로(비교가 끊긴 DOE 를 고치는 길)', async () => {
    // 6개만 구해 비교가 끊긴 DOE(실측 2026-10-25 외팔보 두께 x 폭).
    const done = (number: number) => ({ ...point(number, 'done'), frequencies: [160, 810, 1030, 2860, 2940, 4860] })
    vi.mocked(simulationApi.study).mockResolvedValue({ ...STUDY, points: [done(1), done(2), done(3)] })
    vi.mocked(simulationApi.rerunStudy).mockReset().mockResolvedValue({
      study_id: 'st',
      name: '브래킷',
      created: ['n1', 'n2'],
      skipped: [{ number: 3, params: {}, usable: false, skip_reason: '입력 형상 파일이 없습니다' }],
      notes: [],
    })
    show()
    await userEvent.click(await screen.findByRole('button', { name: '모드 수 바꿔 다시 걸기' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toContain('옛 결과는 지우지 않고 기록으로 남고')
    expect(dialog.textContent).toContain('지금 6개')
    const field = within(dialog).getByLabelText('새 모드 수')
    expect((field as HTMLInputElement).value).toBe('10')
    // 말이 안 되는 수면 누를 수 없다.
    await userEvent.clear(field)
    await userEvent.type(field, '0')
    expect(within(dialog).getByRole('button', { name: '설계점 3개 다시 걸기' })).toBeDisabled()
    await userEvent.clear(field)
    await userEvent.type(field, '12')
    await userEvent.click(within(dialog).getByRole('button', { name: '설계점 3개 다시 걸기' }))

    await waitFor(() => expect(simulationApi.rerunStudy).toHaveBeenCalledWith('st', 12))
    expect(await screen.findByText(/설계점 2개를 모드 12개로 다시 걸었습니다/)).toBeDefined()
    expect(screen.getByText(/p0003 입력 형상 파일이 없습니다/)).toBeDefined()
  })

  it('도는 점이 있거나 정적 DOE 면 다시 걸기를 두지 않는다', async () => {
    vi.mocked(simulationApi.study).mockResolvedValue({ ...STUDY, points: [point(1, 'done'), point(2, 'solving')] })
    const { unmount } = show()
    expect(await screen.findByRole('button', { name: /모두 멈추기/ })).toBeDefined()
    expect(screen.queryByRole('button', { name: '모드 수 바꿔 다시 걸기' })).toBeNull()
    unmount()

    vi.mocked(simulationApi.study).mockResolvedValue({ ...STUDY, recipe: 'static', points: [point(1, 'done')] })
    show()
    expect(await screen.findByRole('button', { name: /표 복사/ })).toBeDefined()
    expect(screen.queryByRole('button', { name: '모드 수 바꿔 다시 걸기' })).toBeNull()
  })

  it('실패 · 취소된 점을 한 번에 다시 실행한다', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: /실패한 점 다시 실행 \(3\)/ }))
    await waitFor(() => expect(simulationApi.retry).toHaveBeenCalledTimes(3))
    expect(screen.getByText(/3개를 다시 실행했습니다/)).toBeDefined()
  })

  it('다시 실행하지 못한 점은 그 까닭을 모아 보여 준다', async () => {
    vi.mocked(simulationApi.retry).mockRejectedValueOnce(new Error('권한이 없습니다'))
    show()
    await userEvent.click(await screen.findByRole('button', { name: /실패한 점 다시 실행/ }))
    await waitFor(() => expect(screen.getByText(/p0001: 권한이 없습니다/)).toBeDefined())
  })

  it('중간 파일을 스터디째 정리하기 전에 무엇이 사라지는지 말한다', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: /중간 파일 정리/ }))
    expect(screen.getByText(/결과 요약 · 그림 · 입력은 남습니다/)).toBeDefined()
    await userEvent.click(screen.getByRole('button', { name: '정리' }))
    await waitFor(() => expect(simulationApi.tidyStudy).toHaveBeenCalledWith('st'))
    await waitFor(() => expect(screen.getByText(/중간 파일 12개 · 3.0MB/)).toBeDefined())
  })

  it('비교 표는 내려받지 않고 클립보드로 — 탭으로 갈라 엑셀에 그대로 붙는다(사내 DRM)', async () => {
    clipboard.copied.length = 0
    vi.mocked(simulationApi.studyTable).mockReset().mockResolvedValue({
      name: '브래킷',
      head: ['점', '두께', '1차 모드 (Hz)'],
      rows: [
        ['1', '2', '812.4'],
        ['2', '4', '1,203'],
      ],
    })
    show()
    await userEvent.click(await screen.findByRole('button', { name: /표 복사/ }))
    await waitFor(() => expect(clipboard.copied).toHaveLength(1))
    expect(clipboard.copied[0]).toBe('점\t두께\t1차 모드 (Hz)\n1\t2\t812.4\n2\t4\t1,203')
    expect(await screen.findByText(/설계점 2개 · 열 3개를 복사했습니다/)).toBeDefined()
  })

  it('DOE 를 지우기 전에 무엇이 사라지는지 말하고, 지우면 목록으로 간다', async () => {
    vi.mocked(simulationApi.removeStudy).mockReset().mockResolvedValue({ jobs: 3, bytes_freed: 1, points: 3 })
    show()
    await userEvent.click(await screen.findByRole('button', { name: '삭제' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toContain('설계점 3개')
    expect(dialog.textContent).toContain('되돌릴 수 없습니다')
    await userEvent.click(within(dialog).getByRole('button', { name: '삭제' }))
    await waitFor(() => expect(simulationApi.removeStudy).toHaveBeenCalledWith('st'))
    expect(await screen.findByText('해석 목록?kind=doe')).toBeDefined()
  })

  it('도는 점이 있으면 지우지 않고 「모두 멈추기」 를 먼저 하게 한다', async () => {
    vi.mocked(simulationApi.study).mockResolvedValue({
      ...STUDY,
      points: [point(1, 'solving'), point(2, 'queued'), point(3, 'done')],
    })
    vi.mocked(simulationApi.cancelStudy).mockReset().mockResolvedValue({ points: 2 })
    show()
    await userEvent.click(await screen.findByRole('button', { name: '삭제' }))
    let dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toContain('도는 설계점 1개')
    expect(within(dialog).getByRole('button', { name: '삭제' }).hasAttribute('disabled')).toBe(true)
    await userEvent.click(within(dialog).getByRole('button', { name: '취소' }))

    await userEvent.click(screen.getByRole('button', { name: /모두 멈추기 \(2\)/ }))
    dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: '모두 멈추기' }))
    await waitFor(() => expect(simulationApi.cancelStudy).toHaveBeenCalledWith('st'))
    expect(await screen.findByText(/설계점 2개를 멈추게 했습니다/)).toBeDefined()
  })

  it('끝난 점이 없으면 비교는 막고, 설계점 탭에서 점마다 상태와 오류를 보인다', async () => {
    vi.mocked(simulationApi.study).mockResolvedValue({
      ...STUDY,
      points: [{ ...point(1, 'failed'), error_code: 'license' }, point(2, 'queued')],
    })
    show()
    const compare = await screen.findByRole('tab', { name: '비교' })
    expect(compare.hasAttribute('disabled') || compare.getAttribute('data-disabled') !== null).toBe(true)
    const points = screen.getByRole('tab', { name: /설계점 \(0\/2\)/ })
    expect(points.getAttribute('aria-selected')).toBe('true')
    const table = screen.getByRole('table')
    expect(within(table).getByText('p0001')).toBeDefined()
    expect(within(table).getByText('license')).toBeDefined()
  })

  it('주소의 탭을 연다 — 끝난 점이 있으면 비교도 열 수 있다', async () => {
    vi.mocked(simulationApi.study).mockResolvedValue({
      ...STUDY,
      points: [point(1, 'done'), point(2, 'done')],
    })
    show('/simulations/studies/st?tab=checks')
    const checks = await screen.findByRole('tab', { name: '검증' })
    expect(checks.getAttribute('aria-selected')).toBe('true')
    expect(await screen.findByText('실측과 맞추기')).toBeDefined()
    expect(screen.getByRole('tab', { name: '비교' }).hasAttribute('disabled')).toBe(false)
  })
})
