/**
 * DOE 폴더 가져오기 — **폴더 한 벌이 계약이다.**
 *
 * CAD 플랫폼(CompCore)이 설계점 N 벌을 폴더로 내놓고 그 뒤로는 아무것도 주고받지 않는다.
 * 결과도 되돌려 보내지 않으므로, 「이 결과가 두께 몇짜리인가」 를 이 플랫폼이 들고 있어야 한다 —
 * 가져올 때 스터디 · 점 번호 · 바꾼 변수를 작업에 함께 적는다.
 *
 * ## 경로를 외워서 치게 하지 않는다
 *
 * 공유 스토리지의 자리는 `/mnt/f/data/0_Program/73_CompCore/브래킷_튜닝-3f9a21` 같은 것이라
 * 사람이 외울 수 없다. 그렇다고 **아무 경로나 받으면** 그 칸이 서버의 모든 폴더를 여는 문이
 * 된다(서버가 막는다 — `DOE_ROOTS`). 그래서 **설정된 공용 폴더 아래를 탐색기처럼 고른다.**
 *
 * ## 먼저 보여 주고 나서 건다
 *
 * 200개를 잘못 걸면 되돌리기 어렵고, 그 사이 Mechanical 라이선스를 계속 문다. 그래서 폴더를
 * 고르면 **훑어 본 결과**(점 몇 개 · 변수 무엇 · 건너뛸 것 몇 개와 그 이유)를 먼저 보인다.
 */

import { useEffect, useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import type { DoeImport, DoeListing, DoePreview } from '@/modules/simulations/api'
import { ApiError } from '@/shared/api/client'
import { useAuth } from '@/shared/auth/AuthContext'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Folder, FolderOpen, ChevronUp } from 'lucide-react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'

interface Props {
  open: boolean
  onClose: () => void
  onImported: (result: DoeImport) => void
}

