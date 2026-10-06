import { usePipelineRun } from '../../api/hooks/usePipeline'

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

  return (
    <button
      onClick={() => trigger()}
      data-testid="refresh-button"
      className="rounded px-3 py-1 text-sm bg-blue-600 text-white hover:bg-blue-700 transition-colors"
    >
      ↺ Обнови
    </button>
  )
}
