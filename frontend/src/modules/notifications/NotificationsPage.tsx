/**
 * 알림 — **나에게 온 것.**
 *
 * 공지가 모두에게 가는 방송이라면 알림은 한 사람에게 가는 편지다. 메일이 없는
 * 환경이라 이것이 유일한 전달 경로이고, 그래서 읽음 상태를 서버가 든다.
 *
 * **하나씩 읽는다.** 「보러 가기」 를 누르거나 「읽음」 을 누르면 그 알림만 읽음이 된다
 * (`POST /notifications/{id}/read`) — 「모두 읽음」 밖에 없으면 하나를 확인하려다 나머지까지
 * 읽은 것이 된다.
 */

import { Link } from 'react-router-dom'

import { api } from '@/shared/api/client'
import type { components } from '@/shared/api/schema'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { PageHeader } from '@/shared/components/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { useResource } from '@/shared/hooks/useResource'
import { shownDateTime } from '@/shared/lib/datetime'

type Notification = components['schemas']['NotificationOut']

export default function NotificationsPage() {
  const list = useResource(() => api.get<Notification[]>('/notifications'), [])
  const unread = (list.data ?? []).filter((one) => !one.read_at).length

  async function markRead(one: Notification) {
    if (one.read_at) return
    await api.post(`/notifications/${one.id}/read`)
    list.reload()
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader
        title="알림"
        description="가입 승인처럼 나에게 온 일들입니다."
        actions={
          <Button
            variant="outline"
            disabled={unread === 0}
            onClick={async () => {
              await api.post('/notifications/read-all')
              list.reload()
            }}
          >
            모두 읽음
          </Button>
        }
      />

      <ErrorNotice error={list.error} />

      {list.data && list.data.length === 0 ? (
        <EmptyState title="알림이 없습니다" hint="가입 승인 같은 일이 생기면 여기에 표시됩니다." />
      ) : (
        <ul className="space-y-2">
          {(list.data ?? []).map((one) => (
            <li
              key={one.id}
              className={one.read_at ? 'rounded-md border p-3 opacity-60' : 'rounded-md border p-3'}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{one.title}</p>
                  {one.body && <p className="text-muted-foreground mt-1 text-sm">{one.body}</p>}
                  {one.link && (
                    // 가면서 읽음으로 — 따로 누르게 하지 않는다.
                    <Link
                      to={one.link}
                      onClick={() => void markRead(one)}
                      className="mt-1 inline-block text-xs underline"
                    >
                      보러 가기
                    </Link>
                  )}
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <span className="text-muted-foreground text-xs">{shownDateTime(one.created_at)}</span>
                  {!one.read_at && (
                    <Button variant="ghost" size="sm" onClick={() => void markRead(one)}>
                      읽음
                    </Button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
