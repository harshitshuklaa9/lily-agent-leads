interface Props {
  events: string[]
  selectedEvent: string
  onEventChange: (v: string) => void
  minScore: number
  onMinScoreChange: (v: number) => void
  buyerType: string
  onBuyerTypeChange: (v: string) => void
}

export function FilterBar({
  events, selectedEvent, onEventChange,
  minScore, onMinScoreChange,
  buyerType, onBuyerTypeChange,
}: Props) {
  return (
    <div className="flex flex-wrap gap-4 items-end bg-white border border-gray-200 rounded-xl p-4 mb-6 shadow-sm">
      {/* Event filter */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Event</label>
        <select
          value={selectedEvent}
          onChange={e => onEventChange(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All Events</option>
          {events.map(e => <option key={e} value={e}>{e}</option>)}
        </select>
      </div>

      {/* Score slider */}
      <div className="flex flex-col gap-1 min-w-[180px]">
        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Min ICP Score: <span className="text-blue-600">{minScore.toFixed(1)}</span>
        </label>
        <input
          type="range" min={0} max={1} step={0.1}
          value={minScore}
          onChange={e => onMinScoreChange(parseFloat(e.target.value))}
          className="accent-blue-600"
        />
      </div>

      {/* Buyer type */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Buyer Type</label>
        <select
          value={buyerType}
          onChange={e => onBuyerTypeChange(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All</option>
          <option value="technical">Technical</option>
          <option value="business">Business</option>
        </select>
      </div>
    </div>
  )
}
