import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../api/client'

export interface Alarm {
  type: string
  message: string
  source?: string | null
  stale_hours?: number | null
}

interface HealthOut {
  alarms: Alarm[]
}

export function useAlarms() {
  const { data } = useQuery<HealthOut>({
    queryKey: ['debug-health'],
    queryFn: () => apiFetch('/api/debug/health'),
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
  return data?.alarms ?? []
}
