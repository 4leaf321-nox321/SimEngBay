/**
 * 한눈에 보기 줄 — **해석 종류마다 대표 숫자를, 「믿어도 되나」 를 한 마디로.**
 */

import { describe, expect, it } from 'vitest'

import type { Convergence, Measurement, Simulation } from '@/modules/simulations/api'
import { convergenceWord, headline, measurementWord } from '@/modules/simulations/ResultGlance'
import type { AnyResult } from '@/modules/simulations/ResultPanel'

const SIM = { summary: { mass_kg: 0.502, nodes: 29890 } } as unknown as Simulation

describe('한눈에 보기 줄', () => {
  it('모달은 1차 고유진동수(방향 · 유효질량) · 탄성 모드 수 · 질량 · 절점', () => {
    const result = {
      recipe: 'modal',
      rigid_body_modes: 0,
      units: { frequency: 'Hz' },
      modes: [
        { number: 1, elastic_number: 1, frequency_hz: 1263.5, rigid_body: false, dominant_direction: 'Y', effective_mass_ratio: 0.62 },
        { number: 2, elastic_number: 2, frequency_hz: 2583.1, rigid_body: false },
      ],
    } as unknown as AnyResult
    const stats = headline(SIM, result)
    expect(stats.map((one) => one.label)).toEqual(['1차 고유진동수', '탄성 모드', '질량', '절점'])
    expect(stats[0].value).toBe('1,263.5 Hz')
    expect(stats[0].hint).toBe('Y 이동 62%')
    expect(stats[1].value).toBe('2개')
    expect(stats[3].value).toBe('29,890')
  })

  it('정적은 최대 변형 · 최대 상당응력 · 가장 큰 반력 · 측정점', () => {
    const result = {
      recipe: 'static',
      units: { displacement: 'mm', stress: 'MPa', force: 'N' },
      max_displacement: 0.3236,
      max_von_mises: 91.1,
      reactions: { 고정단: [0, 0, 66], 바닥: [1, 0, 0] },
      probes: [{ name: '끝', value: 0.31, unit: 'mm' }],
    } as unknown as AnyResult
    const stats = headline(SIM, result)
    expect(stats.map((one) => one.label)).toEqual(['최대 변형', '최대 상당응력', '반력', '측정점'])
    expect(stats[2]).toMatchObject({ value: '66 N', hint: '고정단' })
  })

  it('조화는 봉우리 주파수 · 봉우리 변위 · 감쇠비 · 측정점 봉우리', () => {
    const result = {
      recipe: 'harmonic',
      units: { frequency: 'Hz', displacement: 'mm' },
      damping_ratio: 0.02,
      points: [],
      peak: { frequency_hz: 820, max_displacement: 1.2434 },
      probes: [{ name: '측정점', value: 1.2434, unit: 'mm' }],
    } as unknown as AnyResult
    const stats = headline(SIM, result)
    expect(stats.map((one) => one.label)).toEqual(['봉우리 주파수', '봉우리 변위', '감쇠비', '측정점 봉우리'])
    expect(stats[2].value).toBe('2.0%')
  })

  it('메시 수렴과 실측을 한 마디로', () => {
    expect(convergenceWord(null).text).toBe('점검 안 함')
    const levels = [{ status: 'done' }, { status: 'done' }]
    expect(
      convergenceWord({ levels, metrics: [{ status: 'converged' }] } as unknown as Convergence),
    ).toMatchObject({ text: '수렴', tone: 'good' })
    expect(
      convergenceWord({
        levels,
        metrics: [{ status: 'converged' }, { status: 'diverging' }],
      } as unknown as Convergence).text,
    ).toBe('발산 있음')
    expect(measurementWord([]).text).toBe('없음')
    expect(
      measurementWord([
        { comparison: { score_pct: 7.5 } },
        { comparison: { score_pct: 2.34 } },
      ] as unknown as Measurement[]),
    ).toMatchObject({ text: '차이 2.3%', tone: 'good' })
  })
})
