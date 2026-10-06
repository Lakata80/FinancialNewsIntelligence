import { useVerificationLog } from '../../api/hooks/useDebug'

export function VerificationLogTable() {
  const { data, isLoading } = useVerificationLog()

  return (
    <section>
      <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
        Отхвърлени факти
      </h2>
      <div data-testid="verification-log-table" className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
              <th className="pb-1 pr-4 font-medium">История</th>
              <th className="pb-1 pr-4 font-medium">Факт</th>
              <th className="pb-1 pr-4 font-medium">Проверка</th>
              <th className="pb-1 font-medium">Причина</th>
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
                <td colSpan={4} className="py-3 text-gray-400 text-center">Няма отхвърлени факти.</td>
              </tr>
            )}
            {data?.map((log) => (
              <tr key={log.id} className="border-b border-gray-100 dark:border-gray-800">
                <td className="py-1.5 pr-4 text-xs text-gray-700 dark:text-gray-300 max-w-xs truncate">
                  {log.story_title}
                </td>
                <td className="py-1.5 pr-4 text-xs text-gray-600 dark:text-gray-400 max-w-xs truncate">
                  {log.fact_text ?? '—'}
                </td>
                <td className="py-1.5 pr-4 text-xs font-mono text-gray-500 dark:text-gray-400">
                  {log.check}
                </td>
                <td className="py-1.5 text-xs text-red-600 dark:text-red-400">
                  {log.details ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
