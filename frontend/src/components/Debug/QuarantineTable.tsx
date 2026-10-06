import { useConfirmQuarantine, useQuarantine, useReleaseQuarantine } from '../../api/hooks/useDebug'

export function QuarantineTable() {
  const { data, isLoading } = useQuarantine()
  const release = useReleaseQuarantine()
  const confirm = useConfirmQuarantine()

  const count = data?.length ?? 0

  return (
    <section>
      <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
        Карантина {count > 0 && <span className="ml-1 rounded bg-red-100 dark:bg-red-900 text-red-600 dark:text-red-300 px-1 text-xs">{count}</span>}
      </h2>
      <div data-testid="quarantine-table" className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
              <th className="pb-1 pr-4 font-medium">Заглавие</th>
              <th className="pb-1 pr-4 font-medium">Оценка</th>
              <th className="pb-1 pr-4 font-medium">Правила</th>
              <th className="pb-1 font-medium">Действия</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={4} className="py-3 text-gray-400 text-center">Зарежда…</td>
              </tr>
            )}
            {data?.length === 0 && !isLoading && (
              <tr>
                <td colSpan={4} className="py-3 text-gray-400 text-center">Няма карантинирани статии.</td>
              </tr>
            )}
            {data?.map((art) => (
              <tr key={art.id} className="border-b border-gray-100 dark:border-gray-800">
                <td className="py-1.5 pr-4 max-w-xs">
                  <a href={art.url} target="_blank" rel="noopener noreferrer" className="underline hover:text-blue-600 dark:hover:text-blue-400 text-xs line-clamp-2">
                    {art.title}
                  </a>
                </td>
                <td className="py-1.5 pr-4 text-red-600 dark:text-red-400 font-mono text-xs">
                  {art.injection_score.toFixed(2)}
                </td>
                <td className="py-1.5 pr-4 text-xs text-gray-500 dark:text-gray-400">
                  {art.matched_rules.join(', ')}
                </td>
                <td className="py-1.5 flex gap-2">
                  <button
                    onClick={() => release.mutate(art.id)}
                    disabled={release.isPending}
                    className="rounded px-2 py-0.5 text-xs bg-yellow-100 dark:bg-yellow-900 text-yellow-700 dark:text-yellow-300 hover:bg-yellow-200 dark:hover:bg-yellow-800 disabled:opacity-50"
                  >
                    Освободи
                  </button>
                  <button
                    onClick={() => confirm.mutate(art.id)}
                    disabled={confirm.isPending}
                    className="rounded px-2 py-0.5 text-xs bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50"
                  >
                    ✓
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
