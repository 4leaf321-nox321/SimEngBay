/**
 * 부서 멤버.
 *
 * **마지막 관리자는 뺄 수 없다.** 서버가 막지만 화면도 그 이유를 말해 준다 —
 * 눌러 보고 알게 하면 사람은 그것을 고장으로 읽는다.
 */

import { useState } from 'react'
import { useParams } from 'react-router-dom'

import { workspaceApi } from '@/modules/workspaces/api'
import { ApiError } from '@/shared/api/client'
import { useAuth } from '@/shared/auth/AuthContext'
import { isManagerOf } from '@/shared/auth/roles'
import { CopyMailAddresses } from '@/shared/components/CopyMailAddresses'
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'
import { useResource } from '@/shared/hooks/useResource'
import { shownDate } from '@/shared/lib/datetime'

export default function MembersPage() {
  const { slug = '' } = useParams<{ slug: string }>()
  const { user } = useAuth()
  const list = useResource(() => workspaceApi.members(slug), [slug])
  const [email, setEmail] = useState('')
  const [error, setError] = useState<ApiError | Error | null>(null)
  // 메일 주소를 복사할 멤버 — 목록이 다시 와도 남은 멤버만 센다.
  const [chosen, setChosen] = useState<Set<string>>(() => new Set())
  const rows = list.data ?? []
  const chosenRows = rows.filter((one) => chosen.has(one.user_id))
  const allChosen = rows.length > 0 && chosenRows.length === rows.length

  function toggle(id: string) {
    setChosen((now) => {
      const next = new Set(now)
      if (!next.delete(id)) next.add(id)
      return next
    })
  }

  // **고칠 수 없는 사람에게 단추를 보이지 않는다.** 판정은 서버가 하지만, 눌러
  // 보고 403 을 아는 화면은 "할 수 있는 일" 을 알려 주지 못한다.
  const canEdit = isManagerOf(user, slug)

  async function act(run: () => Promise<unknown>) {
    setError(null)
    try {
      await run()
      list.reload()
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('알 수 없는 오류'))
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="부서 멤버"
        description="관리자는 이 부서의 자료와 멤버를 고칠 수 있습니다."
      />

      {canEdit && (
        <form
          className="flex max-w-md gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            act(async () => {
              await workspaceApi.addMember(slug, email, 'member')
              setEmail('')
            })
          }}
        >
          <Input
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="추가할 계정의 아이디"
            required
          />
          <Button type="submit">추가</Button>
        </form>
      )}

      <ErrorNotice error={error ?? list.error} />

      {list.data && list.data.length === 0 ? (
        <EmptyState
          title="멤버가 없습니다"
          hint="계정을 만들 때 부서를 정하거나, 위에서 아이디로 추가하세요."
        />
      ) : (
        <div className="space-y-3">
          <CopyMailAddresses ids={chosenRows.map((one) => one.email)} />
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8">
                  <input
                    type="checkbox"
                    aria-label="모든 멤버 고르기"
                    checked={allChosen}
                    ref={(box) => {
                      if (box) box.indeterminate = chosenRows.length > 0 && !allChosen
                    }}
                    onChange={() =>
                      setChosen(allChosen ? new Set() : new Set(rows.map((one) => one.user_id)))
                    }
                  />
                </TableHead>
                <TableHead>이름</TableHead>
                <TableHead>아이디</TableHead>
                <TableHead>계정 상태</TableHead>
                <TableHead>역할</TableHead>
                <TableHead>합류</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((one) => (
                <TableRow key={one.user_id}>
                  <TableCell>
                    <input
                      type="checkbox"
                      aria-label={`${one.display_name} 고르기`}
                      checked={chosen.has(one.user_id)}
                      onChange={() => toggle(one.user_id)}
                    />
                  </TableCell>
                  <TableCell>{one.display_name}</TableCell>
                  <TableCell className="font-mono text-xs">{one.email}</TableCell>
                  <TableCell>
                    <StatusBadge kind="account" value={one.status} />
                  </TableCell>
                  <TableCell>
                    {canEdit ? (
                      <Select
                        value={one.role}
                        onValueChange={(role) =>
                          act(() => workspaceApi.setRole(slug, one.user_id, role))
                        }
                      >
                        <SelectTrigger className="h-8 w-32">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="member">멤버</SelectItem>
                          <SelectItem value="manager">부서 관리자</SelectItem>
                        </SelectContent>
                      </Select>
                    ) : (
                      <span className="text-sm">
                        {one.role === 'manager' ? '부서 관리자' : '멤버'}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>{shownDate(one.joined_at)}</TableCell>
                  <TableCell className="text-right">
                    {canEdit && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => act(() => workspaceApi.removeMember(slug, one.user_id))}
                      >
                        빼기
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
