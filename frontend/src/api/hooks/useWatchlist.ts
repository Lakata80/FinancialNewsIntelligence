import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../client'

export interface WatchlistItem {
  id: string
  label: string
  kind: 'ticker' | 'macro'
}

export interface WatchlistOut {
  items: WatchlistItem[]
}

export function useWatchlist() {
  return useQuery<WatchlistOut>({
    queryKey: ['watchlist'],
    queryFn: () => apiFetch('/api/watchlist'),
    staleTime: 5 * 60 * 1000,
  })
}
