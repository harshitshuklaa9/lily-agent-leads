import type { DiscoveryConfidence } from '../types'

const config: Record<DiscoveryConfidence, { label: string; classes: string }> = {
  confirmed_exhibitor: { label: 'Confirmed', classes: 'bg-green-100 text-green-800 border border-green-200' },
  inferred_attendee:   { label: 'Inferred',  classes: 'bg-yellow-100 text-yellow-800 border border-yellow-200' },
  low_confidence:      { label: 'Low Conf.', classes: 'bg-red-100 text-red-700 border border-red-200' },
}

export function ConfidenceBadge({ value }: { value: DiscoveryConfidence }) {
  const { label, classes } = config[value] ?? config.low_confidence
  return (
    <span className={`inline-block text-xs font-medium px-2 py-0.5 rounded-full ${classes}`}>
      {label}
    </span>
  )
}
