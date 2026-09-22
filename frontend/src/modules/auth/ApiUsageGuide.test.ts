/**
 * 토큰을 넣는 법은 도구마다 모양이 다르지만 **주소 · 토큰은 같다.**
 */
import { describe, expect, it } from 'vitest'

import { usageSnippets } from './ApiUsageGuide'

describe('usageSnippets', () => {
  const base = 'https://portal.example/simengbay/api'

  it('토큰이 두 예시에 다 들어간다', () => {
    const s = usageSnippets('simengbay_pat_abc', base)
    for (const text of [s.curl, s.python]) {
      expect(text).toContain('Bearer simengbay_pat_abc')
      expect(text).toContain(base)
    }
  })

  it('토큰이 없으면 자리표시자', () => {
    const s = usageSnippets(null, base)
    expect(s.curl).toContain('‹발급받은_토큰›')
    expect(s.curl).not.toContain('undefined')
  })
})
