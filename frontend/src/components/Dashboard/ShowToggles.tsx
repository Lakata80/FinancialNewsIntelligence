interface Props {
  showOpinions: boolean
  showHidden: boolean
  onToggleOpinions: () => void
  onToggleHidden: () => void
}

export function ShowToggles({ showOpinions, showHidden, onToggleOpinions, onToggleHidden }: Props) {
  return (
    <div data-testid="toggles" className="space-y-1 px-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
        Показване
      </p>
      <label className="flex items-center gap-2 text-sm cursor-pointer">
        <input
          type="checkbox"
          checked={showOpinions}
          onChange={onToggleOpinions}
          className="rounded"
          data-testid="toggle-opinions"
        />
        <span className="text-gray-700 dark:text-gray-300">Мнения</span>
      </label>
      <label className="flex items-center gap-2 text-sm cursor-pointer">
        <input
          type="checkbox"
          checked={showHidden}
          onChange={onToggleHidden}
          className="rounded"
          data-testid="toggle-hidden"
        />
        <span className="text-gray-700 dark:text-gray-300">Скрити (промо / странични)</span>
      </label>
    </div>
  )
}
