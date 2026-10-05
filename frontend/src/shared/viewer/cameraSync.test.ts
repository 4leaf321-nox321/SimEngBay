/**
 * 시점 묶음 — **한 칸의 시점이 나머지로 가고, 꺼 두면 안 가며, 켜면 마지막 시점으로 모인다.**
 */

import { describe, expect, it, vi } from 'vitest'

import { CameraSync } from '@/shared/viewer/cameraSync'
import type { CameraState } from '@/shared/viewer/cameraSync'

const STATE: CameraState = {
  position: [1, 2, 3],
  focalPoint: [0, 0, 0],
  viewUp: [0, 0, 1],
  viewAngle: 30,
  parallelScale: 5,
}

function member() {
  return { apply: vi.fn(), reset: vi.fn() }
}

describe('시점 묶음', () => {
  it('한 칸의 시점을 나머지에 옮긴다 — 보낸 칸은 빼고', () => {
    const sync = new CameraSync(true)
    const [a, b, c] = [member(), member(), member()]
    for (const one of [a, b, c]) sync.join(one)
    sync.publish(a, STATE)
    expect(a.apply).not.toHaveBeenCalled()
    expect(b.apply).toHaveBeenCalledWith(STATE)
    expect(c.apply).toHaveBeenCalledWith(STATE)
  })

  it('꺼 두면 안 옮기고, 켜면 마지막으로 움직인 시점으로 모은다', () => {
    const sync = new CameraSync(false)
    const [a, b] = [member(), member()]
    sync.join(a)
    sync.join(b)
    sync.publish(a, STATE)
    expect(b.apply).not.toHaveBeenCalled()
    sync.setEnabled(true)
    expect(a.apply).toHaveBeenCalledWith(STATE)
    expect(b.apply).toHaveBeenCalledWith(STATE)
  })

  it('새로 뜬 칸은 지금 시점으로 시작하고, 나간 칸에는 안 보낸다', () => {
    const sync = new CameraSync(true)
    const a = member()
    sync.join(a)
    sync.publish(a, STATE)
    const late = member()
    const leave = sync.join(late)
    expect(late.apply).toHaveBeenCalledWith(STATE)
    leave()
    sync.publish(a, { ...STATE, viewAngle: 40 })
    expect(late.apply).toHaveBeenCalledTimes(1)
  })

  it('처음으로 — 모든 칸을 처음 시점으로', () => {
    const sync = new CameraSync(true)
    const [a, b] = [member(), member()]
    sync.join(a)
    sync.join(b)
    sync.resetAll()
    expect(a.reset).toHaveBeenCalled()
    expect(b.reset).toHaveBeenCalled()
  })
})
