import { useCosts } from '../../api/hooks/useDebug'

function BudgetBar({ used, budget }: { used: number; budget: number }) {
  const pct = budget > 0 ? Math.min(100, (used / budget) * 100) : 0
  const color = pct > 80 ? 'bg-red-500' : pct > 50 ? 'bg-yellow-500' : 'bg-blue-500'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded bg-gray-200 dark:bg-gray-700 overflow-hidden">
        <div className={`h-full rounded ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500 dark:text-gray-400 w-8 text-right">{pct.toFixed(0)}%</span>
    </div>
  )
}

export function CostsSummary() {
  const { data, isLoading } = useCosts()

  return (
    <section data-testid="costs-summary">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
        Разходи
      </h2>
      {isLoading && <p className="text-sm text-gray-400">Зарежда…</p>}
      {data && (
        <div className="space-y-2">
          <div>
            <div className="flex justify-between text-xs text-gray-600 dark:text-gray-400 mb-0.5">
              <span>Днес</span>
              <span>${data.today_usd.toFixed(4)} / ${data.today_budget_usd.toFixed(2)}</span>
            </div>
            <BudgetBar used={data.today_usd} budget={data.today_budget_usd} />
          </div>
          <div>
            <div className="flex justify-between text-xs text-gray-600 dark:text-gray-400 mb-0.5">
              <span>Месецът</span>
              <span>${data.month_usd.toFixed(4)} / ${data.month_budget_usd.toFixed(2)}</span>
            </div>
            <BudgetBar used={data.month_usd} budget={data.month_budget_usd} />
          </div>
          {data.by_purpose.length > 0 && (
            <p className="text-xs text-gray-500 dark:text-gray-400">
              По цел: {data.by_purpose.map((p) => `${p.purpose} $${p.cost_usd.toFixed(4)}`).join(' · ')}
            </p>
          )}
        </div>
      )}
    </section>
  )
}
