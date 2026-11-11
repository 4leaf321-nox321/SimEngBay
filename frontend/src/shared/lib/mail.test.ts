import { describe, expect, it } from 'vitest'

import { mailLine } from '@/shared/lib/mail'

describe('mailLine', () => {
  it('메일 주소를 ; 로 잇는다 — Outlook 받는 사람 칸의 모양', () => {
    expect(mailLine(['hong@corp.co.kr', 'kim@corp.co.kr'])).toEqual({
      line: 'hong@corp.co.kr; kim@corp.co.kr',
      count: 2,
      skipped: [],
    })
  })

  it('메일 주소가 아닌 아이디는 빼고 무엇을 뺐는지 말한다', () => {
    const got = mailLine(['admin', 'hong@corp.local', ' ', 'kim@'])
    expect(got.line).toBe('hong@corp.local')
    expect(got.skipped).toEqual(['admin', 'kim@'])
  })

  it('같은 주소는 한 번만 싣는다', () => {
    expect(mailLine(['hong@corp.co.kr', 'HONG@corp.co.kr ']).count).toBe(1)
  })
})
