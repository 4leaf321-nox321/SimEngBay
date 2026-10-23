/**
 * 변형 그림의 위상 — **주기 0(정적)이 NaN 을 만들지 않는다.** NaN 이면 좌표가 모두 NaN 이 되어
 * 그림이 통째로 사라지고, 오류도 안 난다(2026-10-23 「DOE 개별 작업의 3D 가 빈 화면」).
 */
import { describe, expect, it } from 'vitest'

import { animates, warpPhase } from '@/shared/viewer/warp'

describe('warpPhase', () => {
  it('흔들 때는 sin — 4분의 1 주기에 최대', () => {
    expect(warpPhase(400, 1600, true)).toBeCloseTo(1)
    expect(warpPhase(1200, 1600, true)).toBeCloseTo(-1)
  })

  it('멈추면 최대 변형(1)', () => {
    expect(warpPhase(1200, 1600, false)).toBe(1)
  })

  it('주기 0 · 음수 · NaN 이면 흔들지 않고 최대 변형 — NaN 을 내지 않는다', () => {
    for (const period of [0, -1, Number.NaN]) {
      for (const elapsed of [0, 16, 1000]) {
        expect(warpPhase(elapsed, period, true)).toBe(1)
      }
    }
    expect(animates(0)).toBe(false)
    expect(animates(1600)).toBe(true)
  })
})
