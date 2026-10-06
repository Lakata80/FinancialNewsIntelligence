import { useFetchRuns } from '../../api/hooks/useDebug'

const STATUS_STYLE: Record<string, string> = {
  completed: 'text-green-600 dark:text-green-400',
  ok: 'text-green-600 dark:text-green-400',
  failed: 'text-red-600 dark:text-red-400',
  error: 'text-red-600 dark:text-red-400',
  stale: 'text-yellow-600 dark:text-yellow-400',
  running: 'text-blue-600 dark:text-blue-400',
  never_run: 'text-gray-400',
}

function formatAgo(iso: string | null) {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const min = Math.floor(diff / 60_000)
  if (min < 60) return `преди ${min} мин`
  const h = Math.floor(min / 60)
  if (h < 48) return `преди ${h} ч`
  return `преди ${Math.floor(h / 24)} д`
}

export function FetchRunsTable() {
  const { data, isLoading } = useFetchRuns()

  return (
    <section>
      <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
        Последни заявки
      </h2>
      <div data-testid="fetch-runs-table" className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
              <th className="pb-1 pr-4 font-medium">Източник</th>
              <th className="pb-1 pr-4 font-medium">Статус</th>
              <th className="pb-1 pr-4 font-medium">Нови</th>
              <th className="pb-1 pr-4 font-medium">Последна статия</th>
              <th className="pb-1 font-medium">Грешка</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={5} className="py-3 text-gray-400 text-center">Зарежда…</td>
              </tr>
            )}
            {data?.map((run) => (
              <tr key={run.source_name} className="border-b border-gray-100 dark:border-gray-800">
                <td className="py-1.5 pr-4 font-mono text-xs">{run.source_name}</td>
                <td className={`py-1.5 pr-4 ${STATUS_STYLE[run.status] ?? ''}`}>{run.status}</td>
                <td className="py-1.5 pr-4">{run.items_new}</td>
                <td className="py-1.5 pr-4 text-gray-500 dark:text-gray-400">{formatAgo(run.newest_item_at)}</td>
                <td className="py-1.5 text-red-500 dark:text-red-400 text-xs">{run.error ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
