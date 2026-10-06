import { useFunnel } from '../../api/hooks/useFunnel'

interface Props {
  ticker?: string
  hours: number
}

export function FunnelStats({ ticker, hours }: Props) {
  const { data } = useFunnel(ticker, hours)

  if (!data) return <span className="text-sm text-gray-400 dark:text-gray-500">—</span>

  return (
    <span data-testid="funnel-stats" className="text-sm text-gray-600 dark:text-gray-400">
      {data.articles} статии → {data.clusters} клъстера → {data.relevant} релевантни
    </span>
  )
}
