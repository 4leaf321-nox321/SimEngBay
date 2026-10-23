/**
 * 폴더 — 경로 문자열(`고객A/2026/브래킷`)을 나무로. 해석 작업 · DOE 목록이 같이 쓴다.
 *
 * **CompCore 의 폴더(`shared/folders`)를 그대로 옮겼다** — 두 플랫폼을 오가는 사람이 같은 손놀림을
 * 쓰게(docs/adr/0013). 폴더는 서버에 표가 따로 없다 — 항목이 들고 있는 경로에서 나무를 세운다. 그래서
 * **빈 폴더**는 항목을 옮겨 넣기 전까지 이 브라우저에만 있다(`pending`).
 */

import { STORAGE_PREFIX } from '@/shared/branding'

/** 폴더 하나 — 경로와 **바로 그 폴더에** 있는 항목 수. 위 폴더도 빠짐없이 온다. */
export interface FolderRow {
  path: string
  count: number
}

export interface FolderNode {
  path: string
  name: string
  /** 바로 이 폴더에 있는 항목 수. */
  count: number
  /** 하위 폴더까지 합친 수. */
  total: number
  children: FolderNode[]
}

/** 폴더를 쓰는 공간이 서버에 묻는 것 — 넷이 같은 모양이다. */
export interface FolderApi {
  folders: () => Promise<FolderRow[]>
  renameFolder: (path: string, to: string) => Promise<{ moved: number }>
  move: (ids: string[], folder: string) => Promise<{ moved: number }>
}

/** 서버의 정리와 같은 모양 — `/고객A//2026/ ` → `고객A/2026`. 역슬래시도 나눈다. */
export function normalizePath(raw: string): string {
  return raw
    .replace(/\\/g, '/')
    .split('/')
    .map((one) => one.trim())
    .filter(Boolean)
    .join('/')
}

export function parentOf(path: string): string {
  const at = path.lastIndexOf('/')
  return at < 0 ? '' : path.slice(0, at)
}

export function nameOf(path: string): string {
  return path.slice(path.lastIndexOf('/') + 1)
}

export function joinPath(parent: string, name: string): string {
  return normalizePath(parent ? `${parent}/${name}` : name)
}

/** `path` 가 `folder` 이거나 그 아래인가. */
export function isWithin(path: string, folder: string): boolean {
  return path === folder || path.startsWith(`${folder}/`)
}

/** 이름 뒤 조사 — 받침이 있으면 `consonant`(을 · 이), 없으면 `vowel`(를 · 가). */
export function josa(noun: string, consonant: string, vowel: string): string {
  const code = noun.charCodeAt(noun.length - 1) - 0xac00
  const final = code >= 0 && code < 11172 && code % 28 !== 0
  return noun + (final ? consonant : vowel)
}

/** 화면에 보이는 경로 — `고객A › 2026`. */
export function shownPath(path: string): string {
  return path.split('/').join(' › ')
}

/** 경로들 → 나무. 맨 위(빈 경로)는 나무에 넣지 않는다 — 화면이 「폴더 없음」 으로 따로 보인다. */
export function buildTree(rows: FolderRow[], pending: string[] = []): FolderNode[] {
  const nodes = new Map<string, FolderNode>()
  const ensure = (path: string): FolderNode => {
    const found = nodes.get(path)
    if (found) return found
    const made: FolderNode = { path, name: nameOf(path), count: 0, total: 0, children: [] }
    nodes.set(path, made)
    const parent = parentOf(path)
    if (path.includes('/')) ensure(parent).children.push(made)
    return made
  }
  for (const row of rows) if (row.path) ensure(row.path).count += row.count
  for (const path of pending) if (path) ensure(path)
  const totals = (node: FolderNode): number => {
    node.children.sort((a, b) => a.name.localeCompare(b.name, 'ko'))
    node.total = node.count + node.children.reduce((sum, child) => sum + totals(child), 0)
    return node.total
  }
  const roots = [...nodes.values()].filter((node) => !node.path.includes('/'))
  roots.sort((a, b) => a.name.localeCompare(b.name, 'ko'))
  roots.forEach(totals)
  return roots
}

/** 끌어다 놓을 때 싣는 것 — 항목 id 들. 한 화면에 한 공간뿐이라 하나로 족하다. */
export const DRAG_TYPE = `application/x-${STORAGE_PREFIX}-items`

/** 항목을 넣기 전의 빈 폴더 — 이 브라우저에만, 공간마다 따로. 저장소가 막혀 있어도 화면은 돈다. */
export function loadPending(space: string): string[] {
  try {
    const raw = window.localStorage.getItem(`${STORAGE_PREFIX}.${space}.pendingFolders`)
    const parsed = raw ? (JSON.parse(raw) as unknown) : []
    return Array.isArray(parsed) ? parsed.filter((one): one is string => typeof one === 'string') : []
  } catch {
    return []
  }
}

export function savePending(space: string, paths: string[]): void {
  try {
    window.localStorage.setItem(`${STORAGE_PREFIX}.${space}.pendingFolders`, JSON.stringify(paths))
  } catch {
    // 저장 못 해도 이번 화면에서는 보인다.
  }
}
