/**
 * 폴더를 쓰는 목록 화면의 나머지 조각 — 폴더 창들, 지금 보는 곳, 골라 둔 것 막대, 좁은 화면의
 * 폴더 고르개. 상태는 `useFolderSpace` 가 들고 있다.
 */

import { useState } from 'react'
import type { ReactNode } from 'react'

import { FolderDialog } from '@/shared/folders/FolderDialog'
import { joinPath, josa, nameOf, parentOf, shownPath } from '@/shared/folders/paths'
import type { FolderSpace } from '@/shared/folders/useFolderSpace'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { Button } from '@/shared/components/ui/button'

interface FolderDialogsProps {
  space: FolderSpace
  /** 「작업」 · 「DOE」 — 창의 문구에 들어간다. */
  noun: string
  /** 여럿이 함께 쓰는 공간인가 — 남의 것이 든 폴더는 관리자만 옮긴다고 적는다. */
  shared?: boolean
}

export function FolderDialogs({ space, noun, shared = false }: FolderDialogsProps) {
  const { dialog, setDialog, known, pending } = space
  const close = () => setDialog(null)
  const others = shared ? ` 다른 사용자의 ${josa(noun, '이', '가')} 포함된 폴더는 관리자만 변경할 수 있습니다.` : ''
  return (
    <>
      <FolderDialog
        open={dialog?.kind === 'new'}
        title="새 폴더"
        description={`${dialog?.kind === 'new' && dialog.parent ? `‘${shownPath(dialog.parent)}’ 폴더 안에` : '최상위에'} 폴더를 생성합니다. ${josa(noun, '을', '를')} 끌어다 놓으면 해당 폴더로 이동합니다.`}
        confirmLabel="생성"
        onSubmit={(name) => space.createFolder(joinPath(dialog?.kind === 'new' ? dialog.parent : '', name))}
        onClose={close}
      />
      <FolderDialog
        open={dialog?.kind === 'rename'}
        title="폴더 이름 변경·이동"
        description={`경로를 수정하면 하위 폴더와 그 안의 ${josa(noun, '이', '가')} 함께 이동합니다. 이미 있는 폴더이면 병합됩니다.${others}`}
        initial={dialog?.kind === 'rename' ? dialog.path : ''}
        suggestions={known}
        confirmLabel="변경"
        onSubmit={async (to) => {
          if (dialog?.kind === 'rename') await space.renameFolder(dialog.path, to)
        }}
        onClose={close}
      />
      <FolderDialog
        open={dialog?.kind === 'move'}
        title={`${noun} ${space.chosen.size}개를 폴더로 이동`}
        description="기존 폴더를 선택하거나 새 경로를 입력하십시오. 비워 두면 최상위(폴더 없음)로 이동합니다."
        suggestions={[...known, ...pending]}
        allowEmpty
        confirmLabel="이동"
        onSubmit={(path) => space.moveTo([...space.chosen], path)}
        onClose={close}
      />
      <ConfirmDialog
        open={dialog?.kind === 'remove'}
        title="폴더 삭제"
        description={
          dialog?.kind === 'remove'
            ? `‘${nameOf(dialog.path)}’ 폴더를 삭제하시겠습니까? 폴더 안의 ${josa(noun, '과', '와')} 하위 폴더는 ${parentOf(dialog.path) ? `상위 폴더(‘${parentOf(dialog.path)}’)` : '최상위(폴더 없음)'}로 이동하며, ${josa(noun, '은', '는')} 삭제되지 않습니다.${others}`
            : ''
        }
        confirmLabel="삭제"
        onConfirm={async () => {
          if (dialog?.kind === 'remove') await space.removeFolder(dialog.path)
        }}
        onClose={close}
      />
    </>
  )
}

/** 지금 보는 폴더 — 위 폴더로 바로 간다. 고른 폴더가 없고 `extra` 도 없으면 안 보인다. */
export function FolderCrumbs({ space, allLabel, extra }: { space: FolderSpace; allLabel: string; extra?: ReactNode }) {
  const { folder } = space
  if (folder === null && !extra) return null
  return (
    <nav aria-label="현재 위치" className="text-muted-foreground mb-2 flex flex-wrap items-center gap-1 text-sm">
      <button type="button" className="hover:underline" onClick={() => space.select(null)}>
        {allLabel}
      </button>
      {folder === '' && <span>› 폴더 없음</span>}
      {folder
        ? folder.split('/').map((name, index, parts) => (
            <span key={index}>
              ›{' '}
              <button type="button" className="hover:underline" onClick={() => space.select(parts.slice(0, index + 1).join('/'))}>
                {name}
              </button>
            </span>
          ))
        : null}
      {extra}
    </nav>
  )
}

