/**
 * 서버 화면의 「해석 설정」 — **재시작 없이 고치는 값**(`/server/settings`, 2026-11-25).
 *
 * 전에는 `.env` 에 적고 앱을 다시 띄워야 들었다. 읽는 순서는 **서버 설정 → `.env` · 환경 → 기본값**이고,
 * 줄마다 지금 값이 어디서 왔는지 적는다. **결과를 바꾸는 값**(본딩 · 선형 솔버 · 허용오차 · 스레드 ·
 * STE 메모리 상한)은 작업을 만들 때 그 작업에 고정된다 — 고치면 그 뒤에 거는 작업부터 듣고, 이미 건
 * 작업 · 다시 돌리기는 그때 값 그대로다. STE 연결은 다음에 시작하는 단계부터 듣는다.
 *
 * 실행 파일 자리(`CCX_BIN` · `GMSH_BIN`)와 STE 위임 비밀은 여기 없다 — 워커마다 다르거나 비밀이라
 * `.env` 에 남는다.
 */

import { useState } from 'react'

import { api } from '@/shared/api/client'
import type { RuntimeSetting } from '@/shared/api/types'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { useResource } from '@/shared/hooks/useResource'
import { shownDateTime } from '@/shared/lib/datetime'

const GROUPS: { key: RuntimeSetting['group']; title: string }[] = [
  { key: 'calculix', title: 'CalculiX 해석' },
  { key: 'ste', title: 'STE 클러스터' },
]

const SOURCE_LABELS: Record<RuntimeSetting['source'], string> = {
  server: '서버 설정',
  env: '.env · 환경',
  default: '기본값',
}

const APPLIES_LABELS: Record<RuntimeSetting['applies'], string> = {
  new_jobs: '새로 거는 작업부터 (작업에 고정)',
  next_stage: '다음에 시작하는 단계부터',
}

/** 화면에 보일 값 — 빈 값은 「코어가 정한다」 는 뜻이다(허용오차 → CompCore 의 「바디 사이 틈」). */
function shown(row: RuntimeSetting, value: string): string {
  if (!value) return row.key === 'calculix_boolean_tolerance_mm' ? 'CompCore 기준' : '(없음)'
  return row.unit ? `${value} ${row.unit}` : value
}

function Row({ row, onChanged }: { row: RuntimeSetting; onChanged: () => void }) {
  const [draft, setDraft] = useState(row.value)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const id = `runtime-${row.key}`

  async function run(action: () => Promise<unknown>) {
    setSaving(true)
    setError(null)
    try {
      await action()
      onChanged()
    } catch (failure) {
      setError(failure as Error)
    } finally {
      setSaving(false)
    }
  }

  const save = () =>
    run(() => api.put<RuntimeSetting>(`/server/settings/${row.key}`, { value: draft }))
  const reset = () => run(() => api.delete<RuntimeSetting>(`/server/settings/${row.key}`))

  return (
    <li className="space-y-2 rounded-md border p-4" data-testid={id}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <label htmlFor={id} className="font-medium">
          {row.label}
        </label>
        <span className="text-muted-foreground text-xs">
          지금 <span className="text-foreground font-medium">{shown(row, row.value)}</span> ·{' '}
          {SOURCE_LABELS[row.source]} · {APPLIES_LABELS[row.applies]}
        </span>
      </div>
      <p className="text-muted-foreground text-xs">{row.help}</p>
      {row.problem && (
        <p className="text-xs text-amber-700 dark:text-amber-400">{row.problem}</p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {row.kind === 'choice' ? (
          <select
            id={id}
            className="border-input bg-background h-8 rounded-md border px-2 text-sm"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          >
            {row.choices.map((choice) => (
              <option key={choice} value={choice}>
                {choice}
                {choice === row.default ? ' (기본)' : ''}
              </option>
            ))}
          </select>
        ) : (
          <Input
            id={id}
            className="max-w-xs"
            inputMode={row.kind === 'integer' || row.kind === 'number' ? 'decimal' : undefined}
            placeholder={row.default ? `기본 ${row.default}` : '비우면 CompCore 기준'}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
        )}
        <Button size="sm" onClick={save} disabled={saving || draft.trim() === '' || draft === row.value}>
          저장
        </Button>
        {row.source === 'server' && (
          <Button size="sm" variant="outline" onClick={reset} disabled={saving}>
            서버 설정 지우기
          </Button>
        )}
        <span className="text-muted-foreground font-mono text-xs">{row.env}</span>
      </div>
      {row.source === 'server' && row.updated_at && (
        <p className="text-muted-foreground text-xs">
          {row.updated_by_name ?? '누군가'} · {shownDateTime(row.updated_at)}
          {row.env_value ? ` — 지우면 .env 의 ${shown(row, row.env_value)}` : ' — 지우면 기본값'}
        </p>
      )}
      <ErrorNotice error={error} />
    </li>
  )
}

export function RuntimeSettingsCard() {
  const settings = useResource(() => api.get<RuntimeSetting[]>('/server/settings'), [])
  if (settings.error) return <ErrorNotice error={settings.error} />
  if (!settings.data) return null
  const rows = settings.data
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-base font-semibold">해석 설정</h2>
        <p className="text-muted-foreground text-sm">
          다시 띄우지 않아도 듣습니다. 결과를 바꾸는 값은 작업을 만들 때 그 작업에 고정되어, 이미 건
          작업 · 다시 돌리기는 그때 값으로 풉니다.
        </p>
      </div>
      {GROUPS.map((group) => (
        <div key={group.key} className="space-y-2">
          <h3 className="text-sm font-medium">{group.title}</h3>
          <ul className="space-y-2">
            {rows
              .filter((row) => row.group === group.key)
              .map((row) => (
                // 값이 바뀌면 줄을 새로 그린다 — 입력 칸이 저장된 값으로 돌아간다.
                <Row key={`${row.key}:${row.value}:${row.source}`} row={row} onChanged={settings.reload} />
              ))}
          </ul>
        </div>
      ))}
    </section>
  )
}
