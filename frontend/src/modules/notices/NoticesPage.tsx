/**
 * 공지 — **배포 없이 안내를 전하는 자리.**
 *
 * 메일 서버가 없는 사내 설치에서는 이것이 유일한 전달 경로다. 코드에 박아
 * 배포하는 방식은 고치는 데 배포가 필요해지므로 결국 아무도 안 고친다.
 */

import { useState } from 'react'

import { noticeApi } from '@/modules/notices/api'
import { NoticeBody } from '@/modules/notices/NoticeBody'
import { ApiError } from '@/shared/api/client'
import { useAuth } from '@/shared/auth/AuthContext'
import { isSystemAdmin } from '@/shared/auth/roles'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { PageHeader } from '@/shared/components/PageHeader'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import { Textarea } from '@/shared/components/ui/textarea'
import { useResource } from '@/shared/hooks/useResource'
import { shownDateTime } from '@/shared/lib/datetime'

export default function NoticesPage() {
  const { user } = useAuth()
  const admin = isSystemAdmin(user)
  // **관리자는 초안까지 본다** — 배포가 판마다의 업데이트 안내를 초안으로 넣는다(읽고 발행한다).
  const list = useResource(() => noticeApi.list(admin), [admin])
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [level, setLevel] = useState('info')
  const [isPopup, setIsPopup] = useState(false)
  const [error, setError] = useState<ApiError | Error | null>(null)

  // 일괄 발행은 **배포 안내 초안만** — 손으로 쓰다 둔 초안은 하나씩 「발행」 한다.
  const drafts = (list.data ?? []).filter((one) => !one.published_at && one.from_release)

  async function submit() {
    setError(null)
    try {
      await noticeApi.create({ title, body, level, is_popup: isPopup, publish: true })
      setTitle('')
      setBody('')
      setLevel('info')
      setIsPopup(false)
      list.reload()
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('알 수 없는 오류'))
    }
  }

  async function publish(id?: string) {
    setError(null)
    try {
      if (id) await noticeApi.publish(id)
      else await noticeApi.publishDrafts()
      list.reload()
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('알 수 없는 오류'))
    }
  }

  async function remove(id: string) {
    setError(null)
    try {
      await noticeApi.remove(id)
      list.reload()
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('알 수 없는 오류'))
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader title="공지" description="시스템 안내와 점검 일정을 여기서 전합니다." />

      {admin && (
        <div className="space-y-3 rounded-md border p-4">
          <Input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="제목"
          />
          <Textarea
            value={body}
            onChange={(event) => setBody(event.target.value)}
            placeholder="내용"
            rows={4}
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <Select value={level} onValueChange={setLevel}>
                <SelectTrigger className="h-8 w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="info">안내</SelectItem>
                  <SelectItem value="warning">주의</SelectItem>
                  <SelectItem value="urgent">긴급</SelectItem>
                </SelectContent>
              </Select>
              <label className="text-muted-foreground flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={isPopup}
                  onChange={(event) => setIsPopup(event.target.checked)}
                />
                {/* 팝업은 읽지 않은 사람에게 스스로 뜬다 — 급한 안내에만 쓴다. */}
                팝업으로 띄우기
              </label>
            </div>
            <Button onClick={submit} disabled={!title || !body}>
              게시
            </Button>
          </div>
        </div>
      )}

      <ErrorNotice error={error ?? list.error} />

      {admin && drafts.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-dashed p-3 text-sm">
          <p className="text-muted-foreground">
            배포 안내 초안 {drafts.length}건 — 읽어 보고 발행하면 그 판의 날짜에 섭니다. 손으로 쓴 초안은 하나씩
            발행합니다.
          </p>
          <Button size="sm" onClick={() => publish()}>
            배포 안내 초안 {drafts.length}건 모두 발행
          </Button>
        </div>
      )}

      {list.data && list.data.length === 0 ? (
        <EmptyState
          title="공지가 없습니다"
          hint={
            admin
              ? '위에서 첫 공지를 올릴 수 있습니다.'
              : '아직 전할 안내가 없다는 뜻입니다.'
          }
        />
      ) : (
        <ul className="space-y-4">
          {(list.data ?? []).map((one) => (
            <li key={one.id} className="rounded-md border p-4">
              <div className="flex items-start justify-between gap-3">
                <h2 className="flex items-center gap-2 font-medium">
                  <StatusBadge kind="notice" value={one.level} />
                  {one.title}
                </h2>
                <span className="text-muted-foreground shrink-0 text-xs">
                  {shownDateTime(one.published_at ?? one.created_at)}
                </span>
              </div>
              <NoticeBody text={one.body} className="mt-2" />
              <div className="mt-2 flex items-center justify-between">
                <p className="text-muted-foreground text-xs">
                  {one.from_release ? '배포 안내' : (one.author_name ?? '시스템')}
                  {one.published_at ? '' : ' · 초안'}
                </p>
                {admin && (
                  <div className="flex items-center gap-1">
                    {!one.published_at && (
                      <Button variant="outline" size="sm" onClick={() => publish(one.id)}>
                        발행
                      </Button>
                    )}
                    <Button variant="ghost" size="sm" onClick={() => remove(one.id)}>
                      삭제
                    </Button>
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
