/**
 * 온톨로지 — **Standard Platform 이 정의 · 공개한 기준정보의 사본.**
 *
 * 정본은 Standard Platform 이다. 여기서는 고치지 않는다 — 양쪽에서 고칠 수 있게 두면 다음 수신이
 * 한쪽 수정을 말없이 덮는다(SP 연동 지침서 §12-A 2). 바뀌는 길은 SP 에서 고치고 다음 수신을
 * 기다리거나, 시스템 관리자가 「지금 받기」 를 누르는 것이다.
 *
 * `?type=<slug>&key=<식별자>` 로 오면 그 타입을 고르고 그 객체를 연다 — DOE 화면이 CompCore 가
 * 이은 기준정보(적용 모델 …)를 여기로 잇는다(`StudyOntology`).
 */

import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import {
  ontologyApi,
  type OntologyEdge,
  type OntologyObject,
  type OntologyProperty,
  type OntologyRun,
  type OntologyStatus,
  type OntologyType,
} from '@/modules/ontology/api'
import { ApiError } from '@/shared/api/client'
import { useAuth } from '@/shared/auth/AuthContext'
import { isSystemAdmin } from '@/shared/auth/roles'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { PageHeader } from '@/shared/components/PageHeader'
import { Pagination } from '@/shared/components/Pagination'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { Input } from '@/shared/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'
import { useResource } from '@/shared/hooks/useResource'
import { shownDateTime } from '@/shared/lib/datetime'

const PAGE = 50
/** 표에 펼칠 칸 수 — 나머지는 객체를 열면 보인다. */
const SHOWN_PROPERTIES = 4
/** 받는 중일 때 상태를 다시 묻는 간격(ms). */
const POLL_MS = 2000

const TRIGGERS: Record<string, string> = { timer: '주기', manual: '화면', script: '명령' }
const REMOVED: Record<string, string> = {
  deleted: 'SP 에서 지움',
  merged: '합쳐짐',
  hidden: '토큰으로 안 보임',
  absent: '전량 대조에서 안 옴',
}

