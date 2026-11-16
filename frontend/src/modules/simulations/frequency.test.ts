/**
 * 주파수 요구 — 입력 칸을 요구 조건으로 읽고, 서버의 판정을 채워 둔다. 판정 셈은 서버가 한다
 * (`backend/tests/unit/test_study_frequency.py`).
 */

import { describe, expect, it } from 'vitest'

import type { FrequencyCheck } from '@/modules/simulations/api'
import {
  draftOf,
  filled,
  levelsOf,
  modeName,
  newBand,
  newTarget,
  numericFactors,
  orderedPoints,
  parseDraft,
  ruleOf,
  signedPct,
  signedSlope,
} from '@/modules/simulations/frequency'

describe('입력 칸 → 요구 조건', () => {
  it('목표 주파수는 0 보다 큰 수 · 허용 0–100 % · 대상 모드가 있어야 한다', () => {
    const draft = { ...newTarget('a', 2), target: '1,300', tolerance: '3', label: ' 하우징 공진 ' }
    expect(parseDraft(draft).requirement).toEqual({
      kind: 'target',
      label: '하우징 공진',
      mode: 2,
      target_hz: 1300,
      tolerance_pct: 3,
    })
    expect(ruleOf(draft)).toBe('1,261 – 1,339 Hz 안이면 충족')
    expect(parseDraft({ ...draft, target: '' }).problem).toMatch('목표 주파수')
    expect(parseDraft({ ...draft, tolerance: '120' }).problem).toMatch('허용 범위')
  })

  it('회피 대역은 상한이 하한보다 커야 하고 이격 여유를 넣은 범위를 말한다', () => {
    const draft = { ...newBand('b', true), low: '700', high: '900', margin: '10', probe: '센서 A' }
    const parsed = parseDraft(draft).requirement
    expect(parsed).toMatchObject({
      kind: 'band',
      low_hz: 700,
      high_hz: 900,
      margin_pct: 10,
      mass_filter: true,
      mass_direction: 'Z',
      probe_filter: true,
      probe: '센서 A',
    })
    expect(ruleOf(draft)).toBe('630 Hz 이하 또는 990 Hz 이상이면 충족 (이격 여유 포함)')
    expect(parseDraft({ ...draft, high: '600' }).problem).toMatch('상한이 하한보다')
    // 측정점을 비우면 「측정점 중 최대」 — null 로 보낸다.
    expect(parseDraft({ ...draft, probe: '' }).requirement).toMatchObject({ probe: null })
  })

  it('저장된 요구를 다시 입력 칸으로 편다', () => {
    const back = draftOf(
      {
        kind: 'band',
        label: '팬',
        low_hz: 1500,
        high_hz: 1600,
        margin_pct: 5,
        mass_filter: false,
        mass_direction: 'Y',
        mass_min_pct: 5,
        probe_filter: true,
        probe: null,
        probe_min_pct: 20,
      },
      'k',
    )
    expect(back).toMatchObject({ kind: 'band', low: '1500', massOn: false, direction: 'Y', probeOn: true, probe: '' })
  })
})

const CHECK: FrequencyCheck = {
  study_id: 's',
  saved: false,
  tracked: true,
  factors: ['두께', '리브'],
  points: [
    { simulation_id: 'b', number: 2, params: { 두께: 1.4, 리브: 0 }, status: 'done', verdict: 'conform' },
    { simulation_id: 'a', number: 1, params: { 두께: 1.2, 리브: 2 }, status: 'done', verdict: 'nonconform' },
    { simulation_id: 'c', number: 3, params: { 두께: 1.2, 리브: 0 }, status: 'failed', verdict: 'pending' },
  ],
}

describe('판정 채우기 · 차례', () => {
  it('비어 오는 칸을 채운다', () => {
    const check = filled(CHECK)
    expect(check.requirements).toEqual([])
    expect(check.points[0].modes).toEqual([])
    expect(check.tracked).toBe(true)
  })

  it('설계 변수 차례로 선다 — 첫 변수로 묶이고 그 안에서 둘째가 오른다', () => {
    const check = filled(CHECK)
    expect(orderedPoints(check.points, check.factors).map((one) => one.number)).toEqual([3, 1, 2])
    expect(numericFactors(check.points, check.factors)).toEqual(['두께', '리브'])
    expect(levelsOf(check.points, '두께')).toEqual([1.2, 1.4])
  })

  it('모드 이름과 부호 붙은 %', () => {
    expect(modeName({ track: 2, index: 3 })).toBe('2차 모드')
    expect(modeName({ track: null, index: 4 })).toBe('미추적 모드 (4번째)')
    expect(signedPct(-1.04)).toBe('−1.0 %')
    expect(signedPct(2.4)).toBe('+2.4 %')
  })

  it('기울기는 작으면 유효숫자 둘 — 「+0」 으로 뭉개지 않는다', () => {
    expect(signedSlope(791.4)).toBe('+791')
    expect(signedSlope(-82.3)).toBe('−82')
    expect(signedSlope(0.1532)).toBe('+0.15')
    expect(signedSlope(0)).toBe('±0')
  })
})
