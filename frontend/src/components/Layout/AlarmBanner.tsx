import { useState } from 'react'
import type { Alarm } from '../../hooks/useAlarms'
import { useAlarms } from '../../hooks/useAlarms'

function Banner({ alarm, onDismiss }: { alarm: Alarm; onDismiss: () => void }) {
  const isRed = alarm.type === 'budget_exhausted'
  const colorClass = isRed
    ? 'bg-red-100 dark:bg-red-950 border-red-400 text-red-800 dark:text-red-200'
    : 'bg-yellow-100 dark:bg-yellow-950 border-yellow-400 text-yellow-800 dark:text-yellow-200'
  return (
    <div className={`flex items-center justify-between gap-2 px-3 py-1.5 border rounded text-sm ${colorClass}`}>
      <span>{alarm.message}</span>
      <button
        onClick={onDismiss}
        aria-label="Затвори аларма"
        className="opacity-60 hover:opacity-100 ml-4 shrink-0"
      >
        ✕
      </button>
    </div>
  )
}

export function AlarmBanner() {
  const alarms = useAlarms()
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  const visible = alarms.filter((a) => !dismissed.has(`${a.type}:${a.message}`))
  if (visible.length === 0) return null

  function dismiss(alarm: Alarm) {
    setDismissed((prev) => new Set([...prev, `${alarm.type}:${alarm.message}`]))
  }

  return (
    <div className="space-y-1 mb-3" data-testid="alarm-banner">
      {visible.map((alarm) => (
        <Banner
          key={`${alarm.type}:${alarm.message}`}
          alarm={alarm}
          onDismiss={() => dismiss(alarm)}
        />
      ))}
    </div>
  )
}
