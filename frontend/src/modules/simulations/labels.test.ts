/**
 * 화면이 코드값을 날것으로 보여 주지 않는가.
 *
 * 단계 · 실패 코드는 서버가 정하고 화면이 이름표를 단다. 이름표가 빠지면 사람은 `region_unresolved`
 * 같은 코드를 읽고 다음에 무엇을 할지 모른다 — **빠진 것을 여기서 잡는다.**
 * 서버 쪽 코드 전체와 대조하는 것은 `backend/tests/architecture/test_simulation_labels.py` 다.
 */

import { describe, expect, it } from 'vitest'

import { STAGE_NAMES } from '@/modules/simulations/api'
import { STAGE_LABELS, shownDuration, shownSize } from '@/modules/simulations/labels'

describe('해석 작업 이름표', () => {
  it('단계마다 이름표가 있다', () => {
    for (const name of STAGE_NAMES) {
      expect(STAGE_LABELS[name], `${name} 의 이름표가 없습니다`).toBeTruthy()
    }
  })

  it('걸린 시간은 분 · 시간으로 접는다', () => {
    const start = '2026-09-20T00:00:00Z'
    expect(shownDuration(start, '2026-09-20T00:00:42Z')).toBe('42초')
    expect(shownDuration(start, '2026-09-20T00:01:12Z')).toBe('1분 12초')
    expect(shownDuration(start, '2026-09-20T02:30:00Z')).toBe('2시간 30분')
    // **시작하지 않은 작업은 0초가 아니다.** 0초로 적으면 「순식간에 끝났다」 로 읽힌다.
    expect(shownDuration(null, null)).toBe('—')
  })

  it('크기는 자릿수를 사람이 세지 않게 한다', () => {
    expect(shownSize(512)).toBe('512B')
    expect(shownSize(2048)).toBe('2KB')
    expect(shownSize(5 * 1024 * 1024)).toBe('5.0MB')
  })
})
