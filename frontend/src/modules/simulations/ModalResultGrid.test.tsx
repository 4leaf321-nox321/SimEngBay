/**
 * 모달 결과의 「여러 개 보기」 — **하나씩 크게와 같은 3D 뷰어**를 깐다(두 솔버가 똑같이).
 *
 * 처음에는 추출이 만든 그림(PNG)으로 그려서, 그림을 안 만드는 CalculiX 작업은 칸마다 「그림
 * 없음」 이었다(2026-10-05). 이제 칸마다 형상(VTP)을 받아 3D 로 그리고, 움직임은 위에서 한 번에.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/modules/simulations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/simulations/api')>()
  return {
    ...actual,
    // 형상은 받는 중으로 둔다 — jsdom 에는 WebGL 이 없다.
    simulationApi: { ...actual.simulationApi, mesh: vi.fn(() => new Promise(() => {})) },
  }
})

import { simulationApi } from '@/modules/simulations/api'
import type { Artifact, SimulationResult } from '@/modules/simulations/api'
import { ModalResult } from '@/modules/simulations/ModalResult'

/** CalculiX 결과처럼 — 형상(VTP)만 있고 그림(PNG)은 없다. */
const RESULT = {
  recipe: 'modal',
  solver: 'calculix',
  boundary: 'constrained',
  units: { frequency: 'Hz' },
  normalization: 'mass',
  rigid_body_modes: 0,
  modes: Array.from({ length: 7 }, (_, index) => ({
    number: index + 1,
    elastic_number: index + 1,
    frequency_hz: 600 + index * 100,
    rigid_body: false,
    vtp: `mode_${String(index + 1).padStart(2, '0')}.vtp`,
  })),
} as unknown as SimulationResult

const ARTIFACTS = RESULT.modes.map((one, index) => ({
  id: `a${index + 1}`,
  filename: one.vtp,
  kind: 'mode_vtp',
  stage: 'extracting',
  size_bytes: 100,
})) as unknown as Artifact[]

describe('여러 개 보기', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.mesh).mockClear()
  })

  it('그림(PNG)이 없어도 모드마다 3D 칸을 깐다 — 한 화면 6개, 쪽으로 넘긴다', async () => {
    render(<ModalResult simulationId="sim" result={RESULT} artifacts={ARTIFACTS} />)
    await userEvent.click(screen.getByRole('button', { name: '여러 개 보기' }))
    expect(screen.queryByText(/그림 없음/)).toBeNull()
    expect(screen.getAllByText('형상을 불러오는 중…')).toHaveLength(6)
    expect(screen.getByRole('button', { name: '6차 · 1,100 Hz' })).toBeDefined()
    // 칸마다 그 모드의 형상을 받는다.
    const asked = vi.mocked(simulationApi.mesh).mock.calls.map((call) => call[1])
    expect(asked).toEqual(expect.arrayContaining(['a1', 'a6']))
    await userEvent.click(screen.getByRole('button', { name: '9개' }))
    expect(screen.getAllByText('형상을 불러오는 중…')).toHaveLength(7)
  })

  it('움직임은 한 번에 멈추고, 제목을 누르면 그 모드를 크게 연다', async () => {
    render(<ModalResult simulationId="sim" result={RESULT} artifacts={ARTIFACTS} />)
    await userEvent.click(screen.getByRole('button', { name: '여러 개 보기' }))
    await userEvent.click(screen.getByRole('button', { name: '모두 멈추기' }))
    expect(screen.getByRole('button', { name: '모두 움직이기' })).toBeDefined()
    // 시점 맞추기는 켜져서 시작하고, 누르면 꺼진다.
    expect(screen.getByRole('button', { name: '시점 맞추기', pressed: true })).toBeDefined()
    await userEvent.click(screen.getByRole('button', { name: '시점 맞추기' }))
    expect(screen.getByRole('button', { name: '시점 맞추기', pressed: false })).toBeDefined()
    await userEvent.click(screen.getByRole('button', { name: '3차 · 800 Hz' }))
    expect(screen.getByRole('button', { name: '하나씩 크게', pressed: true })).toBeDefined()
    expect(screen.getByRole('heading', { name: /3차 모드/ })).toBeDefined()
  })

  it('형상 파일이 없는 모드를 열면 「불러오는 중」 에 멈추지 않고 없다고 말한다', () => {
    // 스펙트럼에서는 형상이 없는 모드도 누를 수 있다 — 결과가 적은 파일이 산출물에 없을 때도.
    render(<ModalResult simulationId="sim" result={RESULT} artifacts={ARTIFACTS.slice(1)} />)
    expect(screen.getByText(/이 모드는 3D 형상이 없습니다/)).toBeDefined()
    expect(screen.queryByText('모드 형상을 불러오는 중…')).toBeNull()
  })

  it('여러 개 보기 막대에서 색 지도를 고른다 — 기본은 Ansys 식 무지개', async () => {
    render(<ModalResult simulationId="sim" result={RESULT} artifacts={ARTIFACTS} />)
    await userEvent.click(screen.getByRole('button', { name: '여러 개 보기' }))
    const select = screen.getByLabelText('색 지도') as HTMLSelectElement
    expect(select.value).toBe('ansys')
    expect(Array.from(select.options).map((one) => one.value)).toEqual([
      'ansys',
      'turbo',
      'jet',
      'viridis',
      'plasma',
      'inferno',
      'coolwarm',
      'gray',
    ])
    await userEvent.selectOptions(select, 'turbo')
    expect((screen.getByLabelText('색 지도') as HTMLSelectElement).value).toBe('turbo')
    await userEvent.selectOptions(screen.getByLabelText('색 지도'), 'ansys')
  })
})
