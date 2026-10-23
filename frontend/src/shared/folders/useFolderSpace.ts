/**
 * 폴더를 쓰는 목록 화면의 상태 — 고른 폴더, 골라 둔 항목, 아직 빈 폴더, 열린 창.
 *
 * 해석 작업 · DOE 목록이 같은 손놀림을 쓴다(왼쪽 나무, 고르고 옮기기, 끌어다 놓기, 폴더 이름
 * 바꾸기 · 지우기) — CompCore 의 내 작업 · 부품 · 지그와도 같다. 폴더 나무는 여기서 불러온다. 목록을 다시 불러오는 것은 화면
 * 몫이다 — 옮기고 나면 `version` 이 오르니 목록의 deps 에 넣는다.
 */

import { useState } from 'react'
import type { DragEvent } from 'react'

import { DRAG_TYPE, isWithin, loadPending, parentOf, savePending } from '@/shared/folders/paths'
import type { FolderApi, FolderRow } from '@/shared/folders/paths'
import { useResource } from '@/shared/hooks/useResource'

export type FolderDialogState =
  | { kind: 'new'; parent: string }
  | { kind: 'rename'; path: string }
  | { kind: 'move' }
  | { kind: 'remove'; path: string }
  | null

export interface FolderSpace {
  /** null = 전부, '' = 폴더에 넣지 않은 것만. 고른 폴더는 하위까지 보인다. */
  folder: string | null
  select: (path: string | null) => void
  rows: FolderRow[]
  /** 서버가 아는 폴더(맨 위 빼고). */
  known: string[]
  pending: string[]
  chosen: Set<string>
  setChosen: (next: Set<string>) => void
  toggle: (id: string) => void
  dialog: FolderDialogState
  setDialog: (next: FolderDialogState) => void
  /** 옮기거나 이름을 바꾸면 오른다 — 목록의 deps 에 넣는다. */
  version: number
  /** 폴더 나무만 다시 센다 — 항목을 되살리거나 지운 뒤. */
  refresh: () => void
  moveTo: (ids: string[], path: string) => Promise<void>
  createFolder: (path: string) => void
  renameFolder: (from: string, to: string) => Promise<void>
  removeFolder: (path: string) => Promise<void>
  /** 끄는 줄이 골라 둔 것이면 고른 것 전부를, 아니면 그 줄 하나를 싣는다. */
  startDrag: (event: DragEvent, id: string) => void
}

export function useFolderSpace(
  space: string,
  api: FolderApi,
  options: {
    /** 고른 폴더가 바뀌면 — 화면이 첫 쪽으로 돌아간다. */
    onRefilter?: () => void
    /** 나무를 다시 셀 때 — 템플릿의 자리(scope)처럼 보이는 것이 바뀌면. */
    deps?: unknown[]
  } = {},
): FolderSpace {
  const { onRefilter = () => {}, deps = [] } = options
  const [folder, setFolder] = useState<string | null>(null)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [pending, setPending] = useState<string[]>(() => loadPending(space))
  const [dialog, setDialog] = useState<FolderDialogState>(null)
  const [version, setVersion] = useState(0)
  const [tick, setTick] = useState(0)
  const tree = useResource(() => api.folders(), [version, tick, ...deps])
  const rows: FolderRow[] = tree.data ?? []
  const known = rows.map((one) => one.path).filter(Boolean)
  const hasItems = (path: string) => known.some((one) => isWithin(one, path))

  function keepPending(next: string[]) {
    setPending(next)
    savePending(space, next)
  }

  function select(path: string | null) {
    setFolder(path)
    setChosen(new Set())
    onRefilter()
  }

  function changed() {
    setChosen(new Set())
    setVersion((value) => value + 1)
  }

  return {
    folder,
    select,
    rows,
    known,
    pending,
    chosen,
    setChosen,
    toggle(id) {
      const next = new Set(chosen)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      setChosen(next)
    },
    dialog,
    setDialog,
    version,
    refresh: () => setTick((value) => value + 1),
    async moveTo(ids, path) {
      await api.move(ids, path)
      // 항목이 들어간 빈 폴더는 이제 서버가 안다 — 이 브라우저의 목록에서 뺀다.
      keepPending(pending.filter((one) => !isWithin(path, one)))
      changed()
    },
    createFolder(path) {
      if (!known.includes(path) && !pending.includes(path)) keepPending([...pending, path])
      select(path)
    },
    async renameFolder(from, to) {
      if (hasItems(from)) await api.renameFolder(from, to)
      keepPending(pending.map((one) => (isWithin(one, from) ? to + one.slice(from.length) : one)))
      if (folder !== null && isWithin(folder, from)) setFolder(to + folder.slice(from.length))
      changed()
    },
    async removeFolder(path) {
      // 폴더 지우기 = 위 폴더로 합치기. 항목은 지우지 않는다.
      if (hasItems(path)) await api.renameFolder(path, parentOf(path))
      keepPending(pending.filter((one) => !isWithin(one, path)))
      if (folder !== null && isWithin(folder, path)) setFolder(parentOf(path) || null)
      changed()
    },
    startDrag(event, id) {
      const ids = chosen.has(id) ? [...chosen] : [id]
      event.dataTransfer.setData(DRAG_TYPE, JSON.stringify(ids))
      event.dataTransfer.effectAllowed = 'move'
    },
  }
}