export default function OntologyPage() {
  const { user } = useAuth()
  const admin = isSystemAdmin(user)
  const status = useResource(() => ontologyApi.status(), [])
  const types = useResource(() => ontologyApi.types(), [])
  const runs = useResource(() => ontologyApi.runs(), [])
  const [params] = useSearchParams()
  const asked = { type: params.get('type'), key: params.get('key') }
  const [tab, setTab] = useState('types')
  const [selected, setSelected] = useState<string | null>(asked.type)
  const [error, setError] = useState<ApiError | Error | null>(null)

  const running = Boolean(status.data?.running)

  // **받는 중이면 끝날 때까지 상태를 다시 묻는다** — 끝나면 받은 것(타입 · 기록)도 다시 읽는다.
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => status.reload(), POLL_MS)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running])
  const [wasRunning, setWasRunning] = useState(false)
  useEffect(() => {
    if (wasRunning && !running) {
      types.reload()
      runs.reload()
    }
    setWasRunning(running)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running])

  async function sync(full: boolean) {
    setError(null)
    try {
      await ontologyApi.sync(full)
      status.reload()
      runs.reload()
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('수신을 시작하지 못했습니다.'))
    }
  }

  async function toggle(slug: string, enabled: boolean) {
    setError(null)
    try {
      await ontologyApi.setEnabled(slug, enabled)
      types.reload()
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('바꾸지 못했습니다.'))
    }
  }

  const chosen = types.data?.find((one) => one.slug === selected) ?? null

  return (
    <div className="space-y-6">
      <PageHeader
        title="온톨로지"
        description="Standard Platform 이 정의하고 코어로 공개한 타입 · 객체 · 관계를 주기적으로 받아 둔 사본입니다. 여기서는 고치지 않습니다 — 고칠 것은 Standard Platform 에서 고칩니다."
      />
      <ErrorNotice error={error ?? status.error ?? types.error} />
      {status.data && (
        <StatusCard status={status.data} admin={admin} onSync={(full) => void sync(full)} />
      )}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList variant="line">
          <TabsTrigger value="types">타입 · 객체</TabsTrigger>
          <TabsTrigger value="runs">수신 기록</TabsTrigger>
        </TabsList>
        <TabsContent value="types" className="space-y-6 pt-4">
          {types.data && types.data.length === 0 ? (
            <EmptyState
              title="받아 둔 타입이 없습니다"
              hint={
                status.data?.configured
                  ? '아직 한 번도 받지 않았습니다 — 시스템 관리자가 「지금 받기」 를 누르거나 다음 주기를 기다립니다.'
                  : '연결을 설정한 뒤 받으면 여기에 나옵니다.'
              }
            />
          ) : (
            <TypeTable
              types={types.data ?? []}
              admin={admin}
              selected={selected}
              onSelect={setSelected}
              onToggle={(slug, enabled) => void toggle(slug, enabled)}
            />
          )}
          {chosen && (
            <ObjectBrowser
              key={chosen.slug}
              kind={chosen}
              types={types.data ?? []}
              initialKey={chosen.slug === asked.type ? asked.key : null}
            />
          )}
        </TabsContent>
        <TabsContent value="runs" className="pt-4">
          <RunTable runs={runs.data ?? []} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function StatusCard({
  status,
  admin,
  onSync,
}: {
  status: OntologyStatus
  admin: boolean
  onSync: (full: boolean) => void
}) {
  if (!status.configured) {
    return (
      <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 text-sm">
        <p className="font-medium">Standard Platform 연결이 설정되지 않았습니다.</p>
        <p className="text-muted-foreground mt-1">
          서버의 <code>.env</code> 에 <code>ONTOLOGY_SOURCE_URL</code>(예: <code>https://sp.example.com/api</code>) 와{' '}
          <code>ONTOLOGY_SOURCE_TOKEN</code> 을 적습니다. 토큰은 Standard Platform 시스템 관리자에게 범위{' '}
          <code>core:read</code> 하나로 받습니다.
        </p>
      </div>
    )
  }
  const last = status.last_run
  const running = status.running
  return (
    <div className="space-y-3 rounded-lg border p-4 text-sm">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
        <Fact label="출처">{status.source}</Fact>
        <Fact label="마지막 수신">
          {last ? (
            <span className="flex flex-wrap items-center gap-2">
              {shownDateTime(last.finished_at ?? last.started_at)}
              <StatusBadge kind="ontologySync" value={last.status} />
            </span>
          ) : (
            '아직 없음'
          )}
        </Fact>
        <Fact label="다음 수신">
          {status.next_due_at
            ? shownDateTime(status.next_due_at)
            : status.sync_minutes <= 0
              ? '주기 없음 — 「지금 받기」 로만'
              : '—'}
        </Fact>
        <Fact label="받은 것">
          타입 {status.types} · 객체 {status.objects.toLocaleString()} · 선 {status.relations.toLocaleString()}
        </Fact>
        <Fact label="정의 판">{status.revision || '—'}</Fact>
        <Fact label="전량 대조">{status.full_days > 0 ? `${status.full_days}일마다` : '안 함'}</Fact>
      </dl>
      {last?.error && <p className="text-destructive">{last.error}</p>}
      {last?.summary?.revision_changed ? (
        <p className="text-amber-700 dark:text-amber-400">
          지난 수신과 정의 판이 다릅니다 — Standard Platform 에서 칸 · 자료형 · 참조 대상이 바뀌었습니다.
        </p>
      ) : null}
      {admin && (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={Boolean(running)} onClick={() => onSync(false)}>
            {running ? '받는 중…' : '지금 받기'}
          </Button>
          <Button size="sm" variant="outline" disabled={Boolean(running)} onClick={() => onSync(true)}>
            처음부터 전량 받기
          </Button>
          <span className="text-muted-foreground text-xs">
            전량 받기는 SP 에서 사라진 것을 찾아 끕니다(지운 것이 「지움」 으로 안 온 경우).
          </span>
        </div>
      )}
    </div>
  )
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <dt className="text-muted-foreground w-20 shrink-0">{label}</dt>
      <dd className="min-w-0 break-all">{children}</dd>
    </div>
  )
}

function TypeTable({
  types,
  admin,
  selected,
  onSelect,
  onToggle,
}: {
  types: OntologyType[]
  admin: boolean
  selected: string | null
  onSelect: (slug: string) => void
  onToggle: (slug: string, enabled: boolean) => void
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>타입</TableHead>
          <TableHead className="text-right">SP 건수</TableHead>
          <TableHead className="text-right">받은 건수</TableHead>
          <TableHead className="text-right">꺼짐</TableHead>
          <TableHead className="text-right">선</TableHead>
          <TableHead>마지막 수신</TableHead>
          <TableHead>받나</TableHead>
          <TableHead>상태</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {types.map((one) => (
          <TableRow
            key={one.slug}
            className="cursor-pointer"
            data-state={selected === one.slug ? 'selected' : undefined}
            onClick={() => onSelect(one.slug)}
          >
            <TableCell>
              <span className="font-medium">{one.label}</span>{' '}
              <span className="text-muted-foreground text-xs">{one.slug}</span>
            </TableCell>
            <TableCell className="text-right">{one.source_count ?? '—'}</TableCell>
            <TableCell className="text-right">{one.active_count.toLocaleString()}</TableCell>
            <TableCell className="text-right">{one.inactive_count || ''}</TableCell>
            <TableCell className="text-right">{one.relation_count || ''}</TableCell>
            <TableCell>{shownDateTime(one.synced_at)}</TableCell>
            <TableCell onClick={(event) => event.stopPropagation()}>
              {admin ? (
                <label className="flex items-center gap-1.5 text-xs">
                  <input
                    type="checkbox"
                    checked={one.enabled}
                    onChange={(event) => onToggle(one.slug, event.target.checked)}
                    aria-label={`${one.label} 받기`}
                  />
                  {one.enabled ? '받음' : '안 받음'}
                </label>
              ) : one.enabled ? (
                '받음'
              ) : (
                '안 받음'
              )}
            </TableCell>
            <TableCell className="max-w-72">
              {!one.published ? (
                <span className="text-muted-foreground text-xs">공개 안 됨 — {one.last_error}</span>
              ) : one.last_error ? (
                <span className="text-destructive text-xs">{one.last_error}</span>
              ) : null}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

/**
 * 칸 값 한 개를 사람 말로 — 여러 값은 「;」 로, 단위는 칸 정의에서. 참조 칸은 상대의 `key` 라
 * 받아 둔 이름이 있으면 「이름 (key)」 로 보인다.
 */
function shownValue(value: unknown, property?: OntologyProperty, refLabels: Record<string, string> = {}): string {
  if (value === null || value === undefined) return ''
  const shownOne = (one: unknown) => {
    const text = String(one)
    return property?.data_type === 'object_ref' && refLabels[text] ? `${refLabels[text]} (${text})` : text
  }
  const text = Array.isArray(value) ? value.map(shownOne).join('; ') : shownOne(value)
  return property?.unit && text ? `${text} ${property.unit}` : text
}

function ObjectBrowser({
  kind,
  types,
  initialKey = null,
}: {
  kind: OntologyType
  types: OntologyType[]
  /** 처음 열어 둘 객체(주소의 `key`). */
  initialKey?: string | null
}) {
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const [includeInactive, setIncludeInactive] = useState(false)
  const [offset, setOffset] = useState(0)
  const [opened, setOpened] = useState<string | null>(initialKey)
  const page = useResource(
    () => ontologyApi.objects(kind.slug, { q: query, includeInactive, limit: PAGE, offset }),
    [kind.slug, query, includeInactive, offset],
  )
  const columns = kind.properties.slice(0, SHOWN_PROPERTIES)

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-base font-semibold">{kind.label}</h2>
        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            setOffset(0)
            setQuery(q)
          }}
        >
          <Input
            aria-label="식별자 · 이름으로 찾기"
            placeholder="식별자 · 이름"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            className="h-8 w-56"
          />
          <Button size="sm" variant="outline" type="submit">
            찾기
          </Button>
        </form>
        <label className="flex items-center gap-1.5 text-xs">
          <input
            type="checkbox"
            checked={includeInactive}
            onChange={(event) => {
              setOffset(0)
              setIncludeInactive(event.target.checked)
            }}
          />
          꺼진 것도 보기
        </label>
      </div>
      <ErrorNotice error={page.error} />
      {page.data && page.data.items.length === 0 ? (
        <EmptyState title="객체가 없습니다" hint={query ? '찾는 말을 바꿔 봅니다.' : undefined} />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>식별자</TableHead>
              <TableHead>이름</TableHead>
              {columns.map((one) => (
                <TableHead key={one.key}>{one.label || one.key}</TableHead>
              ))}
              <TableHead>상태</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(page.data?.items ?? []).map((row: OntologyObject) => (
              <TableRow
                key={row.key}
                className={row.active ? 'cursor-pointer' : 'text-muted-foreground cursor-pointer'}
                onClick={() => setOpened(row.key)}
              >
                <TableCell className="font-mono text-xs">{row.key}</TableCell>
                <TableCell>{row.label}</TableCell>
                {columns.map((one) => (
                  <TableCell key={one.key}>{shownValue(row.properties[one.key], one, row.ref_labels)}</TableCell>
                ))}
                <TableCell>
                  {row.active ? (
                    row.status && <StatusBadge kind="object" value={row.status} />
                  ) : (
                    <span className="text-xs">
                      {REMOVED[row.removed_reason] ?? row.removed_reason}
                      {row.merged_into ? ` → ${row.merged_into}` : ''}
                    </span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {page.data && (
        <Pagination total={page.data.total} limit={page.data.limit} offset={page.data.offset} onChange={setOffset} />
      )}
      {opened && <ObjectDialog kind={kind} types={types} objectKey={opened} onClose={() => setOpened(null)} />}
    </section>
  )
}

function ObjectDialog({
  kind,
  types,
  objectKey,
  onClose,
}: {
  kind: OntologyType
  types: OntologyType[]
  objectKey: string
  onClose: () => void
}) {
  const detail = useResource(() => ontologyApi.object(kind.slug, objectKey), [kind.slug, objectKey])
  const data = detail.data
  const known = new Set(kind.properties.map((one) => one.key))
  const extra = data ? Object.keys(data.properties).filter((key) => !known.has(key)) : []
  const typeLabel = (slug: string) => types.find((one) => one.slug === slug)?.label ?? slug

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{data?.label || objectKey}</DialogTitle>
          <DialogDescription>
            {kind.label} · <span className="font-mono">{objectKey}</span>
            {data && !data.active && ` · ${REMOVED[data.removed_reason] ?? data.removed_reason}`}
          </DialogDescription>
        </DialogHeader>
        <ErrorNotice error={detail.error} />
        {data && (
          <div className="max-h-[60vh] space-y-4 overflow-y-auto text-sm">
            <dl className="grid grid-cols-[10rem_1fr] gap-x-4 gap-y-1">
              {kind.properties.map((one) => (
                <PropertyRow key={one.key} label={one.label || one.key} value={shownValue(data.properties[one.key], one, data.ref_labels)} />
              ))}
              {extra.map((key) => (
                <PropertyRow key={key} label={key} value={shownValue(data.properties[key])} />
              ))}
              {data.previous_keys.length > 0 && (
                <PropertyRow label="옛 식별자" value={data.previous_keys.join(', ')} />
              )}
              <PropertyRow label="SP 에서 고친 때" value={shownDateTime(data.source_updated_at)} />
            </dl>
            <Edges title="나가는 선" edges={data.outgoing} side="dst" typeLabel={typeLabel} />
            <Edges title="들어오는 선" edges={data.incoming} side="src" typeLabel={typeLabel} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function PropertyRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="break-all">{value || '—'}</dd>
    </>
  )
}

function Edges({
  title,
  edges,
  side,
  typeLabel,
}: {
  title: string
  edges: OntologyEdge[]
  side: 'src' | 'dst'
  typeLabel: (slug: string) => string
}) {
  if (edges.length === 0) return null
  return (
    <div className="space-y-1">
      <h3 className="font-medium">{title}</h3>
      <ul className="space-y-0.5">
        {edges.map((one) => {
          const key = side === 'dst' ? one.dst_key : one.src_key
          const label = side === 'dst' ? one.dst_label : one.src_label
          const slug = side === 'dst' ? one.dst_type : one.src_type
          return (
            <li key={`${one.relation}-${one.src_type}-${one.src_key}-${one.dst_type}-${one.dst_key}`}>
              <span className="text-muted-foreground">{one.relation}</span> → {label || key}{' '}
              <span className="text-muted-foreground text-xs">
                ({typeLabel(slug)} · {key})
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function RunTable({ runs }: { runs: OntologyRun[] }) {
  if (runs.length === 0) return <EmptyState title="수신 기록이 없습니다" />
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>시작</TableHead>
          <TableHead>계기</TableHead>
          <TableHead>결과</TableHead>
          <TableHead>받은 것</TableHead>
          <TableHead>정의 판</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((one) => (
          <TableRow key={one.id}>
            <TableCell className="whitespace-nowrap">{shownDateTime(one.started_at)}</TableCell>
            <TableCell className="whitespace-nowrap">
              {TRIGGERS[one.trigger] ?? one.trigger}
              {one.full ? ' · 전량' : ''}
              {one.actor_name ? ` · ${one.actor_name}` : ''}
            </TableCell>
            <TableCell>
              <StatusBadge kind="ontologySync" value={one.status} />
            </TableCell>
            <TableCell className="text-xs">
              <RunSummary run={one} />
            </TableCell>
            <TableCell className="text-muted-foreground text-xs">{one.revision || '—'}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

/** 타입마다 「만듦 · 고침 · 끔 · 선」, 막혔으면 그 까닭. */
function RunSummary({ run }: { run: OntologyRun }) {
  const types = (run.summary?.types ?? {}) as Record<string, Record<string, number | string | boolean>>
  const lines = Object.entries(types)
  if (run.error) return <span className="text-destructive">{run.error}</span>
  if (lines.length === 0) return <span className="text-muted-foreground">—</span>
  return (
    <ul className="space-y-0.5">
      {lines.map(([slug, report]) => (
        <li key={slug}>
          <span className="font-medium">{slug}</span>{' '}
          {report.error ? (
            <span className="text-destructive">{String(report.error)}</span>
          ) : (
            [
              report.created ? `만듦 ${report.created}` : '',
              report.updated ? `고침 ${report.updated}` : '',
              report.deactivated ? `끔 ${report.deactivated}` : '',
              report.reactivated ? `되살림 ${report.reactivated}` : '',
              report.renamed ? `이름 바뀜 ${report.renamed}` : '',
              report.relations ? `선 ${report.relations}` : '',
              report.relations_removed ? `끊은 선 ${report.relations_removed}` : '',
              report.full ? '전량' : '',
            ]
              .filter(Boolean)
              .join(' · ') || '바뀐 것 없음'
          )}
        </li>
      ))}
    </ul>
  )
}
