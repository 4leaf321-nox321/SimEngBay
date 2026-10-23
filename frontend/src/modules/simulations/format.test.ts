/**
 * 수 표기 — **작은 값을 0 으로 지우지 않는다.** 운영에서 0.029 g 짜리 부품의 질량이 모두 「0」 으로
 * 보였다(2026-10-23): 서버는 kg 을 소수 넷째 자리로 잘랐고, 화면은 kg 소수 둘째 자리로 적었다.
 */
import { describe, expect, it } from 'vitest'

import { massScale, shownMass } from '@/modules/simulations/format'
import { shownNumber } from '@/shared/charts/palette'

describe('shownMass', () => {
  it('크기에 맞는 단위로, 유효숫자 네 자리', () => {
    expect(shownMass(2.9045e-5)).toBe('29.05 mg')
    expect(shownMass(0.02904)).toBe('29.04 g')
    expect(shownMass(1.23456)).toBe('1.235 kg')
  })

  it('0 이하 · 없음은 「—」 — 옛 작업은 반올림으로 0 이 남았다', () => {
    expect(shownMass(0)).toBe('—')
    expect(shownMass(null)).toBe('—')
  })

  it('표 · 축은 한 단위로 — 가장 큰 값에 맞춘다', () => {
    const scale = massScale([2.9e-5, 4.1e-4, null])
    expect(scale.unit).toBe('mg')
    expect(shownMass(4.1e-4, scale)).toBe('410 mg')
    expect(massScale([0.0012, 0.3]).unit).toBe('g')
    expect(massScale([]).unit).toBe('kg')
  })
})

describe('shownNumber(눈금)', () => {
  it('1 아래는 유효숫자 세 자리 — 「0.00」 으로 지우지 않는다', () => {
    expect(shownNumber(0.0000290451)).toBe('0.000029')
    expect(shownNumber(2.9e-7)).toBe('2.9e-7')
    expect(shownNumber(1234.567)).toBe('1234.57')
    expect(shownNumber(1200)).toBe('1,200')
  })
})
