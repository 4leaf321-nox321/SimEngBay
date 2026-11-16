/**
 * **주파수 요구** — 모달 DOE 를 목표 주파수 · 회피 대역으로 판정한다(2026-11-16).
 *
 * 설계 목표가 둘이다 — 「이 모드를 이 주파수에 맞춘다」(공진 맞춤)와 「들뜨는 모드가 가진 대역에
 * 들지 않는다」(공진 회피). 실제 요구는 대개 섞여 오므로 **요구 조건 목록 하나**로 묶고, 설계점마다
 * 모든 줄을 만족하면 적합이다. 차례가 곧 사람이 묻는 차례다:
 *
 *   1. 주파수 요구 조건 — 목표 주파수 · 회피 대역 줄. 스터디에 저장한다(같은 스터디를 여는 사람과
 *      MCP `study_frequency` 가 같은 판정을 본다). 고치는 동안은 저장하지 않은 요구로 미리 본다.
 *   2. 판정 요약 — 적합 · 대역 침범 · 목표 이탈 · 부적합 · 판정 보류의 수, 그리고 보간 추정.
 *   3. 주파수 분포도 — 설계점마다 모드를 세로로. 회피 대역 · 목표 ± 허용을 띠로 깐다.
 *   4. 설계 공간 판정도 — 두 설계 변수의 격자에 판정. 목표를 지나는 자리 · 대역 끝을 지나는 자리.
 *   5. 설계점 상세 · 후보 설계점 표.
 *
 * **판정은 서버가 셈한다**(`backend/app/modules/simulations/frequency.py`). 화면은 셈하지 않는다 —
 * 같은 규칙을 두 벌로 두면 언젠가 갈리고, 그때 화면과 AI 가 다른 판정을 말한다.
 *
 * 회피 대역의 **판정 대상 모드**는 실제로 들뜨는 모드다 — 가진 방향 유효질량 또는 측정점 움직임이
 * 문턱 이상. 범위 안의 모든 모드로 판정하면 국부 모드 · 다른 방향 모드 때문에 거의 다 걸린다.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { CircleAlert, CircleCheck, CircleDashed, CircleX, Plus, RotateCcw, Save, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'

import { simulationApi } from '@/modules/simulations/api'
import type { FrequencyRequirementInput } from '@/modules/simulations/api'
import {
  VERDICTS,
  VERDICT_HINTS,
  VERDICT_INK,
  VERDICT_BACKING,
  VERDICT_LABELS,
  VERDICT_TONES,
  draftOf,
  filled,
  hz,
  levelsOf,
  modeName,
  newBand,
  newTarget,
  numericFactors,
  orderedPoints,
  paramsText,
  parseDraft,
  pointName,
  ruleOf,
  signedPct,
  signedSlope,
} from '@/modules/simulations/frequency'
import type { BandDraft, Check, Crossing, Direction, Draft, Mode, Point, TargetDraft, Verdict } from '@/modules/simulations/frequency'
import { shownMass } from '@/modules/simulations/format'
import { SERIES_COLORS } from '@/shared/charts/palette'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { shownDateTime } from '@/shared/lib/datetime'
import { cn } from '@/shared/lib/utils'

const SELECT =
  'border-input bg-background text-foreground h-8 rounded-md border px-2 text-sm disabled:opacity-50'
/** 입력을 멈추고 이만큼 지나면 미리 본다. */
const PREVIEW_MS = 300
/** 맞출 모드 — 계열 색 첫째(파랑). 회피 대역은 주황 띠로, 판정 대상 모드는 진한 점으로. */
const TARGET_COLOR = SERIES_COLORS[0]

function VerdictIcon({ verdict, className }: { verdict: Verdict; className?: string }) {
  const Icon =
    verdict === 'conform'
      ? CircleCheck
      : verdict === 'nonconform'
        ? CircleX
        : verdict === 'pending'
          ? CircleDashed
          : CircleAlert
  return <Icon className={cn('size-3.5 shrink-0', className)} aria-hidden />
}

function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap',
        VERDICT_TONES[verdict],
      )}
    >
      <VerdictIcon verdict={verdict} />
      {VERDICT_LABELS[verdict]}
    </span>
  )
}

interface Props {
  studyId: string
  /** 남의 게시 DOE — 요구 조건은 읽기만 한다. */
  readOnly: boolean
  /**
   * 대화 안의 결과 화면(MCP 패널) — 요구를 고쳐 **미리 볼** 수는 있지만 저장하지 않는다(패널은
   * 읽기만 한다). 웹 화면으로 옮겨 가는 링크도 숨긴다.
   */
  previewOnly?: boolean
}

