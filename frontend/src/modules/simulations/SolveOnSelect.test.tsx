/**
 * 풀 곳 — STE 를 못 고르면 까닭을 그대로, 고를 수 있으면 대기열을 보인다(요청서 E-2).
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { SolvePlace } from '@/modules/simulations/api'

const solvePlaces = vi.hoisted(() => vi.fn())
vi.mock('@/modules/simulations/api', () => ({ simulationApi: { solvePlaces } }))

import { SolveOnSelect } from '@/modules/simulations/SolveOnSelect'

const LOCAL: SolvePlace = {
  place: 'local',
  label: '이 서버',
  available: true,
  reason: null,
  queue: null,
  note: '메시 · 솔브 · 추출을 모두 이 서버에서 합니다.',
}
const STE: SolvePlace = {
  place: 'ste',
  label: 'STE 클러스터',
  available: true,
  reason: null,
  queue: { partition: 'alpha', cpus_total: 2944, cpus_idle: 222, jobs_pending: 3, mine_pending: 1, mine_running: 0 },
  note: '메시 · 추출은 이 서버, 솔브(ccx)만 STE 에서 — 건 사람 명의로 잡을 냅니다.',
}

describe('풀 곳', () => {
  beforeEach(() => vi.clearAllMocks())

  it('STE 를 고르면 대기열 요약을 보인다', async () => {
    solvePlaces.mockResolvedValue([LOCAL, STE])
    const onChange = vi.fn()
    const { rerender } = render(<SolveOnSelect id="s" value="local" solver="calculix" onChange={onChange} />)
    const option = (await screen.findByRole('option', { name: 'STE 클러스터' })) as HTMLOptionElement
    await waitFor(() => expect(option.disabled).toBe(false))
    await userEvent.selectOptions(screen.getByLabelText('풀 곳'), 'ste')
    expect(onChange).toHaveBeenCalledWith('ste')
    rerender(<SolveOnSelect id="s" value="ste" solver="calculix" onChange={onChange} />)
    expect(screen.getByText(/남은 코어 222 \/ 2,944 · 대기 잡 3 · 내 잡 대기 1 · 실행 0/)).toBeInTheDocument()
  })

  it('못 고르면 까닭을 그대로 보인다', async () => {
    solvePlaces.mockResolvedValue([
      LOCAL,
      { ...STE, available: false, queue: null, reason: 'STE 사용 권한이 없습니다 — 포털에서 STE 권한을 청하세요' },
    ])
    render(<SolveOnSelect id="s" value="local" solver="calculix" onChange={vi.fn()} />)
    expect(await screen.findByText(/포털에서 STE 권한을 청하세요/)).toBeInTheDocument()
    const option = screen.getByRole('option', { name: /STE 클러스터 — 지금 고를 수 없음/ }) as HTMLOptionElement
    expect(option.disabled).toBe(true)
  })

  it('Ansys 로 바꾸면 이 서버로 돌린다 — STE 는 CalculiX 만', async () => {
    solvePlaces.mockResolvedValue([LOCAL, STE])
    const onChange = vi.fn()
    render(<SolveOnSelect id="s" value="ste" solver="ansys" onChange={onChange} />)
    await waitFor(() => expect(onChange).toHaveBeenCalledWith('local'))
  })
})
