import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../client'

export interface FunnelOut {
  articles: number
  clusters: number
  relevant: number
}

export function useFunnel(ticker?: string, hours?: number) {
  const p = new URLSearchParams()
  if (ticker) p.set('ticker', ticker)
  if (hours !== undefined) p.set('hours', String(hours))
  const qs = p.toString()
  return useQuery<FunnelOut>({
    queryKey: ['funnel', ticker, hours],
    queryFn: () => apiFetch(`/api/funnel${qs ? `?${qs}` : ''}`),
  })
}
