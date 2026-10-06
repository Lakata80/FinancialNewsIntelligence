import { useState } from 'react'
import { apiFetch } from '../../api/client'
import { usePipelineRun } from '../../api/hooks/usePipeline'

interface PipelineEstimateOut {
  new_clusters: number
  changed_clusters: number
  total_clusters_to_process: number
  estimated_cost_usd: number
  show_warning: boolean
}

const STAGE_LABELS: Record<string, string> = {
  pending: 'Подготовка…',
  fetch: 'Зареждане…',
  dedup: 'Дедупликация…',
  classify: 'Класифициране…',
  summarize: 'Обобщаване…',
  verify: 'Проверка…',
  done: 'Готово',
}

export function RefreshButton() {
  const { trigger, isRunning, stage, done, error, reset } = usePipelineRun()
  const [pendingEstimate, setPendingEstimate] = useState<PipelineEstimateOut | null>(null)
  const [estimating, setEstimating] = useState(false)

  async function handleClick() {
    setEstimating(true)
    try {
      const est = await apiFetch<PipelineEstimateOut>('/api/pipeline/estimate')
      if (est.show_warning) {
        setPendingEstimate(est)
      } else {
        trigger()
      }
    } catch {
      trigger()
    } finally {
      setEstimating(false)
    }
  }

  if (done && !error) {
    return (
      <button
        onClick={reset}
        data-testid="refresh-button"
        className="rounded px-3 py-1 text-sm bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300"
      >
        ✓ Готово
      </button>
    )
  }

  if (error) {
    return (
      <button
        onClick={reset}
        data-testid="refresh-button"
        className="rounded px-3 py-1 text-sm bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300"
        title={error}
      >
        ✗ Грешка
      </button>
    )
  }

  if (isRunning) {
    return (
      <span data-testid="refresh-button" className="rounded px-3 py-1 text-sm bg-blue-50 dark:bg-blue-900 text-blue-600 dark:text-blue-300">
        {stage ? (STAGE_LABELS[stage] ?? stage) : 'Работи…'}
      </span>
    )
  }

  if (pendingEstimate) {
    return (
      <div className="flex items-center gap-2 text-sm" data-testid="refresh-button">
        <span className="text-yellow-700 dark:text-yellow-300">
          Прогнозна цена: ${pendingEstimate.estimated_cost_usd.toFixed(4)} ({pendingEstimate.total_clusters_to_process} клъстера). Продължи?
        </span>
        <button
          onClick={() => { setPendingEstimate(null); trigger() }}
          className="rounded px-2 py-0.5 bg-blue-600 text-white hover:bg-blue-700 transition-colors"
        >
          Да
        </button>
        <button
          onClick={() => setPendingEstimate(null)}
          className="rounded px-2 py-0.5 bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors"
        >
          Не
        </button>
      </div>
    )
  }

  return (
    <button
      onClick={handleClick}
      disabled={estimating}
      data-testid="refresh-button"
      className="rounded px-3 py-1 text-sm bg-blue-600 text-white hover:bg-blue-700 transition-colors disabled:opacity-50"
    >
      {estimating ? '…' : '↺ Обнови'}
    </button>
  )
}
