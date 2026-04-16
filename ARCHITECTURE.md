# Lily Agent — Lead Generation Pipeline
### Full Architecture & Technical Reference

---

## 1. The Problem

**DuPont Tedlar** sells PVF (polyvinyl fluoride) protective overlaminate films used by companies in the graphics, signage, and vehicle wrap industry. Their sales team needed a list of qualified prospects — specifically manufacturers, distributors, and large-format printers who actively buy or specify protective overlaminate films.

The traditional approach (manual research, buying lead lists) is slow, generic, and expensive. The goal was to build an **automated AI pipeline** that:

1. Finds the right industry trade shows
2. Extracts real exhibitor companies from those shows
3. Scores each company against a strict ICP (Ideal Customer Profile)
4. Finds the right contacts at qualified companies (technical buyer + business buyer)
5. Writes personalised outreach emails for each contact
6. Displays everything in a clean dashboard for the sales team

**Key constraint:** The pipeline had to find companies who are *actively showing up* at relevant trade shows — a strong signal that they are invested in the industry and worth reaching out to.

---

## 2. The Solution

A 5-agent AI pipeline built in Python, backed by Supabase, exposed via a FastAPI REST API, and visualised in a React dashboard.

Each agent does one job and passes its output to the next. The pipeline is **idempotent** — it checks the database before doing any work, so it can be re-run on a schedule at almost zero cost (only processing new data).

**Results from first run:**
| Company | ICP Score |
|---|---|
| Avery Dennison | 1.000 |
| ORAFOL | 1.000 |
| 3M | 0.970 |
| Mimaki | 0.955 |
| Roland DG | 0.885 |
| Arlon | 0.825 |
| Drytac | 0.795 |
| General Formulations | 0.715 |
| Nobelus | 0.700 |
| Lintec | 0.700 |

---

## 3. Full System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     PIPELINE (Railway)                   │
│                                                         │
│  config.json                                            │
│       │                                                 │
│       ▼                                                 │
│  ┌─────────────┐   events    ┌──────────────┐           │
│  │ResearchAgent│────────────▶│DiscoveryAgent│           │
│  │  (GPT-4o-   │            │  (Playwright  │           │
│  │   mini)     │            │  + GPT-4o-   │           │
│  └─────────────┘            │   mini)      │           │
│                             └──────┬───────┘           │
│                                    │ companies          │
│                                    ▼                    │
│                          ┌──────────────────┐           │
│                          │ EnrichmentAgent  │           │
│                          │   (GPT-4o)       │           │
│                          └────────┬─────────┘           │
│                                   │ scored leads        │
│                                   ▼                     │
│                          ┌──────────────────┐           │
│                          │StakeholderAgent  │           │
│                          │  (Serper API +   │           │
│                          │  GPT-4o-mini)    │           │
│                          └────────┬─────────┘           │
│                                   │ contacts            │
│                                   ▼                     │
│                              Supabase DB                │
└─────────────────────────────────────────────────────────┘
           │ reads/writes at every step
           ▼
    ┌─────────────┐        ┌──────────────────────────────────┐
    │  Supabase   │◀──────▶│       FastAPI (Railway)          │
    │ PostgreSQL  │        │  GET    /leads                   │
    │             │        │  POST   /contacts/:id/outreach   │
    │  tables:    │        │  PATCH  /contacts/:id/outreach   │
    │  - events   │        │  POST   /pipeline/run            │
    │  - leads    │        │  GET    /pipeline/status         │
    │  - contacts │        │  GET    /integrations            │
    │  - settings │        │  POST   /integrations            │
    └─────────────┘        │  DELETE /integrations/:provider  │
                           └────────────────┬─────────────────┘
                                            │ CORS
                                            ▼
                              ┌─────────────────────────┐
                              │    React Dashboard      │
                              │  lilyagent.vercel.app   │
                              │                         │
                              │ • Lead table            │
                              │ • ICP score filter      │
                              │ • Contact modal         │
                              │ • Editable outreach     │
                              │   email + Gmail send    │
                              │ • Admin route (hidden)  │
                              └─────────────────────────┘
