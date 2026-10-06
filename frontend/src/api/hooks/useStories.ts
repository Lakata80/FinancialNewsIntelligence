import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../client'

export interface ArticleLink {
  id: number
  title: string
  url: string
  publisher: string | null
  published_at: string
}

export interface StoryOut {
  id: number
  cluster_id: number
  title_bg: string
  summary_bg: string
  tickers: string[]
  event_type: string | null
  is_opinion: boolean
  verification_status: 'pending' | 'verified' | 'partially_supported' | 'removed'
  publisher_count: number
  article_count: number
  first_seen_at: string
  last_seen_at: string
  source_articles: ArticleLink[]
}

export interface Evidence {
  id: number
  article_id: number
  quote_en: string
  publisher: string | null
  published_at: string
  url: string
}

export interface Fact {
  id: number
  fact_order: number
  text_bg: string
  verification_status: string
  evidence: Evidence[]
}

export interface StoryDetail extends StoryOut {
  facts: Fact[]
}

export interface StoryFilters {
  ticker?: string
  hours?: number
  show_opinions?: boolean
  show_hidden?: boolean
}

function buildQuery(filters: StoryFilters): string {
  const p = new URLSearchParams()
  if (filters.ticker) p.set('ticker', filters.ticker)
  if (filters.hours !== undefined) p.set('hours', String(filters.hours))
  if (filters.show_opinions !== undefined) p.set('show_opinions', String(filters.show_opinions))
  if (filters.show_hidden !== undefined) p.set('show_hidden', String(filters.show_hidden))
  const qs = p.toString()
  return qs ? `?${qs}` : ''
}

export function useStories(filters: StoryFilters) {
  return useQuery<StoryOut[]>({
    queryKey: ['stories', filters],
    queryFn: () => apiFetch(`/api/stories${buildQuery(filters)}`),
  })
}

export function useStory(id: number | null) {
  return useQuery<StoryDetail>({
    queryKey: ['story', id],
    queryFn: () => apiFetch(`/api/stories/${id}`),
    enabled: id !== null,
  })
}