export function DoeImportDialog({ open, onClose, onImported }: Props) {
  const { user } = useAuth()
  const [listing, setListing] = useState<DoeListing | null>(null)
  const [preview, setPreview] = useState<DoePreview | null>(null)
  const [material, setMaterial] = useState('SS400')
  const [modes, setModes] = useState('10')
  const [region, setRegion] = useState('bolt_holes')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | Error | null>(null)

  const workspace = user?.home_workspace_slug ?? user?.memberships[0]?.slug ?? null

  // 창을 열면 첫 뿌리부터 보여 준다 — 사람이 아무것도 안 쳐도 고를 것이 있어야 한다.
  useEffect(() => {
    if (!open) return
    setPreview(null)
    setError(null)
    void browse()
    // 창이 열릴 때 한 번. 그 뒤로는 사람이 폴더를 누를 때만 움직인다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  async function browse(path?: string) {
    setBusy(true)
    setError(null)
    try {
      const next = await simulationApi.browseDoe(path)
      setListing(next)
      // **DOE 폴더로 들어갔으면 곧바로 훑어 본다** — 한 번 더 누르게 하지 않는다.
      setPreview(next.is_study ? await simulationApi.previewDoe(next.path) : null)
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('폴더를 읽지 못했습니다.'))
    } finally {
      setBusy(false)
    }
  }

  async function run() {
    if (!preview) return
    setBusy(true)
    setError(null)
    try {
      const result = await simulationApi.importDoe({
        path: preview.path,
        workspace_slug: workspace,
        spec: {
          recipe: 'modal',
          material: {
            name: material.trim(),
            youngs_modulus_gpa: 200,
            poisson_ratio: 0.3,
            density_kg_m3: 7850,
          },
          modes: Number(modes),
          // **모든 점에 같은 스펙을 쓴다** — 그래야 결과를 견줄 수 있다(그러려고 DOE 를 돌린다).
          constraints: region.trim() ? [{ region: region.trim(), kind: 'fixed' }] : [],
        },
      })
      onImported(result)
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('가져오지 못했습니다.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>DOE 가져오기</DialogTitle>
          <DialogDescription>
            CAD 플랫폼이 내보낸 폴더를 읽어 설계점마다 해석 작업을 만듭니다. <b>공용 폴더</b>
            아래만 보입니다(관리자가 <span className="font-mono">DOE_ROOTS</span> 로 정합니다).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* 탐색기 — 뿌리 아래를 눌러 들어간다. 「고를 수 있는 폴더」 는 표시가 다르다. */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <Label>공용 폴더</Label>
              {(listing?.roots?.length ?? 0) > 1 && (
                <div className="flex gap-1">
                  {(listing?.roots ?? []).map((root) => (
                    <Button
                      key={root}
                      variant={listing?.path.startsWith(root) ? 'secondary' : 'ghost'}
                      size="sm"
                      onClick={() => void browse(root)}
                      className="font-mono text-xs"
                    >
                      {root}
                    </Button>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="icon"
                className="size-8 shrink-0"
                disabled={!listing?.parent || busy}
                onClick={() => listing?.parent && void browse(listing.parent)}
                aria-label="한 칸 위"
              >
                <ChevronUp className="size-4" />
              </Button>
              <p className="text-muted-foreground truncate font-mono text-xs" title={listing?.path}>
                {listing?.path ?? '…'}
              </p>
            </div>
            <div className="max-h-48 overflow-y-auto rounded-md border">
              {listing && listing.entries.length === 0 ? (
                <p className="text-muted-foreground p-3 text-sm">
                  {listing.is_study
                    ? '이 폴더가 DOE 입니다. 아래에서 확인하고 실행하세요.'
                    : '하위 폴더가 없습니다.'}
                </p>
              ) : (
                <ul className="divide-y">
                  {(listing?.entries ?? []).map((entry) => (
                    <li key={entry.path}>
                      <button
                        type="button"
                        onClick={() => void browse(entry.path)}
                        className="hover:bg-muted/50 flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm"
                      >
                        {entry.is_study ? (
                          <FolderOpen className="size-4 shrink-0 text-emerald-600" />
                        ) : (
                          <Folder className="text-muted-foreground size-4 shrink-0" />
                        )}
                        <span className="truncate">{entry.name}</span>
                        {/* **눌러 보고 알게 하지 않는다** — 가져올 수 있는 폴더를 미리 표시한다. */}
                        {entry.is_study && (
                          <span className="text-muted-foreground ml-auto text-xs">DOE</span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {listing?.truncated && (
              <p className="text-muted-foreground text-xs">
                폴더가 너무 많아 일부만 보여 줍니다. 하위 폴더로 들어가 좁히세요.
              </p>
            )}
          </div>

          <ErrorNotice error={error} />

          {preview && (
            <>
              <div className="rounded-md border p-3 text-sm">
                <p className="font-medium">{preview.name}</p>
                <p className="text-muted-foreground text-xs">
                  변수 {preview.factors.join(' · ') || '없음'}
                  {preview.method ? ` · ${preview.method}` : ''}
                  {preview.seed != null ? ` · 시드 ${preview.seed}` : ''}
                </p>
                <p className="mt-1">
                  걸 수 있는 점 <b>{preview.usable}</b>개
                  {preview.skipped > 0 && (
                    <span className="text-amber-700 dark:text-amber-400">
                      {' '}
                      · 건너뜀 {preview.skipped}개
                    </span>
                  )}
                </p>
              </div>

              <div className="max-h-56 overflow-y-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>점</TableHead>
                      {preview.factors.map((one) => (
                        <TableHead key={one}>{one}</TableHead>
                      ))}
                      <TableHead>상태</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {preview.points.map((point) => (
                      <TableRow key={point.number}>
                        <TableCell className="font-mono">
                          p{String(point.number).padStart(4, '0')}
                        </TableCell>
                        {preview.factors.map((one) => (
                          <TableCell key={one} className="font-mono">
                            {point.params[one] ?? '—'}
                          </TableCell>
                        ))}
                        <TableCell>
                          {point.usable ? (
                            <span className="text-muted-foreground">걸 수 있음</span>
                          ) : (
                            // **왜 못 거는지 그대로 보여 준다** — 「절반이 실패」 를 로그에서
                            // 찾게 하지 않는다.
                            <span className="text-amber-700 dark:text-amber-400">
                              {point.skip_reason}
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              <fieldset className="grid grid-cols-3 gap-3 rounded-md border p-3">
                <legend className="px-1 text-sm font-medium">모든 점에 같은 조건</legend>
                <div className="space-y-1.5">
                  <Label htmlFor="doe-material">재료</Label>
                  <Input
                    id="doe-material"
                    value={material}
                    onChange={(event) => setMaterial(event.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="doe-modes">모드 수</Label>
                  <Input
                    id="doe-modes"
                    type="number"
                    min={1}
                    value={modes}
                    onChange={(event) => setModes(event.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="doe-region">구속 영역</Label>
                  <Input
                    id="doe-region"
                    value={region}
                    onChange={(event) => setRegion(event.target.value)}
                    placeholder="비우면 자유-자유"
                    className="font-mono"
                  />
                </div>
              </fieldset>
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            취소
          </Button>
          <Button onClick={run} disabled={!preview || preview.usable === 0 || busy}>
            {busy ? '거는 중…' : `${preview?.usable ?? 0}건 실행`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
