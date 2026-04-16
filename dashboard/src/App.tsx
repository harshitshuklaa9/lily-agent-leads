import { useMemo, useState } from 'react'
import { useLeads } from './hooks/useLeads'
import { FilterBar } from './components/FilterBar'
import { LeadsTable } from './components/LeadsTable'

export default function App() {
  const { leads, loading, error } = useLeads()
  const [selectedEvent, setSelectedEvent] = useState('')
  const [minScore, setMinScore] = useState(0.7)
  const [buyerType, setBuyerType] = useState('')

  const events = useMemo(
    () => [...new Set(leads.flatMap(l => l.events ?? []).filter(Boolean))].sort(),
    [leads]
  )

  const filtered = useMemo(() => leads.filter(l => {
    if (selectedEvent && !(l.events ?? []).includes(selectedEvent)) return false
    if (l.icp_score < minScore) return false
    return true
  }), [leads, selectedEvent, minScore])

  const qualified = filtered.filter(l => l.icp_score >= 0.7).length

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-8 py-5">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Lily Agent - Leads</h1>
            <p className="text-sm text-gray-400 mt-0.5">DuPont Tedlar · Graphics & Signage Pipeline</p>
            <p className="text-xs text-gray-300 mt-1">🔄 Agent runs automatically every 2 days</p>
          </div>

          <div className="flex gap-6 text-center">
            <div>
              <p className="text-2xl font-bold text-gray-900">{leads.length}</p>
              <p className="text-xs text-gray-400">Total Leads</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-green-600">{qualified}</p>
              <p className="text-xs text-gray-400">Qualified (≥0.7)</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-blue-600">{events.length}</p>
              <p className="text-xs text-gray-400">Events</p>
            </div>
          </div>
        </div>
      </div>

      {/* Main */}
      <div className="max-w-7xl mx-auto px-8 py-6">
        <FilterBar
          events={events}
          selectedEvent={selectedEvent}
          onEventChange={setSelectedEvent}
          minScore={minScore}
          onMinScoreChange={setMinScore}
          buyerType={buyerType}
          onBuyerTypeChange={setBuyerType}
        />

        {loading && (
          <div className="text-center py-20 text-gray-400">
            <div className="inline-block w-6 h-6 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mb-3" />
            <p>Loading leads...</p>
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-5 py-4 text-sm">
            Failed to load leads: {error}. Is the API server running?
          </div>
        )}

        {!loading && !error && (
          <>
            <p className="text-xs text-gray-400 mb-3">
              Showing {filtered.length} of {leads.length} leads
            </p>
            <LeadsTable leads={filtered} buyerTypeFilter={buyerType} />
          </>
        )}
      </div>

    </div>
  )
}