export function StudyFrequency({ studyId, readOnly, previewOnly = false }: Props) {
  const [stored, setStored] = useState<Check | null>(null)
  const [check, setCheck] = useState<Check | null>(null)
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [saving, setSaving] = useState(false)
  const [filter, setFilter] = useState<Verdict | 'all'>('all')
  const [selected, setSelected] = useState<number | null>(null)
  const counter = useRef(0)
  const asked = useRef(0)

  function key(): string {
    counter.current += 1
    return `d${counter.current}`
  }

  function adopt(found: Check) {
    setStored(found)
    setCheck(found)
    setDrafts(found.requirements.map((one) => draftOf(one, key())))
    setDirty(false)
  }

  useEffect(() => {
    let cancelled = false
    simulationApi
      .studyFrequency(studyId)
      .then((found) => {
        if (!cancelled) adopt(filled(found))
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(caught instanceof Error ? caught : new Error('판정을 불러오지 못했습니다.'))
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studyId])

  const parsed = useMemo(() => drafts.map((one) => parseDraft(one)), [drafts])
  const problems = parsed.some((one) => one.problem)

  // **고칠 때마다 서버에 미리 묻는다** — 저장하지 않은 요구로. 늦게 온 옛 답은 버린다.
  useEffect(() => {
    if (!dirty || problems) return
    const requirements = parsed.map((one) => one.requirement as FrequencyRequirementInput)
    const ticket = ++asked.current
    const timer = window.setTimeout(() => {
      simulationApi
        .checkStudyFrequency(studyId, requirements)
        .then((found) => {
          if (ticket === asked.current) {
            setCheck(filled(found))
            setError(null)
          }
        })
        .catch((caught: unknown) => {
          if (ticket === asked.current)
            setError(caught instanceof Error ? caught : new Error('판정을 미리 보지 못했습니다.'))
        })
    }, PREVIEW_MS)
    return () => window.clearTimeout(timer)
  }, [parsed, dirty, problems, studyId])

  function edit(at: string, change: Partial<TargetDraft> | Partial<BandDraft>) {
    setDrafts((rows) => rows.map((one) => (one.key === at ? ({ ...one, ...change } as Draft) : one)))
    setDirty(true)
  }

  async function save() {
    if (problems) return
    setSaving(true)
    setError(null)
    try {
      const found = await simulationApi.saveStudyFrequency(
        studyId,
        parsed.map((one) => one.requirement as FrequencyRequirementInput),
      )
      asked.current += 1
      adopt(filled(found))
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('저장하지 못했습니다.'))
    } finally {
      setSaving(false)
    }
  }

  function revert() {
    if (!stored) return
    asked.current += 1
    adopt(stored)
  }

  if (!check) {
    return error ? <ErrorNotice error={error} /> : <p className="text-muted-foreground text-sm">판정을 불러오는 중…</p>
  }

  const points = orderedPoints(check.points, check.factors)
  const chosen = points.find((one) => one.number === selected) ?? pickDefault(points)
  const savedLine = stored?.saved
    ? `스터디에 저장됨 · ${stored.updated_by_name ?? '—'} · ${shownDateTime(stored.updated_at)}`
    : '저장된 요구 조건이 없습니다'

  return (
    <div className="space-y-6">
      <section aria-labelledby="freq-req" className="space-y-4 rounded-md border p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="max-w-3xl space-y-1">
            <h2 id="freq-req" className="text-sm font-medium">
              주파수 요구 조건
            </h2>
            <p className="text-muted-foreground text-xs">
              설계점마다 모든 요구를 만족하면 적합입니다. 요구 조건은 스터디에 저장되어 같은 스터디를 여는 사람과
              MCP(study_frequency)가 같은 판정을 봅니다.
              {!check.tracked && ' 이 스터디는 모드를 형상으로 잇지 못해 차례(1차 · 2차 …)로 셉니다.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn('text-xs', dirty ? 'text-amber-700 dark:text-amber-400' : 'text-muted-foreground')}>
              {dirty ? '저장하지 않은 변경 — 아래 판정은 미리보기입니다' : savedLine}
            </span>
            {!readOnly && (
              <>
                <Button variant="outline" size="sm" onClick={revert} disabled={!dirty || saving}>
                  <RotateCcw className="size-4" />
                  되돌리기
                </Button>
                {!previewOnly && (
                  <Button size="sm" onClick={save} disabled={!dirty || problems || saving}>
                    <Save className="size-4" />
                    저장
                  </Button>
                )}
              </>
            )}
          </div>
        </div>
        {previewOnly && !readOnly && (
          <p className="text-muted-foreground text-xs">
            이 화면에서는 요구를 고쳐 판정을 미리 보기만 합니다 — 저장은 SimEngBay 의 「주파수 요구」 탭에서 합니다.
          </p>
        )}
        {readOnly && (
          <p className="text-muted-foreground text-xs">읽기 전용 — 요구 조건은 설계점을 건 사람과 시스템 관리자가 바꿉니다.</p>
        )}

        {drafts.map((draft, at) => (
          <RequirementRow
            key={draft.key}
            draft={draft}
            problem={parsed[at]?.problem}
            check={check}
            readOnly={readOnly}
            onChange={(change) => edit(draft.key, change)}
            onRemove={() => {
              setDrafts((rows) => rows.filter((one) => one.key !== draft.key))
              setDirty(true)
            }}
          />
        ))}
        {drafts.length === 0 && (
          <p className="text-muted-foreground rounded-md border border-dashed p-3 text-sm">
            요구 조건이 없습니다 — 목표 주파수나 회피 대역을 더하세요.
          </p>
        )}
        {!readOnly && (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setDrafts((rows) => [...rows, newTarget(key(), check.tracks[0] ?? 1)])
                setDirty(true)
              }}
            >
              <Plus className="size-4" />
              목표 주파수
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setDrafts((rows) => [...rows, newBand(key(), check.probes.length > 0)])
                setDirty(true)
              }}
            >
              <Plus className="size-4" />
              회피 대역
            </Button>
          </div>
        )}
        {check.notes.length > 0 && (
          <ul className="text-muted-foreground list-disc space-y-0.5 pl-5 text-xs">
            {check.notes.map((one) => (
              <li key={one}>{one}</li>
            ))}
          </ul>
        )}
        <ErrorNotice error={error} />
      </section>

      <VerdictSummary check={check} filter={filter} onFilter={setFilter} />

      {points.some((one) => one.modes.length > 0) && (
        <FrequencyChart check={check} points={points} selected={chosen?.number ?? null} onSelect={setSelected} />
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <DesignSpaceMap check={check} points={points} selected={chosen?.number ?? null} onSelect={setSelected} />
        {chosen && <PointDetail check={check} point={chosen} linked={!previewOnly} />}
      </div>

      <CandidateTable check={check} points={points} filter={filter} selected={chosen?.number ?? null} onSelect={setSelected} />
    </div>
  )
}

function pickDefault(points: Point[]): Point | undefined {
  for (const verdict of VERDICTS) {
    const found = points.find((one) => one.verdict === verdict)
    if (found) return found
  }
  return points[0]
}

function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn('flex flex-col gap-1', className)}>
      <span className="text-muted-foreground text-xs">{label}</span>
      {children}
    </label>
  )
}

