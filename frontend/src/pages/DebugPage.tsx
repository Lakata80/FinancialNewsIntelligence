import { AlarmBanner } from '../components/Layout/AlarmBanner'
import { CostByDay } from '../components/Debug/CostByDay'
import { CostsSummary } from '../components/Debug/CostsSummary'
import { FetchRunsTable } from '../components/Debug/FetchRunsTable'
import { QuarantineTable } from '../components/Debug/QuarantineTable'
import { VerificationLogTable } from '../components/Debug/VerificationLogTable'

export function DebugPage() {
  return (
    <div className="p-4 space-y-8 max-w-5xl mx-auto">
      <AlarmBanner />
      <FetchRunsTable />
      <QuarantineTable />
      <VerificationLogTable />
      <CostsSummary />
      <CostByDay />
    </div>
  )
}
