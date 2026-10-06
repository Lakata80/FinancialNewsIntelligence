import type { StoryFilters } from '../../api/hooks/useStories'
import { useStories } from '../../api/hooks/useStories'
import { StoryCard } from './StoryCard'

interface Props {
  filters: StoryFilters
}

export function StoryList({ filters }: Props) {
  const { data, isLoading, isError } = useStories(filters)

  if (isLoading) {
    return (
      <div data-testid="story-list" className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-24 rounded-lg bg-gray-100 dark:bg-gray-800 animate-pulse" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div data-testid="story-list" className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950 px-4 py-3 text-sm text-red-600 dark:text-red-400">
        Грешка при зареждане на историите.
      </div>
    )
  }

  if (!data || data.length === 0) {
    return (
      <div data-testid="story-list" className="rounded-lg border border-gray-200 dark:border-gray-700 px-4 py-6 text-center text-sm text-gray-500 dark:text-gray-400">
        Няма истории за избрания период.
      </div>
    )
  }

  return (
    <div data-testid="story-list" className="space-y-3">
      {data.map((story) => (
        <StoryCard key={story.id} story={story} />
      ))}
    </div>
  )
}