```

---

## 4. Infrastructure

| Component | Platform | URL |
|---|---|---|
| React Dashboard | Vercel (free) | `https://lilyagent.vercel.app` |
| FastAPI + Pipeline | Railway (~$1-2/mo) | `https://web-production-be2c1.up.railway.app` |
| PostgreSQL Database | Supabase (free) | `https://cmcvvysraogmwurkhowf.supabase.co` |
| Source Code | GitHub | `https://github.com/harshitshuklaa9/lily-agent-leads` |

**Docker base image:** `mcr.microsoft.com/playwright/python:v1.44.0-jammy`
- Python 3.10 + pip
- Chromium + all system dependencies pre-installed
- Runs on Railway via `start.sh` → `uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}`

**Pipeline cadence:** Designed to run automatically every 2 days via cron. Smart mode ensures only new data is processed — existing leads are never re-scored unless stale.

---

## 5. Configuration (`config.json`)

Everything about the seller, ICP, and target industry lives in `config.json`. **No agent code changes if you want to run this for a different industry — only `config.json` changes.**

### Key sections:

**`seller`** — Who is selling what:
```json
{
  "company": "DuPont Tedlar",
  "product": "Tedlar PVF protective overlaminate films",
  "value_props": ["UV durability 12-20 years", "anti-graffiti", "non-PFAS", ...]
}
```

**`icp`** — Who we want to find:
```json
{
  "description": "Companies that manufacture or apply protective overlaminate films",
  "ideal_signals": ["large-format printing", "signage fabrication", "vehicle wraps", ...],
  "revenue_minimum_usd": 10000000,
  "icp_score_threshold": 0.7
}
```

**`scoring_weights`** — How ICP score is calculated (must sum to 1.0):
```json
{
  "industry_fit":       0.40,
  "revenue_tier":       0.25,
  "event_confirmation": 0.20,
  "product_overlap":    0.15
}
```

**`models`** — Which GPT model each agent uses:
```json
{
  "research":    "gpt-4o-mini",
  "discovery":   "gpt-4o-mini",
  "enrichment":  "gpt-4o",
  "stakeholder": "gpt-4o-mini",
  "outreach":    "gpt-4o"
}
```

**`freshness`** — How long DB data is considered valid before re-running:
```json
{
  "events_max_age_hours":   168,   // 7 days
  "leads_max_age_hours":    720,   // 30 days
  "contacts_max_age_hours": 336    // 14 days
}
```

---

## 6. The Five Agents

### Agent 1: ResearchAgent (`agents/research_agent.py`)
**Model:** GPT-4o-mini
**Input:** config.json (seed events, industry description)
**Output:** List of relevant trade shows with exhibitor page URLs

Uses GPT to research which trade shows are relevant to the seller's industry, starting from seed events in config. Specifically instructs the model to find **MapYourShow gallery URLs** (`mapyourshow.com/8_0/explore/exhibitor-gallery.cfm`) — the public exhibitor directories used by ISA, PRINTING United, SEMA, and most major US trade shows.

**Output shape:**
```json
{
  "name": "ISA International Sign Expo 2026",
  "url": "https://isasignexpo2026.mapyourshow.com",
  "exhibitor_page": "https://isasignexpo2026.mapyourshow.com/8_0/explore/exhibitor-gallery.cfm?featured=false",
  "location": "Las Vegas, NV",
  "date": "April 2026",
  "relevance": "Primary signage industry show..."
}
```

---

### Agent 2: DiscoveryAgent (`agents/discovery_agent.py`)
**Model:** GPT-4o-mini
**Tools:** Playwright (headless Chromium), Serper API
**Input:** List of events from ResearchAgent
**Output:** List of companies with discovery confidence scores

This is the most complex agent. It browses exhibitor pages to extract company names.

