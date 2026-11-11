/**
 * 메일 주소 복사 — **운영은 http 라 `navigator.clipboard` 가 없다.** 그 길(execCommand)로 복사되는지,
 * 그것마저 막히면 주소를 칸에 띄우는지 본다.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CopyMailAddresses } from '@/shared/components/CopyMailAddresses'

const IDS = ['hong@corp.co.kr', 'admin', 'kim@corp.co.kr']

describe('CopyMailAddresses', () => {
  let copied: string[]
  let allowed: boolean

  beforeEach(() => {
    copied = []
    allowed = true
    // http — 보안 컨텍스트가 아니면 clipboard 가 없다.
    vi.stubGlobal('navigator', { ...navigator, clipboard: undefined })
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: vi.fn(() => {
        const area = document.activeElement as HTMLTextAreaElement
        copied.push(area.value.slice(area.selectionStart, area.selectionEnd))
        return allowed
      }),
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('http 에서도 고른 주소를 ; 로 이어 복사하고, 메일 주소가 아닌 아이디는 뺐다고 말한다', async () => {
    render(<CopyMailAddresses ids={IDS} />)
    const button = screen.getByRole('button', { name: '메일 주소 복사 (2명)' })
    button.focus()
    fireEvent.click(button)
    await waitFor(() => expect(copied).toEqual(['hong@corp.co.kr; kim@corp.co.kr']))
    expect(await screen.findByText(/2명의 주소를 복사했습니다/)).toBeInTheDocument()
    expect(screen.getByText(/메일 주소가 아닌 아이디 1개는 뺐습니다: admin/)).toBeInTheDocument()
    // 숨은 칸은 치우고 포커스는 누른 단추로 돌아온다.
    expect(document.querySelector('textarea')).toBeNull()
    expect(document.activeElement).toBe(button)
  })

  it('브라우저가 복사를 막으면 주소를 칸에 띄워 직접 복사하게 한다', async () => {
    allowed = false
    render(<CopyMailAddresses ids={IDS} />)
    fireEvent.click(screen.getByRole('button', { name: /메일 주소 복사/ }))
    const box = await screen.findByLabelText('복사할 메일 주소')
    expect(box).toHaveValue('hong@corp.co.kr; kim@corp.co.kr')
    expect(screen.getByText(/Ctrl\+C 로 복사하세요/)).toBeInTheDocument()
  })

  it('고른 계정이 없으면 단추를 막고 고르라고 한다', () => {
    render(<CopyMailAddresses ids={[]} />)
    expect(screen.getByRole('button', { name: '메일 주소 복사' })).toBeDisabled()
    expect(screen.getByText('표에서 계정을 고르세요')).toBeInTheDocument()
  })
})
