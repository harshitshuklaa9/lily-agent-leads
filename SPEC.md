# Instalily Lead Gen — DuPont Tedlar Graphics & Signage

## What we're building

An AI agent pipeline that automatically finds qualified leads for DuPont Tedlar's Graphics & Signage sales team. Pipeline runs end to end: finds events → finds companies → scores ICP fit → identifies decision makers → generates personalized outreach → displays in a React dashboard.

## Stack

- Python
- OpenAI API (gpt-4o) for all AI steps
- Playwright for web scraping (primary)
- Serper API for search fallback
- FastAPI (`api.py`) — REST API layer between pipeline and frontend
- React (Vite + TypeScript) for dashboard
- Tailwind CSS for styling
- Supabase (PostgreSQL) as persistence layer — `supabase-py` in backend, `@supabase/supabase-js` in frontend

## Project Structure

```
instalily-lead-gen/
├── agents/
│   ├── __init__.py
│   ├── base_agent.py
│   ├── research_agent.py
│   ├── discovery_agent.py
│   ├── enrichment_agent.py
│   ├── stakeholder_agent.py
│   └── outreach_agent.py
├── dashboard/                  ← React app (Vite + TypeScript)
│   ├── public/
│   ├── src/
│   │   ├── components/
│   │   │   ├── LeadsTable.tsx
│   │   │   ├── LeadRow.tsx
│   │   │   ├── OutreachModal.tsx
│   │   │   ├── FilterBar.tsx
│   │   │   └── ConfidenceBadge.tsx
│   │   ├── hooks/
│   │   │   └── useLeads.ts
│   │   ├── types.ts
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── outputs/                    ← local debug dumps only (not primary persistence)
├── api.py                      ← FastAPI server, queries Supabase
├── db.py                       ← Supabase client + insert/query helpers
├── config.json
├── main.py
└── requirements.txt
```

## Environment Variables

- `OPENAI_API_KEY`
- `SERPER_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY` — used by Python backend (bypasses RLS)
- `VITE_SUPABASE_URL` — exposed to React frontend
- `VITE_SUPABASE_ANON_KEY` — exposed to React frontend (read-only, RLS-scoped)

---

## Supabase Schema

Two tables. Contacts are a child of leads via foreign key.

```sql
-- leads table
create table leads (
  id               uuid primary key default gen_random_uuid(),
  company          text not null,
  event_source     text,
  discovery_confidence text check (discovery_confidence in ('confirmed_exhibitor','inferred_attendee','low_confidence')),
  revenue_estimate text,
  icp_score        numeric(4,3),
  industry_fit     numeric(4,3),
  revenue_tier     numeric(4,3),
  event_confirmation numeric(4,3),
  product_overlap  numeric(4,3),
  qualification_rationale text,
  created_at       timestamptz default now()
);

-- contacts table
create table contacts (
  id               uuid primary key default gen_random_uuid(),
  lead_id          uuid references leads(id) on delete cascade,
  buyer_type       text check (buyer_type in ('technical','business')),
  name             text,
  title            text,
  linkedin_url     text,
  relevance        text,
  outreach_subject text,
  outreach_body    text,
  created_at       timestamptz default now()
);
```

**`db.py` responsibilities:**
- Init `supabase-py` client using `SUPABASE_URL` + `SUPABASE_SERVICE_KEY`
- `upsert_lead(lead: dict)` — insert or update by `(company, event_source)`
- `insert_contacts(contacts: list, lead_id: str)`
- `get_all_leads()` — returns leads joined with contacts for the API

**Frontend** uses `@supabase/supabase-js` with the anon key to query directly, or goes through FastAPI — both patterns supported.

---

## Pipeline Steps

### 1. ResearchAgent
Finds trade events where Tedlar's ICP congregates.

Target events:
- ISA Sign Expo
- PRINTING United
- FESPA
- PDAA
- SGIA

### 2. DiscoveryAgent
Finds companies per event using fallback cascade:

1. **Try 1:** Playwright scrape exhibitor page directly
2. **Try 2:** Serper search `[event] exhibitors site:linkedin.com OR site:businesswire.com`
3. **Try 3:** Serper search `[event] 2025 companies attending graphics signage`
4. **If all fail:** flag event as `low_confidence`, move on

### 3. EnrichmentAgent
Enriches each company and scores ICP fit using these exact weights:

| Signal | Weight | Notes |
|---|---|---|
| Industry fit | 40% | Does their core business involve large-format print, signage, wraps, or protective films? |
| Revenue tier | 25% | <$10M = 0.3, $10-100M = 0.6, $100M+ = 1.0 |
| Event confirmation | 20% | Confirmed exhibitor = 1.0, inferred attendee = 0.5 |
| Product overlap | 15% | Do they use or sell outdoor/durable graphic materials? |