**Discovery strategy (in order):**
1. **Try the MapYourShow gallery URL** — loads the page, scrolls to load all exhibitors (up to 8 scroll attempts), extracts all company names from the DOM
2. **Search for MapYourShow URL via Serper** — if not known, searches `{event} mapyourshow exhibitors` to find the gallery URL
3. **Serper fallback** — if MapYourShow fails, uses Serper to search for exhibitor lists on LinkedIn/BusinessWire
4. **ICP-aware Serper queries** — uses config verticals/buyer_keywords to find companies matching the ICP

**MapYourShow insight:** ISA Sign Expo, PRINTING United, and SEMA all use MapYourShow as their public exhibitor directory. The gallery URL pattern is:
`https://{eventslug}{year}.mapyourshow.com/8_0/explore/exhibitor-gallery.cfm?featured=false`

**Output shape per company:**
```json
{
  "name": "Avery Dennison",
  "event_source": "ISA International Sign Expo 2026",
  "discovery_confidence": 0.95,
  "source_url": "https://isasignexpo2026.mapyourshow.com/..."
}
```

---

### Agent 3: EnrichmentAgent (`agents/enrichment_agent.py`)
**Model:** GPT-4o
**Tools:** Serper API (web research)
**Input:** List of discovered companies
**Output:** Fully scored leads with ICP breakdown

For each company, uses Serper to find real data about them (revenue, products, industry), then uses GPT-4o to score them against the ICP.

**ICP Score formula:**
```
icp_score = (industry_fit × 0.40)
           + (revenue_tier × 0.25)
           + (event_confirmation × 0.20)
           + (product_overlap × 0.15)
```

**Revenue tiers:**
- Under $10M → 0.3
- $10M–$100M → 0.6
- Over $100M → 1.0
- Unknown → 0.3 (default, never 0.0)

**Event confirmation scores:**
- Confirmed exhibitor → 1.0
- Inferred attendee → 0.5
- Low confidence → 0.0

Runs with 5 parallel workers (`enrichment_workers: 5` in config).

**Output shape:**
```json
{
  "company": "Avery Dennison",
  "icp_score": 1.0,
  "icp_breakdown": {
    "industry_fit": 1.0,
    "revenue_tier": 1.0,
    "event_confirmation": 1.0,
    "product_overlap": 1.0
  },
  "qualification_rationale": "Global graphic film manufacturer, $8B+ revenue...",
  "revenue_estimate": "$8B+"
}
```

---

### Agent 4: StakeholderAgent (`agents/stakeholder_agent.py`)
**Model:** GPT-4o-mini
**Tools:** Serper API (Google → LinkedIn search)
**Input:** Qualified leads (ICP score ≥ 0.7)
**Output:** Same leads with contacts array added

For each qualified company, searches LinkedIn for two specific buyer personas:
- **Technical Buyer** — VP Product, Director R&D, Head of Materials, VP Engineering, Director Product Development
- **Business Buyer** — VP Operations, Procurement Director, COO, Director of Sourcing, VP Supply Chain

Uses Serper to search `site:linkedin.com/in {company} {title keywords}`, then GPT-4o-mini validates each candidate — verifying they currently work at the target company and hold a relevant title.

**Provider routing:** If an integration key is set in Railway env vars, the agent uses that provider instead of the Serper fallback:
1. `LINKEDIN_SALES_NAV_TOKEN` → LinkedIn Sales Navigator API
2. `CLAY_API_KEY` → Clay people search
3. `APOLLO_API_KEY` → Apollo.io
4. No key → Serper/Google scraper (default)

Runs with 3 parallel workers (`stakeholder_workers: 3` in config).

**Output shape per contact:**
```json
{
  "buyer_type": "technical",
  "name": "Jane Smith",
  "title": "VP Product Development",
  "linkedin_url": "https://linkedin.com/in/jane-smith-avery",
  "relevance": "Oversees film product line including overlaminates"
}
```

---

