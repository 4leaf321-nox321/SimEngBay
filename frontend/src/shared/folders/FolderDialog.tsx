/**
 * 폴더 경로를 묻는 창 — 새 폴더 · 이름 바꾸기 · 옮기기가 같이 쓴다. 있는 폴더를 고르거나
 * 새 경로(`고객A/2026`)를 적는다. 빈 것은 맨 위.
 */

import { useEffect, useState } from 'react'

import { normalizePath } from '@/shared/folders/paths'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { Input } from '@/shared/components/ui/input'

interface FolderDialogProps {
  open: boolean
  title: string
  description: string
  /** 처음 칸에 든 값. */
  initial?: string
  /** 고를 수 있는 있는 폴더들. */
  suggestions?: string[]
  /** 빈 경로(맨 위)를 받나 — 새 폴더 이름은 비울 수 없다. */
  allowEmpty?: boolean
  confirmLabel?: string
  onSubmit: (path: string) => Promise<void> | void
  onClose: () => void
}

export function FolderDialog({ open, title, description, initial = '', suggestions = [], allowEmpty = false, confirmLabel = '확인', onSubmit, onClose }: FolderDialogProps) {
  const [value, setValue] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  useEffect(() => {
    if (open) {
      setValue(initial)
      setError(null)
    }
  }, [open, initial])
  const path = normalizePath(value)
  const usable = allowEmpty || path.length > 0

  async function submit() {
    if (!usable) return
    setBusy(true)
    setError(null)
    try {
      await onSubmit(path)
      onClose()
    } catch (failure) {
      setError(failure instanceof Error ? failure : new Error(String(failure)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <Input
          aria-label="폴더 경로"
          list="folder-suggestions"
          value={value}
          placeholder={allowEmpty ? '예: 고객A/2026 (비워 두면 최상위)' : '예: 고객A/2026'}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void submit()
          }}
          autoFocus
        />
        <datalist id="folder-suggestions">
          {suggestions.filter(Boolean).map((one) => (
            <option key={one} value={one} />
          ))}
        </datalist>
        <p className="text-muted-foreground text-xs">
          {path ? `→ ${path.split('/').join(' › ')}` : allowEmpty ? '→ 최상위(폴더 없음)' : '폴더 이름을 입력하십시오.'}
        </p>
        <ErrorNotice error={error} />
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            취소
          </Button>
          <Button onClick={() => void submit()} disabled={busy || !usable}>
            {busy ? '처리 중…' : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
