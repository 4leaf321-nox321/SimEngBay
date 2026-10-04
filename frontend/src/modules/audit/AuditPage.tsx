/**
 * 변경 이력 · 접근 로그.
 *
 * **생성·수정·삭제가 없다.** 고칠 수 있으면 감사가 아니다 — 쓰는 길은
 * 서버의 도메인 코드 하나뿐이다.
 *
 * 변경 이력에 남는 것은 **되돌릴 수 없거나 권한이 실린 일**만이다. 값 하나 고친 것까지
 * 남기면 그 안에서 정작 찾을 것을 못 찾는다. 서버가 한 일(`action`) · 대상 표(`target_table`)로
 * 거를 수 있다 — 화면이 그 거름을 쓴다.
 *
 * 접근 로그는 **누가 언제 무엇을 호출했나** — 사용자 지원용이고 시스템 관리자만 본다(남의 활동
 * 이력이다). 서버가 따로 두는 기록이라 화면도 따로다.
 */

import { useState } from 'react'

import { api } from '@/shared/api/client'
import type { Page } from '@/shared/api/paging'
import type { components } from '@/shared/api/schema'
import { useAuth } from '@/shared/auth/AuthContext'
import { isSystemAdmin } from '@/shared/auth/roles'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { PageHeader } from '@/shared/components/PageHeader'
import { Pagination } from '@/shared/components/Pagination'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'
import { useResource } from '@/shared/hooks/useResource'
import { shownDateTime } from '@/shared/lib/datetime'

type AuditEntry = components['schemas']['AuditEntryOut']
type AccessLog = components['schemas']['AccessLogOut']

function shownChanges(changes: AuditEntry['changes']): string {
  // `_` 로 시작하는 키는 기록에 붙인 표식(묶음 번호 등)이다 — 칸이 아니다.
  const parts = Object.entries(changes ?? {})
    .filter(([key]) => !key.startsWith('_'))
    .map(([key, value]) => {
      const change = (value ?? {}) as { before?: unknown; after?: unknown }
      return `${key}: ${String(change.before ?? '—')} -> ${String(change.after ?? '—')}`
    })
  return parts.join(', ') || '—'
}

/** 서버가 강제하는 상한 안에서 고른 값(`shared/pagination.py` 의 MAX_LIMIT 는 200). */
const PER_PAGE = 50

