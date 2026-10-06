import { useStory } from '../../api/hooks/useStories'
import { FactItem } from './FactItem'

interface Props {
  storyId: number
}

export function StoryDetail({ storyId }: Props) {
  const { data, isLoading, isError } = useStory(storyId)

  if (isLoading) return <p className="text-sm text-gray-400 px-4 py-2">Зарежда…</p>
  if (isError || !data) return <p className="text-sm text-red-500 px-4 py-2">Грешка при зареждане.</p>

  const hasFacts = data.facts.length > 0

  return (
    <div data-testid="story-detail" className="border-t border-gray-100 dark:border-gray-700 px-4 py-3 space-y-3">
      {hasFacts && (
        <section aria-label="Факти">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
            Факти
          </h3>
          <ul className="space-y-3">
            {data.facts.map((f) => (
              <FactItem key={f.id} fact={f} />
            ))}
          </ul>
        </section>
      )}

      {data.is_opinion && (
        <section aria-label="Мнения">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
            Мнения
          </h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 italic">
            Мненията са атрибутирани в оригиналните факти по-горе.
          </p>
        </section>
      )}

      {!hasFacts && (
        <p className="text-sm text-gray-500 dark:text-gray-400 italic">Няма верифицирани факти.</p>
      )}
    </div>
  )
}