/**
 * 골라 둔 것이 있을 때 — 몇 개인지, 폴더로 옮기기. `children` 은 그 공간만의 동작(게시 ·
 * 게시 해제 · 삭제)을 「폴더로 이동」 옆에 둔다.
 */
export function ChosenBar({ space, children }: { space: FolderSpace; children?: ReactNode }) {
  if (space.chosen.size === 0) return null
  return (
    <div className="bg-accent/50 mb-2 flex items-center gap-2 rounded-md px-3 py-1.5 text-sm">
      <span>{space.chosen.size}개 선택됨</span>
      <Button size="sm" variant="outline" className="h-7" onClick={() => space.setDialog({ kind: 'move' })}>
        폴더로 이동
      </Button>
      {children}
      <button type="button" className="text-muted-foreground text-xs hover:underline" onClick={() => space.setChosen(new Set())}>
        선택 해제
      </button>
      <span className="text-muted-foreground ml-auto text-xs">왼쪽 폴더 목록으로 끌어다 놓아 이동할 수도 있습니다.</span>
    </div>
  )
}

/** 좁은 화면의 폴더 고르개 — 넓으면 왼쪽 나무가 한다. */
export function FolderSelect({ space, allLabel }: { space: FolderSpace; allLabel: string }) {
  return (
    <select
      aria-label="폴더 선택"
      className="h-8 rounded-md border px-2 text-sm md:hidden"
      value={space.folder === null ? '__all__' : space.folder}
      onChange={(event) => space.select(event.target.value === '__all__' ? null : event.target.value)}
    >
      <option value="__all__">{allLabel}</option>
      <option value="">폴더 없음</option>
      {[...space.known, ...space.pending].map((one) => (
        <option key={one} value={one}>
          {shownPath(one)}
        </option>
      ))}
    </select>
  )
}

/** 줄 머리의 고르기 칸 — 옮길 수 없는 줄(남의 것)은 막아 둔다. */
export function PickBox({ space, id, name, disabled = false }: { space: FolderSpace; id: string; name: string; disabled?: boolean }) {
  return (
    <input
      type="checkbox"
      aria-label={`${name} 선택`}
      checked={space.chosen.has(id)}
      disabled={disabled}
      title={disabled ? '작성자와 관리자만 이동할 수 있습니다.' : undefined}
      onChange={() => space.toggle(id)}
    />
  )
}

/** 머리줄의 「이 쪽 모두 고르기」 — 고를 수 있는 줄만. */
export function PickAll({ space, ids }: { space: FolderSpace; ids: string[] }) {
  return (
    <input
      type="checkbox"
      aria-label="이 페이지 전체 선택"
      disabled={ids.length === 0}
      checked={ids.length > 0 && ids.every((id) => space.chosen.has(id))}
      onChange={(event) => space.setChosen(event.target.checked ? new Set(ids) : new Set())}
    />
  )
}

/** 이 줄이 놓인 폴더 — 지금 보는 폴더와 다를 때만(하위 폴더의 것). */
export function RowFolder({ space, folder }: { space: FolderSpace; folder: string }) {
  if (!folder || folder === space.folder) return null
  return <p className="text-muted-foreground text-[11px]">📁 {shownPath(folder)}</p>
}

/**
 * 상세 화면의 한 줄 — 이 항목이 놓인 폴더, 고칠 수 있으면 「옮기기」. 폴더는 꼬리표와 달리 한
 * 곳이다.
 */
export function FolderLine({
  folder,
  editable,
  suggestions,
  onMove,
}: {
  folder: string
  editable: boolean
  /** 고를 수 있는 폴더 — 창을 열 때 부른다. */
  suggestions: () => Promise<{ path: string }[]>
  onMove: (folder: string) => Promise<unknown>
}) {
  const [open, setOpen] = useState(false)
  const [known, setKnown] = useState<string[]>([])
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-muted-foreground">폴더</span>
      <span>{folder ? shownPath(folder) : '없음(최상위)'}</span>
      {editable && (
        <button
          type="button"
          className="text-muted-foreground underline"
          onClick={() => {
            setOpen(true)
            suggestions()
              .then((rows) => setKnown(rows.map((one) => one.path).filter(Boolean)))
              .catch(() => setKnown([]))
          }}
        >
          이동
        </button>
      )}
      <FolderDialog
        open={open}
        title="폴더 이동"
        description="기존 폴더를 선택하거나 새 경로(예: 고객A/2026)를 입력하십시오. 비워 두면 최상위로 이동합니다."
        initial={folder}
        suggestions={known}
        allowEmpty
        confirmLabel="이동"
        onSubmit={async (path) => {
          await onMove(path)
        }}
        onClose={() => setOpen(false)}
      />
    </div>
  )
}
