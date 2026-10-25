/**
 * DOE 대상 작업에 이은 **기준정보** — CompCore 가 `study.json` 의 `ontology` 로 싣는다(2026-10-26).
 *
 * 「어느 모델의 부품 해석인가」 를 폴더만 보고 알게 하는 칸이다: 부품 · 지그의 기준정보 칸(「적용
 * 모델」 …)과 작업의 태그. 우리 온톨로지 사본(Standard Platform 수신)에 같은 타입 · 식별자의
 * 객체가 있으면(`known`) 그 객체로 잇는다 — 없는 것(「일반 태그」 처럼 CompCore 에만 있는 것)은
 * 글자로만 둔다. 그 전에 내보낸 폴더면 아무것도 그리지 않는다.
 */

import { Link } from 'react-router-dom'

import type { StudyOntology as Ontology } from '@/modules/simulations/api'

type Ref = NonNullable<Ontology['tags']>[number]

/** 우리 사본의 그 객체 — 온톨로지 화면이 `type` · `key` 로 연다. */
export function ontologyHref(one: Pick<Ref, 'type_slug' | 'key'>): string {
  return `/ontology?${new URLSearchParams({ type: one.type_slug ?? '', key: one.key ?? '' })}`
}

function Shown({ one }: { one: Ref }) {
  const text = one.key ? `${one.label} (${one.key})` : one.label
  if (!one.known || !one.type_slug || !one.key) return <>{text}</>
  return (
    <Link to={ontologyHref(one)} className="underline-offset-2 hover:underline">
      {text}
    </Link>
  )
}

/**
 * `compact` 면 목록 한 줄에 들어가게 기준정보 칸만 「적용 모델 차종 X」 로 잇는다. 아니면 칸은
 * 주인(부품 · 지그)과 함께, 태그는 그 뒤에 칩으로.
 */
export function StudyOntology({ ontology, compact = false }: { ontology?: Ontology | null; compact?: boolean }) {
  const links = ontology?.links ?? []
  const tags = ontology?.tags ?? []
  if (links.length === 0 && tags.length === 0) return null
  if (compact) {
    if (links.length === 0) return null
    return (
      <p className="text-muted-foreground text-xs">
        {links.map((one, index) => (
          <span key={`${one.on?.id}-${one.relation}-${one.object_id}`}>
            {index > 0 && ' · '}
            {one.relation_label || one.relation} <Shown one={one} />
          </span>
        ))}
      </p>
    )
  }
  return (
    <ul aria-label="기준정보" className="flex flex-wrap gap-1.5 text-xs">
      {links.map((one) => (
        <li key={`${one.on?.id}-${one.relation}-${one.object_id}`} className="bg-muted rounded px-1.5 py-0.5">
          <span className="text-muted-foreground">
            {one.on?.name ? `${one.on.name} — ` : ''}
            {one.relation_label || one.relation}
          </span>{' '}
          <Shown one={one} />
        </li>
      ))}
      {tags.map((one) => (
        <li key={`tag-${one.object_id}-${one.label}`} className="rounded border px-1.5 py-0.5">
          <span className="text-muted-foreground">
            {one.type_slug && one.type_slug !== 'cc_tag' && one.type_label ? one.type_label : '태그'}
          </span>{' '}
          <Shown one={one} />
        </li>
      ))}
    </ul>
  )
}
