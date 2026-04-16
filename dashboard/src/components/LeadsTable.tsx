import { useState } from 'react'
import type { Contact } from '../types'
import type { GroupedLead } from '../hooks/useLeads'
import { ConfidenceBadge } from './ConfidenceBadge'
import { OutreachModal } from './OutreachModal'

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color = score >= 0.8 ? 'bg-green-500' : score >= 0.7 ? 'bg-blue-500' : 'bg-gray-300'
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm font-semibold text-gray-700">{score.toFixed(2)}</span>
    </div>
  )
}

interface Props {
  leads: GroupedLead[]
  buyerTypeFilter: string
}

export function LeadsTable({ leads, buyerTypeFilter }: Props) {
  const [modal, setModal] = useState<{ lead: GroupedLead; contact: Contact } | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  if (leads.length === 0) {
    return (
      <div className="text-center py-20 text-gray-400">
        <p className="text-lg">No leads match your filters.</p>
      </div>
    )
  }

  return (
    <>
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
              <th className="px-4 py-3">Company</th>
              <th className="px-4 py-3">Event</th>
              <th className="px-4 py-3">Confidence</th>
              <th className="px-4 py-3">ICP Score</th>
              <th className="px-4 py-3">Revenue</th>
              <th className="px-4 py-3">Contacts</th>
              <th className="px-4 py-3">Rationale</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {leads.map(lead => {
              const contacts = (lead.contacts ?? []).filter(c =>
                buyerTypeFilter ? c.buyer_type === buyerTypeFilter : true
              )
              const isExpanded = expanded === lead.id

              return (
                <>
                  <tr
                    key={lead.id}
                    className="hover:bg-gray-50 cursor-pointer transition-colors"
                    onClick={() => setExpanded(isExpanded ? null : lead.id)}
                  >
                    <td className="px-4 py-3 font-medium text-gray-900">
                      <div className="flex items-center gap-2">
                        <span>{isExpanded ? '▾' : '▸'}</span>
                        <div>
                          <div>{lead.company}</div>
                          {lead.division && (
                            <div className="text-xs text-blue-600 font-normal">{lead.division}</div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {(lead.events ?? [lead.event_source]).map(ev => (
                          <span key={ev} className="inline-block text-xs bg-gray-100 text-gray-600 rounded px-1.5 py-0.5 truncate max-w-[140px]" title={ev}>
                            {ev.replace(' 2025', '').replace(' Expo', '').replace(' Show', '')}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <ConfidenceBadge value={lead.discovery_confidence} />
                    </td>
                    <td className="px-4 py-3">
                      <ScoreBar score={lead.icp_score} />
                    </td>
                    <td className="px-4 py-3 text-gray-500">{lead.revenue_estimate ?? '—'}</td>
                    <td className="px-4 py-3 text-gray-500">{contacts.length}</td>
                    <td className="px-4 py-3 text-gray-400 max-w-[200px] truncate">
                      {lead.qualification_rationale ?? '—'}
                    </td>
                  </tr>

                  {/* Expanded row */}
                  {isExpanded && (
                    <tr key={`${lead.id}-expanded`} className="bg-blue-50/40">
                      <td colSpan={7} className="px-6 py-4">
                        <div className="mb-3 text-sm text-gray-600 leading-relaxed">
                          <span className="font-semibold text-gray-700">Rationale: </span>
                          {lead.qualification_rationale ?? 'No rationale available.'}
                        </div>

                        {/* ICP score breakdown */}
                        <div className="flex gap-6 mb-4 text-xs text-gray-500">
                          <span>Industry fit: <strong className="text-gray-700">{lead.industry_fit ?? '—'}</strong></span>
                          <span>Revenue tier: <strong className="text-gray-700">{lead.revenue_tier ?? '—'}</strong></span>
                          <span>Event conf.: <strong className="text-gray-700">{lead.event_confirmation ?? '—'}</strong></span>
                          <span>Product overlap: <strong className="text-gray-700">{lead.product_overlap ?? '—'}</strong></span>
                        </div>

                        {contacts.length === 0 ? (
                          <p className="text-sm text-gray-400 italic">
                            {lead.icp_score >= 0.7
                              ? 'No contacts found — Serper returned no matching LinkedIn profiles.'
                              : 'Below ICP threshold (0.7) — not targeted for outreach.'}
                          </p>
                        ) : (
                          <div className="flex flex-wrap gap-3">
                            {contacts.map(contact => (
                              <button
                                key={contact.id}
                                onClick={() => setModal({ lead, contact })}
                                className="flex flex-col items-start bg-white border border-gray-200 hover:border-blue-400 rounded-xl px-4 py-3 text-left transition-colors shadow-sm"
                              >
                                <span className={`text-xs font-semibold mb-1 ${
                                  contact.buyer_type === 'technical' ? 'text-purple-600' : 'text-blue-600'
                                }`}>
                                  {contact.buyer_type === 'technical' ? 'Technical Buyer' : 'Business Buyer'}
                                </span>
                                <span className="text-sm font-medium text-gray-800">{contact.name ?? 'Unknown'}</span>
                                <span className="text-xs text-gray-500">{contact.title ?? '—'}</span>
                                <span className="text-xs text-blue-500 mt-1">View outreach →</span>
                              </button>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </>
              )
            })}
          </tbody>
        </table>
      </div>

      {modal && (
        <OutreachModal
          lead={modal.lead}
          contact={modal.contact}
          onClose={() => setModal(null)}
        />
      )}
    </>
  )
}
