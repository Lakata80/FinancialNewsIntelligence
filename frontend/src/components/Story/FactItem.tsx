import type { Fact } from '../../api/hooks/useStories'
import { EvidenceQuote } from './EvidenceQuote'

interface Props {
  fact: Fact
}

export function FactItem({ fact }: Props) {
  return (
    <li data-testid="fact-item" className="space-y-1">
      <p className="text-sm text-gray-800 dark:text-gray-200">• {fact.text_bg}</p>
      {fact.evidence.map((e) => (
        <EvidenceQuote key={e.id} evidence={e} />
      ))}
    </li>
  )
}
