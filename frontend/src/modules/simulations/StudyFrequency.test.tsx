/**
 * 「주파수 요구」 탭 — 요구 조건을 고치면 서버에 미리 묻고(저장하지 않은 요구), 저장하면 스터디에
 * 남는다. 판정 셈은 서버가 한다 — 여기서는 화면이 서버의 판정을 그대로 보이는지 본다.
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { simulationApi } from '@/modules/simulations/api'
import type { FrequencyCheck } from '@/modules/simulations/api'
import { StudyFrequency } from '@/modules/simulations/StudyFrequency'

vi.mock('@/modules/simulations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/simulations/api')>()
  return {
    ...actual,
    simulationApi: {
      ...actual.simulationApi,
      studyFrequency: vi.fn(),
      checkStudyFrequency: vi.fn(),
      saveStudyFrequency: vi.fn(),
    },
  }
})

const TARGET = { kind: 'target' as const, label: '하우징 공진 정합', mode: 2, target_hz: 1300, tolerance_pct: 3 }
const BAND = {
  kind: 'band' as const,
  label: '모터 가진',
  low_hz: 700,
  high_hz: 900,
  margin_pct: 10,
  mass_filter: true,
  mass_direction: 'Z' as const,
  mass_min_pct: 5,
  probe_filter: true,
  probe: '센서 A',
  probe_min_pct: 20,
}

function mode(index: number, track: number, hz: number, role: 'target' | 'judged' | 'excluded', inBand = false) {
  return {
    index,
    track,
    frequency_hz: hz,
    mass_pct: { Z: role === 'excluded' ? 0.4 : 46 },
    probe_pct: { '센서 A': role === 'excluded' ? 3 : 72 },
    role,
    in_band: inBand,
    reason: role === 'excluded' ? 'Z 유효질량 0.4 % · 측정점 센서 A 3 %' : 'Z 유효질량 46.0 %',
  }
}

const CHECK: FrequencyCheck = {
  study_id: 'st',
  requirements: [TARGET, BAND],
  saved: true,
  updated_at: '2026-11-16T05:20:00Z',
  updated_by_name: '설계자',
  factors: ['두께', '리브'],
  probes: ['센서 A'],
  tracks: [1, 2, 3],
  tracked: true,
  counts: { conform: 1, band_violation: 0, target_deviation: 0, nonconform: 1, pending: 0 },
  points: [
    {
      simulation_id: 's13',
      number: 13,
      params: { 두께: 1.6, 리브: 2 },
      status: 'done',
      verdict: 'conform',
      mass_kg: 0.06,
      targets: [{ requirement: 0, index: 2, frequency_hz: 1287, error_pct: -1, ok: true }],
      bands: [
        { requirement: 1, closest_index: 1, closest_track: 1, closest_hz: 615, margin_pct: 12.1, inside: false, ok: true, judged: 3 },
      ],
      modes: [mode(1, 1, 615, 'judged'), mode(2, 2, 1287, 'target'), mode(3, 4, 1142, 'excluded')],
      sensitivity: [{ factor: '두께', hz_per_unit: 791, equivalent: 0.0493 }],
    },
    {
      simulation_id: 's1',
      number: 1,
      params: { 두께: 1.2, 리브: 0 },
      status: 'done',
      verdict: 'nonconform',
      mass_kg: 0.044,
      targets: [{ requirement: 0, index: 3, frequency_hz: 853, error_pct: -34.4, ok: false }],
      bands: [
        { requirement: 1, closest_index: 3, closest_track: 2, closest_hz: 853, margin_pct: 0, inside: true, ok: false, judged: 3 },
      ],
      modes: [mode(1, 1, 431, 'judged'), mode(2, 4, 1095, 'excluded'), mode(3, 2, 853, 'target', true)],
      sensitivity: [],
    },
  ],
  crossings: [],
  estimate: {
    params: { 리브: 4, 두께: 1.49 },
    margin_pct: 12.6,
    text: 'DOE 에 없는 자리 — 리브 4 · 두께 ≈ 1.49 에서 모든 요구 조건을 만족할 것으로 보입니다.',
  },
  notes: [],
}

function show(readOnly = false) {
  return render(
    <MemoryRouter>
      <StudyFrequency studyId="st" readOnly={readOnly} />
    </MemoryRouter>,
  )
}

describe('주파수 요구 탭', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.studyFrequency).mockReset().mockResolvedValue(CHECK)
    vi.mocked(simulationApi.checkStudyFrequency).mockReset()
    vi.mocked(simulationApi.saveStudyFrequency).mockReset()
  })

  it('저장된 요구와 판정을 보인다 — 판정 요약 · 보간 추정 · 후보 설계점', async () => {
    show()
    expect(await screen.findByText('주파수 요구 조건')).toBeInTheDocument()
    expect(screen.getByDisplayValue('하우징 공진 정합')).toBeInTheDocument()
    expect(screen.getByText(/스터디에 저장됨 · 설계자/)).toBeInTheDocument()
    expect(screen.getByText('1,261 – 1,339 Hz 안이면 충족')).toBeInTheDocument()
    expect(screen.getByText('630 Hz 이하 또는 990 Hz 이상이면 충족 (이격 여유 포함)')).toBeInTheDocument()
    const summary = screen.getByRole('region', { name: '판정 요약' })
    expect(within(summary).getByRole('button', { name: /적합 1 모든 요구 충족/ })).toBeInTheDocument()
    expect(within(summary).getByText(/리브 4 · 두께 ≈ 1.49/)).toBeInTheDocument()
    // 기본으로 고른 설계점은 적합인 점 — 상세에 요구마다 결과와 공차 민감도.
    const detail = screen.getByRole('region', { name: /설계점 상세/ })
    expect(within(detail).getByText(/2차 모드 1,287 Hz, 목표 1,300 Hz 대비 −1.0 %/)).toBeInTheDocument()
    expect(within(detail).getByText(/최근접 판정 대상 1차 모드 615 Hz — 대역 끝까지 이격 12.1 %/)).toBeInTheDocument()
    expect(within(detail).getByText(/두께 ± 0.0493 에 해당/)).toBeInTheDocument()
    expect(within(detail).getByText('판정 제외')).toBeInTheDocument()
    // 후보 표는 적합이 먼저다.
    const table = screen.getByRole('region', { name: '후보 설계점' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('p0013')).toBeInTheDocument()
    expect(within(rows[1]).getByText(/회피 대역 안/)).toBeInTheDocument()
  })

  it('판정 요약을 누르면 후보 표가 그 판정만 남긴다', async () => {
    show()
    const summary = await screen.findByRole('region', { name: '판정 요약' })
    await userEvent.click(within(summary).getByRole('button', { name: /부적합 1/ }))
    const table = screen.getByRole('region', { name: '후보 설계점' })
    expect(within(table).getAllByRole('row')).toHaveLength(2)
    expect(within(table).getByText('p0001')).toBeInTheDocument()
  })

  it('고치면 저장하지 않은 요구로 미리 보고, 저장하면 스터디에 남긴다', async () => {
    vi.mocked(simulationApi.checkStudyFrequency).mockResolvedValue({
      ...CHECK,
      saved: false,
      counts: { conform: 0, band_violation: 0, target_deviation: 1, nonconform: 1, pending: 0 },
    })
    vi.mocked(simulationApi.saveStudyFrequency).mockResolvedValue({ ...CHECK, updated_by_name: '설계자' })
    show()
    const target = await screen.findByDisplayValue('1300')
    await userEvent.clear(target)
    await userEvent.type(target, '1250')
    expect(screen.getByText(/저장하지 않은 변경/)).toBeInTheDocument()
    await waitFor(() => expect(simulationApi.checkStudyFrequency).toHaveBeenCalled())
    const sent = vi.mocked(simulationApi.checkStudyFrequency).mock.calls.at(-1)?.[1]
    expect(sent?.[0]).toMatchObject({ kind: 'target', target_hz: 1250, mode: 2 })
    const summary = screen.getByRole('region', { name: '판정 요약' })
    await waitFor(() => expect(within(summary).getByRole('button', { name: /목표 이탈 1/ })).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: '저장' }))
    await waitFor(() => expect(simulationApi.saveStudyFrequency).toHaveBeenCalled())
    expect(vi.mocked(simulationApi.saveStudyFrequency).mock.calls[0][1][1]).toMatchObject({ kind: 'band', low_hz: 700 })
    expect(await screen.findByText(/스터디에 저장됨/)).toBeInTheDocument()
  })

  it('못 읽는 입력은 미리 보지 않고 까닭을 말한다', async () => {
    show()
    const high = await screen.findByDisplayValue('900')
    await userEvent.clear(high)
    await userEvent.type(high, '600')
    expect(screen.getByText('회피 대역의 상한이 하한보다 커야 합니다.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '저장' })).toBeDisabled()
    await new Promise((resolve) => setTimeout(resolve, 400))
    expect(simulationApi.checkStudyFrequency).not.toHaveBeenCalled()
  })

  it('남의 게시 DOE 는 읽기만 한다', async () => {
    show(true)
    expect(await screen.findByText(/읽기 전용/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '저장' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /회피 대역$/ })).not.toBeInTheDocument()
  })
})
