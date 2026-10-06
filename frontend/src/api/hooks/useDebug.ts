import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '../client'

export interface FetchRunOut {
  source_name: string
  source_kind: string
  run_id: number | null
  started_at: string | null
  finished_at: string | null
  status: string
  items_seen: number
  items_new: number
  newest_item_at: string | null
  error: string | null
}

export interface QuarantineOut {
  id: number
  title: string
  url: string
  publisher: string | null
  published_at: string
  injection_score: number
  matched_rules: string[]
  source_name: string
}

export interface VerifLogOut {
  id: number
  story_id: number
  fact_id: number | null
  story_title: string
  fact_text: string | null
  check: string
  details: string | null
  created_at: string
}

export interface PurposeCost {
  purpose: string
  cost_usd: number
}

export interface CostsOut {
  today_usd: number
  today_budget_usd: number
  month_usd: number
  month_budget_usd: number
  by_purpose: PurposeCost[]
}

export function useFetchRuns() {
  return useQuery<FetchRunOut[]>({
    queryKey: ['debug-fetch-runs'],
    queryFn: () => apiFetch('/api/debug/fetch-runs'),
  })
}

export function useQuarantine() {
  return useQuery<QuarantineOut[]>({
    queryKey: ['debug-quarantine'],
    queryFn: () => apiFetch('/api/debug/quarantine'),
  })
}

export function useReleaseQuarantine() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch(`/api/debug/quarantine/${id}/release`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['debug-quarantine'] })
      queryClient.invalidateQueries({ queryKey: ['stories'] })
    },
  })
}

export function useConfirmQuarantine() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch(`/api/debug/quarantine/${id}/confirm`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['debug-quarantine'] })
    },
  })
}

export function useVerificationLog() {
  return useQuery<VerifLogOut[]>({
    queryKey: ['debug-verification-log'],
    queryFn: () => apiFetch('/api/debug/verification-log'),
  })
}

export function useCosts() {
  return useQuery<CostsOut>({
    queryKey: ['debug-costs'],
    queryFn: () => apiFetch('/api/debug/costs'),
  })
}
