/**
 * 공용 폴더 탐색기 — **고른 뒤에 위로 올라가지 않아도 되는가.**
 *
 * 전에는 CAD 폴더를 누르면 그 안(points · shapes)으로 들어가, 옆 폴더로 바꾸려면 매번 「한 칸
 * 위」 를 눌러야 했다. 이제 CAD 폴더는 고르기만 하고, 경로는 마디마다 누르며, 이름으로 거른다.
 */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { crumbs, FolderBrowser } from '@/modules/simulations/FolderBrowser'

const LISTING = {
  path: '/data/doe/2026/브래킷',
  parent: '/data/doe/2026',
  roots: ['/data/doe', '/mnt/f/data/73_CompCore'],
  truncated: false,
  is_study: false,
  entries: [
    { name: '가_옛것', path: '/data/doe/2026/브래킷/가_옛것', is_study: true, modified_at: '2026-09-01T10:00:00Z' },
    { name: '나_새것', path: '/data/doe/2026/브래킷/나_새것', is_study: true, modified_at: '2026-10-04T10:00:00Z' },
    { name: '자료', path: '/data/doe/2026/브래킷/자료', is_study: false, modified_at: '2026-09-15T10:00:00Z' },
  ],
}

function setup(selected: string | null = null) {
  const onBrowse = vi.fn()
  const onPick = vi.fn()
  render(
    <FolderBrowser listing={LISTING} busy={false} onBrowse={onBrowse} onPick={onPick} selected={selected} badge="CAD" />,
  )
  return { onBrowse, onPick }
}

describe('공용 폴더 탐색기', () => {
  it('CAD 폴더는 고르기만 하고, 일반 폴더는 들어간다', async () => {
    const { onBrowse, onPick } = setup()
    await userEvent.click(screen.getByRole('button', { name: /나_새것/ }))
    expect(onPick).toHaveBeenCalledWith('/data/doe/2026/브래킷/나_새것')
    expect(onBrowse).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /자료/ }))
    expect(onBrowse).toHaveBeenCalledWith('/data/doe/2026/브래킷/자료')
  })

  it('고른 CAD 폴더를 표시하고, 옆 폴더도 그대로 보인다', () => {
    setup('/data/doe/2026/브래킷/가_옛것')
    expect(screen.getByRole('button', { name: /가_옛것/, pressed: true })).toBeDefined()
    expect(screen.getByRole('button', { name: /나_새것/, pressed: false })).toBeDefined()
  })

  it('경로 마디를 누르면 몇 칸 위로도 한 번에 간다', async () => {
    const { onBrowse } = setup()
    const trail = screen.getByRole('navigation', { name: '경로' })
    expect(trail.textContent).toContain('doe')
    expect(trail.textContent).toContain('브래킷')
    await userEvent.click(within(trail).getByRole('button', { name: 'doe' }))
    expect(onBrowse).toHaveBeenLastCalledWith('/data/doe')
    await userEvent.click(within(trail).getByRole('button', { name: '2026' }))
    expect(onBrowse).toHaveBeenLastCalledWith('/data/doe/2026')
  })

  it('이름으로 거르고, 하나만 남으면 Enter 로 연다', async () => {
    const { onPick } = setup()
    await userEvent.type(screen.getByLabelText('폴더 이름으로 찾기'), '새{Enter}')
    expect(screen.queryByRole('button', { name: /가_옛것/ })).toBeNull()
    expect(onPick).toHaveBeenCalledWith('/data/doe/2026/브래킷/나_새것')
  })

  it('최근순이면 방금 내보낸 폴더가 맨 위다', async () => {
    setup()
    await userEvent.click(screen.getByRole('button', { name: '최근' }))
    const names = screen.getAllByRole('listitem').map((one) => one.textContent ?? '')
    expect(names[0]).toContain('나_새것')
    expect(names[2]).toContain('가_옛것')
  })

  it('경로 마디는 가장 긴 뿌리부터 자른다', () => {
    expect(crumbs('/data/doe/a/b', ['/data', '/data/doe/'])).toEqual([
      { name: 'doe', path: '/data/doe' },
      { name: 'a', path: '/data/doe/a' },
      { name: 'b', path: '/data/doe/a/b' },
    ])
    // 뿌리 밖(설정이 바뀐 직후 등)이면 경로 그대로 하나.
    expect(crumbs('/elsewhere', ['/data'])).toEqual([{ name: '/elsewhere', path: '/elsewhere' }])
  })
})
