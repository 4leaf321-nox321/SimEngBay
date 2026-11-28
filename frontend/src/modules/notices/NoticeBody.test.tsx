/**
 * 공지 본문 — 배포 안내의 `**굵게**` · `` `코드` `` 만 그리고, 나머지는 **적힌 그대로**인가.
 *
 * 그리지 않으면 별표와 역따옴표가 글자로 보인다. 마크다운 전부를 그리면 HTML 을 끼워 넣을 길이
 * 생긴다 — 그래서 이 둘만이다.
 */
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { NoticeBody } from '@/modules/notices/NoticeBody'

describe('공지 본문', () => {
  it('굵게 · 코드만 그리고 줄과 목록 기호는 그대로 둔다', () => {
    const { container } = render(
      <NoticeBody text={'■ 새로 생긴 것\n- **소성 재료**를 받습니다(`TB,BISO`).\n- 끝'} />,
    )
    expect(container.querySelector('strong')?.textContent).toBe('소성 재료')
    expect(container.querySelector('code')?.textContent).toBe('TB,BISO')
    expect(container.textContent).toBe('■ 새로 생긴 것\n- 소성 재료를 받습니다(TB,BISO).\n- 끝')
  })

  it.each([
    ['줄을 넘는 별표', '**한 줄\n다음 줄**'],
    ['짝 없는 역따옴표', '`짝 없음'],
    ['빈 강조', '****'],
    ['HTML', '<b>굵게</b> <img src=x onerror=alert(1)>'],
  ])('%s 은 글자 그대로다', (_name, text) => {
    const { container } = render(<NoticeBody text={text} />)
    expect(container.querySelector('strong, code, b, img')).toBeNull()
    expect(container.textContent).toBe(text)
  })
})
