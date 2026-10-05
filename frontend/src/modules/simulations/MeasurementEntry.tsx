/**
 * **실측을 화면의 표에 넣는다** — 작업과 스터디가 함께 쓴다.
 *
 * 전에는 양식(CSV)을 내려받아 채우고 그 파일을 올렸다. 회사 PC 는 로컬에 저장한 파일에 DRM 이
 * 걸려 그 길이 막힌다(2026-10-05). 그래서 **표가 화면에 있고, 엑셀과는 클립보드로** 주고받는다:
 *
 * - 엑셀에서 범위를 복사해 표의 칸에서 Ctrl+V — 그 칸부터 채운다. 머리줄(측정점 · 종류 …)까지
 *   복사했으면 열 이름으로 맞춰 표를 통째로 바꾼다(장비 열 이름도 서버와 같은 별칭으로 안다).
 * - 「표 복사」 는 머리줄과 함께 탭으로 가른 줄로 — 엑셀에 그대로 붙는다.
 * - 「검토」 는 표를 그대로(JSON) 서버에 보낸다. 줄 번호가 표의 번호와 같아서, 고칠 곳을 그 줄에
 *   표시한다(서버는 고칠 곳을 전부 한 번에 돌려준다 — `backend/app/core/measured.py`).
 */

import { useState } from 'react'
import type { ClipboardEvent } from 'react'
import { ClipboardCopy, ClipboardPaste, Plus, Trash2 } from 'lucide-react'

import { ApiError } from '@/shared/api/client'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { copyText, parseGrid, readText, toTsv } from '@/shared/lib/clipboard'

/** 열 — 서버의 열 이름 그대로(`measured.py` 의 `_COLUMNS` 첫 별칭). */
export const COLUMNS = [
  { key: '측정점', label: '측정점', hint: 'CAD 점 그룹 이름' },
  { key: '종류', label: '종류', hint: '공진 · FRF · 변위 · 변형률', list: 'measurement-kinds' },
  { key: '주파수', label: '주파수 (Hz)', hint: '' },
  { key: '값', label: '값', hint: '' },
  { key: '단위', label: '단위', hint: 'mm · m/s2 · g · ue', list: 'measurement-units' },
  { key: '성분', label: '성분', hint: 'x · y · z · 크기', list: 'measurement-components' },
] as const

/** 붙여넣은 머리줄을 알아보는 별칭 — 서버(`measured.py` `_COLUMNS`)와 같다. */
const ALIASES: Record<string, string[]> = {
  측정점: ['측정점', 'probe', 'point', 'sensor', '센서', '위치'],
  종류: ['종류', 'kind', 'type'],
  주파수: ['주파수', 'frequency', 'frequencyhz', 'freq', 'hz', '주파수hz'],
  값: ['값', 'value', 'amplitude', '진폭'],
  단위: ['단위', 'unit', 'units'],
  성분: ['성분', 'component', 'direction', '방향', 'axis', '축'],
}

const key = (text: string) => text.trim().toLowerCase().replace(/[\s_()[\]]/g, '')

/** 머리줄이면 열마다 어느 칸인가(모르면 -1), 아니면 null. 둘 이상 알아봐야 머리줄로 본다. */
export function headerColumns(cells: string[]): number[] | null {
  const mapped = cells.map((cell) => COLUMNS.findIndex((column) => ALIASES[column.key].includes(key(cell))))
  return mapped.filter((one) => one >= 0).length >= 2 ? mapped : null
}

type Row = string[]
const WIDTH = COLUMNS.length
const blank = (): Row => Array(WIDTH).fill('')
const isBlank = (row: Row) => row.every((cell) => !cell.trim())

/** 처음 보이는 빈 줄 수. */
const START_ROWS = 6

/** 예시 — 종류 넷을 한 표에(서버 양식과 같다). */
export const EXAMPLE: Row[] = [
  ['측정점', '공진', '1250.3', '', '', ''],
  ['측정점', '공진', '3410', '', '', ''],
  ['측정점', 'FRF', '1200', '0.031', 'mm', 'x'],
  ['측정점', 'FRF', '1250', '0.402', 'mm', 'x'],
  ['측정점', 'FRF', '1300', '0.044', 'mm', 'x'],
  ['이음 입구 위판', '변위', '', '0.0401', 'mm', 'x'],
  ['이음 입구 위판', '변형률', '', '-120', 'ue', 'z'],
]

