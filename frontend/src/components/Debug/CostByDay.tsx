import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../../api/client'

interface CostByDayRow {
  date: string
  calls: number
  cache_hits: number
  cost_usd: number
}

export function CostByDay() {
  const { data, isLoading } = useQuery<CostByDayRow[]>({
    queryKey: ['debug-cost-by-day'],
    queryFn: () => apiFetch('/api/debug/cost-by-day?days=30'),
  })

  return (
    <section data-testid="cost-by-day">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
        Разходи по ден (последните 30 дни)
      </h2>
      {isLoading && <p className="text-sm text-gray-400">Зарежда…</p>}
      {data && data.length === 0 && (
        <p className="text-sm text-gray-400">Няма данни</p>
      )}
      {data && data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
                <th className="pb-1 pr-4">Дата</th>
                <th className="pb-1 pr-4 text-right">Заявки</th>
                <th className="pb-1 pr-4 text-right">Кеш попадения</th>
                <th className="pb-1 text-right">Разход ($)</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={row.date} className="border-b border-gray-100 dark:border-gray-800">
                  <td className="py-1 pr-4 font-mono">{row.date}</td>
                  <td className="py-1 pr-4 text-right">{row.calls}</td>
                  <td className="py-1 pr-4 text-right">{row.cache_hits}</td>
                  <td className="py-1 text-right font-mono">{row.cost_usd.toFixed(6)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
