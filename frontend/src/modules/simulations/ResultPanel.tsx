/**
 * 결과 요약을 받아 그리는 자리 — **못 받으면 왜인지 말한다.**
 *
 * 처음에는 실패를 조용히 삼켰다(「없는 작업도 있으니 카드가 안 뜰 뿐」). 그랬더니 작업 폴더를
 * 못 찾는 설치에서 **글과 표만 나오고 그림이 통째로 사라졌는데 화면은 아무 말도 안 했다** —
 * 실측으로 겪었다(WORK_DIR 이 작업을 만들 때와 달라져 파일이 그 자리에 없었다). 서버는 무엇을
 * 확인해야 하는지까지 메시지에 담아 주는데, 그것을 화면이 버리면 아무 데도 안 남는다.
 */

import { useEffect, useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import type { Artifact, SimulationResult } from '@/modules/simulations/api'
import { ModalResult } from '@/modules/simulations/ModalResult'
import { ApiError } from '@/shared/api/client'
import { ErrorNotice } from '@/shared/components/ErrorNotice'

interface Props {
  simulationId: string
  /** 작업 상태. **끝난 작업에만 결과가 있다** — 도는 동안에는 받지 않는다. */
  status: string
  artifacts: Artifact[]
}

export function ResultPanel({ simulationId, status, artifacts }: Props) {
  const [result, setResult] = useState<SimulationResult | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)

  useEffect(() => {
    setResult(null)
    setError(null)
  }, [simulationId])

  useEffect(() => {
    if (status !== 'done') return
    let disposed = false
    simulationApi
      .result(simulationId)
      .then((next) => {
        if (!disposed) {
          setResult(next)
          setError(null)
        }
      })
      .catch((caught: unknown) => {
        if (disposed) return
        setResult(null)
        setError(caught instanceof Error ? caught : new Error('결과 요약을 받지 못했습니다.'))
      })
    return () => {
      disposed = true
    }
  }, [simulationId, status])

  if (status !== 'done') return null
  if (result) {
    return <ModalResult simulationId={simulationId} result={result} artifacts={artifacts} />
  }
  if (error) {
    return (
      <section className="space-y-2">
        <h2 className="text-sm font-medium">결과</h2>
        <ErrorNotice error={error} />
      </section>
    )
  }
  return <p className="text-muted-foreground text-sm">결과를 불러오는 중…</p>
}
