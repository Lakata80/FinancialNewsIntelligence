import type { StoryOut } from '../../api/hooks/useStories'

const VERIFICATION_BADGE: Record<string, { label: string; className: string }> = {
  verified: {
    label: 'Проверено',
    className: 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300',
  },
  partially_supported: {
    label: 'Частично',
    className: 'bg-yellow-100 dark:bg-yellow-900 text-yellow-700 dark:text-yellow-300',
  },
  pending: {
    label: 'Непроверено',
    className: 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400',
  },
  removed: {
    label: 'Премахнато',
    className: 'bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300',
  },
}

interface Props {
  story: StoryOut
}

export function StoryBadges({ story }: Props) {
  const vb = VERIFICATION_BADGE[story.verification_status] ?? VERIFICATION_BADGE.pending

  return (
    <div className="flex flex-wrap gap-1.5 items-center text-xs">
      <span
        aria-label={`Статус: ${vb.label}`}
        className={`rounded px-1.5 py-0.5 font-medium ${vb.className}`}
      >
        {vb.label}
      </span>
      <span
        aria-label={`${story.publisher_count} уникални издателя`}
        className="rounded px-1.5 py-0.5 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400"
      >
        ■ {story.publisher_count} {story.publisher_count === 1 ? 'източник' : 'източника'}
      </span>
      {story.is_opinion && (
        <span
          aria-label="Мнение"
          className="rounded px-1.5 py-0.5 bg-purple-100 dark:bg-purple-900 text-purple-700 dark:text-purple-300"
        >
          Мнение
        </span>
      )}
      {story.tickers.map((t) => (
        <span
          key={t}
          className="rounded px-1.5 py-0.5 bg-blue-50 dark:bg-blue-900 text-blue-700 dark:text-blue-300 font-mono"
        >
          {t}
        </span>
      ))}
    </div>
  )
}
