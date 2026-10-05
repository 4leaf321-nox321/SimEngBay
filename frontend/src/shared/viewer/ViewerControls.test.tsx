/**
 * 뷰어 막대의 보이기 단추 — **외곽선 · 요소는 모든 뷰어가 함께 쓰고 기억한다. 파트는 하나씩 · 이것만
 * · 모두 보이기로 고른다.**
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { STORAGE_PREFIX } from '@/shared/branding'
import { DisplayToggles, PartPicker } from '@/shared/viewer/ViewerControls'
import { setViewerPrefs } from '@/shared/viewer/viewerPrefs'

const PARTS = [
  { id: 0, name: '지그블록' },
  { id: 1, name: '브래킷' },
  { id: 2, name: '볼트' },
]

describe('뷰어 막대', () => {
  it('외곽선은 켜져서 시작하고, 요소 선은 꺼져서 시작한다 — 누르면 바뀌고 기억한다', async () => {
    render(<DisplayToggles />)
    expect(screen.getByRole('button', { name: '외곽선', pressed: true })).toBeDefined()
    await userEvent.click(screen.getByRole('button', { name: '요소', pressed: false }))
    expect(screen.getByRole('button', { name: '요소', pressed: true })).toBeDefined()
    expect(JSON.parse(window.localStorage.getItem(`${STORAGE_PREFIX}.viewer.display`) ?? '{}')).toEqual({
      outline: true,
      edges: true,
    })
    setViewerPrefs({ edges: false })
  })

  it('파트를 하나씩 숨기고, 이것만 보고, 모두 보인다', async () => {
    const changed = vi.fn()
    const { rerender } = render(<PartPicker parts={PARTS} hidden={[]} onChange={changed} />)
    await userEvent.click(screen.getByRole('button', { name: /파트 3\/3/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: '지그블록' }))
    expect(changed).toHaveBeenLastCalledWith([0])
    const only = screen.getAllByRole('button', { name: '이것만' })
    await userEvent.click(only[1])
    expect(changed).toHaveBeenLastCalledWith([0, 2])

    rerender(<PartPicker parts={PARTS} hidden={[0, 2]} onChange={changed} />)
    expect(screen.getByRole('button', { name: /파트 1\/3/ })).toBeDefined()
    await userEvent.click(screen.getByRole('button', { name: '모두 보이기' }))
    expect(changed).toHaveBeenLastCalledWith([])
  })

  it('파트가 하나면 고르는 칸이 없다', () => {
    render(<PartPicker parts={[PARTS[0]]} hidden={[]} onChange={() => {}} />)
    expect(screen.queryByRole('button', { name: /파트/ })).toBeNull()
  })
})
