/**
 * 새 해석 작업 — 형상 파일 하나 + 물성 + 모드 수.
 *
 * 지금은 레시피가 `modal` 하나고 구속이 없다(자유-자유). 앞 6개 모드는 강체(≈0 Hz)로 나온다는
 * 것을 여기서 말해 둔다 — 결과 표에서 0 Hz 를 보고 「고장났다」 고 읽지 않게.
 */

import { useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import type { Simulation } from '@/modules/simulations/api'
import { ApiError } from '@/shared/api/client'
import { useAuth } from '@/shared/auth/AuthContext'
import { isSystemAdmin } from '@/shared/auth/roles'
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'

/** 전역(부서 없음)을 뜻하는 Select 값. 빈 문자열은 Select 가 못 받는다. */
const GLOBAL = '__global__'

interface Props {
  open: boolean
  onClose: () => void
  onCreated: (simulation: Simulation) => void
}

export function NewSimulationDialog({ open, onClose, onCreated }: Props) {
  const { user } = useAuth()
  const admin = isSystemAdmin(user)
  const memberships = user?.memberships ?? []

  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [workspace, setWorkspace] = useState<string>(
    user?.home_workspace_slug ?? memberships[0]?.slug ?? GLOBAL,
  )
  const [material, setMaterial] = useState('SS400')
  const [youngs, setYoungs] = useState('200')
  const [poisson, setPoisson] = useState('0.3')
  const [density, setDensity] = useState('7850')
  const [modes, setModes] = useState('10')
  const [elementSize, setElementSize] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | Error | null>(null)

  const ready = file !== null && material.trim() !== '' && !busy

  async function submit() {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const created = await simulationApi.create({
        file,
        name: name.trim() || undefined,
        workspaceSlug: workspace === GLOBAL ? null : workspace,
        spec: {
          recipe: 'modal',
          material: {
            name: material.trim(),
            youngs_modulus_gpa: Number(youngs),
            poisson_ratio: Number(poisson),
            density_kg_m3: Number(density),
          },
          mesh: elementSize.trim() ? { element_size_mm: Number(elementSize) } : {},
          modes: Number(modes),
          constraints: [],
        },
      })
      onCreated(created)
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('알 수 없는 오류'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>새 해석 작업</DialogTitle>
          <DialogDescription>
            STEP 형상 하나로 모달 해석을 실행합니다. 구속이 없는 자유-자유 해석이라 앞 6개 모드는
            강체(≈0 Hz)로 표시됩니다.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="sim-file">형상 파일 (STEP)</Label>
            <Input
              id="sim-file"
              type="file"
              accept=".step,.stp,.x_t,.xt"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sim-name">이름</Label>
              <Input
                id="sim-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={file?.name ?? '비우면 파일 이름'}
              />
            </div>
            <div className="space-y-1.5">
              <Label>부서</Label>
              <Select value={workspace} onValueChange={setWorkspace}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {memberships.map((one) => (
                    <SelectItem key={one.slug} value={one.slug}>
                      {one.name}
                    </SelectItem>
                  ))}
                  {/* 전역은 여러 부서가 함께 보는 자리 — 시스템 관리자만 만든다. */}
                  {admin && <SelectItem value={GLOBAL}>전역(부서 없음)</SelectItem>}
                </SelectContent>
              </Select>
            </div>
          </div>

          <fieldset className="space-y-3 rounded-md border p-3">
            <legend className="px-1 text-sm font-medium">물성 (등방성 선형 탄성)</legend>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="sim-material">재료 이름</Label>
                <Input
                  id="sim-material"
                  value={material}
                  onChange={(event) => setMaterial(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sim-youngs">탄성계수 E (GPa)</Label>
                <Input
                  id="sim-youngs"
                  type="number"
                  step="any"
                  value={youngs}
                  onChange={(event) => setYoungs(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sim-poisson">푸아송비 ν</Label>
                <Input
                  id="sim-poisson"
                  type="number"
                  step="0.01"
                  value={poisson}
                  onChange={(event) => setPoisson(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sim-density">밀도 ρ (kg/m³)</Label>
                <Input
                  id="sim-density"
                  type="number"
                  step="any"
                  value={density}
                  onChange={(event) => setDensity(event.target.value)}
                />
              </div>
            </div>
          </fieldset>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sim-modes">탄성 모드 수</Label>
              <Input
                id="sim-modes"
                type="number"
                min={1}
                max={100}
                value={modes}
                onChange={(event) => setModes(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sim-element">요소 크기 (mm)</Label>
              <Input
                id="sim-element"
                type="number"
                step="any"
                value={elementSize}
                onChange={(event) => setElementSize(event.target.value)}
                placeholder="비우면 자동"
              />
            </div>
          </div>

          <ErrorNotice error={error} />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            취소
          </Button>
          <Button onClick={submit} disabled={!ready}>
            {busy ? '업로드 중…' : '실행'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
