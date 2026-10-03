/**
 * 「워커 · 솔버」 카드 — **영원히 대기하는 작업을 말하는가.**
 *
 * CalculiX 작업이 있는데 CalculiX 를 집는 워커가 없으면 그 작업은 대기에서 안 움직이고, 아무도
 * 그 사실을 말해 주지 않는다. 신호가 끊긴 워커는 「응답 없음」 으로 보여야 한다.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { simulationApi } from '@/modules/simulations/api'
import type { WorkersOverview } from '@/modules/simulations/api'
import { ago, WorkersCard } from '@/modules/simulations/WorkersCard'

vi.mock('@/modules/simulations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/simulations/api')>()
  return { ...actual, simulationApi: { ...actual.simulationApi, workers: vi.fn() } }
})

const NOW = '2026-10-03T09:00:00Z'

const OVERVIEW: WorkersOverview = {
  alive: 1,
  workers: [
    {
      id: 'srv1:4101',
      hostname: 'srv1',
      pid: 4101,
      version: '0.3.0',
      executor: 'local',
      solvers: ['ansys'],
      tools: { ccx: '/usr/bin/ccx', gmsh: '/usr/bin/gmsh', ansys: { path: '/ansys_inc/v252/ansys/bin/ansys252', checked: true } },
      state: 'busy',
      started_at: NOW,
      last_seen_at: NOW,
      silent_seconds: 4,
      job: {
        id: 'b6f1b5aa-0000-4000-8000-000000000001',
        name: '브래킷 p0003',
        status: 'solving',
        recipe: 'modal',
        solver: 'ansys',
        started_at: NOW,
        cancelling: false,
      },
    },
    {
      id: 'srv1:4102',
      hostname: 'srv1',
      pid: 4102,
      version: '0.3.0',
      executor: 'local',
      solvers: ['calculix'],
      tools: { ccx: null, gmsh: null, ansys: { checked: false, note: '모의' } },
      state: 'lost',
      started_at: NOW,
      last_seen_at: NOW,
      silent_seconds: 312,
      job: null,
    },
  ],
  queues: [
    { solver: 'ansys', queued: 0, running: 1, oldest_queued_seconds: null, workers_alive: 1 },
    { solver: 'calculix', queued: 3, running: 0, oldest_queued_seconds: 600, workers_alive: 0 },
  ],
  license_holders: [
    {
      simulation_id: 'b6f1b5aa-0000-4000-8000-000000000001',
      name: '브래킷 p0003',
      status: 'solving',
      worker_id: 'srv1:4101',
      started_at: NOW,
    },
  ],
}

function show() {
  return render(
    <MemoryRouter>
      <WorkersCard />
    </MemoryRouter>,
  )
}

describe('워커 · 솔버', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.workers).mockReset().mockResolvedValue(OVERVIEW)
  })

  it('집을 워커가 없는 솔버의 대기를 맨 위에 말한다', async () => {
    show()
    await waitFor(() =>
      expect(screen.getByText(/CalculiX \(오픈소스\) 작업 3개가 기다리지만/)).toBeDefined(),
    )
  })

  it('신호가 끊긴 워커를 응답 없음으로 보여 준다', async () => {
    show()
    await waitFor(() => expect(screen.getByText('응답 없음')).toBeDefined())
    expect(screen.getByText('5분 전')).toBeDefined()
    // 워커가 적은 값 — 집는 솔버와 깔린 도구.
    expect(screen.getAllByText('Ansys').length).toBeGreaterThan(0)
    expect(screen.getByText(/ccx 없음/)).toBeDefined()
  })

  it('라이선스를 쥔 작업을 해석 작업 기준이라고 밝혀 보여 준다', async () => {
    show()
    await waitFor(() => expect(screen.getByText('Ansys 라이선스를 쥔 작업')).toBeDefined())
    expect(screen.getAllByText('브래킷 p0003').length).toBe(2)
    expect(screen.getByText(/해석 작업 기준입니다/)).toBeDefined()
  })

  it('신호를 적는 워커가 없으면 그 까닭을 말한다', async () => {
    vi.mocked(simulationApi.workers).mockResolvedValue({ ...OVERVIEW, workers: [], alive: 0 })
    show()
    await waitFor(() => expect(screen.getByText('신호를 적는 워커가 없습니다')).toBeDefined())
  })

  it('지난 시간을 사람의 말로 적는다', () => {
    expect(ago(12)).toBe('12초 전')
    expect(ago(312)).toBe('5분 전')
    expect(ago(7300)).toBe('2시간 전')
  })
})