function Entries() {
  const [offset, setOffset] = useState(0)
  const [action, setAction] = useState('')
  const [target, setTarget] = useState('')
  const page = useResource(() => {
    const params = new URLSearchParams({ limit: String(PER_PAGE), offset: String(offset) })
    if (action.trim()) params.set('action', action.trim())
    if (target.trim()) params.set('target_table', target.trim())
    return api.get<Page<AuditEntry>>(`/audit/entries?${params}`)
  }, [offset, action, target])

  return (
    <div className="space-y-4">
      {/* **서버가 거르는 칸 둘** — 한 일과 대상 표. 정확히 같은 값만 걸린다. */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="audit-action">한 일</Label>
          <Input
            id="audit-action"
            className="h-8 w-48 font-mono"
            value={action}
            onChange={(event) => {
              setOffset(0)
              setAction(event.target.value)
            }}
            placeholder="예: UPDATE"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="audit-target">대상 표</Label>
          <Input
            id="audit-target"
            className="h-8 w-48 font-mono"
            value={target}
            onChange={(event) => {
              setOffset(0)
              setTarget(event.target.value)
            }}
            placeholder="예: users"
          />
        </div>
      </div>

      <ErrorNotice error={page.error} />

      {page.data && page.data.items.length === 0 ? (
        <EmptyState
          title="기록이 없습니다"
          hint={
            action || target
              ? '거르는 값과 정확히 같은 기록만 표시합니다 — 칸을 비우면 전부 표시합니다.'
              : '아직 남길 만한 변경이 없었습니다.'
          }
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>시각</TableHead>
              <TableHead>한 일</TableHead>
              <TableHead>누가</TableHead>
              <TableHead>대상</TableHead>
              <TableHead>바뀐 것</TableHead>
              <TableHead>요청 ID</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(page.data?.items ?? []).map((one) => (
              <TableRow key={one.id}>
                <TableCell className="whitespace-nowrap">{shownDateTime(one.created_at)}</TableCell>
                <TableCell className="font-mono text-xs">{one.action}</TableCell>
                <TableCell>
                  {one.actor_label}
                  {/* **사람과 통로를 함께 보여 준다.** 「관리자가 바꿨습니다」 만
                      말하면, 그 관리자가 직접 눌렀는지 자기 토큰을 쥔 스크립트가
                      눌렀는지는 다른 이야기인데 구별할 방법이 없다. */}
                  {(one.actor_client || one.actor_token) && (
                    <p className="text-muted-foreground text-xs">
                      {[one.actor_client, one.actor_token].filter(Boolean).join(' · ')}
                    </p>
                  )}
                </TableCell>
                <TableCell>
                  {one.target_label}
                  <p className="text-muted-foreground font-mono text-xs">{one.target_table}</p>
                </TableCell>
                <TableCell className="text-muted-foreground text-xs">
                  {shownChanges(one.changes)}
                  {one.reason && <p className="mt-1">사유: {one.reason}</p>}
                </TableCell>
                {/* **로그와 잇는 끈이다.** 이 값으로 app.log 에서 그 요청의 모든
                    줄을 찾을 수 있다. */}
                <TableCell className="font-mono text-xs">{one.request_id ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {/* **없으면 50건이 넘는 순간 나머지를 볼 방법이 없다** — 그리고 목록은
          잘렸다는 말을 하지 않으므로 사람은 그것이 전부라고 읽는다. */}
      {page.data && (
        <Pagination
          total={page.data.total}
          limit={page.data.limit}
          offset={page.data.offset}
          onChange={setOffset}
        />
      )}
    </div>
  )
}

/** 접근 로그 — 누가 언제 무엇을 호출했나. 폴링 경로는 서버가 남기지 않는다(`access_log`). */
function AccessLogs() {
  const [offset, setOffset] = useState(0)
  const page = useResource(
    () => api.get<Page<AccessLog>>(`/audit/access?limit=${PER_PAGE}&offset=${offset}`),
    [offset],
  )

  return (
    <div className="space-y-4">
      <ErrorNotice error={page.error} />
      {page.data && page.data.items.length === 0 ? (
        <EmptyState title="접근 기록이 없습니다" hint="로그인 · 쓰기 요청이 생기면 여기에 표시됩니다." />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>시각</TableHead>
              <TableHead>누가</TableHead>
              <TableHead>요청</TableHead>
              <TableHead>응답</TableHead>
              <TableHead>주소</TableHead>
              <TableHead>요청 ID</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(page.data?.items ?? []).map((one) => (
              <TableRow key={one.id}>
                <TableCell className="whitespace-nowrap">{shownDateTime(one.created_at)}</TableCell>
                <TableCell>{one.user_label ?? '—'}</TableCell>
                <TableCell className="font-mono text-xs">
                  {one.method} {one.path}
                  {one.action !== 'API' && <span className="text-muted-foreground"> · {one.action}</span>}
                </TableCell>
                <TableCell
                  className={
                    one.status_code >= 400 ? 'text-destructive font-mono text-xs' : 'font-mono text-xs'
                  }
                >
                  {one.status_code}
                </TableCell>
                <TableCell className="font-mono text-xs">{one.client_ip ?? '—'}</TableCell>
                <TableCell className="font-mono text-xs">{one.request_id ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {page.data && (
        <Pagination
          total={page.data.total}
          limit={page.data.limit}
          offset={page.data.offset}
          onChange={setOffset}
        />
      )}
    </div>
  )
}

export default function AuditPage() {
  const { user } = useAuth()
  const admin = isSystemAdmin(user)

  return (
    <div className="space-y-6">
      <PageHeader
        title="변경 이력"
        description="되돌릴 수 없거나 권한이 실린 변경만 남습니다. 여기서는 수정할 수 없습니다."
      />
      {admin ? (
        <Tabs defaultValue="entries">
          <TabsList>
            <TabsTrigger value="entries">변경 이력</TabsTrigger>
            <TabsTrigger value="access">접근 로그</TabsTrigger>
          </TabsList>
          <TabsContent value="entries" className="pt-4">
            <Entries />
          </TabsContent>
          <TabsContent value="access" className="pt-4">
            <AccessLogs />
          </TabsContent>
        </Tabs>
      ) : (
        <Entries />
      )}
    </div>
  )
}
