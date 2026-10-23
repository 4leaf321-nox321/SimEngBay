/**
 * 목록 화면의 왼쪽 — 폴더 나무(와 쓰는 화면이 주면 만든 해). 누르면 거르고, 항목을 끌어다 놓으면
 * 그 폴더로 옮긴다. 폴더마다 하위 폴더 만들기 · 이름 바꾸기 · 지우기(안의 항목은 위 폴더로).
 */

import { useState } from 'react'
import type { DragEvent } from 'react'
import { ChevronDown, ChevronRight, Folder, FolderOpen, FolderPlus, Pencil, Trash2 } from 'lucide-react'

import { buildTree, DRAG_TYPE, josa } from '@/shared/folders/paths'
import type { FolderNode } from '@/shared/folders/paths'
import type { FolderSpace } from '@/shared/folders/useFolderSpace'

interface FolderTreeProps {
  space: FolderSpace
  /** 맨 위 줄 — 「모든 작업」 · 「모든 DOE」. */
  allLabel: string
  /** 안내 문구의 이름 — 「작업」 · 「DOE」. */
  noun: string
  /** 만든 해 — 주는 화면만. */
  years?: { year: number; count: number }[]
  year?: number | null
  onYear?: (year: number | null) => void
}

/** 옮기기에 실패하면(남의 것 등) 나무 아래에 적는다 — 끌어다 놓기는 창이 없어서. */
type Fail = (failure: unknown) => void

/** 끌어다 놓기를 받는 줄 — 항목 id 묶음만 받는다. */
function useDrop(path: string, space: FolderSpace, fail: Fail) {
  const [over, setOver] = useState(false)
  return {
    over,
    handlers: {
      onDragOver: (event: DragEvent) => {
        if (!event.dataTransfer.types.includes(DRAG_TYPE)) return
        event.preventDefault()
        setOver(true)
      },
      onDragLeave: () => setOver(false),
      onDrop: (event: DragEvent) => {
        setOver(false)
        const raw = event.dataTransfer.getData(DRAG_TYPE)
        if (!raw) return
        event.preventDefault()
        try {
          const ids = JSON.parse(raw) as string[]
          if (ids.length) space.moveTo(ids, path).catch(fail)
        } catch {
          // 다른 것을 끌어 왔다 — 무시한다.
        }
      },
    },
  }
}

function Row({ node, depth, space, fail }: { node: FolderNode; depth: number; space: FolderSpace; fail: Fail }) {
  const [open, setOpen] = useState(true)
  const drop = useDrop(node.path, space, fail)
  const chosen = space.folder === node.path
  return (
    <li>
      <div
        {...drop.handlers}
        className={`group flex items-center gap-1 rounded px-1 py-0.5 text-sm ${chosen ? 'bg-accent font-medium' : 'hover:bg-accent/60'} ${drop.over ? 'ring-primary ring-2' : ''}`}
        style={{ paddingLeft: `${depth * 12 + 4}px` }}
      >
        <button
          type="button"
          className="text-muted-foreground w-4 shrink-0"
          onClick={() => setOpen(!open)}
          aria-label={open ? `${node.name} 접기` : `${node.name} 펼치기`}
          disabled={node.children.length === 0}
        >
          {node.children.length > 0 && (open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />)}
        </button>
        <button type="button" className="flex min-w-0 flex-1 items-center gap-1 text-left" onClick={() => space.select(node.path)}>
          {chosen ? <FolderOpen className="size-4 shrink-0" /> : <Folder className="size-4 shrink-0" />}
          <span className="truncate">{node.name}</span>
          <span className="text-muted-foreground ml-auto text-xs">{node.total}</span>
        </button>
        <span className="hidden shrink-0 gap-0.5 group-hover:flex">
          <button type="button" className="text-muted-foreground hover:text-foreground" onClick={() => space.setDialog({ kind: 'new', parent: node.path })} aria-label={`${node.name} 안에 새 폴더`}>
            <FolderPlus className="size-3.5" />
          </button>
          <button type="button" className="text-muted-foreground hover:text-foreground" onClick={() => space.setDialog({ kind: 'rename', path: node.path })} aria-label={`${node.name} 이름 변경`}>
            <Pencil className="size-3.5" />
          </button>
          <button type="button" className="text-muted-foreground hover:text-destructive" onClick={() => space.setDialog({ kind: 'remove', path: node.path })} aria-label={`${node.name} 삭제`}>
            <Trash2 className="size-3.5" />
          </button>
        </span>
      </div>
      {open && node.children.length > 0 && (
        <ul>
          {node.children.map((child) => (
            <Row key={child.path} node={child} depth={depth + 1} space={space} fail={fail} />
          ))}
        </ul>
      )}
    </li>
  )
}

