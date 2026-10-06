import { useState } from 'react'
import type { StoryFilters } from '../api/hooks/useStories'
import { FunnelStats } from '../components/Dashboard/FunnelStats'
import { RefreshButton } from '../components/Dashboard/RefreshButton'
import { ShowToggles } from '../components/Dashboard/ShowToggles'
import { TimeFilter } from '../components/Dashboard/TimeFilter'
import { WatchlistPanel } from '../components/Dashboard/WatchlistPanel'
import { AlarmBanner } from '../components/Layout/AlarmBanner'
import { StoryList } from '../components/Story/StoryList'

export function DashboardPage() {
  const [ticker, setTicker] = useState<string | null>(null)
  const [hours, setHours] = useState(24)
  const [showOpinions, setShowOpinions] = useState(false)
  const [showHidden, setShowHidden] = useState(false)

  const filters: StoryFilters = {
    ticker: ticker ?? undefined,
    hours,
    show_opinions: showOpinions,
    show_hidden: showHidden,
  }

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <aside className="w-48 shrink-0 border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3 space-y-4 hidden sm:block">
        <WatchlistPanel selected={ticker} onSelect={setTicker} />
        <TimeFilter hours={hours} onChange={setHours} />
        <ShowToggles
          showOpinions={showOpinions}
          showHidden={showHidden}
          onToggleOpinions={() => setShowOpinions((v) => !v)}
          onToggleHidden={() => setShowHidden((v) => !v)}
        />
      </aside>

      {/* Main content */}
      <div className="flex-1 min-w-0 p-4 space-y-4">
        <AlarmBanner />
        {/* Funnel + refresh bar */}
        <div className="flex items-center justify-between gap-4">
          <FunnelStats ticker={ticker ?? undefined} hours={hours} />
          <RefreshButton />
        </div>

        <StoryList filters={filters} />
      </div>
    </div>
  )
}
