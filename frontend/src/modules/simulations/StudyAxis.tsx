/**
 * 비교 탭의 **가로축과 단면** — 설계 변수가 여럿일 때 선을 어디까지 이어도 되나(2026-10-25).
 *
 * 2변수 20점(두께 5 x 폭 4)을 폭 축으로 그리니, 폭 값마다 두께가 다른 다섯 점이 세로로 쌓이고 선이
 * 그 사이를 지그재그로 이었다 — 서로 다른 설계를 잇는 거짓 선이다. 그래서:
 *
 *   - **나머지 변수를 고정한 단면**(「폭 = 20」)만 선으로 잇는다. 처음은 가운데 단면이다.
 *   - 「고정 안 함」 이면 잇지 않고 점만 찍는다 — 단면이 없는 무작위 · LHS 설계는 늘 이렇다.
 *   - 처음 가로축은 **그 결과를 가장 크게 움직이는 변수**다(`leadingFactor`) — 변수 차례대로 고르면
 *     1차를 거의 안 움직이는 폭이 먼저 보여 「변화가 없다」 로 읽혔다.
 *
 * 변수가 하나면 아무것도 바뀌지 않는다(단면이 곧 전체다).
 */

import { useCallback, useMemo, useState } from 'react'

import type { Study, StudyPoint } from '@/modules/simulations/api'
import { leadingFactor, slicesOf } from '@/modules/simulations/studyTable'
import type { Slice } from '@/modules/simulations/studyTable'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'

export interface Axis {
  x: string
  setX: (name: string) => void
  slices: Slice[]
  /** 고른 단면 — null 이면 고정하지 않고 점만(또는 변수가 하나). */
  slice: Slice | null
  setSlice: (key: string) => void
  /** 선으로 이어도 되나 — 변수가 하나이거나 단면을 골랐을 때만. */
  connect: boolean
  /** 그림에 놓을 점인가 — 단면을 골랐으면 그 단면의 점만. */
  shows: (point: StudyPoint) => boolean
  /** 가로축이 숫자인가 — 아니면(재료) 선이 아니라 막대로 그린다. 안내 말도 그에 맞춘다. */
  numeric: boolean
}

/** `primary` 는 처음 가로축을 고를 때 볼 결과 열(`mode:1` · `max_mm` …). */
export function useAxis(study: Study, primary: string): Axis {
  const factors = study.factors
  const lead = useMemo(() => leadingFactor(study, primary), [study, primary])
  const [factor, setFactor] = useState<string | null>(null)
  const x = factor ?? lead ?? factors[0] ?? ''
  const slices = useMemo(
    () => slicesOf(study.points.filter((one) => one.status === 'done'), factors, x),
    [study.points, factors, x],
  )
  // 고른 단면은 그 가로축에서만 뜻이 있다 — 가로축을 바꾸면 그 축의 가운데 단면으로 돌아간다.
  const [picked, setPicked] = useState<{ x: string; key: string } | null>(null)
  const key = picked?.x === x ? picked.key : (slices[Math.floor((slices.length - 1) / 2)]?.key ?? '')
  const slice = slices.find((one) => one.key === key) ?? null
  const many = factors.length > 1
  const numeric = study.points.every((one) => typeof one.params[x] !== 'string')
  // 그림이 이것으로 점을 거른다 — 단면이 같으면 같은 함수라야 그림을 다시 셈하지 않는다.
  const shows = useCallback(
    (point: StudyPoint) => !many || slice === null || slice.numbers.has(point.number),
    [many, slice],
  )
  return {
    x,
    setX: setFactor,
    slices,
    slice,
    setSlice: (next) => setPicked({ x, key: next }),
    connect: !many || slice !== null,
    shows,
    numeric,
  }
}

/** 지금 그림이 무엇을 하나 — 숫자 축은 잇는다 · 안 잇는다, 고르는 값(재료) 축은 막대가 어떻게 서나. */
function noteOf(axis: Axis): string {
  if (axis.slice) {
    return axis.numeric
      ? `${axis.slice.label} 인 점 ${axis.slice.numbers.size}개만 잇습니다 — 단면을 바꿔 견줘 보세요.`
      : `${axis.slice.label} 인 점 ${axis.slice.numbers.size}개만 ${axis.x} 마다 막대로 놓습니다 — 단면을 바꿔 견줘 보세요.`
  }
  if (!axis.numeric) {
    return '나머지 변수가 함께 변해 막대마다 설계점을 붙입니다 — 같은 값의 막대가 여럿입니다.'
  }
  return axis.slices.length === 0
    ? '나머지 변수가 같은 점끼리 묶이지 않아(무작위 · LHS 설계) 잇지 않고 점만 찍습니다.'
    : '나머지 변수가 함께 변해 잇지 않고 점만 찍습니다 — 이으면 서로 다른 설계를 잇습니다.'
}

export function AxisPicker({ study, axis }: { study: Study; axis: Axis }) {
  if (study.factors.length < 2) return null
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground text-sm">가로축</span>
        <Select value={axis.x} onValueChange={axis.setX}>
          <SelectTrigger className="h-8 w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {study.factors.map((one) => (
              <SelectItem key={one} value={one}>
                {one}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <label className="flex items-center gap-2">
        <span className="text-muted-foreground text-sm">나머지 고정</span>
        <select
          aria-label="나머지 고정"
          className="border-input bg-background text-foreground h-8 rounded-md border px-2 text-sm"
          value={axis.slice?.key ?? ''}
          onChange={(event) => axis.setSlice(event.target.value)}
        >
          {axis.slices.map((one) => (
            <option key={one.key} value={one.key}>
              {one.label}
            </option>
          ))}
          <option value="">{axis.numeric ? '고정 안 함 — 점만' : '고정 안 함 — 점마다 막대'}</option>
        </select>
      </label>
      <p className="text-muted-foreground text-xs">{noteOf(axis)}</p>
    </div>
  )
}
