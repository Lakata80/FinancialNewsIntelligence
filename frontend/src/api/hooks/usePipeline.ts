import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { apiFetch } from '../client'

interface PipelineRunOut {
  run_id: string
}

interface PipelineStatusOut {
  run_id: string
  stage: string
  done: boolean
  error: string | null
}

export function usePipelineRun() {
  const queryClient = useQueryClient()
  const [runId, setRunId] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: () => apiFetch<PipelineRunOut>('/api/pipeline/run', { method: 'POST' }),
    onSuccess: (data) => {
      setRunId(data.run_id)
    },
  })

  const statusQuery = useQuery<PipelineStatusOut>({
    queryKey: ['pipeline-status', runId],
    queryFn: () => apiFetch(`/api/pipeline/status/${runId}`),
    enabled: runId !== null,
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data || data.done || data.error) return false
      return 2000
    },
    refetchOnWindowFocus: false,
  })

  const reset = () => {
    setRunId(null)
    if (statusQuery.data?.done) {
      queryClient.invalidateQueries({ queryKey: ['stories'] })
      queryClient.invalidateQueries({ queryKey: ['funnel'] })
    }
  }

  return {
    trigger: mutation.mutate,
    isRunning: mutation.isPending || (!!runId && !statusQuery.data?.done && !statusQuery.data?.error),
    stage: statusQuery.data?.stage ?? null,
    done: statusQuery.data?.done ?? false,
    error: statusQuery.data?.error ?? null,
    reset,
  }
}
