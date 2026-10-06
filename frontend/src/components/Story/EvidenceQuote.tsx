import type { Evidence } from '../../api/hooks/useStories'

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('bg-BG', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

interface Props {
  evidence: Evidence
}

export function EvidenceQuote({ evidence }: Props) {
  return (
    <blockquote
      data-testid="evidence-quote"
      className="mt-1 rounded border-l-2 border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800 px-3 py-2"
    >
      <p className="text-sm italic text-gray-700 dark:text-gray-300 font-mono">
        &ldquo;{evidence.quote_en}&rdquo;
      </p>
      <footer className="mt-1 flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
        {evidence.publisher && <span>{evidence.publisher}</span>}
        <span>·</span>
        <span>{formatDate(evidence.published_at)}</span>
        <span>·</span>
        <a
          href={evidence.url}
          target="_blank"
          rel="noopener noreferrer"
          data-testid="evidence-link"
          className="underline hover:text-blue-600 dark:hover:text-blue-400"
        >
          → Оригинален линк
        </a>
      </footer>
    </blockquote>
  )
}