### Agent 5: OutreachAgent (`agents/outreach_agent.py`)
**Model:** GPT-4o
**Input:** Contact + lead context + seller value props
**Output:** Personalised subject line + email body

**Not run in the pipeline.** Outreach emails are generated **on-demand** when the sales rep clicks "Generate Outreach Email" in the dashboard. This avoids generating emails for contacts that are never used.

Triggered via: `POST /contacts/{contact_id}/outreach`

Uses GPT-4o to write a personalised cold outreach email referencing:
- The contact's specific role and company
- The event where the company was found
- Relevant DuPont Tedlar value props for their use case

Once generated, the email is **editable** in the dashboard — the rep can tweak subject and body, which auto-saves via `PATCH /contacts/{id}/outreach`.

---

## 7. Database Schema (Supabase)

### `events` table
| Column | Type | Description |
|---|---|---|
| id | uuid | Primary key |
| name | text | Event name |
| url | text | Event homepage |
| exhibitor_page | text | MapYourShow gallery URL |
| location | text | City, State |
| date_info | text | Date string |
| relevance | text | Why this event is relevant |
| discovered_at | timestamptz | When pipeline found it |

### `leads` table
| Column | Type | Description |
|---|---|---|
| id | uuid | Primary key |
| company | text | Company name |
| division | text | Division/business unit (if applicable) |
| event_source | text | Which trade show they were found at |
| icp_score | float | 0.0–1.0 composite score |
| industry_fit | float | 0.0–1.0 |
| revenue_tier | float | 0.3 / 0.6 / 1.0 |
| event_confirmation | float | 0.0 / 0.5 / 1.0 |
| product_overlap | float | 0.0–1.0 |
| revenue_estimate | text | e.g. "$8B+" |
| qualification_rationale | text | GPT explanation |
| discovery_confidence | float | How confident discovery was |
| updated_at | timestamptz | Last enrichment time |

### `contacts` table
| Column | Type | Description |
|---|---|---|
| id | uuid | Primary key |
| lead_id | uuid | FK → leads.id |
| buyer_type | text | "technical" or "business" |
| name | text | Full name |
| title | text | Job title |
| linkedin_url | text | LinkedIn profile URL |
| relevance | text | Why this person is relevant |
| outreach_subject | text | Generated email subject (editable) |
| outreach_body | text | Generated email body (editable) |
| created_at | timestamptz | When contact was found |

### `settings` table
| Column | Type | Description |
|---|---|---|
| key | text | Primary key (e.g. `clay_api_key`) |
| value | text | API key value |
| updated_at | timestamptz | Last updated |

Used by the admin panel to store integration API keys (LinkedIn Sales Navigator, Clay, Apollo.io).

---

## 8. API (`api.py`)

Base URL: `https://web-production-be2c1.up.railway.app`

| Method | Endpoint | Description |
|---|---|---|
| GET | `/leads` | All leads with nested contacts, ordered by ICP score |
| POST | `/contacts/{id}/outreach` | Generate outreach email on-demand (cached after first call) |
| PATCH | `/contacts/{id}/outreach` | Save manually edited subject/body |
| POST | `/pipeline/run` | Trigger full pipeline run in background thread |
| GET | `/pipeline/status` | Returns `{"running": true/false}` |
| GET | `/integrations` | Returns which providers are connected (boolean flags) |
| POST | `/integrations` | Connect a provider (`{"provider": "clay", "api_key": "..."}`) |
| DELETE | `/integrations/{provider}` | Disconnect a provider |

**CORS:** Allows all origins by default (`FRONTEND_URL=*`). Set `FRONTEND_URL` env var to lock to a specific domain.

---

## 9. Dashboard (`dashboard/`)

Built with **React + TypeScript + Vite + Tailwind CSS**. Deployed on Vercel at `lilyagent.vercel.app`.