function RequirementRow({
  draft,
  problem,
  check,
  readOnly,
  onChange,
  onRemove,
}: {
  draft: Draft
  problem?: string
  check: Check
  readOnly: boolean
  onChange: (change: Partial<TargetDraft> | Partial<BandDraft>) => void
  onRemove: () => void
}) {
  const target = draft.kind === 'target'
  const rule = ruleOf(draft)
  const kindLabel = target ? '목표 주파수' : '회피 대역'
  return (
    <fieldset disabled={readOnly} className="bg-muted/30 space-y-3 rounded-md border p-3">
      <legend className="sr-only">{draft.label || kindLabel}</legend>
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            'rounded-full px-2 py-0.5 text-xs font-medium',
            target ? 'bg-blue-500/10 text-blue-700 dark:text-blue-300' : 'bg-orange-500/10 text-orange-700 dark:text-orange-300',
          )}
        >
          {kindLabel}
        </span>
        <Input
          aria-label={`${kindLabel} 이름`}
          placeholder={target ? '예: 하우징 공진 정합' : '예: 모터 가진 (2차 조화)'}
          value={draft.label}
          onChange={(event) => onChange({ label: event.target.value })}
          className="h-8 max-w-md flex-1"
        />
        {!readOnly && (
          <Button variant="ghost" size="sm" onClick={onRemove} aria-label={`${draft.label || kindLabel} 삭제`}>
            <Trash2 className="size-4" />
            삭제
          </Button>
        )}
      </div>

      {draft.kind === 'target' ? (
        <div className="flex flex-wrap items-end gap-3">
          <Field label="대상 모드 (형상 추적)">
            <select className={SELECT} value={draft.mode} onChange={(event) => onChange({ mode: event.target.value })}>
              {check.tracks.map((one) => (
                <option key={one} value={String(one)}>
                  {one}차 모드
                </option>
              ))}
            </select>
          </Field>
          <Field label="목표 주파수 (Hz)">
            <Input
              inputMode="decimal"
              value={draft.target}
              onChange={(event) => onChange({ target: event.target.value })}
              className="h-8 w-28 tabular-nums"
            />
          </Field>
          <Field label="허용 범위 ± (%)">
            <Input
              inputMode="decimal"
              value={draft.tolerance}
              onChange={(event) => onChange({ tolerance: event.target.value })}
              className="h-8 w-20 tabular-nums"
            />
          </Field>
          {rule && <p className="text-muted-foreground pb-1.5 text-xs tabular-nums">{rule}</p>}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="대역 하한 (Hz)">
              <Input
                inputMode="decimal"
                value={draft.low}
                onChange={(event) => onChange({ low: event.target.value })}
                className="h-8 w-28 tabular-nums"
              />
            </Field>
            <Field label="대역 상한 (Hz)">
              <Input
                inputMode="decimal"
                value={draft.high}
                onChange={(event) => onChange({ high: event.target.value })}
                className="h-8 w-28 tabular-nums"
              />
            </Field>
            <Field label="이격 여유 (%)">
              <Input
                inputMode="decimal"
                value={draft.margin}
                onChange={(event) => onChange({ margin: event.target.value })}
                className="h-8 w-20 tabular-nums"
              />
            </Field>
            {rule && <p className="text-muted-foreground pb-1.5 text-xs tabular-nums">{rule}</p>}
          </div>
          <div className="space-y-2 rounded-md border border-dashed p-3">
            <p className="text-muted-foreground text-xs">
              판정 대상 모드 — 실제로 들뜨는 모드만 판정합니다(둘 중 하나라도 문턱 이상이면 대상, 둘 다 끄면 모든 모드).
            </p>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="size-4"
                  checked={draft.massOn}
                  onChange={(event) => onChange({ massOn: event.target.checked })}
                />
                유효질량
              </label>
              <select
                aria-label="유효질량 방향"
                className={SELECT}
                value={draft.direction}
                disabled={!draft.massOn}
                onChange={(event) => onChange({ direction: event.target.value as Direction })}
              >
                <option value="X">X 방향</option>
                <option value="Y">Y 방향</option>
                <option value="Z">Z 방향</option>
              </select>
              <span className="flex items-center gap-1">
                <span className="text-muted-foreground text-xs">≥</span>
                <Input
                  aria-label="유효질량 문턱 (%)"
                  inputMode="decimal"
                  value={draft.massMin}
                  disabled={!draft.massOn}
                  onChange={(event) => onChange({ massMin: event.target.value })}
                  className="h-8 w-16 tabular-nums"
                />
                <span className="text-muted-foreground text-xs">%</span>
              </span>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="size-4"
                  checked={draft.probeOn}
                  disabled={check.probes.length === 0}
                  onChange={(event) => onChange({ probeOn: event.target.checked })}
                />
                측정점 응답
              </label>
              <select
                aria-label="측정점"
                className={SELECT}
                value={draft.probe}
                disabled={!draft.probeOn || check.probes.length === 0}
                onChange={(event) => onChange({ probe: event.target.value })}
              >
                <option value="">측정점 중 최대</option>
                {check.probes.map((one) => (
                  <option key={one} value={one}>
                    {one}
                  </option>
                ))}
              </select>
              <span className="flex items-center gap-1">
                <span className="text-muted-foreground text-xs">≥</span>
                <Input
                  aria-label="측정점 응답 문턱 (%)"
                  inputMode="decimal"
                  value={draft.probeMin}
                  disabled={!draft.probeOn || check.probes.length === 0}
                  onChange={(event) => onChange({ probeMin: event.target.value })}
                  className="h-8 w-16 tabular-nums"
                />
                <span className="text-muted-foreground text-xs">% (그 측정점의 최대 응답 모드 대비)</span>
              </span>
            </div>
            {check.probes.length === 0 && (
              <p className="text-muted-foreground text-xs">이 스터디에는 측정점이 없어 유효질량으로만 거릅니다.</p>
            )}
          </div>
        </div>
      )}
      {problem && <p className="text-destructive text-xs">{problem}</p>}
    </fieldset>
  )
}

function VerdictSummary({
  check,
  filter,
  onFilter,
}: {
  check: Check
  filter: Verdict | 'all'
  onFilter: (next: Verdict | 'all') => void
}) {
  const total = check.points.length
  return (
    <section aria-labelledby="freq-sum" className="space-y-3">
      <h2 id="freq-sum" className="text-sm font-medium">
        판정 요약
      </h2>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <button
          type="button"
          aria-pressed={filter === 'all'}
          onClick={() => onFilter('all')}
          className={cn(
            'flex min-h-20 flex-col items-start gap-0.5 rounded-md border p-3 text-left',
            filter === 'all' && 'border-foreground ring-foreground/20 ring-2',
          )}
        >
          <span className="text-muted-foreground text-xs font-medium">전체</span>
          <span className="text-2xl font-semibold tabular-nums">{total}</span>
          <span className="text-muted-foreground text-xs">설계점</span>
        </button>
        {VERDICTS.map((verdict) => (
          <button
            key={verdict}
            type="button"
            aria-pressed={filter === verdict}
            onClick={() => onFilter(filter === verdict ? 'all' : verdict)}
            className={cn(
              'flex min-h-20 flex-col items-start gap-0.5 rounded-md border p-3 text-left',
              filter === verdict && 'border-foreground ring-foreground/20 ring-2',
            )}
          >
            <span className={cn('inline-flex items-center gap-1 rounded-full px-1.5 text-xs font-medium', VERDICT_TONES[verdict])}>
              <VerdictIcon verdict={verdict} />
              {VERDICT_LABELS[verdict]}
            </span>
            <span className="text-2xl font-semibold tabular-nums">{check.counts[verdict] ?? 0}</span>
            <span className="text-muted-foreground text-xs">{VERDICT_HINTS[verdict]}</span>
          </button>
        ))}
      </div>
      <div className="bg-muted/30 space-y-1 rounded-md border p-3">
        <p className="text-xs font-medium text-blue-700 dark:text-blue-300">보간 추정</p>
        <p className="text-sm">
          {check.estimate?.text ??
            (check.requirements.some((one) => one.kind === 'target')
              ? '대상 모드가 목표를 지나는 자리가 DOE 범위 안에서 모두 다른 요구를 어깁니다 — 범위를 넓혀 다시 훑어 보세요.'
              : '목표 주파수 요구가 없어 추정할 자리가 없습니다.')}
        </p>
        <p className="text-muted-foreground text-xs">
          이웃 설계점 사이를 곧게 이은 값입니다. SimEngBay 는 형상을 만들지 못하므로 CompCore 에서 이 값으로 설계점을
          더해 확인하세요.
        </p>
      </div>
    </section>
  )
}

