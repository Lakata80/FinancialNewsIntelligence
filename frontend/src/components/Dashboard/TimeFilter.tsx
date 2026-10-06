const OPTIONS = [
  { label: '6ч', value: 6 },
  { label: '24ч', value: 24 },
  { label: '7д', value: 168 },
]

interface Props {
  hours: number
  onChange: (hours: number) => void
}

export function TimeFilter({ hours, onChange }: Props) {
  return (
    <fieldset data-testid="time-filter" className="space-y-1">
      <legend className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 px-2 mb-1">
        Времеви прозорец
      </legend>
      <div className="flex gap-1 px-2">
        {OPTIONS.map((opt) => (
          <button
            key={opt.value}
            aria-pressed={hours === opt.value}
            onClick={() => onChange(opt.value)}
            className={
              `flex-1 rounded py-1 text-sm transition-colors ` +
              (hours === opt.value
                ? 'bg-blue-600 text-white font-semibold'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700')
            }
          >
            {opt.label}
          </button>
        ))}
      </div>
    </fieldset>
  )
}