### Components:
- **`App.tsx`** — Root layout, filter bar (event selector, ICP score slider, buyer type), lead table, pipeline cadence indicator ("Agent runs every 2 days")
- **`LeadsTable.tsx`** — Lead rows, expandable to show contacts per company
- **`OutreachModal.tsx`** — Contact info + editable outreach email (subject input + body textarea). Auto-saves edits to DB. Send button offers: Copy to clipboard, Open in Gmail (pre-fills compose), greyed CRM options (V2)
- **`AdminPage.tsx`** — Hidden admin view at `/admin-harshit`. Not linked in the sales rep UI. Shows integrations panel for connecting LinkedIn/Clay/Apollo API keys
- **`IntegrationsPage.tsx`** — Provider cards for LinkedIn Sales Navigator, Clay, Apollo.io. Connect/disconnect with API key input
- **`useLeads.ts`** — Hook that fetches `/leads`, groups companies appearing in multiple events into single rows, deduplicates contacts by linkedin_url

### Routes:
- `/` → Sales rep dashboard (leads, filters, outreach)
- `/admin-harshit` → Admin integrations panel (hidden, not linked)

### Environment variables (Vercel):
```
VITE_API_URL = https://web-production-be2c1.up.railway.app
```

---

## 10. Pipeline Smart Mode (Idempotency)

The pipeline is designed to run on a schedule without wasting API calls or money.

```
Scheduled run (all data fresh in DB):     ~$0.00
Full run from scratch (new events cycle): ~$2–5
```

Before each step, the pipeline checks Supabase:

| Step | Skipped when |
|---|---|
| ResearchAgent | Events in DB newer than 7 days |
| DiscoveryAgent | Event already has companies in DB |
| EnrichmentAgent | Company already scored in DB (within 30 days, score > 0) |
| StakeholderAgent | Lead already has contacts (within 14 days) |
| OutreachAgent | Skipped entirely — on-demand only |

Use `python3 main.py --fresh` to force a full re-run ignoring all checkpoints.

---

## 11. Environment Variables

### Railway (API server) — required:
```
OPENAI_API_KEY       = sk-proj-...
SERPER_API_KEY       = ...
SUPABASE_URL         = https://cmcvvysraogmwurkhowf.supabase.co
SUPABASE_SERVICE_KEY = eyJhbGci... (service_role JWT)
FRONTEND_URL         = * (or specific Vercel URL to lock CORS)
```

### Railway — contact enrichment providers (optional):
```
LINKEDIN_SALES_NAV_TOKEN = AQV...   # LinkedIn Sales Navigator API (priority 1)
CLAY_API_KEY             = clay_... # Clay people search (priority 2)
APOLLO_API_KEY           = ...      # Apollo.io free tier: 50 credits/mo (priority 3)
```
No code changes needed — set the key, redeploy, next pipeline run uses that provider.

### Vercel (Dashboard):
```
VITE_API_URL = https://web-production-be2c1.up.railway.app
```

---

## 12. Running Locally

```bash
# Clone and set up
git clone https://github.com/harshitshuklaa9/lily-agent-leads
cd lily-agent-leads
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Add .env file with all API keys
cp .env.example .env

# Run full pipeline
python3 main.py

# Run only up to enrichment step
python3 main.py --step enrich

# Force full re-run ignoring DB cache
python3 main.py --fresh

# Run API server
uvicorn api:app --reload

# Run dashboard (separate terminal)
cd dashboard && npm install && npm run dev
```

---

## 13. Adapting for a Different Industry

Only `config.json` needs to change. No agent code modifications required.

1. Update `seller` — your company, product, value props
2. Update `icp` — who you're targeting, revenue minimum, score threshold
3. Update `research.seed_events` — starting trade shows for your industry
4. Update `research.industry.verticals` and `buyer_keywords` — ICP signals
5. Update `stakeholders` — which titles to search for
6. Run `python3 main.py --fresh`

---

*Built April 2026. Pipeline: Python 3.10 + OpenAI + Playwright + Supabase. Dashboard: React + TypeScript + Tailwind + Vercel.*
