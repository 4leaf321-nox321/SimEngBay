/**
 * 목록에서 **고른 것 여럿에** — 게시 · 게시 해제 · 삭제. 폴더 막대(`ChosenBar`)의 「폴더로 이동」
 * 옆에 선다. 해석 작업 · DOE 목록이 같이 쓴다.
 *
 * 게시와 삭제는 **확인을 받는다** — 게시는 조직의 누구나 보게 되고, 삭제는 작업 폴더까지 지워
 * 되돌릴 수 없다(낱개 단추와 같은 규칙).
 */

import { useState } from 'react'
import { Share2, Trash2, Undo2 } from 'lucide-react'

import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { Button } from '@/shared/components/ui/button'

type Pending = 'publish' | 'unpublish' | 'remove' | null

interface ChosenActionsProps {
  count: number
  /** 「작업」 · 「DOE」. */
  noun: string
  /** 삭제 창에 덧붙일 말 — DOE 는 설계점 전부가 사라진다. */
  removeNote?: string
  onPublish: () => Promise<void>
  onUnpublish: () => Promise<void>
  onRemove: () => Promise<void>
}

export function ChosenActions({ count, noun, removeNote, onPublish, onUnpublish, onRemove }: ChosenActionsProps) {
  const [pending, setPending] = useState<Pending>(null)
  const close = () => setPending(null)
  return (
    <>
      <Button size="sm" variant="outline" className="h-7" onClick={() => setPending('publish')}>
        <Share2 className="size-3.5" />
        게시
      </Button>
      <Button size="sm" variant="outline" className="h-7" onClick={() => setPending('unpublish')}>
        <Undo2 className="size-3.5" />
        게시 해제
      </Button>
      <Button size="sm" variant="outline" className="text-destructive h-7" onClick={() => setPending('remove')}>
        <Trash2 className="size-3.5" />
        삭제
      </Button>

      <ConfirmDialog
        open={pending === 'publish'}
        title={`${noun} ${count}개 게시`}
        description={`고른 ${noun}의 끝난 결과를 게시합니다 — 조직의 누구나 읽을 수 있습니다(바꾸는 것은 실행한 사람뿐). 끝나지 않은 것은 건너뜁니다.`}
        confirmLabel="게시"
        onConfirm={onPublish}
        onClose={close}
      />
      <ConfirmDialog
        open={pending === 'unpublish'}
        title={`${noun} ${count}개 게시 해제`}
        description={`고른 ${noun}의 게시를 해제합니다 — 다시 실행한 사람과 시스템 관리자만 봅니다.`}
        confirmLabel="게시 해제"
        onConfirm={onUnpublish}
        onClose={close}
      />
      <ConfirmDialog
        open={pending === 'remove'}
        title={`${noun} ${count}개 삭제`}
        description={
          <div className="space-y-2">
            <p>
              고른 {noun}과 그 작업 폴더(결과 · 그림 · 중간 파일)를 지웁니다. 메시 수렴 점검 수준과 올린 실측도
              함께 사라지고, 게시된 것은 다른 사람의 화면에서도 사라집니다. 되돌릴 수 없습니다.
            </p>
            {removeNote && <p>{removeNote}</p>}
            <p>도는 것은 지우지 않습니다 — 먼저 멈추세요.</p>
          </div>
        }
        confirmLabel="삭제"
        destructive
        onConfirm={onRemove}
        onClose={close}
      />
    </>
  )
}
