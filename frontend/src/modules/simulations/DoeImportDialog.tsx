/**
 * DOE 폴더 가져오기 — **폴더 한 벌이 계약이다.**
 *
 * CAD 플랫폼(CompCore)이 설계점 N 벌을 폴더로 내놓고 그 뒤로는 아무것도 주고받지 않는다.
 * 결과도 되돌려 보내지 않으므로, 「이 결과가 두께 몇짜리인가」 를 이 플랫폼이 들고 있어야 한다 —
 * 가져올 때 스터디 · 점 번호 · 바꾼 변수를 작업에 함께 적는다.
 *
 * ## 먼저 보여 주고 나서 건다
 *
 * 200개를 잘못 걸면 되돌리기 어렵고, 그 사이 Mechanical 라이선스를 계속 문다. 그래서 경로를
 * 주면 **훑어 본 결과**(점 몇 개 · 변수 무엇 · 건너뛸 것 몇 개와 그 이유)를 먼저 보인다.
 */

import { useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import type { DoeImport, DoePreview } from '@/modules/simulations/api'
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
  const [path, setPath] = useState('')
  const [preview, setPreview] = useState<DoePreview | null>(null)
  const [material, setMaterial] = useState('SS400')
  const [modes, setModes] = useState('10')
  const [region, setRegion] = useState('bolt_holes')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | Error | null>(null)

  const workspace = user?.home_workspace_slug ?? user?.memberships[0]?.slug ?? null

  async function look() {
    setBusy(true)
    setError(null)
    setPreview(null)
    try {
      setPreview(await simulationApi.previewDoe(path.trim()))
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
            CAD 플랫폼이 내보낸 폴더를 읽어 설계점마다 해석 작업을 만듭니다. 폴더는 <b>서버가
            보는 경로</b>입니다 — 공유 스토리지의 자리를 적으세요.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="doe-path">폴더 경로</Label>
            <div className="flex gap-2">
              <Input
                id="doe-path"
                value={path}
                onChange={(event) => setPath(event.target.value)}
                placeholder="/data/doe/브래킷_튜닝-3f9a21"
                className="font-mono"
              />
              <Button variant="outline" onClick={look} disabled={!path.trim() || busy}>
                훑어 보기
              </Button>
            </div>
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