/** 끝의 빈 줄은 보내지 않는다 — 가운데 빈 줄은 줄 번호를 맞추려고 그대로 보낸다(서버가 건너뛴다). */
function trimmed(rows: Row[]): Row[] {
  let end = rows.length
  while (end > 0 && isBlank(rows[end - 1])) end -= 1
  return rows.slice(0, end)
}

/** 붙여넣은 칸들을 (줄, 열)부터 채운다 — 모자라면 줄을 늘린다. 머리줄이 있으면 표를 바꾼다. */
export function pasted(rows: Row[], grid: string[][], at: { row: number; column: number }): Row[] {
  const header = grid.length > 0 ? headerColumns(grid[0]) : null
  if (header) {
    const body = grid.slice(1).map((cells) => {
      const row = blank()
      cells.forEach((cell, index) => {
        if (header[index] >= 0) row[header[index]] = cell
      })
      return row
    })
    return body.length > 0 ? body : [blank()]
  }
  const next = rows.map((row) => [...row])
  grid.forEach((cells, offset) => {
    const target = at.row + offset
    while (next.length <= target) next.push(blank())
    cells.forEach((cell, index) => {
      const column = at.column + index
      if (column < WIDTH) next[target][column] = cell
    })
  })
  return next
}

/** 붙여 넣은 뒤의 한 마디 — 머리줄은 줄로 세지 않는다. */
function pastedNotice(grid: string[][]): string {
  const header = grid.length > 0 && headerColumns(grid[0]) !== null
  const count = header ? grid.length - 1 : grid.length
  return header ? `머리줄로 열을 맞춰 ${count}줄을 넣었습니다.` : `${count}줄을 붙여 넣었습니다.`
}

/** 서버의 「N줄: …」 → 표의 줄 번호(머리가 1 줄이라 하나 뺀다). */
export function errorRows(errors: string[]): Set<number> {
  const found = new Set<number>()
  for (const one of errors) {
    const match = /^(\d+)줄/.exec(one)
    if (match) found.add(Number(match[1]) - 1)
  }
  return found
}

