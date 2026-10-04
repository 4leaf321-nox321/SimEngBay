/**
 * 작업 창의 칸들 — 새 작업 창과 DOE 가져오기 창이 **같은 칸**을 쓴다(해석 종류 · 메시 ·
 * 조화 설정). 두 창이 각자 들고 있으면 한쪽만 고쳐진다 — 실제로 DOE 창은 재료 이름만 받고
 * 영률 · 밀도는 강으로 못 박아 보내고 있었다(「AL6061」 이라 적어도 강으로 풀렸다).
 */

import { RECIPE_LABELS } from '@/modules/simulations/labels'
import { RECIPE_NAMES } from '@/modules/simulations/spec'
import type { HarmonicInput, MeshOrder, RecipeName } from '@/modules/simulations/spec'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'

const SELECT = 'border-input bg-background h-9 w-full rounded-md border px-3 text-sm'

/** 해석 종류 — CAD 가 적은 것을 미리 고르고, 다르게 고르면 무엇이 빠지는지 말한다. */
export function RecipeSelect({
  id,
  value,
  onChange,
  suggested,
}: {
  id: string
  value: RecipeName
  onChange: (next: RecipeName) => void
  /** CAD 가 적은 해석 종류. 점 파일이 없으면 `undefined`, 적지 않았으면 `null`. */
  suggested?: RecipeName | null
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>해석 종류</Label>
      <select
        id={id}
        className={SELECT}
        value={value}
        onChange={(event) => onChange(event.target.value as RecipeName)}
      >
        {RECIPE_NAMES.map((one) => (
          <option key={one} value={one}>
            {RECIPE_LABELS[one] ?? one}
          </option>
        ))}
      </select>
      {suggested === undefined ? null : suggested === null ? (
        <p className="text-muted-foreground text-xs">CAD 가 해석 종류를 적지 않았습니다.</p>
      ) : suggested === value ? (
        <p className="text-muted-foreground text-xs">CAD 가 적은 해석입니다.</p>
      ) : (
        // **다르게 실행하는 것은 막지 않는다** — 다만 무엇이 빠지는지 말한다.
        <p className="text-xs text-amber-700 dark:text-amber-400">
          CAD 가 적은 해석: {RECIPE_LABELS[suggested]} — CAD 의 하중 · 해석 설정 일부가 반영되지
          않습니다.
        </p>
      )}
    </div>
  )
}

/**
 * 메시 — 전역 요소 크기와 요소 차수. **CalculiX 는 크기가 꼭 있어야 한다**(gmsh 가 제 나름으로
 * 잡으면 같은 형상이 실행마다 다른 메시가 된다) — CAD 의 「전체」 크기가 있으면 비워도 된다.
 */
export function MeshFields({
  idPrefix,
  size,
  onSize,
  order,
  onOrder,
  cadSize,
  needsSize,
}: {
  idPrefix: string
  size: string
  onSize: (next: string) => void
  order: MeshOrder
  onOrder: (next: MeshOrder) => void
  /** CAD 가 「전체」 로 적은 크기(mm). 없으면 `null`. */
  cadSize: number | null
  /** 크기가 어디에도 없어 실행할 수 없는가(CalculiX). */
  needsSize: boolean
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-element`}>요소 크기 (mm)</Label>
        <Input
          id={`${idPrefix}-element`}
          type="number"
          step="any"
          min={0}
          value={size}
          onChange={(event) => onSize(event.target.value)}
          placeholder={cadSize !== null ? `CAD 값 ${cadSize}` : needsSize ? '필수' : '비우면 자동'}
        />
        {cadSize !== null && !size.trim() && (
          <p className="text-muted-foreground text-xs">비우면 CAD 가 적은 크기를 사용합니다.</p>
        )}
        {needsSize && (
          <p className="text-xs text-amber-700 dark:text-amber-400">
            CalculiX 는 요소 크기가 필요합니다 — CAD 가 「전체」 크기를 보내지 않았습니다.
          </p>
        )}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-order`}>요소 차수</Label>
        <select
          id={`${idPrefix}-order`}
          className={SELECT}
          value={order}
          onChange={(event) => onOrder(event.target.value as MeshOrder)}
        >
          <option value="quadratic">2차 (기본)</option>
          <option value="linear">1차</option>
        </select>
        {order === 'linear' && (
          <p className="text-xs text-amber-700 dark:text-amber-400">
            1차 사면체는 굽힘에서 뻣뻣하게 나옵니다 — 주파수가 높고 변형이 작게 나옵니다.
          </p>
        )}
      </div>
    </div>
  )
}

/** 조화 응답의 설정 — **CAD 가 적은 값이 있으면 그것이 먼저다**(범위 · 점 수 · 감쇠비). */
export function HarmonicFields({
  idPrefix,
  value,
  onChange,
  fromCad,
}: {
  idPrefix: string
  value: HarmonicInput
  onChange: (next: HarmonicInput) => void
  /** CAD 가 조화 응답을 적었나 — 그러면 아래 값은 CAD 가 적지 않은 칸에만 쓰인다. */
  fromCad: boolean
}) {
  const set = (key: keyof HarmonicInput) => (event: { target: { value: string } }) =>
    onChange({ ...value, [key]: event.target.value })
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="space-y-1.5">
          <Label htmlFor={`${idPrefix}-low`}>시작 주파수 (Hz)</Label>
          <Input id={`${idPrefix}-low`} type="number" step="any" min={0} value={value.low} onChange={set('low')} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${idPrefix}-high`}>끝 주파수 (Hz)</Label>
          <Input id={`${idPrefix}-high`} type="number" step="any" min={0} value={value.high} onChange={set('high')} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${idPrefix}-intervals`}>점 수</Label>
          <Input
            id={`${idPrefix}-intervals`}
            type="number"
            min={1}
            value={value.intervals}
            onChange={set('intervals')}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${idPrefix}-damping`}>감쇠비 (%)</Label>
          <Input
            id={`${idPrefix}-damping`}
            type="number"
            step="any"
            min={0}
            value={value.dampingPercent}
            onChange={set('dampingPercent')}
          />
        </div>
      </div>
      <p className="text-muted-foreground text-xs">
        {fromCad
          ? 'CAD 가 적은 범위 · 점 수 · 감쇠비가 먼저입니다 — 이 값은 CAD 가 적지 않은 칸에만 사용합니다.'
          : '봉우리 높이는 감쇠비에 거의 반비례합니다(1/2ζ). 점이 적으면 봉우리가 점 사이로 빠져나갑니다.'}
      </p>
    </div>
  )
}
