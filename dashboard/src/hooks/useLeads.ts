import { useState, useEffect, useMemo } from 'react'
import type { Lead } from '../types'
import { apiUrl } from '../api'

export interface GroupedLead extends Omit<Lead, 'event_source'> {
  events: string[]           // all events this company appeared in
  event_source: string       // best event (highest score)
}

/** Merge leads with the same company name into a single row. */
function groupByCompany(leads: Lead[]): GroupedLead[] {
  const map = new Map<string, Lead[]>()
  for (const lead of leads) {
    const key = lead.company.trim().toLowerCase()
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(lead)
  }

  return Array.from(map.values()).map(group => {
    // Use the instance with the highest ICP score as the primary
    const primary = group.reduce((a, b) => (a.icp_score >= b.icp_score ? a : b))

    // Deduplicate contacts by linkedin_url across all event instances
    const seenUrls = new Set<string>()
    const allContacts = group.flatMap(l => l.contacts ?? []).filter(c => {
      if (!c.linkedin_url) return true
      if (seenUrls.has(c.linkedin_url)) return false
      seenUrls.add(c.linkedin_url)
      return true
    })

    return {
      ...primary,
      events: [...new Set(group.map(l => l.event_source).filter(Boolean))],
      contacts: allContacts,
    }
  })
}

export function useLeads() {
  const [raw, setRaw] = useState<Lead[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(apiUrl('/leads'))
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data: Lead[]) => {
        setRaw(data)
        setLoading(false)
      })
      .catch(e => {
        setError(e.message)
        setLoading(false)
      })
  }, [])

  const leads = useMemo(() => groupByCompany(raw), [raw])

  return { leads, loading, error }
}