interface Scale {
  min: number
  max: number
  y: (value: number) => number
}

function scaleOf(check: Check, full: boolean): Scale {
  let min = 0
  let max = Math.max(1, ...check.points.flatMap((one) => one.modes.map((mode) => mode.frequency_hz))) * 1.05
  const edges: number[] = []
  for (const one of check.requirements) {
    if (one.kind === 'target') {
      const width = (one.target_hz * one.tolerance_pct) / 100
      edges.push(one.target_hz - width, one.target_hz + width)
    } else {
      const margin = (one.margin_pct ?? 0) / 100
      edges.push(one.low_hz * (1 - margin), one.high_hz * (1 + margin))
    }
  }
  if (!full && edges.length) {
    const lo = Math.min(...edges)
    const hi = Math.max(...edges)
    const pad = Math.max(150, (hi - lo) * 0.35)
    min = Math.max(0, Math.floor((lo - pad) / 100) * 100)
    max = Math.ceil((hi + pad) / 100) * 100
  }
  const span = Math.max(1, max - min)
  return { min, max, y: (value) => (1 - (value - min) / span) * 100 }
}

function ticksOf(scale: Scale): number[] {
  const span = scale.max - scale.min
  const step = span > 6000 ? 1000 : span > 2000 ? 500 : span > 1000 ? 200 : 100
  const ticks: number[] = []
  for (let value = Math.ceil(scale.min / step) * step; value <= scale.max; value += step) ticks.push(value)
  return ticks
}

function clampPct(value: number): number {
  return Math.max(0, Math.min(100, value))
}

function strip(scale: Scale, upper: number, lower: number): { top: number; height: number } {
  const top = clampPct(scale.y(upper))
  const bottom = clampPct(scale.y(lower))
  return { top, height: Math.max(0, bottom - top) }
}

function roleText(mode: Mode): string {
  return mode.role === 'target' ? '목표 주파수 대상' : mode.role === 'judged' ? '판정 대상' : '판정 제외'
}

