import { useState } from 'react'
import type { StoryOut } from '../../api/hooks/useStories'
import { StoryBadges } from './StoryBadges'
import { StoryDetail } from './StoryDetail'

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const h = Math.floor(diff / 3_600_000)
  if (h < 1) return 'преди по-малко от час'
  if (h < 24) return `преди ${h} ч.`
  const d = Math.floor(h / 24)
  return `преди ${d} д.`
}

interface Props {
  story: StoryOut
}

export function StoryCard({ story }: Props) {
  const [expanded, setExpanded] = useState(false)
  const isPending = story.verification_status === 'pending'

  return (
    <article data-testid="story-card" className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
      <div className="px-4 py-3">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            {isPending ? (
              <h2 className="text-base font-medium text-gray-500 dark:text-gray-400">
                [Непроверено]
              </h2>
            ) : (
              <h2 className="text-base font-medium text-gray-900 dark:text-gray-100 leading-snug">
                {story.title_bg}
              </h2>
            )}
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
              <StoryBadges story={story} />
              <span className="text-xs text-gray-400 dark:text-gray-500">
                {timeAgo(story.last_seen_at)}
              </span>
            </div>
          </div>
          {isPending ? (
            <div className="text-sm text-gray-500 dark:text-gray-400 space-y-1 mt-1">
              {story.source_articles.slice(0, 3).map((a) => (
                <a
                  key={a.id}
                  href={a.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block underline hover:text-blue-600 dark:hover:text-blue-400 text-xs"
                >
                  {a.title}
                </a>
              ))}
            </div>
          ) : (
            <button
              aria-expanded={expanded}
              aria-label={expanded ? 'Свий историята' : 'Разгъни историята'}
              onClick={() => setExpanded((e) => !e)}
              className="shrink-0 rounded px-2 py-1 text-xs text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
            >
              {expanded ? '▲ Свий' : '▼ Разгъни'}
            </button>
          )}
        </div>

        {!isPending && !expanded && (
          <p className="mt-2 text-sm text-gray-600 dark:text-gray-400 line-clamp-2">
            {story.summary_bg}
          </p>
        )}
      </div>

      {expanded && !isPending && <StoryDetail storyId={story.id} />}
    </article>
  )
}