**Final score** = sum of (signal × weight). Surface anything above **0.7** in dashboard.

### 4. StakeholderAgent
Finds 2 decision makers per company:

- **Technical buyer:** VP Product, Director R&D, Head of Materials
- **Business buyer:** VP Operations, Procurement Director, COO

Per contact: name, title, LinkedIn URL, why relevant to Tedlar.

Includes LinkedIn Sales Navigator stub: real API call structure, auth headers, commented expected response — provisioned but not live.

### 5. OutreachAgent
Generates personalized email per contact:

- **Technical buyer angle:** performance, durability, material specs
- **Business buyer angle:** reliability, longevity, cost of replacement
- **Format:** subject line + 3-4 sentence email
- Must reference event, company context, individual role

---

## ICP Definition (config.json)

```json
{
  "icp": {
    "description": "Companies that buy or specify protective overlaminate films for outdoor graphics",
    "ideal_signals": [
      "large-format printing",
      "signage fabrication",
      "vehicle wraps",
      "architectural graphics",
      "fleet graphics"
    ],
    "revenue_minimum": "$10M+",
    "key_value_props": [
      "UV durability 12-20 years",
      "anti-graffiti",
      "non-PFAS",
      "conformable for wraps"
    ]
  }
}
```

---

## Reference Example (calibrate output quality)

**Event:** ISA Sign Expo 2025  
**Company:** Avery Dennison Graphics Solutions — $8B+ revenue, global manufacturer of pressure-sensitive films  
**ICP Score:** 0.91 (industry fit 1.0, revenue 1.0, event confirmation 1.0, product overlap 0.6)

### Technical Buyer Outreach

> **Subject:** Protecting what Avery Dennison prints — a conversation on film durability
>
> Hi Laura, we've followed Avery Dennison's expansion into durable graphic films and think there's a natural conversation to have about how Tedlar's PVF protective layer extends the outdoor lifespan of your existing product line. Several large-format printers using your MPI 1005 series have asked us about top-coat options — would love 20 minutes to compare notes from ISA.

### Business Buyer Outreach

> **Subject:** Supplier conversation — protective film integration for Graphics Solutions
>
> Hi [name], as Avery Dennison scales its durable films portfolio, we're seeing procurement teams evaluate integrated supply options earlier in the product development cycle. DuPont Tedlar works with several tier-1 graphic film manufacturers on exactly this. Would a brief call make sense before Q3 planning?

---

## Output Format — leads.json

```json
{
  "company": "",
  "event_source": "",
  "discovery_confidence": "confirmed_exhibitor | inferred_attendee | low_confidence",
  "revenue_estimate": "",
  "icp_score": 0.0,
  "icp_breakdown": {
    "industry_fit": 0.0,
    "revenue_tier": 0.0,
    "event_confirmation": 0.0,
    "product_overlap": 0.0
  },
  "qualification_rationale": "",
  "contacts": [
    {
      "buyer_type": "technical | business",
      "name": "",
      "title": "",
      "linkedin_url": "",
      "relevance": "",
      "outreach_subject": "",
      "outreach_body": ""
    }
  ]
}
```

---

## Dashboard Requirements (React)

**API layer (`api.py`):**
- FastAPI app with a single `GET /leads` endpoint
- Queries Supabase via `db.py`, returns leads + nested contacts
- CORS enabled for local dev (`localhost:5173`)

**React app (`dashboard/`):**
- **Table view:** Event | Company | ICP Score | Decision Maker | Title | LinkedIn | Outreach preview | Action
- Filter bar: by event name, ICP score threshold (slider), buyer type (technical/business)
- Click row to expand full outreach message in a modal
- Copy to clipboard button per outreach email
- `ConfidenceBadge` component — color-coded: green = confirmed_exhibitor, yellow = inferred_attendee, red = low_confidence
- `useLeads` hook — fetches from `GET /api/leads`, handles loading/error state

---

## Error Handling

- Each agent validates output before passing to next
- Malformed OpenAI responses caught and retried once
- Missing fields get `null` with logged reason, not a crash
- Companies that can't be enriched flagged in dashboard, not dropped
- `api.py` returns 200 with empty array if Supabase has no rows yet — frontend handles gracefully

---

## Build Order

1. `config.json`
2. `agents/base_agent.py`
3. `agents/research_agent.py`
4. `agents/discovery_agent.py`
5. `agents/enrichment_agent.py`
6. `agents/stakeholder_agent.py`
7. `agents/outreach_agent.py`
8. `main.py`
9. `db.py` — Supabase client + helpers (run schema migration in Supabase dashboard first)
10. `api.py` — FastAPI server
11. `dashboard/` — React app (Vite + TypeScript + Tailwind)