function FrequencyChart({
  check,
  points,
  selected,
  onSelect,
}: {
  check: Check
  points: Point[]
  selected: number | null
  onSelect: (number: number) => void
}) {
  const [full, setFull] = useState(false)
  const [hover, setHover] = useState<{ point: number; index: number } | null>(null)
  const scale = scaleOf(check, full)
  const [group, sub] = check.factors
  const columns = points.length
  const x = (at: number) => ((at + 0.5) / columns) * 100
  const groups: { label: string; from: number; to: number }[] = []
  points.forEach((point, at) => {
    const label = group ? `${group} ${point.params[group] ?? '—'}` : pointName(point)
    const last = groups[groups.length - 1]
    if (last && last.label === label) last.to = at
    else groups.push({ label, from: at, to: at })
  })
  const hidden = points.reduce(
    (sum, point) =>
      sum + point.modes.filter((mode) => mode.frequency_hz < scale.min || mode.frequency_hz > scale.max).length,
    0,
  )
  const tip = (() => {
    if (!hover) return null
    const point = points.find((one) => one.number === hover.point)
    const mode = point?.modes.find((one) => one.index === hover.index)
    if (!point || !mode) return null
    const at = points.indexOf(point)
    const target = check.requirements.find((one) => one.kind === 'target' && one.mode === mode.track)
    const detail =
      mode.role === 'target' && target && target.kind === 'target'
        ? `목표 ${hz(target.target_hz)} Hz 대비 ${signedPct(((mode.frequency_hz - target.target_hz) / target.target_hz) * 100)}`
        : mode.reason
    return { point, mode, left: x(at), top: scale.y(mode.frequency_hz), detail }
  })()

  return (
    <section aria-labelledby="freq-chart" className="space-y-3 rounded-md border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="freq-chart" className="text-sm font-medium">
            주파수 분포도
          </h2>
          <p className="text-muted-foreground text-xs">
            설계점마다 모드를 세로로 찍었습니다. 점에 올리면 값과 판정 근거가, 누르면 아래에 그 설계점이 나옵니다.
          </p>
        </div>
        <div role="group" aria-label="세로축 범위" className="flex overflow-hidden rounded-md border text-xs">
          <button
            type="button"
            aria-pressed={!full}
            onClick={() => setFull(false)}
            className={cn('px-3 py-1.5', !full ? 'bg-foreground text-background font-medium' : 'text-muted-foreground')}
          >
            요구 대역 중심
          </button>
          <button
            type="button"
            aria-pressed={full}
            onClick={() => setFull(true)}
            className={cn('px-3 py-1.5', full ? 'bg-foreground text-background font-medium' : 'text-muted-foreground')}
          >
            전체 범위
          </button>
        </div>
      </div>
      <div className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-full" style={{ background: TARGET_COLOR }} aria-hidden />
          목표 주파수 대상
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="bg-foreground/70 size-2 rounded-full" aria-hidden />
          판정 대상
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="border-muted-foreground size-2 rounded-full border-[1.5px]" aria-hidden />
          판정 제외 (응답 미미)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-4 border-y border-orange-500 bg-orange-500/25" aria-hidden />
          회피 대역
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-4 bg-orange-500/10" aria-hidden />
          이격 여유
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-4 border-t-[1.5px] border-dashed bg-blue-500/10" style={{ borderColor: TARGET_COLOR }} aria-hidden />
          목표 ± 허용
        </span>
      </div>
      <div className="overflow-x-auto">
        <div className="pl-14" style={{ minWidth: Math.max(640, columns * 28 + 56) }}>
          <div
            role="img"
            aria-label={`설계점 ${columns}개의 모드 주파수, 세로축 ${hz(scale.min)}–${hz(scale.max)} Hz. 같은 값은 후보 설계점 표에 있습니다.`}
            className="bg-muted/20 relative h-80 border-b border-l"
          >
            {ticksOf(scale).map((value) => (
              <div key={value} className="absolute inset-x-0" style={{ top: `${scale.y(value)}%` }}>
                <div className="border-border/60 border-t" />
                <span className="text-muted-foreground absolute -left-14 w-12 -translate-y-1/2 text-right text-[11px] tabular-nums">
                  {hz(value)}
                </span>
              </div>
            ))}
            {groups.slice(1).map((one) => (
              <div key={one.label} className="absolute inset-y-0 border-l" style={{ left: `${(one.from / columns) * 100}%` }} />
            ))}
            {selected != null && points.some((one) => one.number === selected) && (
              <div
                className="bg-foreground/5 absolute inset-y-0"
                style={{
                  left: `${(points.findIndex((one) => one.number === selected) / columns) * 100}%`,
                  width: `${100 / columns}%`,
                }}
              />
            )}
            {check.requirements.map((one, at) => {
              if (one.kind === 'band') {
                const margin = (one.margin_pct ?? 0) / 100
                const zone = strip(scale, one.high_hz * (1 + margin), one.low_hz * (1 - margin))
                const core = strip(scale, one.high_hz, one.low_hz)
                return (
                  <div key={`b${at}`}>
                    <div className="absolute inset-x-0 bg-orange-500/10" style={{ top: `${zone.top}%`, height: `${zone.height}%` }} />
                    <div
                      className="absolute inset-x-0 border-y border-orange-500 bg-orange-500/25"
                      style={{ top: `${core.top}%`, height: `${core.height}%` }}
                    />
                    {core.height > 0 && (
                      <span
                        className="bg-background/90 absolute right-1 rounded px-1 text-[11px] font-medium text-orange-700 dark:text-orange-300"
                        style={{ top: `${core.top}%` }}
                      >
                        {one.label || '회피 대역'} {hz(one.low_hz)}–{hz(one.high_hz)} Hz · 이격 여유 {one.margin_pct ?? 0} %
                      </span>
                    )}
                  </div>
                )
              }
              const width = (one.target_hz * one.tolerance_pct) / 100
              const band = strip(scale, one.target_hz + width, one.target_hz - width)
              const line = scale.y(one.target_hz)
              if (line < 0 || line > 100) return null
              return (
                <div key={`t${at}`}>
                  <div className="absolute inset-x-0 bg-blue-500/10" style={{ top: `${band.top}%`, height: `${band.height}%` }} />
                  <div className="absolute inset-x-0 border-t-[1.5px] border-dashed" style={{ top: `${line}%`, borderColor: TARGET_COLOR }} />
                  <span
                    className="bg-background/90 absolute right-1 -translate-y-full rounded px-1 text-[11px] font-medium text-blue-700 dark:text-blue-300"
                    style={{ top: `${line}%` }}
                  >
                    {one.label || `${one.mode}차 모드 목표`} {hz(one.target_hz)} Hz ± {one.tolerance_pct} %
                  </span>
                </div>
              )
            })}
            {points.map((point, at) =>
              point.modes
                .filter((mode) => mode.frequency_hz >= scale.min && mode.frequency_hz <= scale.max)
                .map((mode) => (
                  <button
                    key={`${point.number}-${mode.index}`}
                    type="button"
                    aria-label={`${pointName(point)} ${modeName(mode)} ${hz(mode.frequency_hz)} Hz ${roleText(mode)}`}
                    onMouseEnter={() => setHover({ point: point.number, index: mode.index })}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover({ point: point.number, index: mode.index })}
                    onBlur={() => setHover(null)}
                    onClick={() => onSelect(point.number)}
                    className="group absolute -mt-[9px] -ml-[9px] flex size-[18px] items-center justify-center"
                    style={{ left: `${x(at)}%`, top: `${scale.y(mode.frequency_hz)}%` }}
                  >
                    <span
                      className={cn(
                        'block rounded-full transition-transform group-hover:scale-150 group-focus-visible:scale-150',
                        mode.role === 'target'
                          ? 'border-background size-3 border-2'
                          : mode.role === 'judged'
                            ? 'bg-foreground/70 border-background size-2.5 border-2'
                            : 'border-muted-foreground bg-background size-2 border-[1.5px]',
                      )}
                      style={mode.role === 'target' ? { background: TARGET_COLOR } : undefined}
                    />
                  </button>
                )),
            )}
            {tip && (
              <div
                role="status"
                className="bg-popover text-popover-foreground pointer-events-none absolute z-10 w-64 rounded-md border p-2 text-xs shadow-md"
                style={{
                  left: `${tip.left}%`,
                  top: `${tip.top}%`,
                  transform: `translate(${tip.left > 75 ? '-100%' : tip.left < 25 ? '0' : '-50%'}, ${tip.top < 30 ? '14px' : 'calc(-100% - 14px)'})`,
                }}
              >
                <p className="font-medium">
                  {pointName(tip.point)} · {paramsText(tip.point.params)}
                </p>
                <p className="tabular-nums">
                  {modeName(tip.mode)} {hz(tip.mode.frequency_hz)} Hz — {roleCell(tip.mode, bandNamesOf(check))}
                </p>
                <p className="text-muted-foreground">{tip.detail}</p>
              </div>
            )}
          </div>
          <div className="mt-1 grid" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
            {points.map((point) => (
              <span key={point.number} className="flex flex-col items-center gap-0.5" title={`${pointName(point)} ${VERDICT_LABELS[point.verdict]}`}>
                <VerdictIcon verdict={point.verdict} className={VERDICT_INK[point.verdict]} />
                <span className="text-muted-foreground text-[10px] tabular-nums">
                  {sub ? String(point.params[sub] ?? '') : String(point.number)}
                </span>
              </span>
            ))}
          </div>
          <div className="relative mt-0.5 h-5 text-xs">
            {groups.map((one) => (
              <span
                key={one.label}
                className="text-muted-foreground absolute -translate-x-1/2 whitespace-nowrap"
                style={{ left: `${((one.from + one.to + 1) / 2 / columns) * 100}%` }}
              >
                {one.label}
              </span>
            ))}
          </div>
          <p className="text-muted-foreground mt-1 text-xs">
            {sub ? `묶음 안의 작은 숫자는 ${sub} 입니다.` : '작은 숫자는 설계점 번호입니다.'}
            {hidden > 0 && ` 세로축 범위 밖의 모드 ${hidden}개는 찍지 않았습니다(「전체 범위」 로 보기).`}
          </p>
        </div>
      </div>
    </section>
  )
}

