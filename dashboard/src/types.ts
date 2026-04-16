export type DiscoveryConfidence = 'confirmed_exhibitor' | 'inferred_attendee' | 'low_confidence'
export type BuyerType = 'technical' | 'business'

export interface Contact {
  id: string
  buyer_type: BuyerType
  name: string | null
  title: string | null
  linkedin_url: string | null
  relevance: string | null
  outreach_subject: string | null
  outreach_body: string | null
}

export interface Lead {
  id: string
  company: string
  division: string | null
  event_source: string
  discovery_confidence: DiscoveryConfidence
  revenue_estimate: string | null
  icp_score: number
  industry_fit: number | null
  revenue_tier: number | null
  event_confirmation: number | null
  product_overlap: number | null
  qualification_rationale: string | null
  contacts: Contact[]
  created_at: string
}