export function FolderTree({ space, allLabel, noun, years = [], year = null, onYear }: FolderTreeProps) {
  const [failure, setFailure] = useState<string | null>(null)
  const fail: Fail = (caught) => setFailure(caught instanceof Error ? caught.message : String(caught))
  const tree = buildTree(space.rows, space.pending)
  const everything = space.rows.reduce((sum, row) => sum + row.count, 0)
  const loose = space.rows.find((row) => row.path === '')?.count ?? 0
  const rootDrop = useDrop('', space, fail)
  const item = (active: boolean) => `flex w-full items-center gap-1 rounded px-2 py-0.5 text-left text-sm ${active ? 'bg-accent font-medium' : 'hover:bg-accent/60'}`
  return (
    <nav aria-label="폴더" className="space-y-3">
      <div>
        <button type="button" className={item(space.folder === null)} onClick={() => space.select(null)}>
          {allLabel} <span className="text-muted-foreground ml-auto text-xs">{everything}</span>
        </button>
        <button
          type="button"
          {...rootDrop.handlers}
          className={`${item(space.folder === '')} ${rootDrop.over ? 'ring-primary ring-2' : ''}`}
          onClick={() => space.select('')}
          title={`폴더에 속하지 않은 ${noun} 목록입니다. 여기로 끌어다 놓으면 폴더에서 제외됩니다.`}
        >
          폴더 없음 <span className="text-muted-foreground ml-auto text-xs">{loose}</span>
        </button>
      </div>
      <div>
        <div className="mb-1 flex items-center justify-between px-2">
          <span className="text-muted-foreground text-xs font-medium">폴더</span>
          <button type="button" className="text-muted-foreground hover:text-foreground" onClick={() => space.setDialog({ kind: 'new', parent: '' })} aria-label="새 폴더">
            <FolderPlus className="size-4" />
          </button>
        </div>
        {tree.length === 0 ? (
          <p className="text-muted-foreground px-2 text-xs">폴더가 없습니다. 새 폴더를 생성한 후 {josa(noun, '을', '를')} 끌어다 놓으십시오.</p>
        ) : (
          <ul>
            {tree.map((node) => (
              <Row key={node.path} node={node} depth={0} space={space} fail={fail} />
            ))}
          </ul>
        )}
        {failure && (
          <p role="alert" className="text-destructive mt-1 px-2 text-xs">
            {failure}{' '}
            <button type="button" className="underline" onClick={() => setFailure(null)}>
              닫기
            </button>
          </p>
        )}
      </div>
      {years.length > 0 && onYear && (
        <div>
          <span className="text-muted-foreground mb-1 block px-2 text-xs font-medium">생성 연도</span>
          {years.map((one) => (
            <button
              key={one.year}
              type="button"
              aria-pressed={year === one.year}
              className={item(year === one.year)}
              onClick={() => onYear(year === one.year ? null : one.year)}
            >
              {one.year}년 <span className="text-muted-foreground ml-auto text-xs">{one.count}</span>
            </button>
          ))}
        </div>
      )}
    </nav>
  )
}