function DesignSpaceMap({
  check,
  points,
  selected,
  onSelect,
}: {
  check: Check
  points: Point[]
  selected: number | null
  onSelect: (number: number) => void
}) {
  const numeric = numericFactors(points, check.factors)
  const [xName, setXName] = useState<string | null>(null)
  const [yName, setYName] = useState<string | null>(null)
  const [fixed, setFixed] = useState<Record<string, string>>({})
  const xFactor = xName && numeric.includes(xName) ? xName : numeric[0]
  const yFactor = yName && numeric.includes(yName) && yName !== xFactor ? yName : numeric.find((one) => one !== xFactor)
  if (!xFactor || !yFactor) {
    return (
      <section aria-labelledby="freq-map" className="space-y-2 rounded-md border p-4">
        <h2 id="freq-map" className="text-sm font-medium">
          설계 공간 판정도
        </h2>
        <p className="text-muted-foreground text-sm">숫자 설계 변수가 둘 이상인 DOE 에서 그립니다.</p>
      </section>
    )
  }
  const others = check.factors.filter((one) => one !== xFactor && one !== yFactor)
  const chosen: Record<string, string> = {}
  for (const name of others) chosen[name] = fixed[name] ?? String(levelsOf(points, name)[0] ?? '')
  const inSlice = (params: Record<string, number | string>) =>
    others.every((name) => String(params[name]) === chosen[name])
  const xs = levelsOf(points, xFactor) as number[]
  const ys = (levelsOf(points, yFactor) as number[]).slice().reverse()
  const position = (value: number) => {
    let at = 0
    for (let index = 0; index < xs.length - 1; index += 1) {
      if (value >= xs[index] && value <= xs[index + 1]) {
        at = index + (value - xs[index]) / (xs[index + 1] - xs[index] || 1)
        break
      }
      if (value > xs[index + 1]) at = index + 1
    }
    return ((at + 0.5) / xs.length) * 100
  }
  const crossingsAt = (y: number, kind: Crossing['kind']) =>
    check.crossings.filter(
      (one) =>
        one.kind === kind &&
        one.factor === xFactor &&
        String(one.fixed[yFactor]) === String(y) &&
        others.every((name) => String(one.fixed[name]) === chosen[name]),
    )
  /**
   * 세로 변수를 따라 지나는 자리 — 이 줄(`upper`)과 아래 줄(`lower`) 사이에 든 것. 줄 높이에 줄 사이
   * 4px 를 더한 만큼이 두 줄 가운데 사이의 거리다. 이 줄의 칸에 붙여 그리고 아래로 내린다.
   */
  const crossingsBelow = (upper: number, lower: number | undefined, kind: Crossing['kind']) =>
    lower == null
      ? []
      : check.crossings.flatMap((one) => {
          if (one.kind !== kind || one.factor !== yFactor) return []
          if (!others.every((name) => String(one.fixed[name]) === chosen[name])) return []
          if (!(one.value <= upper && one.value > lower)) return []
          const column = xs.findIndex((x) => String(x) === String(one.fixed[xFactor]))
          if (column < 0) return []
          return [{ one, column, share: (upper - one.value) / (upper - lower) }]
        })
  const cell = `((100% - ${(xs.length - 1) * 4}px) / ${xs.length})`
  const columnStart = (column: number) => `${column} * (${cell} + 4px)`
  const firstTarget = check.requirements.findIndex((one) => one.kind === 'target')
  return (
    <section aria-labelledby="freq-map" className="space-y-3 rounded-md border p-4">
      <div className="space-y-1">
        <h2 id="freq-map" className="text-sm font-medium">
          설계 공간 판정도
        </h2>
        <p className="text-muted-foreground text-xs">
          파란 점선은 대상 모드가 목표 주파수를 지나는 자리, 주황 선은 판정 대상 모드가 회피 대역(이격 여유 포함)의 끝을
          지나는 자리입니다 — 둘 다 이웃 설계점 사이를 이은 보간입니다.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label className="flex items-center gap-1">
          <span className="text-muted-foreground">가로</span>
          <select className={SELECT} value={xFactor} onChange={(event) => setXName(event.target.value)}>
            {numeric.map((one) => (
              <option key={one} value={one}>
                {one}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          <span className="text-muted-foreground">세로</span>
          <select className={SELECT} value={yFactor} onChange={(event) => setYName(event.target.value)}>
            {numeric
              .filter((one) => one !== xFactor)
              .map((one) => (
                <option key={one} value={one}>
                  {one}
                </option>
              ))}
          </select>
        </label>
        {others.map((name) => (
          <label key={name} className="flex items-center gap-1">
            <span className="text-muted-foreground">{name} 고정</span>
            <select
              className={SELECT}
              value={chosen[name]}
              onChange={(event) => setFixed((now) => ({ ...now, [name]: event.target.value }))}
            >
              {levelsOf(points, name).map((one) => (
                <option key={String(one)} value={String(one)}>
                  {String(one)}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <div className="overflow-x-auto">
        <div className="min-w-[440px] space-y-1">
          {ys.map((y, row) => (
            <div key={String(y)} className="flex items-stretch gap-2">
              <span className="text-muted-foreground flex w-20 shrink-0 items-center justify-end text-xs tabular-nums">
                {yFactor} {y}
              </span>
              <div className="relative grid flex-1 gap-1" style={{ gridTemplateColumns: `repeat(${xs.length}, minmax(0, 1fr))` }}>
                {xs.map((x) => {
                  const point = points.find(
                    (one) => one.params[xFactor] === x && one.params[yFactor] === y && inSlice(one.params),
                  )
                  if (!point) return <span key={String(x)} className="bg-muted/30 min-h-16 rounded-md" />
                  const target = firstTarget >= 0 ? point.targets.find((one) => one.requirement === firstTarget) : undefined
                  const band = worstBand(point)
                  return (
                    <button
                      key={String(x)}
                      type="button"
                      aria-pressed={point.number === selected}
                      aria-label={`${pointName(point)} ${xFactor} ${x} ${yFactor} ${y} ${VERDICT_LABELS[point.verdict]}`}
                      onClick={() => onSelect(point.number)}
                      className={cn(
                        // 칸이 경계선 위에 온다 — 선은 옅은 바탕 너머로 비치고, 글자 줄은 칸과 같은 색의
                        // 불투명 바탕(VERDICT_BACKING)을 깔아 선이 글자 뒤로 지나간다(취소선처럼 읽히지 않게).
                        'relative z-[1] flex min-h-16 flex-col items-start gap-0.5 rounded-md border p-1.5 text-left text-xs',
                        VERDICT_TONES[point.verdict],
                        point.number === selected ? 'border-foreground ring-foreground/30 ring-2' : 'border-transparent',
                      )}
                    >
                      <span className={cn('-mx-0.5 inline-flex items-center gap-1 rounded-sm px-0.5 font-medium', VERDICT_BACKING[point.verdict])}>
                        <VerdictIcon verdict={point.verdict} />
                        {VERDICT_LABELS[point.verdict]}
                      </span>
                      {target?.frequency_hz != null && (
                        <span className={cn('text-foreground -mx-0.5 rounded-sm px-0.5 tabular-nums', VERDICT_BACKING[point.verdict])}>
                          {hz(target.frequency_hz)} Hz {signedPct(target.error_pct)}
                        </span>
                      )}
                      {band && (
                        <span className={cn('text-muted-foreground -mx-0.5 rounded-sm px-0.5 tabular-nums', VERDICT_BACKING[point.verdict])}>
                          {band.inside ? '회피 대역 안' : `이격 여유 ${band.margin_pct?.toFixed(1)} %`}
                        </span>
                      )}
                    </button>
                  )
                })}
                {crossingsAt(y, 'band_edge').map((one, at) => (
                  <span
                    key={`e${at}`}
                    className="pointer-events-none absolute -inset-y-0.5 border-l-2 border-orange-500/80"
                    style={{ left: `${position(one.value)}%` }}
                  />
                ))}
                {crossingsBelow(y, ys[row + 1], 'band_edge').map(({ column, share }, at) => (
                  <span
                    key={`ey${at}`}
                    className="pointer-events-none absolute border-t-2 border-orange-500/80"
                    style={{
                      top: `calc(50% + ${share * 100}% + ${share * 4}px)`,
                      left: `calc(${columnStart(column)})`,
                      width: `calc(${cell})`,
                    }}
                  />
                ))}
                {crossingsAt(y, 'target')
                  .filter((one) => one.requirement === firstTarget)
                  .map((one, at) => (
                    <span
                      key={`t${at}`}
                      className="pointer-events-none absolute -inset-y-0.5 border-l-2 border-dashed"
                      style={{ left: `${position(one.value)}%`, borderColor: TARGET_COLOR }}
                    />
                  ))}
                {crossingsBelow(y, ys[row + 1], 'target')
                  .filter(({ one }) => one.requirement === firstTarget)
                  .map(({ column, share }, at) => (
                    <span
                      key={`ty${at}`}
                      className="pointer-events-none absolute border-t-2 border-dashed"
                      style={{
                        top: `calc(50% + ${share * 100}% + ${share * 4}px)`,
                        left: `calc(${columnStart(column)})`,
                        width: `calc(${cell})`,
                        borderColor: TARGET_COLOR,
                      }}
                    />
                  ))}
              </div>
            </div>
          ))}
          <div className="flex gap-2">
            <span className="w-20 shrink-0" />
            <div className="text-muted-foreground grid flex-1 gap-1 text-center text-xs tabular-nums" style={{ gridTemplateColumns: `repeat(${xs.length}, minmax(0, 1fr))` }}>
              {xs.map((x) => (
                <span key={String(x)}>{x}</span>
              ))}
            </div>
          </div>
          <p className="text-muted-foreground pl-[5.5rem] text-center text-xs">{xFactor}</p>
        </div>
      </div>
    </section>
  )
}

function worstBand(point: Point) {
  return point.bands
    .filter((one) => one.closest_hz != null)
    .slice()
    .sort((a, b) => (a.inside === b.inside ? (a.margin_pct ?? 0) - (b.margin_pct ?? 0) : a.inside ? -1 : 1))[0]
}

/**
 * 판정 구분 칸 — 회피 대역이 여럿이고 그 일부만 이 모드를 판정하면 어느 대역인지 적는다(Z 가진 대역의
 * 대상이 Y 가진 대역에서는 제외일 수 있다). 「회피 대역 안」 은 판정하는 대역 안일 때만 붙는다.
 */
function roleCell(mode: Mode, bandNames: Map<number, string>): string {
  const which =
    mode.role === 'judged' && bandNames.size > 1 && mode.bands.length < bandNames.size
      ? ` — ${mode.bands.map((at) => bandNames.get(at)).join(' · ')}`
      : ''
  return `${roleText(mode)}${which}${mode.in_band ? ' · 회피 대역 안' : ''}`
}

/** 회피 대역의 이름 — 요구 조건의 차례 → 이름(비었으면 「회피 대역 n」). */
function bandNamesOf(check: Check): Map<number, string> {
  const names = new Map<number, string>()
  check.requirements.forEach((one, at) => {
    if (one.kind === 'band') names.set(at, one.label || `회피 대역 ${names.size + 1}`)
  })
  return names
}

function PointDetail({ check, point, linked }: { check: Check; point: Point; linked: boolean }) {
  const bandNames = bandNamesOf(check)
  const directions: Direction[] = []
  check.requirements.forEach((one) => {
    if (one.kind !== 'band') return
    const direction = one.mass_direction ?? 'Z'
    if (one.mass_filter !== false && !directions.includes(direction)) directions.push(direction)
  })
  // 유효질량으로 거르는 대역이 없어도 한 열은 보인다 — 첫 대역의 방향(없으면 Z).
  if (directions.length === 0) {
    const first = check.requirements.find((one) => one.kind === 'band')
    directions.push(first && first.kind === 'band' ? (first.mass_direction ?? 'Z') : 'Z')
  }
  const band = check.requirements.find((one) => one.kind === 'band')
  const probe = band && band.kind === 'band' ? band.probe || check.probes[0] : check.probes[0]
  const firstTarget = check.requirements.find((one) => one.kind === 'target')
  const allowed = firstTarget && firstTarget.kind === 'target' ? (firstTarget.target_hz * firstTarget.tolerance_pct) / 100 : null
  return (
    <section aria-labelledby="freq-point" className="space-y-3 rounded-md border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="freq-point" className="text-sm font-medium">
          설계점 상세 — {pointName(point)} · {paramsText(point.params)}
        </h2>
        <VerdictBadge verdict={point.verdict} />
      </div>
      <ul className="space-y-1.5 text-sm">
        {point.targets.map((one) => {
          const req = check.requirements[one.requirement]
          if (!req || req.kind !== 'target') return null
          return (
            <li key={`t${one.requirement}`} className="flex gap-2">
              <ResultMark ok={one.ok} unknown={one.frequency_hz == null} />
              <span className="tabular-nums">
                <strong className="font-medium">{req.label || '목표 주파수'}</strong> —{' '}
                {one.frequency_hz == null
                  ? one.note
                  : `${req.mode}차 모드 ${hz(one.frequency_hz)} Hz, 목표 ${hz(req.target_hz)} Hz 대비 ${signedPct(one.error_pct)} (허용 ± ${req.tolerance_pct} %)`}
              </span>
            </li>
          )
        })}
        {point.bands.map((one) => {
          const req = check.requirements[one.requirement]
          if (!req || req.kind !== 'band') return null
          const closest = one.closest_index != null ? modeName({ track: one.closest_track, index: one.closest_index }) : null
          return (
            <li key={`b${one.requirement}`} className="flex gap-2">
              <ResultMark ok={one.ok} />
              <span className="tabular-nums">
                <strong className="font-medium">{req.label || '회피 대역'}</strong> —{' '}
                {closest == null
                  ? '판정 대상 모드가 없습니다 — 판정 대상 문턱을 확인하세요.'
                  : one.inside
                    ? `${closest} ${hz(one.closest_hz)} Hz 가 회피 대역(${hz(req.low_hz)}–${hz(req.high_hz)} Hz) 안입니다.`
                    : `최근접 판정 대상 ${closest} ${hz(one.closest_hz)} Hz — 대역 끝까지 이격 ${one.margin_pct?.toFixed(1)} % (요구 ${req.margin_pct ?? 0} %)`}
              </span>
            </li>
          )
        })}
      </ul>
      {point.sensitivity.length > 0 && allowed != null && (
        <div className="bg-muted/40 space-y-0.5 rounded-md p-3 text-xs tabular-nums">
          <p className="font-medium">공차 민감도 (이웃 설계점 기울기)</p>
          {point.sensitivity.map((one) => (
            <p key={one.factor}>
              {one.factor} 1 단위당 {signedSlope(one.hz_per_unit)} Hz
              {one.equivalent != null &&
                ` — 목표 허용 폭(± ${hz(allowed)} Hz)은 ${one.factor} ± ${Number(one.equivalent.toPrecision(3))} 에 해당`}
            </p>
          ))}
        </div>
      )}
      {point.modes.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] text-xs">
            <thead className="text-muted-foreground">
              <tr className="border-b text-left">
                <th className="py-1.5 pr-2 font-normal">모드</th>
                <th className="py-1.5 pr-2 text-right font-normal">주파수 (Hz)</th>
                {directions.map((direction) => (
                  <th key={direction} className="py-1.5 pr-2 text-right font-normal">
                    {direction} 유효질량
                  </th>
                ))}
                {probe && <th className="py-1.5 pr-2 text-right font-normal">{probe} 응답</th>}
                <th className="py-1.5 font-normal">판정 구분</th>
              </tr>
            </thead>
            <tbody>
              {point.modes.map((mode) => (
                <tr key={mode.index} className="border-b last:border-0">
                  <td className="py-1.5 pr-2">{modeName(mode)}</td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">{hz(mode.frequency_hz)}</td>
                  {directions.map((direction) => (
                    <td key={direction} className="py-1.5 pr-2 text-right tabular-nums">
                      {mode.mass_pct[direction] != null ? `${mode.mass_pct[direction].toFixed(1)} %` : '—'}
                    </td>
                  ))}
                  {probe && (
                    <td className="py-1.5 pr-2 text-right tabular-nums">
                      {mode.probe_pct[probe] != null ? `${mode.probe_pct[probe].toFixed(0)} %` : '—'}
                    </td>
                  )}
                  <td className={cn('py-1.5', mode.role === 'excluded' && 'text-muted-foreground')}>
                    {roleCell(mode, bandNames)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-muted-foreground text-sm">끝나지 않은 설계점이라 모드가 없습니다.</p>
      )}
      {linked && (
        <Link to={`/simulations/${point.simulation_id}`} className="text-sm underline-offset-4 hover:underline">
          결과 열기 →
        </Link>
      )}
    </section>
  )
}

function ResultMark({ ok, unknown = false }: { ok: boolean; unknown?: boolean }) {
  if (unknown) return <CircleDashed className="text-muted-foreground mt-0.5 size-4 shrink-0" aria-label="판정 보류" />
  return ok ? (
    <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-label="충족" />
  ) : (
    <CircleX className="text-destructive mt-0.5 size-4 shrink-0" aria-label="미충족" />
  )
}

function CandidateTable({
  check,
  points,
  filter,
  selected,
  onSelect,
}: {
  check: Check
  points: Point[]
  filter: Verdict | 'all'
  selected: number | null
  onSelect: (number: number) => void
}) {
  const firstTarget = check.requirements.findIndex((one) => one.kind === 'target')
  const error = (point: Point) =>
    Math.abs(point.targets.find((one) => one.requirement === firstTarget)?.error_pct ?? Number.POSITIVE_INFINITY)
  const rows = points
    .filter((one) => filter === 'all' || one.verdict === filter)
    .slice()
    .sort((a, b) => VERDICTS.indexOf(a.verdict) - VERDICTS.indexOf(b.verdict) || error(a) - error(b) || a.number - b.number)
  return (
    <section aria-labelledby="freq-table" className="space-y-3 rounded-md border p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 id="freq-table" className="text-sm font-medium">
            후보 설계점
          </h2>
          <p className="text-muted-foreground text-xs">
            적합 → 대역 침범 → 목표 이탈 → 부적합 → 판정 보류, 같은 판정 안에서는 목표 오차가 작은 차례입니다. 판정 요약을
            눌러 거를 수 있습니다.
          </p>
        </div>
        <span className="text-muted-foreground text-xs tabular-nums">
          {rows.length}개 / 설계점 {points.length}개{filter === 'all' ? '' : ` — ${VERDICT_LABELS[filter]}`}
        </span>
      </div>
      <div className="max-h-[28rem] overflow-auto rounded-md border">
        <table className="w-full min-w-[860px] text-xs">
          <thead className="bg-muted text-muted-foreground sticky top-0">
            <tr className="text-left">
              <th className="px-3 py-2 font-normal">판정</th>
              <th className="px-3 py-2 font-normal">설계점</th>
              {check.factors.map((name) => (
                <th key={name} className="px-3 py-2 text-right font-normal">
                  {name}
                </th>
              ))}
              <th className="px-3 py-2 font-normal">목표 주파수 (오차)</th>
              <th className="px-3 py-2 font-normal">최근접 판정 대상 모드 · 이격 여유</th>
              <th className="px-3 py-2 text-right font-normal">질량</th>
              <th className="px-3 py-2 font-normal">허용 폭 환산 공차</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((point) => {
              const target = point.targets.find((one) => one.requirement === firstTarget)
              const band = worstBand(point)
              return (
                <tr key={point.number} className={cn('border-t', point.number === selected && 'bg-muted/60')}>
                  <td className="px-3 py-1.5">
                    <VerdictBadge verdict={point.verdict} />
                  </td>
                  <td className="px-3 py-1.5">
                    <button
                      type="button"
                      aria-pressed={point.number === selected}
                      onClick={() => onSelect(point.number)}
                      className="font-mono underline-offset-4 hover:underline"
                    >
                      {pointName(point)}
                    </button>
                  </td>
                  {check.factors.map((name) => (
                    <td key={name} className="px-3 py-1.5 text-right tabular-nums">
                      {String(point.params[name] ?? '—')}
                    </td>
                  ))}
                  <td className="px-3 py-1.5 tabular-nums">
                    {target?.frequency_hz != null
                      ? `${hz(target.frequency_hz)} Hz (${signedPct(target.error_pct)})`
                      : (target?.note ?? '—')}
                  </td>
                  <td className="px-3 py-1.5 tabular-nums">
                    {band && band.closest_index != null
                      ? `${modeName({ track: band.closest_track, index: band.closest_index })} ${hz(band.closest_hz)} Hz · ${band.inside ? '회피 대역 안' : `${band.margin_pct?.toFixed(1)} %`}`
                      : '—'}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {shownMass(point.mass_kg)}
                  </td>
                  <td className="text-muted-foreground px-3 py-1.5 tabular-nums">
                    {point.sensitivity
                      .filter((one) => one.equivalent != null)
                      .map((one) => `${one.factor} ± ${Number((one.equivalent ?? 0).toPrecision(3))}`)
                      .join(' · ') || '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