export function MeasurementEntry({ onSubmit }: { onSubmit: (file: File, label: string) => Promise<void> }) {
  const [rows, setRows] = useState<Row[]>(() => Array.from({ length: START_ROWS }, blank))
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const filled = rows.filter((row) => !isBlank(row)).length
  const details =
    error instanceof ApiError && Array.isArray((error.details as { errors?: unknown })?.errors)
      ? ((error.details as { errors: string[] }).errors ?? [])
      : []
  const marked = errorRows(details)
  // 서버의 줄 번호를 표의 번호로 — 「3줄: …」 이 표의 2번 줄이다.
  const shownDetails = details.map((one) => one.replace(/^(\d+)줄/, (_, line: string) => `${Number(line) - 1}번 줄`))

  function edit(row: number, column: number, value: string) {
    setRows((current) => current.map((cells, at) => (at === row ? cells.map((cell, index) => (index === column ? value : cell)) : cells)))
  }

  function onPaste(event: ClipboardEvent<HTMLInputElement>, row: number, column: number) {
    const text = event.clipboardData.getData('text/plain')
    // 한 칸짜리는 보통의 붙여넣기다 — 여러 칸(탭 · 줄바꿈)일 때만 표로 편다.
    if (!/[\t\n]/.test(text.replace(/\n+$/, ''))) return
    event.preventDefault()
    const grid = parseGrid(text)
    setRows((current) => pasted(current, grid, { row, column }))
    setNotice(pastedNotice(grid))
  }

  async function pasteFromClipboard() {
    const text = await readText()
    if (text === null) {
      setNotice('이 브라우저에서는 단추로 클립보드를 못 읽습니다 — 표의 첫 칸을 누르고 Ctrl+V 하세요.')
      return
    }
    const grid = parseGrid(text)
    // 채운 줄 다음부터 잇는다 — 빈 표면 첫 줄부터.
    setRows((current) => pasted(current, grid, { row: trimmed(current).length, column: 0 }))
    setNotice(pastedNotice(grid))
  }

  async function copyTable() {
    const body = trimmed(rows)
    try {
      await copyText(toTsv([COLUMNS.map((column) => column.key), ...body]))
      setNotice(`머리줄과 ${body.length}줄을 복사했습니다 — 엑셀에 붙여 넣으면 됩니다.`)
    } catch {
      setNotice('복사하지 못했습니다 — 표를 끌어 골라 Ctrl+C 하세요.')
    }
  }

  async function submit() {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const body = trimmed(rows).map((row) => Object.fromEntries(COLUMNS.map((column, index) => [column.key, row[index]])))
      const file = new File([JSON.stringify({ rows: body })], '화면 입력.json', { type: 'application/json' })
      await onSubmit(file, label)
      setRows(Array.from({ length: START_ROWS }, blank))
      setLabel('')
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('실측을 검토하지 못했습니다.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3 rounded-md border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => void pasteFromClipboard()}>
          <ClipboardPaste className="size-4" />
          붙여넣기
        </Button>
        <Button variant="outline" size="sm" onClick={() => void copyTable()}>
          <ClipboardCopy className="size-4" />
          표 복사
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setRows(EXAMPLE.map((row) => [...row]))}>
          예시 넣기
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setRows((current) => [...current, blank()])}>
          <Plus className="size-4" />줄 추가
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={filled === 0}
          onClick={() => {
            setRows(Array.from({ length: START_ROWS }, blank))
            setError(null)
            setNotice(null)
          }}
        >
          비우기
        </Button>
        <span className="text-muted-foreground ml-auto text-xs">{filled}줄</span>
      </div>
      <p className="text-muted-foreground text-xs">
        엑셀에서 범위를 복사해 표의 칸에서 Ctrl+V 하면 그 칸부터 채웁니다. 머리줄(측정점 · 종류 · 주파수 · 값 · 단위 ·
        성분)까지 복사하면 열 이름으로 맞춥니다. 측정점 이름은 CAD 점 그룹 이름과 같아야 합니다.
      </p>

      <div className="max-h-96 overflow-auto rounded-md border">
        <table className="w-full text-sm" aria-label="실측 표">
          <thead className="bg-muted/50 sticky top-0 z-10">
            <tr>
              <th className="w-10 px-2 py-1.5 text-right text-xs font-medium">#</th>
              {COLUMNS.map((column) => (
                <th key={column.key} className="px-1 py-1.5 text-left text-xs font-medium">
                  {column.label}
                </th>
              ))}
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex} className={marked.has(rowIndex + 1) ? 'bg-destructive/10' : undefined}>
                <td className="text-muted-foreground px-2 text-right font-mono text-xs">{rowIndex + 1}</td>
                {COLUMNS.map((column, columnIndex) => (
                  <td key={column.key} className="px-0.5 py-0.5">
                    <input
                      aria-label={`${rowIndex + 1}번 줄 ${column.label}`}
                      className="border-input bg-background h-8 w-full min-w-20 rounded border px-2 text-sm"
                      value={row[columnIndex]}
                      placeholder={rowIndex === 0 ? column.hint : undefined}
                      list={'list' in column ? column.list : undefined}
                      onChange={(event) => edit(rowIndex, columnIndex, event.target.value)}
                      onPaste={(event) => onPaste(event, rowIndex, columnIndex)}
                    />
                  </td>
                ))}
                <td className="px-1">
                  <button
                    type="button"
                    aria-label={`${rowIndex + 1}번 줄 지우기`}
                    className="text-muted-foreground hover:text-destructive"
                    onClick={() => setRows((current) => (current.length > 1 ? current.filter((_, at) => at !== rowIndex) : [blank()]))}
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <datalist id="measurement-kinds">
          {['공진', 'FRF', '변위', '변형률'].map((one) => (
            <option key={one} value={one} />
          ))}
        </datalist>
        <datalist id="measurement-units">
          {['mm', 'um', 'm', 'mm/s', 'm/s', 'm/s2', 'g', 'mm/N', 'g/N', 'ue'].map((one) => (
            <option key={one} value={one} />
          ))}
        </datalist>
        <datalist id="measurement-components">
          {['x', 'y', 'z', '크기'].map((one) => (
            <option key={one} value={one} />
          ))}
        </datalist>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="measurement-label">이름</Label>
          <Input
            id="measurement-label"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="예: 시편 1 · 10월 1일"
          />
        </div>
        <Button size="sm" onClick={() => void submit()} disabled={filled === 0 || busy}>
          {busy ? '검토 중…' : '검토'}
        </Button>
        {notice && <p className="text-muted-foreground text-xs">{notice}</p>}
      </div>
      {shownDetails.length > 0 ? (
        // 고칠 곳은 **표의 줄 번호로** 전부 — 그 줄도 붉게 칠했다.
        <div className="text-destructive space-y-1 text-xs" role="alert">
          <p className="font-medium">고칠 곳이 {shownDetails.length}개 있습니다</p>
          <ul className="space-y-0.5">
            {shownDetails.map((one) => (
              <li key={one}>{one}</li>
            ))}
          </ul>
        </div>
      ) : (
        <ErrorNotice error={error} />
      )}
    </div>
  )
}
