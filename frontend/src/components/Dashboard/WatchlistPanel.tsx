import { useWatchlist, type WatchlistItem } from '../../api/hooks/useWatchlist'

interface Props {
  selected: string | null
  onSelect: (id: string | null) => void
}

function Item({ item, selected, onSelect }: { item: WatchlistItem; selected: boolean; onSelect: () => void }) {
  return (
    <button
      onClick={onSelect}
      className={
        `w-full text-left px-2 py-1 rounded text-sm transition-colors ` +
        (selected
          ? 'bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-200 font-semibold'
          : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700')
      }
    >
      {item.label}
    </button>
  )
}

export function WatchlistPanel({ selected, onSelect }: Props) {
  const { data } = useWatchlist()
  const items = data?.items ?? []
  const tickers = items.filter((i) => i.kind === 'ticker')
  const macros = items.filter((i) => i.kind === 'macro')

  return (
    <nav aria-label="Наблюдавани" data-testid="watchlist" className="space-y-1">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 px-2 mb-1">
        Наблюдавани
      </p>
      <Item
        item={{ id: '', label: 'Всички', kind: 'ticker' }}
        selected={selected === null}
        onSelect={() => onSelect(null)}
      />
      {tickers.map((t) => (
        <Item key={t.id} item={t} selected={selected === t.id} onSelect={() => onSelect(t.id)} />
      ))}
      {macros.length > 0 && (
        <hr className="my-1 border-gray-200 dark:border-gray-700" />
      )}
      {macros.map((m) => (
        <Item key={m.id} item={m} selected={selected === m.id} onSelect={() => onSelect(m.id)} />
      ))}
    </nav>
  )
}
